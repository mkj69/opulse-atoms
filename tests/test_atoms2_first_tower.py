"""Regression checks for the first-screen core-run integer tower."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.atoms import nodes
from opulse.atoms.kernel import FnRef
from opulse.atoms.notation import parse_definition, print_definition
from opulse.atoms.observations import check_observation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Ok, decode, encode_outcome
from opulse.worlds_v2.integer.story import frac

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "docs/assets/data/atoms2/first_tower.json"
NODE = shutil.which(os.environ.get("NODE") or "node")


def test_recorded_tower_controls_do_not_claim_to_run_in_browser():
    script = (ROOT / "docs/assets/js/atoms2/first-tower.js").read_text()
    assert '"Step through the recorded run"' in script
    assert '"Next tower row"' in script
    assert '"Replay tower rows"' in script
    assert 'Use the step button to see each recorded core result' in script
    assert '"Next recorded step"' not in script
    assert 'class: "a2-btn" }, "Run"' not in script


def test_unprintable_core_rows_render_as_prose_only():
    script = (ROOT / "docs/assets/js/atoms2/first-tower.js").read_text()
    assert 'printed ? A2.expr(card.record_summary) : document.createTextNode(card.record_summary)' in script
    assert 'printed ? A2.expr(card.record_summary) : card.record_summary' in script
    for page in (ROOT / "docs/index.md", ROOT / "docs/learn/index.md"):
        fallback = page.read_text().split('<ol class="first-tower-fallback"', 1)[1].split("</ol>", 1)[0]
        assert fallback.count("Core summary:") == 5
        assert "printer unavailable" not in fallback
        assert "<code>obs ?seen_value" in fallback
        assert "<code>Multiplication" not in fallback


def exporter():
    spec = importlib.util.spec_from_file_location("atoms2_tower_export", ROOT / "tools/atoms2_tower_export.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_is_deterministic_and_matches_checked_in_artifact():
    from opulse.notation3.export import add_notation3

    expected = json.loads(EXPORT.read_text())
    actual = add_notation3(exporter().build_export(), 'atoms2', source='atoms2/first_tower.json')
    assert expected == actual


def test_tower_builds_only_its_own_promoted_cards():
    library = exporter().build_tower_library()
    invented = {name for name, record in library.definitions.items() if record.origin == "invented"}
    assert invented == {"nat", "repeat", "mul", "frac", "qmul"}
    assert all(library.get(name).status == "promoted" for name in invented)
    assert all(library.get(name).evidence.scope["size"] > 0 for name in invented)


def test_each_layer_and_dependency_is_from_core_records():
    library = exporter().add_core_observation(exporter().build_tower_library())
    artifact = json.loads(EXPORT.read_text())
    assert {card["kind"] for card in artifact["cards"]} == {
        "object", "operation", "combinator", "observation"}
    assert {card["name"] for card in artifact["cards"]} == {
        "nat", "repeat", "mul", "frac", "qmul", "seen_value"}
    for card in artifact["cards"]:
        record = library.get(card["name"])
        assert card["dependencies"] == list(record.depends_on)
        assert card["evidence"]["scope"]["size"] == record.evidence.scope["size"]
        invented = {dependency.split(".")[0] for dependency in record.depends_on
                    if library.get(dependency.split(".")[0]).origin == "invented"}
        assert card["invented_dependencies"] == sorted(invented)
        assert card["layer"] == 1 + max((library.get(dep).layer for dep in invented), default=0)
    assert "nat" in artifact["cards"][1]["invented_dependencies"]
    assert "repeat" in artifact["cards"][2]["invented_dependencies"]
    assert {"frac", "mul"} <= set(artifact["cards"][4]["invented_dependencies"])
    assert {card["name"] for card in artifact["cards"] if card["summary_label"].startswith("Printed from")} == {"seen_value"}
    for card in artifact["cards"]:
        if card["summary_label"].startswith("Printed from"):
            bare = replace(library.get(card["name"]), status="written", evidence=None,
                           contract=None, cost=Cost(), id=None)
            assert card["record_summary"] == print_definition(bare)
            assert "re-parses: yes" in card["summary_label"]
            parsed = parse_definition(card["record_summary"])
            assert parsed.layer == card["layer"]
            assert parsed.body == library.get(card["name"]).body
        else:
            assert card["summary_label"] == "Core summary"
            assert card["record_summary"].endswith(".")
            assert not card["record_summary"].startswith(("obj ", "op ", "comb "))
    assert {card["display_name"] for card in artifact["cards"] if card["kind"] == "object"} == {
        "Nat", "Frac"}
    assert "<code>nat</code>" not in (ROOT / "docs/index.md").read_text()
    assert "frac(x)" not in (ROOT / "docs/learn/index.md").read_text()


def test_observation_passes_core_checker_not_integer_adapter():
    library = exporter().add_core_observation(exporter().build_tower_library())
    record = library.get("seen_value")
    assert record.status == "promoted"
    assert check_observation(record, library) == []
    assert record.depends_on == ("value",)
    assert "whole" not in library.definitions
    assert "bounded_convergent" not in library.definitions
    product = library.run("qmul", (frac(-1, 2), frac(2, 3)), trace=True).outcome
    assert isinstance(product, Ok)
    denominator = library.run("denominator", (product.value,), trace=True).outcome
    assert isinstance(denominator, Ok)
    observation = next(card for card in json.loads(EXPORT.read_text())["cards"]
                       if card["name"] == "seen_value")["example"]
    assert observation["args"] == [exporter().encode(denominator.value)]
    assert observation["call"] == f"?seen_value{{{denominator.value}}}"
    assert observation["input_from"][0]["target"] == "qmul"
    assert observation["input_from"][1]["target"] == "denominator"
    assert observation["input_from"][0]["outcome"] == encode_outcome(product)
    assert observation["input_from"][1]["outcome"] == encode_outcome(denominator)
    assert encode_outcome(library.run("seen_value", (denominator.value,), trace=True).outcome) == observation["outcome"]


def test_each_run_and_failure_recomputed_independently():
    library = exporter().add_core_observation(exporter().build_tower_library())
    artifact = json.loads(EXPORT.read_text())
    sources = [step for card in artifact["cards"] for step in card["example"].get("input_from", ())]
    for example in [*(card["example"] for card in artifact["cards"]), *sources, artifact["failing"]]:
        run = library.run(example["target"], [decode(arg) for arg in example["args"]], trace=True)
        assert encode_outcome(run.outcome) == example["outcome"]
        assert run.steps == example["steps"]
        assert example["trace"]["outcome"] == example["outcome"]
    assert artifact["failing"]["outcome"] == {"bottom": "invalid"}


def test_first_screens_link_artifact_and_keep_static_fallback():
    for page in (ROOT / "docs/index.md", ROOT / "docs/learn/index.md"):
        source = page.read_text()
        assert 'data-a2="first-tower"' in source
        assert "first_tower.json" in source
        assert "data-first-tower-fallback" in source
        assert "Bottom(invalid)" in source if page.parent.name == "learn" else "@repeat" in source
        assert "Core summary:" in source
        assert "printer unavailable" not in source
        assert "Printed from the core definition (re-parses: yes)" in source
        assert "Core summary (design text, not parseable source)" not in source
        assert "story design text" in source
        expected = exporter().fallback_html(json.loads(EXPORT.read_text()))
        assert re.search(r'<ol class="first-tower-fallback"[^>]*>\n(.*?)\n</ol>', source, re.DOTALL).group(1) == expected
        assert source.index('data-roads-') < source.index('data-a2="first-tower"')
    assert "../play/challenge/" in (ROOT / "docs/learn/index.md").read_text()


def test_mul_summary_matches_separate_counter_and_add_loop_in_core():
    definition = exporter().build_tower_library().get("mul")
    bindings = {item.name: item.value for item in nodes.walk(definition.body) if isinstance(item, nodes.Let)}
    counter = bindings["counter"]
    product = bindings["product"]
    assert isinstance(counter, nodes.Call) and counter.fn == "repeat"
    assert isinstance(counter.args[0], nodes.Lit) and counter.args[0].value == FnRef("succ")
    assert isinstance(product, nodes.Rec) and product.fn == "multiply_loop"
    assert any(isinstance(item, nodes.Call) and item.fn == "add" and
               item.args == (nodes.Var("total"), nodes.Var("magnitude_left"))
               for item in nodes.walk(product))
    summary = next(card["record_summary"] for card in json.loads(EXPORT.read_text())["cards"]
                   if card["name"] == "mul")
    assert "counts ticks" in summary and "adds the left magnitude once per tick" in summary
    assert summary.endswith("input signs differ.")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_browser_helpers_format_outcomes_and_elided_traces():
    script = ROOT / "docs/assets/js/atoms2/first-tower.js"
    result = subprocess.run([NODE, "-e", """
      const assert = require('node:assert/strict');
      global.A2 = require(process.argv[2]);
      global.A2.formatValue = value => 'v' + value.v;
      const view = require(process.argv[1]);
      assert.equal(view.resultText({ok: {v: 8}}), 'Ok(v8)');
      global.A2.formatValue = value => typeof value === 'object' ? 'v' + value.v : String(value);
      assert.equal(view.resultText({ok: {t: 'nat', tag: 'val', f: [{t: 'int', v: 5}]}}), 'Ok(Nat<v5>)');
      assert.equal(view.resultText({ok: {t: 'frac', tag: 'val', f: [{t: 'pair', tag: 'items',
        f: [{t: 'int', v: -5}, {t: 'int', v: 8}]}]}}), 'Ok(Frac<v-5, v8>)');
      global.A2.formatValue = value => 'Bottom(' + value.bottom + ')';
      assert.equal(view.resultText({bottom: 'invalid'}), 'Bottom(invalid)');
      const lines = view.traceLines({name: 'frac.make', outcome: {bottom: 'invalid'},
        steps: 2, children: [], elided: 4}, 0);
      assert.match(lines.join(' '), /4 child calls elided/);
    """, str(script), str(script.with_name("kit.js"))], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
