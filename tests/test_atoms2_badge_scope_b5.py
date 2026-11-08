"""An evidence badge requires auditable checked inputs, not just a method or size."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which(os.environ.get("NODE") or "node")


def render_scope_cases(roads, fixture):
    fixture.write_text(json.dumps(roads))
    script = r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children) => ({tag, text: attrs.text || children || '', setAttribute() {}, addEventListener() {}});
      A2.badge = (status) => ({tag: 'button', textContent: status, setAttribute() {}});
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      const roads = require(process.argv[2]);
      const examples = roads.story.filter(row => ['optimal', 'survives', 'cut_certificate'].includes(row.name));
      console.log(JSON.stringify({
        status: A2.worlds.status(roads),
        badges: examples.map(row => {
          const badge = A2.worlds.towerBadge(row, 'roads.json', roads.decl);
          return badge.textContent || badge.text;
        }),
        scoped: examples.map(row => {
          const badge = A2.scopedBadge(row.evidence, '256 weightings', {});
          return badge.textContent || badge.text;
        }),
      }));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT), str(fixture)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_integrated_roads_unrecorded_observations_cannot_show_badges(tmp_path):
    exported = (ROOT / "docs/assets/data/worlds_v2/roads.json").read_text()
    fixture = tmp_path / "integrated-roads.json"
    fixture.write_text(exported)
    roads = json.loads(fixture.read_text())
    entries = [row for row in roads["story"] if row["name"] in
               {"optimal", "survives", "cut_certificate"}]
    assert len(entries) == 3
    recorded = render_scope_cases(roads, fixture)
    assert recorded["scoped"] == ["bounded"] * 3
    for entry in entries:
        entry["evidence"]["scope"]["checked"] = "unrecorded"
    result = render_scope_cases(roads, fixture)
    assert result["badges"] == ["scope not recorded"] * 3
    assert result["scoped"] == ["scope not recorded"] * 3


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_grammar_unrecorded_observations_cannot_show_badges(tmp_path):
    grammar = json.loads((ROOT / "docs/assets/data/worlds_v2/grammar.json").read_text())
    entries = [row for row in grammar["story"] if row["name"] in {"parse_count", "ambiguous"}]
    assert len(entries) == 2
    for entry in entries:
        entry["evidence"]["scope"]["checked"] = "unrecorded"
    fixture = tmp_path / "grammar.json"
    fixture.write_text(json.dumps(grammar))
    script = r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children) => ({tag, className: attrs.class || '',
        text: attrs.text || children || '', setAttribute() {}});
      A2.badge = (status) => ({tag: 'button', className: 'a2-badge', text: status, setAttribute() {}});
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      const world = require(process.argv[2]);
      const entries = world.story.filter(row => ['parse_count', 'ambiguous'].includes(row.name));
      console.log(JSON.stringify(entries.map(row => [A2.worlds.towerBadge(row, 'grammar.json', world.decl),
        A2.scopedBadge(row.evidence, '81 inputs', {})]).map(pair =>
          pair.map(node => ({tag: node.tag, className: node.className, text: node.text})))));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT), str(fixture)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [[{"tag": "span", "className": "w2-foot",
                                          "text": "scope not recorded"},
                                         {"tag": "span", "className": "a2-scope-note",
                                          "text": "scope not recorded"}]] * 2


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_world_status_requires_recorded_checked_inputs(tmp_path):
    roads = json.loads((ROOT / "docs/assets/data/worlds_v2/roads.json").read_text())
    for entry in roads["story"]:
        entry["evidence"]["scope"]["checked"] = "unrecorded"
    fixture = tmp_path / "roads.json"
    fixture.write_text(json.dumps(roads))
    script = r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      console.log(A2.worlds.status(require(process.argv[2])));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT), str(fixture)],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "design"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_open_kinds_exports_filter_by_recorded_kinds(tmp_path):
    index = json.loads((ROOT / "docs/assets/data/worlds_v2/index.json").read_text())
    expected = {"comb_obs": ["combinator", "observation"], "comb_only": ["combinator"],
                "obj_only": ["object"], "obj_op": ["object", "operation"],
                "obs_only": ["observation"], "op_only": ["operation"]}
    entries = {item["world"]: item for item in index["worlds"]}
    worlds = []
    for name, kinds in expected.items():
        export = json.loads((ROOT / "docs/assets/data/worlds_v2" / entries[name]["file"]).read_text())
        assert export["open_kinds"] == kinds
        assert export["tags"]["open_kinds"] == kinds
        worlds.append(export)
    fixture = tmp_path / "open-kinds.json"
    fixture.write_text(json.dumps(worlds))
    script = r"""
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      const catalog = require(process.argv[1] + '/docs/assets/js/worlds/catalog-ui.js');
      const worlds = require(process.argv[2]);
      console.log(JSON.stringify(Object.fromEntries(A2.KINDS6.map(kind =>
        [kind, catalog.filterWorlds(worlds, {open_kinds:kind}).map(world => world.world)]))));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT), str(fixture)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {
        "object": ["obj_only", "obj_op"], "operation": ["obj_op", "op_only"],
        "combinator": ["comb_obs", "comb_only"], "observation": ["comb_obs", "obs_only"],
        "law": [], "bridge": []}


