"""Object moves and the generator's object obligations."""

import os
import random
import time
from collections import Counter
from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms import objects as core_objects
from opulse.atoms.spec import Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, GenState, Rejection, Signature
from opulse.gen_v2.kinds.objects import normalize_object_spec, sealed_violation
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.object import (
    MOVES,
    ObjectMove,
    _candidate,
    _compose,
    _constant,
    _refine,
    object_atoms,
    release_object_name,
)
from opulse.gen_v2.run import generate, load, save
from opulse.gen_v2.worlds import (
    action,
    automata,
    circuits,
    dice,
    grammar,
    hidden,
    integer,
    lists,
    rhythm,
    toy,
    toy_truth,
    versions,
)
from opulse.gen_v2.worlds.toy import gen_world


def state():
    world = gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))


def operation(state_, body, inputs=("int",), output="int"):
    name = state_.names.fresh("operation")
    spec = OperationSpec(name, "transform", tuple(Edge(sort) for sort in inputs),
                         Edge(output), "generated", extra={"input_names": ["x"]})
    references = tuple(sorted(n.references(body)))
    layer = 1 + max((state_.layer(reference) for reference in references), default=0)
    definition = Definition(name, "operation", "invented", layer, references, spec, body)
    return admit(state_, Candidate(definition, Signature(inputs, output), "op.test"))


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
@pytest.mark.parametrize("adapter", (lists, circuits, action, versions, integer, toy, toy_truth),
                         ids=lambda adapter: adapter.__name__.rsplit(".", 1)[-1])
def test_object_moves_across_world_adapters(adapter):
    world = adapter.gen_world()
    if "object" not in world.open_kinds:
        pytest.skip("adapter does not open the object kind")

    generated = generate(world, target=60, seed=19, per_kind_min=0, layer_target=0,
                         moves=MOVES)
    objects = list(generated.entries.values())
    assert 60 <= len(objects) and generated.attempts <= 180
    assert all(entry.kind == "object" and generated.library.get(entry.name).evidence
               for entry in objects)
    assert {entry.move for entry in objects} >= {"obj.record", "obj.variant", "obj.recursive",
                                                "obj.refine", "obj.seal"}
    world_sorts = {name for name in world.sorts if name not in ("int", "bool", "str", "bit",
                                                                 world.truth_sort)}
    if world_sorts:
        assert any(any(sort in world_sorts for fields in
                       generated.library.get(entry.name).spec.tags.values() for _, sort in fields)
                   for entry in objects if entry.move in ("obj.record", "obj.variant", "obj.recursive"))
    print(f"{world.name}: objects={len(objects)} attempts={generated.attempts} "
          f"rejections={Counter((item.stage, item.reason.split(':')[0]) for item in generated.rejections)}")


@pytest.mark.parametrize("adapter", (lists, toy), ids=lambda adapter: adapter.__name__.rsplit(".", 1)[-1])
def test_small_object_moves_across_world_adapters(adapter):
    world = adapter.gen_world()
    generated = generate(world, target=8, seed=19, per_kind_min=0, layer_target=0,
                         time_limit=12, moves=MOVES)
    assert len(generated.entries) == 8
    assert all(entry.kind == "object" and generated.library.get(entry.name).evidence
               for entry in generated.entries.values())


def test_small_object_moves_are_deterministic():
    def snapshot():
        world = toy.gen_world()
        generated = generate(world, target=12, seed=29, per_kind_min=0,
                             layer_target=0, time_limit=12, moves=MOVES)
        return [(entry.name, entry.move, entry.depends_on, entry.fingerprint)
                for entry in generated.entries.values()]

    first = snapshot()
    assert len(first) == 12
    assert snapshot() == first


def test_refine_without_matching_world_decider_returns_none():
    world = circuits.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), {"bits": world.sorts["bits"]})
    assert _refine(current, random.Random(3), "obj.refine") is None


def test_refine_excludes_the_truth_sort():
    world = lists.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), {"list": world.sorts["list"]})
    proposed = _refine(current, random.Random(3), "obj.refine")
    assert world.truth_sort == "list"
    assert proposed is None


