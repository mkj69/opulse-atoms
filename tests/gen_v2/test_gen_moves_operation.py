"""Operation move generation against the atoms-v2 admission pipeline."""

import importlib
import os
import random
import time
from collections import Counter
from dataclasses import replace

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.check import check_definition
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.atoms.values import Card
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature, Sort
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.operation import MOVES, _target, term
from opulse.gen_v2.worlds import action, circuits, classic, lists, text, toy, versions


def _state():
    world = toy.gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))


def _run(seed, target, limit=1200, moves=MOVES[:3]):
    from opulse.gen_v2 import fast

    return fast.deep(_run_inline, seed, target, limit, moves)


def _run_inline(seed, target, limit, moves):
    state = _state()
    rng = random.Random(seed)
    reasons = Counter()
    proposed = 0
    for _ in range(limit):
        candidate = rng.choice(moves)(state, rng)
        if candidate is None:
            continue
        proposed += 1
        result = admit(state, candidate)
        if isinstance(result, Entry):
            assert state.library.get(result.name).status == "promoted"
            assert state.library.get(result.name).evidence.method in ("exhaustive", "bounded")
            assert candidate.defn.depends_on == tuple(sorted(nodes.references(candidate.defn.body)))
            assert candidate.defn.layer == 1 + max((state.layer(name) for name in candidate.defn.depends_on), default=0)
            if len(state.entries) >= target:
                return state, proposed, reasons
        else:
            reasons[result.stage] += 1
    return state, proposed, reasons


def test_typed_terms_and_signatures_pass_checker():
    state = _state()
    rng = random.Random(81)
    for sort in state.sorts:
        for _ in range(24):
            body = term(state, rng, sort, {"x0": "int", "x1": "bool"}, 3)
            assert body is not None
            assert nodes.node_kinds(body) <= state.world.decl.opened_nodes()
    for move in MOVES[:3]:
        built = 0
        for _ in range(8):
            candidate = move(state, rng)
            if candidate is None:
                continue
            built += 1
            assert not check_definition(candidate.defn, state.world.decl, state.library.resolve)
            assert isinstance(admit(state, candidate), Entry) or state.rejections[-1].stage != "check"
        assert built >= 1


def test_recursion_terminates_on_the_probe_domain():
    state = _state()
    rng = random.Random(29)
    for _ in range(12):
        candidate = MOVES[2](state, rng)
        assert candidate is not None
        result = admit(state, candidate)
        assert isinstance(result, Entry) or result.stage in ("duplicate", "degenerate")
        if isinstance(result, Entry):
            assert result.steps_max > 0


def test_determinism_and_deep_run():
    first, _, _ = _run(73, 18, 50)
    second, _, _ = _run(73, 18, 50)
    assert [(item.move, item.layer, item.depends_on) for item in first.entries.values()] == [
        (item.move, item.layer, item.depends_on) for item in second.entries.values()]


def test_small_run_grows_with_multiple_dependencies():
    state, _, reasons = _run(42, 20, 120, MOVES)
    assert len(state.entries) >= 20, reasons
    assert state.max_layer() >= 4
    assert any(len(set(entry.depends_on) & state.entries.keys()) >= 2
               for entry in state.entries.values())


def test_large_probe_domains_use_recorded_bounded_evidence():
    state = _state()
    state.sorts["int"] = replace(state.sorts["int"], values=tuple(range(20)))
    candidate = MOVES[0](state, random.Random(23))
    assert candidate is not None
    assert candidate.request is not None
    assert candidate.request.method == "bounded"
    assert len(candidate.request.domain) == candidate.request.scope["size"]
    assert len(candidate.request.domain) <= 64
    result = admit(state, candidate)
    if isinstance(result, Entry):
        assert state.library.get(result.name).evidence.scope["size"] == len(candidate.request.domain)


def test_unextendable_port_result_does_not_block_circuit_composition():
    world = circuits.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    state.entries["g1"] = Entry("g1", "operation", 1,
                                Signature(("circuit",), "ports"), "op.substitute", ())
    target = _target(state, random.Random(1))
    assert target in world.signatures
    assert state.signature(target).output != "ports"


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_150_admissions_reach_layer_eight():
    state, proposed, reasons = _run(42, 150, moves=MOVES)
    assert len(state.entries) >= 150, (len(state.entries), proposed, reasons)
    assert state.max_layer() >= 8
    assert proposed <= 750, (proposed, reasons)


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_300_admissions_have_wide_and_deep_dependencies():
    started = time.monotonic()
    state, proposed, reasons = _run(42, 300, 1000, MOVES)
    fanout = [len(set(entry.depends_on) & state.entries.keys()) for entry in state.entries.values()]
    assert len(fanout) >= 300, (len(fanout), proposed, reasons)
    assert sum(width >= 2 for width in fanout) / len(fanout) >= 0.4
    assert sum(fanout) / len(fanout) >= 2
    assert 12 <= state.max_layer() <= 25
    assert len(fanout) / proposed >= 0.4
    assert time.monotonic() - started < 180
    assert any(entry.move == "op.combine" for entry in state.entries.values())


