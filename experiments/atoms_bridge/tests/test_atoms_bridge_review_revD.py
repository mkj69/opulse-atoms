"""Independent regressions for bridge parsing and pre-registered analysis."""

import json
from pathlib import Path

import pytest
from atoms_bridge.env import LibraryView, _check
from atoms_bridge.machine import parse_program
from atoms_bridge.summary import analyze
from atoms_mul.machine.lang import parse_program as parse_masm

TASKS = Path(__file__).resolve().parents[2] / "atoms_mul" / "tasks" / "machine_stage2.json"


def _records(*, unrelated_tasks=False, unpaired=False):
    records = []
    task_ids = [task["id"] for task in json.loads(TASKS.read_text())["tasks"]]
    for group in ("A", "B"):
        for episode in range(40):
            for task_id in task_ids:
                records.append({
                    "group": group,
                    "stage": 2,
                    "episode": episode + (40 if unpaired and group == "B" else 0),
                    "task_id": f"unrelated-{task_id}" if unrelated_tasks else task_id,
                    "correct": group == "B", "length": 2 if group == "A" else 1,
                })
    return records


def test_analysis_refuses_synthetic_task_ids_outside_frozen_task_set():
    with pytest.raises(ValueError, match="task"):
        analyze(_records(unrelated_tasks=True), resamples=10)


def test_analysis_keeps_unpaired_forty_episode_arms_diagnostic():
    assert analyze(_records(unpaired=True), resamples=10)["decision"] == "diagnostic"


def test_parser_keeps_existing_xcall_named_label_legal():
    source = "sub main:\n  xcall:\n  set r0, 1\nend"
    assert parse_program(source) == parse_masm(source)


@pytest.mark.parametrize("reserved_name, instruction", [
    ("mul_scope", "xcall mul r1, r2 -> r0"),
    ("machine_add", "add r0, r1"),
])
def test_checker_refuses_subroutines_shadowing_bridge_runtime_atoms(reserved_name, instruction):
    source = f"sub main:\n  {instruction}\nend\nsub {reserved_name}:\n  halt\nend"
    library = LibraryView()
    library.group = "B"
    assert _check(parse_program(source), {}, "B", library)
