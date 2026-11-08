"""The site must never present unparseable design prose as executable source."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.atoms2_parse_status import (
    OUTPUT,
    PLACEHOLDER_LABEL,
    classify,
    generate,
    parses,
)

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def test_parser_classifies_source_and_prose():
    assert parses("obj Run = <key: Int, count: Int> where lt(0, count) sealed (make, key, count) L5")
    assert not parses("obj Fraction = canonicalize a nonzero-denominator pair")
    assert not parses("")
    assert classify("obj Route = <raw: RouteRaw> where false L1") == PLACEHOLDER_LABEL
    assert classify('op best(g: Roads) -> Route = fail("not implemented") L3') == PLACEHOLDER_LABEL
    assert not parses('op best(g: Roads) -> Route = fail("not implemented") L3')


def test_published_roads_placeholders_are_not_source():
    # The roads export used to publish placeholder bodies here; it now publishes no source
    # for definitions the core printer cannot print, and the status never calls them source.
    roads = json.loads((ROOT / "docs/assets/data/worlds_v2/roads.json").read_text())
    status = generate()
    for name in ("Route", "Closure", "cost", "explore", "best", "optimal", "close",
                 "survives", "worst", "mincut", "cut_certificate"):
        row = next(row for row in roads["story"] if row["name"] == name)
        assert "ascii" not in row and "decl" not in row
        assert row["body_sha256"]
        assert status["entries"]["roads/" + name] is False


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_published_roads_entry_renders_placeholder_not_ascii_source():
    script = r"""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, style:{setProperty() {}},
        children: Array.isArray(children) ? children : [children],
        appendChild(child) {this.children.push(child)}});
      A2.expr = value => A2.el('code', {text:value});
      A2.token = value => A2.el('token', {text:value});
      A2.badge = () => Object.assign(A2.el('badge'), {setAttribute() {}});
      A2.register = () => {};
      require(root + '/docs/assets/js/atoms2/tower.js');
      const story = require(root + '/docs/assets/data/worlds_v2/roads.json').story;
      const status = require(root + '/docs/assets/data/atoms2/parse_status.json');
      const row = story.find(entry => entry.name === 'cost');
      const nodes = node => [node, ...(node.children || []).filter(Boolean).flatMap(nodes)];
      const card = A2.worlds.entryCard(row, story, '', {}, 'roads', status);
      console.log(JSON.stringify(nodes(card).map(node => node.attrs && node.attrs.text).filter(Boolean)));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    labels = json.loads(result.stdout)
    # Notation v3: published roads designs are explicitly labeled, never misrepresented as source.
    assert "Design text (not notation v3 source)" in labels
    assert next(entry["design_decl"] for entry in json.loads((ROOT / "docs/assets/data/worlds_v2/roads.json").read_text())["story"]
                if entry["name"] == "cost") in labels
    assert PLACEHOLDER_LABEL not in labels
    assert "ASCII source" not in labels
    assert not any("not implemented" in label for label in labels)


def test_fixture_files_include_source_and_prose(tmp_path):
    worlds = tmp_path / "docs/assets/data/worlds_v2"
    worlds.mkdir(parents=True)
    worlds.joinpath("index.json").write_text(json.dumps({"worlds": []}))
    worlds.joinpath("fixture.json").write_text(json.dumps({"schema": "opulse.world_v2_export/1",
        "world": "fixture", "story": [
            {"name": "Run", "ascii": "obj Run = <key: Int, count: Int> where lt(0, count) sealed (make, key, count) L5"},
            {"name": "Sketch", "ascii": "obj Sketch = a design idea"}]}))
    challenge = tmp_path / "docs/assets/data/challenge/v2.json"
    challenge.parent.mkdir(parents=True)
    challenge.write_text(json.dumps({"ladders": {}, "paths": {"demo": {"steps": [
        {"id": "task/source", "definition": "obj Run = <key: Int, count: Int> where lt(0, count) sealed (make, key, count) L5"},
        {"id": "task/prose", "definition": "obj Sketch = a design idea"}]}}}))
    designs = tmp_path / "docs/worlds/designs.json"
    designs.parent.mkdir(parents=True)
    designs.write_text(json.dumps({"worlds": {"fixture": {"tower": [
        {"name": "Sketch", "decl": "obj Sketch = a design idea"}]}}}))
    status = generate(tmp_path)
    assert status["entries"] == {"fixture/Run": True, "fixture/Sketch": False, "design/fixture/Sketch": False,
                                  "task/prose": False, "task/source": True}
    assert len(status["sources"]) == 4


