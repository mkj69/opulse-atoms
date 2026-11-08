"""Review-six grading regressions (docs/spec/atoms-v2.md, sections 7 and 9)."""

import json
from dataclasses import replace
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.tasks_v2 import grade, grade_kinds
from opulse.tasks_v2.angles import bridge, template
from opulse.tasks_v2.task import Task

ROOT = Path(__file__).resolve().parents[2] / "worlds/tasks"


def frozen(path, index=0):
    return Task.from_dict(json.loads((ROOT / path).read_text(encoding="utf-8"))[index])


@settings(max_examples=3, deadline=None)
@given(st.just("induce"), st.integers(min_value=1, max_value=3))  # create accepts safe memory by design
def test_observation_invented_memory_changes_full_state(angle, changed):
    task = frozen(f"action@1/observation_{angle}.json")
    answer = {**task.reference["definition"], "memory": {
        "sort": "int", "init": {"node": "Lit", "value": {"t": "int", "v": 0}},
        "step": {"node": "Lit", "value": {"t": "int", "v": changed}},
    }}
    assert grade_kinds.grade(task, task.reference["definition"]).correct
    assert not grade_kinds.grade(task, answer).correct


def test_operation_describe_poisoned_reference_exact_reproduction():
    task = frozen("clock@2/operation_describe.json")
    assert task.reference["choice"] == "i1"
    poisoned = replace(task, reference={**task.reference, "choice": "h4"})
    assert not grade.grade(poisoned, "h4").correct
    assert grade.grade(poisoned, "i1").correct


@settings(max_examples=3, deadline=None)
@given(st.integers(min_value=0, max_value=2))
def test_operation_describe_choice_comes_from_probe(index):
    task = frozen("clock@2/operation_describe.json", index)
    wrong = next(option for option in task.question["options"] if option != task.reference["choice"])
    poisoned = replace(task, reference={**task.reference, "choice": wrong})
    assert grade.grade(poisoned, task.reference["choice"]).correct
    assert not grade.grade(poisoned, wrong).correct


def test_operation_describe_unknown_is_not_a_match():
    task = frozen("clock@2/operation_describe.json")
    exhausted = replace(task, question={**task.question, "options": ["i1"]},
                        grader={**task.grader, "fuel": 1})
    assert not grade.grade(exhausted, "i1").correct


def test_bridge_invert_frozen_labels_and_multiple_solutions():
    records = json.loads((ROOT / "integer@1/bridge_invert.json").read_text(encoding="utf-8"))
    records += json.loads((ROOT / "computer@1/bridge_invert.json").read_text(encoding="utf-8"))
    candidates = [Task.from_dict(record) for record in records
                  if record["question"]["mode"] == "candidate"]
    assert candidates
    assert any(len(task.reference["answer"]) > 1 for task in candidates)
    for task in candidates:
        assert all("broken" not in label for label in task.question["candidates"])
        assert "Map: bridge ~" not in task.prompt["en"]
        assert set(task.question["candidates"]) == set(task.question["candidate_maps"])
        assert bridge.grade(task, task.reference["answer"]).correct
        assert not bridge.grade(task, task.reference["answer"] * 2).correct
        if len(task.reference["answer"]) > 1:
            assert not bridge.grade(task, task.reference["answer"][:1]).correct


def test_bridge_labels_do_not_encode_correctness():
    tasks = [bridge.generate("invert", seed, 2) for seed in range(12)]
    assert {task.reference["answer"][0] == task.question["candidates"][0]
            for task in tasks} == {True, False}


def _grading_rows(prefix, grading):
    rows = [row for key, row in grading.items() if key.startswith(prefix) and "task" in row]
    assert rows, prefix  # the catalogue is rebuilt from current generators; ids are not pinned
    return rows


def test_frozen_challenge_bridges_remain_gradeable(challenge_grading):
    for row in _grading_rows("integer@1/bridge/", challenge_grading):
        task = Task.from_dict(row["task"])
        assert bridge.grade(task, row["reference"]).correct


def test_frozen_challenge_template_decisions_remain_gradeable(challenge_grading):
    for row in _grading_rows("integer@1/template/", challenge_grading):
        task = Task.from_dict(row["task"])
        if task.angle != "decide":
            continue
        assert template.grade(task, row["reference"]).correct
        assert not template.grade(task, {"true": not row["reference"]["true"]}).correct


@settings(max_examples=4, deadline=None)
@given(st.integers(min_value=0, max_value=3))
def test_bridge_candidate_shuffle_retains_behavior(index):
    task = bridge.generate("invert", 13, index * 2)
    assert bridge.grade(task, task.reference["answer"]).correct
    assert not any("broken" in name for name in task.question["candidates"])


def test_statement_decisions_have_both_verdicts_and_require_witness():
    tasks = [Task.from_dict(item) for item in json.loads(
        (ROOT / "templates/template_decide.json").read_text(encoding="utf-8"))
             if item["source"]["index"] >= len(template.CASES)]
    assert {task.reference["answer"]["true"] for task in tasks} == {True, False}
    for task in tasks:
        answer = task.reference["answer"]
        assert template.grade(task, answer).correct
        if not answer["true"]:
            assert not template.grade(task, {"true": False}).correct
            assert not template.grade(task, {"true": True}).correct
            assert not template.grade(task, {"true": False, "counterexample": []}).correct


@settings(max_examples=3, deadline=None)
@given(st.integers(min_value=0, max_value=2))
def test_false_statement_verdict_recomputed_from_scope(seed):
    tasks = [template.generate("decide", seed, index)
             for index in range(len(template.CASES), len(template.CASES) + 4)]
    for family in ("Comm", "Canon"):
        assert {task.reference["answer"]["true"] for task in tasks
                if task.question["template"] == family} == {True, False}
    for task in tasks:
        assert template.grade(task, task.reference["answer"]).correct
        wrong = {"true": not task.reference["answer"]["true"]}
        assert not template.grade(task, wrong).correct
        poisoned = replace(task, reference={"answer": wrong})
        assert template.grade(poisoned, task.reference["answer"]).correct


def test_statement_law_accepts_any_in_scope_counterexample():
    tasks = [frozen("templates/template_decide.json", index) for index in range(len(template.CASES),
                                                                                 len(template.CASES) + 4)]
    law = next(task for task in tasks if task.question["arguments"] == ["sub"])
    original = law.reference["answer"]["counterexample"]
    other = next(row for row in law.grader["scope"]["inputs"] if row != original and row[0] != row[1])
    assert template.grade(law, {"true": False, "counterexample": other}).correct
