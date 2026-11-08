"""Bytecode and static checks for the tiny/1 compiler (atoms-meta, section 5)."""

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.values import Card
from opulse.meta.compiler.compile import CompileError, compile_tiny
from opulse.meta.compiler.tiny import check_tiny
from opulse.meta.vn import reference


def call(name, *args):
    return n.Call(name, args)


def zero(expr):
    return n.Test(call("is_zero", expr))


def multiply():
    return n.Rec("loop", ("counter", "acc"),
                 n.Case(((zero(n.Var("counter")), n.Var("acc")),),
                        call("loop", call("sub", n.Var("counter"), n.Lit(1)),
                             call("add", n.Var("acc"), n.Var("x0")))),
                 (n.Var("x1"), n.Lit(0)), "fuel")


def test_add3_code_card_and_exact_machine_steps():
    body = call("add", n.Var("x0"), n.Lit(3))
    prog = compile_tiny(body, ("x0",))
    assert prog.code == (2, 6, 8, 3, 0, 0)
    assert prog.args == (6,)
    assert prog.card == Card("prog", "prog", (64, Card("list", "items", prog.code),
                                               Card("list", "items", prog.args), "a"))
    assert prog.run((5,))[0::2] == ("ok", 3)
    assert prog.run((5,))[1].a == 8
    assert prog.run((5,))[1] == reference.State(4, 8, (2, 6, 8, 3, 0, 0, 5) + (0,) * 57, True)
    assert reference.run(reference.load(prog.code, 64, {6: 5}), 10)[2] == 3


def test_rec_multiply_simultaneous_parameters_and_machine_steps():
    prog = compile_tiny(multiply(), ("x0", "x1"))
    assert prog.run((0, 0))[1].a == 0
    assert prog.run((0, 0))[2] == 9
    assert prog.run((3, 4))[1].a == 12
    assert prog.run((3, 4))[2] == 73
    assert prog.run((15, 15))[1].a == 225
    assert prog.run((15, 15))[2] == 249
    assert reference.run(reference.load(prog.code, 64, dict(zip(prog.args, (3, 4)))), 1000)[2] == 73


def test_case_lets_short_circuit_conditions_and_inlined_definitions():
    maximum = n.Case(((zero(call("sub", n.Var("x0"), n.Var("x1"))), n.Var("x1")),),
                     n.Var("x0"))
    prog = compile_tiny(maximum, ("x0", "x1"))
    assert (prog.run((5, 5))[1].a, prog.run((5, 5))[2]) == (5, 10)
    assert (prog.run((3, 5))[1].a, prog.run((3, 5))[2]) == (3, 10)

    heavy = n.Let("a", call("add", n.Var("x0"), n.Lit(2)),
                  n.Let("b", call("sub", n.Var("x1"), n.Lit(1)),
                        call("add", n.Var("a"), n.Var("b"))))
    prog = compile_tiny(heavy, ("x0", "x1"))
    assert (prog.run((4, 5))[1].a, prog.run((4, 5))[2]) == (10, 11)

    condition = n.And(n.Not(zero(n.Var("x0"))),
                      n.Or(zero(n.Var("x1")), zero(call("sub", n.Var("x0"), n.Var("x1")))))
    nested = n.Case(((condition, n.Case(((zero(n.Var("x1")), n.Lit(7)),), n.Lit(9))),), n.Lit(3))
    prog = compile_tiny(nested, ("x0", "x1"))
    assert [(prog.run(row)[1].a, prog.run(row)[2]) for row in ((0, 0), (2, 0), (2, 2), (2, 3))] == [
        (3, 4), (7, 11), (9, 19), (3, 16)]

    inc = (call("add", n.Var("y"), n.Lit(1)), ("y",))
    inlined = compile_tiny(call("add", call("inc", n.Var("x0")), n.Lit(2)),
                           ("x0",), {"inc": inc})
    assert (inlined.run((3,))[1].a, inlined.run((3,))[2]) == (6, 6)


def test_checker_rejects_illegal_nodes_boolean_values_and_non_tail_recursion():
    assert "only inside a Test" in check_tiny(call("is_zero", n.Var("x0")), ("x0",))[0]
    assert "only inside a Test" in check_tiny(call("add", call("is_zero", n.Lit(0)), n.Lit(1)), ())[0]
    assert "literals" in check_tiny(n.Lit(256), ())[0]
    assert "literals" in check_tiny(n.Lit(True), ())[0]
    assert "measure fuel" in check_tiny(n.Rec("r", ("x",), n.Var("x"), (n.Lit(1),), "legacy"), ())[0]
    recursive = n.Rec("r", ("x",), call("add", call("r", n.Var("x")), n.Lit(1)),
                      (n.Var("x0"),), "fuel")
    assert any("non-tail recursion" in error and "no stack" in error
               for error in check_tiny(recursive, ("x0",)))
    with pytest.raises(CompileError, match="non-tail recursion"):
        compile_tiny(recursive, ("x0",))


def test_oversized_program_and_data_are_rejected():
    with pytest.raises(CompileError, match="n=16"):
        compile_tiny(multiply(), ("x0", "x1"), n=16)