def test_over_object_uses_invented_record_operations():
    state = _state()
    sort = Sort("A7", tuple(Card("A7", "box", (value,)) for value in (0, 1, 2, 3)),
                origin="invented", defined_by="A7", constructors=("A7.box",),
                accessors=("A7.value",), testers=("A7.is_box",))
    state.sorts[sort.name] = sort
    state.library.add_atoms((kernel.Atom("A7.box", 1, lambda value: Card("A7", "box", (value,))),
                             kernel.Atom("A7.value", 1, lambda card: card.fields[0]),
                             kernel.Atom("A7.is_box", 1, lambda card: card.tag == "box")))
    state.extra_signatures.update({"A7.box": Signature(("int",), "A7"),
                                   "A7.value": Signature(("A7",), "int"),
                                   "A7.is_box": Signature(("A7",), "bool")})
    rng = random.Random(4)
    admitted = []
    for _ in range(80):
        candidate = MOVES[3](state, rng)
        if candidate is None:
            continue
        assert "A7" in (*candidate.signature.inputs, candidate.signature.output)
        if isinstance(admit(state, candidate), Entry):
            admitted.append(candidate)
    assert admitted
    assert any("A7.value" in candidate.defn.depends_on for candidate in admitted)


def test_recursive_compose_sort_uses_accessor_and_decreasing_measure():
    state = _state()
    zero = Card("A7", "end")
    one = Card("A7", "next", (zero,))
    two = Card("A7", "next", (one,))
    state.sorts["A7"] = Sort("A7", (zero, one, two), origin="invented", defined_by="A7",
                              constructors=("A7.end", "A7.next"),
                              accessors=("A7.tail",), testers=("A7.is_end",))
    state.library.add_atoms((kernel.Atom("A7.end", 0, lambda: zero),
                             kernel.Atom("A7.next", 1, lambda card: Card("A7", "next", (card,))),
                             kernel.Atom("A7.tail", 1, lambda card: card.fields[0] if card.fields else card),
                             kernel.Atom("A7.is_end", 1, lambda card: card.tag == "end"),
                             kernel.Atom("A7.size", 1, lambda card: 0 if card.tag == "end"
                                         else 1 if card.fields[0].tag == "end" else 2)))
    state.extra_signatures.update({"A7.end": Signature((), "A7"),
                                   "A7.next": Signature(("A7",), "A7"),
                                   "A7.tail": Signature(("A7",), "A7"),
                                   "A7.is_end": Signature(("A7",), "bool"),
                                   "A7.size": Signature(("A7",), "int")})
    state.world.bases["A7"] = ["A7.is_end"]
    state.world.measures["A7"] = [("A7.tail", "A7.size")]
    rng = random.Random(16)
    for _ in range(40):
        candidate = MOVES[2](state, rng)
        if candidate and candidate.signature.inputs == ("A7",):
            assert "A7.tail" in candidate.defn.depends_on
            assert "A7.size" in candidate.defn.depends_on
            result = admit(state, candidate)
            if isinstance(result, Entry):
                return
    assert False, "recursive invented sort was not selected"


def test_classic_counter_recursion_uses_binary_step():
    state = _state()
    state.world.decl = replace(state.world.decl, dialect="legacy-v1",
                               combinators={**state.world.decl.combinators, "recursion": "legacy"})
    state.world.dialect = "legacy-v1"
    state.library = GenLibrary(state.world.decl, state.world.atoms, state.world.dialect)
    state.world.measures.clear()
    state.world.counters["int"] = [("sub", 1, "is_zero")]
    state.sorts["int"] = replace(state.sorts["int"], values=tuple(range(5)))
    rng = random.Random(17)
    for _ in range(30):
        candidate = MOVES[2](state, rng)
        assert candidate is not None
        assert candidate.defn.body.measure == "legacy"
        assert "sub" in candidate.defn.depends_on
        if isinstance(admit(state, candidate), Entry):
            return
    assert False, "no interesting classic counter was admitted"


