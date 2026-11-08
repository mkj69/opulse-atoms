"""Exported combination modes are kernel results, not authored result sketches."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from opulse.atoms import nodes as n
from opulse.atoms import notation
from opulse.atoms.boundary import Boundary
from opulse.atoms.kernel import call
from opulse.atoms.verify import unfold_equivalent_calls

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def exporter():
    location = ROOT / "tools/atoms2_ui_export.py"
    spec = importlib.util.spec_from_file_location("atoms2_modes_export", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mode_export_agrees_with_fresh_kernel_calls(exporter):
    data = exporter.mode_traces()
    assert set(data["runs"]) == {"fixpoint", "memo", "turns", "fold"}
    for key, (scope, name, args, _) in exporter.mode_cases().items():
        run = call("fib_memo" if key == "memo" else name, args, scope, trace=True)
        published = data["runs"][key]
        root = data["derivations"][key]["root"]
        assert run.steps == published["steps"] == exporter.count_leaves(root)
        assert run.work == published["memo_work" if key == "memo" else "work"]
        assert exporter.ui_value(run.outcome) == published["outcome"] == root["result"]
        assert published["core_digest"] == exporter.CORE_DIGEST
    assert data["runs"]["fixpoint"]["outcome_text"].count('"') == 24
    assert data["runs"]["turns"]["outcome_text"] == "Ok(List<11, 72, 153>)"
    assert data["runs"]["fold"]["outcome_text"] == "Ok(1188)"


def test_memo_matches_plain_result_and_charged_steps(exporter):
    scope, _, args, _ = exporter.mode_cases()["memo"]
    plain = call("fib", args, scope, trace=True)
    memo = call("fib_memo", args, scope, trace=True)
    record = exporter.mode_traces()["runs"]["memo"]
    assert plain.outcome == memo.outcome
    assert plain.steps == memo.steps == record["memo_steps"] == record["steps"]
    assert memo.work == record["memo_work"] < plain.work == record["work"]
    memo_root = exporter.mode_traces()["derivations"]["memo"]["root"]
    def collect(frame):
        return [frame, *(item for child in frame["children"] for item in collect(child))]
    entries = collect(memo_root)
    assert record["cache_hits"] == exporter.memo_hits(memo.trace) == 33
    assert record["executed_cache_hits"] == exporter.executed_memo_hits(memo.trace) == sum(
        item["cache_hit"] for item in entries) == 7
    assert sum(item["cached_replay"] and not item["cache_hit"] for item in entries) > 0
    assert any(item["cached_replay"] for item in entries)
    assert unfold_equivalent_calls(memo.trace, [Boundary.unfold_none(),
                                                 Boundary.unfold_all(),
                                                 Boundary(open_names=frozenset({"fib_memo"}))]).ok


def test_exported_digest_identifies_kernel_source(exporter):
    from tools.export_digest import inputs_sha256

    assert exporter.CORE_DIGEST == inputs_sha256(ROOT, (ROOT / "src/opulse/atoms").glob("*.py"))


def test_all_shown_expressions_and_declarations_round_trip(exporter):
    from opulse.atoms.spec import Definition

    data = exporter.mode_traces()["runs"]
    for key, (scope, name, args, details) in exporter.mode_cases().items():
        context = {"kinds": {name: "combinator"},
                   "op_arity": {name: 1 if key == "fixpoint" else 5}}
        if key == "fold":
            context = {"kinds": {name: "combinator"}, "op_arity": {name: 0}}
        elif key == "memo":
            context = {"kinds": {name: "operation", "fib_memo": "operation"}}
        expected = n.Call("fib_memo" if key == "memo" else name,
                          tuple(n.Lit(value) for value in args))
        assert notation.parse_expr(data[key]["expression"], context) == expected
        assert notation.print_expr(expected, context) == data[key]["expression"]
        if key == "memo":
            assert notation.parse_expr(data[key]["memo_expression"], context) == n.Call(
                "fib_memo", (n.Lit(9),))
        if key == "fold":
            tree = details["object"]
            definition = Definition(tree.name, "object", "invented", 1, (), tree, None)
            assert notation.parse_definition(data[key]["declaration"]) == definition


JS_CUT_CHECK = r"""
const assert = require('node:assert/strict');
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
require(process.argv[1] + '/../../../../tests/fixtures/atoms2-mock.js');
require(process.argv[1] + '/data.js');
require(process.argv[1] + '/boundary.js');
let checked = 0;
for (const [key, sample] of Object.entries(A2.kernelData.modes.derivations)) {
  const root = sample.root;
  const total = A2.kernelData.modes.runs[key].steps;
  assert.deepEqual(root.result, A2.kernelData.modes.runs[key].outcome);
  assert.equal(A2.mock.charged(root), total);
  const depthLimit = Math.max(...A2.boundary.definitions(root).map(def => def.layer)) + 1;
  for (let depth = 1; depth <= depthLimit; depth++) {
    for (let mask = 0; mask < (1 << A2.ALL_KINDS.length); mask++) {
      const kinds = A2.ALL_KINDS.filter((kind, index) => mask & (1 << index));
      for (const extra of [{}, {open_paths: [[], [0]]},
        {open_names: ['fix', 'fib', 'fold_tree', 'turns']},
        {keep_names: ['fib_local'], open_paths: [[]]}]) {
        const rows = A2.boundary.cut(root, A2.boundary({...extra, depth, kinds}));
        assert.deepEqual(rows[0].result, root.result, key);
        assert.equal(rows.filter(row => row.folded || row.given)
          .reduce((sum, row) => sum + row.charged, 0), total, key);
        checked++;
      }
    }
  }
}
console.log(checked);
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_new_mode_boundary_cuts_preserve_outcome_and_charge():
    result = subprocess.run([NODE, "-e", JS_CUT_CHECK, str(ROOT / "docs/assets/js/atoms2")],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    assert int(result.stdout) >= 500


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_reference_mode_panels_and_boundary_handoff():
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.textContent = ''; this.hidden = false; }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name,value) { this.attrs[name] = value; }
  addEventListener(name,fn) { this.listeners[name] = fn; }
}
const host = new Element('main');
globalThis.document = {getElementById: id => id === 'a2-reference-modes' ? host : null,
  createElement: tag => new Element(tag)};
