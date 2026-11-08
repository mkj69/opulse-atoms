"""Atoms v2 UI kit and mock data: shared invariants checked under Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "docs" / "assets" / "js" / "atoms2"
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

SCRIPT = r"""
globalThis.window = globalThis;
require(process.argv[1] + "/kit.js");
const mock = require(process.argv[1] + '/../../../../tests/fixtures/atoms2-mock.js');
const out = {kinds: window.A2.KINDS6, legacyKinds: window.A2.KINDS, statuses: window.A2.STATUSES, derivations: {}, defs: []};
function leaves(n) { return n.children.length ? n.children.reduce((s, c) => s + leaves(c), 0) : 1; }
function ids(n, acc) { acc.push(n.id); n.children.forEach(c => ids(c, acc)); return acc; }
for (const [key, d] of Object.entries(mock.derivations)) {
  const all = ids(d.root, []);
  out.derivations[key] = {result: d.root.result, charged: mock.charged(d.root), leaves: leaves(d.root),
                          unique: new Set(all).size === all.length, world: d.world};
}
for (const d of mock.defs) out.defs.push({name: d.name, kind: d.kind, origin: d.origin, layer: d.layer,
  world: d.world, status: d.status, method: d.evidence ? d.evidence.method : null,
  deps: d.depends_on || [], steps: d.cost && d.cost.steps.example ? d.cost.steps.example.steps : null});