def test_classic_counter_infers_missing_zero_test():
    state = _state()
    state.world.decl = replace(state.world.decl, dialect="legacy-v1",
                               combinators={**state.world.decl.combinators, "recursion": "legacy"})
    state.world.dialect = "legacy-v1"
    state.library = GenLibrary(state.world.decl, state.world.atoms, state.world.dialect)
    state.world.measures.clear()
    state.world.counters["int"] = [("sub", 1, None)]
    state.world.bases.clear()
    state.sorts["int"] = replace(state.sorts["int"], values=tuple(range(5)))
    candidate = MOVES[2](state, random.Random(17))
    assert candidate is not None
    assert "is_zero" in candidate.defn.depends_on
    assert "sub" in candidate.defn.depends_on


def test_invented_decreasing_counter_step():
    state = _state()
    name = state.names.fresh("operation")
    body = nodes.Call("maxv", (nodes.Lit(0), nodes.Call("sub", (nodes.Var("x0"), nodes.Lit(2)))))
    definition = Definition(name, "operation", "invented", 1, ("maxv", "sub"),
                            OperationSpec(name, "transform", (Edge("int"),), Edge("int"),
                                          "Decrease a positive counter by two.",
                                          extra={"input_names": ["x0"]}), body)
    result = admit(state, Candidate(definition, Signature(("int",), "int"), "op.substitute"))
    assert isinstance(result, Entry), result
    rng = random.Random(10)
    for _ in range(60):
        candidate = MOVES[2](state, rng)
        if candidate and candidate.meta.get("step") == name:
            assert isinstance(admit(state, candidate), Entry)
            return
    assert False, "invented decreasing step was not selected"


def test_recursive_list_can_map_with_constructor():
    state = _state()
    nil = Card("A7", "nil")
    one = Card("A7", "cons", (1, nil))
    two = Card("A7", "cons", (2, one))
    state.sorts["A7"] = Sort("A7", (nil, one, two), "invented", "A7",
                              ("A7.nil", "A7.cons"), ("A7.head", "A7.tail"), ("A7.is_nil",))
    state.library.add_atoms((kernel.Atom("A7.nil", 0, lambda: nil),
                             kernel.Atom("A7.cons", 2, lambda head, tail: Card("A7", "cons", (head, tail))),
                             kernel.Atom("A7.head", 1, lambda card: card.fields[0] if card.fields else 0),
                             kernel.Atom("A7.tail", 1, lambda card: card.fields[1] if card.fields else card),
                             kernel.Atom("A7.is_nil", 1, lambda card: card.tag == "nil"),
                             kernel.Atom("A7.size", 1, lambda card: 0 if card.tag == "nil"
                                         else 1 if card.fields[1].tag == "nil" else 2)))
    state.extra_signatures.update({"A7.nil": Signature((), "A7"),
                                   "A7.cons": Signature(("int", "A7"), "A7"),
                                   "A7.head": Signature(("A7",), "int"),
                                   "A7.tail": Signature(("A7",), "A7"),
                                   "A7.is_nil": Signature(("A7",), "bool"),
                                   "A7.size": Signature(("A7",), "int")})
    state.world.bases["A7"] = ["A7.is_nil"]
    state.world.measures["A7"] = [("A7.tail", "A7.size")]
    rng = random.Random(3)
    for _ in range(100):
        candidate = MOVES[2](state, rng)
        if (candidate and candidate.signature == Signature(("A7",), "A7")
                and isinstance(admit(state, candidate), Entry)):
            assert "A7.cons" in candidate.defn.depends_on
            return
    assert False, "no interesting recursive map was admitted"


def test_specialization_uses_two_inputs_of_a_ternary_atom():
    world = versions.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    move = next(move for move in MOVES if move.name == "op.specialize")
    rng = random.Random(11)
    candidates = [move(state, rng) for _ in range(24)]
    assert any(candidate is not None and len(candidate.signature.inputs) == 2
               and not check_definition(candidate.defn, world.decl, state.library.resolve)
               for candidate in candidates)


def test_branch_can_use_a_separate_guard_input():
    world = action.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    rng = random.Random(13)
    for _ in range(80):
        candidate = MOVES[1](state, rng)
        if candidate is not None and candidate.signature.inputs == ("Bot", "int"):
            assert not check_definition(candidate.defn, world.decl, state.library.resolve)
            assert isinstance(admit(state, candidate), Entry)
            return
    assert False, "no guarded two-input robot operation was admitted"


def test_measured_recursion_uses_the_declared_list_step():
    world = lists.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    rng = random.Random(4)
    for _ in range(12):
        candidate = MOVES[2](state, rng)
        if candidate is not None and candidate.signature == Signature(("list",), "int"):
            assert candidate.meta["step"] == "tail"
            assert candidate.meta["measure"] == "length"
            assert "tail" in candidate.defn.depends_on
            assert isinstance(admit(state, candidate), Entry)
            return
    assert False, "no measured list recursion was admitted"


