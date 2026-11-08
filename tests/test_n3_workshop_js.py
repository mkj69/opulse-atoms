"""The Workshop browser converter follows the Python notation-v3 converter."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from opulse.notation3 import convert as notation3_convert

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

CASES = [
    ("operation", "integer", "op multiply_preview(a, b) = if is_zero(b) then 0 else add(a, multiply_preview(a, dec(b))) L1",
     "op multiply_preview(a: Int, b: Int) -> Int = if is_zero(b) then 0 else add(a, multiply_preview(a, dec(b))) L1"),
    ("operation", "integer", "op step(a) = let temp = add(a, 1) in mod(temp, 3) L1",
     "op step(a: Int) -> Int = let temp = add(a, 1) in mod(temp, 3) L1"),
    ("operation", "integer", "op choose(a, b) = if is_zero(a) or lt(a, b) and not is_zero(b) then add(a, b) else mod(a, 3) L1",
     "op choose(a: Int, b: Int) -> Int = if is_zero(a) or lt(a, b) and not(is_zero(b)) then add(a, b) else mod(a, 3) L1"),
    ("operation", "integer", "op chain(a, b) = if is_zero(a) then 0 else if is_zero(b) then 1 else add(a, b) L1",
     "op chain(a: Int, b: Int) -> Int = if is_zero(a) then 0 else if is_zero(b) then 1 else add(a, b) L1"),
    ("operation", "integer", "op empty() = 7 L1", "op empty() -> Int = 7 L1"),
    ("operation", "integer", "op three(a, b, c) = add(add(a, b), c) L1",
     "op three(a: Int, b: Int, c: Int) -> Int = add(add(a, b), c) L1"),
    ("object", "integer", "obj Byte83 = mod(339, 256) L1", "obj Byte83 = mod(339, 256) L1"),
    ("combinator", "integer", "comb @twice_preview[f](x) = f(f(x)) L1",
     "comb @twice_preview[f: A -> A](x: A) -> A = f(f(x)) L1"),
    ("combinator", "integer", "comb @fourfold[f](x) = f(f(f(f(x)))) L1",
     "comb @fourfold[f: A -> A](x: A) -> A = f(f(f(f(x)))) L1"),
    ("observation", "robot", "obs ?clear_ahead = not ?front_wall{} and not ?front_water{} L1",
     "obs ?clear_ahead{s} = not(?front_wall{s}) and not(?front_water{s}) L1"),
    ("law", "integer", "law #byte_shift(a) = eq(mod(add(a, 256), 256), mod(a, 256)) L1",
     "law #byte_shift: eq(mod(add(a, 256), 256), mod(a, 256)) for a: Int L1"),
    ("bridge", "integer", "bridge ~to_byte(a) = mod(a, 256) L1",
     "bridge ~to_byte: Int -> Int = mod(a, 256) L1"),
]


def browser(script, data=None):
    setup = r"""
const N3 = require('./docs/assets/js/atoms2/n3.js');
require('./docs/assets/js/atoms2/kit.js');
const mock = require('./docs/assets/js/atoms2/lab-preview-world.js');
const converter = require('./docs/assets/js/atoms2/n3-convert.js');
const define = require('./docs/assets/js/atoms2/define.js');
class Element {
  constructor(text = '') { this.children = []; this.attrs = {}; this.value = text; this.className = ''; }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  set textContent(text) { this.value = text; this.children = []; }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(''); }
}
globalThis.document = { createElement: () => new Element(), createTextNode: text => new Element(text) };
const cases = JSON.parse(process.argv[1]);
"""
    proc = subprocess.run([NODE, "-e", setup + script, json.dumps(data)], cwd=ROOT,
                          check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def mock_atoms(definitions, world, legend):
    _, atoms = legend.atoms_from_atoms2("workshop", {
        "world": world, "definitions": [item for item in definitions if item["world"] == world]
    })
    atoms.append(legend.Atom("eq", "operation", 0, "given", 2))
    return atoms


@requires_node
def test_workshop_matches_python_converter():
    convert = notation3_convert
    from opulse.notation3 import legend as legend

    rows = browser("""
