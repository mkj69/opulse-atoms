"""Browser notation v3 lexer, renderer and export contract under Node."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

SCRIPT = r"""
const fs = require('fs');
const root = process.argv[1];
const N3 = require(root + '/docs/assets/js/atoms2/n3.js');
const base = root + '/tests/data/notation3_js/';
const lines = name => fs.readFileSync(base + name, 'utf8').trimEnd().split('\n')
  .map(line => line.slice(line.indexOf('\t') + 1));
const display = lines('corpus_final.txt'), ascii = lines('corpus_ascii.txt');
class Node {
  constructor(tag, text = '') { this.tag = tag; this.attrs = {}; this.children = []; this._text = text; this.className = ''; }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name]; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = value; this.children = []; }
}
globalThis.document = { readyState: 'loading', createElement: tag => new Node(tag),
  createTextNode: text => new Node('#text', text), addEventListener() {}, querySelectorAll: () => [] };
const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
const fixture = { version: 1, worlds: { test: { legend: [
  { mark: '\\dia_6', display: '♦₆', name: 'multiply', kind: 'operation',
    signature: { ascii: '\\dia_6 : \\bbZ -> \\bbZ', display: '♦₆ : ℤ → ℤ' } },
  { mark: '\\bbZ', display: 'ℤ', name: 'integer', kind: 'object', signature: null }
], formulas: { 'op multiply(x)': { display: '♦₆ x', ascii: '\\dia_6 x',
  signature: { display: '♦₆ : ℤ → ℤ', ascii: '\\dia_6 : \\bbZ -> \\bbZ' } } },
  prose: { 'Use multiply': [['t', 'Use '], ['f', '♦₆', '\\dia_6']] } } } };
N3.register(fixture);
const formulas = display.map((text, index) => {
  const rendered = N3.render(text, ascii[index]);
  return { display: N3.toDisplay(ascii[index]), ascii: N3.toAscii(text),
    text: rendered.textContent, stored: rendered.getAttribute('data-n3-ascii') };
});
const integer = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds/integer.json', 'utf8'));
const definitions = integer.operators.map(op => op.definition);
const integerLegend = JSON.parse(fs.readFileSync(root + '/docs/assets/data/worlds_v2/integer.json', 'utf8'));
N3.register(integerLegend.notation3);
const panel = N3.legendPanel('test');
const fixtureFormula = A2.expr('op multiply(x)', {world:'test'}).children[0];
N3.register({worlds: {values: {formulas: {'shared': {display: '♦₆', ascii: '\\dia_6'}}, prose: {}, legend: [
  {name:'Thing', kind:'object', display:'𝔼₃', mark:'\\bbE_3', forms:['Thing']},
  {name:'List', kind:'object', display:'𝕃₂', mark:'\\bbL_2', forms:['nil','cons']},
  {name:'List.nil', kind:'operation', form_of:'List', display:'■₄', mark:'\\sq_4'},
  {name:'List.cons', kind:'operation', form_of:'List', display:'♣₅', mark:'\\club_5'},
  {name:'Quot', kind:'template', display:'ℚ₆', mark:'\\bbQ_6'},
  {name:'list[int]', kind:'object', display:'𝕍₇', mark:'\\bbV_7', forms:['nil','cons']},
  {name:'list[int].nil', kind:'operation', form_of:'list[int]', display:'■₈', mark:'\\sq_8'},
  {name:'list[int].cons', kind:'operation', form_of:'list[int]', display:'♣₉', mark:'\\club_9'},
  {name:'plus', kind:'BIN-sign', display:'+', mark:null},
  {name:'and', kind:'BIN-sign', display:'and', mark:null}
]}}});
N3.register({worlds: {same: {formulas: {'shared': {display: '♦₆', ascii: '\\dia_6'}}}}});
N3.register({worlds: {mixed: {legend: [
  {name:'same',kind:'operation',display:'♠₁',mark:'\\spade_1'},
  {name:'same',kind:'object',display:'𝔼₃',mark:'\\bbE_3'}
]}}});
const valueCases = [0, -12, 'say "hi"', true, false, [1, 'x'],
  {t:'int', v:-3}, {t:'str', v:'q'}, {t:'bool', tag:'true', f:[]},
  {t:'Thing', tag:'Thing', f:[1,2]}, {t:'Thing', tag:'Thing', f:[1,2]},
  {t:'List', tag:'nil', f:[]}, {t:'List', tag:'cons', f:[1, {t:'List', tag:'nil', f:[]}]},
  {t:'list[int]', tag:'cons', f:[2, {t:'list[int]',tag:'nil',f:[]}]},
  {t:'Thing',tag:'Thing',f:[1,2]}, {ok:{t:'int',v:5}}, {bottom:'reason'}, {unknown:'resource'}];
