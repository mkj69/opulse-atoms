"""Published legacy worlds agree with layer-zero declarations (specification section 13)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.core.presets import register_preset
from opulse.core.primitives import CUSTOM
from opulse.core.semantics import BASE_OPERATIONS, NAN, Semantics
from opulse.tasks_v2.decl import compute_lock, host_digest, load, validate, write_locks
from opulse.tasks_v2.hosts import NAMES, valid_colour, valid_note, valid_person
from opulse.worlds.action import Direction, State, initial_state, register_action_atoms
from opulse.worlds.perm import Permutation
from tools.tasks_v2_decl_b import WORLDS, declaration

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs/assets/data/worlds"


@pytest.fixture(autouse=True)
def isolate_legacy_registration():
    from opulse.core.presets import _REGISTERED

    custom = CUSTOM.copy()
    base = BASE_OPERATIONS.copy()
    registered = _REGISTERED.copy()
    try:
        yield
    finally:
        CUSTOM.clear()
        CUSTOM.update(custom)
        BASE_OPERATIONS.clear()
        BASE_OPERATIONS.update(base)
        _REGISTERED.clear()
        _REGISTERED.update(registered)


def records(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from records(child)
    elif isinstance(value, list):
        for child in value:
            yield from records(child)


def sources(world):
    return [DATA / f"{world}.json", *sorted((DATA / world).rglob("*.json"))]


def decode(value):
    tag = value["t"]
    if tag == "nan":
        return NAN
    if tag == "state":
        return State.from_dict(value["v"])
    if tag == "perm":
        return Permutation(value["v"])
    if tag == "list":
        return tuple(decode(child) for child in value["v"])
    if tag == "grid":
        return tuple(tuple(row) for row in value["v"])
    if tag == "melody":
        return tuple((item["p"], item["d"]) for item in value["v"])
    return value["v"]


@pytest.mark.parametrize("world", WORLDS)
def test_schema_locks_published_atoms_and_tags(world):
    path = ROOT / f"worlds/decl/{world}@1.json"
    world_file = load(path)
    data = world_file.to_dict()
    published = json.loads((DATA / f"{world}.json").read_text(encoding="utf-8"))
    assert data == declaration(world)
    assert data == json.loads(path.read_text(encoding="utf-8"))
    assert validate(world_file) == []
    assert (data["schema"], data["world"], data["version"], data["dialect"]) == (
        "opulse.world/2", world, 1, "legacy-v1")
    assert data["source"] == {"published": f"docs/assets/data/worlds/{world}.json",
                              "settings": {row["key"]: row["value"] for row in published["settings"]}}
    sorts = {item["name"] for item in data["objects"]}
    assert len(sorts) == len(data["objects"])
    assert len({item["name"] for item in data["operations"]}) == len(data["operations"])
    assert [(op["name"], op["symbol"], len(op["inputs"]),
             [(arg["name"], arg["sort"]) for arg in op["inputs"]],
             op["output"]["sort"], op["rule"]) for op in data["operations"]] == [
        (atom["name"], atom["symbol"], atom["arity"],
         [(arg["name"], {"str": "person", "state": "robot_state",
                         "perm[5]": "perm[n]"}.get(arg["type"], arg["type"]))
          for arg in atom["params"]],
         {"str": "person", "state": "robot_state", "perm[5]": "perm[n]"}.get(
             atom["result_type"], atom["result_type"]), atom["rule"])
        for atom in published["atoms"]]
    for op in data["operations"]:
        assert op["cost"] == 1 and op["strict"]
        assert {arg["sort"] for arg in op["inputs"]} | {op["output"]["sort"]} <= sorts
    assert set(data["codec"]["legacy_tags"]) >= {
        entry["t"] for path in sources(world)
        for entry in records(json.loads(path.read_text(encoding="utf-8"))) if "t" in entry}
    assert set(data["codec"]["legacy_tags"].values()) <= sorts | {"Bottom"}
    assert data["lock"] == compute_lock(world_file)
    functions = {op["name"]: op["impl"] for op in data["operations"]}
    functions.update({f'{obj["name"]}.valid': obj["valid"] for obj in data["objects"] if obj["valid"]})
    functions.update({f'probe.{probe["name"]}': probe["impl"]
                      for probe in data["observation"]["probes"]})
    assert set(functions) == set(data["lock"]["host_digests"])
    for name, spec in functions.items():
        assert "<locals>" not in spec["host"]
        assert spec["digest"] == data["lock"]["host_digests"][name] == host_digest(spec["host"])


def test_host_predicates_match_published_bounds():
    published = json.loads((DATA / "rel.json").read_text(encoding="utf-8"))
    assert NAMES == set(published["context"]["entities"])
    assert all(valid_person(name) for name in NAMES)
    assert not valid_person("Nobody") and not valid_person(3)
    assert all(valid_colour(value) for value in range(10))
    assert not valid_colour(-1) and not valid_colour(10) and not valid_colour(True)
    assert valid_note(0) and valid_note(127)
    assert not valid_note(-1) and not valid_note(128) and not valid_note(True)


def test_loader_rewrites_six_worlds_byte_identically(tmp_path):
    for world in WORLDS:
        source = ROOT / f"worlds/decl/{world}@1.json"
        (tmp_path / source.name).write_bytes(source.read_bytes())
    write_locks(tmp_path)
    for world in WORLDS:
        source = ROOT / f"worlds/decl/{world}@1.json"
        assert (tmp_path / source.name).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("world", WORLDS)
def test_published_operator_references(world):
    data = json.loads((ROOT / f"worlds/decl/{world}@1.json").read_text(encoding="utf-8"))
    atoms = {op["name"] for op in data["operations"]}
    symbols = {op["symbol"] for op in data["operations"]}
    for path in sources(world):
        source = json.loads(path.read_text(encoding="utf-8"))
        generated = {op["name"] for op in source.get("operators", [])} if isinstance(source, dict) else set()
        if not generated:
            if "steps" in path.parts:
                seed_path = DATA / world / f"seed-{path.parent.name}.json"
                seed_file = seed_path if seed_path.exists() else DATA / f"{world}.json"
                generated = {op["name"] for op in json.loads(seed_file.read_text())["operators"]}
            else:
                generated = {op["name"] for seed_file in [DATA / f"{world}.json",
                             *(DATA / world).glob("seed-*.json")]
                             for op in json.loads(seed_file.read_text())["operators"]}
        for item in records(source):
            for name in item.get("uses", []):
                assert name in atoms | generated, (path, name)
            if item.get("operator"):
                assert item["operator"] in atoms | symbols | generated, (path, item["operator"])
            if item.get("kind") in ("atom", "eval", "expand", "undefined"):
                gate = item.get("gate")
                if gate and gate != "self":
                    assert gate in atoms | symbols | generated, (path, gate)
            if world == "action" and isinstance(item.get("rule"), dict):
                for key in ("first", "second", "guard"):
                    name = item["rule"].get(key)
                    if name:
                        assert name in atoms | generated, (path, key, name)


@pytest.mark.parametrize("world", WORLDS)
def test_atom_host_results_and_declared_failures(world):
    if world == "action":
        register_action_atoms()
    else:
        register_preset(world)
    operations = Semantics().operations()
    data = json.loads((ROOT / f"worlds/decl/{world}@1.json").read_text(encoding="utf-8"))
    published = json.loads((DATA / f"{world}.json").read_text(encoding="utf-8"))
    by_name = {op["name"]: op for op in data["operations"]}
    for atom in published["atoms"]:
        example = atom["example"]
        result = operations[atom["name"]](*(decode(arg) for arg in example["inputs"]))
        expected = decode(example["output"])
        assert result is expected if expected is NAN else result == expected, (world, atom["name"])
        if result is NAN:
            assert by_name[atom["name"]]["errors"]

    permutation = Permutation(range(5))
    grid = ((0, 1), (2, 0))
    state = replace(initial_state(), robot=(0, 0), facing=Direction("N"))
    failures = {
        "lists": {"mod": ((7, 0), "div_zero"),
                  "list_head": (((),), "empty"), "list_at": (((1,), -1), "invalid")},
        "perm": {"swap": ((permutation, 25), "invalid"),
                 "perm_compose": ((permutation, Permutation(range(3))), "invalid"),
                 "perm_apply": ((permutation, 5), "invalid")},
        "rel": {"rel_parent": (("Luz",), "missing")},
        "grid": {"grid_recolour": ((grid, 100), "invalid"),
                 "grid_overlay": ((grid, ((1,),)), "shape"),
                 "grid_count": ((grid, -1), "invalid"),
                 "grid_fill": ((grid, 10), "invalid")},
        "pitch": {"pitch_transpose": ((127, 1), "invalid"),
                  "pitch_octave_up": ((127,), "invalid"),
                  "pitch_octave_down": ((0,), "invalid"),
                  "pitch_invert": (((((0, 1),), 127)), "invalid"),
                  "pitch_scale_step": ((127,), "invalid"),
                  "pitch_major_triad": ((127,), "invalid"),
                  "pitch_minor_triad": ((127,), "invalid"),
                  "pitch_repeat": (((), 17), "invalid")},
        "action": {"forward": ((state,), "blocked"),
                   "pick": ((state,), "blocked"),
                   "place": ((state,), "blocked"),
                   "craft": ((state,), "blocked"),
                   "front_colour": ((state,), "invalid"),
                   "held_colour": ((state,), "invalid"),
                   "front_height": ((state,), "invalid")},
    }
    for name, (args, reason) in failures[world].items():
        assert operations[name](*args) is NAN, (world, name)
        assert reason in by_name[name]["errors"]
    if world == "action":
        probes = data["observation"]["probes"]
        assert data["observation"]["truth"] == "robot_state"
        assert {p["name"] for p in probes} == {
            "front_wall", "front_water", "front_colour", "holding", "held_colour", "front_height"}
        for probe in probes:
            assert probe["reads"] == "robot_state"
            assert probe["sort"] == by_name[probe["name"]]["output"]["sort"]
            assert probe["impl"] == by_name[probe["name"]]["impl"]
