"""MUL/COPY evidence and world locks (spec sections 8, 9 and 15)."""

import hashlib
import inspect
import json
import os
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms.nodes import Block, Blocks, Call, Halt, Lit, Var, to_json
from opulse.atoms.values import Ok
from opulse.tasks_v2.decl import compute_lock, load, validate
from opulse.worlds_v2.computer import machine
from opulse.worlds_v2.computer.reference import COMPUTER_A
from opulse.worlds_v2.computer.reference import atoms as reference_atoms
from opulse.worlds_v2.computer.runner import atoms, run
from opulse.worlds_v2.computer.verify import (
    ARTIFACT,
    DECLARATION,
    body_hash,
    copy_program,
    fast_mul,
    mul_program,
    promote,
    step_formula,
    verify_copy,
    verify_dot2,
    verify_mul,
)


def test_subset_all_checks():
    randomizer = random.Random(47)
    pairs = {(a, b) for a in range(256) for b in range(4)}
    pairs.update((a, b) for a in (0, 1, 255) for b in range(256))
    pairs.update((randomizer.randrange(256), randomizer.randrange(256)) for _ in range(2000))
    for a, b in pairs:
        state = machine.State((0, a, b, 0))
        unfolded = run(mul_program(), {"s": state}, record_trace=False)
        fast, steps = fast_mul(state)
        assert isinstance(unfolded.outcome, Ok)
        assert unfolded.outcome.value == unfolded.final_state == fast
        assert unfolded.steps == steps == step_formula(a, b)
        assert fast.regs[0] == machine.given_mul(state).regs[0] == a * b % 256
        assert fast.regs[1] == a and fast.regs[3] == 0 and fast.mem == state.mem
    untouched_flags = machine.State((91, 2, 0, 3), bytes(range(256)), True, True)
    assert run(mul_program(), {"s": untouched_flags}).outcome.value == fast_mul(untouched_flags)[0]


def test_evidence_promotion_and_copy():
    record = verify_mul(exhaustive=False, samples=4)
    with pytest.raises(ValueError):
        promote(record)
    with pytest.raises(ValueError):
        promote({**record, "evidence": None, "status": "verified"})
    with pytest.raises(ValueError):
        promote({**record, "evidence": {**record["evidence"], "method": "exhaustive", "world_hash": "stale"}, "status": "verified"})
    with pytest.raises(ValueError):
        promote({**record, "evidence": {**record["evidence"], "method": "exhaustive", "deps_hash": "stale"}, "status": "verified"})
    with pytest.raises(ValueError):
        promote({**record, "evidence": {**record["evidence"], "method": "exhaustive", "checks": []}, "status": "verified"})
    with pytest.raises(ValueError):
        promote({**record, "evidence": {**record["evidence"], "method": "exhaustive", "failed_checks": ["reference"]}, "status": "verified"})
    copy = verify_copy()
    assert promote(copy)["status"] == "promoted"


def test_promotion_rejects_substituted_body_and_replays_checks():
    record = json.loads(ARTIFACT.read_text())
    with pytest.raises(ValueError):
        promote({**record, "body": to_json(copy_program()), "status": "verified"})

    original = verify_copy()
    program = copy_program()
    label, block = program.blocks[0]
    altered = Blocks(program.vars, program.entry, ((label, Block(
        block.assigns + (("scratch", Call("read", (Var("s"), Lit(machine.REGISTERS[0])))),),
        block.end)),))
    body = to_json(altered)
    evidence = {**original["evidence"], "content_hash": body_hash(body, original["depends_on"])}
    with pytest.raises(ValueError, match="verification check failed"):
        promote({**original, "body": body, "evidence": evidence})


@given(st.integers(min_value=0, max_value=255))
def test_body_identity_rejects_any_substituted_write(byte):
    original = verify_copy()
    changed = Blocks((), "copy", (("copy", Block((("s", Call("write", (
        Var("s"), Lit(machine.REGISTERS[0]), Lit(byte)))),), Halt(Var("s")))),))
    with pytest.raises(ValueError, match="insufficient evidence"):
        promote({**original, "body": to_json(changed)})


def test_bounded_dot2_promotion_replays_recorded_scope():
    record = verify_dot2(bound=2)
    assert promote(record)["status"] == "promoted"
    with pytest.raises(ValueError, match="insufficient evidence"):
        promote({**record, "evidence": {**record["evidence"], "content_hash": "stale"}})


def test_declaration_and_committed_evidence():
    declaration = json.loads(DECLARATION.read_text())
    lock = declaration["lock"]
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    assert declaration["schema"] == "opulse.world/2"
    assert lock["constants_hash"] == hashlib.sha256(canonical(declaration["constants"])).hexdigest()
    world = load(DECLARATION)
    assert validate(world) == []
    assert lock == compute_lock(world)
    assert lock["host_digests"]["byte.valid"] == hashlib.sha256(inspect.getsource(machine.byte_ok).encode()).hexdigest()
    assert {operation["name"] for operation in declaration["operations"]} == set(atoms())
    assert COMPUTER_A["extends"] == "computer@1"
    assert set(reference_atoms()) == set(atoms()) | {"mul"}
    assert "program" not in json.dumps(declaration["operations"])
    assert all("Blocks" not in json.dumps(op["inputs"] + [op["output"]]) for op in declaration["operations"])
    artifact = json.loads(ARTIFACT.read_text())
    assert artifact["body"] == to_json(mul_program())
    assert artifact["evidence"]["world_hash"] == lock["world_hash"]
    assert artifact["evidence"]["scope"]["size"] == 65536
    assert artifact["contract"]["may_change"] == ["carry", "r0", "r2", "zero"]
    assert artifact["cost"]["steps"] == {"min": 4, "max": 1279, "mean": 641.5,
                                          "formula": "4 + 5 * initial_r2", "over": "verification scope"}
    if os.environ.get("OPULSE_SLOW") == "1":
        assert artifact == verify_mul()
