"""Definition workshop parser, checker, evaluator and lifecycle preview."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_workshop_tabs_use_one_shared_kind_icon():
    script = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    styles = (ROOT / "docs/assets/css/atoms2-define.css").read_text()
    assert '[A2.icon(name), A2.KIND6_META[name].word]' in script
    assert '.a2-define-tab.a2-k-law::before' not in styles
    assert '.a2-define-tab.a2-k-bridge::before' not in styles
    assert '.a2-define-shelf .a2-tok-given { color: var(--a2-chip-ink); }' in styles


@requires_node
def test_workshop_use_defaults_to_edited_operation_and_reuses_it():
    source = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    assert 'value: "multiply_preview(13, 17)"' in source
    assert 'kind === "operation" ? "multiply_preview(13, 17)"' in source
    assert 'current.parsed.params.length === 2 ? "(13, 17)"' in source
    assert 'expression.value = current.parsed.name + (current.parsed.params.length === 2 ? "(13, 17)" : "(13)")' in source
    assert 'library.filter(function (entry) { return entry.world !== world || entry.name !== preview.name; }).concat(preview)' in source
    use_handler = source[source.index('    function use() {'):source.index('    useButton.addEventListener("click", use);')]
    assert 'var current = pending.pop()' not in use_handler
    data = run_preview("""
const preview = api.pipeline('op multiply_preview(a, b) = add(a, b) L1', 'operation', 'integer', {});
const library = api.storeSession([], preview.record, []).library;
const used = api.evaluate(api.parse('preview_use = multiply_preview(13, 17) L1', 'operation'),
  'operation', 'integer', [], [preview.record], {fuel: 300, layer: 1});
console.log(JSON.stringify({result: used.result, definition: used.tree.children[0].def,
  stored: library[0].name,
  hashLength: preview.record.content_hash.length}));
""")
    assert data == {"result": 30, "definition": "multiply_preview", "stored": "multiply_preview", "hashLength": 64}


def run_preview(script):
    setup = """
globalThis.window = globalThis;
const base = process.argv[1];
for (const name of ['kit', 'lab-preview-world', 'boundary', 'define']) require(base + '/' + name + '.js');
const api = A2.define;
"""
    result = subprocess.run(
        [NODE, "-e", setup + script, str(ROOT / "docs/assets/js/atoms2")],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


@requires_node
def test_colliding_sources_get_full_sha256_and_detach_transitive_evidence():
    data = run_preview("""
const crypto = require('crypto');
const sources = [
  'op f(a) = add(a, 8918874225872) L1',
  'op f(a) = add(a, 3526672943457) L1',
  'obj ByteCase = mod(398134173867, 256) L1',
  'obj ByteCase = mod(228346510649, 256) L1'
];
const first = api.pipeline(sources[0], 'operation', 'integer', {});
let library = api.storeSession([], first.record, []).library;
const dependent = api.pipeline('op use_f(a) = f(a) L2', 'operation', 'integer', {library});
library = api.storeSession(library, dependent.record, []).library;
const before = library.find(item => item.name === 'use_f').content_hash;
const second = api.pipeline(sources[1], 'operation', 'integer', {library});
const detached = [];
library = api.storeSession(library, second.record, detached).library;
const objectFirst = api.pipeline(sources[2], 'object', 'integer', {});
const objectSecond = api.pipeline(sources[3], 'object', 'integer', {});
const entries = [first, second, objectFirst, objectSecond];
console.log(JSON.stringify({ hashes: entries.map(item => item.record.content_hash),
  expected: entries.map((item, index) => crypto.createHash('sha256').update(JSON.stringify([
    sources[index], item.record.kind, item.record.world,
    item.record.depends_on.map(name => [name, 'given'])])).digest('hex')),
  detached: detached.map(item => item.name), before,
  after: library.find(item => item.name === 'use_f') }));
""")
    assert data["hashes"] == data["expected"]
    assert all(len(value) == 64 for value in data["hashes"])
    assert data["hashes"][0] != data["hashes"][1]
    assert data["hashes"][2] != data["hashes"][3]
    assert "use_f" in data["detached"]
    assert data["after"]["content_hash"] != data["before"]
    assert data["after"]["evidence"] is None


@requires_node
def test_evaluation_without_reference_cannot_claim_verified():
    data = run_preview("""
const evaluated = api.pipeline('op shift(a) = add(a, 11) L1', 'operation', 'integer', {});
const compared = api.pipeline('op shift(a) = add(a, 11) L1', 'operation', 'integer', {reference: 'succ'});
const law = api.pipeline('law #truth(a) = eq(a, a) L1', 'law', 'integer', {});
console.log(JSON.stringify({status: evaluated.record.status, detail: evaluated.stations[4].detail,
  checks: evaluated.evidence.checks, compared: compared.record && compared.record.status,
  law: law.record.status, lawDetail: law.stations[0].detail}));
""")
    assert data["status"] == "evaluated (no reference check)"
    assert "no reference check" in data["detail"].lower()
    assert data["checks"] == ["evaluation_only"]
    assert data["law"] == "written"
    assert "syntax and sorts only" in data["lawDetail"]
    workshop = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    lab = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    assert '"Check syntax, sorts and layers for " + kind' in workshop
    assert "Law and bridge drafts check syntax, sorts and layers only." in lab
    assert "check a six-kind definition" not in lab.lower()


@requires_node
def test_hidden_invalid_sample_seed_does_not_block_exhaustive_preview():
    data = run_preview("""
const source = 'op plus_one(a) = succ(a) L1';
const options = {method: 'exhaustive', seed: Number('bad')};
const exhaustive = api.pipeline(source, 'operation', 'integer', options);
const sampled = api.pipeline(source, 'operation', 'integer', {...options, method: 'sampled'});
console.log(JSON.stringify({exhaustive: exhaustive.record && exhaustive.record.evidence,
  exhaustiveError: exhaustive.error, sampledError: sampled.error}));
