"""Schema /3 tasks prepare offline grading without using public answer checks."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/atoms2_challenge_schema3.json"
CATALOGUE = ROOT / "docs/assets/data/challenge/v2.json"
SCRIPT = ROOT / "docs/assets/js/atoms2/ladders.js"
PRIVATE = ROOT / "build/challenge_v2/grading.json"
PRIVATE_MISSING = "run python -m opulse.tasks_v2.challenge_grade --build first"
NODE = shutil.which("node")


def matching_private_grading() -> bool:
    return (PRIVATE.is_file() and hashlib.sha256(PRIVATE.read_bytes()).hexdigest() ==
            json.loads(CATALOGUE.read_text())["grading_sha256"])


def test_schema3_fixture_matches_current_public_entries_without_checks() -> None:
    original = json.loads(CATALOGUE.read_text())
    fixture = json.loads(FIXTURE.read_text())
    assert original["schema"] == fixture["schema"] == "opulse.challenge_v2/3"
    for tasks in original["ladders"].values():
        for task in tasks:
            assert "grader" not in task
            assert task["grading"] == "Graded offline by the exact grader."
            assert task["answer_format"]
            assert task["prompt"]
    for tasks in fixture["ladders"].values():
        for task in tasks:
            assert task["answer_format"] and task["prompt"]
    assert original["paths"]["six_kinds_one_world"]["steps"]
    assert fixture["paths"]["six_kinds_one_world"]["steps"]
    assert '"check"' not in CATALOGUE.read_text()


@pytest.mark.skipif(NODE is None, reason="node is required")
def test_schema3_answers_only_check_shape_and_quote_offline_command() -> None:
    script = r"""const assert = require('node:assert/strict');
const data = require(process.argv[1]);
const bridge = require(process.argv[2]);
const schema = data.schema;
const task = data.ladders.compute[0];
(async () => {
  const good = bridge.parseAnswer(task, '0', schema);
  assert.deepEqual(good, {ok:{t:'int',v:0}});
  assert.equal((await bridge.grade(task, good, schema)).status, 'offline');
  assert.equal((await bridge.grade(task, {ok:{t:'int',v:12}}, schema)).status, 'offline');
  assert.equal((await bridge.grade(task, {unknown:'fuel'}, schema)).status, 'invalid');
  assert.equal((await bridge.grade(task, {ok:{t:'int',v:1.5}}, schema)).status, 'invalid');
  assert.equal((await bridge.grade(task, {ok:{t:'int',v:2 ** 53}}, schema)).status, 'invalid');
  assert.equal((await bridge.grade(task, [1], schema)).status, 'invalid');
  assert.throws(() => bridge.parseAnswer(task, '{"unknown":"fuel"}', schema), /Invalid answer shape/);
  assert.throws(() => bridge.parseAnswer(task, '{"ok":{"t":"int","v":1.5}}', schema), /Invalid answer shape/);
  assert.equal(bridge.pythonCommand(task, good, schema),
    `PYTHONPATH=src python -m opulse.tasks_v2.challenge_grade '${task.id}' '{"ok":{"t":"int","v":0}}'`);
  const choice = data.ladders.describe[0];
  const quoted = "it's a shell test";
  assert.equal((await bridge.grade(choice, bridge.parseAnswer(choice, quoted, schema), schema)).status, 'offline');
  assert(bridge.pythonCommand(choice, quoted, schema).includes("it'\\''s a shell test"));
  assert.equal((await bridge.grade({...choice, grader:{...choice.grader, check:{hash:'wrong'}}},
    'i1', schema)).status, 'offline');
  for (const [shape, goodAnswer, badAnswer] of [
    ['definition', 'op f(a) = a L1', null],
    ['verdict', {true:false, counterexample:[{t:'int',v:2}]}, {true:'false'}],
    ['one_witness', [{t:'int',v:12}], null],
    ['all_solutions', [[{t:'int',v:12}]], {t:'int',v:12}],
  ]) {
    const entry = {...task, answer_format:shape};
    assert.equal((await bridge.grade(entry, goodAnswer, schema)).status, 'offline', shape);
    assert.equal((await bridge.grade(entry, badAnswer, schema)).status, 'invalid', shape);
  }
  assert.throws(() => bridge.parseAnswer(task, ''), /Enter an answer/);
  assert.throws(() => bridge.parseAnswer(task, '\u2666'), /ASCII/);
})();"""
    result = subprocess.run([NODE, "-e", script, str(FIXTURE), str(SCRIPT)],
                            cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(NODE is None, reason="node is required")
def test_schema3_accepts_all_published_answer_shapes_without_comparing_answers() -> None:
    if not matching_private_grading():
        pytest.skip(PRIVATE_MISSING + "; tasks must regenerate the public catalogue")
    script = """const assert = require('node:assert/strict');
const data = require(process.argv[1]);
const privateAnswers = require(process.argv[2]);
const bridge = require(process.argv[3]);
(async () => {
  for (const task of Object.values(data.ladders).flat()) {
    assert.equal((await bridge.grade(task, privateAnswers[task.id].reference,
      'opulse.challenge_v2/3')).status, 'offline', task.id);
  }
})().catch(error => {console.error(error); process.exitCode = 1});"""
    result = subprocess.run([NODE, "-e", script, str(CATALOGUE), str(PRIVATE), str(SCRIPT)],
                            cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(NODE is None, reason="node is required")
def test_schema3_render_prepares_command_without_a_browser_grade() -> None:
    script = r"""const assert = require('node:assert/strict');
