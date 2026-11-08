"""Kitchen library hooks for parameterized observations and tuple-backed records."""

from copy import deepcopy
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.check import all_dependencies
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import object_atoms, verify_object
from opulse.atoms.spec import Evidence, compute_layer
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal
from opulse.worlds_v2.export_util import bound_evidence

from . import depth_hosts as hosts


def _observable(value):
    if isinstance(value, Card):
        if value.sort == "State":
            return ("State", hosts.stock(value), hosts.busy(value))
        if value.sort == "Plan":
            start, slots, end = value.fields[0].fields
            return ("Plan", _observable(start), slots, _observable(end))
        return (value.sort, value.tag, tuple(_observable(item) for item in value.fields))
    if isinstance(value, tuple):
        return tuple(_observable(item) for item in value)
    return value


class KitchenLibrary(Library):
    """Keep observation probes and tuple-backed plans inside their finite scopes."""

    PRIVATE_READS = frozenset(("Plan.start", "Plan.end"))

    def _params(self, definition):
        if definition.kind == "observation" and definition.origin == "invented":
            return tuple(definition.spec.extra["params"])
        return super()._params(definition)

    def check(self, name):
        definition = self.get(name)
        legacy_tuples = {"Order", "reach", "advance_frontier", "pack_frontier", "meets", "score",
                         "filter_plans", "best", "earliest", "min_flour"}
        if definition.kind != "observation" and name not in legacy_tuples:
            return super().check(name)
        definitions = self.definitions
        if name == "Order":
            if (definition.spec.base != "OrderData" or
                    set(definition.depends_on) != nodes.references(definition.spec.valid) or
                    definition.layer != 1):
                raise PipelineError("Order refine or design layer mismatch")
            return self._advance(name, "checked")
        if definition.kind != "observation":
            references = (nodes.references(definition.body) |
                          ({"meets"} if name == "best" else set())) - set(
                              getattr(definition.spec, "op_params", ()))
            if references != set(definition.depends_on):
                raise PipelineError("operation dependencies differ from body")
            unresolved = references - set(definitions) - set(self.scope().atoms)
            if unresolved:
                raise PipelineError(f"unresolved operation dependencies: {sorted(unresolved)}")
            def layer_of(reference):
                owner = reference.split(".", 1)[0]
                return definitions[owner if owner in definitions else reference].layer
            expected = compute_layer(all_dependencies(definition) - set(
                getattr(definition.spec, "op_params", ())), layer_of)
            if definition.layer != expected:
                raise PipelineError(f"operation layer must be {expected}, got {definition.layer}")
            return self._advance(name, "checked")
        references = nodes.references(definition.body)
        problems = []
        if references - set(definitions) - set(self.scope().atoms):
            problems.append("unresolved observation dependencies")
        if definition.spec.body != definition.body or not set(definition.spec.reads) <= {"stock", "busy"}:
            problems.append("observation uses undeclared probes")
        if references != set(definition.depends_on):
            problems.append("observation dependencies differ from body")
        def layer_of(reference):
            owner = reference.split(".", 1)[0]
            return definitions[owner if owner in definitions else reference].layer
        if not problems and definition.layer != compute_layer(all_dependencies(definition), layer_of):
            problems.append("observation layer differs from dependencies")
        def inspect(node, through_probe=False):
            if isinstance(node, nodes.Call):
                if node.fn in self.PRIVATE_READS and not through_probe:
                    problems.append(f"{node.fn} may only feed a probe")
                if node.fn == "field" and node.args == (nodes.Var("q"), nodes.Lit(0)) and not through_probe:
                    problems.append("private query state may only feed a probe")
                if node.fn in ("stock", "busy") and node.fn not in definition.spec.reads:
                    problems.append(f"undeclared probe {node.fn}")
                through_probe = through_probe or node.fn in definition.spec.reads
            for child in nodes.children(node):
                if isinstance(child, nodes.NODE_TYPES):
                    inspect(child, through_probe)
        inspect(definition.body)
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def run_observation(self, name, args):
        definition = self.get(name)
        scope = self.scope().extend((kernel.Defn(name, self._params(definition),
                                                 definition.body, "observation", definition.layer),))
        return kernel.call(name, args, scope)

    def make_callable(self, name, sample):
        if self.get(name).kind != "observation":
            return super().make_callable(name, sample)
        if self.get(name).status != "checked" or not sample:
            raise PipelineError("observation requires checked examples")
        for args in sample:
            if isinstance(self.run_observation(name, args).outcome, Unknown):
                raise PipelineError("observation ran out of fuel")
        return self._advance(name, "callable")

    def verify(self, name, request):
        if self.get(name).kind == "observation":
            definition = self.get(name)
            if definition.status != "callable" or request.scope.get("size") != len(request.domain):
                raise PipelineError("observation requires a callable and exact finite scope")
            steps = []
            observations = []
            for args in request.domain:
                before = deepcopy(args)
                observed = self.run_observation(name, args)
                expected = request.reference(*args)
                expected = expected if isinstance(expected, (Ok, Bottom, Unknown)) else Ok(expected)
                if not outcome_equal(observed.outcome, expected) or before != args:
                    raise PipelineError(f"observation reference or purity mismatch: {name}: {args!r}")
                view = _observable(args)
                for prior_view, prior_outcome in observations:
                    if view == prior_view and not outcome_equal(observed.outcome, prior_outcome):
                        raise PipelineError(f"observation non-interference mismatch: {name}: {args!r}")
                observations.append((view, observed.outcome))
                steps.append(observed.steps)
            evidence = Evidence(request.method, dict(request.scope), request.seed,
                                ("dependency", "facts_unchanged", "non_interference", "reference"),
                                self.world.world_hash(), self._deps_hash(name), self.content_hash(name))
            self._definitions[name] = replace(definition, evidence=bound_evidence(
                self, name, evidence, request.domain))
            self._steps[name] = steps
            return self._advance(name, "verified")
        if name in ("Plan", "Order"):
            definition = self.get(name)
            generated = {operation.name for operation in object_atoms(definition.spec, self)}
            available = tuple(operation for operation in definition.spec.interface
                              if operation in generated)
            checked = replace(definition, spec=replace(definition.spec, interface=available))
            result = verify_object(checked, self, request)
            if not result.ok:
                raise PipelineError(result.problems)
            scope = dict(request.scope)
            scope["verified_interface"] = list(available)
            evidence = Evidence(request.method, scope, request.seed, result.checks,
                                self.world.world_hash(), self._deps_hash(name),
                                self.content_hash(name))
            self._definitions[name] = replace(definition, evidence=bound_evidence(
                self, name, evidence, request.domain))
            self._steps[name] = result.steps
            return self._advance(name, "verified")
        if name not in ("PlanData", "OrderData"):
            return super().verify(name, request)
        definition = self.get(name)
        if definition.status != "callable" or request.scope.get("size") != len(request.domain):
            raise PipelineError("record requires a callable and exact finite scope")
        steps = []
        tag = "record" if name == "PlanData" else "order"
        fields = (("start", "slots", "end") if name == "PlanData" else
                  ("bread", "cake", "dessert", "deadline"))
        for row in request.domain:
            result = self.run(name + "." + tag, row)
            if not isinstance(result.outcome, Ok):
                raise PipelineError(f"{name} constructor failed on finite family")
            for field_name, expected in zip(fields, row):
                projected = self.run(name + "." + field_name, (result.outcome.value,))
                if projected.outcome != Ok(expected):
                    raise PipelineError(f"{name} accessor roundtrip failed")
                steps.append(result.steps + projected.steps)
        evidence = Evidence(request.method, dict(request.scope), request.seed,
                            ("constructor_total", "accessor_roundtrip"),
                            self.world.world_hash(), self._deps_hash(name), self.content_hash(name))
        self._definitions[name] = replace(definition, evidence=bound_evidence(
            self, name, evidence, request.domain))
        self._steps[name] = steps
        return self._advance(name, "verified")