const values = valueCases.map(input => N3.value(input, 'values'));
const renderedValues = valueCases.map(input => A2.value(input, {world:'values'}).textContent);
const valueNodes = valueCases.map(input => A2.value(input, {world:'values'}).children.some(child => child.className === 'n3'));
const valuePanel = N3.legendPanel('values');
const findNodes = (node, name) => [node, ...node.children.flatMap(child => findNodes(child, name))]
  .filter(child => child.className === name);
const extended = 'memo rec ♦ᵣ(x, y) = fail("reason") ⊢ ↓ x in ♦ᵣ(x, y)';
const program = 'prog (x = -1) entry L0 { L0: x := unknown("fuel"); if x jump L1 else L2; L1: halt x }';
const towerFixture = {version: 1, worlds: {tower: {legend: fixture.worlds.test.legend,
  formulas: {'op f(x) -> Int = x L1': {display: '♦₆ x = x', ascii: '\\dia_6 x = x',
    signature: {display: '¹♦₆ : ℤ → ℤ', ascii: '^1\\dia_6 : \\bbZ -> \\bbZ'}}}, prose: {}}}};
N3.register(towerFixture);
const designText = 'op imagined(x) = x <future> L2';
N3.register({worlds: {designed: {designs: [designText], formulas: {
  [designText]: {display: '♦₆', ascii: '\\dia_6'}
}}, elsewhere: {designs: ['other design']}}});
const designNode = A2.expr(designText, {world:'designed'});
const forcedDesign = A2.expr('op missing(x)', {world:'test', design:true});
const originalExpr = A2.expr, originalToken = A2.token, originalEl = A2.el;
A2.expr = text => ({tag: 'formula', text});
A2.token = text => ({tag: 'token', text});
A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, children: Array.isArray(children) ? children : [children],
  appendChild(child) {this.children.push(child);}});
require(root + '/docs/assets/js/atoms2/tower.js');
const story = [{name:'f', ascii:'op f(x) -> Int = x L1', layer:1, def_layer:1, kind:'operation',
  body_sha256:'example', examples:[]}];