const fixture = require(process.argv[1]);
const catalogue = require(process.argv[2]);
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.handlers = {}; this.dataset = {};
    this.value = ''; this.classList = {toggle() {}}; }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  prepend(child) { this.children.unshift(child); }
  querySelectorAll() { return []; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
}
global.document = {createElement: tag => new Element(tag), readyState:'loading', addEventListener() {}};
global.A2 = {badge: () => new Element('badge'), kindBadge: () => new Element('kind'), expr: text => text};
const bridge = require(process.argv[3]);
function find(element, predicate) {
  if (predicate(element)) return element;
  for (const child of element.children || []) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}
function text(element) { return (element.textContent || '') + (element.children || []).map(text).join(''); }
(async () => {
  const host = new Element('div');
  bridge.renderTask(host, fixture.ladders.compute[0], {entries:{}}, fixture.schema);
  assert(text(host).includes('Browser grading is off'));
  assert(!text(host).includes('PUBLIC HASH CHECK'));
  assert(!text(host).includes('Browser checks are open-book'));
  const form = find(host, element => element.tag === 'form');
  const input = find(form, element => element.tag === 'textarea');
  const report = find(host, element => element.className === 'ladder-report');
  input.value = '0';
  await form.handlers.submit({preventDefault() {}});
  assert(text(report).includes('Answer shape accepted locally'));
  assert(text(report).includes('generate the private grading file locally'));
  assert(text(report).includes('opulse.tasks_v2.challenge_grade --build'));
  assert(text(report).includes('OPULSE_CHALLENGE_GRADING'));
  assert(text(report).includes("PYTHONPATH=src python -m opulse.tasks_v2.challenge_grade 'clock@2/compute/operation/0004'"));
  assert(!text(report).includes('Matches the public hash check'));
  input.value = '{"unknown":"fuel"}';
  await form.handlers.submit({preventDefault() {}});
  assert(text(report).includes('Invalid answer shape'));
  assert(!text(report).includes('python -m'));
  const fullFixture = {...fixture, ladders:{...fixture.ladders,
    invert:[], decide:[], induce:[], create:[]}};
  bridge.render(host, fullFixture, {entries:{}});
  assert(text(host).includes('Prepare offline command'));
  assert(text(host).includes('Canonicalize Pair<2, 4>'));
  bridge.renderTask(host, catalogue.ladders.compute[0], {entries:{}}, catalogue.schema);
  assert(text(host).includes('Browser grading is off'));
  assert(!text(host).includes('PUBLIC HASH CHECK'));
  assert(text(host).includes('Prepare offline command'));
})();"""
    result = subprocess.run([NODE, "-e", script, str(FIXTURE), str(CATALOGUE), str(SCRIPT)],
                            cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_schema3_page_discloses_offline_grading() -> None:
    page = (ROOT / "docs/play/ladders.md").read_text()
    assert "browser grading is off" in page.lower()
    assert "offline Python grading command" in page
    assert "private grading file" in page
    assert "private grading file locally on first use" in page
    assert "build/challenge_v2/grading.json" in page
    assert "OPULSE_CHALLENGE_GRADING" in page
    assert "file is not in the repository" in page
    assert "grader's reference file in the repository" not in SCRIPT.read_text()


def _javascript_command_grades_real_reference_answer() -> None:
    # The build, node and grading steps all use PRIVATE, whatever the caller's environment says.
    private = {"OPULSE_CHALLENGE_GRADING": str(PRIVATE)}
    build = subprocess.run([sys.executable, "-m", "opulse.tasks_v2.challenge_grade", "--build"],
                           cwd=ROOT, env={**os.environ, "PYTHONPATH": "src", **private},
                           capture_output=True, text=True, check=False)
    if build.returncode and "does not match the public catalogue hash" in build.stderr:
        pytest.skip("tasks must regenerate the public catalogue against this checkout")
    assert build.returncode == 0, build.stderr
    script = """const bridge = require(process.argv[1]);
const data = require(process.argv[2]);
const privateData = require(process.argv[3]);
const task = data.ladders.compute[0];
console.log(bridge.pythonCommand(task, privateData[task.id].reference, data.schema));"""
    generated = subprocess.run([NODE, "-e", script, str(SCRIPT), str(CATALOGUE), str(PRIVATE)],
                               cwd=ROOT, capture_output=True, text=True, check=True)
    command = generated.stdout.strip()
    assert command.startswith("PYTHONPATH=src python -m opulse.tasks_v2.challenge_grade ")
    environment = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
                       **private)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(command, shell=True, cwd=ROOT, env=environment,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"correct": True}


@pytest.mark.skipif(NODE is None, reason="node is required")
def test_schema3_javascript_command_grades_real_reference_answer() -> None:
    _javascript_command_grades_real_reference_answer()


@pytest.mark.skipif(NODE is None, reason="node is required")
def test_schema3_javascript_command_ignores_session_grading_override(challenge_grading_path, challenge_grading) -> None:
    # Regression: with the session override active, the build used to write to the temporary
    # file and leave build/challenge_v2/grading.json missing for node.
    assert os.environ["OPULSE_CHALLENGE_GRADING"] == str(challenge_grading_path) != str(PRIVATE)
    _javascript_command_grades_real_reference_answer()


def test_session_grading_override_does_not_leak_into_other_tests(challenge_grading_path) -> None:
    # Runs after the test above in file order; the override must be gone once that test ends.
    assert os.environ.get("OPULSE_CHALLENGE_GRADING") != str(challenge_grading_path)
