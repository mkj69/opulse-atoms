"""The grammar lesson's claims are tied to a reproducible kernel export."""

import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from opulse.atoms import kernel
from opulse.atoms.notation import parse_definition, print_definition
from opulse.atoms.spec import Cost
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.worlds_v2.grammar import hosts, story
from tools import atoms2_grammar_export as exporter

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
ARTIFACT = ROOT / "docs/assets/data/atoms2/grammar_core.json"


def test_grammar_export_matches_rebuilt_kernel():
    from opulse.notation3.export import add_notation3

    stored = json.loads(ARTIFACT.read_text())
    assert stored == add_notation3(exporter.export(), 'atoms2', source='atoms2/grammar_core.json')
    payload = {key: value for key, value in stored.items() if key not in ('digest', 'notation3')}
    assert stored["digest"] == hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
    assert stored["inputs_sha256"] == exporter.input_digest()


def test_grammar_examples_recompute_and_preserve_layers():
    rows = json.loads(ARTIFACT.read_text())["rows"]
    library = story.build_library()
    word = story.word_from((2, "+", 2, "*", 2, "+", 2, "*", 2, "+", 2, "*", 2, "+", 2))
    slots = tuple(kernel.FnRef(name) for name in
                  ("one", "multiply", "identity", "combine_count", "zero"))
    inputs = {"object": ("ExprTree.make", (hosts.to_card(("num", 7)),)),
              "operation": ("split", (word,)), "combinator": ("chart", (*slots, word)),
              "observation": ("parse_count", (word,))}
    for kind, (call, args) in inputs.items():
        row = rows[kind]
        run = library.run(call, args)
        assert row["example"]["outcome"] == exporter.outcome_text(run.outcome)
        assert row["example"]["layer0_steps"] == run.steps
        definition = library.get(row["name"])
        assert row["layer"] == definition.layer
        assert row["depends_on"] == list(definition.depends_on)
        prerequisites = [library.get(name).layer for name in definition.depends_on
                         if name in library.definitions]
        assert row["layer"] == 1 + max(prerequisites, default=0)
        assert row["status"] == definition.evidence.method == "bounded"
        assert row["content_hash"] == library.content_hash(row["name"])
        if row["declaration"]["text"]:
            bare = replace(definition, status="written", evidence=None, contract=None,
                           cost=Cost(), id=None)
            if bare.kind == "observation":
                bare = replace(bare, spec=replace(
                    bare.spec, extra={**bare.spec.extra, "subject": "w"}))
            assert row["declaration"]["text"] == print_definition(bare, library)
            assert row["declaration"]["label"] == "Printed from the core definition (re-parses: yes)"
            assert parse_definition(row["declaration"]["text"], library).name == row["name"]
        else:
            assert row["declaration"]["label"].startswith("Design summary (printer unavailable: ")
            assert row["declaration"]["reason"]
    assert {kind for kind, row in rows.items() if row["declaration"]["text"]} == {"combinator", "observation"}
    assert isinstance(library.run("parse_count", (word,)).outcome, Ok)
    assert library.run("parse_count", (word,)).outcome.value == 429
    invalid = library.run("ExprTree.make", (hosts.HOLE,))
    assert isinstance(invalid.outcome, Bottom)
    assert rows["object"]["failure"]["outcome"] == exporter.outcome_text(invalid.outcome)
    assert rows["object"]["failure"]["layer0_steps"] == invalid.steps