const towerCard = A2.worlds.entryCard(story[0], story, '', {}, 'tower', null);
const towerLines = towerCard.children.filter(child => child.tag === 'formula').map(child => child.text);
A2.expr = originalExpr; A2.token = originalToken; A2.el = originalEl;
console.log(JSON.stringify({formulas, definitions: definitions.map(text => N3.toDisplay(N3.toAscii(text)) === text),
  values, renderedValues, valueNodes, valuePanel:valuePanel.textContent,
  sign:findNodes(valuePanel, 'n3').find(node => node.textContent === '+').getAttribute('data-n3-ascii'),
  wordSign:findNodes(valuePanel, 'n3').find(node => node.textContent === 'and').getAttribute('data-n3-ascii'),
  names:['@multiply', 'Thing', 'plus'].map((name, index) => N3.name(name, index ? 'values' : 'test')),
  preferred:N3.name('multiply','test','operation'), missingSort:N3.value({t:'Missing',tag:'Missing',f:[1]},'values'),
  preferredKind:N3.name('same','mixed','object'),
  formatted:A2.formatValue({t:'List',tag:'nil',f:[]},{world:'values'}),
  formattedCard:A2.formatValue({t:'Thing',tag:'Thing',f:[1,2]},{world:'values'}),
  fallback:A2.formatValue({t:'Missing',tag:'Missing',f:[1]},{world:'values'}),
  shared:N3.lookup('shared'), ambiguous:(N3.register({worlds:{other:{formulas:{shared:{display:'♠₁',ascii:'\\spade_1'}}}}}), N3.lookup('shared')),
  valueRoundTrips:values.every(item => item && N3.toAscii(item.display) === item.ascii && N3.toDisplay(item.ascii) === item.display),
  nonFormula:A2.expr('not recorded', {world:'values'}).className,
  plainWords:['pending', '42'].map(text => A2.expr(text, {world:'test'}).className),
  designs: {scoped:N3.isDesign(designText, 'designed'), unscoped:N3.isDesign(designText),
    wrongWorld:N3.isDesign(designText, 'elsewhere'), absent:N3.isDesign('absent'),
    node:{tag:designNode.tag, className:designNode.className, text:designNode.textContent,
      children:designNode.children.map(child => child.tag)}, forced:{className:forcedDesign.className,
      text:forcedDesign.textContent, children:forcedDesign.children.map(child => child.tag)}},
  plainToken:A2.token('not recorded', {world:'values'}).className,
  namedToken:A2.token('Thing', {world:'values'}).textContent,
  layeredToken:A2.token('List.cons', {world:'values', kind:'operation', layer:3}).textContent,
  layeredBadge:A2.token('List.cons', {world:'values', kind:'operation', layer:3}).children[1].className,
  hourMark:(() => {
    // 'Hour' in trace frames is the declared object 'hour' (sort names are case-insensitive).
    const entry = integerLegend.notation3.worlds.integer.legend.find(entry =>
      entry.kind === 'object' && entry.name.toLowerCase() === 'hour');
    return {display:entry.display, ascii:entry.mark};
  })(),
  dottedFrame:(() => {
    const chip = A2.token('Hour.make', {world:'integer', kind:'operation', layer:2});
    return {text:chip.textContent, className:chip.className, mark:chip.children[0].textContent,
      ascii:chip.children[0].getAttribute('data-n3-ascii'), part:chip.children[1].className,
      layer:chip.children[2].className};
  })(),
  dottedStore:A2.token('Hour.Pack', {world:'integer'}).textContent,
  dottedCanon:A2.token('Hour.base', {world:'integer'}).textContent,
  dottedCheck:A2.token('Hour.EdgeValid', {world:'integer'}).textContent,
  dottedField:A2.token('Hour.start_point', {world:'integer'}).textContent,
  dottedConstructor:(() => {
    const chip = A2.token('List.cons', {world:'values', kind:'object'});
    return {text:chip.textContent, className:chip.className};
  })(),
  designToken:(() => {
    const node = A2.token('split(Word<2,"+",2>)', {world:'designed', kind:'operation', layer:1});
    N3.register({worlds: {designed: {designs: [designText, 'split(Word<2,"+",2>)'], formulas: {}, legend: []}}});
    const after = A2.token('split(Word<2,"+",2>)', {world:'designed', kind:'operation', layer:1});
    return {before:node.className, tag:after.tag, className:after.className, text:after.textContent};
  })(),
  dottedUnknown:(() => {
    const node = A2.token('Missing.make', {world:'integer', kind:'object'});
    return {tag:node.tag, className:node.className, text:node.textContent};
  })(),
  templateName:N3.name('Quot','values','template'),
  templateToken:A2.token('Quot', {world:'values', kind:'template', layer:2}).textContent,
  legacySeparatorTokens:N3.lex('::').map(token => token.type),
  unknownForm:N3.value({t:'Thing',tag:'other',f:[1]},'values'),
  missingConstructor:N3.value({t:'List',tag:'unknown',f:[1]},'values'),
  allowed: [...N3.ALLOWED], missing: A2.expr('op unmapped(x)', {world:'test'}).className,
  registered: fixtureFormula.textContent, registeredClass: fixtureFormula.className,
  registeredAscii: fixtureFormula.getAttribute('data-n3-ascii'),
  token: A2.token('♦₆', {world:'test'}).textContent,
  prose: N3.prose('Use multiply', 'test'), panel: panel.textContent,
  legendRows: panel.children[1].children[2].children.length,
  kinds: ['♦₆', '𝔻₁', 'Θ₁', 'Ô₁', '≡₁', '↝₁', '◈⁷₃'].map(N3.kindOfMark),
  extended: N3.toDisplay(N3.toAscii(extended)) === extended,
  program: N3.toDisplay(N3.toAscii(program)) === program,
  keywords: N3.lex(extended).filter(token => token.kind === 'kw').map(token => token.type),
  stringTokens: N3.lex(program).filter(token => token.type === 'STR').map(token => token.text), towerLines }));