const results = cases.map(([kind, world, source]) => {
  const parsed = define.parse(source, kind);
  const result = converter.preview(parsed, kind, world, mock.defs, [], source);
  return {world, result};
});
console.log(JSON.stringify({results, defs: mock.defs}));
""", [item[:3] for item in CASES])
    for (kind, world, source, typed), actual in zip(CASES, rows["results"]):
        atoms = mock_atoms(rows["defs"], world, legend)
        name = source.split()[1].split("(")[0].split("[")[0].lstrip("@?#~")
        count = len(source.split("=", 1)[0].split("(")[-1].split(")")[0].split(","))
        if kind in ("object", "law", "bridge", "observation"):
            count = 0 if kind != "bridge" else 1
        if kind == "combinator":
            count = 1
        if kind == "operation" and source.startswith("op empty("):
            count = 0
        world_legend = legend.assign([*atoms, legend.Atom(name, kind, 1, "invented", count)])
        expected = convert.convert_text(typed, world_legend)
        assert actual["result"].get("fallback") is None, (source, actual)
        assert actual["result"]["formula"] == expected["display"], source
        assert actual["result"]["signature"] == (expected["signature"] or {}).get("display"), source


@requires_node
def test_registered_world_legend_and_session_definitions_continue_indices():
    convert = notation3_convert
    from opulse.notation3 import legend as legend

    definitions = browser("console.log(JSON.stringify(mock.defs));", [])
    atoms = mock_atoms(definitions, "integer", legend)
    base = legend.assign(atoms).to_json()
    source = "op step(a) = add(a, 1) L1"
    typed = "op step(a: Int) -> Int = add(a, 1) L1"
    session = {"world": "integer", "name": "twiddle", "kind": "operation", "layer": 1,
               "origin": "invented", "params": ["a"]}
    result = browser("""
N3.register({worlds: {integer: {legend: cases.legend}}});
const source = cases.source;
const preview = converter.preview(define.parse(source, 'operation'), 'operation', 'integer', mock.defs, [cases.session], source);
console.log(JSON.stringify({preview, mark: converter.worldLegend('integer', mock.defs, [cases.session])
  .find(entry => entry.name === 'twiddle').display}));
""", {"legend": base, "source": source, "session": session})
    assigned = legend.assign([*atoms, legend.Atom("twiddle", "operation", 1, "invented", 1),
                              legend.Atom("step", "operation", 1, "invented", 1)])
    expected = convert.convert_text(typed, assigned)
    assert result["mark"] == assigned.by_name("twiddle").display
    assert result["preview"]["formula"] == expected["display"]
    assert result["preview"]["signature"] == expected["signature"]["display"]


@requires_node
def test_given_overflow_continues_defined_operation_indices():
    from opulse.notation3 import legend as legend

    givens = [{"world": "overflow", "name": f"g{index}", "kind": "operation", "layer": 0,
               "origin": "given", "arity": 1} for index in range(28)]
    new = {"world": "overflow", "name": "fresh", "kind": "operation", "layer": 1,
           "origin": "invented", "params": ["a"]}
    results = browser("""
console.log(JSON.stringify(converter.worldLegend('overflow', cases.givens, [cases.new])
  .map(entry => [entry.name, entry.display])));
""", {"givens": givens, "new": new})
    expected = legend.assign([*(legend.Atom(item["name"], "operation", 0, "given", 1) for item in givens),
                              legend.Atom("fresh", "operation", 1, "invented", 1)])
    assert results == [[entry.atom.name, entry.display] for entry in expected.entries]


@requires_node
def test_workshop_previews_render_round_trippable_formula_nodes():
    rows = browser("""
