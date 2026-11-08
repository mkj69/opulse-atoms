"""Regression checks for published layer-0 declarations (spec section 13.3)."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.core.presets import register_preset as register_typed
from opulse.core.semantics import NAN, Semantics
from opulse.tasks_v2.decl import (
    WorldFile,
    compute_lock,
    find,
    host_digest,
    load,
    load_all,
    validate,
    write_locks,
)

ROOT = Path("docs/assets/data/worlds")
DECL = Path("worlds/decl")
NUMBER_PRESETS = ("successor", "bits")


def published_files(world):
    yield ROOT / f"{world}.json"
    yield from (ROOT / world).rglob("*.json")


def visit(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from visit(child)
    elif isinstance(value, list):
        for child in value:
            yield from visit(child)


def test_all_world_files_round_trip_and_locks():
    files = sorted(DECL.glob("*.json"))
    assert files
    assert len(load_all(DECL)) == len(files)
    for path in files:
        data = json.loads(path.read_text())
        world = load(path)
        assert world.to_dict() == data
        assert WorldFile.from_dict(data).to_dict() == data
        assert find(world.world, world.version, DECL) == world
        assert world.lock == compute_lock(world)
        assert validate(world) == []


@pytest.mark.parametrize("world", ("integer", "successor", "clock", "bits", "logic", "strings"))
def test_legacy_published_atoms_tags_and_references(world):
    declared = find(world, 1)
    published = json.loads((ROOT / f"{world}.json").read_text())
    settings = {item["key"]: item["value"] for item in published["settings"]}
    assert declared.source["settings"] == settings
    assert declared.params["published_settings"] == settings
    assert [(op.name, op.symbol, len(op.inputs),
             [(edge.name, edge.sort) for edge in op.inputs], op.output.sort, op.rule)
            for op in declared.operations] == [
                (atom["name"], atom["symbol"], atom["arity"],
                 [(param["name"], param["type"]) for param in atom["params"]],
                 atom["result_type"], atom["rule"]) for atom in published["atoms"]]
    tags = set()
    referenced = set()
    generated = set()
    for path in published_files(world):
        content = json.loads(path.read_text())
        for item in visit(content):
            if isinstance(item, dict):
                if "t" in item:
                    tags.add(item["t"])
                if "operators" in item and isinstance(item["operators"], list):
                    generated.update(row["name"] for row in item["operators"]
                                     if isinstance(row, dict) and "name" in row)
                if "uses" in item and isinstance(item["uses"], list):
                    referenced.update(item["uses"])
                if isinstance(item.get("gate"), str) and item["gate"]:
                    referenced.add(item["gate"])
    assert tags <= set(declared.codec["legacy_tags"])
    assert referenced <= generated | {op.name for op in declared.operations} | {
        op.symbol for op in declared.operations}


@pytest.mark.parametrize("world", ("integer", "successor", "clock", "bits", "logic", "strings"))
def test_legacy_host_failure_coverage(world):
    from opulse.core.primitives import CUSTOM
    from opulse.presets import register_preset as register_number

    if world in NUMBER_PRESETS:
        register_number(world)
    if world in ("logic", "strings"):
        register_typed(world)
    declaration = find(world, 1)
    settings = declaration.params["semantics"]
    semantics = Semantics(**{key: value for key, value in settings.items()
                             if key in ("mode", "bound", "modulus", "max_string_length")})
    functions = semantics.operations()
    for operation in declaration.operations:
        assert operation.impl["digest"] == host_digest(operation.impl["host"])
        assert operation.impl["host"].endswith("Semantics.operations" if operation.name not in CUSTOM
                                                 else "register_preset")
        inputs = [edge.sort for edge in operation.inputs]
        cases = [[(False if kind == "bool" else "ab" if kind == "str" else 2)
                  for kind in inputs]]
        if "int" in inputs:
            cases.append([(-1 if kind == "int" else False if kind == "bool" else "ab")
                          for kind in inputs])
            cases.append([(2**31 - 1 if kind == "int" else False if kind == "bool" else "ab")
                          for kind in inputs])
        if operation.name in ("div", "mod", "shift_left"):
            cases.append([2, 0 if operation.name != "shift_left" else 32])
        if operation.name == "str_concat":
            cases.append(["x" * 256, "y"])
        if operation.name in ("str_reverse", "str_drop", "str_upper", "str_lower"):
            cases.append(["x" * 258])
        for args in cases:
            result = functions[operation.name](*args)
            if result is NAN:
                assert operation.errors, (world, operation.name, args)


def _evaluate(node, environment):
    kind = node["node"]
    if kind == "Var":
        return environment[node["name"]]
    if kind == "Lit":
        value = node["value"]
        return value["tag"] == "true" if value["t"] == "bool" else value["v"]
    if kind == "Call":
        return {"int_mod_twelve": lambda number: number % 12,
                "nonnegative": lambda number: number >= 0,
                "below_twelve": lambda number: number < 12}[node["fn"]](
                    *[_evaluate(arg, environment) for arg in node["args"]])
    if kind == "Test":
        return bool(_evaluate(node["expr"], environment))
    if kind == "And":
        return _evaluate(node["left"], environment) and _evaluate(node["right"], environment)
    if kind == "Case":
        for condition, body in node["arms"]:
            if _evaluate(condition, environment):
                return _evaluate(body, environment)
        return _evaluate(node["default"], environment)
    raise AssertionError(kind)


def test_true_clock_hour_canonicalization():
    from opulse.atoms.nodes import from_json, to_json

    clock = find("clock", 2)
    hour = next(obj for obj in clock.objects if obj.name == "hour")
    assert all(to_json(from_json(getattr(hour, field))) == getattr(hour, field)
               for field in ("valid", "canon"))
    assert [_evaluate(hour.canon, {"x": value}) for value in (14, -4)] == [2, 8]
    assert [_evaluate(hour.valid, {"x": value}) for value in (-1, 0, 11, 12)] == [
        False, True, True, False]
    for operation in clock.operations[:10]:
        assert all(edge.enter == "normalize" for edge in (*operation.inputs, operation.output))
        assert all(edge.sort == "hour" for edge in (*operation.inputs, operation.output))
    legacy = find("clock", 1)
    assert all(edge.enter == "bottom" for operation in legacy.operations
               for edge in operation.inputs)
    assert all(operation.output.enter == "fold(modular)" for operation in legacy.operations)


def test_validator_rejects_invalid_declarations():
    original = find("integer", 1)
    operation = original.operations[0]
    bad = (
        (replace(original, operations=(replace(operation,
                 inputs=(replace(operation.inputs[0], sort="missing"), *operation.inputs[1:])),
                 *original.operations[1:])), "unknown sort"),
        (replace(original, operations=(*original.operations, operation)), "duplicate operation"),
        (replace(original, operations=(replace(operation,
                 inputs=(replace(operation.inputs[0], enter="warp"), *operation.inputs[1:])),
                 *original.operations[1:])), "illegal enter"),
        (replace(original, operations=(replace(operation,
                 impl={**operation.impl, "digest": "0" * 64}), *original.operations[1:])),
         "stale host digest"),
        (replace(original, combinators={**original.combinators,
                 "nodes": [*original.combinators["nodes"], "MadeUp"]}), "unknown combinator node"),
    )
    for world_file, expected in bad:
        assert any(expected in problem for problem in validate(world_file)), expected


def test_validator_rejects_invalid_object_and_probe():
    original = find("clock", 2)
    hour = next(obj for obj in original.objects if obj.name == "hour")
    malformed = replace(original, objects=tuple(
        replace(obj, base="absent") if obj == hour else obj for obj in original.objects))
    assert any("unknown sort" in problem for problem in validate(malformed))
    malformed = replace(original, objects=tuple(
        replace(obj, sealed=True, interface=["unknown"]) if obj == hour else obj
        for obj in original.objects))
    assert any("sealed interface" in problem for problem in validate(malformed))
    malformed = replace(original, operations=(replace(original.operations[0], cost=0, role="unknown"),
                                              *original.operations[1:]))
    problems = validate(malformed)
    assert any("cost" in problem for problem in problems)
    assert any("role" in problem for problem in problems)
    observation = {**original.observation, "truth": "int",
                   "probes": [{"name": "peek", "sort": "hour", "reads": "hour",
                               "reveals": [], "impl": None}]}
    assert any("reads must equal" in problem
               for problem in validate(replace(original, observation=observation)))


def test_lock_rewrite_and_check_cli(tmp_path):
    source = DECL / "integer@1.json"
    target = tmp_path / source.name
    data = json.loads(source.read_text())
    data["operations"][0]["impl"]["digest"] = "stale"
    data["lock"]["world_hash"] = "stale"
    target.write_text(json.dumps(data))
    command = [sys.executable, "-m", "opulse.tasks_v2.decl"]
    assert subprocess.run([*command, "--check", "--directory", str(tmp_path)],
                          capture_output=True, check=False).returncode == 1
    assert any("stale host digest" in problem for problem in validate(load(target)))
    write_locks(tmp_path)
    assert validate(load(target)) == []
    data = json.loads(target.read_text())
    data["lock"]["world_hash"] = "stale"
    target.write_text(json.dumps(data))
    assert subprocess.run([*command, "--lock", "--directory", str(tmp_path)],
                          capture_output=True, check=False).returncode == 0
    assert validate(load(target)) == []
    assert subprocess.run([*command, "--check", "--directory", str(tmp_path)],
                          capture_output=True, check=False).returncode == 0


def test_validate_rejects_duplicate_error_reasons():
    world = find("integer", 1)
    first = world.operations[0]
    bad = replace(world, operations=(replace(first, errors=["overflow", "overflow"]), *world.operations[1:]))
    assert any("duplicate error" in problem for problem in validate(bad))


def test_extra_top_level_members_round_trip_and_open_kinds_checked():
    data = json.loads((DECL / "integer@1.json").read_text())
    data = {**{key: value for key, value in data.items() if key != "lock"},
            "title_zh": "整数", "tags": {"domain": "math"}, "open_kinds": ["operation"], "lock": data["lock"]}
    world = WorldFile.from_dict(data)
    assert world.to_dict() == data and list(world.to_dict()) == list(data)
    assert validate(world) == [] or all("digest" in problem or "world_hash" in problem for problem in validate(world))
    bad = WorldFile.from_dict({**data, "open_kinds": ["operation", "tactic"]})
    assert any("open_kinds" in problem for problem in validate(bad))


def test_every_declaration_loads_through_core_world_decl():
    from opulse.atoms.world import WorldDecl, legacy_world_decl

    for path in sorted(DECL.glob("*.json")):
        data = json.loads(path.read_text())
        world = WorldDecl.from_dict(data)
        assert [op.name for op in world.operations] == [op["name"] for op in data["operations"]]
        if data["dialect"] == "legacy-v1" and path.name != "clock@1.json":
            published = json.loads((ROOT / f"{data['world']}.json").read_text())
            assert [op.name for op in legacy_world_decl(published).operations] == [op["name"] for op in data["operations"]]


def test_open_kinds_accepts_law_and_bridge():
    world = load(DECL / "integer@1.json")
    for kinds in (["law"], ["bridge", "operation"]):
        assert not any("open_kinds" in problem for problem in validate(replace(world, extra={**world.extra, "open_kinds": kinds})))


def test_display_members_do_not_change_world_hash():
    world = find("computer", 1)
    assert compute_lock(world)["world_hash"] == compute_lock(replace(world, title=world.title + " cosmetic"))["world_hash"]
    assert compute_lock(world)["world_hash"] != compute_lock(replace(world, params={**world.params, "extra": 1}))["world_hash"]


def test_static_int_parameters_must_be_integers():
    world = find("perm", 1)
    data = world.to_dict()
    for operation in data["operations"]:
        for edge in operation["inputs"]:
            if edge["sort"] == "perm[n]":
                edge["sort"] = "perm[not_an_integer]"
    assert any("static int parameter" in problem for problem in validate(WorldFile.from_dict(data)))
    assert not any("static int parameter" in problem for problem in validate(world))