""")
    assert data["exhaustiveError"] is None
    assert data["exhaustive"]["method"] == "exhaustive"
    assert data["exhaustive"]["seed"] is None
    assert "Seed must be an integer" in data["sampledError"]


@requires_node
def test_restoring_identical_record_does_not_detach_evidence_or_descendants():
    data = run_preview("""
const detached = [];
let library = [];
for (const source of ['op lift(a) = succ(a) L1', 'op downstream(a) = lift(a) L2']) {
  const preview = api.pipeline(source, 'operation', 'integer', {library});
  if (preview.error) throw Error(preview.error);
  library = api.storeSession(library, preview.record, detached).library;
}
const before = library.find(item => item.name === 'downstream');
const again = api.pipeline('op lift(a) = succ(a) L1', 'operation', 'integer', {library});
const stored = api.storeSession(library, again.record, detached);
const after = stored.library.find(item => item.name === 'downstream');
console.log(JSON.stringify({sameHash: library.find(item => item.name === 'lift').content_hash === again.record.content_hash,
  replaced: stored.replaced, detached, before: [before.content_hash, !!before.evidence],
  after: [after.content_hash, !!after.evidence]}));
""")
    assert data["sameHash"]
    assert data["replaced"] is False
    assert data["detached"] == []
    assert data["before"] == data["after"]


@requires_node
def test_all_workshop_presets_parse_with_their_selected_kind():
    data = run_preview("""
const results = {};
for (const kind of ['object', 'operation', 'combinator', 'observation', 'law', 'bridge']) {
  results[kind] = api.presetsFor(kind).map(preset => {
    try { return [preset.label, api.parse(preset.source, kind).name]; }
    catch (error) { return [preset.label, error.message]; }
  });
}
console.log(JSON.stringify(results));
""")
    for kind, presets in data.items():
        assert all(not name.startswith("Line ") for _, name in presets), (kind, presets)
    assert [name for label, name in data["combinator"] if label == "Four applications"] == ["@fourfold"]


@requires_node
def test_replacing_own_session_definition_detaches_old_evidence_and_rechecks():
    data = run_preview("""
const first = api.pipeline('op plus_one(a) = succ(a) L1', 'operation', 'integer', {reference: 'succ'});
const detached = [];
let library = api.storeSession([], first.record, detached).library;
const second = api.pipeline('op plus_one(a) = add(a, 2) L1', 'operation', 'integer', {library, reference: 'succ'});
const replacement = api.pipeline('op plus_one(a) = add(a, 2) L1', 'operation', 'integer', {library});
const stored = api.storeSession(library, replacement.record, detached);
library = stored.library;
const use = api.parse('op call(a) = plus_one(a) L2', 'operation');
const value = api.evaluate(use, 'operation', 'integer', [11], library).result;
const sameNameReference = api.pipeline('op plus_one(a) = succ(a) L1', 'operation', 'integer', {library, reference: 'plus_one'});
const worldAtom = api.pipeline('op mul(a, b) = add(a, b) L1', 'operation', 'integer', {library});
console.log(JSON.stringify({first: first.record, failed: second.error, replacement: replacement.record,
  stored: stored.replaced, library: library.map(item => item.content_hash), detached, value,
  sameNameReference: sameNameReference.error, worldAtom: worldAtom.error}));
""")
    assert data["first"]["status"] == "previewed"
    assert "counterexample" in data["failed"].lower()
    assert data["replacement"]["status"] == "evaluated (no reference check)"
    assert data["first"]["content_hash"] != data["replacement"]["content_hash"]
    assert data["first"]["id"] != data["replacement"]["id"]
    assert data["stored"] is True
    assert data["library"] == [data["replacement"]["content_hash"]]
    assert data["detached"] == [{"world": "integer", "name": "plus_one", "content_hash": data["first"]["content_hash"], "evidence": data["first"]["evidence"]}]
    assert data["replacement"]["evidence"]["checks"] == ["evaluation_only"]
    assert data["value"] == 13
    assert "itself as a reference" in data["sameNameReference"]
    assert "already names" in data["worldAtom"]


@requires_node
def test_replacing_session_definition_detaches_transitive_evidence_and_rehashes():
    data = run_preview("""
const detached = [];
let library = [];
for (const source of [
  'op lift_two(a) = add(a, 2) L1',
  'op downstream(a) = lift_two(a) L2',
  'op further(a) = downstream(a) L3'
]) {
  const checked = api.pipeline(source, 'operation', 'integer', {library});
  if (checked.error) throw Error(checked.error);
  library = api.storeSession(library, checked.record, detached).library;
}
const before = library.map(item => ({name: item.name, hash: item.content_hash, evidence: !!item.evidence}));
const call = api.parse('op call(a) = further(a) L4', 'operation');
const oldValue = api.evaluate(call, 'operation', 'integer', [13], library).result;
const replacement = api.pipeline('op lift_two(a) = add(a, 3) L1', 'operation', 'integer', {library});
if (replacement.error) throw Error(replacement.error);
const priorLibrary = library;
library = api.storeSession(library, replacement.record, detached).library;
const oldLibraryIntact = priorLibrary.every(item => item.evidence && before.find(old => old.name === item.name).hash === item.content_hash);
const after = library.map(item => ({name: item.name, hash: item.content_hash, evidence: !!item.evidence, status: item.status}));
const newValue = api.evaluate(call, 'operation', 'integer', [13], library).result;
const recheckedDownstream = api.pipeline('op downstream(a) = lift_two(a) L2', 'operation', 'integer', {library});
console.log(JSON.stringify({before, after, detached: detached.map(item => item.name), oldValue, newValue,
  recheckedHash: recheckedDownstream.record && recheckedDownstream.record.content_hash, oldLibraryIntact}));
