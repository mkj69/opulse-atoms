"""Build executable finite worlds and evidence-gated extensions (atoms-meta 6)."""

from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    Evidence,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, boolean, encode
from opulse.atoms.world import DerivedWorld, WorldDecl
from opulse.meta import code as C
from opulse.meta.builder import world_value as V


class WorldError(ValueError):
    pass


class _BuiltWorldDecl(WorldDecl):
    """Use the canonical world value as the identity of a builder instance."""

    def world_hash(self):
        return self.lock["world_value_hash"]


def _sorts(card):
    return {sort.fields[0]: sort for sort in C.items(card.fields[2])}


def domain(sort, sorts):
    if sort == "bool":
        return (Card("bool", "false"), Card("bool", "true"))
    if sort == "int":
        return None
    definition = sorts[sort]
    if definition.tag == "enum":
        return tuple(Card(sort, tag) for tag in C.items(definition.fields[1]))
    return tuple(range(definition.fields[1], definition.fields[2] + 1))


def _operation(spec, op, sorts):
    name, _, inputs, _, _, rows, cost = op.fields
    lookup = {tuple(C.items(entry.fields[0])): entry.fields[1] for entry in C.items(rows)}

    def execute(*args):
        cell = lookup.get(tuple(args))
        if cell is None:
            return Bottom("invalid")
        return cell.fields[0] if cell.tag == "val" else Bottom(cell.fields[0])

    return kernel.Atom(name, len(C.items(inputs)), execute, cost)


def _builtin_le():
    return kernel.Atom("__range_le", 2, lambda left, right: boolean(type(left) is int and type(right) is int
                                                                     and left <= right), cost=0)


def _assemble(card):
    sorts = _sorts(card)
    objects = []
    for name, definition in sorts.items():
        if definition.tag == "enum":
            # Core object_atoms reads fields["items"] for every dict tag, including nullary tags.
            objects.append(ObjectSpec(name, "compose", tags={tag: [] for tag in C.items(definition.fields[1])}))
        else:
            lo, hi = definition.fields[1:]
            valid = n.Case(((n.Test(n.Call("__range_le", (n.Lit(lo), n.Var("x")))),
                             n.Call("__range_le", (n.Var("x"), n.Lit(hi)))),), n.Lit(boolean(False)))
            objects.append(ObjectSpec(name, "refine", base="int", valid=valid))
    operations, executable, definitions = [], [_builtin_le()], []
    for op in C.items(card.fields[3]):
        if op.tag == "table":
            name, role, inputs, output, errors, rows, cost = op.fields
            spec = OperationSpec(name, role, tuple(Edge(sort) for sort in C.items(inputs)),
                                 Edge(output), f"Finite table {name}", tuple(C.items(errors)),
                                 {"table": [{"inputs": [encode(value) for value in C.items(entry.fields[0])],
                                             "out": {entry.fields[1].tag: encode(entry.fields[1].fields[0])
                                                     if entry.fields[1].tag == "val" else entry.fields[1].fields[0]}}
                                            for entry in C.items(rows)]}, cost)
            executable.append(_operation(spec, op, sorts))
        else:
            name, code = op.fields
            decoded = C.decode(code)
            sig_inputs, sig_output = code.fields[1].fields
            inputs = tuple(Edge(*edge.fields) for edge in C.items(sig_inputs))
            output = Edge(*sig_output.fields)
            spec = OperationSpec(name, "decide" if output.sort == "bool" else "transform", inputs,
                                 output, f"Decoded code {C.code_hash(code)}", impl={"body": decoded.main.body},
                                 cost=0)
            definitions.append(kernel.Defn(name, decoded.main.params, decoded.main.body, layer=1))
        operations.append(spec)
    name, version, _, _, nodes, recursion, probes, view, kinds, tags = card.fields[:10]
    decl = _BuiltWorldDecl(name, version, "atoms-v2", {}, {}, tuple(objects), tuple(operations),
                     {"nodes": list(C.items(nodes)), "library": [], "recursion": recursion},
                     {"truth": None, "show": {"input": "values", "result": "value"},
                      "probes": list(C.items(probes)), "judge_view": view},
                     {"world_value_hash": V.world_hash(card)},
                     {"open_kinds": list(C.items(kinds)),
                      "tags": {entry.fields[0]: list(C.items(entry.fields[1]))
                               if isinstance(entry.fields[1], Card) else entry.fields[1]
                               for entry in C.items(tags)}})
    return decl, executable + definitions


def instantiate(card):
    """Return a WorldDecl and a mixed Atom/Defn scope; Defns charge inner steps."""
    from opulse.meta.builder.wf import wf

    report = wf(card)
    if report != Card("report", "ok"):
        raise WorldError(f"{report.fields[0]}: {report.fields[1]}")
    canonical = V.canonicalize(card)
    declaration, entries = _assemble(canonical)
    laws = [
        {"name": law.fields[0], "code_hash": C.code_hash(law.fields[1]),
         "statement": n.to_json(C.decode(law.fields[1]).main.body)}
        for law in C.items(canonical.fields[10])] if len(canonical.fields) == 11 else []
    return replace(declaration, extra={**declaration.extra, "laws": laws}), entries


def extend(card, code, ledger_or_evidence):
    """Add promoted code only for evidence tied to this exact world value."""
    if not C.is_canonical(code):
        raise WorldError("code must be canonical")
    if "operation" not in C.items(card.fields[8]):
        raise WorldError("operation kind is closed")
    base, _ = instantiate(card)
    try:
        found = ledger_or_evidence.promoted(C.code_hash(code), V.world_hash(card))
    except (AttributeError, KeyError, TypeError) as exc:
        raise WorldError("promoted evidence is required") from exc
    if found is None:
        raise WorldError("promoted evidence is required")
    evidence, contract = found
    if (not isinstance(evidence, Evidence) or evidence.method not in ("bounded", "exhaustive")
            or evidence.world_hash != V.world_hash(card) or not isinstance(contract, Contract)):
        raise WorldError("evidence or contract is not promoted for this world")
    decoded = C.decode(code)
    if decoded.kind != "operation" or decoded.deps:
        raise WorldError("only operation code over given atoms can extend this world")
    specs = {spec.name: spec for spec in base.operations}
    if any(name not in specs or digest != C.atom_digest(specs[name]) for name, digest in decoded.atoms):
        raise WorldError("code refers to foreign or changed atoms")
    sig_inputs, sig_output = decoded.sig.fields
    name = "derived_" + C.code_hash(code)[:12]
    from opulse.meta.builder.wf import wf

    fields = list(card.fields)
    fields[3] = C.lst((*C.items(fields[3]), V.body(name, code)))
    report = wf(Card("world", "world", tuple(fields)))
    if report != Card("report", "ok"):
        raise WorldError(f"invalid extension: {report.fields[0]}: {report.fields[1]}")
    spec = OperationSpec(name, "transform", tuple(Edge(*edge.fields) for edge in C.items(sig_inputs)),
                         Edge(*sig_output.fields), "Promoted code", impl={"body": decoded.main.body}, cost=0)
    definition = Definition(name, "operation", "invented", 1, tuple(sorted(n.references(decoded.main.body))),
                            spec, decoded.main.body, evidence, contract, status="promoted")
    if definition.validate():
        raise WorldError("invalid promoted definition")
    return DerivedWorld.build(base, (definition,))
