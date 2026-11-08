"""Executable finite worlds and evidence-gated extensions (atoms-meta 6)."""

from dataclasses import replace

import pytest
from test_builder_wf import base, tags

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import Bottom, Card, Ok
from opulse.meta import code as C
from opulse.meta.builder import world_value as V
from opulse.meta.builder.instantiate import WorldError, extend, instantiate


def z(number):
    return Card("z", f"z{number}")


def z5():
    def operation(name, function):
        return V.table(name, "combine", ["z", "z"], "z", [],
                       [V.row([z(left), z(right)], V.val(z(function(left, right) % 5)))
                        for left in range(5) for right in range(5)])

    return base(sorts=[V.enum("z", [f"z{number}" for number in range(5)])],
                ops=[operation("add5", lambda left, right: left + right),
                     operation("mul5", lambda left, right: left * right)], probes=[], tags=tags())


def scope(entries):
    return kernel.DictScope([entry for entry in entries if isinstance(entry, kernel.Atom)],
                            [entry for entry in entries if isinstance(entry, kernel.Defn)])


def test_z5_tables_run_with_exact_steps_and_trace():
    card = z5()
    decl, entries = instantiate(card)
    assert decl.dialect == "atoms-v2"
    assert decl.lock["world_value_hash"] == V.world_hash(card)
    assert decl.world_hash() == V.world_hash(card)
    assert len(decl.operations[0].impl["table"]) == 25
    program = n.Call("add5", (n.Call("mul5", (n.Lit(z(3)), n.Lit(z(4)))), n.Lit(z(2))))
    run = kernel.evaluate(program, scope=scope(entries), trace=True)
    assert run.outcome == Ok(z(4)) and run.steps == 2
    assert [(child.name, child.steps, child.outcome) for child in run.trace.children] == [
        ("mul5", 1, Ok(z(2))), ("add5", 1, Ok(z(4)))]


def test_err_cell_preserves_reason_and_step():
    card = base(ops=[V.table("id", "transform", ["z"], "z", ["blocked"],
                             [V.row([z(0)], V.err("blocked")), V.row([z(1)], V.val(z(1)))])])
    _, entries = instantiate(card)
    run = kernel.call("id", [z(0)], scope(entries), trace=True)
    assert run.outcome == Bottom("blocked") and run.steps == 1
    assert run.trace.children[0].outcome == Bottom("blocked")


def body_world():
    card = z5()
    first = C.items(card.fields[3])[0]
    from opulse.meta.builder.instantiate import _assemble
    digest = C.atom_digest(_assemble(card)[0].operations[0])
    code = C.make_code("operation", C.sig_op([("z", "bottom")], ("z", "bottom")),
                       ("a",), n.Call("add5", (n.Var("a"), n.Var("a"))),
                       lambda name: C.Resolved(digest=digest) if name == "add5" else None)
    card = base(sorts=C.items(card.fields[2]), ops=[first, V.body("double", code)], probes=[])
    return card, code


def test_body_charges_inner_steps_not_extra_atom_step():
    card, _ = body_world()
    decl, entries = instantiate(card)
    assert decl.operations[1].impl["body"] == n.Call("add5", (n.Var("x0"), n.Var("x0")))
    run = kernel.call("double", [z(3)], scope(entries), trace=True)
    assert run.outcome == Ok(z(1)) and run.steps == 1
    assert [(child.name, child.given, child.steps) for child in run.trace.children] == [
        ("double", False, 1)]
    assert [(child.name, child.given, child.steps) for child in run.trace.children[0].children] == [
        ("add5", True, 1)]


def test_one_cell_changes_both_content_hashes():
    card = z5()
    op = C.items(card.fields[3])[0]
    rows = list(C.items(op.fields[5]))
    rows[0] = V.row([z(0), z(0)], V.val(z(1)))
    changed = replace(card, fields=(*card.fields[:3], C.lst((replace(op, fields=(*op.fields[:5], C.lst(rows), op.fields[6])),
                                                               *C.items(card.fields[3])[1:])), *card.fields[4:]))
    decl, _ = instantiate(card)
    changed_decl, _ = instantiate(changed)
    assert V.world_hash(card) != V.world_hash(changed)
    assert decl.world_hash() != changed_decl.world_hash()


class StubLedger:
    def __init__(self, pair=None):
        self.pair = pair
        self.lookups = []

    def promoted(self, code_hash, world_hash):
        self.lookups.append((code_hash, world_hash))
        return self.pair


def test_extend_rejects_unpromoted_sampled_and_foreign_evidence():
    card, code = body_world()
    world_digest = V.world_hash(card)
    contract = Contract("same result", keeps=("z",))
    ledger = StubLedger()
    with pytest.raises(WorldError, match="promoted evidence is required"):
        extend(card, code, ledger)
    assert ledger.lookups == [(C.code_hash(code), world_digest)]
    sampled = Evidence("sampled", {"domain": "z", "size": 2}, seed=7, world_hash=world_digest)
    with pytest.raises(WorldError, match="evidence or contract is not promoted"):
        extend(card, code, StubLedger((sampled, contract)))
    foreign = Evidence("exhaustive", {"domain": "z", "size": 5}, world_hash="foreign")
    with pytest.raises(WorldError, match="evidence or contract is not promoted"):
        extend(card, code, StubLedger((foreign, contract)))
    evidence = replace(foreign, world_hash=world_digest)
    derived = extend(card, code, StubLedger((evidence, contract)))
    assert derived.extends == "z5@1"
    assert len(derived.promoted) == 1
    assert derived.promoted[0].evidence == evidence
    assert derived.promoted[0].contract == contract
    assert derived.scopes() == {derived.promoted[0].name: {"domain": "z", "size": 5}}


def test_invalid_world_cannot_instantiate():
    with pytest.raises(WorldError, match="tables: incomplete table: id"):
        instantiate(base(ops=[V.table("id", "transform", ["z"], "z", [], [])]))


def test_range_refinement_uses_decide_le_atom():
    card = base(sorts=[V.range_sort("z", -1, 2)],
                ops=[V.table("id", "transform", ["z"], "z", [],
                             [V.row([number], V.val(number)) for number in range(-1, 3)])])
    decl, entries = instantiate(card)
    assert decl.objects[0].form == "refine" and decl.objects[0].base == "int"
    run = kernel.evaluate(decl.objects[0].valid, {"x": 2}, scope(entries), trace=True)
    outside = kernel.evaluate(decl.objects[0].valid, {"x": 3}, scope(entries))
    assert run.outcome == Ok(Card("bool", "true")) and run.steps == 0
    assert outside.outcome == Ok(Card("bool", "false")) and outside.steps == 0
    assert kernel.call("id", [-1], scope(entries)).outcome == Ok(-1)
