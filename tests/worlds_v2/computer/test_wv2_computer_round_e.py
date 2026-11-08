"""Round-e checks for honest observation evidence (spec section 7.2)."""

from copy import copy
from dataclasses import replace
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.observations import check_observation
from opulse.atoms.values import Ok
from opulse.worlds_v2.computer2 import adapter, hosts
from opulse.worlds_v2.computer2.story import build_library, definitions, vector


@pytest.fixture(scope="module")
def library():
    return build_library()


def test_unpromoted_observations_do_not_claim_dependency_evidence(library):
    for name, kind, _, _ in definitions():
        if kind != "observation":
            continue
        definition = library.get(name)
        problems = check_observation(definition, library)
        assert problems, name
        assert definition.status == "callable" and definition.contract is None
        assert definition.evidence is None
        with pytest.raises(PipelineError, match="promote requires verified status"):
            library.promote(name, library.get("mul_carry").contract)


def test_observation_evidence_tracks_the_core_dependency_checker(library):
    for name, kind, _, _ in definitions():
        if kind == "observation":
            definition = library.get(name)
            passes = not check_observation(definition, library)
            if passes:
                assert "dependency" in definition.evidence.checks
            else:
                assert definition.evidence is None
            assert passes or definition.status == "callable"


@settings(deadline=None, max_examples=12)
@given(register=st.integers(min_value=0, max_value=255))
def test_at_cannot_claim_non_interference_when_body_reads_undeclared_register(
        library, register):
    machine = hosts.state((1, 2, 3, register), {16: 37})
    original = library.get("?at")
    body = nodes.Call("?d", (nodes.Var("s"),))
    broken = replace(original, body=body, spec=replace(original.spec, body=body))
    candidate = copy(library)
    candidate._definitions = copy(library._definitions)
    candidate._definitions["?at"] = broken
    request = VerifyRequest("bounded", ((machine, 16),),
                            {"domain": "bound: one granted address", "size": 1},
                            reference=lambda state, addr: hosts.d(state))
    with pytest.raises(PipelineError):
        candidate.verify("?at", request)
    assert candidate.get("?at").status == "callable"
    assert candidate.get("?at").evidence is None

    with (patch.object(adapter, "check_observation", return_value=[]),
          pytest.raises(PipelineError, match="non-interference failed")):
        candidate.verify("?at", request)
    assert candidate.get("?at").status == "callable"
    assert candidate.get("?at").evidence is None


def test_wrap_body_never_calls_machine_operations(library):
    definition = library.get("?dot_wrap")
    assert definition.spec.reads == ("?mem",)
    pending = list(nodes.references(definition.body))
    assert {"?at", "mul_parts"} <= set(pending)
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if name == "?at":
            assert library.get(name).spec.reads == ("?mem",)
            pending.extend(nodes.references(library.get(name).body))
        elif name in library.definitions:
            dependency = library.get(name)
            if dependency.kind == "operation":
                assert all(edge.sort != "Machine" for edge in dependency.spec.inputs)
            if dependency.body is not None:
                pending.extend(nodes.references(dependency.body))
        else:
            operation = next((item for item in library.world.operations if item.name == name), None)
            if operation is not None:
                assert operation.role != "act"
                assert all(edge.sort != "Machine" for edge in operation.inputs)
            else:
                assert (name == "?mem" or name in library.scope().atoms or
                        (name.startswith(("Vec.", "Wide.")) and library.scope().resolve(name)))
    assert check_observation(definition, library)


@settings(deadline=None, max_examples=24)
@given(left=st.integers(min_value=0, max_value=255),
       right=st.integers(min_value=0, max_value=255))
def test_carry_counts_byte_wraps_without_machine(library, left, right):
    assert library.get("mul_carry").kind == "operation"
    assert library.run("mul_carry", (left, right)).outcome == Ok(left * right // 256)
    assert library.run("mul_parts", (left, right)).outcome == Ok(
        hosts.pair(left * right // 256, left * right % 256))


def test_wrap_depends_only_on_granted_vector_cells(library):
    left, right = vector(80, 2), vector(120, 2)
    one = hosts.state(changes={80: 200, 81: 50, 120: 200, 121: 10, 0: 1})
    two = hosts.state((17, 3, 2, 9), {80: 200, 81: 50, 120: 200, 121: 10, 0: 250}, pc=34, z=1)
    for machine in (one, two):
        assert library.run("?dot_wrap", (machine, left, right)).outcome == Ok(True)
    altered = hosts.state(changes={80: 1, 81: 1, 120: 1, 121: 1})
    assert library.run("?dot_wrap", (altered, left, right)).outcome == Ok(False)