def test_published_status_is_current_and_covers_each_rendered_definition():
    stored = json.loads((ROOT / OUTPUT).read_text())
    assert stored == generate()
    worlds = ROOT / "docs/assets/data/worlds_v2"
    for path in worlds.glob("*.json"):
        world = json.loads(path.read_text())
        for row in world.get("story", []):
            assert stored["entries"][world["world"] + "/" + row["name"]] == classify(row.get("ascii", row.get("decl")))
            if "ascii" not in row and "decl" not in row:
                assert stored["entries"][world["world"] + "/" + row["name"]] is False
    challenge = json.loads((ROOT / "docs/assets/data/challenge/v2.json").read_text())
    for task in challenge["paths"]["six_kinds_one_world"]["steps"]:
        assert stored["entries"][task["id"]] == classify(task["definition"])
    designs = json.loads((ROOT / "docs/worlds/designs.json").read_text())
    for world_name, world in designs["worlds"].items():
        for row in world.get("tower", []):
            assert stored["entries"]["design/" + world_name + "/" + row["name"]] == classify(row.get("decl"))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_tower_source_and_prose_render_differently():
    script = r"""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, children: Array.isArray(children) ? children : [children],
        appendChild(child) { this.children.push(child); }});
      A2.expr = value => A2.el('code', {text:value});
      A2.token = value => A2.el('token', {text:value});
      A2.badge = () => Object.assign(A2.el('badge'), {setAttribute() {}});
      A2.register = () => {};
      require(root + '/docs/assets/js/atoms2/tower.js');
      const status = {entries: {'fixture/Run':true, 'fixture/Sketch':false}};
      const story = [
        {name:'Run', kind:'object', ascii:'obj Run = <key: Int, count: Int> where lt(0, count) sealed (make, key, count) L5', examples:[], depends_on:[]},
        {name:'Sketch', kind:'combinator', ascii:'comb @Sketch = a design idea', examples:[], depends_on:[]}
      ];
      const flatten = node => [node, ...(node.children || []).filter(Boolean).flatMap(flatten)];
      console.log(JSON.stringify(story.map(row => flatten(A2.worlds.entryCard(row, story, '', {}, 'fixture', status))
        .map(node => [node.tag, node.attrs.text, node.attrs.class]))));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    parsed, prose = json.loads(result.stdout)
    assert any(tag == "code" and text.startswith("obj Run") for tag, text, _ in parsed)
    assert any(tag == "p" and text == "comb @Sketch = a design idea" for tag, text, _ in prose)
    assert not any(tag == "code" and text == "comb @Sketch = a design idea" for tag, text, _ in prose)
    # Notation v3: design prose is labeled against the visible notation, not the machine parser.
    assert any(text == "Design text (not notation v3 source)" for _, text, _ in prose)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_ladder_prompt_never_labels_prose_as_source():
    script = r"""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      function el(tag, attrs = {}, children = []) {
        const element = {tag, attrs, children:[], appendChild(child) {this.children.push(child)},
          replaceChildren(...items) {this.children = items}, setAttribute() {}, addEventListener() {}};
        for (const item of (Array.isArray(children) ? children : [children])) if (item) element.appendChild(item);
        return element;
      }
      A2.el = el;
      A2.expr = text => el('code', {text});
      A2.token = text => el('token', {text});
      A2.badge = () => el('badge');
      A2.kindBadge = kind => el('kind', {text:kind});
      const ladders = require(root + '/docs/assets/js/atoms2/ladders.js');
      global.document = {createElement:tag => el(tag)};
      const host = el('section');
      const task = {id:'task', kind:'object', name:'Fraction', world:'integer', definition:'obj Fraction = design idea',
        purpose:'Check the source', prompt:'Canonicalize Pair<2, 4>.', depends_on:[], answer_format:'value', grader:{}};
      const status = {entries:{task:false}};
      function inspect() {
        const flatten = node => [node, ...node.children.flatMap(flatten)];
        return flatten(host).map(node => [node.tag, node.attrs.text || node.textContent,
          node.attrs.class || node.className]);
      }
      ladders.renderTask(host, task, status);
      const prose = inspect();
      task.definition = 'obj Run = <key: Int, count: Int> where lt(0, count) sealed (make, key, count) L5';
      status.entries.task = true;
      ladders.renderTask(host, task, status);
      console.log(JSON.stringify({prose, source:inspect()}));
    """
    result = subprocess.run([NODE, "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    result = json.loads(result.stdout)
    prose, source = result["prose"], result["source"]
    # Notation v3: ladder design text is not a published v3 source formula.
    assert ["p", "Design text (not notation v3 source)", "ladder-caption"] in prose
    assert ["p", "PROMPT / TEXT", "ladder-caption"] in prose
    assert not any(tag == "code" and text == "obj Fraction = design idea" for tag, text, _ in prose)
    assert ["p", "DEFINITION / ASCII SOURCE", "ladder-caption"] in source
    assert any(tag == "code" and text.startswith("obj Run =") for tag, text, _ in source)