const e = window.A2.ease;
out.ease = [e.out(0), e.out(1), e.inOut(0.5)];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def data() -> dict:
    if NODE is None:
        pytest.skip("node is not installed")
    result = subprocess.run([NODE, "-e", SCRIPT, str(JS)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@requires_node
def test_kinds_and_statuses(data: dict) -> None:
    assert data["kinds"] == ["object", "operation", "combinator", "observation", "law", "bridge"]
    assert data["legacyKinds"] == data["kinds"][:4]
    assert data["statuses"] == ["written", "checked", "callable", "verified", "promoted"]
    assert data["ease"][0] == 0 and data["ease"][1] == 1
    assert abs(data["ease"][2] - 0.5) < 1e-6


@requires_node
def test_every_definition_follows_the_record(data: dict) -> None:
    for d in data["defs"]:
        assert d["kind"] in data["kinds"], d
        assert d["origin"] in ("given", "invented"), d
        assert d["status"] in data["statuses"], d
        if d["origin"] == "given":
            assert d["layer"] == 0, d
        else:
            assert d["layer"] >= 1 and d["method"], d


@requires_node
def test_sampled_evidence_is_never_promoted(data: dict) -> None:
    for d in data["defs"]:
        if d["method"] == "sampled":
            assert d["status"] != "promoted", d


@requires_node
def test_dependencies_sit_on_lower_layers(data: dict) -> None:
    by_world: dict[tuple[str, str], int] = {(d["world"], d["name"]): d["layer"] for d in data["defs"]}
    for d in data["defs"]:
        for dep in d["deps"]:
            candidates = [layer for (world, name), layer in by_world.items()
                          if name.lower().lstrip("@?") == dep.lower().lstrip("@?")
                          and (world == d["world"] or (d["world"] == "clock" and world == "integer" and dep == "Quot"))]
            assert candidates and any(layer < d["layer"] for layer in candidates), (d["name"], dep)


@requires_node
def test_derivations_charge_their_layer0_leaves(data: dict) -> None:
    expected = {"mul_3_4": (12, 13), "dot": (11, 30), "twice_triple": (9, 28), "front_free": (False, 2)}
    for key, (result, charged) in expected.items():
        d = data["derivations"][key]
        assert d["result"] == result and d["charged"] == charged == d["leaves"], (key, d)
        assert d["unique"], key


@requires_node
def test_cost_examples_match_derivations(data: dict) -> None:
    steps = {d["name"]: d["steps"] for d in data["defs"]}
    assert steps["mul"] == data["derivations"]["mul_3_4"]["charged"]
    assert steps["dot"] == data["derivations"]["dot"]["charged"]


@requires_node
def test_six_kind_tokens_icons_and_badges() -> None:
    script = r'''
globalThis.window = globalThis;
function node(tag) { return {tag, attrs: {}, children: [], setAttribute(k,v){this.attrs[k]=v},
  appendChild(child){this.children.push(child)}, get textContent(){return this.children.map(c=>c.textContent || '').join('')},
  set textContent(value){this.children=String(value)?[{textContent:String(value)}]:[]}}; }
globalThis.document = {readyState:'loading', createElement:node, createElementNS:(_,tag)=>node(tag),
  createTextNode:text=>({textContent:text}), addEventListener(){}, querySelectorAll:()=>[]};
require(process.argv[1] + '/kit.js');
const A2 = globalThis.A2;
const names = ['Frac', 'mul', '@twice', '?even', '#mul_comm', '~to_frac'];
const kinds = names.map(name => A2.kindOf(name));
const samples = names.map((name,index) => ({kind:kinds[index],
  token:A2.token(name,{origin:'invented',layer:2}), chip:A2.chip({name,kind:kinds[index],origin:'invented',layer:2}),
  glyph:A2.icon(kinds[index])}));
const given=A2.chip({name:'Zero',kind:'object',origin:'given',layer:0});
const badge=A2.badge('bounded',{scope:'a in 0..15',artifact:'artifact.json'});
console.log(JSON.stringify({kinds, names:samples.map(s=>s.token.textContent),
  chipNames:samples.map(s=>s.chip.children[1].textContent), tokenLayers:samples.map(s=>s.token.attrs['data-layer']),
  chipLayers:samples.map(s=>s.chip.attrs['data-layer']), glyphs:samples.map(s=>s.glyph.innerHTML),
  givenLayer:given.attrs['data-layer'] || null, badge:badge.textContent,
  expression:A2.expr('eq(mul(12, 34), mul(34, 12))').textContent,
  boundaryKinds:A2.boundary().kinds}));
'''
    result = subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert output["kinds"] == output["boundaryKinds"] == ["object", "operation", "combinator", "observation", "law", "bridge"]
    assert output["names"] == ["FracL2", "mulL2", "@twiceL2", "?evenL2", "#mul_commL2", "~to_fracL2"]
    assert output["chipNames"] == ["Frac", "mul", "@twice", "?even", "#mul_comm", "~to_frac"]
    assert output["tokenLayers"] == output["chipLayers"] == ["2"] * 6
    assert all(output["glyphs"]) and len(set(output["glyphs"])) == 6
    assert output["givenLayer"] is None or output["givenLayer"] == ""
    assert output["badge"] == "Bounded (a in 0..15)"
    assert output["expression"] == "eq(mul(12, 34), mul(34, 12))"


@requires_node
def test_given_chip_names_have_readable_ink_in_both_themes() -> None:
    script = r'''
const fs = require('node:fs');
globalThis.window = globalThis;
function node(tag) { return {tag, attrs:{}, children:[], setAttribute(key,value){this.attrs[key]=value},
  appendChild(child){this.children.push(child)},
  get textContent(){return this.children.map(child=>child.textContent || '').join('')},
  set textContent(value){this.children=[{textContent:String(value)}]}}; }
globalThis.document={readyState:'loading',createElement:node,createElementNS:(_,tag)=>node(tag),
  createTextNode:text=>({textContent:text}),addEventListener(){},querySelectorAll:()=>[]};
require(process.argv[1] + '/kit.js');
const css=fs.readFileSync(process.argv[2], 'utf8');
const kinds=A2.KINDS6;
const names=['Int','zero','@fold','?front_free','#mul_comm','~to_frac'];
function vars(scheme) {
  const start=css.indexOf((scheme==='default'?':root, ':'')+'[data-md-color-scheme="'+scheme+'"] {');
  const body=css.slice(start,css.indexOf('}',start));
  return Object.fromEntries([...body.matchAll(/(--a2-[\w-]+):\s*(#[\da-f]+);/g)].map(match=>[match[1],match[2]]));
}
function luminance(hex) {
  if(hex.length===4) hex='#'+hex.slice(1).split('').map(channel=>channel+channel).join('');
  const channels=hex.match(/[\da-f]{2}/g).map(channel=>parseInt(channel,16)/255)
    .map(channel=>channel<=.04045?channel/12.92:((channel+.055)/1.055)**2.4);
  return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
}
const output={};
for(const scheme of ['default','slate']) {
  const palette=vars(scheme);
  output[scheme]=kinds.map((kind,index)=>{
    const token=A2.token(names[index],{kind,origin:'given',layer:0});
    const chip=A2.chip({name:names[index],kind,origin:'given',layer:0});
    const fill=palette['--a2-'+kind];
    const ink=palette['--a2-chip-ink'];
    const values=[luminance(fill),luminance(ink)];
    return {kind,fill,ink,contrast:(Math.max(...values)+.05)/(Math.min(...values)+.05),
      token:token.textContent,chip:chip.children[1].textContent,
      given:token.attrs['data-layer']===undefined && chip.attrs['data-layer']===undefined};
  });
}
output.order=css.indexOf('.a2-tok.a2-tok-given {')>css.indexOf('.a2-tok {');
output.tokenRule=/\.a2-tok\.a2-tok-given\s*\{[^}]*background:\s*var\(--a2-k\);\s*color:\s*var\(--a2-chip-ink\)/.test(css);
output.chipNameRule=/\.a2-chip:not\(\.a2-invented\) \.a2-chip-name\s*\{\s*color:\s*var\(--a2-chip-ink\)/.test(css);
output.specialInk=/--a2-chip-ink:\s*#000000/.test(css);
console.log(JSON.stringify(output));
'''
    result = subprocess.run([NODE, "-e", script, str(JS), str(ROOT / "docs/assets/css/atoms2.css")],
                            text=True, capture_output=True, check=True)
    output = json.loads(result.stdout)
    # Every light kind colour now carries the scheme's white chip ink at >= 4.5:1; no black override.
    assert output["order"] and output["tokenRule"] and output["chipNameRule"] and not output["specialInk"]
    for scheme in ("default", "slate"):
        for sample in output[scheme]:
            assert sample["token"] == sample["chip"] and sample["given"], sample
            assert sample["ink"] != sample["fill"] and sample["contrast"] >= 4.5, sample
    assert output["default"][0]["fill"] == "#1a7b46"
    assert output["default"][1]["fill"] == "#bb4219"


@requires_node
def test_given_expression_names_are_filled_without_layer_badges() -> None:
    script = r'''
globalThis.window = globalThis;
function node(tag) { return {tag, attrs:{}, children:[], classList:{add(){}},
  setAttribute(key,value){this.attrs[key]=value}, getAttribute(key){return this.attrs[key]},
  hasAttribute(key){return key in this.attrs}, appendChild(child){this.children.push(child)},
  get childNodes(){return this.children},
  get textContent(){return this.children.map(child=>child.textContent).join('')},
  set textContent(value){this.children=[{textContent:String(value)}]}}; }
const code = node('code');
code.textContent = 'Graph Path ?probe{Graph} #law ~bridge(Graph)';
code.attrs['data-a2-given'] = 'Graph,Path ?probe #law ~bridge';
globalThis.document = {readyState:'loading', createElement:node, createElementNS:(_,tag)=>node(tag),
  createTextNode:text=>({textContent:text}), addEventListener(){},
  querySelectorAll:selector=>selector==='code[data-a2-expr]'?[code]:[]};
const A2 = require(process.argv[1] + '/kit.js');
const result = A2.expr('Graph Path next(Graph)', {given:['Graph','Path']});
const given = A2.token('Roads', {layer:0,origin:'invented'});
const chip = A2.chip({name:'Roads',kind:'object',layer:0,origin:'invented'});
A2.scan();
const first = code.textContent;
A2.scan();
console.log(JSON.stringify({text:result.textContent, first, idempotent:code.textContent===first,
  expressions:result.children.filter(child=>child.attrs && child.attrs['data-kind']).map(child=>({
    name:child.textContent, origin:child.attrs['data-origin'], className:child.className})),
  scanned:code.children.filter(child=>child.attrs && child.attrs['data-kind']).map(child=>({
    name:child.textContent, origin:child.attrs['data-origin']})),
  given:{tokenLayer:given.attrs['data-layer'] || null, tokenClass:given.className,
    chipLayer:chip.attrs['data-layer'] || null, chipTitle:chip.attrs.title, chipClass:chip.className}}));
'''
    result = subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert output["text"] == "Graph Path next(Graph)"
    assert output["first"] == "Graph Path ?probe{Graph} #law ~bridge(Graph)"
    assert output["idempotent"]
    assert [(item["name"], item["origin"]) for item in output["expressions"]] == [
        ("Graph", "given"), ("Path", "given"), ("next", "neutral"), ("Graph", "given")]
    assert all("a2-x-given" in item["className"] for item in output["expressions"] if item["origin"] == "given")
    assert all(item["origin"] == "given" for item in output["scanned"])
    assert output["given"]["tokenLayer"] is None and "a2-tok-given" in output["given"]["tokenClass"]
    assert output["given"]["chipLayer"] is None and "layer 0" not in output["given"]["chipTitle"]
    assert "a2-invented" not in output["given"]["chipClass"]
    css = (ROOT / "docs" / "assets" / "css" / "atoms2.css").read_text()
    assert ".a2-x-given {" in css and "background: var(--a2-k)" in css.split(".a2-x-given {", 1)[1].split("}", 1)[0]


@requires_node
def test_outcomes_and_unknown_provenance_remain_neutral() -> None:
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
function node(tag) { return {tag, attrs:{}, children:[], classList:{add(){}},
  setAttribute(key,value){this.attrs[key]=value}, getAttribute(key){return this.attrs[key]},
  hasAttribute(key){return key in this.attrs}, appendChild(child){this.children.push(child)},
  get childNodes(){return this.children},
  get textContent(){return this.children.map(child=>child.textContent).join('')},
  set textContent(value){this.children=[{textContent:String(value)}]}}; }
globalThis.document = {readyState:'loading', createElement:node, createElementNS:(_,tag)=>node(tag),
  createTextNode:text=>({textContent:text}), addEventListener(){}, querySelectorAll:()=>[]};
const A2 = require(process.argv[1] + '/kit.js');
const expression = 'eq(Ok(Roads<1, Pair<Int, Int>>), Bottom(blocked), Unknown(resource), ~to_frac(x))';
for (const options of [undefined, {given:null}, {given:[]}, {given:['Roads','Ok','Pair','Int']}]) {
  const rendered = A2.expr(expression, options);
  assert.equal(rendered.textContent, expression);
  const outcomes = rendered.children.filter(child=>child.className==='a2-x-outcome');
  assert.deepEqual(outcomes.map(child=>child.textContent), [
    'Ok(Roads<1, Pair<Int, Int>>)', 'Bottom(blocked)', 'Unknown(resource)']);
  assert.equal(rendered.children.some(child=>child.attrs && child.attrs['data-origin']==='invented'), false);
  assert.deepEqual(rendered.children.filter(child=>child.attrs && child.attrs['data-origin']).map(child=>child.attrs['data-origin']), ['neutral','neutral']);
}
const known = A2.expr('Roads ~to_frac(x)', {given:['Roads'], invented:['~to_frac']});
assert.deepEqual(known.children.filter(child=>child.attrs && child.attrs['data-origin']).map(child=>child.attrs['data-origin']), ['given','invented']);
assert.equal(known.textContent, 'Roads ~to_frac(x)');
const constructors = A2.expr('Ok Bottom Unknown', {given:['Ok','Bottom','Unknown']});
assert.equal(constructors.textContent, 'Ok Bottom Unknown');
assert.deepEqual(constructors.children.filter(child=>child.attrs).map(child=>child.className),
  ['a2-x-outcome','a2-x-outcome','a2-x-outcome']);
const staticCode = node('code');
staticCode.textContent = 'Roads ~to_frac(x) Ok(Roads<1>)';
staticCode.attrs['data-a2-given'] = 'Roads';
staticCode.attrs['data-a2-invented'] = '~to_frac';
document.querySelectorAll = selector => selector==='code[data-a2-expr]' ? [staticCode] : [];
A2.scan();
assert.equal(staticCode.textContent, 'Roads ~to_frac(x) Ok(Roads<1>)');
assert.deepEqual(staticCode.children.filter(child=>child.attrs && child.attrs['data-origin']).map(child=>child.attrs['data-origin']),
  ['given','invented']);
A2.scan();
assert.equal(staticCode.textContent, 'Roads ~to_frac(x) Ok(Roads<1>)');
'''
    subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)
    css = (ROOT / "docs" / "assets" / "css" / "atoms2.css").read_text()
    assert ".a2-x-neutral {" in css and "border: 0" in css.split(".a2-x-neutral {", 1)[1].split("}", 1)[0]


@requires_node
def test_six_kind_declarations_only_style_syntactic_identifiers() -> None:
    script = r'''
globalThis.window = globalThis;
function node(tag) { return {tag, attrs:{}, children:[], classList:{add(){}},
  setAttribute(key,value){this.attrs[key]=value}, getAttribute(key){return this.attrs[key]},
  hasAttribute(key){return key in this.attrs}, removeAttribute(key){delete this.attrs[key]},
  appendChild(child){this.children.push(child)}, get childNodes(){return this.children},
  get textContent(){return this.children.map(child=>child.textContent).join('')},
  set textContent(value){this.children=[{textContent:String(value)}]}}; }
const code = node('code');
code.textContent = 'law #assoc_count: eq(?parse_count{w}, catalan(binary_ops(w))) for w: Word where unparenthesized(w) L5';
const legendHost = node('div'); legendHost.attrs['data-a2']='legend';
globalThis.document = {readyState:'loading', createElement:node, createElementNS:(_,tag)=>node(tag), createTextNode:text=>({textContent:text}),
  addEventListener(){}, querySelectorAll(selector){return selector==='code[data-a2-expr]'?[code]:selector==='[data-a2]'?[legendHost]:[]}};
const A2 = require(process.argv[1] + '/kit.js');
const grammar = require(process.argv[2]);
const declarations = grammar.cards.map(card=>card.definition);
function tokens(expression){const result=[];function walk(child){
  if(child.attrs && child.attrs['data-kind']) result.push([child.textContent,child.attrs['data-kind']]);
  if(child.children) child.children.forEach(walk);
}walk(expression);return result;}
const results = declarations.map(text=>({same:A2.expr(text).textContent===text,
  kinds:tokens(A2.expr(text)), keywords:A2.expr(text).children.filter(child=>child.className==='a2-x-keyword').map(child=>child.textContent)}));
const syntax = 'obj A given op f(a) comb @slot[f](a) obs ?see{a} law #valid for a: Int and sealed where canon bridge ~carry(a)';
const syntaxResult = A2.expr(syntax);
const first = code.textContent;
A2.scan();const enhanced = {text:code.textContent, kinds:tokens(code), ready:code.attrs['data-a2-expr-ready']};
const count = code.children.length;
A2.scan();enhanced.idempotent=code.textContent===first && code.children.length===count;
console.log(JSON.stringify({results, enhanced, legend:A2.legend().textContent, legendMount:legendHost.textContent,
  syntax:syntaxResult.textContent,
  syntaxKinds:tokens(syntaxResult), syntaxKeywords:syntaxResult.children.filter(child=>child.className==='a2-x-keyword').map(child=>child.textContent)}));
'''
    grammar = ROOT / "docs" / "assets" / "data" / "atoms2" / "grammar.json"
    result = subprocess.run([NODE, "-e", script, str(JS), str(grammar)], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert all(item["same"] for item in output["results"])
    kinds = [list(map(tuple, item["kinds"])) for item in output["results"]]
    assert ("ExprTree", "object") in kinds[0]
    assert ("split", "operation") in kinds[1]
    assert ("@chart", "combinator") in kinds[2]
    assert ("?parse_count", "observation") in kinds[3]
    assert ("#assoc_count", "law") in kinds[4]
    assert ("~to_rpn", "bridge") in kinds[5]
    assert ("w", "operation") not in kinds[1] + kinds[2] + kinds[3] + kinds[4]
    assert ("t", "operation") not in kinds[0] + kinds[5]
    assert not any(name in {"obj", "op", "comb", "obs", "law", "bridge", "where", "for", "and", "canon", "sealed", "given"}
                   for item in kinds for name, _ in item)
    assert "law" in output["results"][4]["keywords"]
    assert output["enhanced"]["text"].startswith("law #assoc_count:")
    assert ("#assoc_count", "law") in list(map(tuple, output["enhanced"]["kinds"]))
    assert output["enhanced"]["ready"] == "1" and output["enhanced"]["idempotent"]
    assert output["syntax"].startswith("obj A given op f(a)")
    assert ("a", "operation") not in list(map(tuple, output["syntaxKinds"]))
    assert set(output["syntaxKeywords"]) == {"obj", "op", "comb", "obs", "law", "bridge", "where", "for", "and", "canon", "sealed", "given"}
    assert all(word in output["legend"] for word in ("Object", "Operation", "Combinator", "Observation", "Law", "Bridge", "Filled: given"))
    assert output["legendMount"] == output["legend"]


@requires_node
def test_chip_colour_contrast_contract() -> None:
    stylesheet = (ROOT / "docs" / "assets" / "css" / "atoms2.css").read_text()
    light = ["1a7b46", "bb4219", "3f5bd8", "a8329e", "59625b", "7443a7"]
    dark = ["5fd68f", "ff8f64", "99aaff", "ea8ee1", "b4c1b9", "c0a0f3"]

    def luminance(hex_colour: str) -> float:
        channels = [int(hex_colour[index:index + 2], 16) / 255 for index in (0, 2, 4)]
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
                  for channel in channels]
        return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))

    for index, colour in enumerate(light):
        assert f"#{colour}" in stylesheet
        assert (1.05 / (luminance(colour) + .05)) >= 4.5
    for colour in dark:
        assert f"#{colour}" in stylesheet
        assert (luminance(colour) + .05) / (luminance("0f172a") + .05) >= 4.5
    assert ".a2-chip:not(.a2-invented), .a2-tok-given { background: var(--a2-k);" in stylesheet
    assert ".a2-tok-invented { background: transparent; }" in stylesheet
    assert ".a2-learn-app button.a2-tok { border-color: var(--a2-k); color: var(--a2-k);" in stylesheet
    assert ".a2-tok.a2-k-law { border-style: double; border-width: 3px; border-radius: 2px; }" in stylesheet


def test_kind_shapes_and_learn_accents_do_not_depend_on_colour_alone() -> None:
    stylesheet = (ROOT / "docs/assets/css/atoms2.css").read_text()
    for kind in ("object", "operation", "combinator", "observation", "law", "bridge"):
        assert f".a2-x.a2-k-{kind}" in stylesheet
        assert f".a2-tok.a2-k-{kind}" in stylesheet
    assert '.a2-k-observation:is(.a2-tok, .a2-x)::before' in stylesheet
    assert '.a2-chip.a2-k-object::before, .a2-tok.a2-k-object::before' in stylesheet
    for kind in ("law", "bridge"):
        assert f'.a2-learn-app .a2-learn-card[data-kind="{kind}"]' in stylesheet
        assert f'var(--a2-{kind})' in stylesheet.split(f'.a2-learn-app .a2-learn-card[data-kind="{kind}"]', 1)[1].split('}', 1)[0]
        assert f'.a2-k-{kind}:is(.a2-tok, .a2-x) {{ --a2-k: var(--a2-{kind}); }}' in stylesheet


@requires_node
def test_kernel_export_is_only_trace_source() -> None:
    script = r'''
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
const mock = require(process.argv[1] + '/../../../../tests/fixtures/atoms2-mock.js');
console.log(JSON.stringify({same: mock.derivations === A2.kernelData.derivations,
  cost: A2.kernelData.runs.mul_3_4.steps, manual: typeof mock.build.mulTree,
  law: mock.find('#mul_comm','integer')?.kind, lemma: mock.find('#gcd_lin','integer')?.kind,
  bridge: mock.find('~to_frac','integer')?.kind, template: mock.find('Quot','integer')?.spec.template,
  frac: mock.find('Frac','integer')?.depends_on, hour: mock.find('Hour','clock')?.depends_on,
  integerHeads: mock.layer0('integer').filter(item => ['head','tail','is_nil'].includes(item.name)).length}));
'''
    result = subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert output == {"same": True, "cost": 13, "manual": "undefined", "law": "law", "lemma": "law",
                      "bridge": "bridge", "template": True, "frac": ["Int", "gcd", "neg", "mul", "Quot"],
                      "hour": ["Quot"], "integerHeads": 0}


@requires_node
def test_plain_values_use_copyable_ascii_object_names() -> None:
    script = r'''
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
const mock = require(process.argv[1] + '/../../../../tests/fixtures/atoms2-mock.js');
console.log(JSON.stringify({fraction:A2.formatValue(mock.build.frac(2,4)),
  list:A2.formatValue(mock.build.list([1,2,3])), empty:A2.formatValue(mock.build.list([])),
  failure:A2.formatValue({bottom:'blocked'}), unknown:A2.formatValue({unknown:'fuel'}),
  text:A2.formatValue({t:'str',v:'é'}), hostText:A2.formatValue('line\nnext'),
  tagged:A2.formatValue({t:'robot_state',tag:'robot',f:[]}),
  boolean:A2.formatValue({t:'bool',tag:'true',f:[]})}));
'''
    result = subprocess.run([NODE, "-e", script, str(JS)], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {"fraction": "Frac<2, 4>", "list": "List<1, 2, 3>",
                                         "empty": "List<>", "failure": "Bottom(blocked)", "unknown": "Unknown(fuel)",
                                         "text": '"\\u00e9"', "hostText": '"line\\nnext"',
                                         "tagged": "RobotState.robot<>", "boolean": "true"}


@requires_node
def test_shared_values_render_without_mock_fixture() -> None:
    script = r'''
globalThis.window = globalThis;
function node(tag) { return {tag, attrs:{}, children:[], setAttribute(key,value){this.attrs[key]=value},
  appendChild(child){this.children.push(child)}, get textContent(){return this.children.map(child=>child.textContent).join('')},
  set textContent(text){this.children=[{textContent:String(text)}]}}; }
globalThis.document = {readyState:'loading', createElement:node, createElementNS:(_,tag)=>node(tag),
  createTextNode:text=>({textContent:text}), addEventListener(){}, querySelectorAll:()=>[]};
const A2 = require(process.argv[1] + '/kit.js');
const frac = {t:'fraction',tag:'fraction',f:[{t:'int',v:1},{t:'int',v:2}]};
const list = {t:'list[int]',tag:'cons',f:[{t:'int',v:1},{t:'list[int]',tag:'nil',f:[]}]};
console.log(JSON.stringify({fraction:A2.formatValue(frac),list:A2.formatValue(list),
  failure:A2.value({bottom:'blocked'}).textContent}));
'''
    result = subprocess.run([NODE, "-e", script, str(JS)], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == {"fraction": "Frac<1, 2>", "list": "List<1>",
                                         "failure": "Bottom(blocked)"}


@requires_node
def test_world_export_value_shapes_render_without_object_coercion() -> None:
    world_files = sorted((ROOT / "docs/assets/data/worlds_v2").rglob("*.json"))
    assert world_files
    shapes: dict[tuple[str, ...], object] = {}
    def scan(value: object) -> None:
        if isinstance(value, dict):
            shape = tuple(sorted(value))
            if ("codec" not in value and any(key in value for key in
                                             ("repr", "elided_value", "t", "ok", "bottom", "unknown"))
                    and (shape not in shapes or len(json.dumps(value)) < len(json.dumps(shapes[shape])))):
                    shapes[shape] = value
            for child in value.values():
                scan(child)
        elif isinstance(value, list):
            for child in value:
                scan(child)

    for world_file in world_files:
        export = json.loads(world_file.read_text())
        scan({key: value for key, value in export.items() if key != 'notation3'})
    assert shapes.keys() <= {("repr",), ("chars", "elided_value"), ("busy", "stock", "t"), ("t", "v"),
                             ("f", "t", "tag"), ("ok",), ("bottom",), ("unknown",)}
    assert {("repr",), ("chars", "elided_value"), ("busy", "stock", "t"), ("t", "v"), ("f", "t", "tag"),
            ("ok",), ("bottom",)} <= shapes.keys()
    script = r'''
globalThis.window = globalThis;
function node(tag) { return {tag, children:[], setAttribute(){}, appendChild(child){this.children.push(child)},
  get textContent(){return this.children.map(child=>child.textContent).join('')},
  set textContent(text){this.children=[{textContent:String(text)}]}}; }
globalThis.document = {readyState:'loading', createElement:node, createElementNS:(_,tag)=>node(tag),
  createTextNode:text=>({textContent:text}), addEventListener(){}, querySelectorAll:()=>[]};
const A2 = require(process.argv[1] + '/kit.js');
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  const values = JSON.parse(input);
  console.log(JSON.stringify(Object.fromEntries(Object.entries(values).map(([shape, sample]) =>
    [shape, {plain:A2.formatValue(sample), dom:A2.value(sample).textContent}]))));
});
'''
    samples = {",".join(shape): value for shape, value in shapes.items()}
    samples.update({"unicode repr": {"repr": "State<é>"},
                    "unicode elision": {"elided_value": "état"},
                    "count only": {"elided_value": "", "chars": 42},
                    "outcome repr": {"ok": shapes[("repr",)]},
                    "outcome elision": {"ok": shapes[("chars", "elided_value")]}})
    result = subprocess.run([NODE, "-e", script, str(JS)], input=json.dumps(samples),
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    for shape, forms in rendered.items():
        assert "[object Object]" not in forms["plain"], shape
        assert "[object Object]" not in forms["dom"], shape
        assert forms["plain"].isascii() and forms["dom"].isascii(), shape
    for shape in (("repr",), ("chars", "elided_value")):
        key = ",".join(shape)
        assert rendered[key]["dom"] == rendered[key]["plain"]
    assert rendered["repr"]["plain"] == shapes[("repr",)]["repr"]
    elided = shapes[("chars", "elided_value")]
    assert rendered["chars,elided_value"]["plain"] == (
        f"value elided ({elided['chars']} chars): {elided['elided_value']}")
    assert rendered["unicode repr"] == {"plain": "State<\\u00e9>", "dom": "State<\\u00e9>"}
    assert rendered["unicode elision"] == {"plain": "value elided: \\u00e9tat", "dom": "value elided: \\u00e9tat"}
    assert rendered["count only"] == {"plain": "value elided (42 chars)", "dom": "value elided (42 chars)"}
    assert rendered["outcome repr"] == rendered["repr"]
    assert rendered["outcome elision"] == rendered["chars,elided_value"]


@requires_node
def test_charged_leaves_on_nested_and_kernel_traces() -> None:
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
const A2 = require(process.argv[1] + '/kit.js');
require(process.argv[1] + '/data.js');
assert.equal(A2.chargedLeaves({children:[]}), 1);
assert.equal(A2.chargedLeaves({children:[{children:[]}, {children:[{},{}]}]}), 3);
for (const [key, trace] of Object.entries(A2.kernelData.modes.derivations))
  assert.equal(A2.chargedLeaves(trace.root), A2.kernelData.modes.runs[key].steps, key);
'''
    subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)