def test_record_witness_calls_an_invented_operation():
    current = state()
    made = operation(current, n.Call("add", (n.Var("x"), n.Lit(2))))
    assert isinstance(made, Entry)
    proposals = (_compose(current, random.Random(seed), "obj.record") for seed in range(10))
    record = next(candidate for candidate in proposals if made.name in candidate.defn.depends_on)
    assert record.defn.layer == made.layer + 1
    assert isinstance(admit(current, record), Entry)
    result = kernel.call(record.defn.name, (), current.library.scope()).outcome
    assert isinstance(result, Ok)
    assert result.value in current.sorts[record.defn.name].values
    assert current.library.get(record.defn.name).evidence is not None


def test_named_constant_uses_observed_typical_values_without_truth():
    current = state()
    first = operation(current, n.Call("add", (n.Var("x"), n.Lit(2))))
    second = operation(current, n.Call("mul", (n.Call(first.name, (n.Var("x"),)),
                                              n.Lit(2))))
    assert isinstance(second, Entry)
    current.entries["q100"] = Entry("q100", "observation", 1, Signature(("int",), "int"),
                                    "obs.test", (), examples=[((), {"ok": {"t": "int", "v": 4}}, 0)])
    proposals = (_constant(current, random.Random(seed)) for seed in range(20))
    constant = next(item for item in proposals if item is not None and
                    item.meta["observation_sources"])
    assert constant.meta["observation_sources"] == ["q100"]
    assert n.Lit(4) in constant.defn.body.args
    assert isinstance(admit(current, constant), Entry)


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
@pytest.mark.parametrize("adapter", (lists, circuits, action, versions, integer, toy, toy_truth,
                                     automata, dice, grammar, hidden, rhythm),
                         ids=lambda adapter: adapter.__name__.rsplit(".", 1)[-1])
def test_all_moves_deep_objects(adapter):
    world = adapter.gen_world()
    if "object" not in world.open_kinds:
        pytest.skip("adapter does not open the object kind")
    generated = generate(world, 400, 1, per_kind_min=50, layer_target=10, time_limit=300)
    objects = [entry for entry in generated.entries.values() if entry.kind == "object"]
    assert len(objects) >= 50
    assert generated.max_layer("object") >= 10
    assert sum(any(reference in generated.entries and
                   generated.entries[reference].kind == "operation"
                   for reference in entry.depends_on) for entry in objects) >= 0.3 * len(objects)


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_moves_admit_sixty_mixed_objects_deterministically():
    def run(seed):
        current = state()
        first = operation(current, n.Call("add", (n.Var("x"), n.Lit(3))))
        assert isinstance(first, Entry)
        second = operation(current, n.Call("mul", (n.Call(first.name, (n.Var("x"),)), n.Lit(2))))
        assert isinstance(second, Entry)
        randomizer = random.Random(seed)
        start = time.monotonic()
        for index in range(180):
            proposal = MOVES[index % len(MOVES)](current, randomizer)
            if proposal is not None:
                admit(current, proposal)
        objects = [entry for entry in current.entries.values() if entry.kind == "object"]
        assert len(objects) >= 60
        assert current.max_layer("object") >= 6
        assert {entry.move for entry in objects} == {move.name for move in MOVES}
        assert all(current.library.get(entry.name).evidence for entry in objects)
        assert all(current.library.get(entry.name).status == "promoted" for entry in objects)
        for entry in objects:
            if entry.move == "obj.constant":
                continue
            definition = current.library.get(entry.name)
            assert any(isinstance(node, n.Call) and node.fn in current.sorts[entry.name].constructors
                       for node in n.walk(definition.body))
            witness = kernel.call(entry.name, (), current.library.scope()).outcome
            assert isinstance(witness, Ok)
            assert witness.value in current.sorts[entry.name].values
        return current, [(entry.name, entry.move, entry.fingerprint) for entry in objects], time.monotonic() - start

    current, first, elapsed = run(29)
    _, second, _ = run(29)
    assert first == second
    recursive = next(item for item in current.entries.values() if item.move == "obj.recursive")
    sort = current.sorts[recursive.name]
    assert current.world.measures[sort.name] == [(f"{sort.name}.tail", f"{sort.name}.size")]
    assert current.world.bases[sort.name] == [f"{sort.name}.is_nil"]
    constructor = kernel.call(f"{sort.name}.nil", (), current.library.scope())
    assert constructor.outcome == Ok(Card(sort.name, "nil"))
    assert kernel.call(f"{sort.name}.size", (constructor.outcome.value,), current.library.scope()).outcome == Ok(1)
    record = next(item for item in current.entries.values() if item.move == "obj.record")
    record_sort = current.sorts[record.name]
    pair = record_sort.values[0]
    assert kernel.call(f"{record.name}.pair", pair.fields, current.library.scope()).outcome == Ok(pair)
    assert kernel.call(f"{record.name}.field0", (pair,), current.library.scope()).outcome == Ok(pair.fields[0])
    assert kernel.call(f"{record.name}.field0", (Card(record.name, "other"),),
                       current.library.scope()).outcome == Bottom("wrong_tag")
    later = operation(current, n.Call(f"{record.name}.field0", (n.Var("x"),)),
                      (record.name,), current.signature(f"{record.name}.field0").output)
    assert isinstance(later, Entry)
    constructed = operation(current,
                            n.Call(f"{record.name}.pair", (n.Var("x"), n.Lit(pair.fields[1]))),
                            (current.signature(f"{record.name}.field0").output,), record.name)
    assert isinstance(constructed, Entry)
    constant = next(item for item in current.entries.values() if item.move == "obj.constant")
    assert current.extra_signatures[constant.name] == Signature((), constant.meta["output"])
    assert current.signature(constant.name) == current.extra_signatures[constant.name]
    assert constant.name in current.callables("operation", inputs=(), output=constant.meta["output"])
    print(f"objects={len(first)} rejects={Counter((r.stage, r.reason.split(':')[0]) for r in current.rejections)} "
          f"max_layer={current.max_layer('object')} seconds={elapsed:.2f}")


