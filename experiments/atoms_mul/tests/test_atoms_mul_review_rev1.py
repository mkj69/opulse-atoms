"""Independent review reproductions for the multiplication experiment."""

import json
from pathlib import Path

import pytest
from atoms_mul.analysis.analyze import analyze
from atoms_mul.harness.run import run
from atoms_mul.machine.core_library import CoreMirror
from atoms_mul.machine.evaluate import run_sub
from atoms_mul.machine.lang import parse_program

from opulse.atoms import nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Definition, ObjectSpec
from opulse.atoms.values import Unknown
from opulse.worlds_v2.computer.machine import State


def test_review_rev1_machine_zero_fuel_has_no_visible_atom_step():
    program = parse_program("sub main:\n  set r0, 7\n  halt\nend")
    result = run_sub("main", State(), group="A", program=program, fuel=0)
    assert isinstance(result.outcome, Unknown)
    assert result.steps == result.boundary_steps == 0


def test_review_rev1_incomplete_episodes_cannot_trigger_primary_decision():
    records = [
        {"track": "aml", "group": group, "episode": episode, "stage": 2,
         "task_id": "s2_t01", "correct": group == "B", "length": 1,
         "steps": 1, "boundary_steps": 1}
        for group in ("B", "C") for episode in range(40)
    ]
    result = analyze(records, resamples=100)
    assert result["decision"] == "diagnostic"


def test_review_rev1_two_episode_dry_run_cannot_trigger_primary_decision():
    task_root = Path(__file__).resolve().parents[1] / "tasks"
    ids = {stage: [task["id"] for task in json.loads(
        (task_root / f"stage{stage}.json").read_text())["tasks"]] for stage in (1, 2)}
    records = [
        {"track": "aml", "group": group, "episode": episode, "stage": stage,
         "task_id": task_id, "correct": group == "B", "length": 1,
         "steps": 1, "boundary_steps": 1}
        for group in ("B", "C") for episode in range(2)
        for stage, task_ids in ids.items() for task_id in task_ids
    ]
    result = analyze(records, resamples=100)
    assert result["decision"] == "diagnostic"
    assert result["reason"] == "n=2 eligible episodes per group < 40 pre-registered"


def test_review_rev1_existing_run_id_must_fail_before_replacing_artifacts(monkeypatch, tmp_path):
    from atoms_mul.analysis import llm_policy
    from atoms_mul.harness import run as runner

    class OfflineActor:
        model = "fake"

    monkeypatch.setattr(llm_policy, "LLMPolicy", lambda **kwargs: OfflineActor())
    monkeypatch.setattr(runner, "run_episode", lambda *args, **kwargs: [])
    options = {"policy": "llm", "groups": ["B"], "episodes": 1,
               "run_id": "real", "out": tmp_path, "model": "fake", "allow_api": True}
    run(**options)
    with pytest.raises(ValueError, match="existing|resume"):
        run(**options)


def test_review_rev1_machine_mirror_refuses_closed_object_kind():
    mirror = CoreMirror("B")
    spec = ObjectSpec("ReviewObject", "constant", body=nodes.Lit(1))
    definition = Definition(spec.name, "object", "invented", 1, (), spec, spec.body)
    with pytest.raises(PipelineError, match="kind object is closed"):
        mirror.library.write(definition)


def test_review_rev1_prereg_notation_is_ascii_only():
    prereg = Path(__file__).resolve().parents[1] / "PREREG.md"
    text = prereg.read_text(encoding="utf-8")
    assert not any(chr(codepoint) in text for codepoint in (0xD7, 0x2248, 0x2212, 0x2013))


def test_review_rev1_experiment_source_and_docs_are_ascii_only():
    experiments = Path(__file__).resolve().parents[2]
    for suffix in ("*.md", "*.py"):
        for path in experiments.rglob(suffix):
            assert path.read_bytes().isascii(), str(path)


def test_review_rev1_existing_checkpoint_rejected_before_policy_initialization(monkeypatch, tmp_path):
    from atoms_mul.harness import run as runner

    destination = tmp_path / "paid"
    destination.mkdir()
    (destination / "episodes.jsonl").write_text("checkpoint")

    def forbidden(*args, **kwargs):
        raise AssertionError("policy must not be constructed")

    monkeypatch.setitem(runner.POLICIES, "inventor", forbidden)
    with pytest.raises(ValueError, match="run paid exists; use --resume or a new --run-id"):
        run(policy="inventor", groups=["B"], episodes=1, run_id="paid", out=tmp_path)
