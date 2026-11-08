"""Finite, explicit commuting diagrams for invented and cross-world sorts."""

import json
from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card
from opulse.gen_v2.admit import admit
from opulse.gen_v2.audit import audit
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature
from opulse.gen_v2.bridges import (
    BridgeRecord,
    BridgeRefuted,
    BridgeUnknown,
    _metadata,
    check,
    propose,
    to_json,
)
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.bridge import candidate as bridge_candidate
from opulse.gen_v2.moves.object import _candidate
from opulse.gen_v2.run import load, save
from opulse.gen_v2.worlds import integer, rhythm, toy


def _state(adapter):
    world = adapter.gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                      world.extra_scope), dict(world.sorts))


def _invented_record():
    state = _state(toy)
    _add_record(state, "A1", "f1")
    return state


def _add_record(state, sort, operation):
    spec = ObjectSpec(sort, "compose", tags={"pair": [["value", "int"], ["other", "int"]]})
    values = tuple(Card(sort, "pair", (first, second))
                   for first in range(3) for second in range(3))
    candidate = _candidate(state, spec, "obj.record", n.Call(f"{sort}.pair", (n.Lit(0), n.Lit(1))),
                           values)
    assert isinstance(admit(state, candidate), Entry)
    variable = n.Var("x")
    body = n.Call(f"{sort}.pair", (
        n.Call("add", (n.Call(f"{sort}.value", (variable,)), n.Lit(1))),
        n.Call(f"{sort}.other", (variable,))))
    op = OperationSpec(operation, "transform", (Edge(sort),), Edge(sort), "Increase the value.",
                       extra={"input_names": ["x"]})
    references = tuple(sorted(n.references(body)))
    definition = Definition(operation, "operation", "invented", 2, references, op, body)
    assert isinstance(admit(state, Candidate(definition, Signature((sort,), sort),
                                             "op.record_step")), Entry)


def test_invented_record_projects_and_commutes_with_given_sort():
    state = _invented_record()
    records = propose(state, max_bridges=20, seed=19)
    bridge = next(record for record in records if record.source[1] == "A1" and
                  record.target[1] == "int" and record.map == n.Call("A1.value", (n.Var("x"),)) and
                  ("f1", "inc") in record.interface)
    assert bridge.layer == 3
    assert {"A1", "A1.value", "f1", "inc"} <= set(bridge.depends_on)
    assert bridge.layer == 3
    assert bridge.evidence == check(bridge, state)
    assert bridge.notation() == f"bridge ~{bridge.name}: A1 -> int  L3"
    assert bridge.application() == f"~{bridge.name}(x)"
    data = json.loads(to_json([bridge]))
    assert data["schema"] == "opulse.gen_v2.bridge/1"
    assert data["bridges"][0]["evidence"]["scope"]["size"] == len(bridge.domain)
    assert to_json([bridge]).isascii()


def test_counterexample_and_unknown_are_not_evidence():
    state = _invented_record()
    bridge = next(record for record in propose(state, max_bridges=20, seed=19)
                  if record.map == n.Call("A1.value", (n.Var("x"),)) and
                  ("f1", "inc") in record.interface)
    with pytest.raises(BridgeRefuted, match="counterexample"):
        changed = replace(bridge, interface=(("f1", "dec"),),
                          depends_on=("A1", "A1.value", "dec", "f1"))
        check(changed, state)
    with pytest.raises(BridgeRefuted, match="domain"):
        check(replace(bridge, domain=(Card("A1", "pair", (999, 1)),)), state)
    with pytest.raises(BridgeRefuted, match="dependencies"):
        check(replace(bridge, depends_on=()), state)
    state.world.fuel = 0
    with pytest.raises(BridgeUnknown, match="resource"):
        check(bridge, state)


def test_cross_world_integer_to_rhythm_arithmetic_is_partial_and_deterministic():
    source, target = _state(integer), _state(rhythm)
    first = propose(source, target, seed=3)
    second = propose(source, target, seed=3)
    assert first == second and first
    bridge = next(record for record in first if record.source == ("integer", "int") and
                  record.target == ("rhythm", "int") and ("add", "add") in record.interface)
    assert bridge.map == n.Var("x")
    assert len(bridge.domain) >= 2
    assert -3 not in bridge.domain
    assert bridge.evidence == check(bridge, source, target)
    assert {tuple(pair) for pair in json.loads(to_json(first))["bridges"][0]["interface"]} == {
        ("add", "add"), ("add", "maximum"), ("sub", "sub")}


