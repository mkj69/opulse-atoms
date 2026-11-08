"""Sealed-world observation hook; all other kinds use the core pipeline."""
from dataclasses import replace
from itertools import combinations

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import _CHECKERS, Library, PipelineError, _ensure_kind
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence

from . import deep_hosts as hosts


class ShadowsLibrary(Library):
    agent = "learner"

    def scope(self):
        scope = super().scope()
        fast_candidates = getattr(self, "_fast_candidates", None)
        if fast_candidates is not None:
            scope.fast_paths["Candidates.make"] = fast_candidates
        fast_plan = getattr(self, "_fast_plan", None)
        if fast_plan is not None:
            scope.fast_paths["plan"] = fast_plan
        return scope

    def _required_probes(self, name, seen=None):
        seen = seen or set()
        if name in seen:
            return set()
        seen.add(name)
        probes = {probe["name"] for probe in self.world.observation["probes"]}
        if name in probes:
            return {name}
        if name in self.definitions:
            definition = self.get(name)
            direct = {part.value.name for part in nodes.walk(definition.body)
                      if isinstance(part, nodes.Lit) and isinstance(part.value, kernel.FnRef)
                      and part.value.name in probes} if isinstance(definition.body, nodes.NODE_TYPES) else set()
            if name in ("best_probe", "plan"):
                direct.update(("front", "diag", "anti"))
            return direct | set().union(*(self._required_probes(dep, seen) for dep in definition.depends_on))
        return set()

    def run(self, name, args, fuel=None, trace=False):
        if any(not hosts.safe_value(value) for value in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        if name == "plan" and tuple(args[:3]) != tuple(kernel.FnRef(probe) for probe in ("front", "diag", "anti")):
            return kernel.Run(Bottom("probe_domain"), 0, 0, None)
        granted = set(self.world.observation["capabilities"][self.agent]["probes"])
        needed = self._required_probes(name)
        needed.update(value.name for value in args if isinstance(value, kernel.FnRef)
                      and value.name in {probe["name"] for probe in self.world.observation["probes"]})
        if not needed <= granted:
            return kernel.Run(Bottom("permission"), 0, 0, None)
        token = hosts.validated_run.set(True)
        try:
            return super().run(name, args, fuel, trace)
        finally:
            hosts.validated_run.reset(token)

    def check(self, name):
        definition = self.get(name)
        if name == "ink":
            return super().check(name)
        def resolve(dependency):
            target = self.definitions.get(dependency) or self.scope().resolve(dependency)
            parent = dependency.split(".", 1)[0]
            if parent in self.definitions and self.get(parent).kind == "object" and target is not None:
                return replace(target, layer=self.get(parent).layer)
            return target
        problems = check_definition(definition, self.world,
                                    resolve)
        if definition.kind != "observation":
            _ensure_kind(definition.kind)
            if checker := _CHECKERS.get(definition.kind):
                problems.extend(checker(definition, self))
            problems = [problem for problem in problems if not problem.startswith(
                ("same argument ", "size argument ", "diag argument ", "snoc argument ",
                 "within_mask argument ", "matches argument "))]
            if problems:
                raise PipelineError(problems)
            return self._advance(name, "checked")
        problems = [problem for problem in problems if not problem.startswith(
            ("same argument ", "size argument ", "diag argument ", "snoc argument "))]
        if definition.body != definition.spec.body:
            problems.append("observation body differs from specification")
        probes = {probe["name"] for probe in self.world.observation["probes"]}
        if not (self._required_probes(name) <= set(definition.spec.reads) <= probes):
            problems.append("observation reads undeclared probes")
        if not set(definition.spec.reads) <= set(self.world.observation["capabilities"][self.agent]["probes"]):
            problems.append("probe not granted")
        operations = {operation.name: operation for operation in self.world.operations}
        checked = set()
        def inspect(current):
            if current in checked:
                return
            checked.add(current)
            operation = operations.get(current)
            if operation is not None and current not in probes and current != "snoc" and (
                operation.role == "act" or any(edge.sort == self.world.observation["truth"]
                                                  for edge in operation.inputs)
            ):
                problems.append("observation reads or changes sealed truth outside probes")
            dependent = self.definitions.get(current)
            if dependent is not None and dependent.origin == "invented":
                for required in dependent.depends_on:
                    inspect(required)
        inspect(name)
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, samples):
        definition = self.get(name)
        if definition.kind != "observation" or name == "ink":
            return super().make_callable(name, samples)
        if definition.status != "checked" or not samples:
            raise PipelineError("observation needs checked status and samples")
        scope = self.scope().extend([kernel.Defn(name, self._params(definition), definition.body,
                                                definition.kind, definition.layer)])
        for args in samples:
            if isinstance(kernel.call(name, args, scope).outcome, Unknown):
                raise PipelineError("observation sample exhausted fuel")
        return self._advance(name, "callable")

    def verify(self, name, request):
        definition = self.get(name)
        if definition.kind != "observation" or name == "ink":
            return super().verify(name, request)
        if definition.status != "callable" or not request.domain or request.reference is None:
            raise PipelineError("observation needs a reference and a checked family")
        steps = []
        outcomes = []
        observations = []
        truth_sort = self.world.observation["truth"]
        granted = self.world.observation["capabilities"][self.agent]["probes"]
        probes = tuple(granted if granted != "all" else
                       (probe["name"] for probe in self.world.observation["probes"]))
        if not self._required_probes(name) <= set(definition.spec.reads) <= set(probes):
            raise PipelineError("dependency: observation reads outside granted probes")
        for args in request.domain:
            before = tuple((arg.sort, arg.tag, arg.fields) if isinstance(arg, Card) else arg for arg in args)
            actual = self.run(name, args)
            expected = request.reference(*args)
            expected = expected if isinstance(expected, (Ok, Bottom, Unknown)) else Ok(expected)
            if not outcome_equal(actual.outcome, expected):
                raise PipelineError(f"observation reference counterexample: {args!r}")
            unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),
                                                     self.scope()), scope=self.scope())
            if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
                raise PipelineError("observation unfold counterexample")
            steps.append(actual.steps)
            outcomes.append(actual.outcome)
            if before != tuple((arg.sort, arg.tag, arg.fields) if isinstance(arg, Card) else arg for arg in args):
                raise PipelineError("facts_unchanged: observation modified the state")
            observations.append(tuple(self.run(probe, args).outcome for probe in probes)
                                if len(args) == 1 and getattr(args[0], "sort", None) == truth_sort else args)
        for first, second in combinations(range(len(outcomes)), 2):
            first_args, second_args = request.domain[first], request.domain[second]
            indistinguishable = (all(outcome_equal(left, right) for left, right in zip(
                observations[first], observations[second])) if len(first_args) == len(second_args) == 1 and
                getattr(first_args[0], "sort", None) == getattr(second_args[0], "sort", None) ==
                truth_sort else first_args == second_args)
            if indistinguishable and not outcome_equal(outcomes[first], outcomes[second]):
                raise PipelineError("non_interference: indistinguishable states differ")
        evidence = Evidence(request.method, dict(request.scope), request.seed,
                            ("reference", "unfold_equivalence", "dependency", "facts_unchanged", "non_interference"),
                            self.world.world_hash(), self._deps_hash(name))
        self._steps[name] = steps
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, evidence, request.domain))
        return self._advance(name, "verified")
