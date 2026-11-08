"""Adversarial reproductions for the pre-run review."""

import io
import json
from pathlib import Path

import pytest
from atoms_mul.analysis.analyze import analyze
from atoms_mul.analysis.llm_policy import LLMPolicy
from atoms_mul.harness.env import run_episode
from atoms_mul.harness.run import run
from atoms_mul.kernel import (
    AmlSyntaxError,
    Library,
    check_program,
    load_world,
    parse_program,
)


def task():
    return {
        "id": "review", "family": "constant_scale", "statement": "Return x.",
        "params": ["x"], "solve_signature": "solve(x)",
        "public_examples": [{"args": [1], "expected": 1}],
        "hidden_tests": [{"args": [2], "expected": 2}],
    }


class Fixed:
    name = "fixed"

    def __init__(self, response):
        self.response = response

    def reset(self, **kwargs):
        pass

    def act(self, observation):
        return self.response


def test_review_oversized_literal_is_rejected_without_crashing():
    response = "op solve(x: Nat) -> Nat = " + "9" * 5000
    result = run_episode(Fixed(response), "B", 0, [task()], [], max_attempts=1)
    assert result[0]["check_errors"] == 1


def test_review_deep_expression_is_rejected_without_crashing():
    response = "op solve(x: Nat) -> Nat = " + "(" * 400 + "x" + ")" * 400
    result = run_episode(Fixed(response), "B", 0, [task()], [], max_attempts=1)
    assert result[0]["check_errors"] == 1


def test_review_duplicate_save_is_check_error_not_episode_crash():
    response = "op helper(x: Nat) -> Nat = x\ndef solve(x) = x\nsave helper\nsave helper"
    result = run_episode(Fixed(response), "B", 0, [task()], [], max_attempts=1)
    assert result[0]["check_errors"] == 1


def test_review_resume_rejects_stale_fuel_checkpoint(monkeypatch, tmp_path):
    from atoms_mul.harness import run as runner

    monkeypatch.setattr(runner, "run_episode", lambda *args, **kwargs: [])
    destination = tmp_path / "real"
    run(policy="inventor", groups=["B"], episodes=1, run_id="real", out=tmp_path, fuel=1)
    config = json.loads((destination / "config.json").read_text())
    checkpoint = {"group": "B", "episode": 0, "prompts": [], "records": [
        {"group": "B", "episode": 0, "stage": 2, "task_id": "stale",
         "correct": True, "attempts": 1, "length": 1, "steps": 0,
         "boundary_steps": 0, "uses_library": False, "mul_equivalent": []}
    ]}
    (destination / "episodes.jsonl").write_text(json.dumps({"config": config}) + "\n" +
                                                 json.dumps(checkpoint) + "\n")
    with pytest.raises(ValueError, match="config mismatch: fuel"):
        run(policy="inventor", groups=["B"], episodes=1, run_id="real",
            out=tmp_path, resume=True, fuel=0)


def test_review_group_sampling_seeds_are_independent(monkeypatch):
    seeds = []

    def opener(request, timeout):
        seeds.append(json.loads(request.data)["seed"])
        return io.BytesIO(b'{"choices":[{"message":{"content":"op solve(x: Nat) -> Nat = x"}}]}')

    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    monkeypatch.setattr("urllib.request.urlopen", opener)
    actor = LLMPolicy(allow_api=True, model="fake")
    for group in ("B", "C"):
        run_episode(actor, group, 0, [task()], [], max_attempts=1)
    assert seeds[0] != seeds[1]
    assert seeds == [101000, 201000]


def test_review_malformed_api_response_retries_three_times(monkeypatch):
    attempts = []

    def opener(request, timeout):
        attempts.append(json.loads(request.data)["seed"])
        if len(attempts) < 3:
            return io.BytesIO(b"not json")
        return io.BytesIO(b'{"choices":[{"message":{"content":"op solve(x: Nat) -> Nat = x"}}]}')

    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    monkeypatch.setattr("urllib.request.urlopen", opener)
    actor = LLMPolicy(allow_api=True, model="fake")
    actor.reset(group="B", episode=0, seed=1000)
    assert actor.act({"prompt": "same question"}) == "op solve(x: Nat) -> Nat = x"
    assert attempts == [1000] * 3


