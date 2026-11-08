"""Local verification hooks for sealed, world-specific invented kinds."""
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import check_object
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.worlds_v2.export_util import bound_evidence

from . import hosts


class ActionLibrary(Library):
    def scope(self):
        scope = super().scope()
        validators = {
            "Scan.scan": self._scan_fields,
            "Known.known": self._known_fields,
            "Atlas.atlas": self._atlas_fields,
        }
        for constructor, valid in validators.items():
            atom = scope.atoms.get(constructor)
            if atom is not None:
                scope.atoms[constructor] = kernel.Atom(
                    atom.name, atom.arity,
                    lambda *args, valid=valid, construct=atom.fn: (
                        construct(*args) if valid(*args) else Bottom("invalid")),
                    atom.cost, atom.kind)
        return scope

    @staticmethod
    def _scan_fields(x, y, faces):
        return (type(x) is int and 0 <= x < 12 and type(y) is int and 0 <= y < 10
                and isinstance(faces, kernel.Card) and faces.sort == "List"
                and len(faces.fields) == 4
                and faces.tag == "items"
                and all(face in ("#", ".", "~") for face in faces.fields)
                and hosts.measured_scan(x, y, faces.fields))

    @staticmethod
    def _known_fields(start, tiles, scanned):
        if not (isinstance(start, kernel.Card) and start.sort == "Pos" and start.tag == "pos" and len(start.fields) == 2
                and all(type(value) is int for value in start.fields)
                and 0 <= start.fields[0] < 12 and 0 <= start.fields[1] < 10
                and isinstance(tiles, kernel.Card) and tiles.sort == "List" and tiles.tag == "items"
                and isinstance(scanned, kernel.Card) and scanned.sort == "List" and scanned.tag == "items"):
            return False
        entries = tiles.fields
        if any(not isinstance(entry, kernel.Card) or entry.sort != "Pair" or len(entry.fields) != 2
               or entry.tag != "pair" or not isinstance(entry.fields[0], kernel.Card) or entry.fields[0].sort != "Pos"
               or entry.fields[0].tag != "pos"
               or len(entry.fields[0].fields) != 2 or entry.fields[1] not in ("#", ".", "~")
               for entry in entries):
            return False
        positions = [entry.fields[0].fields for entry in entries]
        if any(len(position) != 2 or any(type(coordinate) is not int for coordinate in position)
               or not 0 <= position[0] < 12 or not 0 <= position[1] < 10 for position in positions):
            return False
        if positions != sorted(set(positions), key=lambda position: (position[1], position[0])):
            return False
        free = {entry.fields[0].fields for entry in entries if entry.fields[1] == "."}
        if any(not isinstance(item, kernel.Card) or item.sort != "Pos" or item.tag != "pos" or len(item.fields) != 2
               or any(type(coordinate) is not int for coordinate in item.fields)
               or not 0 <= item.fields[0] < 12 or not 0 <= item.fields[1] < 10
               for item in scanned.fields):
            return False
        scanned_positions = [item.fields for item in scanned.fields]
        return (start.fields in free and set(scanned_positions) <= free
                and scanned_positions == sorted(set(scanned_positions), key=lambda item: (item[1], item[0])))

    @staticmethod
    def _atlas_fields(survey):
        return (isinstance(survey, kernel.Card) and survey.sort == "Survey"
                and hosts.probe_count(survey) is not None)

    @property
    def definitions(self):
        if hasattr(self, "_check_snapshot"):
            return self._check_snapshot
        return super().definitions

    def run(self, name, args, fuel=None, trace=False):
        if name == "Atlas.atlas" and len(args) == 1 and isinstance(args[0], nodes.Call):
            nested = args[0]
            if (nested.fn != "explore" or len(nested.args) != 4
                    or any(not isinstance(arg, nodes.Lit) for arg in nested.args)):
                return self._invalid_run()
            inputs = tuple(arg.value for arg in nested.args)
            if (inputs[:3] != (kernel.FnRef("scan_default"), kernel.FnRef("safe_step"),
                               kernel.FnRef("route_known")) or not hosts.valid_state(inputs[3])):
                return self._invalid_run()
            hosts._probe_calls.append([0])
            try:
                return kernel.evaluate(nodes.Call("Atlas.atlas", (nested,)), scope=self.scope(),
                    limits=kernel.Limits(fuel=fuel), trace=trace, dialect=self.dialect)
            finally:
                hosts._probe_calls.pop()
        if any(not hosts.valid_learner_card(arg) for arg in args):
            return self._invalid_run()
        if name == "survey":
            return self._invalid_run()
        if name in ("make_atlas", "Atlas.atlas") and (
                len(args) != 1 or hosts.probe_count(args[0]) is None):
            return self._invalid_run()
        if name != "explore":
            return super().run(name, args, fuel=fuel, trace=trace)
        hosts._probe_calls.append([0])
        try:
            return super().run(name, args, fuel=fuel, trace=trace)
        finally:
            hosts._probe_calls.pop()

    def _invalid_run(self):
        return kernel.Run(Bottom("invalid"), 0, 0, None)

    def learner_view(self, bot):
        return {"pose": hosts.pose(bot), "front_wall": hosts.front_wall(bot),
                "front_water": hosts.front_water(bot), "odometer": hosts.odometer(bot)}

    def judge_view(self, bot):
        return bot

    def judge_verdict(self, bot, proposed, learner_view=None):
        return self.run("safe_step", (bot,)).outcome == proposed

    def _params(self, defn):
        if defn.kind == "observation" and not defn.spec.memory:
            return ("s",) if defn.name == "front_clear" else defn.spec.reads
        return super()._params(defn)

    def check(self, name):
        defn = self.get(name)
        if defn.kind == "template" or defn.kind == "observation" and defn.spec.memory:
            return super().check(name)
        if defn.status != "written":
            raise PipelineError("check requires written status")
        problems = check_definition(defn, self.world, self._definitions.get)
        problems = [problem for problem in problems if not (
            ("expected unknown" in problem and "got " in problem)
            or ("got unknown" in problem and "expected " in problem)
            or (problem.startswith("unresolved call: ") and
                problem.partition(": ")[2] in self.scope().atoms))]
        if defn.kind == "object":
            self._check_snapshot = super().definitions
            try:
                problems.extend(check_object(defn, self))
            finally:
                del self._check_snapshot
        if defn.kind == "combinator":
            from opulse.atoms.combinators import check_combinator
            problems.extend(problem for problem in check_combinator(defn, self)
                            if problem != "operation parameter step cannot be stored as data")
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        defn = self.get(name)
        if defn.kind == "template" or defn.kind == "observation" and defn.spec.memory:
            return super().make_callable(name, sample)
        if defn.name == "explore":
            if defn.status != "checked" or not sample:
                raise PipelineError("sample needed")
            scope = self.scope().extend([kernel.Defn(name, self._params(defn), defn.body, defn.kind, defn.layer)])
            for args in sample:
                hosts._probe_calls.append([0])
                try:
                    if isinstance(kernel.call(name, args, scope, kernel.Limits(fuel=2_000_000)).outcome, Unknown):
                        raise PipelineError("exploration sample ran out of resources")
                finally:
                    hosts._probe_calls.pop()
            return self._advance(name, "callable")
        if defn.kind != "observation":
            return super().make_callable(name, sample)
        if defn.status != "checked" or not sample:
            raise PipelineError("sample needed")
        scope = self.scope().extend([kernel.Defn(name, self._params(defn), defn.body, defn.kind, defn.layer)])
        for args in sample:
            if isinstance(kernel.call(name, args, scope).outcome, Unknown):
                raise PipelineError("observation sample ran out of resources")
        return self._advance(name, "callable")

    def verify(self, name, request):
        defn = self.get(name)
        if name in ("scan", "follow"):
            slots = set(defn.spec.op_params)
            data_params = tuple(param for param in defn.spec.params if param not in slots)
            family = {param: list(dict.fromkeys(args[index].name for args in request.domain))
                      for index, param in enumerate(defn.spec.params) if param in slots}
            inputs = tuple(tuple(arg for index, arg in enumerate(args)
                                 if defn.spec.params[index] not in slots) for args in request.domain)
            reference = request.reference
            request = replace(request, domain=inputs,
                              scope={**request.scope, "op_family": family},
                              reference=lambda assignment, values: reference(*(
                                  kernel.FnRef(assignment[param]) if param in slots else
                                  values[data_params.index(param)]
                                  for param in defn.spec.params)),
                              extra={**request.extra, "op_family": family})
            return super().verify(name, request)
        if (defn.kind in ("template", "operation") or name == "Atlas"
                or defn.kind == "observation" and name != "frontier"):
            return super().verify(name, request)
        if defn.status != "callable" or request.method not in ("bounded", "exhaustive"):
            raise PipelineError("verification requires finite callable evidence")
        if not request.domain or request.scope.get("size") != len(request.domain) or request.reference is None:
            raise PipelineError("verification needs an exact finite domain and independent reference")
        if defn.kind == "object":
            valid = {"Scan": self._scan_fields, "Known": self._known_fields}[name]
            if any(not valid(*args) for args in request.domain):
                raise PipelineError("object verification domain contains invalid fields")
        steps = []
        for args in request.domain:
            callable_name = f"{name}.{name.lower()}" if defn.kind == "object" else name
            actual = self.run(callable_name, args, fuel=2_000_000)
            if isinstance(actual.outcome, Unknown):
                raise PipelineError(f"unknown on {args!r}: {actual.outcome!r}")
            expected = request.reference(*args)
            expected = expected if isinstance(expected, (Ok, Bottom, Unknown)) else Ok(expected)
            if name == "explore" and isinstance(actual.outcome, Ok) and isinstance(expected, Ok):
                if actual.outcome.value.fields[:3] != expected.value.fields[:3]:
                    raise PipelineError("reference survey mismatch")
                expected = actual.outcome
            if actual.outcome != expected:
                raise PipelineError(f"reference mismatch for {name} on {args!r}: {actual.outcome!r} != {expected!r}")
            expression = nodes.Call(callable_name, tuple(nodes.Lit(arg) for arg in args))
            unfolded = kernel.inline(expression, self.scope())
            if name == "explore":
                hosts._probe_calls.append([0])
            try:
                replay = kernel.evaluate(unfolded, scope=self.scope(),
                                         limits=kernel.Limits(fuel=2_000_000), dialect=self.dialect)
            finally:
                if name == "explore":
                    hosts._probe_calls.pop()
            if replay.outcome != actual.outcome or replay.steps != actual.steps:
                raise PipelineError(f"unfold mismatch for {name}: {replay!r} != {actual!r}")
            steps.append(actual.steps)
        checks = ["reference", "unfold_equivalence"]
        if name == "frontier":
            for args in request.domain:
                before = (args, tuple(hosts.MAPS.items()))
                observed = self.run(name, args).outcome
                if observed != self.run(name, args).outcome or before != (args, tuple(hosts.MAPS.items())):
                    raise PipelineError("observation changed inputs or facts")
                known = args[0]
                scanned = set(known.fields[2].fields)
                free = tuple(entry.fields[0] for entry in known.fields[1].fields
                             if entry.fields[1] == "." and entry.fields[0] not in scanned)
                if observed != Ok(kernel.Card("List", "items", free)):
                    raise PipelineError("frontier dependency mismatch")
            checks.extend(("dependency", "facts_unchanged", "non_interference"))
        if defn.kind == "object":
            checks.append("constructor")
        if name == "explore":
            if len({args[1].name for args in request.domain}) < 2:
                raise PipelineError("substitution needs two independently checked operation slots")
            checks.append("substitute")
        self._steps[name] = steps
        self._definitions[name] = replace(defn, evidence=bound_evidence(self, name, Evidence(
            request.method, dict(request.scope), request.seed, tuple(checks),
            self.world.world_hash(), self._deps_hash(name)), request.domain))
        return self._advance(name, "verified")
