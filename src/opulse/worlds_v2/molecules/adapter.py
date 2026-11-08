"""World-parametric observation bridge for the robot-specific core observer."""
from dataclasses import replace

from opulse.atoms import nodes
from opulse.atoms.check import all_dependencies, check_definition
from opulse.atoms.combinators import check_combinator
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import check_object
from opulse.atoms.spec import Evidence
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence


class MoleculeLibrary(Library):
    """Only observations need a bridge: the core assumes robot-specific zero-arg probes."""

    def _resolve(self, name):
        definition = self._definitions.get(name)
        if definition is not None and definition.origin == "invented":
            return definition
        return self.scope().resolve(name)

    def check(self, name):
        definition = self.get(name)
        problems = check_definition(definition, self.world, self._resolve)
        if definition.kind == "object":
            problems += check_object(definition, self)
        if definition.kind == "combinator":
            problems += check_combinator(definition, self)
        if definition.kind == "observation":
            for item in nodes.walk(definition.body):
                if isinstance(item, nodes.Call) and item.fn in {"attach", "link", "graph_labels",
                                                           "graph_edges", "graph_hydrogen", "relabel",
                                                           "graph_key", "graph_valid", "normalize"}:
                    problems.append(f"observation reads truth without a probe: {item.fn}")
                if isinstance(item, nodes.Call) and item.fn in {"atoms", "count", "group_sizes"} and item.fn not in definition.spec.reads:
                    problems.append(f"ungranted probe: {item.fn}")
        if definition.body is not None:
            layers = []
            for dependency in all_dependencies(definition) - set(getattr(definition.spec, "op_params", ())):
                parent = dependency.split(".", 1)[0]
                target = self._definitions.get(dependency) or self._definitions.get(parent)
                layers.append(target.layer if target is not None else 0)
            expected = 1 + max(layers, default=0)
            if expected != definition.layer:
                problems.append(f"computed layer must be {expected}, got {definition.layer}")
        if problems:
            raise PipelineError([name, *problems])
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        if self.get(name).kind != "observation":
            return super().make_callable(name, sample)
        if self.get(name).status != "checked" or not sample:
            raise PipelineError("observation needs checked status and a nonempty sample")
        self._advance(name, "callable")
        for args in sample:
            if isinstance(self.run(name, args).outcome, Unknown):
                raise PipelineError("observation sample exhausted fuel")
        return self.get(name)

    def verify(self, name, request):
        if self.get(name).kind != "observation":
            return super().verify(name, request)
        definition = self.get(name)
        if definition.status != "callable" or len(request.domain) != request.scope.get("size") or not request.domain:
            raise PipelineError("invalid observation verification scope")
        steps = []
        observed = {}
        for args in request.domain:
            before = tuple(args)
            actual = self.run(name, args)
            if isinstance(actual.outcome, Unknown) or tuple(args) != before:
                raise PipelineError("observation exhausted resources or changed facts")
            if name == "ambiguity":
                view = tuple(args)
            else:
                from . import hosts

                view = hosts.atoms(args[0].fields[0])
            previous = observed.get(view)
            if previous is not None and not outcome_equal(previous, actual.outcome):
                raise PipelineError("non_interference: identical granted view has different outcomes")
            observed[view] = actual.outcome
            if request.reference is not None:
                expected = request.reference(*args)
                if not outcome_equal(actual.outcome, expected if isinstance(expected, (Ok, Bottom, Unknown)) else Ok(expected)):
                    raise PipelineError(f"observation reference mismatch: {args!r}")
            steps.append(actual.steps)
        checks = ("dependency", "facts_unchanged", "non_interference")
        if request.reference is not None:
            checks += ("reference",)
        evidence = Evidence(request.method, dict(request.scope), request.seed, checks,
                            self.world.world_hash(), self._deps_hash(name))
        self._steps[name] = steps
        self._definitions[name] = replace(definition, evidence=bound_evidence(self, name, evidence, request.domain))
        return self._advance(name, "verified")