""")
    assert data["oldValue"] == 15
    assert data["newValue"] == 16
    before_by_name = {item["name"]: item for item in data["before"]}
    after_by_name = {item["name"]: item for item in data["after"]}
    assert before_by_name.keys() == after_by_name.keys()
    assert all(before_by_name[name]["hash"] != after_by_name[name]["hash"] for name in before_by_name)
    assert all(item["evidence"] for item in data["before"])
    assert all(not after_by_name[name]["evidence"] for name in ["downstream", "further"])
    assert data["detached"] == ["lift_two", "downstream", "further"]
    assert data["recheckedHash"] == after_by_name["downstream"]["hash"]
    assert data["oldLibraryIntact"] is True


@requires_node
def test_four_kind_tower_observation_only_reads_granted_probes():
    data = run_preview("""
let library = [];
const stages = [
  ['object', 'obj Beacon = 83 L1'],
  ['operation', 'op signal(a) = if eq(a, Beacon) then 1 else 0 L2'],
  ['combinator', 'comb @twice_signal[f](x) = f(f(signal(x))) L3'],
  ['observation', 'obs ?clear_signal = not ?front_wall{} and not ?front_water{} L1']
];
const results = stages.map(([kind, source]) => {
  const checked = api.pipeline(source, kind, 'robot', {library});
  if (!checked.error) library = api.storeSession(library, checked.record, []).library;
  return {error: checked.error, status: checked.record && checked.record.status, depends_on: checked.record && checked.record.depends_on};
});
console.log(JSON.stringify(results));
""")
    assert all(not result["error"] and result["status"] == "evaluated (no reference check)" for result in data)
    assert data[3]["depends_on"] == ["front_wall", "front_water"]


def test_switching_back_from_write_only_kind_restores_verification_controls():
    source = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    assert 'selectKind("observation"); towerWorld = true;' in source
    assert 'verifyFields.hidden = writeOnly;' in source
    assert 'run.textContent = writeOnly ? "Parse definition" : "Run preview";' in source


def test_computer_controls_wait_for_fixture_before_toggle():
    source = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    assert 'toggle.addEventListener("click", function () { if (!fixture) return;' in source


@requires_node
def test_rechecking_same_source_with_new_settings_detaches_prior_evidence():
    data = run_preview("""
const source = 'op plus_one(a) = succ(a) L1';
const first = api.pipeline(source, 'operation', 'integer', {reference: 'succ'});
const detached = [];
const library = api.storeSession([], first.record, detached).library;
const rechecked = api.pipeline(source, 'operation', 'integer', {library, method: 'sampled', seed: 37});
const stored = api.storeSession(library, rechecked.record, detached);
console.log(JSON.stringify({first: first.record, rechecked: rechecked.record, detached,
  stored: stored.replaced, length: stored.library.length}));
""")
    assert data["first"]["content_hash"] == data["rechecked"]["content_hash"]
    assert data["stored"] is True
    assert data["length"] == 1
    assert data["detached"][0]["evidence"]["method"] == "exhaustive"
    assert data["rechecked"]["evidence"]["method"] == "sampled"
    assert data["rechecked"]["evidence"]["checks"] == ["evaluation_only"]


@requires_node
def test_refine_rejects_zero_denominator_even_with_vacuous_validity():
    data = run_preview("""
const source = 'obj BadRatio = refine {num: int, den: int} where eq(den, den) canon reduce L1';
const parsed = api.parse(source, 'object');
const run = api.pipeline(source, 'object', 'integer');
console.log(JSON.stringify({ status: run.record.status, cases: [[3, 0], [0, 0], [2, 4]].map(args => api.evaluate(parsed, 'object', 'integer', args).outcome) }));
""")
    assert data["cases"][:2] == [{"bottom": "div_zero"}, {"bottom": "div_zero"}]
    assert data["cases"][2]["ok"]["f"] == [{"t": "int", "v": 1}, {"t": "int", "v": 2}]
    assert data["status"] == "failed"


@requires_node
def test_invalid_canonical_representation_cannot_promote():
    data = run_preview("""
const source = 'obj InvalidHour = refine {value: int} where neq(value, 0) canon mod 12 L1';
const run = api.pipeline(source, 'object', 'integer');
const direct = api.evaluate(api.parse(source, 'object'), 'object', 'integer', [12]);
console.log(JSON.stringify({ status: run.record.status, error: run.error, verified: run.stations[3].ok, direct: direct.outcome }));
""")
    assert data["status"] == "failed"
    assert data["verified"] is False
    assert "Bottom(invalid)" in data["error"]
    assert data["direct"] == {"bottom": "invalid"}


@requires_node
def test_unrecognized_verification_method_fails_before_preview():
    data = run_preview("""
const run = api.pipeline('op new_succ(a) = succ(a) L1', 'operation', 'integer', {reference: 'succ', method: 'bogus'});
console.log(JSON.stringify({ status: run.record.status, error: run.error, promoted: run.stations[4].ok }));
""")
    assert data["status"] == "failed"
    assert "Unknown verification method" in data["error"]
    assert data["promoted"] is None


@requires_node
def test_previewed_call_outside_scope_unfolds_after_serialization():
    data = run_preview("""
