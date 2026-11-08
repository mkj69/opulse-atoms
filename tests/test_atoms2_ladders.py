"""Synthetic schema /2 grading and public challenge asset checks."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
FIXTURE = ROOT / "tests/fixtures/atoms2_challenge_schema2.json"
LIVE_CATALOGUE = ROOT / "docs/assets/data/challenge/v2.json"
SCRIPT = ROOT / "docs/assets/js/atoms2/ladders.js"
PAGE = ROOT / "docs/play/ladders.md"


def reference_hash(identifier: str, value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(identifier.encode("utf-8") + b"\0" + encoded).hexdigest()


def synthetic_tasks():
    catalogue = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert catalogue["schema"] == "opulse.challenge_v2/2"
    tasks = []
    for case in catalogue["cases"]:
        task = {"id": case["id"], "answer_format": case["answer_format"], "grader": {}}
        answer = case["answer"]
        if "scope" in case:
            values = [answer] if case["answer_format"] == "one_witness" else answer
            task["grader"]["check"] = {
                "scope": case["scope"],
                "hashes": sorted(reference_hash(case["id"], value) for value in values),
                "complete": False,
            }
        elif case["answer_format"] != "definition":
            task["grader"]["check"] = {"hash": reference_hash(case["id"], answer),
                                         "complete": False}
        else:
            task["grader"]["method"] = "definition"
        tasks.append({"task": task, "answer": answer})
    return tasks


@pytest.mark.skipif(NODE is None, reason="Node.js is required")
def test_synthetic_schema2_hash_grading():
    script = r"""const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const bridge = require(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
(async () => {
  const results = [];
  for (const {task, answer} of cases) {
    const status = (await bridge.grade(task, answer)).status;
    assert.equal(status, task.answer_format === 'definition' ? 'python' : 'correct', task.id);
    if (task.answer_format !== 'definition') {
      const changed = task.answer_format === 'all_solutions' ? answer.slice(0, 1) :
        task.answer_format === 'one_witness' ? 11 :
        task.answer_format === 'choice' ? 'option_a' :
        task.answer_format === 'verdict' ? {...answer, true: true} :
        task.answer_format === 'value' && answer.bottom ? {bottom: 'different'} : {ok: {t: 'int', v: 43}};
      assert.notEqual((await bridge.grade(task, changed)).status, 'correct', task.id);
      assert.notEqual((await bridge.grade(task, {unknown:'fuel'})).status, 'correct', task.id);
      const check = task.grader.check;
      const digest = value => crypto.createHash('sha256').update(task.id + '\0' + bridge.canonical(value)).digest('hex');
      if (check.hash) assert.equal(digest(answer), check.hash);
      else assert.deepEqual((task.answer_format === 'one_witness' ? [answer] : answer).map(digest).sort(), check.hashes);
    }
    results.push(status);
  }
  assert.equal((await bridge.grade(cases.find(item => item.task.answer_format === 'one_witness').task, 11)).status, 'undecidable');
  assert.equal((await bridge.grade(cases.find(item => item.task.answer_format === 'verdict').task, {true: true})).status, 'undecidable');
  assert.equal((await bridge.grade(cases.find(item => item.task.answer_format === 'all_solutions').task, [23, 11])).status, 'correct');
  assert.throws(() => bridge.canonical({unsafe: Number.MAX_SAFE_INTEGER + 1}), /unsafe/);
  assert.equal(bridge.canonical({z:'\u00e9', a:['\ud83d\ude00']}), '{"a":["\\ud83d\\ude00"],"z":"\\u00e9"}');
  assert.equal(bridge.canonical({'\ud83d\ude00':1, '\ue000':2, control:'\u007f'}), '{"control":"\\u007f","\\ue000":2,"\\ud83d\\ude00":1}');
  assert.deepEqual(bridge.parseAnswer({answer_format:'value'}, '12'), {ok:{t:'int',v:12}});
  assert.equal(bridge.parseAnswer({answer_format:'value'}, 'add(mul(1, -2), mul(-2, 1))'), 'add(mul(1, -2), mul(-2, 1))');
  assert.throws(() => bridge.parseAnswer({answer_format:'choice'}, '\u2666'), /ASCII/);
  const bottom = cases.find(item => item.answer.bottom);
  assert.equal((await bridge.grade(bottom.task, bridge.parseAnswer(bottom.task, 'Bottom(no_path)'))).status, 'correct');
  console.log(JSON.stringify(results));
})().catch(error => { console.error(error); process.exitCode = 1; });"""
    result = subprocess.run([NODE, "-e", script, str(SCRIPT), json.dumps(synthetic_tasks())],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "python" if case["task"]["answer_format"] == "definition" else "correct"
        for case in synthetic_tasks()
    ]


def test_fixture_is_synthetic_and_live_challenge_has_no_grader_hashes():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    live = json.loads(LIVE_CATALOGUE.read_text(encoding="utf-8"))
    assert live["schema"] == "opulse.challenge_v2/3"
    live_ids = {entry["id"] for ladder in live["ladders"].values() for entry in ladder}
    live_ids.update(step["id"] for step in live["paths"]["six_kinds_one_world"]["steps"])
    assert fixture["cases"] and all(case["id"].startswith("synthetic/") for case in fixture["cases"])
    assert not live_ids.intersection(case["id"] for case in fixture["cases"])
    assert all("grader" not in case for case in fixture["cases"])
    for task in [entry for ladder in live["ladders"].values() for entry in ladder] + live["paths"]["six_kinds_one_world"]["steps"]:
        assert "reference" not in task
        assert "check" not in task.get("grader", {})
        assert "native_task_b64" not in json.dumps(task)


def test_public_assets_do_not_ship_private_references():
    served = PAGE.read_text() + SCRIPT.read_text() + (ROOT / "docs/assets/css/atoms2-ladders.css").read_text()
    assert served.isascii() and "scratchpad" not in served
    assert 'src="../../assets/js/atoms2/ladders.js"' in served
    assert 'href="../../assets/css/atoms2-ladders.css"' in served
    assert "Reveal reference answer" not in served
    assert "browser grading is off" in served.lower()
    assert "offline Python grading command" in served
    assert "NO ANSWER SHIPPED" not in served
    assert "answers are hidden" not in served.lower()
    assert "private in the browser" not in served.lower()
    assert "ladders" in (ROOT / "docs/play/index.md").read_text()
    assert "ladders" in (ROOT / "docs/play/challenge.md").read_text()


@pytest.mark.skipif(NODE is None, reason="Node.js is required")
def test_unmatched_verdict_and_complete_witness_policy():
    script = """const assert = require('node:assert/strict');
    const bridge = require(process.argv[1]);
    (async () => {
      const verdict = {id:'synthetic/verdict-policy', answer_format:'verdict', grader:{method:'decide', check:{hash:'none'}}};
      assert.equal((await bridge.grade(verdict, {true:false})).status, 'undecidable');
      const witness = {id:'synthetic/witness-policy', answer_format:'one_witness',
        grader:{method:'invert', check:{scope:[1,2], hashes:[], complete:true}}};
      assert.equal((await bridge.grade(witness, 2)).status, 'incorrect');
      assert.equal((await bridge.grade({...witness, grader:{...witness.grader,
        check:{...witness.grader.check, complete:false}}}, 2)).status, 'undecidable');
      console.log(bridge.pythonCommand(witness, 2));
    })().catch(error => { console.error(error); process.exitCode = 1; });"""
    result = subprocess.run([NODE, "-e", script, str(SCRIPT)], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "opulse.tasks_v2.challenge_grade" in result.stdout