def test_nested_object_witnesses_have_real_dependencies_and_layers():
    current = state()
    refine_name = current.names.fresh("object")
    refine = ObjectSpec(refine_name, "refine", base="int",
                        valid=n.Call("lt", (n.Var("x"), n.Lit(2))))
    refined = _candidate(current, refine, "obj.refine",
                         n.Call(f"{refine_name}.make", (n.Lit(0),)),
                         (Card(refine_name, "val", (0,)),))
    assert isinstance(admit(current, refined), Entry)
    assert refined.defn.layer == 1
    assert kernel.call(refine_name, (), current.library.scope()).outcome == Ok(Card(refine_name, "val", (0,)))

    first_name = current.names.fresh("object")
    first = ObjectSpec(first_name, "compose", tags={"pair": [["field0", refine_name],
                                                  ["field1", "int"]]})
    first_body = n.Call(f"{first_name}.pair", (n.Call(refine_name), n.Lit(0)))
    first_card = Card(first_name, "pair", (Card(refine_name, "val", (0,)), 0))
    record = _candidate(current, first, "obj.record", first_body, (first_card,))
    assert isinstance(admit(current, record), Entry)
    assert record.defn.depends_on == (refine_name, f"{first_name}.pair")
    assert record.defn.layer == 2
    assert record.meta["sort_deps"] == [refine_name]
    assert kernel.call(first_name, (), current.library.scope()).outcome == Ok(first_card)

    next_name = current.names.fresh("object")
    next_spec = ObjectSpec(next_name, "compose", tags={"pair": [["field0", first_name],
                                                      ["field1", "bool"]]})
    next_body = n.Call(f"{next_name}.pair", (n.Call(first_name), n.Lit(False)))
    next_card = Card(next_name, "pair", (first_card, False))
    next_record = _candidate(current, next_spec, "obj.record", next_body, (next_card,))
    assert isinstance(admit(current, next_record), Entry)
    assert next_record.defn.layer == 3
    assert next_record.defn.depends_on == (first_name, f"{next_name}.pair")
    assert kernel.call(next_name, (), current.library.scope()).outcome == Ok(next_card)


