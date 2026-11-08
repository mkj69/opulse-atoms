"""Kernel parity, unfolding, and promotion for computer@1."""

import json
import os
import random

import pytest

from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.kernel import evaluate, inline
from opulse.atoms.nodes import Block, Blocks, Call, CondJump, Halt, Lit, Test, Var
from opulse.atoms.spec import Definition
from opulse.atoms.verify import unfold_equivalent
from opulse.worlds_v2.computer.kernel_scope import run_kernel, scope
from opulse.worlds_v2.computer.machine import REGISTERS, State
from opulse.worlds_v2.computer.runner import run
from opulse.worlds_v2.computer.verify import (
    ARTIFACT,
    DOT_ARTIFACT,
    copy_program,
    core_definition,
    derived_computer,
    dot2_program,
    mul_program,
    verify_dot2,
)


def _same(program, state, *, fuel=None, defs=None, trace=False):
    local = run(program, {"s": state}, fuel=fuel, defs=defs, record_trace=False)
    kernel = run_kernel(program, state, fuel=fuel, defs=defs, trace=trace)
    assert (local.outcome, local.final_state, local.steps, local.jumps) == (
        kernel.outcome, kernel.final_state, kernel.steps, kernel.jumps)
    return kernel


def test_kernel_parity_mul_and_copy():
    randomizer = random.Random(37)
    pairs = {(a, b) for a in range(256) for b in (*range(4), 255)}
    pairs.update((index // 8, 4 + index % 8)
                 for index in randomizer.sample(range(256 * 8), 1800))
    assert len(pairs) >= 3000
    environment = scope({"MUL": mul_program()})
    call = Call("MUL", (Var("s"),))
    unfolded_call = inline(call, environment)
    for a, b in sorted(pairs):
        state = State((0, a, b, 0))
        kernel = _same(mul_program(), state)
        assert kernel.outcome.value.regs[0] == a * b % 256
        called_result = evaluate(call, {"s": state}, scope=environment)
        unfolded_result = evaluate(unfolded_call, {"s": state}, scope=environment)
        assert (called_result.outcome, called_result.steps) == (unfolded_result.outcome,
                                                               unfolded_result.steps)
        if (a, b) in {(0, 0), (17, 1), (255, 255)}:
            called = _same(Blocks((), "call", (("call", Block((
                ("s", Call("MUL", (Var("s"),))),), Halt(Var("s")))),)),
                           state, defs={"MUL": mul_program()}, trace=True)
            assert len(called.trace.children) == 1
            assert called.trace.children[0].name == "MUL"
            assert called.trace.children[0].steps == kernel.steps
    for byte in range(256):
        _same(copy_program(), State((0, byte, 0, 0)))


def test_seeded_straight_and_looping_programs():
    randomizer = random.Random(118)
    for index in range(200):
        state = State(tuple(randomizer.randrange(256) for _ in range(4)))
        register = Lit(REGISTERS[randomizer.randrange(4)])
        if index % 2:
            program = Blocks((), "start", (("start", Block((
                ("s", Call("dec", (Var("s"), register))),),
                CondJump(Test(Call("is_zero", (Var("s"), register))), "done", "start"))),
                ("done", Block((), Halt(Var("s"))))))
            fuel = randomizer.choice((0, 4, 18, 40))
        else:
            program = Blocks((), "start", (("start", Block((
                ("s", Call("write", (Var("s"), register, Lit(index % 256)))),
                ("s", Call("add", (Var("s"), register, Lit(REGISTERS[0]))))),
                Halt(Var("s")))),))
            fuel = randomizer.choice((0, 1, 5))
        _same(program, state, fuel=fuel)


def test_failed_test_becomes_nan_condition():
    program = Blocks((), "start", (("start", Block((),
        CondJump(Test(Call("is_zero", (Var("s"), Lit("invalid")))), "done", "done"))),
        ("done", Block((), Halt(Var("s"))))))
    result = _same(program, State())
    assert result.outcome.reason == "nan_condition"


def test_inline_and_boundaries():
    definitions = {"MUL": mul_program(), "DOT2": dot2_program()}
    environment = scope(definitions)
    boundaries = [Boundary(), Boundary(depth=0), Boundary(open_names=frozenset({"MUL"})),
                  Boundary(open_names=frozenset({"DOT2"})),
                  Boundary(open_names=frozenset({"DOT2", "MUL"}))]
    for a, b in ((0, 0), (17, 1), (255, 255), (12, 21)):
        state = State((0, a, b, 0))
        expression = Call("MUL", (Lit(state),))
        direct = evaluate(expression, scope=environment, trace=True)
        unfolded = evaluate(inline(expression, environment), scope=environment)
        assert (direct.outcome, direct.steps) == (unfolded.outcome, unfolded.steps)
        assert unfold_equivalent(direct.trace, boundaries).ok
    state = State(mem=bytes((2, 3, 4, 5)) + bytes(252))
    root = evaluate(Call("DOT2", (Lit(state),)), scope=environment, trace=True).trace
    assert unfold_equivalent(root, boundaries).ok
    assert [item.name for item in flatten_calls(root, Boundary())] == ["DOT2"]
    assert [item.name for item in flatten_calls(root, Boundary(open_names=frozenset({"DOT2"})))].count("MUL") == 2
    assert all(item.given for item in flatten_calls(root, Boundary(depth=0)))


def test_promoted_record_and_bounded_dot2():
    record = json.loads(ARTIFACT.read_text())
    assert isinstance(core_definition(record), Definition)
    derived = derived_computer(record)
    assert derived.extends == "computer@1"
    assert derived.scopes()["MUL"]["size"] == 65536
    assert core_definition(record).evidence.checked_recorded()
    for evidence in ({**record["evidence"], "method": "sampled", "seed": 7},
                     {**record["evidence"], "world_hash": "stale"},
                     {**record["evidence"], "deps_hash": "stale"},
                     {**record["evidence"], "scope": {**record["evidence"]["scope"],
                                                     "checked": {**record["evidence"]["scope"]["checked"],
                                                                 "sha256": "0" * 64}}}):
        with pytest.raises(ValueError):
            derived_computer({**record, "evidence": evidence})
    dot = json.loads(DOT_ARTIFACT.read_text())
    assert dot["layer"] == 2 and "MUL" in dot["depends_on"]
    assert dot["evidence"]["method"] == "bounded" and dot["evidence"]["scope"]["size"] == 4096
    if os.environ.get("OPULSE_SLOW") == "1":
        assert dot == verify_dot2(bound=8)