const previewed = api.pipeline('op plus_one(a) = succ(a) L1', 'operation', 'integer', {reference: 'succ'});
const restored = JSON.parse(JSON.stringify(previewed.record));
const parsed = api.parse('op external(a) = plus_one(a) L2', 'operation');
const inside = api.evaluate(parsed, 'operation', 'integer', [9], [restored], {layer: 2});
const outside = api.evaluate(parsed, 'operation', 'integer', [-100], [restored], {layer: 2});
const insideRow = A2.boundary.cut(inside.tree, {depth: 2}).find(row => row.def === 'plus_one');
const outsideRow = A2.boundary.cut(outside.tree, {depth: 2}).find(row => row.def === 'plus_one');
console.log(JSON.stringify({status: restored.status, inside: insideRow.folded, outside: outsideRow.folded, marked: outside.tree.children[0].outsideCheckedScope, outcome: outside.outcome, scope: restored.evidence.scope.predicate.type}));
""")
    assert data == {"status": "previewed", "inside": True, "outside": False, "marked": True,
                    "outcome": {"ok": {"t": "int", "v": -99}}, "scope": "cases"}


@requires_node
def test_outside_scope_call_unfolds_every_folded_ancestor():
    data = run_preview("""
const previewed = api.pipeline('op plus_one(a) = succ(a) L1', 'operation', 'integer', {reference: 'succ'}).record;
const middle = api.parse('op middle(a) = plus_one(a) L2', 'operation');
const library = [previewed, {world:'integer', name:'middle', kind:'operation', origin:'invented', layer:2,
  spec:{params:['a'], inputs:[{sort:'int'}], output:{sort:'int'}}, body:middle.body}];
const outer = api.parse('op outer(a) = middle(a) L3', 'operation');
function rows(value) {
  const result = api.evaluate(outer, 'operation', 'integer', [value], library, {layer:3});
  return A2.boundary.cut(result.tree, {depth:4, keep_names:['outer','middle','plus_one']})
    .map(row => [row.def, row.opened, row.folded]);
}
console.log(JSON.stringify({inside:rows(9), outside:rows(-100)}));
""")
    assert data["inside"] == [["outer", False, True]]
    assert data["outside"][:3] == [["outer", True, False], ["middle", True, False],
                                   ["plus_one", True, False]]
    assert data["outside"][-1][0] == "succ"


@requires_node
def test_given_object_names_follow_capitalized_ascii_form():
    data = run_preview("""
const objects = A2.mock.defs.filter(def => def.kind === 'object' && def.origin === 'given');
const parsed = api.parse('op identity(a) = add(a, Zero) L1', 'operation');
const result = api.evaluate(parsed, 'operation', 'integer', [11]);
console.log(JSON.stringify({objects:objects.map(def => def.name), value:result.outcome, calls:result.tree.children.map(def => def.def)}));
""")
    assert data["objects"] == ["Int", "Zero", "Int", "Zero"]
    assert data["value"] == {"ok": {"t": "int", "v": 11}}
    assert data["calls"] == ["Zero", "add"]


@requires_node
def test_modulo_near_max_safe_integer_agrees_with_bigint():
    data = run_preview("""
const source = api.parse('op modulo(a, b) = mod(a, b) L1', 'operation');
const pairs = [[9007199254740990, 9007199254740991], [-9007199254740990, 9007199254740991], [9007199254740990, -9007199254740991]];
const results = pairs.map(pair => {
  const actual = api.evaluate(source, 'operation', 'integer', pair);
  const divisor = BigInt(pair[1]);
  const expected = Number(((BigInt(pair[0]) % divisor) + divisor) % divisor);
  return {actual: actual.outcome.ok && actual.outcome.ok.v, expected, steps: actual.steps};
});
const refine = api.evaluate(api.parse('obj Hour = refine {value: int} where eq(value, value) canon mod 12 L1', 'object'), 'object', 'integer', [-9007199254740990]);
console.log(JSON.stringify({results, refine: refine.outcome.ok.f[0].v,
  refineExpected: Number(((BigInt(-9007199254740990) % 12n) + 12n) % 12n)}));
""")
    assert all(result["actual"] == result["expected"] and result["steps"] == 1
               for result in data["results"])
    assert data["refine"] == data["refineExpected"]


@requires_node
def test_empty_unfolded_bodies_have_no_fabricated_given_call():
    data = run_preview("""
const definitions = ['constant(a) = 8 L1', 'identity(a) = a L1'];
const results = definitions.map((source, index) => {
  const name = index ? 'identity' : 'constant';
  const previewed = {world: 'integer', name, kind: 'operation', origin: 'invented',
    layer: 1, status: 'previewed', spec: {inputs: [{sort:'int'}], params: ['a'], output: {sort:'int'}},
    body: api.parse(source, 'operation').body,
    evidence: {scope: {predicate: {type: 'cases', cases: [[0]]}}}};
  const parsed = api.parse('op outside(a) = ' + name + '(a) L2', 'operation');
  return [0, 1].map(value => {
    const outcome = api.evaluate(parsed, 'operation', 'integer', [value], [previewed], {layer: 2});
    const unfolded = outcome.tree.children[0];
    return {steps: outcome.steps, emptyBody: unfolded.emptyBody, given: unfolded.given,
      children: unfolded.children.length, outside: unfolded.outsideCheckedScope,
      value: outcome.outcome.ok.v};
  });
});
console.log(JSON.stringify(results));
""")
    assert data == [
        [{"steps": 0, "emptyBody": True, "given": False, "children": 0, "outside": False, "value": 8},
         {"steps": 0, "emptyBody": True, "given": False, "children": 0, "outside": True, "value": 8}],
        [{"steps": 0, "emptyBody": True, "given": False, "children": 0, "outside": False, "value": 0},
         {"steps": 0, "emptyBody": True, "given": False, "children": 0, "outside": True, "value": 1}],
    ]


@requires_node
def test_seeded_cases_vary_by_seed_and_record_both_probe_dimensions():
    data = run_preview("""