def test_review_resume_completed_run_does_not_repeat_model_calls(monkeypatch, tmp_path):
    from atoms_mul.harness.run import POLICIES

    calls = []

    class CountingPolicy:
        def __init__(self, *args):
            pass

        def reset(self, **kwargs):
            pass

        def act(self, observation):
            calls.append(observation["task_id"])
            params = ", ".join(f"{name}: Nat" for name in observation["task"]["params"])
            return f"op solve({params}) -> Nat = 0"

    monkeypatch.setitem(POLICIES, "review_count", CountingPolicy)
    options = {"policy": "review_count", "groups": ["C"], "episodes": 1,
               "run_id": "real", "out": tmp_path, "max_attempts": 1}
    run(**options)
    first_count = len(calls)
    assert first_count == 40
    run(**options, resume=True)
    assert len(calls) == first_count


def test_review_resume_can_grow_groups_and_episodes_without_repeating_pairs(monkeypatch, tmp_path):
    from atoms_mul.harness.run import POLICIES

    calls = []

    class CountingPolicy:
        def __init__(self, *args):
            pass

        def reset(self, **kwargs):
            calls.append((kwargs["group"], kwargs["episode"]))

        def act(self, observation):
            params = ", ".join(f"{name}: Nat" for name in observation["task"]["params"])
            return f"op solve({params}) -> Nat = 0"

    monkeypatch.setitem(POLICIES, "review_count", CountingPolicy)
    options = {"policy": "review_count", "groups": ["B"], "episodes": 1,
               "run_id": "growth", "out": tmp_path, "max_attempts": 1}
    run(**options)
    run(**{**options, "groups": ["B", "C"], "episodes": 2}, resume=True)
    assert calls == [("B", 0), ("B", 1), ("C", 0), ("C", 1)]
    assert len((tmp_path / "growth" / "results.jsonl").read_text().splitlines()) == 160


def test_review_checkpoint_survives_failed_final_write(monkeypatch, tmp_path):
    from atoms_mul.harness import run as runner

    monkeypatch.setattr(runner, "run_episode", lambda *args, **kwargs: [])
    original_replace = runner.os.replace

    def replace(source, destination):
        if destination.name == "results.jsonl":
            raise OSError("simulated full disk")
        return original_replace(source, destination)

    monkeypatch.setattr(runner.os, "replace", replace)
    with pytest.raises(OSError, match="full disk"):
        run(policy="inventor", groups=["B"], episodes=1, run_id="real", out=tmp_path)
    assert (tmp_path / "real" / "episodes.jsonl").exists()


def test_review_api_errors_cannot_make_one_episode_decisive():
    records = [
        {"group": group, "episode": episode, "stage": 2, "task_id": f"dot{index}",
         "correct": index < 8 and episode == 0, "api_error": episode != 0,
         "length": 1, "defs_written": [], "saved": [], "mul_equivalent": [],
         "uses_library": False, "steps": 1, "boundary_steps": 1}
        for group in ("B", "C") for episode in range(40) for index in range(16)
    ]
    result = analyze(records, resamples=20)
    assert result["decision"] == "diagnostic"


def test_review_real_run_without_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        LLMPolicy(allow_api=True, model="fake")


def test_review_missing_api_key_does_not_create_run(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        run(policy="llm", groups=["B"], episodes=1, run_id="never", out=tmp_path,
            allow_api=True, model="fake")
    assert not (tmp_path / "never").exists()


def test_review_malformed_api_keys_are_retried(monkeypatch):
    replies = iter((b'{"choices": []}', b'{"choices": [{"message": {}}]}',
                    b'{"choices": [{"message": {"content": "op solve(x: Nat) -> Nat = x"}}]}'))
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: io.BytesIO(next(replies)))
    actor = LLMPolicy(allow_api=True, model="fake")
    assert actor.act({"prompt": "question"}) == "op solve(x: Nat) -> Nat = x"


def test_review_resume_rejects_changed_config_fields(monkeypatch, tmp_path):
    from atoms_mul.harness import run as runner

    monkeypatch.setattr(runner, "run_episode", lambda *args, **kwargs: [])
    options = {"policy": "inventor", "groups": ["B"], "episodes": 1,
               "run_id": "real", "out": tmp_path}
    run(**options)
    destination = tmp_path / "real"
    original = json.loads((destination / "config.json").read_text())
    for field, value in (("policy", "nosave"), ("fuel", 0), ("max_attempts", 1),
                         ("model", "different"), ("hashes", {})):
        header = {"config": {**original, field: value}}
        (destination / "episodes.jsonl").write_text(json.dumps(header) + "\n")
        with pytest.raises(ValueError, match=f"config mismatch: {field}"):
            run(**options, resume=True)
    (destination / "episodes.jsonl").unlink()
    for field, value in (("fuel", 0), ("max_attempts", 1)):
        with pytest.raises(ValueError, match=f"config mismatch: {field}"):
            run(**{**options, field: value}, resume=True)


