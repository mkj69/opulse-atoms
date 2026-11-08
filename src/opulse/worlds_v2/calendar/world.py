"""Locked layer-zero calendar and public day-step unfold rule."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.check import check_definition
from opulse.atoms.library import _CHECKERS, Library, PipelineError, _ensure_kind
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Ok, outcome_equal
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.export_util import bound_evidence

from . import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/calendar@1.json"


def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms() -> list[kernel.Atom]:
    implementations = {"next_date": hosts.next_date, "year_of": hosts.year_of,
                       "month_of": hosts.month_of, "day_of": hosts.day_of,
                       "equal_int": hosts.equal_int, "less_int": hosts.less_int,
                       "decrement": hosts.decrement, "fail": hosts.fail,
                       "eq": hosts.eq, "lt": hosts.lt, "le": hosts.le,
                       "add": hosts.add, "subtract": hosts.subtract,
                       "indicator": hosts.indicator, "date": hosts.date,
                       "pair": hosts.pair, "first": hosts.first, "second": hosts.second,
                       "some": hosts.some, "optional_date": hosts.optional_date}
    world = decl()
    return ([kernel.Atom(op.name, len(op.inputs), implementations[op.name], op.cost, strict=op.strict)
             for op in world.operations] +
            [kernel.Atom(probe["name"], 1, getattr(hosts, probe["name"]), 1, "observation")
             for probe in world.observation["probes"]])


class CalendarLibrary(Library):
    def check(self, name):
        if name != "open_day":
            return super().check(name)
        definition = self.get(name)
        if definition.status != "written":
            raise PipelineError("check requires written status")
        scope = self.scope()
        problems = check_definition(definition, self.world,
                                    lambda dependency: self.definitions.get(dependency) or scope.resolve(dependency))
        _ensure_kind(definition.kind)
        checker = _CHECKERS.get(definition.kind)
        if checker:
            reconstructed_date_operations = {"holiday_match", "week_later", "next_date",
                                             *(f"weekday_is_{weekday}" for weekday in range(7))}
            allowed = {f"operation {operation} may read or change truth"
                       for operation in reconstructed_date_operations}
            problems.extend(problem for problem in checker(definition, self)
                            if problem not in allowed)
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        if name == "open_day":
            definition = self.get(name)
            scope = self.scope().extend((kernel.Defn(name, (definition.spec.subject,),
                                                   definition.body, "observation", definition.layer),))
            for args in sample:
                if not isinstance(kernel.call(name, args, scope).outcome, Ok):
                    raise PipelineError("open_day sample failed")
            return self._advance(name, "callable")
        return super().make_callable(name, sample)

    def verify(self, name, request):
        if name != "open_day":
            return super().verify(name, request)
        from .deep import reference_for

        if request.scope.get("size") != len(request.domain) or len(request.domain) < 50:
            raise PipelineError("open_day requires at least 50 checked states")
        steps = []
        for args in request.domain:
            state = args[0]
            snapshot = repr(state)
            readings = tuple(self.run(probe, (state,)).outcome
                             for probe in self.get(name).spec.reads)
            if not all(isinstance(reading, Ok) for reading in readings):
                raise PipelineError("open_day needs all granted readings")
            if hosts.to_card(*(self.run(probe, (state,)).outcome.value
                               for probe in ("year_of", "month_of", "day_of"))) != state:
                raise PipelineError("probes do not reconstruct the observed date")
            observed = self.run(name, args)
            if not outcome_equal(observed.outcome, Ok(reference_for(name)(args[0]))):
                raise PipelineError(f"open_day counterexample: {args!r}")
            if repr(state) != snapshot:
                raise PipelineError("open_day mutated its truth state")
            steps.append(observed.steps)
        definition = self.get(name)
        self._steps[name] = steps
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, Evidence(
            request.method, dict(request.scope), request.seed,
            ("dependency", "facts_unchanged", "non_interference", "reference"),
            self.world.world_hash(), self._deps_hash(name), self.content_hash(name)), request.domain))
        return self._advance(name, "verified")

def new_library() -> Library:
    return CalendarLibrary(decl(), atoms())