const result = {};
for (const [kind, world] of [['combinator', 'integer'], ['observation', 'robot']]) {
  const parsed = api.parse(api.examples[kind].good, kind);
  result[kind] = [1, 42].map(seed => api.verify(parsed, kind, world, [], {method: 'sampled', seed}).evidence);
}
console.log(JSON.stringify(result));
""")
    for kind in ("combinator", "observation"):
        first, second = data[kind]
        assert first["seed"] == 1 and second["seed"] == 42
        assert first["scope"]["cases"] != second["scope"]["cases"]
    cases = data["observation"][0]["scope"]["cases"]
    assert {pair[0] for pair in cases} == {True, False}
    assert {pair[1] for pair in cases} == {True, False}


@requires_node
def test_binding_call_forms_and_tower_run_end_to_end():
    data = run_preview("""
const stages = [
  ['object', 'obj Beacon = 83 L1'],
  ['operation', 'op signal(a) = if eq(a, Beacon) then 1 else 0 L2'],
  ['combinator', 'comb @twice_signal[f](x) = f(f(signal(x))) L3'],
  ['observation', 'obs ?clear_signal = not ?front_wall{} and not ?front_water{} L1']
];
const library = [], states = [];
for (const [kind, source] of stages) {
  const result = api.pipeline(source, kind, 'robot', {library, method:'exhaustive'});
  states.push([result.error, result.record && result.record.status, result.record && result.record.layer]);
  if (!result.error) library.push(result.record);
}
const use = api.parse('preview_use = ?clear_signal{} L1', 'operation');
const output = api.evaluate(use, 'operation', 'robot', [], library, {probes:{front_wall:false, front_water:false}});
const blocked = api.evaluate(use, 'operation', 'robot', [], library, {probes:{front_wall:true, front_water:false}});
const chain = api.evaluate(api.parse('preview_use = @twice_signal[signal](Beacon) L1', 'operation'), 'operation', 'robot', [], library);
const invalidObservation = api.pipeline('obs ?bad = eq(@twice_signal[signal](Beacon), 0) L4', 'observation', 'robot', {library});
const invalidObjectObservation = api.pipeline('obs ?bad_obj = eq(Beacon, 0) L2', 'observation', 'robot', {library});
const twice = api.pipeline(api.examples.combinator.good, 'combinator', 'integer');
const twiceUse = api.evaluate(api.parse('preview_use = @twice_preview[succ](11) L1', 'operation'), 'operation', 'integer', [], [twice.record]);
const seedCases = [1, 7, 999].map(seed => api.verify(api.parse(api.examples.combinator.good, 'combinator'), 'combinator', 'integer', [], {method:'sampled', seed}).evidence.scope.cases);
const errors = ['comb @old(f, x) = f(x) L1', 'obs ?old = ?front_wall L1'].map((source, index) => {
  try { api.parse(source, index ? 'observation' : 'combinator'); return null; } catch (error) { return error.message; }
});
const bare = api.pipeline('obs ?bare = not front_wall L1', 'observation', 'robot');
console.log(JSON.stringify({states, output:output.outcome, blocked:blocked.outcome, chain:chain.outcome,
  invalidObservation:invalidObservation.error, invalidObjectObservation:invalidObjectObservation.error,
  twice:twiceUse.outcome, seedCases, errors, bare:bare.error}));