console.log(JSON.stringify(cases.map(([kind, world, source]) => {
  const preview = converter.preview(define.parse(source, kind), kind, world, mock.defs, [], source);
  return [preview.signature, preview.formula].filter(Boolean).map(text => {
    const element = converter.render(text);
    return {className: element.className, text: element.textContent,
      ascii: element.getAttribute('data-n3-ascii'), valid: N3.toDisplay(N3.toAscii(element.textContent)) === element.textContent};
  });
})));
""", [item[:3] for item in CASES])
    assert all(row["className"] == "n3" and row["valid"] and row["ascii"] for pair in rows for row in pair)
    assert all("op " not in row["text"] and "obj " not in row["text"] for pair in rows for row in pair)
    assert all(pair for pair in rows)


@requires_node
def test_unconvertible_preview_is_plain_machine_code():
    result = browser("""
const source = 'obj PairRatio = refine {num: int, den: int} where neq(den, 0) canon reduce L1';
console.log(JSON.stringify(converter.preview(define.parse(source, 'object'), 'object', 'integer', mock.defs, [], source)));
""", [])
    assert result["fallback"] == "No display form for this construct yet"
    assert result["machine"].startswith("obj PairRatio")


@requires_node
def test_session_cards_and_outcomes_use_v3_values():
    result = browser("""
const session = [{world: 'integer', name: 'CaseBox', kind: 'object', origin: 'invented', layer: 1}];
const values = [
  {t: 'CaseBox', tag: 'some', f: [{t: 'int', v: 2}]},
  {ok: [{t: 'CaseBox', tag: 'some', f: [{t: 'int', v: 2}]}, true, 'word']},
  {bottom: 'invalid'}, {unknown: 'fuel'}
];
const entries = values.map(value => {
  const text = converter.value(value, 'integer', mock.defs, session);
  const rendered = text && converter.render(text.display);
  return {text: text && text.display, roundtrip: !!rendered &&
    N3.toDisplay(rendered.getAttribute('data-n3-ascii')) === rendered.textContent};
});
const single = converter.value({t: 'CaseBox', tag: 'only', f: [{t: 'int', v: 3}]},
  'integer', mock.defs, [{...session[0], forms: ['only']}]);
console.log(JSON.stringify({entries, single: single.display}));
""", [])
    assert [row["text"] for row in result["entries"]] == [
        "𝔸₁(2)", '[𝔸₁(2), ⊤, "word"]', 'fail("invalid")', 'unknown("fuel")'
    ]
    assert result["single"] == "𝔸₁(3)"
    assert all(row["roundtrip"] for row in result["entries"])


@requires_node
def test_session_card_display_matches_python_tag_rule():
    convert = notation3_convert
    from opulse import notation3 as n3
    from opulse.notation3 import legend as legend
    from opulse.atoms.values import Card, Ok

    definitions = browser("console.log(JSON.stringify(mock.defs));", [])
    world = legend.assign([*mock_atoms(definitions, "integer", legend),
                           legend.Atom("CaseBox", "object", 1, "invented", forms=("none", "some"))])
    result = browser("""
const session = [{world: 'integer', name: 'CaseBox', kind: 'object', origin: 'invented',
  layer: 1, forms: ['none', 'some']}];
console.log(JSON.stringify(converter.value({ok: {t: 'CaseBox', tag: 'some',
  f: [{t: 'int', v: 2}]}}, 'integer', mock.defs, session)));
""", [])
    assert result["display"] == n3.show(convert.convert_value(Ok(Card("CaseBox", "some", (2,))), world))
    assert result["ascii"] == n3.show(convert.convert_value(Card("CaseBox", "some", (2,)), world), ascii=True)


@requires_node
def test_session_multi_form_cards_always_use_constructor_calls():
    result = browser("""
const session = [{world:'integer',name:'CaseBox',kind:'object',origin:'invented',layer:1,
  forms:['none','some']}];
console.log(JSON.stringify(['none','some'].map((tag, index) =>
  converter.value({t:'CaseBox',tag,f:index ? [2] : []},'integer',mock.defs,session))));
