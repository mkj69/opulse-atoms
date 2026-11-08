"""Dependent four-kind chains from verified proposals."""

import os
import time

import pytest

from opulse.gen_v2.moves.chain import MOVES, ChainMove
from opulse.gen_v2.moves.registry import discover_moves
from opulse.gen_v2.run import generate
from opulse.gen_v2.tasks_bridge import four_kinds_path
from opulse.gen_v2.worlds import lists, toy, toy_truth


@pytest.mark.parametrize("world", [lambda: toy_truth.gen_world(
    ("object", "operation", "combinator", "observation")), lists.gen_world])
def test_chain_is_promoted_and_deterministic(world):
    def build():
        return generate(world(), 4, 2, per_kind_min=1, layer_target=0, moves=MOVES)

    first, second = build(), build()
    path = four_kinds_path(first)
    assert len(first.entries) == 4
    assert [step["kind"] for step in path["steps"]] == [
        "object", "operation", "combinator", "observation"]
    assert path["links"][-1] == "observation uses combinator"
    assert all(step["status"] == "promoted" and step["evidence"] and step["contract"]
               and step["name"] in first.requests for step in path["steps"])
    assert path == four_kinds_path(second)
    assert first.attempts == second.attempts


def test_chain_respects_missing_probes_and_closed_kinds():
    assert generate(toy.gen_world(), 0, 2, per_kind_min=0, layer_target=0,
                    moves=MOVES).entries == {}
    state = generate(toy_truth.gen_world(("object",)), 1, 2, per_kind_min=0,
                     layer_target=0, moves=[ChainMove("object")])
    assert {entry.kind for entry in state.entries.values()} == {"object"}
    assert four_kinds_path(state) is None
    assert all(move.bias == 0.0 and move.name == "chain.extend" for move in MOVES)
    assert {move.kind for move in MOVES} == {"observation"}
    assert any(move.name == "chain.extend" for move in discover_moves()["observation"])


def test_chain_extends_existing_partial_path():
    world = toy_truth.gen_world(("object", "operation", "combinator", "observation"))
    prefix = generate(world, 3, 2, per_kind_min=0, layer_target=0,
                      moves=MOVES)
    assert len(prefix.entries) == 3
    result = generate(world, 4, 2, per_kind_min=0, layer_target=0,
                      moves=[ChainMove("observation")], state=prefix)
    assert len(result.entries) == 4
    assert four_kinds_path(result) is not None


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
@pytest.mark.parametrize("world", [lambda: toy_truth.gen_world(
    ("object", "operation", "combinator", "observation")), lists.gen_world])
def test_mixed_moves_produce_a_path_within_200_admissions(world):
    start = time.monotonic()
    state = generate(world(), 100, 2, per_kind_min=8, layer_target=3, time_limit=30)
    assert len(state.entries) <= 200
    assert four_kinds_path(state) is not None
    assert time.monotonic() - start < 40
