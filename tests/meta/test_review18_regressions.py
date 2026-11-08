"""Regression checks for published claims and malformed JSON (atoms-meta section 8)."""

import copy
import json
import random
import shutil
from pathlib import Path

import pytest

from opulse.atoms import nodes
from opulse.meta.check import check, export_problems
from opulse.meta.export_util import parse_meta_definition

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def export_copy(tmp_path):
    for relative in ("docs/spec/atoms-meta.md", "worlds/decl/meta/code@1.json",
                     "docs/assets/data/meta/code.json"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    return tmp_path / "docs/assets/data/meta/code.json"


def test_fabricated_example_is_not_certified_by_its_own_outcome(export_copy):
    entry = {"kind": "operation", "name": "increment", "symbol": "increment",
             "definition": "Add one to the input.", "status": "callable",
             "ascii": "op increment(x: int) -> int = add(x, 1) L1",
             "examples": [{"ascii": "increment(2) = 100", "inputs": [{"t": "int", "v": 2}],
                           "outcome": {"kind": "Ok", "value": {"t": "int", "v": 100}}}]}
    for example in (entry["examples"][0],
                    {"ascii": "increment(2) = 100"}):
        sample = copy.deepcopy(entry)
        sample["examples"] = [example]
        export_copy.write_text(json.dumps({"story": [sample]}))
        problems = export_problems(json.loads(export_copy.read_text()), export_copy, strict=True)
        assert any("outcome differs from declaration evaluation" in issue for issue in problems)
        if "inputs" not in example:
            assert any("missing recorded inputs" in issue for issue in problems)
            assert any("missing recorded outcome" in issue for issue in problems)


def test_example_unfolds_a_published_operation_call(export_copy):
    source = {"kind": "operation", "name": "increment", "symbol": "increment",
              "definition": "Add one to the input.", "status": "callable",
              "ascii": "op increment(x: int) -> int = add(x, 1) L1",
              "examples": [{"ascii": "increment(2) = 3", "inputs": [2],
                            "outcome": {"kind": "Ok", "value": {"t": "int", "v": 3}}}]}
    wrapper = {"kind": "operation", "name": "twice", "symbol": "twice",
               "definition": "Apply the named operation twice.", "status": "callable",
               "ascii": "op twice(x: int) -> int = increment(increment(x)) L1",
               "examples": [{"ascii": "twice(2) = 100", "inputs": [2],
                             "outcome": {"kind": "Ok", "value": {"t": "int", "v": 100}}}]}
    export_copy.write_text(json.dumps({"story": [source, wrapper]}))
    problems = export_problems(json.loads(export_copy.read_text()), export_copy, strict=True)
    assert any("twice: example[0]: ascii outcome differs from declaration evaluation" in issue
               for issue in problems)
    wrapper["ascii"] = "op twice(x: int) -> int = unknown_call(x) L1"
    export_copy.write_text(json.dumps({"story": [source, wrapper]}))
    problems = export_problems(json.loads(export_copy.read_text()), export_copy, strict=True)
    assert any("semantic verification unavailable: unresolved unknown_call" in issue
               for issue in problems)


def test_template_member_provenance_must_match_pattern(export_copy):
    data = json.loads((ROOT / "docs/assets/data/meta/code.json").read_text())
    member = next(item for item in data["story"] if item["name"] == "specialize_member_0")
    export_copy.write_text(json.dumps(data))
    assert not any("semantic verification unavailable" in issue for issue in export_problems(
        json.loads(export_copy.read_text()), export_copy, strict=True))
    member["ascii"] = member["ascii"].replace("specialize(arg0, 0)", "specialize(arg0, 1)")
    member["body"] = nodes.to_json(parse_meta_definition(member["ascii"]).body)
    export_copy.write_text(json.dumps(data))
    problems = export_problems(json.loads(export_copy.read_text()), export_copy, strict=True)
    assert any("semantic verification unavailable" in issue for issue in problems)


@pytest.mark.parametrize("world,status", [("code", "promoted"), ("compiler", "verified")])
def test_verified_claim_requires_committed_evidence(tmp_path, world, status):
    source = ROOT / f"docs/assets/data/meta/{world}.json"
    export = tmp_path / source.name
    shutil.copyfile(source, export)
    data = json.loads(export.read_text())
    entry = next(item for item in data["story"] if item["status"] == status)
    entry["evidence"] = {"method": "bounded", "scope": {"size": 1}}
    export.write_text(json.dumps({"story": [entry], "world": world}))
    problems = export_problems(json.loads(export.read_text()), export, strict=True)
    assert any("domain fingerprint or enumeration" in issue for issue in problems)
    assert any("world_hash differs" in issue for issue in problems)
    assert any("requires atoms_hash" in issue for issue in problems)
    assert any("requires content_hash" in issue for issue in problems)
    assert any("requires deps_hash" in issue for issue in problems)
    if status == "promoted":
        entry["contract"] = None
        export.write_text(json.dumps({"story": [entry], "world": world}))
        problems = export_problems(json.loads(export.read_text()), export, strict=True)
        assert any("promoted requires contract" in issue for issue in problems)
    if status == "verified":
        entry["evidence"] = None
        export.write_text(json.dumps({"story": [entry], "world": world}))
        problems = export_problems(json.loads(export.read_text()), export, strict=True)
        assert any("verified/promoted requires evidence" in issue for issue in problems)


def test_evidence_world_hash_must_match_declaration(export_copy):
    data = json.loads(export_copy.read_text())
    entry = next(item for item in data["story"] if item["status"] == "promoted")
    entry["evidence"]["world_hash"] = "0" * 64
    export_copy.write_text(json.dumps({"story": [entry], "world": "code"}))
    problems = export_problems(json.loads(export_copy.read_text()), export_copy, strict=True)
    assert any("evidence world_hash differs from declaration world hash" in issue
               for issue in problems)
    entry["world_hash"] = "0" * 64
    export_copy.write_text(json.dumps({"story": [entry], "world": "code"}))
    problems = export_problems(json.loads(export_copy.read_text()), export_copy, strict=True)
    assert any("evidence world_hash differs from declaration world hash" in issue
               for issue in problems)


def test_enumerated_evidence_size_is_exact(export_copy):
    data = json.loads(export_copy.read_text())
    entry = next(item for item in data["story"] if item["status"] == "promoted" and
                 isinstance(item["evidence"]["scope"].get("input_hashes"), list) and
                 item["evidence"]["scope"]["input_hashes"])
    entry["evidence"]["scope"]["size"] += 1
    export_copy.write_text(json.dumps({"world": "code", "story": [entry]}))
    problems = export_problems(json.loads(export_copy.read_text()), export_copy, strict=True)
    assert any("input_hashes count differs from scope.size" in issue for issue in problems)


def test_compiler_derived_world_hash_is_a_declared_world(tmp_path):
    export = tmp_path / "compiler.json"
    data = json.loads((ROOT / "docs/assets/data/meta/compiler.json").read_text())
    entry = next(item for item in data["story"] if item["name"] == "emit")
    entry["world_hash"] = "0" * 64
    entry["evidence"]["world_hash"] = "0" * 64
    export.write_text(json.dumps({"world": "compiler", "story": [entry]}))
    problems = export_problems(json.loads(export.read_text()), export, strict=True)
    assert any("unknown declaration world_hash" in issue for issue in problems)


@pytest.mark.parametrize("mutation,expected", [
    (lambda data: data.update(story=None), "story must be an array"),
    (lambda data: data["story"][0].update(examples=None), "examples must be an array"),
    (lambda data: data["story"][0]["examples"][0].update(
        outcome={"kind": "Ok", "value": {"bad": "format"}}), "invalid ascii example"),
    (lambda data: data["story"][0]["examples"][0].update(inputs={"bad": "format"}),
     "invalid ascii example"),
    (lambda data: data.update(showcase=None), "showcase must be an array"),
    (lambda data: data.update(world=[]), "world must be a string"),
    (lambda data: data["story"][0].update(spec=[]), "spec must be an object"),
    (lambda data: data["story"][0].update(status={"invalid": True}), "invalid status"),
])
def test_malformed_export_reports_problem_not_exception(export_copy, mutation, expected):
    data = json.loads(export_copy.read_text())
    mutation(data)
    export_copy.write_text(json.dumps(data))
    problems = check(export_copy.parents[4], fresh_exports=False, strict=True)
    assert any(expected in issue for issue in problems)


def test_nested_export_mutations_never_abort_checker(export_copy):
    original = json.loads(export_copy.read_text())
    randomizer = random.Random(18)
    for _ in range(12):
        data = copy.deepcopy(original)
        entry = data["story"][0]
        target = randomizer.choice((entry, entry["examples"][0], entry["evidence"],
                                    entry["evidence"]["scope"]))
        key = randomizer.choice(tuple(target))
        target[key] = randomizer.choice((None, False, 42, [], {}, "invalid"))
        export_copy.write_text(json.dumps(data))
        assert check(export_copy.parents[4], fresh_exports=False, strict=True)