def test_scope_copy_agrees_with_regenerated_exports():
    roads = json.loads((ROOT / "docs/assets/data/worlds_v2/roads.json").read_text())
    grammar = json.loads((ROOT / "docs/assets/data/worlds_v2/grammar.json").read_text())
    for world, names in ((roads, {"optimal", "survives", "cut_certificate"}),
                         (grammar, {"parse_count", "ambiguous"})):
        selected = [row for row in world["story"] if row["name"] in names]
        assert len(selected) == len(names)
        assert all(row["evidence"]["scope"]["checked"] != "unrecorded" for row in selected)
    home = (ROOT / "docs/index.md").read_text()
    kinds = (ROOT / "docs/learn/kinds.md").read_text()
    catalog = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert "The optimality observation has no recorded checked-input scope" not in home
    assert "The chart combinator and parse-count observation have no recorded" not in kinds
    assert "Checked-input scopes are not recorded for three observations" not in catalog
    assert "outside that checked scope" in home and "outside that checked scope" in kinds


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_recorded_and_missing_scopes_on_published_artifacts():
    for name in ("first_tower", "roads_core"):
        artifact = json.loads((ROOT / "docs/assets/data/atoms2" / f"{name}.json").read_text())
        evidence = artifact["cards"][0]["evidence"]
        script = """
          const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
          const evidence = JSON.parse(process.argv[2]);
          const without = {...evidence, scope: {...evidence.scope, checked: 'unrecorded'}};
          console.log(JSON.stringify({real:A2.hasRecordedScope(evidence), missing:A2.hasRecordedScope(without),
            absent:A2.hasRecordedScope({...evidence, scope:{size:60}}),
            unhashed:A2.hasRecordedScope({...evidence, scope:{size:60, checked:{size:60}}}),
            checked:A2.evidenceRecord({evidence}).checkedInputs}));
        """
        result = subprocess.run([NODE, "-e", script, str(ROOT), json.dumps(evidence)],
                                capture_output=True, text=True, check=True)
        actual = json.loads(result.stdout)
        assert actual["real"] is True
        assert actual["missing"] is False and actual["absent"] is False and actual["unhashed"] is False
        assert actual["checked"] == evidence["scope"]["checked"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_fallback_scopes_and_run_badges_require_records():
    from tools.atoms2_tower_export import fallback_html

    artifact = json.loads((ROOT / "docs/assets/data/atoms2/first_tower.json").read_text())
    assert "Bounded (61 cases)" in fallback_html(artifact)
    artifact["cards"][0]["evidence"]["scope"]["checked"] = "unrecorded"
    artifact["failing"].pop("outcome")
    rendered = fallback_html(artifact)
    assert "Bounded (61 cases)" not in rendered
    assert rendered.count("scope not recorded") == 2

    script = """
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, text) => ({tag, text: attrs.text || text});
      A2.badge = status => ({text: status === 'executable' ? 'Executable' : status});
      const good = {call:'Route<Metro,A,L>', outcome:{ok:1}, steps:5};
      console.log(JSON.stringify([A2.runBadge(good, 'core.json').text,
        A2.runBadge({...good, outcome:undefined}, 'core.json').text]));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ["Executable", "scope not recorded"]
