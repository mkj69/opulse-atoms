"""Blocks/Jump, strict calls, fuel and definition boundaries (spec section 6)."""

from opulse.atoms.nodes import Block, Blocks, Call, CondJump, Halt, Jump, Let, Lit, Var
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.worlds_v2.computer.machine import REGISTERS, State
from opulse.worlds_v2.computer.runner import run
from opulse.worlds_v2.computer.verify import mul_program


def test_jumps_fuel_and_halt():
    infinite = Blocks((), "again", (("again", Block((), Jump("again"))),))
    assert run(infinite, {}, fuel=3).outcome == Unknown("fuel")
    assert run(infinite, {}, fuel=3).steps == 3
    branch = Blocks((), "head", (("head", Block((), CondJump(Lit(True), "done", "bad"))),
                                  ("done", Block((), Halt(Lit(42)))),
                                  ("bad", Block((), Halt(Lit(0))))))
    assert run(branch, {}, fuel=1).outcome == Ok(42)
    assert run(branch, {}, fuel=0).outcome == Unknown("fuel")
    assert run(branch, {}).jumps == 1


def test_assignment_order_strict_failure_and_determinism():
    state = State()
    program = Blocks((), "start", (("start", Block((
        ("s", Call("write", (Var("s"), Lit(REGISTERS[0]), Lit(8)))),
        ("s", Call("write", (Var("s"), Lit(REGISTERS[1]),
                             Let("value", Call("read", (Var("s"), Lit(REGISTERS[0]))), Var("value"))))),
    ), Halt(Var("s")))),))
    outcome = run(program, {"s": state})
    assert outcome.outcome.value.regs[:2] == (8, 8)
    assert outcome.steps == 3 and run(program, {"s": state}) == outcome
    invalid = Blocks((), "bad", (("bad", Block((
        ("s", Call("write", (Var("s"), Lit(REGISTERS[0]), Lit(256)))),),
        Halt(Var("s")))),))
    assert run(invalid, {"s": state}).outcome == Bottom("invalid")
    assert run(invalid, {"s": state}).steps == 1
    literal_failure = Blocks((), "bad", (("bad", Block((), Halt(Lit(Bottom("invalid"))))),))
    assert run(literal_failure, {}).outcome == Bottom("invalid")


def test_definition_call_boundary_and_trace():
    state = State((31, 7, 9, 55))
    inline = run(mul_program(), {"s": state})
    call = Blocks((), "call", (("call", Block((), Halt(Call("MUL", (Var("s"),))))),))
    wrapped = run(call, {"s": state}, defs={"MUL": mul_program()})
    assert (inline.outcome, inline.final_state, inline.steps, inline.jumps) == (
        wrapped.outcome, wrapped.final_state, wrapped.steps, wrapped.jumps)
    assert len(wrapped.trace) == 1 and wrapped.trace[0].name == "MUL"
    assert wrapped.trace[0].children == inline.trace


def test_jump_conditions_and_or_not_always_short_circuit():
    from opulse.atoms.nodes import (
        Always,
        And,
        Block,
        Blocks,
        Call,
        CondJump,
        Halt,
        Lit,
        Not,
        Or,
        Test,
        Var,
    )
    from opulse.atoms.values import Bottom
    from opulse.worlds_v2.computer.machine import REGISTERS, State
    from opulse.worlds_v2.computer.runner import run

    state = Var("s")
    zero = Test(Call("is_zero", (state, Lit(REGISTERS[0]))))
    bad = Test(Call("is_zero", (state, Lit(7))))  # not a register: Bottom(invalid)

    def branch(cond):
        return Blocks((), "a", (("a", Block((), CondJump(cond, "yes", "no"))),
                                ("yes", Block((("s", Call("write", (state, Lit(REGISTERS[1]), Lit(1)))),), Halt(state))),
                                ("no", Block((), Halt(state)))))

    start = State((0, 0, 0, 0))
    assert run(branch(Always()), {"s": start}).final_state.regs[1] == 1
    assert run(branch(Not(zero)), {"s": start}).final_state.regs[1] == 0
    assert run(branch(Or(zero, bad)), {"s": start}).final_state.regs[1] == 1  # short-circuit: bad not evaluated
    assert run(branch(And(Not(zero), bad)), {"s": start}).final_state.regs[1] == 0
    assert run(branch(And(zero, bad)), {"s": start}).outcome == Bottom("nan_condition")