""")
    assert data["states"] == [[None, "evaluated (no reference check)", 1], [None, "evaluated (no reference check)", 2],
                              [None, "evaluated (no reference check)", 3], [None, "evaluated (no reference check)", 1]]
    assert data["output"] == {"ok": {"t": "bool", "tag": "true", "f": []}}
    assert data["blocked"] == {"ok": {"t": "bool", "tag": "false", "f": []}}
    assert data["chain"] == {"ok": {"t": "int", "v": 0}}
    assert "This browser preview supports only probes and observations" in data["invalidObservation"]
    assert "the 0.5 core also permits pure definitions" in data["invalidObjectObservation"]
    assert data["twice"] == {"ok": {"t": "int", "v": 13}}
    assert len({json.dumps(cases) for cases in data["seedCases"]}) == 3
    assert all(data["errors"])
    assert "?front_wall{}" in data["bare"]


def test_fuel_input_removes_old_result_and_preview_starts_at_first_station():
    lab = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    define = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    assert 'fuel.addEventListener("input", function () {' in lab
    assert 'results = [];' in lab and 'machines.replaceChildren();' in lab
    assert 'previous results are stale' in lab
    assert 'options()); frame = 1;' in define
    assert 'playing = true; play.textContent = "Pause"; timer = setTimeout(advance, 700);' in define
    assert 'opulse.atoms.laws.verify_law and replay_rewrite' in define
    assert 'opulse.atoms.bridges.verify_bridge' in define

SCRIPT = r"""
globalThis.window = globalThis;
const base = process.argv[1];
require(base + '/kit.js');
require(base + '/lab-preview-world.js');
require(base + '/boundary.js');
const api = require(base + '/define.js');
const out = {};
out.nodes = {
  mul: api.parse(api.examples.operation.good, 'operation').body,
  three: api.parse(api.examples.object.good, 'object').body,
  fraction: api.parse(api.examples.object.refine, 'object').refine,
  twice: api.parse(api.examples.combinator.good, 'combinator').body,
  front_free: api.parse(api.examples.observation.good, 'observation').body,
  let: api.parse('increment(a) = let x = succ(a) in x L1', 'operation').body,
};
out.errors = [];
for (const source of ['bad(a) = add(a,', 'bad(a) = @', 'bad(a) = if is_zero(a) then 0']) {
  try { api.parse(source, 'operation'); out.errors.push(null); } catch (error) { out.errors.push(error.message); }
}
out.mul = api.pipeline(api.examples.operation.good, 'operation', 'integer', {reference: 'mul', sample: [3, 4]});
out.wrong = api.pipeline('wrong(a, b) = add(a, b) L1', 'operation', 'integer', {reference: 'mul'});
out.sampled = api.pipeline(api.examples.operation.good, 'operation', 'integer', {method: 'sampled', reference: 'mul'});
out.fuel = api.pipeline(api.examples.operation.fuel, 'operation', 'integer');
out.unbound = api.pipeline(api.examples.operation.bad, 'operation', 'integer');
out.sealed = api.pipeline(api.examples.observation.bad, 'observation', 'robot');
out.arity = api.pipeline('bad(a) = add(a) L1', 'operation', 'integer');
out.three = api.pipeline(api.examples.object.good, 'object', 'integer');
out.fraction = api.pipeline(api.examples.object.refine, 'object', 'integer');
out.twice = api.pipeline(api.examples.combinator.good, 'combinator', 'integer', {reference: 'twice'});
out.probe = api.pipeline(api.examples.observation.good, 'observation', 'robot');
out.dep = api.pipeline('plus_eighty_three(a) = add(a, Byte83) L2', 'operation', 'integer', {library: [out.three.record]});
out.tree = api.evaluate(api.parse(api.examples.operation.good, 'operation'), 'operation', 'integer', [3, 4]);
out.genericReference = api.pipeline('increment(a) = succ(a) L1', 'operation', 'integer', {reference: 'succ'});
out.missingReference = api.pipeline('increment(a) = succ(a) L1', 'operation', 'integer', {reference: 'not_defined'});
out.restricted = api.pipeline(api.examples.observation.good, 'observation', 'robot', {grantedProbes: ['front_wall']});
out.derivedProbe = api.pipeline('obs ?still_free = not ?front_free{} L2', 'observation', 'robot');
out.slot = api.pipeline('@wrong_twice[f](x) = add(f, x) L1', 'combinator', 'integer');
out.mod = api.pipeline('hour = refine {value: int} where eq(value, value) canon mod 12 L1', 'object', 'integer');
out.modInvalid = api.pipeline('hour_bad = refine {value: int} where neq(value, 0) canon mod 12 L1', 'object', 'integer');
out.boolAsInt = api.pipeline('flag(a) = is_zero(a) L1', 'operation', 'integer');
out.closed = api.pipeline('constant = add(11, 13) L1', 'object', 'integer');
out.shadow = api.pipeline('add(a, b) = 0 L1', 'operation', 'integer', {reference: 'add'});
out.shadowSession = api.pipeline('inc(a) = 0 L1', 'operation', 'integer', {library: [{name: 'inc', kind: 'operation', world: 'integer'}], reference: 'inc'});
out.unsafeInput = api.evaluate(api.parse('increment(a) = add(a, 1) L1', 'operation'), 'operation', 'integer', [9007199254740992]);
out.unsafeLiteral = api.pipeline('unsafe = 9007199254740993 L1', 'object', 'integer');
out.law = api.pipeline(api.examples.law.good, 'law', 'integer');
out.bridge = api.pipeline(api.examples.bridge.good, 'bridge', 'integer');
out.invalidSigils = ['op ?pretend(a) = a L1', 'obj @wrong = 12 L1', 'op ?pretend(a, b) = add(a, b) L1'].map(source => api.pipeline(source, source.startsWith('obj') ? 'object' : 'operation', 'integer'));
out.layers = ['op spoof(a) = a L0', 'op spoof(a) = a L2', 'op spoof(a) = a L99', 'op spoof(a) = a'].map(source => api.pipeline(source, 'operation', 'integer'));
out.comparisons = ['op bad(a) = if eq(a, a, 0) then succ(a) else a L1', 'op bad(a) = if eq(a) then succ(a) else a L1', 'op bad(a) = if neq(a) then succ(a) else a L1'].map(source => api.pipeline(source, 'operation', 'integer'));
out.sortFailures = [api.pipeline('obj Bad = refine {value: succ} where eq(value, value) canon mod 12 L1', 'object', 'integer'), api.pipeline('op bad(a) = add(is_zero(a), a) L1', 'operation', 'integer')];
out.writeOnlyFailures = [api.pipeline('law #bad(a) = eq(a, a) L2', 'law', 'integer'), api.pipeline('bridge ~bad(a) = is_zero(a) L1', 'bridge', 'integer')];
out.failureSteps = [0, 1, 2, 3, 4, 5].map(frame => api.canAdvance(out.unbound, frame));
out.defaults = Object.fromEntries(['operation', 'object', 'combinator', 'observation', 'law', 'bridge'].map(kind => [kind, api.pipeline(api.examples[kind].good, kind, kind === 'observation' ? 'robot' : 'integer')]));
out.key = [api.evidenceKey('op f(a) = succ(a) L1', 'operation', {method: 'sampled', reference: 'succ', seed: 7}),
           api.evidenceKey('op f(a) = succ(a) L1', 'operation', {method: 'sampled', reference: 'succ', seed: 8}),
           api.evidenceKey('op f(a) = dec(a) L1', 'operation', {method: 'sampled', reference: 'succ', seed: 7})];
