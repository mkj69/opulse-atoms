"""Machine-track contract tests and computer-world regression reproductions."""

import json
import random
import string

import pytest
from atoms_mul.machine.check import check_program
from atoms_mul.machine.compile import compile_sub, format_sub, size
from atoms_mul.machine.env import run_episode, state_for
from atoms_mul.machine.equiv import (
    _fast_projection,
    exhaustive_mul_check,
    is_mul_equivalent,
)
from atoms_mul.machine.evaluate import run_blocks, run_sub
from atoms_mul.machine.lang import MasmSyntaxError, parse_program
from atoms_mul.machine.library import Library
from atoms_mul.machine.policies import HELPER, Flaky, Inventor, Unroll
from atoms_mul.machine.prompts import SAVE_OFF, SAVE_ON, render_prompt
from atoms_mul.machine.tasks import ROOT, _true_value, generate

from opulse.atoms.values import Ok, Unknown
from opulse.worlds_v2.computer import runner
from opulse.worlds_v2.computer.machine import State


def tasks(stage):
    path = ROOT / "tasks" / f"machine_stage{stage}.json"
    data = json.loads(path.read_text())
    assert data == generate(stage)
    return data["tasks"]


def test_parse_format_and_fuzz():
    program = parse_program("# comment\nsub main:\n set r0, 255 # byte\nX:\n jnz r1, X\nend\n")
    formatted = parse_program(format_sub(program.defs[0]))
    assert [(line.op, line.args) for line in formatted.defs[0].lines] == [
        (line.op, line.args) for line in program.defs[0].lines]
    assert size(program.defs[0]) == 3
    rng = random.Random(45)
    for _ in range(1500):
        text = "".join(rng.choices(string.printable + "\x00", k=rng.randrange(150)))
        try:
            parse_program(text)
        except MasmSyntaxError as error:
            assert error.line >= 1 and error.col >= 1


@pytest.mark.parametrize("source,expected", [
    ("sub main:\n jmp X\nend", "unknown label"),
    ("sub main:\n X:\n X:\nend", "duplicate label"),
    ("sub main:\n call other\nend", "unknown target"),
    ("sub main:\n call other\nend\nsub other:\n call main\nend", "recursive call"),
    ("sub main:\n mul\nend", "mul is unavailable"),
    ("sub main:\n set r5, 2\nend", "invalid register"),
    ("sub main:\n load r0, 256\nend", "out of range"),
    ("sub main:\nend\nsave main", "cannot save main"),
    ("sub main:\nend\nsub helper:\nend\nsave helper\nsave helper", "duplicate save"),
    ("sub main:\nend\nsub one:\n call two\nend\nsub two:\nend\nsave one", "unsaved"),
])
def test_check_errors(source, expected):
    assert expected in " ".join(check_program(parse_program(source), "B", Library()))


def test_save_disabled_exact_message():
    assert "saving definitions is not available in this world" in check_program(
        parse_program("sub main:\nend\nsub MUL:\nend\nsave MUL"), "C", Library())


def test_library_layers_and_json_roundtrip():
    program = parse_program("sub main:\nend\nsub low:\n set r0, 1\nend\n"
                            "sub high:\n call low\nend\nsave high\nsave low")
    library = Library()
    library.add_from_program(program, program.saves, "example")
    assert library.get("low").layer == 1
    assert library.get("high").layer == 2
    assert Library.from_json(library.to_json()).to_json() == library.to_json()