"""


@pytest.fixture(scope="module")
def result():
    if NODE is None:
        pytest.skip("node is not installed")
    completed = subprocess.run([NODE, "-e", SCRIPT, str(ROOT)], capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


@requires_node
def test_reference_corpus_round_trips_and_renders(result):
    data = ROOT / "tests/data/notation3_js"
    display = [line.split("\t", 1)[1] for line in (data / "corpus_final.txt").read_text().splitlines()]
    ascii_lines = [line.split("\t", 1)[1] for line in (data / "corpus_ascii.txt").read_text().splitlines()]
    assert len(display) == len(ascii_lines) == len(result["formulas"])
    for rendered, expected_display, expected_ascii in zip(result["formulas"], display, ascii_lines):
        assert rendered == {"display": expected_display, "ascii": expected_ascii,
                            "text": expected_display, "stored": expected_ascii}


@requires_node
def test_legacy_definitions_and_allowed_code_points(result):
    assert len(result["definitions"]) == 100 and all(result["definitions"])
    corpus = (ROOT / "tests/data/notation3_js/corpus_final.txt").read_text()
    assert {char for char in corpus if not char.isascii()} <= set(result["allowed"])
    assert all(not char.isascii() for char in result["allowed"])
    assert "🚀" not in result["allowed"]
    assert set(result["allowed"]) == set(
        "♠♤♥♡♦♢♣♧■□●○▲△▼▽◆◇★☆ℂℍℕℙℚℝℤΓΔΘΛΞΠΣΦΨΩÂĈÊĜĤÎĴÔŜÛŴŶẐ≡↝⇝"
        "₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ′⟨⟩⌜⌝⌞⌟⇒→↦⊢…×∈∀∣↾↓⊤⊥◈"
    ) | {chr(0x1D538 + index) for index, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
         if letter not in "CHNPQRZ"}


@requires_node
def test_numbered_given_and_layered_given_signs():
    script = r'''
const N3 = require('./docs/assets/js/atoms2/n3.js');
for (const index of ['01', '07', '012']) {
  const ascii = '\\dia_' + index;
  const display = '♦' + Array.from(index).map(digit => '₀₁₂₃₄₅₆₇₈₉'[Number(digit)]).join('');
  if (N3.toAscii(display) !== ascii || N3.toDisplay(ascii) !== display ||
      !N3.lex(display)[0].given || N3.lex(display)[0].ascii !== ascii) throw Error(ascii);
}
if (N3.lex('♦₇')[0].given) throw Error('defined index');
for (const sign of '@#$&') {
  if (N3.toDisplay('^0' + sign + ' : \\bbB -> \\bbZ') !== '⁰' + sign + ' : 𝔹 → ℤ' ||
      N3.toAscii('⁰' + sign + ' : 𝔹 → ℤ') !== '^0' + sign + ' : \\bbB -> \\bbZ') throw Error('layered sign');
}
for (const mark of ['\\dia_0', '\\dia_00', '\\dia_007', '♦₀', '♦₀₀']) {
  try { N3.lex(mark); throw Error('accepted ' + mark); }
  catch (error) { if (error.message.startsWith('accepted')) throw error; }
}
'''
    result = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@requires_node
def test_converter_allocates_distinct_numbered_givens():
    script = r'''
const N3 = require('./docs/assets/js/atoms2/n3.js');
const converter = require('./docs/assets/js/atoms2/n3-convert.js');
const givens = Array.from({length: 40}, (_, index) => ({world:'new', name:'given'+index,
  kind:'operation', layer:0, origin:'given', arity:2}));
const atoms = givens.concat([{world:'new',name:'defined',kind:'operation',layer:1,origin:'invented',arity:2}]);
const entries = converter.worldLegend('new', atoms, []);
const overflow = entries.filter(entry => /^♦₀/.test(entry.display));
if (overflow.length !== 16 || overflow[6].display !== '♦₀₇' ||
    entries.find(entry => entry.name === 'defined').display !== '♦₁' ||
    new Set(entries.map(entry => entry.mark)).size !== entries.length) throw Error('allocation');
'''
    result = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@requires_node
def test_kit_and_legend_fixture(result):
    assert "n3-missing" in result["missing"]
    assert result["registered"] == "♦₆ x"
    assert result["registeredClass"] == "n3"
    assert result["registeredAscii"] == "\\dia_6 x"
    assert result["token"] == "♦₆"
    assert result["prose"][1] == ["f", "♦₆", "\\dia_6"]
    assert all(name in result["panel"] for name in ["Legend", "multiply", "integer", "Operation".lower(), "♦₆", "ℤ"])
    assert result["legendRows"] == 2
    assert result["kinds"] == ["operation", "object", "combinator", "observation", "law", "bridge", "kind7"]
    assert result["extended"] and result["program"]
    assert result["keywords"] == ["memo", "rec", "fail", "in"]
    assert result["stringTokens"] == ['"fuel"']
    assert result["towerLines"] == ["¹♦₆ : ℤ → ℤ", "op f(x) -> Int = x L1"]


@requires_node
def test_designs_render_only_as_plain_code(result):
    designs = result["designs"]
    assert designs["scoped"] and designs["unscoped"]
    assert not designs["wrongWorld"] and not designs["absent"]
    assert designs["node"] == {"tag": "code", "className": "a2-design-text",
                               "text": "op imagined(x) = x <future> L2", "children": ["#text"]}
    assert designs["forced"] == {"className": "a2-design-text", "text": "op missing(x)", "children": ["#text"]}
    assert all("n3-missing" not in name for name in result["plainWords"])


@requires_node
def test_dotted_chips_resolve_exact_atoms_and_object_frames(result):
    hour = result["hourMark"]["display"]
    assert result["hourMark"]["ascii"].startswith("\\bb")
    assert result["dottedFrame"] == {
        "text": hour + "makeL2", "className": "a2-tok a2-k-object a2-tok-invented a2-tok-n3",
        "mark": hour, "ascii": result["hourMark"]["ascii"], "part": "a2-layer-badge a2-part-badge",
        "layer": "a2-layer-badge",
    }
    assert result["dottedStore"] == hour + "store"
    assert result["dottedCanon"] == hour + "canon"
    assert result["dottedCheck"] == hour + "check"
    assert result["dottedField"] == hour + "start point"
    assert result["dottedConstructor"] == {
        "text": "♣₅", "className": "a2-tok a2-k-operation a2-tok-invented a2-tok-n3",
    }
    assert "n3-missing" in result["designToken"]["before"]
    assert {key: result["designToken"][key] for key in ("tag", "className", "text")} == {
        "tag": "code", "className": "a2-design-text", "text": 'split(Word<2,"+",2>)'}
    assert result["dottedUnknown"] == {
        "tag": "code", "className": "a2-design-text", "text": "Missing.make",
    }


@requires_node
def test_legend_names_values_and_unscoped_lookup(result):
    assert result["names"] == [
        {"display": "♦₆", "ascii": "\\dia_6"},
        {"display": "𝔼₃", "ascii": "\\bbE_3"},
        {"display": "+", "ascii": "+"},
    ]
    assert result["preferred"] == result["names"][0]
    assert result["preferredKind"] == result["names"][1]
    assert result["formatted"] == "■₄()"
    assert result["formattedCard"] == "𝔼₃(1, 2)"
    assert result["layeredToken"] == "♣₅L3" and result["layeredBadge"] == "a2-layer-badge"
    assert result["templateName"] == {"display": "ℚ₆", "ascii": "\\bbQ_6"}
    assert result["templateToken"] == "ℚ₆L2"
    assert result["legacySeparatorTokens"] == [":", ":"]
    assert result["unknownForm"] is None
    # A nullary capitalised tag would be a constant; this lowercase unknown form stays missing.
    assert result["missingConstructor"] is None
    # A sort the legend does not know keeps the machine fallback (nullary capitalised forms
    # would be constants, so the fixture gives the card a field).
    assert result["fallback"] == "Missing<1>"
    assert result["namedToken"] == "𝔼₃"
    assert result["missingSort"] is None
    assert result["shared"] == {"display": "♦₆", "ascii": "\\dia_6"}
    assert result["ambiguous"] is None
    assert result["sign"] == "+"
    assert result["wordSign"] == "and"
    assert "object (forms: nil, cons)" in result["valuePanel"]
    assert "n3-missing" not in result["nonFormula"]
    assert "n3-missing" not in result["plainToken"]


@requires_node
def test_json_values_render_and_round_trip(result):
    expected = ['0', '-12', '"say \\"hi\\""', '⊤', '⊥', '[1, "x"]', '-3', '"q"', '⊤',
                '𝔼₃(1, 2)', '𝔼₃(1, 2)', '■₄()', '♣₅(1, ■₄())', '♣₉(2, ■₈())',
                '𝔼₃(1, 2)', '5', 'fail("reason")', 'unknown("resource")']
    assert [entry["display"] for entry in result["values"]] == expected
    assert result["renderedValues"] == expected
    assert all(result["valueNodes"])
    assert result["valueRoundTrips"]
    for entry in result["values"]:
        assert entry["ascii"]


@requires_node
def test_value_matches_python_converter_for_compound_fields_and_outcomes():
    from opulse import notation3
    from opulse.atoms.values import Bottom, Card, Ok, Unknown
    from opulse.notation3 import convert as notation3_convert
    from opulse.notation3 import legend as notation3_legend

    legend = notation3_legend.assign([
        notation3_legend.Atom("Box", "object", 0, "given", forms=("empty", "set", "pair")),
        notation3_legend.Atom("Inner", "object", 0, "given", forms=("nil", "item")),
    ])
    inner = Card("Inner", "item", (3,))
    values = [Card("Box", "set", (inner,)), Card("Box", "set", (Card("Inner", "nil", ()),)),
              Card("Box", "set", ((inner, -2),)), Card("Box", "set", ("word",)),
              Card("Box", "empty", ()), Card("Box", "pair", (inner, inner)),
              (inner, -5, "quote"), Ok(Card("Box", "set", (inner,))),
              Bottom("guard"), Unknown("fuel")]

    def json_value(value):
        if isinstance(value, Card):
            return {"t": value.sort, "tag": value.tag, "f": [json_value(field) for field in value.fields]}
        if isinstance(value, tuple):
            return [json_value(field) for field in value]
        if isinstance(value, Ok):
            return {"ok": json_value(value.value)}
        if isinstance(value, Bottom):
            return {"bottom": json_value(value.reason)}
        if isinstance(value, Unknown):
            return {"unknown": json_value(value.resource)}
        return value

    payload = {"legend": legend.to_json(), "values": [json_value(value) for value in values]}
    script = """const N3 = require('./docs/assets/js/atoms2/n3.js');
