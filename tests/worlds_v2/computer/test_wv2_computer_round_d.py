"""Round-d observation grants, private grading, and proof provenance."""

import hashlib
import json
from copy import copy
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.observations import check_observation
from opulse.atoms.values import Bottom, Ok
from opulse.worlds_v2.computer2 import hosts
from opulse.worlds_v2.computer2.export import GRADING, META, OUTPUT
from opulse.worlds_v2.computer2.story import build_library
from opulse.worlds_v2.computer2.verify_mul import ARTIFACT, validate_artifact


@pytest.fixture(scope="module")
def library():
    return build_library()


@settings(deadline=None, max_examples=30)
@given(first=st.integers(min_value=0, max_value=255),
       second=st.integers(min_value=0, max_value=255))
def test_probe_equivalence_outside_grants(library, first, second):
    left = hosts.state(changes={15: first, 80: 13})
    right = hosts.state(changes={15: second, 80: 13})
    assert library.run("?at", (left, 15)).outcome == Bottom("permission")
    assert library.run("?at", (right, 15)).outcome == Bottom("permission")
    assert library.run("?at", (left, 80)).outcome == Ok(13)
    assert library.run("?at", (right, 80)).outcome == Ok(13)


def test_memory_observation_checker_and_verified_grants(library):
    definition = library.get("?at")
    assert definition.spec.reads == ("?mem",)
    assert set(check_observation(definition, library)) == {
        "the subject s may only be passed to probes and observations",
        "probe ?mem receives only the subject s",
        "observation reads undeclared value addr",
    }
    assert definition.status == "callable" and definition.evidence is None
    assert set(range(80, 92)) | set(range(120, 132)) <= hosts.MEMORY_GRANTS
    assert hosts.MEMORY_GRANTS == {
        addr for start, end in library.world.observation["capabilities"]["learner"]["memory_ranges"]
        for addr in range(start, end + 1)
    }
    assert library.run("?at", (hosts.state(), 256)).outcome == Bottom("permission")
    assert library.run("?mem", (hosts.state(), 0)).outcome == Bottom("permission")
    play = copy(library)
    play.agent = "play"
    assert play.run("?at", (hosts.state(changes={16: 7}), 16)).outcome == Bottom("permission")
    assert play.run("?mem", (hosts.state(changes={16: 7}), 16)).outcome == Bottom("permission")
    assert play.run("?at", (hosts.state(changes={80: 7}), 80)).outcome == Ok(7)
    assert play.run("?b", (hosts.state(),)).outcome == Bottom("permission")
    assert kernel.call("?at", (hosts.state(changes={16: 7}), 16), play.scope()).outcome == Bottom("permission")
    assert set(range(80, 92)) | set(range(120, 132)) == {
        addr for start, end in library.world.observation["capabilities"]["play"]["memory_ranges"]
        for addr in range(start, end + 1)
    }


def test_acting_operation_cannot_hide_in_memory_observation(library):
    definition = library.get("?at")
    body = nodes.Call("?c", (nodes.Call("load", (nodes.Var("s"), nodes.Lit("C"),
                                               nodes.Var("addr"))),))
    invalid = replace(definition, body=body, spec=replace(definition.spec, body=body))
    assert any("operation load may read or change truth" in problem
               for problem in check_observation(invalid, library))
    assert library.get("?at").evidence is None


def test_public_showcase_stores_kernel_answers_without_judge_state():
    # Supervisor decision 11-06 04:40 (B5): each checked showcase stores its kernel-computed answer;
    # the judge-only machines stay in the separate grading artifact.
    public = json.loads(OUTPUT.read_text(encoding="utf-8"))
    grading = json.loads(GRADING.read_text(encoding="utf-8"))
    metadata = json.loads(META.read_text(encoding="utf-8"))
    assert all("answer" not in case for case in metadata["showcase"])  # never hand-written
    assert public["grading_sha256"] == hashlib.sha256(GRADING.read_bytes()).hexdigest()
    for case, graded in zip(public["showcase"], grading["showcase"], strict=True):
        assert case["answer_checked"] and case["answer"] == graded["answer"]
        assert "judge_view" not in case and "machines" not in case
    assert "32" not in public["showcase"][0]["why_hard_zh"]
    assert "不相同" not in public["showcase"][2]["check_zh"]
    assert grading["showcase"][2]["answer"]["modular"] == [40, 40]
    assert len(grading["showcase"][2]["machines"]) == 2
    assert all(machine["?d"] == 0 for machine in public["showcase"][2]["learner_view"]["machines"])
    assert all("judge_view" not in example for card in public["story"] for example in card["examples"])


def test_full_run_provenance_not_just_hashes(library):
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    validate_artifact(library, artifact)
    assert artifact["full_run"]["pairs_checked"] == 65536
    assert artifact["full_run"]["process_count"] == 32
    for field in ("date_utc", "inputs_sha256", "process_count", "pairs_checked"):
        invalid = {**artifact, "full_run": {key: value for key, value in artifact["full_run"].items()
                                               if key != field}}
        with pytest.raises(PipelineError, match="missing, stale or malformed"):
            validate_artifact(library, invalid)
