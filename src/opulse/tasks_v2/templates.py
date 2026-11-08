"""Local six-kind definition-template adapter (atoms-v2, sections 3 and 9).

Core Definition has no template record yet. Family evidence and its membership
gate live here; law and bridge outputs use the local kind-specific checks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from opulse.atoms import kernel, notation
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    content_hash,
)
from opulse.atoms.values import Card, boolean, encode
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2 import kernel_engine as engine
from opulse.tasks_v2 import lawbridge


@dataclass(frozen=True)
class FamilyEvidence:
    method: str
    members: frozenset[str]
    scope: dict

    def __post_init__(self):
        if self.method not in ("bounded", "sampled") or not self.members:
            raise ValueError("a template needs a nonempty bounded or sampled family")

    def to_dict(self) -> dict:
        return {"method": self.method, "members": sorted(self.members),
                "scope": self.scope}


@dataclass(frozen=True)
class StatementInstance:
    name: str
    kind: str
    id: str
    depends_on: tuple[str, ...]
    statement: lawbridge.Law | lawbridge.Bridge
    evidence: lawbridge.Evidence | None = None
    status: str = "written"

    def verify(self) -> bool:
        return (lawbridge.check_law(self.statement) if self.kind == "law" else
                lawbridge.check_bridge(self.statement))

    def promote(self) -> StatementInstance:
        if (self.evidence is None or self.evidence.method == "sampled" or
                not self.verify()):
            raise PipelineError("statement needs bounded verified evidence")
        return replace(self, status="promoted")


@dataclass(frozen=True)
class Template:
    name: str
    kind: str
    params: tuple[tuple[str, str], ...]
    body_factory: Callable
    evidence: FamilyEvidence | None = field(default=None, compare=False)

    def __post_init__(self):
        if self.kind not in ("object", "operation", "combinator", "observation", "law", "bridge"):
            raise ValueError("invalid template output kind")
        if len({name for name, _ in self.params}) != len(self.params) or any(
                sort not in ("sort", "op", "value") for _, sort in self.params):
            raise ValueError("invalid template parameters")

    def key(self, arguments: tuple) -> str:
        arguments = self._canonical(arguments)
        result = self.body_factory("template_member", *arguments)
        if self.kind in ("law", "bridge"):
            statement = result
            body = ({"variables": statement.variables, "lhs": n.to_json(statement.lhs),
                     "rhs": n.to_json(statement.rhs), "relation": statement.relation}
                    if self.kind == "law" else
                    {"source_sort": statement.source_sort, "target_sort": statement.target_sort,
                     "map": n.to_json(statement.map), "domain": n.to_json(statement.domain),
                     "interface": statement.interface, "source_world": statement.source_world,
                     "target_world": statement.target_world})
        elif result is None:
            body = None
        else:
            spec, expression = result
            body = {"spec": spec.to_dict(), "expression": n.to_json(expression) if expression is not None else None}
        return content_hash({"template": self.name, "kind": self.kind,
                             "params": self.params, "body": body,
                             "arguments": [encode(value) for value in arguments]})

    def display(self, arguments: tuple) -> str:
        arguments = self._canonical(arguments)
        rendered = ", ".join(
            ("Pair<Int, Int>" if value == "pair[int,int]" else
             {"int": "Int", "nat": "Nat"}.get(value, value))
            if sort == "sort" else
            str(value) if isinstance(value, (int, str)) else notation.print_value(value)
            for (_, sort), value in zip(self.params, arguments))
        return f"{self.name}[{rendered}]"

    def _canonical(self, arguments: tuple) -> tuple:
        self._arguments(arguments)
        aliases = {"Int": "int", "Nat": "nat", "Pair<Int, Int>": "pair[int,int]"}
        return tuple(aliases.get(value, value) if sort == "sort" else value
                     for (_, sort), value in zip(self.params, arguments))

    def _arguments(self, arguments: tuple) -> None:
        if len(arguments) != len(self.params) or any(
                (type(value) not in (int, str, Card) if sort == "value"
                 else type(value) is not str)
                for (_, sort), value in zip(self.params, arguments)):
            raise ValueError("invalid template arguments")

    def instantiate(self, arguments: tuple, name: str, *, cite: bool = False,
                    world_hash: str | None = None) -> Definition:
        arguments = self._canonical(arguments)
        key = self.key(arguments)
        if cite and (self.evidence is None or key not in self.evidence.members):
            raise PipelineError("instantiation outside the recorded template family")
        if cite and (world_hash is None or world_hash not in
                     self.evidence.scope["members"][key]["world_hashes"]):
            raise PipelineError("template family evidence belongs to another world")
        if self.kind in ("law", "bridge"):
            statement = self.body_factory(name, *arguments)
            if statement.name != name:
                raise ValueError("factory returned a differently named statement")
            if cite:
                recorded = self.evidence.scope["members"][key]["verification"]["inputs"]
                covered = statement.evidence.scope if self.kind == "bridge" else statement.scope
                if any([encode(value) for value in row] not in recorded for row in covered):
                    raise PipelineError("template family evidence does not cover instance scope")
                statement = replace(statement, evidence=lawbridge.Evidence(self.evidence.method,
                                                                            statement.scope))
            return StatementInstance(name, self.kind, key, (self.display(arguments),), statement,
                                     statement.evidence)
        spec, body = self.body_factory(name, *arguments)
        if getattr(spec, "name", None) != name:
            raise ValueError("factory returned a differently named spec")
        if cite:
            member = self.evidence.scope["members"][key]
            spec = replace(spec, extra={**spec.extra, "template_family_scope": {
                "inputs": member["verification"]["inputs"], "method": self.evidence.method,
                "world_hashes": member["world_hashes"], "seed": member["seed"],
            }})
        dependency = self.display(arguments)
        if body is None:
            dependencies = (dependency,)
        else:
            expressions = (body,)
            if self.kind == "observation" and spec.memory:
                expressions += (spec.memory["init"], spec.memory["step"])
            dependencies = tuple(sorted(set().union(*(n.references(expr) for expr in expressions))))
            if dependency not in dependencies:
                raise ValueError("executable instantiation must call its template layer")
        return Definition(name, self.kind, "invented", 2, dependencies,
                          spec, body, id=key)

    def check_family(self, cases: tuple[tuple[tuple, str, VerifyRequest], ...],
                     library_factory: Callable[[str], Library]) -> Template:
        if not cases:
            raise ValueError("empty family")
        members = set()
        scopes = {}
        if len({self.key(arguments) for arguments, _, _ in cases}) != len(cases):
            raise ValueError("duplicate family arguments")
        for arguments, name, request in cases:
            if request.method not in ("bounded", "sampled"):
                raise ValueError("template family must be bounded or sampled")
            definition = self.instantiate(arguments, name)
            library = library_factory(name)
            if self.kind in ("law", "bridge"):
                if (tuple(request.domain) != definition.statement.scope or
                        not definition.verify()):
                    raise PipelineError("template statement does not hold on its checked scope")
                covered = definition.evidence.scope if self.kind == "bridge" else request.domain
                verification = {"inputs": [[encode(value) for value in row] for row in covered],
                                "size": len(covered)}
                if self.kind == "bridge":
                    _, excluded = lawbridge.bridge_coverage(definition.statement)
                    verification["excluded"] = [{"op": list(pair),
                                                  "value": [encode(value) for value in row]}
                                                 for pair, row in excluded]
            else:
                advance_instance(library, definition, request)
                verification = dict(library.get(name).evidence.scope)
            key = self.key(arguments)
            members.add(key)
            scopes[key] = {"world_hashes": [library.world.world_hash()],
                           "verification": verification,
                           "seed": request.seed}
        return replace(self, evidence=FamilyEvidence("bounded" if all(
            case[2].method == "bounded" for case in cases) else "sampled",
            frozenset(members), {"domain": "recorded instantiations", "size": len(members),
                                 "members": scopes}))


def advance_instance(library: Library, definition: Definition, request: VerifyRequest) -> Definition:
    """Never reuse family evidence as instance evidence."""
    inputs = [[encode(item) for item in row] for row in request.domain]
    request = replace(request, scope={**request.scope, "inputs": inputs})
    citation = definition.spec.extra.get("template_family_scope")
    if citation is not None and (library.world.world_hash() not in citation["world_hashes"] or
                                 any(row not in citation["inputs"] for row in inputs) or
                                 citation["method"] == "sampled" and (
                                     request.method != "sampled" or
                                     request.seed != citation["seed"])):
        raise PipelineError("template family evidence does not cover instance scope")
    height = definition.spec.extra.get("finite_height")
    if height is not None and any(len(row) != 1 or type(row[0]) is not int or
                                  not 0 <= row[0] <= height for row in request.domain):
        raise PipelineError("until-stable scope exceeds the recorded finite height")
    alias = definition.spec.extra.get("template") if definition.kind == "object" else None
    if definition.kind == "operation" and "template_base" in definition.spec.extra:
        alias = definition.depends_on[0]
    if definition.kind == "combinator" and "template_body" in definition.spec.extra:
        alias = definition.depends_on[0]
    if definition.kind == "observation" and "template_probe" in definition.spec.extra:
        alias = definition.depends_on[0]
    if alias is not None and alias in library.definitions:
        layer = library.get(alias)
        if (layer.origin != "invented" or layer.status not in ("verified", "promoted") or
                any(row not in layer.evidence.scope.get("inputs", ()) for row in inputs) or
                layer.evidence.method == "sampled" and request.method != "sampled"):
            raise PipelineError("template layer evidence does not cover instance scope")
    if alias is not None and alias not in library.definitions:
        if definition.kind == "observation":
            probe = definition.spec.extra["template_probe"]
            subject = n.Var("s")
            alias_body = n.Call(probe, (subject,))
            alias_spec = ObservationSpec(alias, (probe,), alias_body, extra={"subject": "s"})
            alias_def = Definition(alias, "observation", "invented", 1, (probe,),
                                   alias_spec, alias_body)
            alias_request = replace(request, reference=lambda state: kernel.call(
                probe, (state,), library.scope(), dialect=library.dialect).outcome)
            advance_instance(library, alias_def, alias_request)
        elif definition.kind == "object":
            expansion = n.from_json(definition.spec.extra["template_body"])
            if "reduce" in alias:
                reference = engine.canonical
            elif alias.startswith("Interval"):
                reference = lambda value: value
            elif "step_up" in alias:
                reference = lambda value: min(value + 1, 12)
            else:
                reference = lambda value: value % (2 if "mod2" in alias else 12)
            params = ("x",)
            sorts = ("unknown",)
        elif definition.kind == "operation":
            expansion = n.Call(definition.spec.extra["template_base"],
                               (n.Var("left"), n.Var("right")))
            reference = definition.spec.extra["template_base"]
            params = ("left", "right")
            sorts = tuple(edge.sort for edge in definition.spec.inputs)
        else:
            expansion = n.from_json(definition.spec.extra["template_body"])
            reference = _reach_closure if "reach" in alias else lambda value: 12
            params = ("x",)
            sorts = ("int",)
        if definition.kind != "observation":
            alias_spec = OperationSpec(alias, "transform" if len(params) == 1 else "combine",
                                       tuple(Edge(sort) for sort in sorts),
                                       Edge(sorts[0]), "Template expansion",
                                       extra={"input_names": list(params)})
            alias_def = Definition(alias, "operation", "invented", 1,
                                   tuple(sorted(n.references(expansion))), alias_spec, expansion)
            alias_request = replace(request, reference=reference)
            advance_instance(library, alias_def, alias_request)
    library.write(definition)
    library.check(definition.name)
    library.make_callable(definition.name, request.domain[:1])
    library.verify(definition.name, request)
    library.account(definition.name)
    if request.method != "sampled":
        library.promote(definition.name, Contract("Matches its checked expansion on the recorded scope"))
    return library.get(definition.name)


def _mod(value, modulus):
    return value % modulus


def _reach_step(value):
    return value | (2 if value & 1 else 0) | (4 if value & 2 else 0)


def _reach_closure(value):
    while (advanced := _reach_step(value)) != value:
        value = advanced
    return value


def _valid(value):
    return boolean(type(value) is int)


def library(world="integer@1") -> Library:
    """The only bridge from task-world declarations to the core pipeline."""
    declaration = WorldDecl.from_dict(engine.world(world).to_dict())
    if world in ("integer@1", "clock@2"):
        representations = (
            ObjectSpec("fraction", "given"), ObjectSpec("interval", "given"),
        )
        declaration = replace(declaration, objects=(*declaration.objects, *representations))
    atoms = list(engine.scope(world).atoms.values())
    atoms.extend((kernel.Atom("template_valid", 1, _valid),
                  kernel.Atom("template_mod2", 1, lambda value: _mod(value, 2)),
                  kernel.Atom("template_mod12", 1, lambda value: _mod(value, 12)),
                  kernel.Atom("template_interval_valid", 1, lambda value: boolean(
                      isinstance(value, Card) and value.sort == "interval" and
                      len(value.fields) == 2 and all(type(part) is int for part in value.fields) and
                      value.fields[0] <= value.fields[1])),
                  kernel.Atom("template_nat_interval_valid", 1, lambda value: boolean(
                      isinstance(value, Card) and value.sort == "interval" and
                      len(value.fields) == 2 and all(type(part) is int and part >= 0
                                                     for part in value.fields) and
                      value.fields[0] <= value.fields[1]))))
    atoms.append(kernel.Atom("template_step_up", 1, lambda value: min(value + 1, 12)))
    atoms.append(kernel.Atom("template_step_by_two", 1, lambda value: min(value + 2, 12)))
    atoms.append(kernel.Atom("template_reach", 1, _reach_step))
    if world in ("integer@1", "clock@2"):
        hour_operations = (
            ("template_hour_add_base", lambda left, right: (left + right) % 12),
            ("template_hour_mul_base", lambda left, right: (left * right) % 12),
        )
        atoms.extend(kernel.Atom(name, 2, operation) for name, operation in hour_operations)
        declaration = replace(declaration, operations=(*declaration.operations, *(
            OperationSpec(name, "combine", (Edge("int"), Edge("int")), Edge("int"),
                          "Arithmetic on canonical hours") for name, _ in hour_operations)))
    if world == "action@1":
        atoms.append(kernel.Atom("template_increment", 1, lambda value: value + 1))
        increment = OperationSpec("template_increment", "transform", (Edge("int"),),
                                  Edge("int"), "Increment observation memory")
        declaration = replace(declaration, operations=(*declaration.operations, increment))
    return Library(declaration, atoms, declaration.dialect)


def _quot(name, sort, canon):
    if (sort, canon) not in (("int", "mod2"), ("int", "mod12"), ("int", "step_up"),
                             ("pair[int,int]", "reduce")):
        raise ValueError("unsupported quotient arguments")
    canonical = n.Call("fraction_canon" if canon == "reduce" else f"template_{canon}",
                       (n.Var("x"),))
    alias = QUOT.display((sort, canon))
    spec = ObjectSpec(name, "refine", base="fraction" if canon == "reduce" else sort,
                      valid=n.Call("fraction_valid" if canon == "reduce" else "template_valid",
                                   (n.Var("x"),)),
                      canon=n.Call(alias, (n.Var("x"),)),
                      extra={"template": alias, "template_body": n.to_json(canonical)})
    return spec, n.Call(alias, (n.Var("x"),))


def _interval(name, sort, lt):
    if (sort, lt) not in (("int", "le"), ("nat", "le")):
        raise ValueError("unsupported interval arguments")
    alias = INTERVAL.display((sort, lt))
    spec = ObjectSpec(name, "refine", base="interval",
                      valid=n.Call("template_nat_interval_valid" if sort == "nat" else
                                   "template_interval_valid", (n.Var("x"),)),
                      canon=n.Call(alias, (n.Var("x"),)),
                      extra={"template": alias, "template_body": n.to_json(n.Var("x"))})
    return spec, n.Call(alias, (n.Var("x"),))


def _lift(name, operation):
    if operation not in ("add", "mul", "hour_add", "hour_mul"):
        raise ValueError("unsupported lifted operation")
    body = n.Call(f"Lift[{operation}]", (n.Var("left"), n.Var("right")))
    hourly = operation.startswith("hour_")
    sort = "int" if hourly else "fraction"
    base = (f"template_{operation}_base" if hourly else
            "frac_add_base" if operation == "add" else "frac_mul_base")
    spec = OperationSpec(name, "combine", (Edge(sort), Edge(sort)),
                         Edge(sort), f"Lift {operation} through canonicalization",
                         extra={"input_names": ["left", "right"],
                                "template_base": base})
    return spec, body


def _until_stable(name, step):
    if step not in ("step_up", "step_by_two", "reach"):
        raise ValueError("unsupported finite step")
    height = 7 if step == "reach" else 12
    current = n.Var("current")
    advanced = n.Call(f"template_{step}", (current,))
    loop = n.Rec("iterate", ("current",), n.Case(
        ((n.Test(n.Call("zero_test", (n.Call("sub", (advanced, current)),))), current),),
        n.Call("iterate", (advanced,))), (n.Var("x"),),
        n.Call("sub", (n.Lit(height), current)))
    body = n.Call(f"Until_stable[{step}]", (n.Var("x"),))
    spec = CombinatorSpec(name, ("x",), (), body,
                          extra={"finite_height": height, "template_body": n.to_json(loop)})
    return spec, body


def _count(name, probe):
    if probe not in ("front_wall", "front_water"):
        raise ValueError("unsupported probe")
    subject = n.Var("s")
    step = n.Case(((n.Test(n.Call(probe, (subject,))),
                    n.Call("template_increment", (n.Var("memory"),))),), n.Lit(0))
    body = n.Case(((n.Test(n.Call(f"Count[{probe}]", (subject,))),
                    n.Var("memory")),), n.Var("memory"))
    return ObservationSpec(name, (probe,), body,
                           {"sort": "int", "init": n.Lit(0), "step": step},
                           {"subject": "s", "template_probe": probe}), body


QUOT = Template("Quot", "object", (("T", "sort"), ("canon", "op")), _quot)
INTERVAL = Template("Interval", "object", (("T", "sort"), ("lt", "op")), _interval)
LIFT = Template("Lift", "operation", (("f", "op"),), _lift)
UNTIL_STABLE = Template("Until_stable", "combinator", (("step", "op"),), _until_stable)
COUNT = Template("Count", "observation", (("probe", "op"),), _count)


def _comm(name, operation):
    if operation not in ("add", "mul"):
        raise ValueError("unsupported commutative operation")
    variables = (("a", "Int"), ("b", "Int"))
    left = n.Call(operation, (n.Var("a"), n.Var("b")))
    right = n.Call(operation, (n.Var("b"), n.Var("a")))
    return lawbridge.Law(name, variables, left, right,
                         scope=tuple((a, b) for a in range(-2, 3) for b in range(-2, 3)))


def _canon_bridge(name, sort, canonicalizer):
    if (sort, canonicalizer) not in (("pair[int,int]", "fraction_canon"),
                                    ("IList", "as_list")):
        raise ValueError("unsupported bridge canonicalizer")
    original = lawbridge.bridges()["pair_to_frac" if canonicalizer == "fraction_canon"
                                   else "ilist_to_list"]
    return replace(original, name=name)


COMM = Template("Comm", "law", (("op", "op"),), _comm)
CANON = Template("Canon", "bridge", (("T", "sort"), ("canon", "op")), _canon_bridge)


def unfold_chain(definition: Definition) -> tuple[str, ...]:
    """Expose the two provenance boundaries without changing evaluation."""
    return (definition.name, *definition.depends_on)
