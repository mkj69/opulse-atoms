"""Harness contract tests with small frozen task subsets."""

import json
from pathlib import Path

from atoms_mul.harness.env import run_episode
from atoms_mul.harness.policies import Flaky, Inventor, NoSave, ScriptedPolicy, Unroll
from atoms_mul.harness.prompts import SAVE_OFF, SAVE_ON, render_prompt
from atoms_mul.kernel import Library, load_world

ROOT = Path(__file__).resolve().parents[1]


def tasks(stage):
    return json.loads((ROOT / "tasks" / f"stage{stage}.json").read_text())["tasks"]


class Fixed(ScriptedPolicy):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses

    def act(self, observation):
        return self.responses[min(observation["attempt"] - 1, len(self.responses) - 1)]


def test_grading_exact_wrong_and_unknown():
    task = next(task for task in tasks(1) if task["family"] == "variable_scale")
    correct = "op solve(a: Nat, b: Nat) -> Nat = mul(a, b)"
    assert run_episode(Fixed([correct]), "A", 0, [task], [], max_attempts=1)[0]["correct"]
    wrong = run_episode(Fixed(["op solve(a: Nat, b: Nat) -> Nat = add(a, b)"]), "A", 0,
                        [task], [], max_attempts=1)[0]
    assert not wrong["correct"] and wrong["steps"] is not None
    exhausted = run_episode(Fixed([correct]), "A", 0, [task], [], fuel=0,
                            max_attempts=1)[0]
    assert not exhausted["correct"] and exhausted["steps"] is None


def test_library_rules_and_feedback():
    task = next(task for task in tasks(1) if task["family"] == "variable_scale")
    helper = "op rep(n: Nat, x: Nat) -> Nat = if is_zero(n) then 0 else add(x, rep(pred(n), x))\n"
    text = helper + "op solve(a: Nat, b: Nat) -> Nat = rep(a, b)\nsave rep"
    assert run_episode(Fixed([text]), "C", 0, [task], [], max_attempts=1)[0]["check_errors"] == 1
    wrong_save = helper + "op solve(a: Nat, b: Nat) -> Nat = add(a, b)\nsave rep"
    result = run_episode(Fixed([wrong_save, "op solve(a: Nat, b: Nat) -> Nat = add(a, b)"]),
                         "B", 0, [task], [], max_attempts=2)[0]
    assert result["saved"] == [] and result["library_size_after"] == 0
    saved = run_episode(Fixed(["op solve(a: Nat, b: Nat) -> Nat = missing(a)", text]),
                        "B", 0, [task], [], max_attempts=2)[0]
    assert saved["saved"] == ["rep"] and saved["check_errors"] == 1
    assert "rep" in saved["mul_equivalent"]
    wrapped = run_episode(Fixed(["op times2(a: Nat, b: Nat) -> Nat = mul(a, b)\nop solve(a: Nat, b: Nat) -> Nat = times2(a, b)"]),
                          "A", 0, [task], [], max_attempts=1)[0]
    assert wrapped["correct"] and wrapped["mul_equivalent"] == []


def test_inventor_reuse_and_length():
    first = next(task for task in tasks(1) if task["family"] == "variable_scale")
    second = next(task for task in tasks(1) if task["family"] == "constant_scale")
    dot = tasks(2)[0]
    inventor = run_episode(Inventor([first, second], [dot]), "B", 0,
                           [first, second], [dot])
    nosave = run_episode(NoSave([first, second], [dot]), "B", 0,
                         [first, second], [dot])
    assert all(row["correct"] for row in inventor)
    assert any("rep" in row["mul_equivalent"] for row in inventor)
    assert inventor[-1]["uses_library"] and inventor[-1]["library_calls"] > 0
    assert inventor[-1]["boundary_steps"] < inventor[-1]["steps"]
    assert inventor[-1]["length"] < nosave[-1]["length"]
    assert sum(row["length"] for row in inventor) < sum(row["length"] for row in nosave)
    control = run_episode(Inventor([first], [dot]), "C", 0, [first], [dot])
    assert all(row["library_size_after"] == 0 and not row["saved"] for row in control)


def test_scripted_failures():
    variable = next(task for task in tasks(1) if task["family"] == "variable_scale")
    for group in ("B", "C"):
        assert not run_episode(Unroll([variable]), group, 0, [variable], [])[0]["correct"]
    flaky = run_episode(Flaky([variable]), "B", 0, [variable], [])[0]
    assert flaky["correct"] and flaky["attempts"] == 3 and flaky["check_errors"] == 2


def test_observation_feedback_and_api_exhaustion():
    task = next(task for task in tasks(1) if task["family"] == "variable_scale")

    class Inspect(Fixed):
        def act(self, observation):
            assert "hidden_tests" not in observation["task"]
            assert "reference_aml" not in observation["task"]
            if observation["attempt"] == 2:
                assert observation["feedback"] and "expected" in observation["prompt"]
                assert "hidden test failed" in observation["feedback"][0]
            return super().act(observation)

    run_episode(Inspect(["op solve(a: Nat, b: Nat) -> Nat = add(a, b)",
                         "op solve(a: Nat, b: Nat) -> Nat = mul(a, b)"]), "A", 0, [task], [])

    class FailingAPI(ScriptedPolicy):
        name = "llm"

        def act(self, observation):
            raise OSError("temporary service error")

    result = run_episode(FailingAPI(), "B", 0, [task], [], max_attempts=3)[0]
    assert result["api_error"] and result["attempts"] == 1
    assert result["check_errors"] == 0 and not result["correct"]


def test_prompt_controlled_differences():
    task = tasks(1)[0]
    a = render_prompt(load_world("A"), Library(), task, [], True)
    b = render_prompt(load_world("B"), Library(), task, [], True)
    c = render_prompt(load_world("C"), Library(), task, [], False)
    mul_line = next(line for line in a.splitlines() if line.startswith("op mul("))
    assert a.replace(mul_line + "\n", "") == b
    assert b.replace(SAVE_ON, SAVE_OFF) == c
    assert "multiplication" not in b.lower() + c.lower()
    assert "save" not in c.lower()
    for banned in ("mul", "multipl", "times", "product", "twice", "double", "triple", "*", "\u00d7", "\u00b7"):
        assert banned not in b.lower() and banned not in c.lower()
    assert "hidden" in b and "Public examples" in b and "empty" in b
