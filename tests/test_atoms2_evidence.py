"""Evidence records stay scoped, and their badge remains keyboard-operable."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_js(script: str) -> None:
    result = subprocess.run([NODE, "-e", script, str(ROOT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_core_evidence_and_world_story_keep_only_recorded_fields() -> None:
    run_js(r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = process.argv[1];
const A2 = require(path.join(root, 'docs/assets/js/atoms2/kit.js'));
const core = A2.evidenceRecord({method: 'sampled', scope: {domain: 'eight states', size: 8},
  seed: 0, checks: ['reference'], content_hash: 'abc'});
assert.equal(core.method, 'sampled');
assert.equal(core.seed, 0);
assert.equal(core.domain, 'eight states');
assert.equal(core.size, 8);
assert.deepEqual(core.checks, ['reference']);
assert.equal(core.artifact.contentHash, 'abc');
assert.equal(core.answerShape, null);
assert.equal(core.layer0Cost, null);
assert.equal(core.bottom, null);
assert.equal(core.unknown, null);
assert.equal(A2.evidenceRecord({layer0_cost: {exact: 12}}).layer0Cost, 12);
assert.equal(A2.evidenceRecord({layer0_cost: 'estimated 12'}).layer0Cost, null);
const world = JSON.parse(fs.readFileSync(path.join(root, 'docs/assets/data/worlds_v2/roads.json')));
const entry = world.story.find(row => row.name === 'optimal');
const story = A2.evidenceRecord(entry);
assert.equal(entry.evidence.method, 'bounded');
assert.equal(story.method, 'bounded');
assert.equal(story.domainTotal, null);
assert.equal(story.topology, null);
assert.equal(story.size, entry.evidence.scope.size);
assert.equal(story.artifact.worldHash, entry.evidence.world_hash);
assert.equal(story.artifact.depsHash, entry.evidence.deps_hash);
assert.equal(story.artifact.file, null);
assert.equal(story.layer0Cost, null, 'aggregate cost is not an exact run cost');
assert.equal(story.fullStateResult, null);
assert.equal(story.artifact.version, null, 'story has no version unless explicitly supplied');
""")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_design_fixtures_do_not_become_verified_records() -> None:
    run_js(r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = process.argv[1];
const A2 = require(path.join(root, 'docs/assets/js/atoms2/kit.js'));
for (const name of ['roads', 'computer', 'grammar', 'checks']) {
  const fixture = JSON.parse(fs.readFileSync(path.join(root, 'docs/assets/data/atoms2', name + '.json')));
  const info = A2.evidenceRecord(fixture);
  assert.equal(info.method, null, name + ' has no check method');
  assert.equal(info.domain, null);
  assert.equal(info.size, null);
  assert.equal(info.artifact.file, null);
  assert.equal(info.layer0Cost, null);
  assert.equal(info.fullStateResult, null);
  assert.equal(info.taskResult, null);
  assert.equal(info.artifact.version, fixture.version ?? null);
}
const item = JSON.parse(fs.readFileSync(path.join(root, 'docs/assets/data/atoms2/checks.json'))).evidence[2];
const illustration = A2.evidenceRecord(item);
assert.equal(illustration.method, 'sampled');
assert.equal(illustration.description, item.scope);
assert.equal(illustration.seed, null, 'description cannot supply a seed');
""")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_drawer_opens_closes_and_returns_focus() -> None:
    run_js(r"""
const assert = require('node:assert/strict');
const path = require('node:path');
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.className = ''; }
  appendChild(child) { this.children.push(child); child.parent = this; return child; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(key, fn) { (this.listeners[key] ||= []).push(fn); }
  dispatch(key, event = {}) { for (const fn of this.listeners[key] || []) fn(event); }
  focus() { document.activeElement = this; }
  remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
  showModal() { this.open = true; }
  close() { this.open = false; }
  set textContent(text) { this.children = [new Node('text')]; this.children[0].value = text; }
  get textContent() { return this.value || this.children.map(child => child.textContent).join(''); }
}
globalThis.document = {body: new Node('body'), readyState: 'loading',
  createElement: tag => new Node(tag), createTextNode: text => { const node = new Node('text'); node.value = text; return node; },
  addEventListener() {}, querySelectorAll() { return []; }};
const A2 = require(path.join(process.argv[1], 'docs/assets/js/atoms2/kit.js'));
const trigger = A2.badge('design', {record: {method: 'bounded', scope: {domain: 'A', size: 0}}});
assert.equal(trigger.tag, 'button');
assert.match(trigger.attrs['aria-label'], /View verification scope/);
trigger.focus();
trigger.dispatch('click');
let dialog = document.body.children[0];
assert.equal(dialog.tag, 'dialog');
assert.equal(dialog.open, true);
assert.equal(document.activeElement.textContent, 'Close evidence details');
assert.match(dialog.textContent, /Scope size0/);
assert.match(dialog.textContent, /Seednot recorded/);
assert.match(dialog.textContent, /Layer-0 costnot run/);
assert.match(dialog.textContent, /Design only. No verification run is claimed/);
let tabPrevented = false;
dialog.dispatch('keydown', {key: 'Tab', preventDefault() { tabPrevented = true; }});
assert.equal(tabPrevented, true);
assert.equal(document.activeElement.textContent, 'Close evidence details');
let prevented = false;
dialog.dispatch('keydown', {key: 'Escape', preventDefault() { prevented = true; }});
assert.equal(prevented, true);
assert.equal(document.body.children.length, 0);
assert.equal(document.activeElement, trigger);
trigger.dispatch('click');
dialog = document.body.children[0];
dialog.dispatch('cancel', {preventDefault() { prevented = true; }});
assert.equal(document.body.children.length, 0);
assert.equal(document.activeElement, trigger);
trigger.dispatch('click');
dialog = document.body.children[0];
dialog.children.find(child => child.tag === 'button').dispatch('click');
assert.equal(document.body.children.length, 0);
assert.equal(document.activeElement, trigger);
const linked = A2.badge('bounded', {record: {artifact: {file: 'docs/assets/data/atoms2/checks.json',
  href: '../../assets/data/atoms2/checks.json'}}});
linked.dispatch('click');
dialog = document.body.children[0];
const link = dialog.children.find(child => child.tag === 'a');
assert.equal(link.attrs.href, '../../assets/data/atoms2/checks.json');
dialog.dispatch('keydown', {key: 'Tab', shiftKey: true, preventDefault() {}});
assert.equal(document.activeElement, link);
dialog.dispatch('keydown', {key: 'Tab', shiftKey: false, preventDefault() {}});
assert.equal(document.activeElement.textContent, 'Close evidence details');
dialog.children.find(child => child.tag === 'button').dispatch('click');
assert.equal(document.activeElement, linked);
""")
