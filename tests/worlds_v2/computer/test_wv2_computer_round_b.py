"""Round-b multiplication evidence, restricted views, and task hooks."""

import json
import os
import sys

import pytest

from opulse.atoms.kernel import FnRef
from opulse.atoms.library import PipelineError, atoms_digest
from opulse.atoms.values import Ok
from opulse.tasks_v2.generic import generate_world, grade
from opulse.worlds_v2.computer2 import hosts
from opulse.worlds_v2.computer2.export import OUTPUT
from opulse.worlds_v2.computer2.story import build_library, vector
from opulse.worlds_v2.computer2.tasks import task_world
from opulse.worlds_v2.computer2.verify_mul import (
    ARTIFACT,
    WHILE_ARTIFACT,
    apply_while_artifact,
    check_all,
    check_subset,
    validate_artifact,
)


def test_exhaustive_evidence_and_seeded_subset():
    """Check signed full-run metadata and a subset; OPULSE_SLOW=1 reruns all pairs."""
    library = build_library()
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_artifact(library, artifact)
    assert artifact["full_run"]["pairs_checked"] == 65536
    assert artifact["full_run"]["process_count"] == 32
    from opulse.worlds_v2.computer2.verify_mul import inputs_sha256

    assert artifact["full_run"]["inputs_sha256"] == inputs_sha256()
    assert artifact["full_run"]["date_utc"].endswith("+00:00")
    with pytest.raises(PipelineError, match="stale"):
        validate_artifact(library, {**artifact, "full_run": {**artifact["full_run"], "pairs_checked": 2000}})
    with pytest.raises(PipelineError, match="stale"):
        validate_artifact(library, {**artifact, "definition_body_hash": "stale"})
    for key in ("content_hash", "atoms_hash"):
        with pytest.raises(PipelineError, match="stale"):
            validate_artifact(library, {**artifact, key: "stale"})
    definition = library.get("mul_into")
    assert definition.evidence.content_hash == library.content_hash("mul_into")
    assert definition.evidence.atoms_hash == atoms_digest(library.atoms)
    assert definition.evidence.method == "exhaustive"
    assert definition.evidence.scope["size"] == 65536
    assert definition.evidence.checked_recorded()
    assert definition.cost.steps["min"] == 6
    assert definition.cost.steps["max"] == 2046
    assert definition.cost.steps["mean"] == 1026
    check_subset(library, 2000, seed=0)


