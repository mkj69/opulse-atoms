"""Local adapters for public-word observations and mixed-arity algebra slots."""
from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence

from .hosts import valid_card


class GrammarLibrary(Library):
    def run(self, name, args, fuel=None, trace=False, expression=None):
        if any(not self._valid_input(arg) for arg in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None, 0)
        if expression is not None:
            def valid_expression(node):
                if isinstance(node, nodes.Lit):
                    return (self._valid_input(node.value) and
                            not (isinstance(node.value, kernel.FnRef) and
                                 node.value.name in self.sealed_names()))
                return (isinstance(node, nodes.Call) and node.fn not in self.sealed_names() and
                        all(valid_expression(item) for item in node.args))

            if (not isinstance(expression, nodes.Call) or expression.fn != name or
                    not valid_expression(expression)):
                return kernel.Run(Bottom("invalid"), 0, 0, None, 0)
            return kernel.evaluate(expression, scope=self.scope(), limits=kernel.Limits(fuel=fuel),
                                   trace=trace, dialect=self.dialect)
        return super().run(name, args, fuel=fuel, trace=trace)

    def _valid_input(self, value):
        if isinstance(value, (tuple, list)):
            return all(self._valid_input(item) for item in value)
        if isinstance(value, dict):
            return all(self._valid_input(item) for pair in value.items() for item in pair)
        if isinstance(value, (set, frozenset)):
            return all(self._valid_input(item) for item in value)
        if isinstance(value, Card):
            return valid_card(value)
        return True

    def _params(self, definition):
        if definition.kind == "observation" and definition.origin == "invented":
            return ("w",)
        return super()._params(definition)

    def check(self, name):
        definition = self.get(name)
        if definition.kind not in ("observation", "operation", "combinator"):
            return super().check(name)
        problems = check_definition(definition, self.world, self._definitions.get)
        generated = ("ExprTree.make", "ExprTree.base", "Ambiguity.make", "Ambiguity.base")
        problems = [problem for problem in problems if not (
            "expected any, got " in problem or problem.endswith("got any") or
            any(problem == f"unresolved call: {item}" for item in generated))]
        from opulse.atoms.objects import check_object

        object_problems = check_object(definition, self)
        if any(problem == "fold: private sealed operation ExprTree.base" for problem in object_problems):
            from .story import definitions

            trusted_fold = next(item for item in definitions() if item.name == "fold")
            recorded_fold = self._definitions.get("fold")
            if (recorded_fold is not None and recorded_fold.body == trusted_fold.body and
                    recorded_fold.spec == trusted_fold.spec):
                object_problems = [problem for problem in object_problems
                                   if problem != "fold: private sealed operation ExprTree.base"]
        problems += object_problems
        if definition.kind == "observation":
            granted = {probe["name"] for probe in self.world.observation["probes"]}
            for reference in nodes.references(definition.body):
                if reference in granted and reference not in definition.spec.reads:
                    problems.append(f"probe {reference} is not granted")
            if definition.spec.body != definition.body:
                problems.append("observation body does not match spec")
        if definition.kind == "combinator":
            from opulse.atoms.combinators import check_combinator

            problems += check_combinator(definition, self)
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, samples):
        definition = self.get(name)
        if definition.kind != "observation":
            return super().make_callable(name, samples)
        if definition.status != "checked" or not samples:
            raise PipelineError("observation requires checked status and samples")
        scope = self.scope().extend([kernel.Defn(name, ("w",), definition.body, "observation", definition.layer)])
        for args in samples:
            if isinstance(kernel.call(name, args, scope).outcome, Unknown):
                raise PipelineError("unknown observation sample")
        return self._advance(name, "callable")

    def verify(self, name, request):
        definition = self.get(name)
        if definition.kind != "observation":
            return super().verify(name, request)
        if (definition.status != "callable" or request.scope.get("size") != len(request.domain) or
                not request.domain or request.reference is None):
            raise PipelineError("observation needs a real, referenced family")
        steps = []
        seen = []
        for args in request.domain:
            if (len(args) != 1 or not isinstance(args[0], Card) or
                    args[0].sort != "Word" or not valid_card(args[0])):
                raise PipelineError("observation family requires valid public words")
            granted_view = args[0].fields
            frozen = deepcopy(args)
            actual = self.run(name, args, fuel=1_000_000)
            expected = request.reference(*args)
            expected = expected if isinstance(expected, (Ok, Unknown)) else Ok(expected)
            if (not outcome_equal(actual.outcome, expected) or args != frozen or
                    isinstance(actual.outcome, Unknown)):
                raise PipelineError(f"observation counterexample {args!r}: {actual.outcome!r} != {expected!r}")
            for previous_view, previous_outcome in seen:
                if granted_view == previous_view and not outcome_equal(actual.outcome, previous_outcome):
                    raise PipelineError(f"observation non-interference counterexample: {granted_view!r}")
            seen.append((granted_view, actual.outcome))
            steps.append(actual.steps)
        return record(self, name, request, ("dependency", "facts_unchanged", "non_interference", "reference"), steps)


def record(library, name, request, checks, steps):
    definition = library.get(name)
    library._steps[name] = steps
    library._definitions[name] = replace(definition, evidence=bound_evidence(library, name, Evidence(
        request.method, dict(request.scope), request.seed, tuple(checks),
        library.world.world_hash(), library._deps_hash(name)), request.domain))
    return library._advance(name, "verified")