""", [])
    assert all(entry and "::" not in entry["display"] for entry in result)
    assert result[0]["display"].endswith("()")
    assert result[1]["display"].endswith("(2)")
    from opulse import notation3
    assert all(entry["display"] == notation3.to_display(entry["ascii"]) for entry in result)


@requires_node
def test_mounted_workshop_preview_contains_display_not_machine_source():
    result = browser("""
class BrowserNode {
  constructor(tag, value = '') {
    this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.style = {}; this._text = value; this._value = null; this.className = '';
    this.classList = {toggle: () => {}, add: () => {}, remove: () => {}};
  }
  appendChild(child) {
    if (typeof child !== 'object') child = new BrowserNode('#text', String(child));
    this.children.push(child); child.parentElement = this; return child;
  }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === 'value') this._value = value; }
  getAttribute(key) { return this.attrs[key] || null; }
  get value() { return this._value === null ? (this.children[0] && this.children[0].value) || '' : this._value; }
  set value(value) { this._value = value; }
  get firstChild() { return this.children[0]; }
  get options() { return this.children; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(text) { this._text = String(text); this.children = []; }
  find(selector) {
    const candidates = [this, ...this.children.flatMap(child => child.find(selector))];
    return candidates.filter(child => selector.startsWith('.') ? child.className.split(' ').includes(selector.slice(1))
      : selector.startsWith('[') ? child.attrs[selector.slice(1, selector.indexOf('='))] === selector.match(/"([^"]+)"/)[1]
      : child.tag === selector);
  }
  querySelector(selector) { return this.find(selector)[0] || null; }
  querySelectorAll(selector) { return this.find(selector); }
}
globalThis.document = {createElement: tag => new BrowserNode(tag),
  createElementNS: (ns, tag) => new BrowserNode(tag), createTextNode: text => new BrowserNode('#text', text),
  querySelectorAll: () => [], addEventListener: () => {}, readyState: 'loading'};
globalThis.matchMedia = () => ({matches: true});
const A2 = globalThis.A2;
let mount;
A2.register = (name, handler) => { if (name === 'define') mount = handler; };
delete require.cache[require.resolve('./docs/assets/js/atoms2/define.js')];
require('./docs/assets/js/atoms2/define.js');
const host = new BrowserNode('main');
mount(host, mock);
const source = define.examples.operation.good;
host.querySelector('.a2-define-run').listeners.click();
const card = host.querySelector('.a2-define-card');
const preview = {source, visible: card.textContent,
  formula: card.find('.n3').map(node => [node.textContent, node.getAttribute('data-n3-ascii')])};
host.querySelectorAll('.a2-define-tab').find(tab => tab.getAttribute('data-kind') === 'object').listeners.click();
host.querySelector('textarea').value = define.examples.object.refine;
host.querySelector('.a2-define-run').listeners.click();
const fallback = host.querySelector('.a2-define-card');
console.log(JSON.stringify({...preview, fallback: fallback.textContent,
  machineCode: fallback.find('code').map(node => node.textContent),
  fallbackFormulaCount: fallback.find('.n3').length}));
""", [])
    assert result["source"] not in result["visible"]
    assert "multiply_preview(" not in result["visible"]
    assert len(result["formula"]) >= 2
    assert all(text and ascii for text, ascii in result["formula"])
    assert "No display form for this construct yet" in result["fallback"]
    assert result["machineCode"] == ["obj PairRatio = refine {num: int, den: int} where neq(den, 0) canon reduce L1"]
    assert result["fallbackFormulaCount"] == 0


def test_workshop_load_order_and_visible_preview_contract():
    page = (ROOT / "docs/play/index.md").read_text()
    script = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    assert "Type the ASCII storage form; the preview shows notation v3." in page
    assert page.index("n3-convert.js") < page.index("define.js")
    assert 'cardHolder.replaceChildren(definitionPreview(' in script
    assert 'root.N3Convert.render(result.formula)' in script