def test_finding_1_variant_depends_on_invented_field_outside_witness_tag():
    current = state()
    first = _compose(current, random.Random(0), "obj.record")
    assert isinstance(admit(current, first), Entry)
    name = current.names.fresh("object")
    spec = ObjectSpec(name, "compose", tags={"none": [], "some": [["child", first.defn.name]]})
    candidate = _candidate(current, spec, "obj.variant", n.Call(f"{name}.none"),
                           (Card(name, "none"), Card(name, "some", (first.new_sorts[0].values[0],))))
    assert first.defn.name in candidate.defn.depends_on
    assert candidate.defn.depends_on == tuple(sorted(n.references(candidate.defn.body)))
    assert candidate.defn.layer >= first.defn.layer + 1
    assert isinstance(admit(current, candidate), Entry)
    assert kernel.call(name, (), current.library.scope()).outcome == Ok(Card(name, "none"))


def test_unused_sort_dependency_does_not_evaluate_its_witness():
    current = state()
    first_name = current.names.fresh("object")
    first_spec = ObjectSpec(first_name, "compose", tags={"nil": []})
    expensive = n.Let("work", n.Call("inc", (n.Lit(1),)), n.Call(f"{first_name}.nil"))
    first = _candidate(current, first_spec, "obj.test", expensive, (Card(first_name, "nil"),))
    assert isinstance(admit(current, first), Entry)

    second_name = current.names.fresh("object")
    second_spec = ObjectSpec(second_name, "compose", tags={"none": [], "some": [["child", first_name]]})
    plain = n.Call(f"{second_name}.none")
    second = _candidate(current, second_spec, "obj.test", plain,
                        (Card(second_name, "none"), Card(second_name, "some", (Card(first_name, "nil"),))))
    assert first_name in second.defn.depends_on
    assert isinstance(admit(current, second), Entry)
    scope = current.library.scope()
    baseline = kernel.evaluate(plain, scope=scope)
    actual = kernel.call(second_name, (), scope)
    assert actual.outcome == baseline.outcome == Ok(Card(second_name, "none"))
    assert actual.steps == baseline.steps


def test_finding_1_object_hook_rejects_false_layer_with_constructor_reference():
    current = state()
    candidate = _compose(current, random.Random(0), "obj.record")
    bad = replace(candidate, defn=replace(candidate.defn, layer=candidate.defn.layer + 1))
    result = admit(current, bad)
    assert isinstance(result, Rejection) and result.stage == "check"
    assert "layer must be" in result.reason


def test_finding_1_refine_depends_on_invented_base_valid_and_canon():
    current = state()
    base = _candidate(current, ObjectSpec("A1", "compose", tags={"pair": [["value", "int"],
                                                                      ["other", "int"]]}),
                      "obj.record", n.Call("A1.pair", (n.Lit(0), n.Lit(0))),
                      tuple(Card("A1", "pair", (value, other))
                            for value in range(3) for other in range(2)))
    assert isinstance(admit(current, base), Entry)
    valid = operation(current, n.Call("is_pos", (n.Call("A1.value", (n.Var("x"),)),)),
                      ("A1",), "bool")
    canon = operation(current, n.Call("A1.pair", (n.Lit(1), n.Call("A1.other", (n.Var("x"),)))),
                      ("A1",), "A1")
    assert isinstance(valid, Entry) and isinstance(canon, Entry)
    name = "B2"
    spec = ObjectSpec(name, "refine", base="A1", valid=n.Call(valid.name, (n.Var("x"),)),
                      canon=n.Call(canon.name, (n.Var("x"),)))
    body = n.Call(f"{name}.make", (n.Lit(Card("A1", "pair", (1, 0))),))
    candidate = _candidate(current, spec, "obj.refine", body,
                           (Card(name, "val", (Card("A1", "pair", (1, 0)),)),))
    assert {"A1", valid.name, canon.name} <= set(candidate.defn.depends_on)
    assert candidate.defn.layer == 1 + max(current.layer(part) for part in candidate.defn.depends_on)
    assert isinstance(admit(current, candidate), Entry)
    assert kernel.call(name, (), current.library.scope()).outcome == Ok(candidate.new_sorts[0].values[0])
    before = current.library._deps_hash(name)
    original = current.library.get(canon.name)
    current.library._definitions[canon.name] = replace(
        original, body=n.Call("A1.pair", (n.Lit(2), n.Call("A1.other", (n.Var("x"),)))))
    try:
        assert current.library._deps_hash(name) != before
    finally:
        current.library._definitions[canon.name] = original