def test_runner_consistency_and_boundary():
    program = parse_program("sub main:\n set r0, 3\n add r0, r1\nend")
    state = State((0, 7, 1, 0))
    for fuel in (0, 1, 2, 20):
        actual = run_sub("main", state, group="B", program=program, fuel=fuel)
        expected = runner.run(compile_sub(program.defs[0]), {"s": state}, fuel=fuel)
        assert (actual.outcome, actual.steps, actual.final_state) == (
            expected.outcome, expected.steps, expected.final_state)
    program = parse_program(HELPER + "\nsub main:\n call MUL\nend\nsave MUL")
    library = Library()
    library.add_from_program(program, ["MUL"], "t")
    assert library.get("MUL").body["node"] == "Blocks"
    assert "jump" in library.get("MUL").depends_on
    pasted = run_sub("main", State((0, 13, 12, 0)), group="B", program=program)
    reused = run_sub("main", State((0, 13, 12, 0)), group="B",
                     program=parse_program("sub main:\n call MUL\nend"), library=library,
                     boundary=frozenset({"MUL"}))
    assert (reused.outcome, reused.final_state, reused.steps) == (
        pasted.outcome, pasted.final_state, pasted.steps)
    assert reused.boundary_steps < reused.steps
    assert reused.calls["MUL"] == 1
    unbounded = run_sub("main", State((0, 13, 12, 0)), group="B",
                        program=parse_program("sub main:\n call MUL\nend"), library=library)
    assert (unbounded.outcome, unbounded.final_state, unbounded.steps) == (
        reused.outcome, reused.final_state, reused.steps)
    assert unbounded == run_sub("main", State((0, 13, 12, 0)), group="B",
                               program=parse_program("sub main:\n call MUL\nend"), library=library)
    assert isinstance(run_sub("main", state, group="B", program=program, fuel=1).outcome, Unknown)


def test_equivalence_projection_and_given_exclusion():
    program = parse_program(HELPER + "\nsub main:\n call MUL\nend")
    assert is_mul_equivalent("MUL", group="B", program=program)["equivalent"]
    assert not is_mul_equivalent("main", group="A", program=parse_program(
        "sub main:\n mul\nend"))["equivalent"]
    assert not is_mul_equivalent("MUL", group="B", program=parse_program(
        "sub MUL:\n set r0, 0\nend"))["equivalent"]


@pytest.mark.slow
def test_full_domain_exhaustive_check():
    assert exhaustive_mul_check("MUL", group="B", program=parse_program(HELPER)) == {
        "equivalent": True, "method": "exhaustive",
        "scope": "r1,r2 in [0,255], projection r0", "counterexample": None}


@pytest.mark.parametrize("group", ("A", "B"))
def test_fast_exhaustive_path_matches_original_runner_on_sample(group):
    body = compile_sub(parse_program(HELPER).defs[0])
    fast = _fast_projection(body, 200_000)
    for left, right in ((0, 0), (1, 255), (15, 16), (127, 128), (255, 255)):
        state = State((0, left, right, 0))
        original = run_blocks(body, state, {"MUL": body}, 200_000, group,
                              record_trace=False).outcome
        assert fast(state) == original
    assert _fast_projection(body, 1)(State((0, 8, 8, 0))) is None


