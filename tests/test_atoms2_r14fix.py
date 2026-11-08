"""Round 14 UI regressions for the first tower, glossary, and workshop."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opulse.atoms.values import decode
from opulse.worlds_v2.integer.story import scope_for
from tools import mkdocs_hooks

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which(os.environ.get("NODE") or "node")


def test_recorded_tower_calls_are_checked_or_explicitly_outside_scope():
    tower = json.loads((ROOT / "docs/assets/data/atoms2/first_tower.json").read_text())
    targets = {"nat.make": "nat", "frac.make": "frac"}
    for card in tower["cards"]:
        examples = [card["example"], *card["example"].get("input_from", [])]
        for example in examples:
            name = targets.get(example["target"], example["target"])
            if name == "denominator":
                continue
            scope = scope_for(name).domain if name != "seen_value" else tuple((value,) for value in range(-10, 11))
            if name == "repeat":
                assert example["args"][0] == {"t": "fn", "v": "succ"}
                assert "succ" in scope_for(name).extra["op_family"]
            raw_args = example["args"][1:] if name == "repeat" else example["args"]
            args = tuple(decode(arg) for arg in raw_args)
            assert args in scope or example.get("outside_checked_scope"), example["call"]
    assert tuple(decode(arg) for arg in tower["failing"]["args"]) in scope_for("frac").domain
    js = (ROOT / "docs/assets/js/atoms2/first-tower.js").read_text()
    assert 'if (example.outside_checked_scope)' in js
    assert 'if (step.outside_checked_scope)' in js


def test_glossary_comparison_builds_from_both_exports_and_without_volumes(tmp_path, monkeypatch):
    original = json.loads((ROOT / "docs/assets/data/worlds_v2/shadows.json").read_text())
    result = subprocess.run(["git", "show", "cx/at_worlds:docs/assets/data/worlds_v2/shadows.json"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    worlds = json.loads(result.stdout) if result.returncode == 0 else json.loads(json.dumps(original))
    if result.returncode != 0:
        worlds["decl"]["constants"] = {name: value for name, value in original["decl"]["constants"].items()
                                         if name in ("M", "N")}
    no_volumes = json.loads(json.dumps(original))
    no_volumes["decl"]["constants"] = {}
    docs = tmp_path / "docs"
    source = docs / "assets/data/worlds_v2/shadows.json"
    source.parent.mkdir(parents=True)
    monkeypatch.setattr(mkdocs_hooks, "ROOT", tmp_path)
    template = (ROOT / "docs/reference/glossary.md").read_text()
    page = SimpleNamespace(file=SimpleNamespace(src_uri="reference/glossary.md"))
    config = SimpleNamespace(docs_dir=str(docs))
    for export in (original, worlds, no_volumes):
        source.write_text(json.dumps(export))
        rendered = mkdocs_hooks.on_page_markdown(template, page, config, None)
        assert "{{ A2_GLOSSARY_COMPARISON }}" not in rendered
        assert "Example unavailable" not in rendered
        snippet = re.search(r"```python\n(.*?)\n```", rendered, re.DOTALL).group(1)
        run = subprocess.run([sys.executable, "-c", snippet], cwd=ROOT,
                             env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                             capture_output=True, text=True, check=True)
        assert run.stdout.strip() == "same full state: False\nsame top view: True\nsame front view: False"
        assert run.stdout.strip() in rendered


def test_glossary_constructs_distinct_volumes_with_same_top_and_different_front():
    from opulse.worlds_v2.shadows.deep_hosts import front, top

    first, second = mkdocs_hooks.glossary_volume_pair()
    assert first != second and top(first) == top(second) and front(first) != front(second)


def test_glossary_comparison_rejects_incompatible_probe_contract(tmp_path):
    export = json.loads((ROOT / "docs/assets/data/worlds_v2/shadows.json").read_text())
    export["decl"]["observation"]["capabilities"]["learner"]["probes"] = ["front"]
    source = tmp_path / "shadows.json"
    source.write_text(json.dumps(export))
    with pytest.raises(ValueError, match="learner probes changed"):
        mkdocs_hooks.glossary_volume_comparison(source)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_workshop_featured_examples_are_nontrivial_and_runnable():
    script = """
