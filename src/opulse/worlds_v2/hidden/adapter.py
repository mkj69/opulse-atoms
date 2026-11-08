"""World-local, capability-scoped verification of public-value observations."""
from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import _CHECKERS, Library, PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence

from . import hosts


class HiddenLibrary(Library):
    agent = "receiver"

    def __init__(self, world, atoms, agent="receiver"):
        super().__init__(world, atoms)
        if agent not in ("receiver", "judge"):
            raise ValueError("unknown capability")
        self.agent = agent

    def scope(self):
        scope = super().scope()
        if self.agent == "receiver":
            scope.atoms.pop("signal", None)
        for definition in self.records().values():
            if definition.kind == "observation" and definition.origin == "invented" and definition.status in (
                "callable", "verified", "promoted"):
                scope.defns[definition.name] = kernel.Defn(
                    definition.name, definition.spec.reads, definition.body,
                    "observation", definition.layer)
        if self.agent == "judge":
            scope.atoms["judge"] = kernel.Atom("judge", 2, hosts.judge, kind="observation")
        return scope

    def learner_view(self, truth):
        return hosts.receiver(truth)

    def judge_view(self, truth):
        return truth

    def run(self, name, args, fuel=None, trace=False):
        def invalid(value):
            if isinstance(value, hosts.Card):
                return not hosts.valid(value)
            if isinstance(value, (tuple, list)):
                return any(invalid(child) for child in value)
            return False

        if any(invalid(arg) for arg in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        return super().run(name, args, fuel=fuel, trace=trace)

    def check(self, name):
        definition = self.get(name)
        if definition.kind not in ("observation",) and name not in ("value", "optimize"):
            return super().check(name)
        def resolve(reference):
            if reference.startswith(("Belief.", "Policy.")):
                return replace(self.get(reference.split(".")[0]), name=reference)
            return self._definitions.get(reference)

        problems = check_definition(definition, self.world, resolve)
        problems = [problem for problem in problems if not (
            ("expected any" in problem or "got any" in problem)
            and problem.split(" ")[0] in ("empty", "head", "tail", "prepend", "reverse", "size", "step_lamp", "eq"))
            and not ("expected Lamp, got str" in problem or "expected Mode, got str" in problem)]
        if definition.kind != "observation":
            if definition.kind in _CHECKERS:
                problems.extend(_CHECKERS[definition.kind](definition, self))
            if problems:
                raise PipelineError(problems)
            return self._advance(name, "checked")
        if definition.spec.reads not in (("view",), ("belief",), ("policy",)):
            problems.append("observation requires one public input")
        if any(isinstance(part, nodes.Call) and part.fn in ("signal", "judge", "receiver")
               for part in nodes.walk(definition.body)):
            problems.append("observation reads sealed truth")
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        definition = self.get(name)
        if definition.kind != "observation":
            return super().make_callable(name, sample)
        if definition.status != "checked" or not sample:
            raise PipelineError("observation needs checked status and public samples")
        scope = self.scope().extend([kernel.Defn(name, definition.spec.reads, definition.body,
                                                  "observation", definition.layer)])
        runs = [kernel.call(name, args, scope) for args in sample]
        if any(isinstance(run.outcome, Unknown) for run in runs):
            raise PipelineError("observation sample exhausted resources")
        self._steps[name] = [run.steps for run in runs]
        return self._advance(name, "callable")

    def verify(self, name, request):
        definition = self.get(name)
        if definition.kind != "observation":
            return super().verify(name, request)
        if definition.status != "callable" or request.scope.get("size") != len(request.domain):
            raise PipelineError("invalid observation verification")
        steps = []
        scope = self.scope()
        domain = deepcopy(request.domain)
        for args in domain:
            before = deepcopy(args)
            run = self.run(name, deepcopy(args), trace=True)
            expected = request.reference(*deepcopy(args))
            if run.outcome != Ok(expected) or any(
                part.name in ("signal", "judge", "receiver") for part in _walk_trace(run.trace)
            ):
                raise PipelineError(f"public observation counterexample {args!r}: {run.outcome!r}")
            if args != before:
                raise PipelineError(f"observation changed public facts: {args!r}")
            public_history = args[0].fields[0].fields if name == "lamps" else ()
            history = tuple(step.fields for step in public_history)
            red = hosts.state("R", history)
            blue = hosts.state("B", history)
            if self.learner_view(red) != self.learner_view(blue):
                raise PipelineError(f"observation paired views differ: {args!r}")
            paired_args = ((self.learner_view(red),) if name == "lamps" else args)
            other_args = ((self.learner_view(blue),) if name == "lamps" else args)
            if name == "lamps" and paired_args != args:
                raise PipelineError(f"observation paired view is outside recorded domain: {args!r}")
            if not outcome_equal(self.run(name, paired_args).outcome, self.run(name, other_args).outcome):
                raise PipelineError(f"observation non_interference counterexample: {args!r}")
            unfolded = kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)), scope)
            inline_run = kernel.evaluate(unfolded, scope=scope, dialect=self.dialect)
            if not outcome_equal(run.outcome, inline_run.outcome) or run.steps != inline_run.steps:
                raise PipelineError(f"observation unfold_equivalence counterexample: {args!r}")
            steps.append(run.steps)
        checks = ("dependency", "facts_unchanged", "non_interference", "reference", "unfold_equivalence")
        self._steps[name] = steps
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, Evidence(
            request.method, dict(request.scope), request.seed, checks,
            self.world.world_hash(), self._deps_hash(name)), domain))
        return self._advance(name, "verified")


def _walk_trace(trace):
    yield trace
    for child in trace.children:
        yield from _walk_trace(child)
