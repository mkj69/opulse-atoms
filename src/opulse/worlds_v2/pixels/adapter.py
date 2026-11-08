"""World-specific verification for public unary probes and constructed sorts."""

from dataclasses import replace
from itertools import product

from opulse.atoms import kernel, nodes
from opulse.atoms.boundary import Boundary
from opulse.atoms.check import check_definition
from opulse.atoms.combinators import check_combinator
from opulse.atoms.library import Library, PipelineError
from opulse.atoms.objects import check_object
from opulse.atoms.spec import Edge, Evidence, ObservationSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal
from opulse.atoms.verify import unfold_equivalent
from opulse.worlds_v2.export_util import bound_evidence
from opulse.worlds_v2.pixels import hosts


class PixelsLibrary(Library):
    def scope(self):
        if (shared := getattr(self, "_verification_scope", None)) is not None:
            return shared
        return super().scope()

    def run(self, name, args, fuel=None, trace=False):
        def valid(value):
            if not isinstance(value, Card):
                return True
            if value.sort == "grid":
                return not isinstance(hosts.from_card(value), Bottom)
            if value.sort == "point":
                return not isinstance(hosts.x_coord(value), Bottom)
            if value.sort == "list":
                return value.tag == "items" and all(valid(item) for item in value.fields)
            if value.sort == "bool":
                return value.tag in ("true", "false") and not value.fields
            if value.sort in ("Island", "Shape"):
                return not isinstance(hosts.from_card(value), Bottom)
            return False

        if not all(valid(arg) for arg in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        return super().run(name, args, fuel=fuel, trace=trace)

    def _params(self, defn):
        if isinstance(defn.spec, ObservationSpec):
            return ("arg0",)
        return super()._params(defn)

    def check(self, name):
        definition = self.get(name)
        if definition.status != "written":
            raise PipelineError("check requires written status")
        if definition.kind == "object":
            problems = [problem for problem in check_object(definition, self)
                        if " argument " not in problem]
            if problems:
                raise PipelineError(problems)
            return self._advance(name, "checked")
        if definition.kind == "observation":
            spec = OperationSpec(name, "transform", (self.world.operations[7].inputs[0],),
                                 Edge("unknown"), "Check the public constructor body.",
                                 extra={"input_names": ["arg0"]})
            checkable = replace(definition, kind="operation", spec=spec)
        else:
            checkable = definition
        operations = tuple(replace(op, inputs=tuple(replace(edge, sort="any") for edge in op.inputs))
                           if op.name in {"eq", "cons", "head", "member", "nth", "list4", "list8", "unwrap", "rows", "width", "height", "cell", "text_pattern", "empty_grid"}
                           else op for op in self.world.operations)
        check_world = replace(self.world, operations=operations)
        problems = [problem for problem in check_definition(checkable, check_world, self._definitions.get)
                    if " argument " not in problem and not (
                        problem.startswith("unresolved call: ") and
                        problem.removeprefix("unresolved call: ").split(".")[0] in self._definitions and
                        problem.removeprefix("unresolved call: ").split(".")[-1] in {"make", "base"})]
        if definition.kind == "combinator":
            problems += check_combinator(definition, self)
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")

    def make_callable(self, name, sample):
        definition = self.get(name)
        if definition.kind == "object":
            return super().make_callable(name, sample)
        if definition.kind != "observation":
            try:
                return super().make_callable(name, sample)
            except PipelineError as error:
                if "Unknown(resource='fuel')" not in str(error):
                    raise
                scope = self.scope().extend([kernel.Defn(name, self._params(definition),
                                                         self._entered_body(definition),
                                                         definition.kind, definition.layer)])
                if isinstance(definition.spec, OperationSpec):
                    for position, edge in self._operation_edges(definition.spec):
                        if self._edge_needed(edge):
                            atom = self._edge_atom(name, position, edge)
                            scope.atoms[atom.name] = atom
                steps = []
                for args in sample:
                    run = kernel.call(name, args, scope, kernel.Limits(fuel=4_000_000), dialect=self.dialect)
                    if isinstance(run.outcome, Unknown):
                        raise PipelineError(f"sample {args!r}: {run.outcome!r}") from error
                    steps.append(run.steps)
                self._steps[name] = steps
                return self._advance(name, "callable")
        if definition.status != "checked" or not sample:
            raise PipelineError("observation or object needs checked status and sample")
        scope = self.scope().extend([kernel.Defn(name, ("arg0",), definition.body, definition.kind, definition.layer)])
        run = kernel.call(name, sample[0], scope, kernel.Limits(fuel=2_000_000), dialect=self.dialect)
        if isinstance(run.outcome, Unknown):
            raise PipelineError(f"observation or object sample: {run.outcome}")
        self._steps[name] = [run.steps]
        return self._advance(name, "callable")

    def verify(self, name, request):
        definition = self.get(name)
        if definition.kind == "combinator":
            sample = replace(request, domain=request.domain[:1],
                             scope={**request.scope, "size": 1})
            super().verify(name, sample)
            definition = self.get(name)
            scope = self.scope()
            steps = []
            for family in product(request.extra["op_family"], repeat=len(definition.spec.op_params)):
                assignment = dict(zip(definition.spec.op_params, family))
                for inputs in request.domain:
                    arguments = iter(inputs)
                    args = tuple(kernel.FnRef(assignment[param]) if param in assignment else next(arguments)
                                 for param in definition.spec.params)
                    run = kernel.call(name, args, scope, dialect=self.dialect)
                    expected = request.reference(assignment, inputs)
                    if not isinstance(expected, (Ok, Bottom, Unknown)):
                        expected = Ok(expected)
                    if isinstance(run.outcome, Unknown) or not outcome_equal(run.outcome, expected):
                        raise PipelineError(f"reference mismatch for {name}: {family!r}, {inputs!r}: "
                                            f"{run.outcome!r} != {expected!r}")
                    steps.append(run.steps)
            evidence = Evidence(request.method, {**request.scope, "unfold_samples_per_slot": 1},
                                request.seed, definition.evidence.checks + ("reference_all",),
                                self.world.world_hash(), self._deps_hash(name))
            self._steps[name] = steps
            self._definitions[name] = replace(definition, status="callable", evidence=None)
            return self.record_evidence(name, bound_evidence(self, name, evidence, request.domain))
        if definition.kind != "observation":
            self._verification_scope = super().scope()
            previous_sync = getattr(self, "_sync_suspended", False)
            self._sync_suspended = True
            try:
                return super().verify(name, request)
            finally:
                self._sync_suspended = previous_sync
                self._verification_scope = None
        if definition.status != "callable" or request.reference is None or request.scope.get("size") != len(request.domain):
            raise PipelineError("verification requires exact finite domain and reference")
        steps = []
        scope = self.scope()
        if not definition.spec.reads or any(scope.resolve(probe) is None for probe in definition.spec.reads):
            raise PipelineError(f"missing observation dependency for {name}")
        arguments = tuple(f"_pixel_arg_{index}" for index in range(len(request.domain[0])))
        unfolded = kernel.inline(nodes.Call(name, tuple(nodes.Var(arg) for arg in arguments)), scope)
        for index, inputs in enumerate(request.domain):
            sample = index in (0, len(request.domain) - 1)
            before = hosts.pixels(inputs[0])
            run = kernel.call(name, inputs, scope, kernel.Limits(fuel=2_000_000),
                              trace=sample, dialect=self.dialect)
            if isinstance(before, Bottom) or hosts.pixels(inputs[0]) != before:
                raise PipelineError(f"observation changed facts for {name}")
            if sample:
                public_copy = Card(inputs[0].sort, inputs[0].tag, inputs[0].fields)
                other = kernel.call(name, (public_copy, *inputs[1:]), scope,
                                    kernel.Limits(fuel=2_000_000), dialect=self.dialect)
                if not outcome_equal(run.outcome, other.outcome):
                    raise PipelineError(f"observation interference for {name}")
            expected = request.reference(*inputs)
            if not isinstance(expected, (Ok, Bottom, Unknown)):
                expected = Ok(expected)
            if isinstance(run.outcome, Unknown) or not outcome_equal(run.outcome, expected):
                raise PipelineError(f"reference mismatch for {name}: {inputs!r}: {run.outcome!r} != {expected!r}")
            if sample:
                inline_run = kernel.evaluate(unfolded, dict(zip(arguments, inputs)), scope,
                                             kernel.Limits(fuel=2_000_000), dialect=self.dialect)
                if not outcome_equal(run.outcome, inline_run.outcome) or run.steps != inline_run.steps:
                    raise PipelineError(f"inline mismatch for {name}")
                if not unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0))).ok:
                    raise PipelineError(f"boundary mismatch for {name}")
            steps.append(run.steps)
        checks = ["reference", "unfold_equivalence", "boundary_equivalence",
                  "dependency", "facts_unchanged", "non_interference"]
        evidence = Evidence(request.method, {**request.scope, "unfold_samples": min(2, len(request.domain))},
                            request.seed, tuple(checks),
                            self.world.world_hash(), self._deps_hash(name))
        self._steps[name] = steps
        return self.record_evidence(name, bound_evidence(self, name, evidence, request.domain))