@requires_node
def test_published_play_preview_uses_its_own_definitions() -> None:
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
const A2 = require(process.argv[1] + '/kit.js');
const preview = require(process.argv[1] + '/lab-preview-world.js');
assert.equal(A2.mock, preview);
assert.equal(preview.find('mul','integer').kind,'operation');
assert.equal(preview.find('front_free','robot').kind,'observation');
assert.equal(preview.charged, A2.chargedLeaves);
assert.equal(preview.charged({children:[{}, {children:[{},{}]}]}), 3);
'''
    subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)


@requires_node
def test_motion_helpers_use_fake_clock_and_handle_reduced_motion() -> None:
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
let reduced = false, frames = [], timers = [];
globalThis.matchMedia = () => ({matches: reduced});
globalThis.requestAnimationFrame = callback => frames.push(callback);
globalThis.setTimeout = (callback, ms) => { timers.push({callback, ms}); };
const A2 = require(process.argv[1] + '/kit.js');
(async () => {
  let values = [], done = false;
  const tween = A2.tween(100, value => values.push(value), {ease: value => value}).then(() => done = true);
  frames.shift()(10); frames.shift()(60); frames.shift()(110);
  await tween;
  assert.deepEqual(values, [0, 0.5, 1]); assert.equal(done, true);
  const full = A2.wait(80); const fullTimer = timers.shift();
  assert.equal(fullTimer.ms, 80); fullTimer.callback(); await full;
  const waiting = A2.wait(40).then(() => done = true);
  const timer = timers.shift(); assert.equal(timer.ms, 40); timer.callback(); await waiting;
  assert.equal(done, true);
  const animations = [];
  function node(key, left) { return {left, getAttribute: () => key,
    getBoundingClientRect() {return {left:this.left,top:0};},
    animate(keys, options) {animations.push({keys,options}); return {};}}; }
  const moved = node('moved', 0), added = node('new', 9);
  const container = {nodes:[moved],querySelectorAll(){return this.nodes;}};
  const flip = A2.flip(container, () => { moved.left = 12; container.nodes.push(added); }, {ms:25,stagger:5});
  assert.equal(animations.length, 2);
  assert.equal(animations[0].keys[0].transform, 'translate(-12px,0px)');
  assert.equal(animations[1].options.delay, 5);
  const flipTimer = timers.shift(); assert.equal(flipTimer.ms, 25); flipTimer.callback(); await flip;
  let animation;
  const traveler = {animate(keys, options){animation = {keys,options}; return animation;}};
  const finish = A2.travel(traveler,{left:1,top:2},{left:11,top:22},31);
  assert.equal(animation.keys[0].transform,'translate(-10px,-20px)');
  assert.equal(animation.options.duration,31); animation.onfinish(); await finish;
  const cancel = A2.travel(traveler,{left:0,top:0},{left:1,top:1});
  assert.equal(animation.options.duration,A2.DUR.travel); animation.oncancel(); await cancel;
  reduced = true;
  values = []; await A2.tween(100, value => values.push(value)); assert.deepEqual(values,[1]);
  let mutation = false;
  await A2.flip(container, () => mutation = true); assert.equal(mutation,true);
  assert.equal(animations.length,2);
  await A2.travel(traveler,{left:0,top:0},{left:1,top:1});
  const short = A2.wait(30); const shortTimer = timers.shift();
  assert.equal(shortTimer.ms,0); shortTimer.callback(); await short;
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([NODE, "-e", script, str(JS)], capture_output=True, text=True, check=True)
