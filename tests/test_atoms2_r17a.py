"""Round 17 scope and signed-workshop regressions."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from opulse.atoms.values import decode
from opulse.worlds_v2.grammar import story as grammar_story
from opulse.worlds_v2.integer.story import scope_for
from opulse.worlds_v2.roads import depth_hosts
from opulse.worlds_v2.roads.story import TINY
from tools.atoms2_roads_export import TARGETS, outside_checked_scope

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which(os.environ.get("NODE") or "node")
DATA = ROOT / "docs/assets/data/atoms2"


def test_every_published_metro_outcome_is_outside_its_four_node_scope():
    data = json.loads((DATA / "roads_core.json").read_text())
    assert {card["name"] for card in data["cards"]} == set(TARGETS)
    for card in data["cards"]:
        example = card["example"]
        args = tuple(decode(arg) for arg in example["args"])
        assert card["evidence"]["scope"]["size"] == 256
        assert outside_checked_scope(card["evidence"]["scope"], args)
        assert example["outside_checked_scope"] is True, example["call"]
    scope = data["cards"][0]["evidence"]["scope"]
    checked = depth_hosts.to_card((("A", "B", "C", "D"),
              (("A", "B", 1), ("A", "C", 1), ("B", "D", 1), ("C", "D", 1))))
    assert not outside_checked_scope(scope, (checked,))
    assert not outside_checked_scope(scope, (TINY,))
    assert data["failing"]["outside_checked_scope"] is True
    assert "checked cut" not in (ROOT / "docs/worlds/roads/index.md").read_text()
    assert "checked cut" not in (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()


def test_each_grammar_call_marks_its_actual_scope():
    rows = json.loads((DATA / "grammar_core.json").read_text())["rows"]
    words, tiny = grammar_story._domains(None, None)
    for kind, row in rows.items():
        example = row["example"]
        if kind == "object":
            assert "three-numeral" in row["scope"]
            assert example["outside_checked_scope"] is True
            assert "outside_checked_scope" not in row["failure"]
        else:
            assert "three-numeral" in row["scope"]
            assert example["outside_checked_scope"] is True
            assert all(len([value for value in word.fields if type(value) is int]) == 3
                       for word in (tiny if kind == "combinator" else words))


def test_every_first_tower_call_marks_its_actual_scope():
    tower = json.loads((DATA / "first_tower.json").read_text())
    for card in tower["cards"]:
        for example in (card["example"], *card["example"].get("input_from", [])):
            target = example["target"].removesuffix(".make")
            args = tuple(decode(arg) for arg in example["args"])
            if target == "repeat":
                args = args[1:]
            scope = (tuple((value,) for value in range(-10, 11)) if target == "seen_value" else
                     scope_for(target).domain if target != "denominator" else None)
            assert example.get("outside_checked_scope", False) == (scope is not None and args not in scope), example["call"]
    assert "outside_checked_scope" not in tower["failing"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_workshop_mul_agrees_with_signed_core_on_both_input_orders():
    assert "nonnegative second input" in (ROOT / "docs/play/index.md").read_text()
    tower = json.loads((DATA / "first_tower.json").read_text())
    core_mul = next(card for card in tower["cards"] if card["name"] == "mul")
    assert core_mul["example"]["call"] == "mul(-6, 5)"
    assert core_mul["example"]["outcome"] == {"ok": {"t": "int", "v": -30}}
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
require(process.argv[1] + '/lab-preview-world.js');
const define = require(process.argv[1] + '/define.js');
const variable = name => ({node: 'Var', name});
const parsed = {name: 'signed_preview', params: ['a', 'b'], body: {
  node: 'Call', fn: 'mul', args: [variable('a'), variable('b')]}};
for (const args of [[5, -6], [-6, 5], [-6, -5], [5, 0]]) {
  const result = define.evaluate(parsed, 'operation', 'integer', args, [], {fuel: 400});
  assert.deepEqual(result.outcome, {ok: {t: 'int', v: args[0] * args[1]}});
}
'''
    subprocess.run([NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2")], check=True)


def test_learn_identifies_second_tower_and_separates_definition_evidence():
    learn = (ROOT / "docs/learn/index.md").read_text()
    home = (ROOT / "docs/index.md").read_text()
    assert "One tower: roads" in learn
    assert "second, independent tower" in learn
    assert "second, independent tower" in home
    assert "Frac&lt;1, 0&gt;" in learn
    for file in ("atoms2/roads.js", "worlds/catalog-ui.js"):
        source = (ROOT / "docs/assets/js" / file).read_text()
        assert 'A2.scopedBadge(card.evidence, null' in source or 'root.A2.scopedBadge(evidence, null' in source
        assert "Core run on Metro (outside the checked scope)" in source
        assert "A2.scopedBadge(card.evidence" in source or "root.A2.scopedBadge(evidence" in source
