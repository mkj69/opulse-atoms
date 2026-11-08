"""Review-19 export commitments and executable ASCII examples."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.values import boolean, encode
from opulse.meta.check import export_problems
from opulse.meta.export_util import parse_meta_definition
from opulse.meta.worlds.builder import export


def test_builder_operation_roles_round_trip():
    rows = json.loads(export.DATA.read_text())["story"]
    for name, role in (("product", "combine"), ("audit_product", "decide")):
        row = next(item for item in rows if item["name"] == name)
        assert parse_meta_definition(row["ascii"]).spec.role == role == row["spec"]["role"]
        broken = deepcopy(row)
        broken["spec"]["role"] = "transform"
        assert any("signature differs" in issue for issue in export_problems(
            {"world": "builder", "story": [broken]}, "probe", strict=True))


def test_false_law_example_is_rejected():
    source = "law #always: eq(x, x) for x: int L1"
    assert kernel.evaluate(parse_meta_definition(source).body, {"x": 2},
                           kernel.DictScope((kernel.Atom("eq", 2, lambda left, right: left == right),))
                           ).outcome == kernel.Ok(True)
    row = {"kind": "law", "name": "always", "symbol": "#always", "status": "callable",
           "definition": "Reflexivity of equality.", "ascii": source,
           "examples": [{"ascii": "#always(2) = false", "inputs": [encode(2)],
                         "outcome": {"kind": "Ok", "value": encode(boolean(False))}}]}
    assert any("declaration evaluation" in issue for issue in export_problems(
        {"world": "code", "story": [row]}, "probe", strict=True))


@pytest.mark.parametrize("field,value", [(field, value) for field in
                         ("content_hash", "deps_hash", "atoms_hash") for value in ("0" * 64, "")])
def test_evidence_commitments_are_recomputed(field, value):
    row = next(item for item in json.loads(Path("docs/assets/data/meta/code.json").read_text())["story"]
               if item["status"] == "promoted")
    row["evidence"][field] = value
    assert any(field in issue for issue in export_problems(
        {"world": "code", "story": [row]}, "probe", strict=True))


def test_evidence_does_not_follow_rewritten_ascii_body():
    rows = json.loads(Path("docs/assets/data/meta/code.json").read_text())["story"]
    row = deepcopy(next(item for item in rows if item["name"] == "expr_size"))
    row["body"] = nodes.to_json(nodes.Lit(1))
    row["ascii"] = "op expr_size(c: code) -> int = 1 L1"
    assert any("exported body differs from checked definition" in issue for issue in export_problems(
        {"world": "code", "story": [row]}, "probe", strict=True))


def test_world_hash_is_checked_against_declaration():
    rows = json.loads(Path("docs/assets/data/meta/code.json").read_text())["story"]
    row = deepcopy(next(item for item in rows if item["name"] == "expr_size"))
    row["evidence"]["world_hash"] = "0" * 64
    assert any("world_hash differs from declaration world hash" in issue for issue in export_problems(
        {"world": "code", "story": [row]}, "probe", strict=True))


def test_bridge_outside_domain_cannot_claim_success():
    row = {"kind": "bridge", "name": "partial", "symbol": "~partial", "status": "callable",
           "definition": "Map only positive integers.",
           "ascii": "bridge ~partial: int -> int = x where eq(x, 1) commutes (eq -> eq) L1",
           "interface": [["eq", "eq"]], "evidence": {"checks": ["commutes"]},
           "examples": [{"ascii": "~partial(0) = 0", "inputs": [encode(0)],
                         "outcome": {"kind": "Ok", "value": encode(0)}}]}
    assert any("declaration evaluation" in issue for issue in export_problems(
        {"world": "code", "story": [row]}, "probe", strict=True))
    row["examples"][0]["ascii"] = '~partial(0) = fail("outside_domain")'
    row["examples"][0]["outcome"] = {"kind": "Bottom", "reason": "outside_domain"}
    assert export_problems({"world": "code", "story": [row]}, "probe", strict=True) == []


def test_bridge_mapped_value_is_checked_against_its_body():
    row = {"kind": "bridge", "name": "increment", "symbol": "~increment", "status": "callable",
           "definition": "Map integers by adding one.",
           "ascii": "bridge ~increment: int -> int = add(x, 1) commutes (add -> add) L1",
           "interface": [["add", "add"]], "evidence": {"checks": ["commutes"]},
           "examples": [{"ascii": "~increment(2) = 3", "inputs": [encode(2)],
                         "outcome": {"kind": "Ok", "value": encode(3)}}]}
    assert export_problems({"world": "code", "story": [row]}, "probe", strict=True) == []
    row["examples"][0].update(ascii="~increment(2) = 4",
                              outcome={"kind": "Ok", "value": encode(4)})
    assert any("declaration evaluation" in issue for issue in export_problems(
        {"world": "code", "story": [row]}, "probe", strict=True))
