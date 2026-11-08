"""Real kernel traces agree with the generated UI data and every boundary cut."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from opulse.atoms.kernel import Atom, DictScope, FnRef, call

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "tools/atoms2_ui_export.py"
JS = ROOT / "docs/assets/js/atoms2"
NODE = shutil.which("node")


def load_exporter():
    spec = importlib.util.spec_from_file_location("atoms2_ui_export", EXPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_data_is_current():
    result = subprocess.run([sys.executable, str(EXPORTER), "--check"], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_trace_charges_and_results_match_kernel():
    exporter = load_exporter()
    data = exporter.traces()
    assert set(data["derivations"]) == set(exporter.TITLE)
    integer = exporter.world()
    state = {"front_wall": False, "front_water": True}
    robot = DictScope(atoms=[
        Atom(name, 0, lambda name=name: state[name], kind="observation")
        for name in ("front_wall", "front_water")
    ], defns=[integer.defns["front_free"]])
    examples = {
        "mul_3_4": (integer, "mul", (3, 4)),
        "dot": (integer, "dot", (exporter.list_card((1, 2)), exporter.list_card((3, 4)))),
        "twice_triple": (integer, "twice", (FnRef("triple"), 1)),
        "front_free": (robot, "front_free", ()),
    }
    for key, sample in data["derivations"].items():
        scope, name, args = examples[key]
        run = call(name, args, scope, trace=True)
        root = sample["root"]
        assert root["path"] == [] and root["id"] == "n1"
        assert root["result"] == data["runs"][key]["outcome"] == exporter.ui_value(run.outcome)
        assert exporter.count_leaves(root) == data["runs"][key]["steps"] == run.steps
        seen = []

        def visit(node, path, seen=seen):
            assert node["path"] == path
            seen.append(node["id"])
            if not node["children"]:
                assert node["given"] and node["layer"] == 0
            else:
                assert not node["given"]
            for index, child in enumerate(node["children"]):
                visit(child, path + [index])

        visit(root, [])
        assert seen == [f"n{index}" for index in range(1, len(seen) + 1)]


SCRIPT = r"""
const assert = require('node:assert/strict');
globalThis.window = globalThis;
require(process.argv[1] + '/kit.js');
const mock = require(process.argv[1] + '/../../../../tests/fixtures/atoms2-mock.js');
require(process.argv[1] + '/data.js');
require(process.argv[1] + '/boundary.js');
assert.equal(mock.source, 'kernel');
assert.equal(mock.derivations, A2.kernelData.derivations);
let checked = 0;
for (const [key, sample] of Object.entries(mock.derivations)) {
  const root = sample.root;
  const total = A2.kernelData.runs[key].steps;
  assert.deepEqual(root.result, A2.kernelData.runs[key].outcome);
  assert.equal(mock.charged(root), total);
  const maxDepth = Math.max(...A2.boundary.definitions(root).map(def => def.layer)) + 1;
  for (let depth = 1; depth <= maxDepth; depth++) {
    for (let mask = 0; mask < 16; mask++) {
      const kinds = A2.ALL_KINDS.filter((kind, index) => mask & (1 << index));
      for (const extra of [{}, {open_paths: [[], [0], [1]]},
        {open_names: ['mul', 'three', 'twice', 'front_free']},
        {keep_names: ['mul', 'three'], open_paths: [[]]}]) {
        const rows = A2.boundary.cut(root, A2.boundary({...extra, depth, kinds}));
        assert.deepEqual(rows[0].result, root.result, key);
        assert.equal(rows.filter(row => row.folded || row.given)
          .reduce((sum, row) => sum + row.charged, 0), total, key);
        checked++;
      }
    }
  }
}
console.log(JSON.stringify({checked}));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_real_boundary_cuts_keep_result_and_charge():
    output = subprocess.run([NODE, "-e", SCRIPT, str(JS)], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    assert json.loads(output.stdout)["checked"] >= 500