def test_refine_witness_uses_rules_without_changing_value_or_failure():
    current = state()
    valid = operation(current, n.Call("is_pos", (
        n.Call("add", (n.Var("x"), n.Lit(1))),)), output="bool")
    canon = operation(current, n.Call("maxv", (n.Var("x"), n.Lit(2))))
    assert isinstance(valid, Entry) and isinstance(canon, Entry)
    for name, base_value, expected in (("R10", 2, Ok(Card("R10", "val", (2,)))),
                                       ("S11", -2, Bottom("invalid"))):
        spec = ObjectSpec(name, "refine", base="int",
                          valid=n.Call(valid.name, (n.Var("x"),)),
                          canon=n.Call(canon.name, (n.Var("x"),)))
        plain = n.Call(f"{name}.make", (n.Lit(base_value),))
        candidate = _candidate(current, spec, "obj.refine", plain,
                               (Card(name, "val", (2,)),))
        scope = current.library.scope().extend(candidate.extra_atoms)
        limits = kernel.Limits(fuel=current.world.fuel)
        raw = kernel.evaluate(plain, {}, scope, limits)
        witness = kernel.evaluate(candidate.defn.body, {}, scope, limits)
        promoted = kernel.call(name, (), scope, limits)
        assert raw.outcome == witness.outcome == promoted.outcome == expected
        assert witness.steps == promoted.steps > raw.steps
        assert {valid.name, canon.name} <= set(candidate.defn.depends_on)
        assert candidate.defn.depends_on == tuple(sorted(n.references(candidate.defn.body)))


def test_rejected_object_proposal_can_release_its_name():
    current = state()
    first = _compose(current, random.Random(1), "obj.recursive")
    assert isinstance(admit(current, first), Entry)
    before = current.names.counter, set(current.names.taken)
    duplicate = _compose(current, random.Random(1), "obj.recursive")
    assert duplicate.defn.name != first.defn.name
    rejected = admit(current, duplicate)
    assert isinstance(rejected, Rejection)
    release_object_name(current, duplicate)
    assert (current.names.counter, current.names.taken) == before
    assert _compose(current, random.Random(1), "obj.recursive").defn.name == duplicate.defn.name


def test_object_move_reuses_rejected_name_at_next_proposal():
    current = state()
    move = next(item for item in MOVES if item.name == "obj.recursive")
    first = move(current, random.Random(1))
    assert isinstance(admit(current, first), Entry)
    duplicate = move(current, random.Random(1))
    assert isinstance(admit(current, duplicate), Rejection)
    next_proposal = move(current, random.Random(1))
    assert next_proposal.defn.name == duplicate.defn.name


def test_finding_9_refused_recursive_proposal_does_not_register_hints():
    current = state()
    measures, bases = dict(current.world.measures), dict(current.world.bases)
    candidate = _compose(current, random.Random(1), "obj.recursive")
    assert candidate is not None
    assert current.world.measures == measures and current.world.bases == bases
    bad = replace(candidate, new_sorts=(replace(candidate.new_sorts[0],
                                                values=(Card("other", "nil"),)),))
    assert isinstance(admit(current, bad), Rejection)
    assert current.world.measures == measures and current.world.bases == bases
    accepted = _compose(current, random.Random(1), "obj.recursive")
    assert isinstance(admit(current, accepted), Entry)
    assert accepted.defn.name not in current.world.measures
    ObjectMove("obj.record")(current, random.Random(0))
    assert current.world.measures[accepted.defn.name] == [
        (f"{accepted.defn.name}.tail", f"{accepted.defn.name}.size")]
    assert current.world.bases[accepted.defn.name] == [f"{accepted.defn.name}.is_nil"]


