"""Page renderers consume the registered notation block, not displayed machine text."""

import shutil
import subprocess
from pathlib import Path

import pytest


NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for page-render tests")


DOM = r"""
const assert = require('node:assert/strict');
global.window = global;
class Element {
  constructor(tag, value = '') {
    this.tagName = tag; this.children = []; this.parentNode = null; this.attrs = {};
    this.dataset = {}; this.classes = new Set(); this._text = value; this.handlers = {};
    this.classList = {contains: name => this.classes.has(name), add: name => this.classes.add(name)};
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get childNodes() { return this.children; }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get className() { return [...this.classes].join(' '); }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach(child => {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) this.append(...child);
    else this.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }); }
  replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
  replaceWith(child) { const siblings = this.parentNode.children; siblings.splice(siblings.indexOf(this), 1, child); child.parentNode = this.parentNode; }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === 'class') this.className = value;
    if (key === 'data-n3-ascii') this.dataset.n3Ascii = String(value); }
  hasAttribute(key) { return key in this.attrs; }
  getAttribute(key) { return this.attrs[key] || null; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  click() { if (this.handlers.click) this.handlers.click(); }
  closest() { return null; }
  querySelectorAll(selector) {
    const matches = []; const visit = node => {
      for (const child of node.children) {
        if (selector === 'code' && child.tagName === 'code' || selector === '.n3' && child.classes.has('n3')) matches.push(child);
        visit(child);
      }
    }; visit(this); return matches;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
global.Node = Element;
global.document = {readyState: 'loading', createElement: tag => new Element(tag),
  createTextNode: value => new Element('#text', String(value)), addEventListener() {},
  currentScript: {src: 'https://example.org/assets/js/atoms2/roads.js'}};
const block = {version: 1, worlds: {integer: {formulas: {
  'mul(2, 4)': {display: '2 ♦₆ 4', ascii: '2 \dia_6 4'},
  'op mul(a: Int, b: Int) -> Int = a + b L1': {display: 'a ♦₆ b = { a + b }', ascii: 'a \dia_6 b = { a + b }'},
  'Ok(8)': {display: '8', ascii: '8'},
  '#identity': {display: '≡₁', ascii: '\eqv_1'}
}, prose: {'Use mul(2, 4).': [['t', 'Use '], ['f', '2 ♦₆ 4', '2 \dia_6 4'], ['t', '.']]}}}};
const entries = new Map();
global.N3 = {
  register(data) { for (const [world, detail] of Object.entries(data.worlds)) {
    const previous = entries.get(world) || {};
    entries.set(world, {...previous, ...detail, formulas:{...previous.formulas, ...detail.formulas},
      prose:{...previous.prose, ...detail.prose}});
  } },
  lookup(text, world) { return world ? entries.get(world)?.formulas[text] || null :
    [...entries.values()].map(detail => detail.formulas[text]).find(Boolean) || null; },
  prose(text, world) { return entries.get(world)?.prose[text] || null; },
  render(display, ascii) { const node = document.createElement('span'); node.className = 'n3';
    node.dataset.n3Ascii = ascii; node.setAttribute('data-n3-ascii', ascii); node.textContent = display; return node; },
  legendPanel() { return document.createElement('aside'); }
};
function el(tag, attrs, children) {
  const node = document.createElement(tag); if (attrs) for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (attrs && attrs.value !== undefined) node.value = attrs.value;
  const add = value => { if (Array.isArray(value)) value.forEach(add);
    else if (value !== undefined && value !== null && value !== false) node.append(value); };
  add(children);
  if (tag === 'select' && node.children[0]) node.value = node.children[0].value;
  return node;
}
global.A2 = {el, expr(text, opts = {}) { const entry = N3.lookup(text, opts.world);
  return entry ? N3.render(entry.display, entry.ascii) : el('span', {class: 'fallback'}, text); },
  token(text, opts) { return this.expr(text, opts); }, hasRecordedScope() { return false; },
  scopedBadge() { return el('span'); }, badge() { return el('span'); },
  kindBadge() { return el('span'); }, runBadge() { return el('span'); }, register() {}};
function check(host) {
  const rendered = host.querySelectorAll('.n3');
  assert(rendered.length > 0, 'expected a display formula');
  for (const node of rendered) {
    assert(node.dataset.n3Ascii, 'copy spelling is required');
    assert(!node.textContent.includes('mul('), 'machine text is not visible');
  }
}
"""