const data = JSON.parse(process.argv[1]); N3.register({worlds:{test:{legend:data.legend}}});
console.log(JSON.stringify(data.values.map(value => N3.value(value, 'test'))));"""
    result = subprocess.run([NODE, "-e", script, json.dumps(payload)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    expected = [notation3_convert.convert_value(value, legend) for value in values]
    assert actual == [{"display": notation3.show(item), "ascii": notation3.show(item, ascii=True)}
                      for item in expected]
    # Printer rule: a call whose single argument is compound (a card) has a space; a list is simple.
    assert actual[0]["display"].count(" (") == 1
    assert actual[1]["display"].count(" (") == 1
    assert actual[2]["display"].count(" (") == 0


@requires_node
def test_world_scoped_atom_chips_and_json_outcomes():
    script = r"""
const N3 = require('./docs/assets/js/atoms2/n3.js');
class Node {
  constructor(tag, text='') { this.tagName=tag; this.children=[]; this._text=text; this.attrs={}; this.className=''; }
  appendChild(child) { this.children.push(child); return child; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text=String(value); this.children=[]; }
  setAttribute(name,value) { this.attrs[name]=value; }
  getAttribute(name) { return this.attrs[name]; }
}
global.document={readyState:'loading',createElement:tag=>new Node(tag),
  createTextNode:text=>new Node('#text',text), addEventListener(){},querySelectorAll(){return []}};
