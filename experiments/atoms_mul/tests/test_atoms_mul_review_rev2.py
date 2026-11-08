"""Independent reproductions of machine-track boundary and persistence gaps."""

import json
from pathlib import Path

import pytest
from atoms_mul.analysis.analyze import analyze
from atoms_mul.machine.evaluate import run_sub
from atoms_mul.machine.lang import parse_program
from atoms_mul.machine.library import Library

from opulse.worlds_v2.computer.machine import State


@pytest.mark.parametrize("group", ["A", "B"])
def test_machine_boundary_can_keep_entry_as_one_visible_step(group):
    program = parse_program("sub main:\n  set r0, 7\n  add r0, r1\n  halt\nend")
    state = State()
    unfolded = run_sub("main", state, group=group, program=program)
    kept = run_sub("main", state, group=group, program=program,
                   boundary=frozenset({"main"}))
    assert (kept.outcome, kept.steps, kept.final_state) == (
        unfolded.outcome, unfolded.steps, unfolded.final_state)
    assert unfolded.steps == 2
    assert kept.boundary_steps == 1


def test_machine_library_round_trip_preserves_learner_visible_definition():
    program = parse_program("sub reusable:\n  set r0, 7\nend\n"
                            "sub main:\n  call reusable\nend\nsave reusable")
    library = Library()
    library.add_from_program(program, ["reusable"], "stage1")
    restored = Library.from_json(library.to_json())
    assert restored.listing() == library.listing()


def test_primary_decision_requires_complete_stage_two_episodes():
    records = [
        {"group": group, "episode": episode, "stage": 2, "task_id": "s2_t01",
         "correct": True, "length": 1, "defs_written": [], "saved": [],
         "mul_equivalent": [], "uses_library": False, "steps": 1,
         "boundary_steps": 1}
        for group in ("B", "C") for episode in range(40)
    ]
    result = analyze(records, resamples=10)
    assert result["decision"] == "diagnostic"


def test_primary_decision_requires_preregistered_episode_count():
    path = Path(__file__).resolve().parents[1] / "runs/dryrun_inventor/results.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    result = analyze(records, resamples=10)
    assert result["groups"]["B"]["episodes"] == 2
    assert result["groups"]["C"]["episodes"] == 2
    assert result["decision"] == "diagnostic"


def test_interface_describes_current_runs_and_runtime_dependencies():
    root = Path(__file__).resolve().parents[1]
    interface = (root / "INTERFACE.md").read_text()
    assert not (root / "runs/dryrun").exists()
    assert (root / "runs/dryrun_inventor").exists()
    assert "runs/dryrun/" not in interface
    assert "Only the Python standard library may be used." not in interface