def test_frozen_references_and_c_repeated_addition():
    first, second = tasks(1), tasks(2)
    assert len(first) == 24 and len(second) == 16
    assert [task["n"] for task in second] == [2] * 6 + [3] * 5 + [4] * 5
    banned = ("mul", "multipl", "times", "product", "twice", "double", "triple", "*", "\u00d7", "\u00b7")
    inventor = Inventor(first, second)
    for task in (*first, *second):
        assert task["id"].endswith(tuple(f"t{index:02}" for index in range(1, 25)))
        assert not any(word in task["statement"].lower() for word in banned)
        assert len(task["public_examples"]) == 3 and len(task["hidden_tests"]) == 12
        if task["family"] not in ("constant_scale",):
            def counts(test, task=task):
                if task["family"] == "dot":
                    return [test["memory"][str(32 + position)] for position in range(task["n"])]
                if task["family"] == "square":
                    return [test["registers"][1]]
                if task["family"] == "square_second":
                    return [test["registers"][2]]
                if task["family"] == "sum_first":
                    return [test["registers"][2] + test["registers"][3]]
                return [test["registers"][2]]

            assert all(value in counts(test) for value, test in
                       ((0, task["hidden_tests"][0]), (1, task["hidden_tests"][1])))
        assert sum(_true_value(task["family"], test["registers"],
                               {int(address): value for address, value in test["memory"].items()},
                               k=task["k"], n=task["n"]) >= 256
                   for test in task["hidden_tests"]) >= 6
        for test in (*task["public_examples"], *task["hidden_tests"]):
            assert 0 <= test["registers"][1] <= 255
            assert 0 <= test["registers"][2] <= 20
            if task["family"] == "square":
                assert test["registers"][1] <= 20
            if task["family"] == "sum_first":
                assert test["registers"][2] + test["registers"][3] <= 20
            if task["family"] == "sum_both":
                assert test["registers"][1] + test["registers"][3] <= 255
            assert all(0 <= value <= (255 if int(address) < 32 else 20)
                       for address, value in test["memory"].items())
        for group in ("A", "C"):
            inventor.reset(group=group, episode=0, seed=1000)
            program = parse_program(inventor.act({"task_id": task["id"], "library": ""}))
            assert not check_program(program, group, Library())
            for test in (*task["public_examples"], *task["hidden_tests"]):
                result = run_sub("main", state_for(test), group=group, program=program)
                assert isinstance(result.outcome, Ok)
                assert result.final_state.regs[0] == test["expected_r0"]


def test_prompt_only_controlled_differences():
    task = tasks(1)[0]
    a = render_prompt("A", Library(), task, [])
    b = render_prompt("B", Library(), task, [])
    c = render_prompt("C", Library(), task, [])
    mul_line = next(line for line in a.splitlines() if line.startswith("mul:"))
    assert a.replace(mul_line + "\n", "") == b
    assert b.replace(SAVE_ON, SAVE_OFF) == c
    assert "reference_masm" not in b


def test_scripted_and_feedback():
    variable = tasks(1)[8]
    for group in "BC":
        assert not run_episode(Unroll([variable]), group, 0, [variable], [], max_attempts=1)[0]["correct"]
    flaky = run_episode(Flaky([variable]), "B", 0, [variable], [])[0]
    assert flaky["correct"] and flaky["attempts"] == 3 and flaky["check_errors"] == 2


def test_dryrun_facts_from_committed_artifacts():
    cases = (("inventor", 2), ("nosave", 2), ("unroll", 1), ("flaky", 1))
    for policy, episodes in cases:
        name = f"dryrun_machine_{policy}"
        original = ROOT / "runs" / name
        assert json.loads((original / "config.json").read_text())["episodes"] == episodes
        rows = [json.loads(line) for line in (original / "results.jsonl").read_text().splitlines()]
        assert all(row["core_library"] == [] for row in rows if not row["saved"])
        assert all(row["core_library"] and row["core_library"][0]["status"] == "callable"
                   for row in rows if row["saved"])
        assert all(row["track"] == "machine" for row in rows)
        prompt_rows = [json.loads(line) for line in (original / "prompts.jsonl").read_text().splitlines()]
        assert all(row["track"] == "machine" for row in prompt_rows)
        if policy == "inventor":
            assert any("MUL" in row["saved"] and row["mul_equivalent"] for row in rows if row["group"] == "B")
            assert all(not row["saved"] for row in rows if row["group"] == "C")
            assert all(row["uses_library"] for row in rows if row["group"] == "B" and row["stage"] == 2)
            assert all(row["boundary_steps"] < row["steps"] for row in rows
                       if row["group"] == "B" and row["stage"] == 2)
            assert max(row["steps"] for row in rows if row["group"] == "A" and row["stage"] == 2) < min(
                row["steps"] for row in rows if row["group"] == "B" and row["stage"] == 2)
        if policy == "unroll":
            assert all(not row["correct"] for row in rows if row["group"] in "BC" and
                       row["family"] == "variable_scale")
        if policy == "flaky":
            assert all(row["correct"] and row["attempts"] == 3 and row["check_errors"] == 2
                       for row in rows)
