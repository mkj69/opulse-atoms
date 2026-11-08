"""vn/1 machine and kernel agreement (meta spec section 4.2)."""

import itertools
import random

import pytest

from opulse.atoms import nodes
from opulse.atoms.kernel import DictScope, Limits, evaluate
from opulse.atoms.values import FALSE, TRUE, Bottom, Card, Ok, Unknown
from opulse.atoms.world import WorldDecl
from opulse.meta.vn import machine, reference


def assert_agrees(state, fuel):
    expected, final, steps = reference.run(state, fuel)
    actual = machine.run(machine.to_card(state), fuel)
    assert actual.steps == steps
    if expected == "ok":
        assert actual.outcome == Ok(machine.to_card(final))
    elif expected == "illegal":
        assert actual.outcome == Bottom("illegal")
    else:
        assert actual.outcome == Unknown("fuel")


def test_all_two_instruction_programs():
    for code in itertools.product(range(10), range(16), range(10), range(16)):
        assert_agrees(reference.load(code), 20)


def test_seeded_eight_instruction_programs():
    rng = random.Random(74091)
    for _ in range(2000):
        program = [part for _ in range(8) for part in (rng.randrange(10), rng.randrange(32))]
        assert_agrees(reference.load(program, 32), 20)


def test_atoms_and_cards():
    state = reference.load([1, 22, 0, 0])
    card = machine.to_card(state)
    assert machine.from_card(card) == state
    assert card.fields[2].sort == "mem" and card.fields[2].tag == "items"
    assert card.fields[3] == FALSE
    assert machine.is_halted(machine.to_card(reference.State(0, 0, state.mem, True))) == TRUE
    assert machine.step(machine.to_card(reference.State(0, 0, state.mem, True))) == machine.to_card(
        reference.State(0, 0, state.mem, True))
    scope = DictScope(machine.atoms(16))
    for name, args, expected in (("poke", (card, 16, 0), Bottom("invalid")),
                                  ("poke", (card, 0, 256), Bottom("invalid")),
                                  ("peek", (card, -1), Bottom("invalid")),
                                  ("set_a", (card, -1), Bottom("invalid")),
                                  ("set_pc", (card, 16), Bottom("invalid")),
                                  ("get_a", (card,), Ok(0)),
                                  ("get_pc", (card,), Ok(0)),
                                  ("cell", (card, 0), Ok(1)),
                                  ("pc", (card,), Ok(0))):
        result = evaluate(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)), scope=scope)
        assert result.outcome == expected
        assert result.steps == scope.resolve(name).cost
    assert machine.run(machine.to_card(reference.load([0, 0])), 1).steps == 1
    assert machine.run(machine.to_card(reference.load([9, 0])), 1).outcome == Bottom("illegal")
    assert machine.run(machine.to_card(reference.load([6, 0])), 3).outcome == Unknown("fuel")
    assert machine.run(machine.to_card(reference.load([6, 0])), 3).steps == 3
    with pytest.raises(ValueError, match="halted flag"):
        machine.from_card(Card("vn", "vn", (0, 0, card.fields[2], True)))


def test_exec_trace_exact_instruction_steps():
    state = machine.to_card(reference.load([1, 5, 0, 0]))
    traced = evaluate(machine.exec_node(nodes.Lit(state)), scope=DictScope(machine.atoms(16)),
                      limits=Limits(fuel=2), trace=True)
    assert traced.outcome == Ok(machine.to_card(reference.run(reference.load([1, 5, 0, 0]), 2)[1]))
    assert traced.steps == 2
    assert [frame.name for frame in traced.trace.children] == ["r0"]
    first = traced.trace.children[0]
    assert first.steps == 2
    assert [(frame.name, frame.steps) for frame in first.children] == [("is_halted", 0), ("step", 1),
                                                                       ("r0", 1)]
    assert [(frame.name, frame.steps) for frame in first.children[-1].children] == [
        ("is_halted", 0), ("step", 1), ("r0", 0)]


def test_world_declaration():
    world = machine.world_decl(16)
    assert world.world == "vonneumann" and world.version == 1 and world.dialect == "atoms-v2"
    assert world.combinators == {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                                 "library": ["exec"], "recursion": "fuel"}
    assert world.observation["judge_view"] == "full_state"
    assert world.observation["truth"] == "vn"
    assert len(world.operations) == 8 and len(world.observation["probes"]) == 4
    assert WorldDecl.from_dict(world.to_dict()).world_hash() == world.world_hash()
    for operation in world.operations:
        fn = getattr(machine, operation.name)
        assert operation.impl == machine._host_rule(fn)
        assert operation.cost == machine.DictScope(machine.atoms(16)).resolve(operation.name).cost
    with pytest.raises(ValueError):
        machine.world_decl(17)
