"""Independent computer, promotion and declaration properties (spec sections 8, 11, 15)."""

import json
import os
from copy import deepcopy

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.values import Ok
from opulse.tasks_v2.angles.computer import build_tasks, grade_computer, observed_input
from opulse.tasks_v2.decl import WorldFile, validate
from opulse.worlds_v2.computer.kernel_scope import run_kernel
from opulse.worlds_v2.computer.machine import State
from opulse.worlds_v2.computer.runner import run
from opulse.worlds_v2.computer.verify import (
    ARTIFACT,
    DECLARATION,
    fast_mul,
    mul_program,
    promote,
    step_formula,
    verify_mul,
)


@settings(derandomize=True, max_examples=16, deadline=None)
@given(st.integers(0, 255), st.integers(0, 255), st.integers(0, 255),
       st.booleans(), st.booleans())
def test_kernel_runner_fast_path_same_state_and_steps(left, right, saved, zero, carry):
    state = State((saved, left, right, saved), bytes(range(256)), zero, carry)
    program = mul_program()
    actual = run_kernel(program, state)
    independent = run(program, {"s": state}, record_trace=False)
    fast_state, fast_steps = fast_mul(state)
    assert isinstance(actual.outcome, Ok) and isinstance(independent.outcome, Ok)
    assert actual.outcome.value == independent.outcome.value == fast_state
    assert actual.final_state == independent.final_state == fast_state
    assert actual.steps == independent.steps == fast_steps == step_formula(left, right)
    assert actual.jumps == independent.jumps


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from(("world_hash", "method")), st.text(alphabet="abc123", min_size=1, max_size=8))
def test_promotion_rejects_changed_world_or_sampled_method(field, mutation):
    record = json.loads(ARTIFACT.read_text())
    assert promote({**record, "status": "verified"})["status"] == "promoted"
    evidence = {**record["evidence"], field: mutation if field == "world_hash" else "sampled"}
    with pytest.raises(ValueError):
        promote({**record, "status": "verified", "evidence": evidence})


@settings(derandomize=True, max_examples=8, deadline=None)
@given(st.sampled_from(("rename_sort", "illegal_enter", "duplicate_operation")),
       st.text(alphabet="xyz", min_size=2, max_size=6))
def test_world_declaration_mutations_produce_validator_problems(mutation, suffix):
    document = json.loads(DECLARATION.read_text())
    assert validate(WorldFile.from_dict(document)) == []
    document = deepcopy(document)
    if mutation == "rename_sort":
        document["objects"][0]["name"] = "missing_" + suffix
    elif mutation == "illegal_enter":
        document["operations"][0]["inputs"][0]["enter"] = "invalid(" + suffix
    else:
        document["operations"].append(deepcopy(document["operations"][0]))
    problems = validate(WorldFile.from_dict(document))
    assert problems
    if mutation == "rename_sort":
        assert any("unknown sort" in problem for problem in problems)
    elif mutation == "illegal_enter":
        assert any("illegal enter" in problem for problem in problems)
    else:
        assert any("duplicate operation" in problem for problem in problems)


@settings(derandomize=True, max_examples=8, deadline=None)
@given(st.sampled_from(("compute", "compute_state", "invert_witness", "describe",
                        "induce", "create")))
def test_computer_grades_reference_and_rejects_unknown(task_name):
    task = next(item for item in build_tasks() if item["id"].endswith("/" + task_name))
    answer = {"compute": 63, "compute_state": {"regs": [6, 2, 0, 9], "mem": [0] * 256,
                                                "zero": True, "carry": False},
              "invert_witness": 3, "describe": "multiply",
              "induce": task.get("reference"), "create": task.get("reference")}[task_name]
    assert grade_computer(task, answer)["correct"]
    assert not grade_computer(task, {"unknown": "fuel"})["correct"]


@settings(derandomize=True, max_examples=8, deadline=None)
@given(st.integers(0, 255), st.integers(0, 255))
def test_computer_witnesses_and_wrong_counterexamples(left, right):
    tasks = {item["id"].split("/")[-1]: item for item in build_tasks()}
    witness = deepcopy(tasks["invert_witness"])
    witness["input"]["regs"][2] = right
    witness["target"] = left * right % 256
    witness["domain"] = list(dict.fromkeys((left, (left + 1) % 256, (left + 127) % 256)))
    assert grade_computer(witness, left)["correct"]
    nonmembers = [candidate for candidate in witness["domain"]
                  if candidate * right % 256 != witness["target"]]
    if nonmembers:
        assert not grade_computer(witness, nonmembers[left % len(nonmembers)])["correct"]


def test_computer_rechecks_counterexample():
    decision = next(item for item in build_tasks() if item["angle"] == "decide")
    matching = next(state for state in decision["scope"] if state["regs"][1:3] == [7, 1])
    decision = {**decision, "scope": [matching, decision["scope"][0]]}
    found = grade_computer(decision, True)["counterexample"]
    assert found is not None
    assert grade_computer(decision, {"equivalent": False, "counterexample": found})["correct"]
    assert not grade_computer(decision, {"equivalent": False, "counterexample": matching})["correct"]


@settings(derandomize=True, max_examples=8, deadline=None)
@given(st.integers(0, 31), st.integers(1, 15))
def test_computer_solution_set_contains_exactly_all_scope_members(left, right):
    task = deepcopy(next(item for item in build_tasks() if item["id"].endswith("/invert")))
    task["input"]["regs"][2] = right
    task["target"] = left * right % 256
    task["domain"] = list(range(32))
    matches = [item for item in task["domain"] if item * right % 256 == task["target"]]
    assert grade_computer(task, matches)["correct"]
    assert not grade_computer(task, matches + [255])["correct"]


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from(("compute", "compute_state", "create")),
       st.sampled_from(("io", "all_registers")), st.integers(0, 5))
def test_computer_observation_and_boundary_do_not_change_verdict(task_name, view, depth):
    task = next(item for item in build_tasks() if item["id"].endswith("/" + task_name))
    answer = (task["reference"] if task_name == "create" else 63 if task_name == "compute" else
              {"regs": [6, 2, 0, 9], "mem": [0] * 256, "zero": True, "carry": False})
    altered = {**task, "observation": view,
               "boundary": {"depth": depth, "open_names": ["MUL"]}}
    assert grade_computer(altered, answer) == grade_computer(task, answer)
    if "input" in altered:
        assert set(observed_input(altered)) <= {"r0", "r1", "r2", "r3"}


def test_slow_exhaustive_evidence_when_requested():
    if os.environ.get("OPULSE_SLOW") != "1":
        pytest.skip("65,536 pairs run only with OPULSE_SLOW=1")
    assert verify_mul() == json.loads(ARTIFACT.read_text())