def test_finding_10_recursive_size_rejects_malformed_cards_and_counts_nodes():
    current = state()
    candidate = _compose(current, random.Random(1), "obj.recursive")
    assert isinstance(admit(current, candidate), Entry)
    name = candidate.defn.name
    scope = current.library.scope()
    nil = Card(name, "nil")
    head = next(value.fields[0] for value in candidate.new_sorts[0].values
                if value.tag == "cons")
    cons = Card(name, "cons", (head, nil))
    for invalid in (123, Card("elsewhere", "nil"), Card(name, "unknown"),
                    Card(name, "cons", (head,)),
                    Card(name, "cons", (head, Card("elsewhere", "nil")))):
        assert kernel.call(f"{name}.size", (invalid,), scope).outcome == Bottom("wrong_tag")
    assert kernel.call(f"{name}.size", (cons,), scope).outcome == Ok(2)
    assert kernel.call(f"{name}.size", (Card(name, "cons", (head, cons)),), scope).outcome == Ok(3)


def test_finding_12_explicit_record_normalizer_does_not_patch_core(tmp_path):
    assert core_objects.object_atoms.__module__ == "opulse.atoms.objects"
    spec = ObjectSpec("A1", "compose", tags={"pair": {"left": "int", "right": "int"}})
    normalized = normalize_object_spec(spec)
    assert spec.tags["pair"] == {"left": "int", "right": "int"}
    assert normalized.tags["pair"] == [["left", "int"], ["right", "int"]]
    current = state()
    candidate = _candidate(current, spec, "obj.record",
                           n.Call("A1.pair", (n.Lit(1), n.Lit(2))),
                           (Card("A1", "pair", (1, 2)),))
    assert isinstance(admit(current, candidate), Entry)
    assert kernel.call("A1.left", (Card("A1", "pair", (1, 2)),),
                       current.library.scope()).outcome == Ok(1)
    path = tmp_path / "normalized.json"
    save(current, path)
    restored = load(current.world, path)
    assert kernel.call("A1.left", (Card("A1", "pair", (1, 2)),),
                       restored.library.scope()).outcome == Ok(1)


def test_refine_uses_non_integer_canon_and_decide_callable():
    current = state()
    record_name = current.names.fresh("object")
    spec = ObjectSpec(record_name, "compose", tags={"pair": [["field0", "int"],
                                                    ["field1", "int"]]})
    values = tuple(Card(record_name, "pair", (first, second))
                   for first in (0, 1, 2) for second in (0, 1))
    record = _candidate(current, spec, "obj.record",
                        n.Call(f"{record_name}.pair", (n.Lit(0), n.Lit(0))), values)
    assert isinstance(admit(current, record), Entry)
    record_sort = record.defn.name
    canon = operation(current, n.Call(f"{record_sort}.pair", (
        n.Lit(0), n.Call(f"{record_sort}.field1", (n.Var("x"),)))),
        (record_sort,), record_sort)
    assert isinstance(canon, Entry)
    current.sorts = {record_sort: current.sorts[record_sort]}
    predicate = operation(current, n.Call("is_zero", (n.Call(f"{record_sort}.field0",
                                                        (n.Var("x"),)),)), (record_sort,), "bool")
    assert isinstance(predicate, Entry)
    candidate = _refine(current, random.Random(0), "obj.refine")
    assert candidate is not None
    assert candidate.defn.spec.base == record_sort
    assert canon.name in n.references(candidate.defn.spec.canon)
    assert predicate.name in n.references(candidate.defn.spec.valid)
    assert isinstance(admit(current, candidate), Entry)
    evidence = current.library.get(candidate.defn.name).evidence
    assert {"valid_bool", "canon_total", "canon_idempotent", "canon_keeps_valid",
            "interface_respects_canon", "unfold_equivalence"} <= set(evidence.checks)


def test_sealed_compose_exposes_constructor_and_accessor():
    current = state()
    candidate = _compose(current, random.Random(3), "obj.seal")
    if candidate.defn.spec.form != "compose":
        raise AssertionError("expected a compose object")
    assert isinstance(admit(current, candidate), Entry)
    sort = current.sorts[candidate.defn.name]
    assert sort.sealed and sort.interface == candidate.defn.spec.interface
    assert set(sort.constructors) <= set(sort.interface)
    assert set(sort.accessors) & set(sort.interface)
    assert isinstance(kernel.call(candidate.defn.name, (), current.library.scope()).outcome, Ok)