out.badSeed = api.pipeline(api.examples.operation.good, 'operation', 'integer', {method: 'sampled', seed: 0, reference: 'mul'});
out.sampledProbe = api.pipeline(api.examples.observation.good, 'observation', 'robot', {method: 'sampled', seed: 7});
out.sampledCombinator = api.pipeline(api.examples.combinator.good, 'combinator', 'integer', {method: 'sampled', seed: 7});
out.sampledRefine = api.pipeline(api.examples.object.refine, 'object', 'integer', {method: 'sampled', seed: 7});
out.cut = {folded: window.A2.boundary.cut(out.tree.tree, {depth: 2}).length,
           opened: window.A2.boundary.cut(out.tree.tree, {depth: 1}).length};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def preview():
    result = subprocess.run([NODE, "-e", SCRIPT, str(ROOT / "docs/assets/js/atoms2")], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@requires_node
def test_parser_and_positions(preview):
    assert preview["nodes"]["mul"]["node"] == "Case"
    assert preview["nodes"]["three"]["node"] == "Call"
    assert preview["nodes"]["fraction"]["canon"] == "reduce"
    assert preview["nodes"]["twice"]["args"][0]["node"] == "Call"
    assert preview["nodes"]["front_free"]["node"] == "And"
    assert preview["nodes"]["let"]["node"] == "Let"
    assert all(message.startswith("Line 1, column ") for message in preview["errors"])


@requires_node
def test_mul_matches_reference_and_charges_13(preview):
    result = preview["mul"]
    assert result["record"]["status"] == "previewed"
    assert result["record"]["depends_on"] == ["is_zero", "add", "dec"]
    assert result["sample"]["outcome"] == {"ok": {"t": "int", "v": 12}}
    assert result["sample"]["steps"] == 13
    assert result["evidence"]["method"] == "exhaustive"
    assert result["evidence"]["scope"]["size"] == 256
    assert result["record"]["contract"]["guarantees"]
    assert preview["tree"]["tree"]["result"] == 12
    assert preview["cut"]["opened"] > preview["cut"]["folded"] == 1


@requires_node
def test_bad_definitions_fail_at_the_correct_station(preview):
    assert preview["wrong"]["stations"][3]["ok"] is False
    assert "First counterexample" in preview["wrong"]["error"]
    assert preview["fuel"]["stations"][2]["ok"] is False
    assert "fuel" in preview["fuel"]["error"]
    assert preview["unbound"]["stations"][1]["ok"] is False
    assert preview["arity"]["stations"][1]["ok"] is False
    assert "Sealed truth" in preview["sealed"]["error"]
    assert "not granted" in preview["restricted"]["error"]
    assert "Operation slot" in preview["slot"]["error"]


@requires_node
def test_sampled_evidence_stays_case_scoped(preview):
    result = preview["sampled"]
    assert result["record"]["status"] == "verified"
    assert result["evidence"]["method"] == "sampled"
    assert result["stations"][4]["ok"] is None
    assert "Case check only" in result["stations"][4]["detail"]


@requires_node
def test_all_four_kinds_and_session_dependencies(preview):
    assert preview["fraction"]["record"]["status"] == "previewed"
    assert preview["twice"]["record"]["status"] == "previewed"
    assert preview["three"]["record"]["status"] == "evaluated (no reference check)"
    assert preview["probe"]["record"]["status"] == "evaluated (no reference check)"
    assert preview["fraction"]["sample"]["result"]["f"] == [{"t": "int", "v": 1}, {"t": "int", "v": 2}]
    assert preview["twice"]["evidence"]["method"] == "bounded"
    assert preview["probe"]["record"]["spec"]["reads"] == ["front_wall", "front_water"]
    assert preview["derivedProbe"]["record"]["spec"]["reads"] == ["front_wall", "front_water"]
    assert preview["derivedProbe"]["record"]["layer"] == 2
    assert preview["dep"]["record"]["status"] == "evaluated (no reference check)"
    assert preview["dep"]["record"]["layer"] == 2
    assert preview["genericReference"]["record"]["status"] == "previewed"
    assert preview["missingReference"]["stations"][1]["ok"] is False
    assert preview["mod"]["record"]["status"] == "previewed"
    assert preview["mod"]["sample"]["result"]["f"][0]["v"] == 2
    assert preview["modInvalid"]["stations"][3]["ok"] is False


@requires_node
def test_sorts_and_scope_are_declared_from_cases(preview):
    assert "Output sort bool" in preview["boolAsInt"]["error"]
    assert preview["closed"]["record"]["status"] == "evaluated (no reference check)"
    assert preview["closed"]["evidence"]["scope"]["domain"] == "closed term (one case)"
    assert preview["sampled"]["evidence"]["scope"]["domain"].startswith("seeded cases [")
    assert preview["sampled"]["evidence"]["scope"]["size"] == 24
    assert preview["sampledProbe"]["evidence"]["scope"]["domain"].startswith("seeded cases [")
    assert preview["sampledCombinator"]["evidence"]["scope"]["domain"].startswith("seeded cases [")
    assert "Seeded sampling is unavailable" in preview["sampledRefine"]["error"]


@requires_node
def test_shadowing_and_integer_precision_are_rejected(preview):
    assert "already names" in preview["shadow"]["error"]
    assert "already names" in preview["shadowSession"]["error"]
    assert preview["unsafeInput"]["outcome"] == {"bottom": "unsafe_integer"}
    assert "safe range" in preview["unsafeLiteral"]["error"]


@requires_node
def test_laws_and_bridges_are_write_and_parse_only(preview):
    for kind in ("law", "bridge"):
        result = preview[kind]
        assert result["record"]["status"] == "written"
        assert result["stations"][0]["ok"] is True
        assert all(station["ok"] is None for station in result["stations"][1:])
        assert result["evidence"] is None
        assert "syntax and sorts only" in result["stations"][0]["detail"]
        assert result["record"]["layer"] == 1
    assert all(result["stations"][0]["ok"] is False for result in preview["writeOnlyFailures"])


@requires_node
def test_fixture_default_of_every_kind_reaches_honest_last_station(preview):
    for kind, result in preview["defaults"].items():
        assert result["error"] is None, (kind, result["error"])
        final = 0 if kind in ("law", "bridge") else 3
        assert result["stations"][final]["ok"] is True, kind
    assert preview["three"]["sample"]["result"] == 83


@requires_node
def test_wrong_kind_sigils_cannot_enter_verification(preview):
    for result in preview["invalidSigils"]:
        assert result["stations"][0]["ok"] is False
        assert "sigil" in result["error"]


@requires_node
def test_declared_layer_matches_dependencies_and_is_required(preview):
    assert preview["dep"]["record"]["layer"] == 2
    for result in preview["layers"][:3]:
        assert result["stations"][1]["ok"] is False
        assert "computed L1" in result["error"]
    assert preview["layers"][3]["stations"][0]["ok"] is False
    assert "Expected a declared layer" in preview["layers"][3]["error"]


@requires_node
def test_comparison_arity_is_checked_before_sort_inference(preview):
    for result in preview["comparisons"]:
        assert result["stations"][1]["ok"] is False
        assert "Line 1, column" in result["error"]
        assert "expects exactly two arguments" in result["error"]
    assert all(result["stations"][1]["ok"] is False for result in preview["sortFailures"])
    assert "Unknown object sort" in preview["sortFailures"][0]["error"]
    assert "expects int" in preview["sortFailures"][1]["error"]


def test_lab_and_workshop_controls_have_visible_actions():
    lab = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    workshop = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    page = (ROOT / "docs/play/index.md").read_text()
    assert "machines.replaceChildren(machine(selected" in lab
    assert "playback = setInterval" in lab
    assert "runMachine(false, false); runStatus.textContent" in lab
    assert "refreshLibrary(); refreshReferences();" in workshop
    assert "seedField.hidden = method.value !==" in workshop
    assert "#definition-workshop" in lab and "{#definition-workshop}" in page


@requires_node
def test_play_cannot_advance_past_failed_or_unrun_station(preview):
    assert preview["failureSteps"] == [True, True, False, False, False, False]


def test_play_controls_guard_unrun_stations_and_fixture_load_order():
    source = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    page = (ROOT / "docs/play/index.md").read_text()
    assert "if (!canAdvance(current, frame)) { stop(); return; }" in source
    assert "current.stations[frame].ok !== null" in source
    assert "tabs.addEventListener(\"keydown\"" in source
    assert page.index("lab-preview-world.js") < page.index("define.js")
    assert "boundary.js" in page
    assert "atoms2-boundary.css" in page


@requires_node
def test_evidence_is_bound_to_source_settings_and_seed(preview):
    assert len(set(preview["key"])) == 3
    assert "Seed must" in preview["badSeed"]["error"]
    source = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    assert 'text.addEventListener("input", invalidate)' in source
    assert 'seed.addEventListener("input", invalidate)' in source
    assert 'if (event.target !== section) return;' in source
    assert 'event.key === " "' not in source


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_play_world_picker_updates_both_hash_targets():
    source = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    assert 'id: "computer-lab"' in source
    assert 'world === "integer" ? "definition-workshop" : "computer-lab"' in source
    assert 'root.location.hash === "#definition-workshop"' in source
    chooser = source[source.index("    function chooseWorld(world) {"):source.index("    var requestedWorld =")]
    result = subprocess.run(
        [NODE, "-e", """
const worldPicker = {value: 'computer'}, scrolled = [];
let hash = '';
const root = {location: {href: 'https://example.test/play/', get hash() { return hash; }, set hash(value) { hash = '#' + value.replace(/^#/, ''); }}, document: {getElementById: id => ({scrollIntoView: () => scrolled.push(id)})}};
eval(process.argv[1]);
chooseWorld('integer');
const workshop = [worldPicker.value, root.location.hash];
chooseWorld('computer');
const computer = [worldPicker.value, root.location.hash];
chooseWorld('computer');
console.log(JSON.stringify({workshop, computer, scrolled}));
""", chooser],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {
        "workshop": ["integer", "#definition-workshop"],
        "computer": ["computer", "#computer-lab"],
        "scrolled": ["computer-lab"],
    }


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_play_world_picker_redirects_roads_query_on_load():
    source = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    chooser = source[source.index("    function chooseWorld(world) {"):source.index("    var requestedWorld =")]
    initialization = source[source.index("    var requestedWorld ="):source.index("    section.append(el(\"div\", { class: \"a2-computer-world\"")]
    result = subprocess.run(
        [NODE, "-e", """
const load = new Function('root', 'worldPicker', process.argv[1] + process.argv[2]);
const cases = ['computer', 'integer', 'roads'].map(world => {
  const root = {location:{search:'?world=' + world, hash:'#computer-lab',
    href:'https://example.test/play/?world=' + world,
    assign(destination) { root.destination = destination; }}};
  const picker = {value:'computer', addEventListener() {}};
  load(root, picker);
  return {value:picker.value, destination:root.destination};
});
console.log(JSON.stringify(cases));
""", chooser, initialization],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == [
        {"value": "computer"}, {"value": "integer"},
        {"value": "computer", "destination": "https://example.test/play/challenge/"},
    ]


@requires_node
def test_play_law_bridge_copy_and_preview_status_are_honest(preview):
    page = (ROOT / "docs/play/index.md").read_text()
    source = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    for function in ("opulse.atoms.laws.verify_law", "replay_rewrite", "opulse.atoms.bridges.verify_bridge"):
        assert function in page
        assert function in source
    assert "not yet executable in the core" not in page + source
    assert 'record.status = "previewed"' in source
    assert 'record.status = "promoted"' not in source
    assert preview["mul"]["stations"][4]["status"] == "previewed"
    assert preview["sampled"]["record"]["status"] == "verified"


def test_given_shelf_label_and_explicit_tower_preview():
    source = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    assert 'layer === 0 ? "Given" : "L" + layer' in source
    assert 'towerButton.addEventListener("click"' in source
    assert '    towerButton.click();' not in source
    assert 'A2.define.enterWorkshop' not in source
    assert 'expression.value = "?clear_signal{}"' in source
    assert 'results.push({ name: result.record.name, size: result.evidence.scope.size })' in source
    assert 'towerStatus.appendChild(mark ? root.N3Convert.render(mark.display) : formula(null, result.name))' in source