const base = process.argv[1];
for (const part of ['kit', 'lab-preview-world', 'boundary', 'define']) require(base + '/' + part + '.js');
const api = A2.define, object = api.presetsFor('object')[0].source;
const combinator = api.presetsFor('combinator')[0].source;
const first = api.pipeline(object, 'object', 'integer');
const second = api.pipeline(combinator, 'combinator', 'integer');
const usage = api.evaluate(api.parse('preview_use = @adjust_twice[succ](41) L1', 'operation'), 'operation', 'integer', [], [second.record]);
const ratio = api.evaluate(api.parse('preview_use = ResiduePair(21, 35) L1', 'operation'), 'operation', 'integer', [], [first.record]);
console.log(JSON.stringify({object, combinator, first: first.error, second: second.error, result: usage.result, ratio: ratio.outcome}));
"""
    result = subprocess.run([NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2")],
                            check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert "canon reduce" in data["object"] and "f(add(f(x), 17))" in data["combinator"]
    assert data["first"] is None and data["second"] is None and data["result"] == 60
    assert [field["v"] for field in data["ratio"]["ok"]["f"]] == [3, 5]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_workshop_navigation_and_invalid_use_clear_previous_result():
    define = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    lab = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    assert '    towerButton.click();' not in define
    use = define[define.index("    function use() {"):define.index('    useButton.addEventListener("click", use);')]
    choose = lab[lab.index("    function chooseWorld(world) {"):lab.index("    var requestedWorld =")]
    script = """
const root = {location: {href: 'https://example.test/play/', hash: ''}, A2: {define: {enterWorkshop() { throw new Error('Selecting a world must not reset the editor'); }}}};
const worldPicker = {value: 'computer'};
const draft = {text: 'op my_draft(a) = add(a, 19) L1', preview: 'checked'};
eval(process.argv[1]);
chooseWorld('integer');
let destroyed = false;
let boundaryViewer = {destroy() { destroyed = true; }}, tree = {id: 'old'};
const trace = {children: ['old trace'], replaceChildren(...children) { this.children = children; }};
const useStatus = {textContent: 'old result'}, expression = {value: 'broken('};
const parse = () => { throw new Error('invalid syntax'); };
eval(process.argv[2]);
use();
console.log(JSON.stringify({draft, world: worldPicker.value, hash: root.location.hash,
  destroyed, boundaryViewer, tree, trace: trace.children, status: useStatus.textContent}));
"""
    result = subprocess.run([NODE, "-e", script, choose, use], check=True, capture_output=True, text=True)
    state = json.loads(result.stdout)
    assert state == {"draft": {"text": "op my_draft(a) = add(a, 19) L1", "preview": "checked"}, "world": "integer", "hash": "definition-workshop", "destroyed": True,
                     "boundaryViewer": None, "tree": None, "trace": [],
                     "status": "Cannot use this expression: invalid syntax"}


def test_mobile_summary_wraps_and_prerequisites_have_layers():
    css = (ROOT / "docs/assets/css/atoms2-first-tower.css").read_text()
    assert ".first-tower-declaration summary { cursor: pointer; overflow-wrap: anywhere; white-space: normal;" in css
    js = (ROOT / "docs/assets/js/atoms2/first-tower.js").read_text()
    # Notation v3: prerequisite tokens receive the layer as a positional renderer argument.
    assert '"operation", layers[name])' in js
    tower = json.loads((ROOT / "docs/assets/data/atoms2/first_tower.json").read_text())
    layers = {card["name"]: card["layer"] for card in tower["cards"]}
    assert layers["nat"] == 1 and layers["repeat"] == 2


def test_checks_uses_three_key_values_and_kinds_identifies_counter():
    checks = (ROOT / "docs/assets/js/atoms2/learn-checks.js").read_text()
    kinds = (ROOT / "docs/assets/js/atoms2/learn-kinds.js").read_text()
    for value in ("Even.val<18>", "Even.val<20>", "Even.val<24>"):
        assert value in checks
    assert "scope, not 13 steps" in checks
    assert "BigInt counter counts binary groupings of the eight operands" in kinds
