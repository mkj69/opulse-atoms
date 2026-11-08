"""Independent review reproductions for frozen-task inference eligibility."""

import json
from pathlib import Path

import pytest
from atoms_kinds.harness import analyze as analyze_kinds
from atoms_mul.analysis.analyze import analyze


@pytest.mark.parametrize("track", ["aml", "machine"])
@pytest.mark.parametrize("replaced_stage", [1, 2])
def test_foreign_task_id_cannot_produce_primary_verdict(replaced_stage, track):
    task_root = Path(__file__).resolve().parents[1] / "tasks"
    prefix = "machine_" if track == "machine" else ""
    frozen_ids = {stage: [task["id"] for task in json.loads(
        (task_root / f"{prefix}stage{stage}.json").read_text())["tasks"]]
        for stage in (1, 2)}
    records = []
    for group in ("B", "C"):
        for episode in range(40):
            for stage, task_ids in frozen_ids.items():
                for task_index, task_id in enumerate(task_ids):
                    if group == "B" and stage == replaced_stage and task_index == 0:
                        task_id = "not_a_frozen_task"
                    correct = stage == 2 and group == "B"
                    records.append({
                        "track": track, "group": group, "episode": episode, "stage": stage,
                        "task_id": task_id, "correct": correct, "length": 1,
                        "defs_written": [], "saved": [], "mul_equivalent": [],
                        "uses_library": False,
                        "steps": 1 if correct else None,
                        "boundary_steps": 1 if correct else None,
                    })
    assert analyze(records, resamples=8)["decision"] == "diagnostic"


def test_kinds_rejects_forty_episodes_with_wrong_indexes():
    root = Path(__file__).resolve().parents[2] / "atoms_kinds" / "tasks"
    tasks = {stage: [task["id"] for task in json.loads(
        (root / f"stage{stage}.json").read_text())["tasks"]] for stage in (1, 2)}
    records = [
        {"group": group, "episode": episode, "stage": stage, "task_id": task_id,
         "correct": group == "K2", "api_error": False, "invented": [], "reused": [],
         "length": 1, "steps": 1, "boundary_steps": 1}
        for group in ("K1", "K2")
        for episode in (range(40) if group == "K1" else range(40, 80))
        for stage, task_ids in tasks.items() for task_id in task_ids
    ]
    assert analyze_kinds(records, resamples=8)["primary"]["decision"] == "diagnostic"
