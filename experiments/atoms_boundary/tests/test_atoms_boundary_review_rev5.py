"""Regression tests for boundary-experiment analysis and resume."""

import json
import re

import pytest
from atoms_boundary import prompts
from atoms_boundary import run as runner
from atoms_boundary.analysis import analyze
from atoms_boundary.prompts import boundary_for


def test_confirmatory_decision_requires_three_distinct_forms_per_episode():
    rows = [
        {
            "episode": episode,
            "form": 0,
            "records": [
                {
                    "item_id": index,
                    "boundary": boundary_for(index, 0),
                    "status": "incorrect",
                    "value_correct": boundary_for(index, 0) == 0,
                    "adds_correct": False,
                }
                for index in range(48)
            ],
        }
        for episode in range(40)
        for _ in range(3)
    ]
    report = analyze(rows, resamples=12)
    assert report["decision"] != "B0 better"


def test_resume_rejects_changed_prompt_renderer(tmp_path, monkeypatch):
    runner.run(out=tmp_path)
    original_render = runner.render
    monkeypatch.setattr(
        runner,
        "render",
        lambda item, boundary: original_render(item, boundary) + "\nNew instructions",
    )
    with pytest.raises(ValueError, match="configuration mismatch"):
        runner.run(episodes=2, out=tmp_path, resume=True)


@pytest.mark.parametrize("tamper", ("missing", "duplicate", "wrong_boundary"))
def test_confirmatory_decision_requires_exact_item_assignments(tamper):
    rows = [
        {"episode": episode, "form": form, "records": [
            {"item_id": index, "boundary": boundary_for(index, form),
             "status": "incorrect", "value_correct": boundary_for(index, form) == 0,
             "adds_correct": False}
            for index in range(48)
        ]}
        for episode in range(40) for form in range(3)
    ]
    if tamper == "missing":
        rows[0]["records"].pop()
        rows[0]["records"].append(dict(rows[0]["records"][0]))
    elif tamper == "duplicate":
        rows[0]["records"][1]["item_id"] = 0
    else:
        rows[0]["records"][0]["boundary"] = 1
    assert analyze(rows, resamples=12)["decision"] != "B0 better"


def test_resume_rejects_changed_grader_and_boundary(tmp_path, monkeypatch):
    runner.run(out=tmp_path)
    original_grade = runner.grade
    monkeypatch.setattr(runner, "grade", lambda item, reply: original_grade(item, reply))
    with pytest.raises(ValueError, match="configuration mismatch"):
        runner.run(episodes=2, out=tmp_path, resume=True)
    monkeypatch.undo()
    monkeypatch.setattr(runner, "BOUNDARIES", tuple(reversed(runner.BOUNDARIES)))
    with pytest.raises(ValueError, match="configuration mismatch"):
        runner.run(episodes=2, out=tmp_path, resume=True)


def test_resume_rejects_changed_answer_pattern(tmp_path, monkeypatch):
    runner.run(out=tmp_path)
    monkeypatch.setattr(prompts, "ANSWER", re.compile(r"\Avalue=(\d+); adds=(\d+)\Z"))
    with pytest.raises(ValueError, match="configuration mismatch"):
        runner.run(episodes=2, out=tmp_path, resume=True)


def test_checkpoint_resume_rejects_changed_model_settings(tmp_path, monkeypatch):
    runner.run(out=tmp_path)
    directory = tmp_path / "dryrun_oracle"
    config = json.loads((directory / "config.json").read_text(encoding="ascii"))
    (directory / "episodes.jsonl").write_text(
        json.dumps({"config": config}) + "\n", encoding="ascii"
    )
    monkeypatch.setattr(runner, "TEMPERATURE", 0.1)
    with pytest.raises(ValueError, match="configuration mismatch"):
        runner.run(episodes=2, out=tmp_path, resume=True)