const keys = ['fixpoint','memo','turns','fold'];
const calls = [];
globalThis.A2 = {kernelData:{modes:{runs:Object.fromEntries(keys.map(key => [key,
  {core_digest:'abc123',expression:key+'(1)',outcome_text:'Ok(1)',steps:271,
   memo_steps:271,work:271,memo_work:34,cache_hits:33,executed_cache_hits:7}])),
  derivations:Object.fromEntries(keys.map(key => [key,{root:{def:key}}]))}},
  boundary:{render:(element,options) => calls.push([element,options])},
  expr:text => {const element = new Element('code'); element.textContent = text; return element;}};
require(process.argv[1] + '/modes.js');
assert.equal(host.children.length,4);
assert.equal(calls.length,4);
const memoAccounting = host.children[1].children.find(child => child.className === 'a2-mode-accounting');
assert.match(memoAccounting.textContent,/Exact layer-0 steps: 271 plain, 271 memo/);
assert.match(memoAccounting.textContent,/Executed work: 271 plain, 34 memo/);
assert.match(memoAccounting.textContent,/33 memo-hit nodes in the charged trace; 7 were cache lookups during execution/);
assert.match(memoAccounting.textContent,/replayed unfoldings and did not run again/);
keys.forEach((key,index) => {
  const panel = host.children[index];
  const badge = panel.children.find(child => child.className === 'ar-badge ar-badge-executable');
  assert.match(badge.textContent,/Executable \(core SHA-256 abc123\)/);
  const button = panel.children.find(child => child.tag === 'button');
  const viewer = panel.children.find(child => child.className === 'a2-mode-viewer');
  assert.equal(button.attrs['aria-controls'],viewer.id);
  assert.equal(viewer.hidden,index !== 0);
  assert.equal(button.attrs['aria-expanded'],String(index === 0));
  assert.equal(calls[index][0],viewer);
  assert.equal(calls[index][1].derivation,A2.kernelData.modes.derivations[key]);
  assert.equal(calls[index][1].compact,true);
  button.listeners.click();
  assert.equal(viewer.hidden,index === 0);
  assert.equal(button.attrs['aria-expanded'],String(index !== 0));
});
'''
    subprocess.run([NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2")],
                   cwd=ROOT, capture_output=True, text=True, check=True)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_reference_modes_missing_data_fallback():
    script = r'''
const assert = require('node:assert/strict');
globalThis.window = globalThis;
const host = {textContent:''};
globalThis.document = {getElementById:() => host};
globalThis.A2 = {kernelData:{modes:{runs:{fixpoint:{}},derivations:{fixpoint:{}}}},boundary:{render(){throw Error('unexpected render')}}};
require(process.argv[1] + '/modes.js');
assert.match(host.textContent,/Kernel traces are unavailable/);
'''
    subprocess.run([NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2")],
                   cwd=ROOT, capture_output=True, text=True, check=True)
