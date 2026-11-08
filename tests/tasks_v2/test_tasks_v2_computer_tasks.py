"""Frozen computer tasks and full-state grading (spec section 11.I3)."""

import json
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms.nodes import Block, Blocks, Call, Halt, Lit, Var, to_json
from opulse.atoms.values import Unknown
from opulse.tasks_v2.angles.computer import build_tasks, grade_computer, observed_input
from opulse.worlds_v2.computer.machine import REGISTERS
from opulse.worlds_v2.computer.verify import copy_program, mul_program

SAMPLES = Path(__file__).resolve().parents[2] / "worlds/tasks/computer@1"


def test_frozen_samples_and_six_angles():
    tasks = build_tasks()
    assert {task["angle"] for task in tasks} == {
        "compute", "invert", "decide", "describe", "induce", "create"}
    for task in tasks:
        assert json.loads((SAMPLES / f"{task['id'].split('/')[-1]}.json").read_text()) == task
    by_id = {task["id"].split("/")[-1]: task for task in tasks}
    assert grade_computer(by_id["compute"], 63)["correct"]
    assert grade_computer(by_id["compute_state"], {
        "regs": [6, 2, 0, 9], "mem": [0] * 256, "zero": True, "carry": False})["correct"]
    assert grade_computer(by_id["invert"], [3, 67, 131, 195])["correct"]
    assert grade_computer(by_id["invert_witness"], 67)["correct"]
    witness = grade_computer(by_id["decide"], True)["counterexample"]
    assert witness is not None
    assert grade_computer(by_id["decide"], {"equivalent": False, "counterexample": witness})["correct"]
    assert grade_computer(by_id["describe"], "multiply")["correct"]
    for task in (by_id["induce"], by_id["create"], by_id["create_reusable"]):
        assert grade_computer(task, to_json(mul_program()))["correct"]
    assert by_id["create_reusable"]["unfolded_reference_length"] > by_id["create_reusable"]["reference_length"]
    assert grade_computer(by_id["create_reusable"], mul_program())["length_savings"] > 0


def test_judging_uses_full_state_not_observation():
    task = next(task for task in build_tasks() if task["angle"] == "create")
    from opulse.worlds_v2.computer.verify import copy_program

    candidate = copy_program()
    isolated = {**task, "scope": [task["scope"][0]], "reference": to_json(candidate)}
    program = Blocks((), "copy", (("copy", Block((
        ("s", Call("write", (Var("s"), Lit(REGISTERS[0]),
                             Call("read", (Var("s"), Lit(REGISTERS[1])))))),
        ("s", Call("dec", (Var("s"), Lit(REGISTERS[2]))))), Halt(Var("s")))),))
    for observation in ("io", "all_registers"):
        projected = {**isolated, "observation": observation}
        assert not grade_computer(projected, program)["correct"]
        assert not grade_computer({**projected, "judge_view": "full_state"}, program)["correct"]
    compute = build_tasks()[0]
    assert set(observed_input(compute)) == {"r0", "r1", "r2"}
    assert set(observed_input({**compute, "observation": "all_registers"})) == {
        "r0", "r1", "r2", "r3"}


def test_compute_grades_bottom_and_rejects_unknown(monkeypatch):
    from opulse.tasks_v2.angles import computer

    task = next(item for item in build_tasks() if item["id"].endswith("/compute"))
    invalid = Blocks((), "bad", (("bad", Block((("s", Call("write", (
        Var("s"), Lit(REGISTERS[0]), Lit(999)))),), Halt(Var("s")))),))
    task = {**task, "program": to_json(invalid)}
    assert grade_computer(task, {"bottom": "invalid"})["correct"]
    assert not grade_computer(task, {"bottom": "other"})["correct"]
    valid = {**task, "program": to_json(mul_program())}
    assert grade_computer(valid, {"ok": {"t": "int", "v": 63}})["correct"]
    from dataclasses import replace

    outcome = computer._run(invalid, computer._decode(task["input"]))
    monkeypatch.setattr(computer, "_run", lambda *args, **kwargs: replace(outcome, outcome=Unknown("fuel")))
    assert not grade_computer(task, {"unknown": "fuel"})["correct"]


@given(st.permutations((3, 67, 131, 195)))
def test_all_solutions_is_order_independent_without_duplicates(permutation):
    task = next(item for item in build_tasks() if item["id"].endswith("/invert"))
    task = {**task, "domain": list(permutation)}
    assert grade_computer(task, list(reversed(permutation)))["correct"]
    assert not grade_computer(task, [3, 67, 131, 3])["correct"]


def test_create_and_induce_reject_extra_layer_zero_read():
    program = mul_program()
    label, block = program.blocks[0]
    altered = Blocks(program.vars, program.entry, ((label, Block(
        block.assigns + (("scratch", Call("read", (Var("s"), Lit(REGISTERS[0])))),),
        block.end)), *program.blocks[1:]))
    for angle in ("create", "induce"):
        task = next(item for item in build_tasks() if item["id"].endswith("/" + angle))
        task = {**task, "scope": [{**task["scope"][0], "regs": [0, 3, 2, 0]}]}
        assert not grade_computer(task, altered)["correct"]


def test_describe_checks_program_against_option_behavior():
    task = next(item for item in build_tasks() if item["id"].endswith("/describe"))
    task = {**task, "program": to_json(copy_program())}
    assert grade_computer(task, "copy")["correct"]
    assert not grade_computer(task, "multiply")["correct"]


def test_compute_projection_uses_truth_not_learner_view():
    task = next(item for item in build_tasks() if item["id"].endswith("/compute"))
    task = {**task, "judge_view": {"contract_projection": ["r0", "r1"]}}
    for observation in ("io", "all_registers"):
        projected = {**task, "observation": observation}
        assert grade_computer(projected, {"r0": 63, "r1": 7})["correct"]
        assert not grade_computer(projected, {"r0": 63, "r1": 8})["correct"]