def test_refine_bad_canon_fails_named_obligations():
    scenarios = (
        (n.Lit(True), n.Call("is_pos", (n.Var("x"),)), (), "canon_total"),
        (n.Call("lt", (n.Var("x"), n.Lit(5))), n.Call("inc", (n.Var("x"),)), (), "canon_idempotent"),
        (n.Call("is_pos", (n.Var("x"),)), n.Call("neg", (n.Var("x"),)), (), "canon_keeps_valid"),
        (n.Lit(True), n.Call("absv", (n.Var("x"),)), ("neg",), "interface_respects_canon"),
        (n.Lit(1), None, (), "valid_bool"),
    )
    for valid, canon, interface, check in scenarios:
        current = state()
        name = current.names.fresh("object")
        spec = ObjectSpec(name, "refine", base="int", valid=valid, canon=canon, interface=interface)
        body = n.Call(f"{name}.make", (n.Lit(0),))
        candidate = _candidate(current, spec, "obj.test", body)
        result = admit(current, candidate)
        assert isinstance(result, Rejection), (check, result)
        assert check in result.reason, (check, result)


@pytest.mark.parametrize("value", (
    Card("B1", "not_declared", ("illegal",)),
    Card("B1", "ok", (0,)),
    Card("B1", "ok", ("illegal", 0)),
    Card("B1", "ok", (Card("B1", "ok", (0, 1)), 0)),
))
def test_compose_refuses_bogus_probe_values(value):
    current = state()
    spec = ObjectSpec("B1", "compose", tags={"ok": [["left", "int"], ["right", "int"]]})
    proposal = _candidate(current, spec, "obj.record",
                          n.Call("B1.ok", (n.Lit(0), n.Lit(1))), (value,))
    result = admit(current, proposal)
    assert isinstance(result, Rejection)
    assert result.stage == "verify" and "values_in_sort" in result.reason


@pytest.mark.parametrize(("adapter", "sort", "invalid"), (
    (integer, "nat", 0), (hidden, "Branch", "B"),
), ids=("integer-nat", "hidden-branch"))
def test_compose_probe_must_pass_core_constructor(adapter, sort, invalid):
    world = adapter.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    spec = ObjectSpec("A501", "compose", tags={"some": [["item", sort], ["index", "int"]]})
    value = Card("A501", "some", (invalid, 0))
    candidate = _candidate(current, spec, "obj.record", n.Call("A501.some", (n.Lit(invalid), n.Lit(0))),
                           (value,))
    result = admit(current, candidate)
    assert isinstance(result, Rejection) and "values_in_sort" in result.reason
    assert "A501" not in current.entries
    assert "B1" not in current.sorts


def test_compose_refuses_malformed_witness_with_valid_probes():
    current = state()
    spec = ObjectSpec("B1", "compose", tags={"ok": [["left", "int"], ["right", "int"]]})
    candidate = _candidate(current, spec, "obj.record",
                           n.Call("B1.ok", (n.Lit("wrong"), n.Lit(1))),
                           (Card("B1", "ok", (0, 1)),))
    result = admit(current, candidate)
    assert isinstance(result, Rejection) and "witness_value" in result.reason


def test_refine_refuses_noncanonical_and_invalid_probe_values():
    for value in (Card("B1", "val", (-1,)), Card("B1", "val", (1, 2)),
                  Card("B1", "other", (1,))):
        current = state()
        spec = ObjectSpec("B1", "refine", base="int",
                          valid=n.Call("is_pos", (n.Var("x"),)))
        candidate = _candidate(current, spec, "obj.refine",
                               n.Call("B1.make", (n.Lit(1),)), (value,))
        result = admit(current, candidate)
        assert isinstance(result, Rejection) and "values_in_sort" in result.reason
    current = state()
    spec = ObjectSpec("B1", "refine", base="int", valid=n.Lit(True),
                      canon=n.Call("absv", (n.Var("x"),)))
    candidate = _candidate(current, spec, "obj.refine", n.Call("B1.make", (n.Lit(2),)),
                           (Card("B1", "val", (-2,)),))
    result = admit(current, candidate)
    assert isinstance(result, Rejection) and "values_in_sort" in result.reason