def run_node(source: str) -> None:
    result = subprocess.run([NODE, "-e", DOM + source], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_research_code_only_enhances_registered_notation() -> None:
    run_node(r"""
const research = require('./docs/assets/js/atoms2/research-ui.js');
const host = el('div'); N3.register(block);
const machine = el('code', {}, 'mul(2, 4)');
const plain = el('code', {}, 'python -m pytest');
const display = el('code', {}, '≡₁'); display.className = 'n3'; display.setAttribute('data-n3-ascii', '\eqv_1');
host.append(machine, plain, display);
assert.equal(research.renderInline(host, A2), 1);
assert.equal(host.children[1], plain); assert.equal(host.children[2], display);
check(host); assert.equal(host.children[0].dataset.n3Ascii, '2 \dia_6 4');
""")


def test_learn_evidence_registers_and_renders_export_formulas() -> None:
    run_node(r"""
require('./docs/assets/js/atoms2/learn-evidence.js');
const item = {declaration: 'op mul(a: Int, b: Int) -> Int = a + b L1', before: 'mul(2, 4)',
  after: 'mul(2, 4)', before_outcome: 'unknown', after_outcome: 'unknown', input: 'mul(2, 4)',
  outcome: 'unknown', diagram: 'mul(2, 4)', evidence: {}, layer0_steps: 1, rewrite_steps: 1, charged_steps: 1};
const host = A2.learnEvidence.render({notation3: block, world: 'integer',
  law_and_bridge: {law: item, bridge: item}}, 'export.json');
check(host);
assert(host.textContent.includes('unknown'), 'missing formulas keep their fallback');
assert(!host.textContent.includes('mul(2, 4)'));
""")


def test_roads_expression_passes_world_and_preserves_missing_fallback() -> None:
    run_node(r"""
const roads = require('./docs/assets/js/atoms2/roads.js');
N3.register(block);
const formula = roads.roadExpression('mul(2, 4)', {world: 'integer'});
check(el('div', {}, formula));
assert.equal(roads.roadExpression('not published', {world: 'integer'}).textContent, 'not published');
""")


def test_ladder_task_renders_definition_and_prose_without_changing_answer_parser() -> None:
    run_node(r"""
const ladders = require('./docs/assets/js/atoms2/ladders.js');
N3.register(block);
const host = el('section');
const task = {id:'test', world:'integer', kind:'operation', level:1, purpose:'Check notation',
  definition:'op mul(a: Int, b: Int) -> Int = a + b L1', depends_on:[],
  prompt:'Use mul(2, 4).', answer_format:'definition', angle:'create'};
ladders.renderTask(host, task, {entries: {test: true}}, 'opulse.challenge_v2/3');
check(host);
assert(!host.textContent.includes('mul(2, 4)'));
assert(host.textContent.includes('Type answers in the ASCII storage form'));
assert.equal(ladders.parseAnswer(task, 'op mul(a: Int, b: Int) -> Int = a + b L1', 'opulse.challenge_v2/3'), task.definition);
assert.throws(() => ladders.parseAnswer(task, '♦₆', 'opulse.challenge_v2/3'), /ASCII/);
""")


def test_world_declaration_registers_block_and_renders_tokens() -> None:
    run_node(r"""
global.A2.KINDS6 = ['object','operation','combinator','observation','law','bridge'];
global.A2.token = (text, opts) => A2.expr(text, opts);
require('./docs/assets/js/worlds/declare.js');
const declare = global.OpulseWorldsDeclare;
const host = el('section');
const data = {world:'integer', atoms:[{name:'mul', symbol:'mul', params:[], result_type:'int'}], notation3: block};
data.atoms[0].name = '#identity';
declare.render(host, data, A2);
check(host);
assert(!host.textContent.includes('#identity'));
""")


def test_step_view_renders_registered_before_and_after_with_world() -> None:
    run_node(r"""
require('./docs/assets/js/stepview.js');
const host = el('section');
OpulseStepView.render(host, {world:'integer', notation3:block,
  steps:[{before:'mul(2, 4)', after:'mul(2, 4)', note:'Use mul(2, 4).'}]});
setImmediate(() => {
  check(host);
  assert(!host.textContent.includes('mul(2, 4)'));
  assert(host.querySelectorAll('.n3').length >= 3);
});
""")


def test_reference_modes_registers_kernel_data_before_rendering_formulas() -> None:
    run_node(r"""
const host = el('div'); document.getElementById = () => host;
const run = {core_digest:'deadbeefdeadbeef', expression:'mul(2, 4)', outcome_text:'unknown', steps:3};
A2.kernelData = {notation3:block, modes:{runs:{fixpoint:run, memo:run, turns:run, fold:run},
  derivations:{fixpoint:{}, memo:{}, turns:{}, fold:{}}}};
A2.boundary = {render() {}};
require('./docs/assets/js/atoms2/modes.js');
check(host);
assert.equal(host.querySelectorAll('.n3').length, 4);
assert(host.textContent.includes('unknown'));
""")


def test_spec_tables_enhancer_only_converts_registered_code() -> None:
    run_node(r"""
A2.kernelData = {notation3:block};
const spec = require('./docs/assets/js/atoms2/spec-tables.js');
const host = el('div'); const machine = el('code', {}, 'mul(2, 4)');
const command = el('code', {}, 'python -m pytest');
host.append(machine, command);
spec.enhance(host);
check(host);
assert.equal(host.children[1], command);
""")


def test_learn_kinds_mount_registers_each_loaded_export() -> None:
    run_node(r"""
A2.KIND6_META = Object.fromEntries(['object','operation','combinator','observation','law','bridge'].map(kind => [kind,{word:kind}]));
A2.learnEvidence = {render: () => el('section')};
const data = require('./docs/assets/data/atoms2/grammar.json');
data.notation3 = block; data.expression = 'mul(2, 4)';
require('./docs/assets/js/atoms2/learn-kinds.js');
const host = el('div'); host.dataset = {walk:'walk.json',core:'core.json'};
A2.learnKinds.mount(host, data, null, null);
check(host);
assert(!host.textContent.includes('mul(2, 4)'));
assert(!host.children[0].textContent.includes('ExprTree<'));
assert(!host.children[0].textContent.includes('::'));
""")


def test_first_tower_mount_renders_export_calls_and_results() -> None:
    run_node(r"""
A2.register = (_, mount) => { A2.mountTower = mount; };
A2.formatValue = value => value.v === 8 ? '8' : String(value);
A2.evidenceRecord = () => ({artifact:{}});
require('./docs/assets/js/atoms2/first-tower.js');
const result = {ok:{t:'int',v:8}};
const data = {schema:'opulse.first_tower/1', world:'integer', notation3:block,
  cards:[{name:'mul',kind:'operation',layer:1,display_name:'mul',summary_label:'Printed from core',
    record_summary:'op mul(a: Int, b: Int) -> Int = a + b L1', evidence:{},
    dependencies:[],invented_dependencies:[],example:{call:'mul(2, 4)',outcome:result,steps:1,
      trace:{name:'mul(2, 4)',outcome:result,steps:1}}}]};
global.fetch = async () => ({ok:true,json:async () => data});
const host = el('section'); host.setAttribute('data-src','export.json');
host.parentElement = {querySelector:() => null};
A2.mountTower(host);
setImmediate(() => { check(host); assert(!host.textContent.includes('mul(2, 4)')); });
""")


def test_learn_checks_mount_uses_notation_for_loaded_definition() -> None:
    run_node(r"""
A2.KIND6_META = Object.fromEntries(['object','operation','combinator','observation','law','bridge'].map(kind => [kind,{word:kind}]));
A2.kernelData = {};
A2.learnEvidence = {render:() => el('section')};
const checks = require('./docs/assets/data/atoms2/checks.json');
const walk = require('./docs/assets/data/atoms2/walk.json');
checks.notation3 = block; checks.definition = 'mul(2, 4)';
require('./docs/assets/js/atoms2/learn-checks.js');
const host = el('div'); host.dataset = {walk:'walk.json'};
A2.learnChecks.mount(host, checks, walk);
check(host);
assert(!host.textContent.includes('mul(2, 4)'));
assert(!host.querySelectorAll('.n3').some(node => node.textContent.includes('Broken canon')));
assert(host.textContent.includes('Broken canon add(x, 2)'));
""")


def test_showcase_renders_prose_and_looks_up_only_stored_answers() -> None:
    run_node(r"""
const catalog = require('./docs/assets/js/worlds/catalog-ui.js');
A2.worlds = {ascii:text => text}; A2.value = value => el('span', {}, JSON.stringify(value));
const originalEl = A2.el;
A2.el = (tag, attrs, children) => originalEl(tag, attrs, attrs && attrs.text !== undefined ? attrs.text : children);
N3.register(block);
const plain = catalog.showcaseEntry({prompt:'Compute mul(2, 4).', answer:'List<3>'}, 'export.json', 'integer');
assert.equal(plain.querySelectorAll('.n3').length, 0);
assert(plain.textContent.includes('Compute mul(2, 4).'));
assert(plain.textContent.includes('List<3>'));
const stored = catalog.showcaseEntry({prompt:'Use mul(2, 4).', answer:'mul(2, 4)'}, 'export.json', 'integer');
assert.equal(stored.querySelectorAll('.n3').length, 2);
assert(!stored.textContent.includes('mul(2, 4)'));
const design = catalog.designBrief({goal:'Calendar',inputs:'World: Gregorian Date<2000-01-01>',
  output:'Ordered List<Date> of days',rules:['Compute from the calendar.'],
  prompt:'Let A = Date<2000-01-01>. Find the next date.'},'integer');
assert.equal(design.querySelectorAll('.n3').length,0);
assert(design.textContent.includes('World: Gregorian Date<2000-01-01>'));
assert(design.textContent.includes('Let A = Date<2000-01-01>'));
""")


@pytest.mark.parametrize("script", [
    "research-ui", "learn-kinds", "learn-checks", "learn-evidence", "first-tower", "roads",
    "modes", "boundary", "lab-computer", "lab-preview-world", "ladders", "spec-tables",
])
def test_atoms_page_script_parses(script: str) -> None:
    path = ROOT / "docs/assets/js/atoms2" / f"{script}.js"
    result = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", ["stepview.js", "worlds/legacy-ui.js", "worlds/declare.js"])
def test_other_page_script_parses(path: str) -> None:
    result = subprocess.run([NODE, "--check", str(ROOT / "docs/assets/js" / path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