def test_export_helpers_and_stale_copy():
    assert exporter.outcome_text(Ok(429)) == "Ok(429)"
    assert exporter.outcome_text(Bottom("invalid")) == "Bottom(invalid)"
    assert exporter.outcome_text(Unknown("fuel")) == "Unknown(fuel)"
    assert exporter.compact_trace(None) == []
    leaf = SimpleNamespace(name="split", layer=1, steps=3, outcome=Ok(7), children=[])
    parent = SimpleNamespace(name=None, layer=0, steps=3, outcome=Ok(7), children=[leaf])
    assert exporter.compact_trace(parent, limit=1) == [
        {"call": "root", "depth": 0, "layer": 0, "steps": 3, "outcome": "Ok(7)"}]
    assert exporter.compact_trace(parent)[1] == {
        "call": "split", "depth": 1, "layer": 1, "steps": 3, "outcome": "Ok(7)"}
    page = (ROOT / "docs/learn/kinds.md").read_text()
    script = (ROOT / "docs/assets/js/atoms2/learn-kinds.js").read_text()
    assert "grammar_core.json" in page
    assert "read_parse_count" not in page + script
    assert "neither path has a checked grammar-world export" not in page + script
    assert "not a run of the designed declarations" not in page + script
    assert "separate calculation, not a second core certificate" in script


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_grammar_cards_render_core_and_keep_unchecked_kinds_as_designs():
    script = r"""
const assert = require('node:assert/strict');
const root = process.argv[1];
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.className = ''; }
  appendChild(item) { this.children.push(item); return item; }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(event, handler) { this.listeners[event] = handler; }
  get textContent() { return this.children.filter(Boolean).map(child => child.textContent).join(''); }
  set textContent(text) { this.children = [{textContent: String(text)}]; }
}
globalThis.document = {readyState:'loading', addEventListener(){}, querySelectorAll(){return []},
  createElement: tag => new Element(tag), createTextNode: text => ({textContent: text})};
const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
require(root + '/docs/assets/js/atoms2/learn-kinds.js');
const design = require(root + '/docs/assets/data/atoms2/grammar.json');
const core = require(root + '/docs/assets/data/atoms2/grammar_core.json');
const host = new Element('div');
host.dataset = {core:'../../assets/data/atoms2/grammar_core.json'};
A2.learnKinds.mount(host, design, null, core);
function all(node) { return [node, ...(node.children || []).filter(Boolean).flatMap(all)]; }
const nodes = all(host);
assert(host.children.findIndex(item => item.className === 'a2-learn-grid') <
       host.children.findIndex(item => item.className === 'a2-learn-detail-tree'));
for (const kind of ['object','operation','combinator','observation']) {
  const card = nodes.find(item => item.tag === 'article' && item.attrs.id === 'kind-' + kind);
  assert(card, kind);
  const children = all(card);
  if (A2.hasRecordedScope(core.rows[kind].evidence))
    assert(children.some(item => item.tag === 'button' && item.textContent.startsWith('Bounded')), kind);
  else {
    assert(children.some(item => item.textContent === 'scope not recorded'), kind);
    assert(!children.some(item => item.textContent.startsWith('Bounded')), kind);
  }
  assert(children.some(item => item.tag === 'a' && item.textContent === 'Executable'), kind);
  assert(children.filter(item => item.tag === 'a' && item.textContent === 'Executable')
    .every(item => item.attrs.href === host.dataset.core), kind);
  assert(card.textContent.includes(core.rows[kind].example.outcome), kind);
  assert(card.textContent.includes(String(core.rows[kind].example.layer0_steps)), kind);
}
for (const kind of ['law', 'bridge']) {
  const card = nodes.find(item => item.tag === 'article' && item.attrs.id === 'kind-' + kind);
  assert(all(card).some(item => item.textContent === 'Designed example'), kind);
}
assert(host.textContent.includes('Ok(429)'));
assert(!host.textContent.includes('read_parse_count'));
const unrecorded = structuredClone(core);
for (const kind of ['object', 'operation'])
  unrecorded.rows[kind].evidence.scope.checked = 'unrecorded';
const secondHost = new Element('div');
secondHost.dataset = host.dataset;
A2.learnKinds.mount(secondHost, design, null, unrecorded);
for (const kind of ['object', 'operation']) {
  const card = all(secondHost).find(item => item.tag === 'article' && item.attrs.id === 'kind-' + kind);
  assert(card.textContent.includes('scope not recorded'), kind);
  assert(!all(card).some(item => item.textContent.startsWith('Bounded')), kind);
}
"""
    result = subprocess.run([NODE, "-e", script, str(ROOT)],
                            check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
