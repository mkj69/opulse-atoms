"""Bridge public multi-argument text observations to the single-state core API."""

from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import check_definition
from opulse.atoms.library import (
    Library,
    PipelineError,
    _operation_verifier,
)
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence


class TextLibrary(Library):
    def __init__(self, world, atoms):
        super().__init__(world, atoms)
        self._public_observations = {"starts": ("text",), "parses": ("text", "dictionary"),
                                     "best": ("text", "dictionary"),
                                     "optimal_count": ("text", "dictionary")}

    def _params(self, definition):
        if definition.name in self._public_observations:
            return self._public_observations[definition.name]
        return super()._params(definition)

    def check(self, name):
        definition = self.get(name)
        if definition.kind == "observation" and name in self._public_observations:
            if definition.status != "written":
                raise PipelineError("check requires written status")
            scope = self.scope()
            problems = [problem for problem in check_definition(definition, self.world,
                                                                 lambda target: self._definitions.get(target) or
                                                                 scope.resolve(target))
                        if not (" argument " in problem and any(
                            marker in problem for marker in ("expected any", "got any",
                                                            "expected unknown", "got unknown")))]
            if definition.body != definition.spec.body or definition.spec.reads != ("chars",):
                problems.append("observation must use declared public probe")
            if name in ("parses", "best", "optimal_count") and not any(
                    isinstance(item, n.Call) and item.fn == "public_text" for item in n.walk(definition.body)):
                problems.append("observation must reconstruct text from the granted chars probe")
            if problems:
                raise PipelineError(problems)
            return self._advance(name, "checked")
        return super().check(name)

    def make_callable(self, name, sample):
        if name not in self._public_observations:
            return super().make_callable(name, sample)
        definition = self.get(name)
        if definition.status != "checked" or not sample:
            raise PipelineError("observation needs a nonempty sample")
        scope = self.scope().extend([kernel.Defn(name, self._params(definition), definition.body,
                                                 "observation", definition.layer)])
        for args in sample:
            if isinstance(kernel.call(name, args, scope).outcome, Unknown):
                raise PipelineError("observation sample exhausted resources")
        return self._advance(name, "callable")

    def verify(self, name, request):
        if name not in self._public_observations:
            return super().verify(name, request)
        definition = self.get(name)
        if definition.status != "callable" or len(request.domain) != request.scope.get("size"):
            raise PipelineError("observation verification requires a bounded domain")
        result = _operation_verifier(definition, self, request)
        if not result.ok:
            raise PipelineError(result.problems)
        before = deepcopy(request.domain)
        observed = [(self.run("chars", (args[0],)).outcome, args[1:]) for args in request.domain]
        for first in range(len(request.domain)):
            for second in range(first + 1, len(request.domain)):
                if (outcome_equal(observed[first][0], observed[second][0]) and
                        observed[first][1] == observed[second][1] and
                        not outcome_equal(self.run(name, request.domain[first]).outcome,
                                          self.run(name, request.domain[second]).outcome)):
                    raise PipelineError("non_interference: indistinguishable public inputs differ")
        if request.domain != before:
            raise PipelineError("facts_unchanged: observation changed inputs")
        evidence = Evidence(request.method, dict(request.scope), request.seed,
                            (*result.checks, "dependency", "facts_unchanged", "non_interference"),
                            self.world.world_hash(), self._deps_hash(name), self.content_hash(name))
        self._steps[name] = result.steps
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, evidence, request.domain))
        return self._advance(name, "verified")