const A2 = require('./docs/assets/js/atoms2/kit.js');
N3.register({worlds:{sample:{legend:[
  {name:'explore',kind:'combinator',display:'Γ₁'},
  {name:'ambiguity',kind:'observation',display:'Â₂'},
  {name:'beat_row',kind:'bridge',display:'↝₃'},
  {name:'assoc_count',kind:'law',display:'≡₄'},
  {name:'map',kind:'observation',display:'Ĉ₅'},
  {name:'@fold',kind:'combinator',display:'Δ₆'},
  {name:'Box',kind:'object',display:'𝔹',forms:['val']}
]}}});
N3.register({worlds:{sample:{formulas:{'call()':{display:'Γ₁',ascii:'\\Gamma_1'}}}}});
if (!N3.lookup('call()','sample') || !N3.name('@explore','sample','combinator'))
  throw Error('registration discarded earlier formulas or marks');
for (const [text,kind] of [['@explore','combinator'],['?ambiguity','observation'],
  ['~beat_row','bridge'],['#assoc_count','law'],['?map','observation'],['@fold','combinator']]) {
  const mark = N3.name(text,'sample',kind);
  if (!mark || N3.toAscii(mark.display) !== mark.ascii) throw Error('invalid name: '+text);
  const chip = A2.token(text,{world:'sample',kind});
  if (chip.textContent !== mark.display || !chip.children[0].getAttribute('data-n3-ascii'))
    throw Error('unrendered chip: '+text);
}
if (N3.name('?map','sample','operation') !== null) throw Error('wrong kind selected');
for (const [value,expected] of [[{ok:34},'34'],[{ok:[11,72,153]},'[11, 72, 153]'],
  [{ok:{t:'Box',tag:'val',f:[34]}},'𝔹(34)'],
  [{bottom:'guard'},'fail("guard")'],[{unknown:'fuel'},'unknown("fuel")']]) {
  const node=A2.outcome(value,{world:'sample'});
  if (node.textContent!==expected || !node.children[0].getAttribute('data-n3-ascii'))
    throw Error('outcome was not rendered: '+expected);
}
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@requires_node
def test_nullary_capitalised_forms_render_as_constants():
    script = """const N3 = require('./docs/assets/js/atoms2/n3.js');
N3.register({worlds:{w:{legend:[{mark:'\\\\bbR_1',display:'ℝ₁',name:'Route',kind:'object',layer:1,origin:'invented',forms:['route']}]}}});
console.log(JSON.stringify([N3.value({t:'Node',tag:'A',f:[]},'w'), N3.value({t:'Map',tag:'Metro',f:[]},'w')]));"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [{"display": "A", "ascii": "A"}, {"display": "Metro", "ascii": "Metro"}]
