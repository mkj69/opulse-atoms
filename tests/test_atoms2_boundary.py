"""Boundary cuts preserve the layer-0 charge under every visible configuration."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "docs" / "assets" / "js" / "atoms2"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_dynamic_boundary_is_its_own_responsive_container() -> None:
    css = (JS.parents[1] / "css" / "atoms2-boundary.css").read_text(encoding="utf-8")
    assert ".a2-boundary { container-type: inline-size;" in css
    assert ".a2-boundary-pinned { grid-column: 1 / -1;" in css
    assert ".a2-boundary-check { grid-column: 1 / -1; grid-row: 3;" in css


def test_given_boundary_atoms_show_origin_not_definition_layer() -> None:
    source = (JS / "boundary.js").read_text(encoding="utf-8")
    assert 'text: band.layer === 0 ? "Given" : "L" + band.layer' in source
    assert 'text: row.given ? "given" : row.charged === 0 ? "invented / 0 steps" : row.opened' in source
    assert 'def.name + ", given atom"' in source
    assert 'row.def + ", given atom"' in source
    assert 'mock.find(row.def, mock.derivations[current].world), { given: row.given }' in source


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_kernel_boundary_cut_does_not_require_mock_fixture() -> None:
    script = r'''
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
require(process.argv[1] + '/data.js');
require(process.argv[1] + '/boundary.js');
const root = A2.kernelData.derivations.mul_3_4.root;
const rows = A2.boundary.cut(root, {depth:1});
console.log(JSON.stringify({mock:!!A2.mock, root:rows[0].def,
  total:rows.filter(row=>row.given || row.folded).reduce((sum,row)=>sum+row.charged,0),
  expected:A2.kernelData.runs.mul_3_4.steps}));
'''
    result = subprocess.run([NODE, "-e", script, str(JS)], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {"mock": False, "root": "mul", "total": 13, "expected": 13}


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_browser_boundary_charges_literal_variable_and_call_bodies_on_both_sides_of_scope() -> None:
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
const base = process.argv[1];
for (const name of ['kit', 'lab-preview-world', 'boundary', 'define']) require(base + '/' + name + '.js');
const {parse, evaluate} = A2.define;
for (const [name, body, expected] of [
  ['constant', '8', 0], ['identity', 'a', 0], ['increment', 'add(a, 1)', 1]
]) {
  const source = 'op ' + name + '(a) = ' + body + ' L1';
  const promoted = {world: 'integer', name, kind: 'operation', origin: 'invented', layer: 1,
    status: 'promoted', spec: {inputs: [{sort: 'int'}], params: ['a'], output: {sort: 'int'}},
    body: parse(source, 'operation').body,
    evidence: {scope: {predicate: {type: 'cases', cases: [[0]]}}}};
  const outer = parse('op outside(a) = ' + name + '(a) L2', 'operation');
  for (const input of [0, 1]) {
    const outcome = evaluate(outer, 'operation', 'integer', [input], [promoted], {layer: 2});
    assert(outcome.outcome.ok, name + ' ' + input);
    const inner = outcome.tree.children[0];
    assert.equal(inner.outsideCheckedScope, input === 1, name);
    assert.equal(inner.emptyBody, expected === 0, name);
    assert.equal(inner.given, false, name);
    assert.equal(outcome.steps, expected, name);
    assert.equal(A2.chargedLeaves(inner), expected, name);
    assert.equal(A2.chargedLeaves(outcome.tree), outcome.steps, name);
    assert.equal(A2.boundary.definitions(outcome.tree).find(def => def.name === name).given, false, name);
    for (const row of A2.boundary.cut(inner, {depth: 1})) {
      if (row.def === name) {
        assert.equal(row.given, false, name);
        assert.equal(row.charged, expected, name);
      }
    }
    for (const boundary of [
      {depth: 3}, {depth: 2}, {depth: 1},
      {depth: 3, open_paths: [[], [0]]},
      {depth: 3, open_names: [name]},
      {depth: 1, keep_names: [name]}
    ]) {
      const rows = A2.boundary.cut(outcome.tree, boundary);
      assert.equal(rows.filter(row => row.folded || row.given).reduce((sum, row) => sum + row.charged, 0), outcome.steps, name + ' ' + input + ' ' + JSON.stringify(boundary));
      for (const row of rows.filter(row => row.def === name)) {
        assert.equal(row.given, false, name);
        assert.equal(row.charged, expected, name);
      }
      assert.equal(rows.filter(row => row.given && row.def === name).length, 0, name);
    }
  }
}
'''
    subprocess.run([NODE, "-e", script, str(JS)], text=True, capture_output=True, check=True)

SCRIPT = r"""
const assert = require('node:assert/strict');
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
const mock = require(process.argv[1] + '/../../../../tests/fixtures/atoms2-mock.js');
require(process.argv[1] + '/boundary.js');
const {cut, definitions, tour, graphLayout} = A2.boundary;
const allKinds = A2.ALL_KINDS;
let checked = 0;
function visit(node, out) { out.push(node); (node.children || []).forEach(child => visit(child, out)); return out; }
for (const [key, sample] of Object.entries(mock.derivations)) {
  const nodes = visit(sample.root, []);
  const maxDepth = Math.max(...nodes.map(node => node.layer)) + 1;
  assert.equal(definitions(sample.root).length, new Set(nodes.map(node => node.def)).size);
  const states = tour(sample.root);
  assert.equal(states.length, 3, key);
  assert(states.every(state => state.caption && state.boundary.depth >= 1), key);
  assert.deepEqual(states[1].boundary.open_paths, [[]], key);
  assert.equal(cut(sample.root, states[1].boundary)[0].opened, true, key);
  assert(cut(sample.root, states[1].boundary).slice(1).every(row => !row.opened), key);
  const graph = graphLayout(definitions(sample.root), sample.root);
  assert.equal(Object.keys(graph.positions).length, definitions(sample.root).length, key);
  assert.equal(graph.bands[graph.bands.length - 1].layer, 0, key);
  assert(graph.links.every(link => graph.positions[link.from] && graph.positions[link.to]), key);
  assert.equal(cut(sample.root, states[0].boundary).length, 1, key);
  assert.equal(cut(sample.root, states[states.length - 1].boundary)[0].result, sample.root.result, key);
  for (let depth = 1; depth <= maxDepth; depth++) {
    for (let mask = 0; mask < (1 << allKinds.length); mask++) {
      const kinds = allKinds.filter((kind, index) => mask & (1 << index));
      for (const variation of [
        {}, {open_paths: [[], [2], [7], [0, 1]]},
        {open_names: ['mul', 'three', 'front_free', 'twice']},
        {keep_names: ['mul', 'three', 'front_free', 'twice'], open_paths: [[], [2]]}
      ]) {
        const boundary = A2.boundary({...variation, depth, kinds});
        const rows = cut(sample.root, boundary);
        assert.equal(rows[0].result, sample.root.result, key);
        assert.equal(rows[0].parentId, null, key);
        assert.deepEqual(rows[0].path, [], key);
        assert.equal(rows.filter(row => row.folded || row.given).reduce((sum, row) => sum + row.charged, 0), mock.charged(sample.root), key);
        assert.equal(rows.filter(row => row.given).every(row => !row.opened && !row.folded), true, key);
        assert.equal(rows.filter(row => row.opened).every(row => !row.given && !row.folded), true, key);
        for (const row of rows.slice(1)) {
          const parent = rows.find(candidate => candidate.id === row.parentId);
          assert(parent && parent.opened && row.depth === parent.depth + 1, key);
        }
        checked++;
      }
    }
  }
}
const dot = mock.derivations.dot.root;
let rows = cut(dot, A2.boundary({depth: 3, open_paths: [[]], keep_names: ['mul']}));
assert.equal(rows[0].opened, true);
assert.equal(rows.filter(row => row.def === 'mul').length, 2);
assert(rows.filter(row => row.def === 'mul').every(row => row.folded));
const mul = mock.derivations.mul_3_4.root;
rows = cut(mul, A2.boundary({depth: 9, open_paths: [[], [2]]}));
assert(rows[0].opened && rows.some(row => A2.pathKey(row.path) === '2' && row.opened));
assert(rows.some(row => A2.pathKey(row.path) === '2.2' && row.folded));
rows = cut(mul, A2.boundary({depth: 1, kinds: []}));
assert.equal(rows.length, 1);
rows = cut(mul, A2.boundary({depth: 1, kinds: [], open_paths: [[]]}));
assert.equal(rows.length, 1);
rows = cut(mul, A2.boundary({depth: 1, kinds: ['operation'], keep_names: ['mul'], open_paths: [[]], open_names: ['mul']}));
assert.equal(rows.length, 1);
assert.deepEqual(cut(null, A2.boundary({depth: 1})), []);
assert.equal(A2.boundary.format(A2.boundary({depth: 3}), 3), 'Boundary()');
assert.equal(A2.boundary.format(A2.boundary({depth: 1, keep_names: ['mul']}), 3), 'Boundary(depth=1, keep_names={mul})');
const twice = mock.derivations.twice_triple.root;
assert(cut(twice, tour(twice)[1].boundary).some(row => row.def === 'triple' && row.folded));
assert.equal(cut(mock.derivations.front_free.root, tour(mock.derivations.front_free.root)[2].boundary).filter(row => row.given).length, 2);
console.log(checked);
"""


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_boundary_cuts_and_precedence() -> None:
    run = subprocess.run([NODE, "-e", SCRIPT, str(JS)], capture_output=True, text=True, check=True)
    assert int(run.stdout.strip()) >= 300


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_render_mounts_independent_instances_and_destroys() -> None:
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
require(process.argv[1] + '/../../../../tests/fixtures/atoms2-mock.js');
class Node {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attrs = {}; this.style = {setProperty() {}};
    this.listeners = {}; this.className = ''; this.textContent = ''; this.offsetTop = 0;
    this.offsetHeight = 30; this.offsetWidth = 100;
    this.classList = {add: (...names) => { this.className += ' ' + names.join(' '); },
      remove: (...names) => { this.className = this.className.split(' ').filter(item => !names.includes(item)).join(' '); }};
  }
  append(...items) { items.forEach(item => this.appendChild(item)); }
  appendChild(item) { if (item != null) this.children.push(item); return item; }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  hasAttribute(name) { return name in this.attrs; }
  get disabled() { return this.hasAttribute('disabled') || this._disabled === true; }
  set disabled(value) { this._disabled = value; }
  focus() { document.activeElement = this; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  removeEventListener(name, fn) { this.listeners[name] = (this.listeners[name] || []).filter(item => item !== fn); }
  click() { (this.listeners.click || []).forEach(fn => fn()); }
  querySelectorAll(selector) {
    const all = this.children.flatMap(child => child instanceof Node ? [child, ...child.querySelectorAll('*')] : []);
    if (selector === '*') return all;
    if (selector === '[data-flip]') return all.filter(node => node.hasAttribute('data-flip'));
    if (selector === '[data-boundary-control]') return all.filter(node => node.hasAttribute('data-boundary-control'));
    if (selector.startsWith('[data-flip="')) return all.filter(node => node.getAttribute('data-flip') === selector.slice(12, -2));
    if (selector === 'button' || selector === 'input') return all.filter(node => node.tagName === selector);
    return all.filter(node => selector.split(',').some(part => node.className.split(' ').includes(part.trim().slice(1))));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
globalThis.document = {createElementNS: (_, tag) => new Node(tag), querySelectorAll: () => []};
A2.el = (tag, attrs = {}, children) => {
  const node = new Node(tag);
    for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'style') node.style.cssText = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  A2.append(node, children);
  return node;
};
A2.append = (node, items) => {
  if (items == null) return node;
  (Array.isArray(items) ? items : [items]).forEach(item => {
    if (Array.isArray(item)) A2.append(node, item);
    else if (item != null) node.appendChild(item);
  });
  return node;
};
A2.icon = () => new Node('svg');
A2.chip = def => A2.el('span', {text: def.name});
A2.badge = status => A2.el('span', {class: 'a2-badge', text: status});
A2.value = value => A2.el('span', {text: String(value)});
A2.flip = (_node, update) => update();
A2.reducedMotion = () => false;
globalThis.requestAnimationFrame = fn => fn();
require(process.argv[1] + '/boundary.js');
const hosts = [new Node('div'), new Node('div')];
const derivation = {title: 'Custom sample', root: A2.mock.derivations.dot.root, world: 'integer'};
const viewers = hosts.map(host => A2.boundary.render(host, {derivation, compact: true}));
const counters = hosts.map(host => host.querySelector('.a2-boundary-counter'));
assert.equal(counters[0].textContent, 'Step 2 / 3');
assert.equal(counters[1].textContent, 'Step 2 / 3');
assert(hosts[0].querySelector('.a2-boundary-caption').textContent.includes('immediate steps'));
assert(hosts[0].querySelectorAll('.a2-boundary-row').length > 1);
assert.equal(hosts[0].querySelector('.a2-boundary-list').getAttribute('role'), 'group');
assert(hosts[0].querySelectorAll('.a2-boundary-row').some(node => node.tagName === 'div'));
assert(hosts[0].querySelectorAll('.a2-boundary-row').filter(node => node.tagName === 'div').every(node => !node.hasAttribute('type')));
const kindControl = hosts[0].querySelector('.a2-boundary-kind');
kindControl.focus(); kindControl.click();
assert.equal(document.activeElement.getAttribute('data-boundary-control'), kindControl.getAttribute('data-boundary-control'));
const graphControl = hosts[0].querySelectorAll('.a2-boundary-node').find(node => !node.disabled);
graphControl.focus(); graphControl.click();
assert.equal(document.activeElement.getAttribute('data-boundary-control'), graphControl.getAttribute('data-boundary-control'));
const rowControl = hosts[0].querySelectorAll('.a2-boundary-row').find(node => node.tagName === 'button' && !node.disabled);
rowControl.focus(); rowControl.click();
assert(document.activeElement === hosts[0].querySelector('.a2-boundary-list') || document.activeElement.getAttribute('data-boundary-control') === rowControl.getAttribute('data-boundary-control'));
assert.equal(hosts[0].querySelector('.a2-boundary-transport').querySelectorAll('button')[2].textContent, 'Restart tour');
hosts[0].querySelector('.a2-boundary-transport').querySelectorAll('button')[2].click();
assert.equal(counters[0].textContent, 'Step 1 / 3');
hosts[0].querySelector('.a2-boundary-transport').querySelectorAll('button')[2].click();
assert.equal(counters[0].textContent, 'Step 2 / 3');
hosts[0].querySelector('.a2-boundary-transport').querySelectorAll('button')[2].click();
assert.equal(counters[0].textContent, 'Step 3 / 3');
assert.equal(counters[1].textContent, 'Step 2 / 3');
viewers[0].destroy(); viewers[0].destroy();
assert.equal(hosts[0].children.length, 0);
assert.equal((hosts[0].listeners.keydown || []).length, 0);
assert(hosts[1].children.length > 0);
viewers[1].destroy();
const protectedRoot = JSON.parse(JSON.stringify(derivation.root));
protectedRoot.containsOutsideCheckedScope = true;
const protectedHost = new Node('div');
const protectedViewer = A2.boundary.render(protectedHost, {derivation: {title: 'Out of scope', world: 'integer', root: protectedRoot}});
assert(protectedHost.querySelector('.a2-boundary-caption').textContent.includes('must remain unfolded'));
assert(protectedHost.querySelectorAll('.a2-boundary-node').find(node => node.getAttribute('data-boundary-control') === 'node:' + protectedRoot.def).disabled);
assert(protectedHost.querySelectorAll('.a2-boundary-kind').find(node => node.getAttribute('data-boundary-control') === 'kind:' + protectedRoot.kind).disabled);
assert(protectedHost.querySelectorAll('.a2-boundary-row').find(node => node.getAttribute('data-boundary-control') === 'row:' + protectedRoot.id).disabled);
protectedViewer.destroy();
const fullHost = new Node('div');
const fullViewer = A2.boundary.render(fullHost, {derivation, compact: false});
assert(!fullHost.className.includes('a2-boundary-compact'));
assert(!fullHost.className.includes('a2-boundary-embedded'));
assert(fullHost.querySelector('.a2-boundary-graph-panel'));
fullViewer.destroy();
A2.reducedMotion = () => true;
const reducedHost = new Node('div');
const reducedViewer = A2.boundary.render(reducedHost, {derivation, compact: true});
const reducedCounter = reducedHost.querySelector('.a2-boundary-counter');
assert.equal(reducedCounter.textContent, 'Step 2 / 3');
assert(reducedHost.querySelectorAll('input').some(node => (node.listeners.input || []).length === 1));
const transport = reducedHost.querySelector('.a2-boundary-transport').querySelectorAll('button');
transport[2].click();
assert.equal(reducedCounter.textContent, 'Step 3 / 3');
transport[1].click();
assert.equal(reducedCounter.textContent, 'Step 2 / 3');
transport[1].click();
reducedHost.querySelectorAll('button').find(button => button.textContent === 'Reset').click();
assert.equal(reducedCounter.textContent, 'Step 2 / 3');
reducedViewer.destroy();
const longHost = new Node('div');
const longViewer = A2.boundary.render(longHost, {derivation: A2.kernelData.modes.derivations.fixpoint, compact: true});
const wrapped = longHost.querySelector('.a2-boundary-wrapped-value');
assert(wrapped);
assert(longHost.querySelectorAll('.a2-badge').every(badge => badge.textContent === 'executable'));
assert.equal(wrapped.children.map(part => part.textContent).join(''), A2.formatValue(A2.kernelData.modes.derivations.fixpoint.root.result));
assert(wrapped.children.filter(part => part.tagName === 'wbr').length >= 10);
assert.equal(longHost.querySelector('.a2-boundary-counter').textContent, 'Step 2 / 3');
longViewer.destroy();
const browserHost = new Node('div');
const browserViewer = A2.boundary.render(browserHost, {derivation: {title:'Browser preview', root:{...A2.kernelData.modes.derivations.memo.root}}, compact:true});
assert(browserHost.querySelectorAll('.a2-badge').every(badge => badge.textContent === 'design'));
browserViewer.destroy();
require(process.argv[1] + '/lab-preview-world.js');
require(process.argv[1] + '/define.js');
for (const [name, body, cost] of [['constant', '8', 0], ['identity', 'a', 0], ['increment', 'add(a, 1)', 1]]) {
  const promoted = {world: 'integer', name, kind: 'operation', origin: 'invented', layer: 1,
    status: 'promoted', spec: {inputs: [{sort: 'int'}], params: ['a'], output: {sort: 'int'}},
    body: A2.define.parse('op ' + name + '(a) = ' + body + ' L1', 'operation').body,
    evidence: {scope: {predicate: {type: 'cases', cases: [[0]]}}}};
  const outer = A2.define.parse('op outside(a) = ' + name + '(a) L2', 'operation');
  for (const input of [0, 1]) {
    const outcome = A2.define.evaluate(outer, 'operation', 'integer', [input], [promoted], {layer: 2});
    const host = new Node('div');
    const viewer = A2.boundary.render(host, {derivation: {title: 'Browser preview', world: 'integer', root: outcome.tree}, compact: true});
    if (input === 1) {
      const outOfScope = outcome.tree.children[0];
      assert(outOfScope.outsideCheckedScope);
      assert(A2.boundary.cut(outOfScope, {depth: 1, kinds: [], keep_names: [name]})[0].opened);
      assert(host.querySelectorAll('.a2-boundary-node').find(node => node.getAttribute('data-boundary-control') === 'node:' + name).disabled);
      assert(host.querySelectorAll('.a2-boundary-kind').find(node => node.getAttribute('data-boundary-control') === 'kind:operation').disabled);
      assert(host.querySelectorAll('.a2-boundary-row').find(node => node.getAttribute('data-boundary-control') === 'row:' + outOfScope.id).disabled);
    }
    const metrics = host.querySelectorAll('.a2-boundary-metric');
    assert.equal(metrics[1].children[1].textContent, cost, name + ' ' + input);
    const rows = host.querySelectorAll('.a2-boundary-row');
    assert(rows.filter(row => row.getAttribute('aria-label').includes(name)).every(row => !row.getAttribute('aria-label').includes('given atom')), name);
    host.querySelector('.a2-boundary-transport').querySelectorAll('button')[2].click();
    assert.equal(metrics[1].children[1].textContent, cost, name + ' ' + input);
    assert.equal(metrics[2].children[1].textContent, cost, name + ' ' + input);
    if (cost === 0) assert(host.querySelectorAll('.a2-boundary-row-status').some(row => row.textContent === 'invented / 0 steps'), name);
    viewer.destroy();
    if (cost === 0) {
      const emptyHost = new Node('div');
      const emptyViewer = A2.boundary.render(emptyHost, {derivation: {title: name, world: 'integer', root: outcome.tree.children[0]}, compact: true});
      assert.equal(emptyHost.querySelectorAll('.a2-boundary-metric')[1].children[1].textContent, 0, name);
      assert.equal(emptyHost.querySelectorAll('.a2-boundary-metric')[2].children[1].textContent, 0, name);
      assert.equal(emptyHost.querySelector('.a2-boundary-row-status').textContent, 'invented / 0 steps', name);
      assert(!emptyHost.querySelector('.a2-boundary-row').getAttribute('aria-label').includes('given atom'), name);
      emptyViewer.destroy();
    }
  }
}
'''
    subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)