def test_review_api_error_episode_threshold():
    from atoms_mul.analysis.analyze import episode_outcomes

    task_root = Path(__file__).resolve().parents[1] / "tasks"
    ids = {stage: [task["id"] for task in json.loads(
        (task_root / f"stage{stage}.json").read_text())["tasks"]] for stage in (1, 2)}
    records = [{"group": "B", "episode": episode, "stage": stage, "task_id": task_id,
                "correct": True, "api_error": index < errors, "length": 0,
                "steps": 1, "boundary_steps": 1}
               for episode, errors in ((0, 2), (1, 3))
               for stage, task_ids in ids.items() for index, task_id in enumerate(task_ids)]
    for record in records:
        record["api_error"] = record["stage"] == 2 and record["api_error"]
    first, second = episode_outcomes(records)
    assert first["stage2_accuracy"] == 1
    assert second["stage2_accuracy"] is None


def test_review_stage_two_requires_variable_pairwise_products():
    tasks_path = Path(__file__).resolve().parents[1] / "tasks" / "stage2.json"
    tasks = json.loads(tasks_path.read_text())["tasks"]
    assert len(tasks) == 16
    assert sorted(len(item["params"]) // 2 for item in tasks) == [2] * 6 + [3] * 5 + [4] * 5
    for item in tasks:
        assert item["params"] == [name for pair in range(1, len(item["params"]) // 2 + 1)
                                  for name in (f"q{pair}", f"p{pair}")]


def test_review_parser_only_raises_syntax_errors_on_arbitrary_input():
    import random

    rng = random.Random(20261104)
    samples = ["op solve(x: Nat) -> Nat = " + "(" * 400 + "x" + ")" * 400,
               "op solve(x: Nat) -> Nat = " + "9" * 5000,
               "op solve(x: Nat) -> Nat = " + "let x = " * 400 + "0" + " in x" * 400,
               "op solve(x: Nat) -> Nat = " + "add(" * 400 + "x" + ", x)" * 400,
               "op solve(x: Nat) -> Nat = " + "if x then " * 400 + "0" + " else 0" * 400]
    samples += ["".join(rng.choices("abc0123456789 ()=,\n#\u00e9", k=rng.randrange(500)))
                for _ in range(200)]
    for sample in samples:
        try:
            parse_program(sample)
        except AmlSyntaxError:
            pass  # any other exception escapes and fails the test


@pytest.mark.parametrize("expression", [
    "(" * 201 + "x" + ")" * 201,
    "add(" * 201 + "x" + ", x)" * 201,
    "let x = " * 201 + "0" + " in x" * 201,
    "if x then " * 201 + "0" + " else 0" * 201,
])
def test_review_nested_forms_report_syntax_position(expression):
    with pytest.raises(AmlSyntaxError, match="expression nested too deeply at line 1, column"):
        parse_program("op solve(x: Nat) -> Nat = " + expression)


@pytest.mark.parametrize("literal", ["0" * 11, "1000000001", "9" * 5000])
def test_review_literal_bounds_report_syntax_position(literal):
    with pytest.raises(AmlSyntaxError, match="literal too large at line 1, column 27"):
        parse_program("op solve(x: Nat) -> Nat = " + literal)




def test_review_bool_and_unknown_are_not_graded_as_integer_success():
    for response in ("op solve(x: Nat) -> Nat = eq(x, x)",
                     "op solve(x: Nat) -> Nat = if is_zero(x) then 0 else solve(x)"):
        record = run_episode(Fixed(response), "C", 0, [task()], [], max_attempts=1)[0]
        assert not record["correct"]


def test_review_mul_and_save_rejected_in_disallowed_worlds():
    assert any("unknown call target mul" in error for error in
               check_program(parse_program("op solve(x: Nat) -> Nat = mul(x, x)"),
                             load_world("B"), Library()))
    assert any("saving definitions is not available" in error for error in
               check_program(parse_program("op solve(x: Nat) -> Nat = x\nsave solve"),
                             load_world("C"), Library()))