def test_mutual_group_requires_atomic_admission():
    current = state()
    spec = ObjectSpec("A1", "compose", tags={"nil": [], "next": [["child", "A2"]]},
                      group=("A2",))
    body = n.Call("A1.nil")
    definition = Definition("A1", "object", "invented", 1, ("A1.nil",), spec, body)
    result = admit(current, Candidate(definition, None, "obj.group"))
    assert isinstance(result, Rejection)
    assert "group" in result.reason


def test_nested_compose_values_and_core_size(tmp_path):
    current = state()
    first = _candidate(current, ObjectSpec("A1", "compose", tags={"leaf": [["value", "int"], ["other", "int"]]}),
                       "obj.record", n.Call("A1.leaf", (n.Lit(1), n.Lit(2))),
                       (Card("A1", "leaf", (1, 2)),))
    assert isinstance(admit(current, first), Entry)
    second = _candidate(current, ObjectSpec("A2", "compose", tags={"pair": [["child", "A1"], ["value", "int"]]}),
                        "obj.record", n.Call("A2.pair", (n.Call("A1", ()), n.Lit(3))),
                        (Card("A2", "pair", (Card("A1", "leaf", (1, 2)), 3)),))
    assert isinstance(admit(current, second), Entry)
    assert current.library.scope().resolve("A2.fold") is not None
    assert kernel.call("A2.size", (second.new_sorts[0].values[0],), current.library.scope()).outcome == Ok(1)
    assert sum(atom.name == "A2.size" for atom in second.extra_atoms) == 1
    path = tmp_path / "objects.json"
    save(current, path)
    restored = load(current.world, path)
    assert kernel.call("A2.pair", (Card("A1", "leaf", (1, 2)), 3),
                       restored.library.scope()).outcome == Ok(second.new_sorts[0].values[0])
    witnesses = [atom for name in ("A1", "A2") for atom in
                 object_atoms(restored.library.get(name).spec, restored)]
    assert [atom.body for atom in witnesses] == [restored.library.get(name).body
                                                 for name in ("A1", "A2")]
    scope = restored.library.scope().extend(witnesses)
    assert kernel.call("A2", (), scope).outcome == Ok(second.new_sorts[0].values[0])
    assert restored.library.scope().resolve("A2.fold") is not None


def test_recursive_size_uses_core_structural_measure():
    current = state()
    spec = ObjectSpec("A1", "compose", tags={"nil": [],
                                              "cons": [["head", "int"], ["tail", "A1"]]})
    nil = Card("A1", "nil")
    cons = Card("A1", "cons", (1, nil))
    candidate = _candidate(current, spec, "obj.recursive",
                           n.Call("A1.cons", (n.Lit(1), n.Call("A1.nil"))), (nil, cons))
    assert sum(atom.name == "A1.size" for atom in candidate.extra_atoms) == 1
    assert isinstance(admit(current, candidate), Entry)
    assert kernel.call("A1.size", (cons,), current.library.scope()).outcome == Ok(2)
    assert current.library.scope().resolve("A1.fold") is not None


def test_seal_and_invalid_constant_are_rejected():
    current = state()
    sealed = next(move for move in MOVES if move.name == "obj.seal")(current, random.Random(3))
    assert isinstance(admit(current, sealed), Entry)
    sort = sealed.defn.name
    private = f"{sort}.base" if sealed.defn.spec.form == "refine" else f"{sort}.pair"
    if private in sealed.defn.spec.interface:
        private = f"{sort}.base" if sealed.defn.spec.form == "compose" else f"{sort}._pack"
    body = n.Call(private, (n.Lit(0),))
    name = current.names.fresh("object")
    spec = ObjectSpec(name, "constant", body=body)
    candidate = _candidate(current, spec, "obj.constant", body)
    assert sealed_violation(candidate.defn, current) is not None
    result = admit(current, candidate)
    assert isinstance(result, Rejection) and "sealed" in result.reason
    failure = n.Call("sub", (n.Lit(1),))
    name = current.names.fresh("object")
    candidate = _candidate(current, ObjectSpec(name, "constant", body=failure), "obj.constant", failure)
    assert isinstance(admit(current, candidate), Rejection)
