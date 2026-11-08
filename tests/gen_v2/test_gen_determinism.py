"""A seed must determine the generated library, not earlier runs in this process."""

import json
import os
import subprocess
import sys

from opulse.atoms import nodes
from opulse.atoms.spec import ObjectSpec
from opulse.gen_v2.base import GenState
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.object import _candidate
from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import lists, toy, toy_truth


def test_compose_accessors_follow_declared_field_order():
    world = toy.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    spec = ObjectSpec("A1", "compose", tags={
        "pair": [["right", "int"], ["left", "int"]],
        "other": [["left", "int"], ["middle", "int"]],
    })
    body = nodes.Call("A1.pair", (nodes.Lit(1), nodes.Lit(2)))
    candidate = _candidate(state, spec, "obj.record", body)
    assert candidate.new_sorts[0].accessors == ("A1.right", "A1.left", "A1.middle")


def test_independent_hash_seeds_have_identical_definitions_and_evidence(tmp_path):
    code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from opulse.gen_v2 import export\n"
        "from opulse.gen_v2.run import generate\n"
        "from opulse.gen_v2.worlds import toy, lists, integer\n"
        "world = {'toy': toy, 'lists': lists, 'integer': integer}[sys.argv[1]]\n"
        "state = generate(world.gen_world(), 35, 1, per_kind_min=0, layer_target=0)\n"
        "base = Path(sys.argv[2])\n"
        "export.export(state, base.with_suffix('.json'))\n"
        "export.export_compact(state, base.with_suffix('.compact.json'))\n"
        "export.export_jsonl(state, base.with_suffix('.jsonl'))\n"
        "base.with_suffix('.md').write_text(export.export_summary_md(state), encoding='utf-8')\n"
        "print(json.dumps([[entry.name, entry.kind, repr(state.library.get(entry.name).body), "
        "state.library.get(entry.name).evidence.to_dict(), "
        "list(state.sorts[entry.name].accessors) if entry.name in state.sorts else []] "
        "for entry in state.entries.values()], sort_keys=True))\n"
    )
    for world in ("toy", "lists", "integer"):
        outputs = []
        for hash_seed in ("1", "2"):
            base = tmp_path / f"{world}_{hash_seed}"
            environment = {**os.environ, "PYTHONPATH": "src", "PYTHONHASHSEED": hash_seed}
            result = subprocess.run([sys.executable, "-c", code, world, str(base)], env=environment,
                                    capture_output=True, text=True, check=True, timeout=35)
            outputs.append(json.loads(result.stdout))
        assert len(outputs[0]) >= 35
        assert outputs[0] == outputs[1], world
        for extension in (".json", ".compact.json", ".jsonl", ".md"):
            assert (tmp_path / f"{world}_1{extension}").read_bytes() == (
                tmp_path / f"{world}_2{extension}").read_bytes(), (world, extension)


def _snapshot(state):
    return [
        [entry.name, entry.kind, repr(state.library.get(entry.name).body),
         state.library.get(entry.name).evidence.scope, state.requests[entry.name].scope]
        for entry in state.entries.values()
    ]


def _toy(seed=7, target=24):
    return generate(toy.gen_world(), target, seed, per_kind_min=3, layer_target=2)


def test_seed_survives_intervening_worlds_and_subprocess():
    first = _toy()
    assert len(first.entries) >= 24
    assert {entry.kind for entry in first.entries.values()} == {
        "object", "operation", "combinator"}
    expected = _snapshot(first)
    observed = generate(toy_truth.gen_world(), 8, 7, per_kind_min=0, layer_target=2)
    assert {entry.kind for entry in observed.entries.values()} == {"observation"}
    expected_observed = _snapshot(observed)
    listed = generate(lists.gen_world(), 10, 17, per_kind_min=0, layer_target=2)
    expected_listed = _snapshot(listed)
    generate(toy.gen_world(), 16, 99, per_kind_min=0, layer_target=2)
    assert _snapshot(first) == expected
    assert _snapshot(_toy()) == expected
    assert _snapshot(observed) == expected_observed
    assert _snapshot(generate(toy_truth.gen_world(), 8, 7, per_kind_min=0,
                              layer_target=2)) == expected_observed
    assert _snapshot(generate(lists.gen_world(), 10, 17, per_kind_min=0,
                              layer_target=2)) == expected_listed

    code = (
        "import json\n"
        "from opulse.gen_v2.run import generate\n"
        "from opulse.gen_v2.worlds import toy, toy_truth\n"
        "state = generate(toy.gen_world(), 24, 7, per_kind_min=3, layer_target=2)\n"
        "def snapshot(state):\n"
        "    return [[entry.name, entry.kind, repr(state.library.get(entry.name).body), "
        "state.library.get(entry.name).evidence.scope, state.requests[entry.name].scope] "
        "for entry in state.entries.values()]\n"
        "observed = generate(toy_truth.gen_world(), 8, 7, per_kind_min=0, layer_target=2)\n"
        "print(json.dumps([snapshot(state), snapshot(observed)]))\n"
    )
    environment = {**os.environ, "PYTHONPATH": "src", "PYTHONHASHSEED": "13"}
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            capture_output=True, text=True, check=True, timeout=60)
    assert json.loads(result.stdout) == json.loads(json.dumps([expected, expected_observed]))


def test_recursive_hints_and_sort_values_do_not_mutate_caller_world():
    world = toy.gen_world()
    before = (dict(world.sorts), {name: sort.values for name, sort in world.sorts.items()},
              {name: list(pairs) for name, pairs in world.measures.items()},
              {name: list(names) for name, names in world.bases.items()})
    first = generate(world, 70, 1, per_kind_min=4, layer_target=4)
    assert len(first.entries) >= 70
    assert first.world.measures != before[2]
    assert first.world.sorts["int"] is not world.sorts["int"]
    assert world.sorts == before[0]
    assert {name: sort.values for name, sort in world.sorts.items()} == before[1]
    assert world.measures == before[2]
    assert world.bases == before[3]
    assert _snapshot(generate(world, 70, 1, per_kind_min=4, layer_target=4)) == _snapshot(first)


def test_move_bias_does_not_escape_its_run():
    class BiasedMove:
        kind = "operation"
        name = "test.biased"
        bias = -1

        def __call__(self, state, rng):
            return None

    move = BiasedMove()
    state = generate(toy.gen_world(("operation",)), 1, 1, per_kind_min=0,
                     layer_target=0, moves=(move,))
    assert state.attempts == 200
    assert move.bias == -1
    assert not state.entries
