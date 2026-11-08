"""Behavioral regressions for the rv7 browser review."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_node(script: str) -> None:
    result = subprocess.run([NODE, "-e", script, str(ROOT)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_learn_kind_buttons_copy_exact_visible_text() -> None:
    run_node(r"""
const assert = require('node:assert/strict');
const root = process.argv[1];
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.className = ''; this.attrs = {}; }
  appendChild(item) { this.children.push(item); return item; }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(event, handler) { this.listeners[event] = handler; }
  get textContent() { return this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.children = [{textContent: String(value)}]; }
  click() { this.listeners.click(); }
}
globalThis.document = {readyState: 'loading', addEventListener() {}, querySelectorAll: () => [],
  createElement: tag => new Element(tag), createTextNode: text => ({textContent: text})};
const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
require(root + '/docs/assets/js/atoms2/learn-kinds.js');
const data = require(root + '/docs/assets/data/atoms2/grammar.json');
const writes = [];
Object.defineProperty(globalThis, 'navigator', {configurable: true,
  value: {clipboard: {writeText(value) { writes.push(value); return Promise.resolve(); }}}});
const host = new Element('div');
A2.learnKinds.mount(host, data, null);
function descendants(node) { return [node, ...(node.children || []).filter(Boolean).flatMap(descendants)]; }
const cards = descendants(host).filter(node => node.tag === 'article' && node.className === 'a2-learn-card' && node.attrs.id);
assert.equal(cards.length, data.cards.length);
for (const [index, card] of cards.entries()) {
  const button = descendants(card).find(node => node.tag === 'button' && node.className.includes('a2-tok'));
  assert(button, data.cards[index].kind);
  button.click();
  // Notation v3: the chip also shows a separate layer badge; the copied text is the chip text
  // without that badge.
  const visible = button.children.filter(child => !String(child.className || '').includes('a2-layer-badge'))
    .map(child => child.textContent).join('');
  assert.equal(writes.at(-1), visible, data.cards[index].kind);
  assert.equal(visible, data.cards[index].name, data.cards[index].kind);
  if (data.cards[index].kind === 'observation') {
    assert(visible.includes('{Word<'));
    assert(button.className.includes('a2-learn-observation'));
  }
}
assert.equal(writes.length, data.cards.length);
""")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_boundary_cut_opens_protected_parent_and_child_without_workshop() -> None:
    run_node(r"""
const assert = require('node:assert/strict');
const base = process.argv[1] + '/docs/assets/js/atoms2/';
const A2 = require(base + 'kit.js');
require(base + 'boundary.js');
const child = {id:'child', path:[0], def:'inside', kind:'operation', layer:1,
  containsOutsideCheckedScope:true, children:[
    {id:'leaf', path:[0,0], def:'succ', kind:'operation', layer:0, given:true, children:[]}]};
const root = {id:'root', path:[], def:'outside', kind:'operation', layer:1,
  containsOutsideCheckedScope:true, children:[child]};
for (const boundary of [{depth:3}, {depth:1, open_paths:[[]]}]) {
  const rows = A2.boundary.cut(root, boundary);
  assert.deepEqual(rows.map(row => [row.id, row.folded, row.opened, row.outsideScope]), [
    ['root', false, true, true], ['child', false, true, true], ['leaf', false, false, false]]);
}
assert.equal(A2.isOpened(root, A2.boundary({depth:3})), false);
root.containsOutsideCheckedScope = false;
assert.deepEqual(A2.boundary.cut(root, {depth:3}).map(row => row.id), ['root']);
assert.equal(A2.boundary.cut(root, {depth:3})[0].folded, true);
assert.deepEqual(A2.boundary.cut(root, {depth:1}).map(row => row.id), ['root','child','leaf']);
""")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_roads_design_tower_renders_unparseable_declaration_as_prose() -> None:
    # Notation v3: the design remains prose, labeled as not v3 source.
    run_node(r"""
const assert = require('node:assert/strict');
const root = process.argv[1];
const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
function el(tag, attrs = {}, children = []) {
  return {tag, attrs, children: Array.isArray(children) ? children : [children],
    appendChild(item) {this.children.push(item);}, append(...items) {this.children.push(...items);},
    replaceChildren(...items) {this.children = items;},
    setAttribute(key, value) {this.attrs[key] = value;},
    addEventListener(event, handler) {this.listeners = this.listeners || {}; this.listeners[event] = handler;},
    querySelectorAll(selector) {return selector === 'button' ? this.children.filter(item => item.tag === 'button') : [];}};
}
A2.el = el;
A2.token = text => el('token', {text});
A2.expr = text => el('code', {text});
A2.badge = () => el('badge');
const catalog = require(root + '/docs/assets/js/worlds/catalog-ui.js');
const row = require(root + '/docs/worlds/designs.json').worlds.roads.tower[0];
const status = require(root + '/docs/assets/data/atoms2/parse_status.json');
assert.equal(status.entries['design/roads/' + row.name], false);
const host = el('div');
catalog.designTower(host, [row], 'roads', '../../worlds/designs.json', status);
function descendants(node) { return [node, ...(node.children || []).filter(Boolean).flatMap(descendants)]; }
const nodes = descendants(host);
assert(nodes.some(node => node.tag === 'p' && node.attrs.text === 'Design text (not notation v3 source)'));
assert(nodes.some(node => node.tag === 'p' && node.attrs.class === 'w2-design-text' && node.attrs.text === row.decl));
assert(!nodes.some(node => node.tag === 'code' && node.attrs.text === row.decl));
""")