def test_partial_bridge_requires_a_checked_pair_for_each_interface():
    source, target = _state(integer), _state(rhythm)
    bridge = next(record for record in propose(source, target, seed=3)
                  if record.source == ("integer", "int") and
                  record.target == ("rhythm", "int") and ("add", "add") in record.interface)
    partial = replace(bridge, domain=(1,), interface=(("add", "add"),))
    dependencies, layer = _metadata(partial, source, target)
    partial = replace(partial, depends_on=dependencies, layer=layer)
    with pytest.raises(BridgeRefuted, match="no checked pairs"):
        check(partial, source, target)


def test_cross_world_bridge_admits_and_requires_attached_target(tmp_path):
    source, target = _state(integer), _state(rhythm)
    source.world = replace(source.world, decl=replace(source.world.decl,
                           open_kinds=(*source.world.decl.open_kinds, "bridge")),
                           open_kinds=frozenset((*source.world.open_kinds, "bridge")))
    source.library = GenLibrary(source.world.decl, source.world.atoms, source.world.dialect,
                                source.world.extra_scope, source.world.signatures)
    bridge = next(item for item in propose(source, target, max_bridges=30)
                  if item.source[1] == item.target[1] == "int")
    item = bridge_candidate(source, bridge, target)
    result = admit(source, item)
    assert isinstance(result, Entry), result
    record = source.library.get(result.name)
    assert record.spec.target == "rhythm@1:int"
    assert record.spec.extra["target_world_hash"] == target.world.decl.world_hash()
    assert record.evidence.scope["size"] == len(bridge.domain)
    assert source.library.run(result.name, (2,)).outcome == Bottom("outside_domain")
    assert audit(source).ok
    path = tmp_path / "cross.json"
    save(source, path)
    # Core 14d586f2 resets evidence when an attached world goes away, so the
    # checkpoint is taken while the target is attached.
    source.library._attached_worlds.pop("rhythm@1")
    assert any(failure.name == result.name for failure in audit(source).failures)
    with pytest.raises(ValueError, match="target worlds"):
        load(source.world, path)
    restored = load(source.world, path, target_worlds=(target,))
    assert audit(restored).ok


def test_cross_world_constructor_preserves_record_fields_and_operation():
    source, target = _state(integer), _state(rhythm)
    _add_record(source, "A1", "f1")
    _add_record(target, "B1", "f2")
    bridge = next(record for record in propose(source, target, max_bridges=50, seed=7)
                  if record.source[1] == "A1" and record.target[1] == "B1")
    assert bridge.map == n.Call("B1.pair", (
        n.Call("A1.value", (n.Var("x"),)), n.Call("A1.other", (n.Var("x"),))))
    assert ("f1", "f2") in bridge.interface
    assert {"A1", "B1", "A1.other", "A1.value", "B1.pair", "f1", "f2"} <= set(bridge.depends_on)
    assert bridge.layer == 3
    assert bridge.evidence == check(bridge, source, target)


def test_check_rejects_empty_interface_and_invalid_signature():
    source, target = _state(integer), _state(rhythm)
    bridge = BridgeRecord("b1", ("integer", "int"), ("rhythm", "int"), n.Var("x"),
                          (0, 1), (), {"seed": 0}, 1, ())
    with pytest.raises(BridgeRefuted, match="empty"):
        check(bridge, source, target)
    with pytest.raises(BridgeRefuted, match="incompatible"):
        check(replace(bridge, interface=(("eq", "add"),),
                      depends_on=("add", "eq")), source, target)