def test_exhaustive_evidence_rejects_changed_checked_domain():
    library = build_library()
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    artifact["scope"]["checked"]["sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="stale"):
        validate_artifact(library, artifact)


def test_while_b_covers_all_counters_and_exact_steps():
    library = build_library()
    artifact = json.loads(WHILE_ARTIFACT.read_text(encoding="utf-8"))
    assert artifact["content_hash"] == library.content_hash("@while_b")
    assert artifact["atoms_hash"] == atoms_digest(library.atoms)
    assert library.get("@while_b").evidence.content_hash == artifact["content_hash"]
    scope = library.get("@while_b").evidence.scope
    assert scope["size"] == 512
    assert scope["op_family"] == ["mul_tick", "carry_tick"]
    state = hosts.state((0, 255, 255, 17), pc=29)
    result = library.run("@while_b", (FnRef("mul_tick"), state))
    assert isinstance(result.outcome, Ok) and result.steps == 2046
    assert hosts.fields(result.outcome.value)[0] == (1, 0, 255, 17)


@pytest.mark.parametrize("hash_name", ["content_hash", "atoms_hash"])
def test_stale_loop_hash_is_rejected(monkeypatch, tmp_path, hash_name):
    import opulse.worlds_v2.computer2.verify_mul as verifier

    artifact = json.loads(WHILE_ARTIFACT.read_text(encoding="utf-8"))
    artifact[hash_name] = "stale"
    stale = tmp_path / "while_b.evidence.json"
    stale.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr(verifier, "WHILE_ARTIFACT", stale)
    with pytest.raises(PipelineError, match="stale"):
        apply_while_artifact(build_library())


def test_stale_loop_checked_scope_is_rejected(monkeypatch, tmp_path):
    import opulse.worlds_v2.computer2.verify_mul as verifier

    artifact = json.loads(WHILE_ARTIFACT.read_text(encoding="utf-8"))
    artifact["evidence"]["scope"]["checked"]["sha256"] = "0" * 64
    stale = tmp_path / "while_b.evidence.json"
    stale.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr(verifier, "WHILE_ARTIFACT", stale)
    with pytest.raises(PipelineError, match="stale"):
        apply_while_artifact(build_library())


def test_write_rebuilds_both_artifacts_without_reading_stale_ones(monkeypatch, tmp_path):
    import opulse.worlds_v2.computer2.verify_mul as verifier
    from opulse.worlds_v2.computer2 import story

    events = []
    library = object()
    output = tmp_path / "mul_into.evidence.json"
    output.write_text("stale", encoding="utf-8")

    def fresh_library(**kwargs):
        assert kwargs == {"use_mul_artifact": False, "use_while_artifact": False}
        events.append("build")
        return library

    monkeypatch.setattr(story, "build_library", fresh_library)
    monkeypatch.setattr(verifier, "save_while_artifact", lambda built: events.append(("while", built)))
    def full_check(processes, built):
        events.append(("mul", processes, built))
        return 65536

    monkeypatch.setattr(verifier, "check_all", full_check)
    monkeypatch.setattr(verifier, "hashes", lambda built: {"content_hash": "fresh"})
    monkeypatch.setattr(verifier, "ARTIFACT", output)
    monkeypatch.setattr(sys, "argv", ["verify_mul", "--write", "--processes", "2"])

    verifier.main()

    assert events == ["build", ("while", library), ("mul", 2, library)]
    assert json.loads(output.read_text(encoding="utf-8"))["content_hash"] == "fresh"


def test_worst_case_vector_steps():
    library = build_library()
    state = hosts.state(changes={**{index: 255 for index in range(16, 48)},
                                 **{index: 255 for index in range(64, 96)}})
    args = (state, vector(16, 32), vector(64, 32))
    # Core 0.5 charges unfolded argument work at the call site.
    for name, steps in (("dot", 70681), ("wide_dot", 119255)):
        result = library.run(name, args)
        assert isinstance(result.outcome, Ok) and result.steps == steps


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OPULSE_SLOW") != "1", reason="65536-pair rerun is opt-in")
def test_exhaustive_evidence_rerun():
    check_all()


def test_restricted_showcase_and_fuel_note():
    exported = json.loads(OUTPUT.read_text(encoding="utf-8"))
    case = exported["showcase"][2]
    assert case["grants"]["probes"] == ["?d", "?out"]
    assert "initially zero" not in case["prompt"]
    allowed = set(range(80, 92)) | set(range(120, 132))
    for machine in case["learner_view"]["machines"]:
        assert set(machine) == {"label", "cells", "?d", "?out"}
        assert {int(index) for index in machine["cells"]} == allowed
        assert machine["?d"] == 0
    assert "judge_view" not in case  # answers are public since the 11-06 04:40 decision (B5); judge state is not
    assert exported["fuel_note"]["worst_case_steps"] == {
        "@while_b": 2046, "mul_into": 2046, "dot_32": 70681, "wide_dot_32": 119255}
    assert exported["fuel_note"]["cap"] is None


def test_task_world_all_kinds_ascii_and_reference_grading():
    world = task_world()
    tasks = generate_world(world, 1, seed=0)
    assert {task.kind for task in tasks} == {"object", "operation", "combinator", "observation"}
    for task in tasks:
        assert task.prompt["en"].isascii()
        if task.angle == "compute":
            answer = task.reference["outcome"]
        elif task.angle == "invert":
            answer = task.reference["witness"]
        elif task.angle == "decide":
            answer = dict(task.reference)
        elif task.angle == "describe":
            answer = task.reference["choice"]
        else:
            answer = {"body": task.reference["definition"]}
        assert grade(world, task, answer).correct, (task.kind, task.angle, task.question["definition"])
