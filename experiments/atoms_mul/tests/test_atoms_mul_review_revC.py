"""Independent-oracle regression for the cross-kernel comparison."""

import json
from importlib import import_module

import pytest
from atoms_mul.harness import run as runner
from atoms_mul.kernel.core_backend import _reference_operation, core_evaluate
from atoms_mul.kernel.worlds import load_world
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms.values import Bottom, Ok


def test_core_reference_does_not_inherit_broken_aml_operation(monkeypatch):
    local_evaluator = import_module("atoms_mul.kernel.evaluate")
    original_compute = local_evaluator.compute

    def broken_compute(name, args):
        if name == "mul":
            return True, 7
        return original_compute(name, args)

    monkeypatch.setattr(local_evaluator, "compute", broken_compute)
    result, _ = core_evaluate("mul", (2, 3), world=load_world("A"))
    assert result.value == 6


@given(st.sampled_from(("add", "sub", "succ", "pred", "is_zero", "eq", "lt", "mul")),
       st.integers(min_value=-1, max_value=1_000_000_001),
       st.integers(min_value=-1, max_value=1_000_000_001))
def test_reference_atoms_match_documented_aml_operations(name, left, right):
    from atoms_mul.kernel.ops import compute

    arguments = (left,) if name in ("succ", "pred", "is_zero") else (left, right)
    valid, payload = compute(name, arguments)
    expected = Ok(payload) if valid else Bottom(payload)
    assert _reference_operation(name, arguments) == expected


def test_resume_reruns_checkpoint_missing_all_task_records(tmp_path):
    options = {"policy": "nosave", "groups": ("C",), "episodes": 1,
               "run_id": "incomplete", "out": tmp_path}
    destination = runner.run(**options)
    config = json.loads((destination / "config.json").read_text(encoding="utf-8"))
    checkpoint = destination / "episodes.jsonl"
    checkpoint.write_text(json.dumps({"config": config}) + "\n" + json.dumps({
        "group": "C", "episode": 0, "records": [], "prompts": []}) + "\n", encoding="utf-8")
    runner.run(**options, resume=True)
    assert len((destination / "results.jsonl").read_text().splitlines()) == 40
    assert len((destination / "prompts.jsonl").read_text().splitlines()) >= 40


@pytest.mark.parametrize("damage", ("missing_result", "missing_record_field",
                                  "missing_prompt", "wrong_attempt"))
def test_resume_reruns_partially_saved_episode(tmp_path, damage):
    options = {"policy": "nosave", "groups": ("C",), "episodes": 1,
               "run_id": damage, "out": tmp_path}
    destination = runner.run(**options)
    config = json.loads((destination / "config.json").read_text())
    records = [json.loads(line) for line in (destination / "results.jsonl").read_text().splitlines()]
    prompts = [json.loads(line) for line in (destination / "prompts.jsonl").read_text().splitlines()]
    if damage == "missing_result":
        records.pop()
    elif damage == "missing_record_field":
        records[0].pop("correct")
    elif damage == "missing_prompt":
        prompts.pop()
    else:
        records[0]["attempts"] += 1
    checkpoint = destination / "episodes.jsonl"
    checkpoint.write_text(json.dumps({"config": config}) + "\n" + json.dumps({
        "group": "C", "episode": 0, "records": records, "prompts": prompts}) + "\n")
    runner.run(**options, resume=True)
    assert not checkpoint.exists()
    assert len((destination / "results.jsonl").read_text().splitlines()) == 40


def test_resume_reuses_complete_episode_with_all_attempt_prompts(tmp_path, monkeypatch):
    options = {"policy": "nosave", "groups": ("C",), "episodes": 1,
               "run_id": "complete", "out": tmp_path}
    destination = runner.run(**options)
    config = json.loads((destination / "config.json").read_text())
    records = [json.loads(line) for line in (destination / "results.jsonl").read_text().splitlines()]
    prompts = [json.loads(line) for line in (destination / "prompts.jsonl").read_text().splitlines()]
    (destination / "episodes.jsonl").write_text(json.dumps({"config": config}) + "\n" + json.dumps({
        "group": "C", "episode": 0, "records": records, "prompts": prompts}) + "\n")

    def unexpected_episode(*args, **kwargs):
        raise AssertionError("complete episode must not rerun")

    monkeypatch.setattr(runner, "run_episode", unexpected_episode)
    runner.run(**options, resume=True)


def test_resume_reruns_final_artifacts_missing_prompts(tmp_path):
    options = {"policy": "nosave", "groups": ("C",), "episodes": 1,
               "run_id": "missing_final_prompt", "out": tmp_path}
    destination = runner.run(**options)
    prompt_file = destination / "prompts.jsonl"
    prompts = prompt_file.read_text().splitlines(keepends=True)
    prompt_file.write_text("".join(prompts[:-1]))
    runner.run(**options, resume=True)
    assert prompt_file.read_text().splitlines(keepends=True) == prompts


def test_resume_reruns_when_final_prompt_file_is_absent(tmp_path):
    options = {"policy": "nosave", "groups": ("C",), "episodes": 1,
               "run_id": "missing_final_file", "out": tmp_path}
    destination = runner.run(**options)
    prompt_file = destination / "prompts.jsonl"
    original_prompts = prompt_file.read_bytes()
    prompt_file.unlink()
    runner.run(**options, resume=True)
    assert prompt_file.read_bytes() == original_prompts