def test_finding_2_host_repr_is_not_semantic_equality_and_unknown_comparator_refuses():
    state = _state(toy)

    class Host:
        def __repr__(self):
            return "Host<1>"

    first, second = Host(), Host()
    state.sorts["int"] = replace(state.sorts["int"], values=(first, second))
    state.library.add_atoms((kernel.Atom("identity_host", 1, lambda value: value),
                             kernel.Atom("wrong_host", 1, lambda value: second if value is first else first)))
    state.extra_signatures.update({name: Signature(("int",), "int")
                                   for name in ("identity_host", "wrong_host")})
    bridge = BridgeRecord("host", ("toy", "int"), ("toy", "int"), n.Var("x"), (first, second),
                          (("identity_host", "wrong_host"),), {}, 1,
                          ("identity_host", "wrong_host"))
    with pytest.raises(BridgeRefuted, match="comparator"):
        check(bridge, state)

    class ComparableHost(Host):
        def __eq__(self, other):
            return self is other

    first, second = ComparableHost(), ComparableHost()
    state.sorts["int"] = replace(state.sorts["int"], values=(first, second))
    bridge = replace(bridge, domain=(first, second))
    with pytest.raises(BridgeRefuted, match="counterexample"):
        check(bridge, state)


def test_finding_3_bottom_reasons_require_explicit_forgetting():
    state = _state(toy)
    state.library.add_atoms((kernel.Atom("fail_left", 1, lambda value: Bottom("divide_by_zero") if value == 0 else value),
                             kernel.Atom("fail_right", 1, lambda value: Bottom("out_of_bounds") if value == 0 else value)))
    state.extra_signatures.update({name: Signature(("int",), "int")
                                   for name in ("fail_left", "fail_right")})
    bridge = BridgeRecord("failure", ("toy", "int"), ("toy", "int"), n.Var("x"), (0, 1),
                          (("fail_left", "fail_right"),), {}, 1, ("fail_left", "fail_right"))
    with pytest.raises(BridgeRefuted, match="failure reason"):
        check(bridge, state)
    forgotten = replace(bridge, forget_failure_reasons=True)
    evidence = check(forgotten, state)
    assert evidence["forget_failure_reasons"] is True
    assert "forget_failure_reasons" in forgotten.notation()
    from opulse.gen_v2.notation import parse_declaration

    assert parse_declaration(forgotten.notation())["forget_failure_reasons"] is True


def test_finding_15_partial_bridge_records_closure_for_composition():
    state = _state(toy)
    bridge = BridgeRecord("partial", ("toy", "int"), ("toy", "int"), n.Var("x"),
                          (0, 1), (("inc", "inc"),), {}, 1, ("inc",))
    evidence = check(bridge, state)
    assert evidence["closed"] is False
    record = replace(bridge, evidence=evidence)
    assert record.closed is False
    assert json.loads(to_json([record]))["bridges"][0]["closed"] is False
    assert check(replace(bridge, interface=(("absv", "absv"),),
                         depends_on=("absv",)), state)["closed"] is True


def test_finding_30_unchecked_comparator_cannot_prove_false_bridge():
    state = _state(toy)
    bridge = BridgeRecord("false", ("toy", "int"), ("toy", "int"), n.Var("x"),
                          (0, 1), (("inc", "neg"),), {}, 1, ("inc", "neg"))
    with pytest.raises(BridgeRefuted, match="counterexample"):
        check(bridge, state)
    with pytest.raises(BridgeRefuted, match="abstraction"):
        check(replace(bridge, abstraction=lambda left, right: True), state)
    with pytest.raises(BridgeRefuted, match="abstraction"):
        check(replace(bridge, abstraction="unregistered"), state)


def test_finding_32_interface_and_object_dependencies_fix_bridge_layer():
    state = _invented_record()
    bridge = next(record for record in propose(state, max_bridges=20, seed=19)
                  if record.map == n.Call("A1.value", (n.Var("x"),)) and
                  ("f1", "inc") in record.interface)
    assert {"A1", "A1.value", "f1", "inc"} <= set(bridge.depends_on)
    assert bridge.layer == 1 + state.layer("f1")
    with pytest.raises(BridgeRefuted, match="layer"):
        check(replace(bridge, layer=0), state)
    with pytest.raises(BridgeRefuted, match="dependencies"):
        check(replace(bridge, depends_on=tuple(dep for dep in bridge.depends_on if dep != "f1")), state)