def test_inferred_counter_repeats_an_independent_state_step():
    world = toy.gen_world()
    world.sorts["int"] = replace(world.sorts["int"], values=(0, 1, 2, 3))
    world.decl = replace(world.decl, operations=(*world.decl.operations,
                         OperationSpec("flip", "transform", (Edge("bool"),), Edge("bool"),
                                       "Toggle a boolean state.")))
    world.atoms = (*world.atoms, kernel.Atom("flip", 1, lambda value: not value))
    world.signatures["flip"] = Signature(("bool",), "bool")
    world.counters["int"] = [("sub", 1, "is_zero")]
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))
    candidate = MOVES[2](state, random.Random(4))
    assert candidate is not None and candidate.signature == Signature(("int", "bool"), "bool")
    assert candidate.meta["step"] == "sub" and candidate.meta["worker"] == "flip"
    assert {"sub", "flip"} <= set(candidate.defn.depends_on)
    assert isinstance(admit(state, candidate), Entry)


def test_wide_combiner_accepts_two_invented_arguments():
    world = circuits.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    for projection in ("dag_outputs", "dag_gates"):
        name = state.names.fresh("operation")
        body = nodes.Call("tuple_len", (nodes.Call(projection, (nodes.Var("x0"),)),))
        defn = Definition(name, "operation", "invented", 1, (projection, "tuple_len"),
                          OperationSpec(name, "transform", (Edge("circuit"),), Edge("int"),
                                        "Measure a circuit projection.",
                                        extra={"input_names": ["x0"]}), body)
        assert isinstance(admit(state, Candidate(defn, Signature(("circuit",), "int"),
                                               "op.specialize")), Entry)
    rng = random.Random(31)
    for _ in range(100):
        candidate = MOVES[4](state, rng)
        if candidate is not None and candidate.signature.output == "witness":
            assert len(set(candidate.defn.depends_on) & state.entries.keys()) == 2
            assert not check_definition(candidate.defn, world.decl, state.library.resolve)
            return
    assert False, "the four-input witness constructor cannot combine invented functions"


def test_binary_text_operation_can_branch_on_sequence_guard():
    world = text.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    rng = random.Random(22)
    for _ in range(80):
        candidate = MOVES[1](state, rng)
        if candidate is not None and candidate.signature.inputs == ("List", "int"):
            assert not check_definition(candidate.defn, world.decl, state.library.resolve)
            return
    assert False, "text transforms cannot branch on a sequence"


def test_classic_action_branches_on_boolean_input_without_a_decider():
    world = classic.gen_world("action")
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    rng = random.Random(23)
    for _ in range(24):
        candidate = MOVES[1](state, rng)
        if candidate is not None and candidate.signature.inputs == ("state", "bool"):
            assert not check_definition(candidate.defn, world.decl, state.library.resolve)
            return
    assert False, "state transforms cannot branch on a boolean input"


def test_classic_note_host_integers_are_not_literal_notes():
    world = classic.gen_world("pitch")
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                     dict(world.sorts))
    assert term(state, random.Random(9), "note", {}, 0) is None
    assert term(state, random.Random(9), "note", {"x0": "note"}, 0) == nodes.Var("x0")


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
@pytest.mark.parametrize("adapter,name", [
    ("catalogue", name) for name in (
        "action", "automata", "calendar", "circuits", "dice", "geometry", "grammar",
        "hidden", "integer", "kitchen", "lists", "melody", "molecules",
        "permutation", "pixels", "rhythm", "roads", "shadows", "text", "versions")
] + [("classic", name) for name in (
    "action", "bits", "clock", "grid", "integer", "lists", "logic", "perm",
    "pitch", "rel", "strings")])
def test_operation_only_adapter_acceptance(adapter, name):
    from opulse.gen_v2.run import generate

    module = importlib.import_module("opulse.gen_v2.worlds." +
                                     (name if adapter == "catalogue" else "classic"))
    world = module.gen_world() if adapter == "catalogue" else module.gen_world(name)
    state = generate(world, 400, 1, per_kind_min=0, layer_target=10,
                     time_limit=120, moves=MOVES)
    assert len(state.entries) >= 300, (adapter, name, state.attempts)
    assert state.max_layer() >= 10
    assert sum(len(set(entry.depends_on) & state.entries.keys()) >= 2
               for entry in state.entries.values()) >= 0.4 * len(state.entries)
