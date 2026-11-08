"""Finite-scope translation evidence for tiny/1 (atoms-meta, section 5)."""

import hashlib
from itertools import product

from test_compiler import call, multiply, zero

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.definition.interpreter import run_with_deep_stack
from opulse.meta.compiler.compile import CompileError, Prog, compile_tiny
from opulse.meta.compiler.validate import (
    _validate_compiler,
    prog_hash,
    routine_id,
    tiny_family,
    validate,
    validate_compiler,
)


def test_batched_validation_matches_individual_kernel_runs():
    family = tiny_family()[40:48]
    inputs = ((0, 0), (0, 1), (15, 15))
    expected = _validate_compiler(family, inputs)
    assert validate_compiler(family, inputs) == expected
    assert run_with_deep_stack(validate_compiler, family, inputs) == expected


def test_add3_bounded_evidence_hashes_and_overflow_rejection():
    body = call("add", n.Var("x0"), n.Lit(3))
    prog = compile_tiny(body, ("x0",))
    result = validate(body, ("x0",), prog, [(0,), (253,)], 100)
    assert not result.accepted and result.method == "bounded"
    assert result.scope["size"] == 2 and result.scope["domain"] == ((0,), (253,))
    assert len(result.source_hash) == 64
    assert result.prog_id == prog_hash(prog)
    assert result.routine_id == routine_id(prog)
    payload = "[0,[" + ",".join(map(str, prog.code)) + "]]"
    assert result.routine_id == hashlib.sha256(("opulse.vn/1\n64\n" + payload).encode()).hexdigest()
    assert result.counterexample.inputs == (253,)
    assert result.counterexample.source == Bottom("overflow")
    assert result.counterexample.compiled == Ok(0)
    assert (result.counterexample.source_steps, result.counterexample.compiled_steps) == (1, 3)
    assert result.counterexample.reason == "overflow"
    assert validate(body, ("x0",), prog, [(0,), (252,)], 100).accepted


def test_rec_multiply_full_16_by_16_scope_and_fuel_unknown():
    body = multiply()
    prog = compile_tiny(body, ("x0", "x1"))
    result = validate(body, ("x0", "x1"), prog, product(range(16), repeat=2), 10000)
    assert result.accepted and result.scope["size"] == 256
    assert result.counterexample is None
    insufficient = validate(body, ("x0", "x1"), prog, [(3, 4)], fuel=3)
    assert not insufficient.accepted
    assert insufficient.counterexample.reason == "fuel: outcome unverifiable"
    assert isinstance(insufficient.counterexample.compiled, Unknown)
    assert insufficient.unverifiable == (insufficient.counterexample,)
    state = validate(body, ("x0", "x1"), prog, [(3, 4)], 10000, full_state=True)
    assert not state.accepted and state.counterexample.reason == "no source full-state semantics"


def test_in_range_result_mismatch_from_negative_integer_intermediate():
    difference = call("sub", call("sub", n.Var("x0"), n.Var("x1")), n.Var("x1"))
    body = n.Case(((zero(difference), n.Lit(1)),), n.Lit(0))
    prog = compile_tiny(body, ("x0", "x1"))
    result = validate(body, ("x0", "x1"), prog, [(0, 128)], 100)
    assert result.counterexample.inputs == (0, 128)
    assert result.counterexample.source == Ok(0)
    assert result.counterexample.compiled == Ok(1)
    assert (result.counterexample.source_steps, result.counterexample.compiled_steps) == (3, 15)
    assert result.counterexample.reason == "is_zero on negative intermediate"
    atoms = [kernel.Atom("sub", 2, lambda left, right: left - right),
             kernel.Atom("is_zero", 1, lambda value: value == 0)]
    trace = kernel.call("source", (0, 128), kernel.DictScope(atoms, [
        kernel.Defn("source", ("x0", "x1"), body)]), trace=True).trace
    assert trace.steps == 3
    assert [(frame.name, frame.inputs) for frame in trace.children[0].children] == [
        ("sub", (0, 128)), ("sub", (-128, 128)), ("is_zero", (-256,))]
    family = validate_compiler(((body, ("x0", "x1")),), [(0, 128)])
    assert family.total == 1 and family.passed == 0
    assert family.rejected == ((0, "is_zero on negative intermediate", (0, 128)),)


def test_source_bottom_requires_machine_bottom():
    body = n.Case(((zero(n.Var("x0")), n.Lit(4)),), None)
    import pytest

    with pytest.raises(CompileError, match="Bottom\\(no_branch\\)"):
        compile_tiny(body, ("x0",))
    result = validate(body, ("x0",), Prog(64, (9, 0), (60,)), [(1,)], 100)
    assert result.counterexample.source == Bottom("no_branch")
    assert result.counterexample.compiled == Bottom("illegal")
    assert result.counterexample.reason == "Bottom reason mismatch"
    assert not result.accepted


def test_case_let_nested_conditions_and_dependency_validation():
    same = n.Case(((zero(call("sub", n.Var("x0"), n.Var("x1"))), n.Var("x1")),),
                  n.Var("x0"))
    heavy = n.Let("a", call("add", n.Var("x0"), n.Lit(2)),
                  n.Let("b", call("sub", n.Var("x1"), n.Lit(1)),
                        call("add", n.Var("a"), n.Var("b"))))
    condition = n.And(n.Not(zero(n.Var("x0"))),
                      n.Or(zero(n.Var("x1")), zero(call("sub", n.Var("x0"), n.Var("x1")))))
    nested = n.Case(((condition, n.Case(((zero(n.Var("x1")), n.Lit(7)),), n.Lit(9))),), n.Lit(3))
    for body, inputs in ((same, [(3, 3), (3, 5), (5, 3)]),
                         (heavy, [(4, 5), (2, 2)]),
                         (nested, [(0, 0), (2, 0), (2, 2), (2, 3)])):
        prog = compile_tiny(body, ("x0", "x1"))
        assert validate(body, ("x0", "x1"), prog, inputs, 100).accepted

    inc = (call("add", n.Var("y"), n.Lit(1)), ("y",))
    defs = {"inc": inc}
    body = call("add", call("inc", n.Var("x0")), n.Lit(2))
    prog = compile_tiny(body, ("x0",), defs)
    result = validate(body, ("x0",), prog, [(0,), (252,)], 100)
    assert result.accepted
    different = compile_tiny(body, ("x0",), {"inc": (n.Lit(1), ("y",))})
    assert validate(body, ("x0",), different, [(0,)], 100).source_hash != result.source_hash


def test_family_enumeration_and_report_expected_overflow_rejections():
    family = tiny_family()
    assert len(family) == 1806
    assert n.length(family[0]) == 1 and n.length(family[-1]) == 5
    report = validate_compiler(family, [(0, 0), (15, 15)])
    assert report.method == "bounded" and report.total == 1806
    assert report.passed + len(report.rejected) == 1806
    assert report.scope["size"] == 2
    assert any(reason == "overflow" for _, reason, *_ in report.rejected)
    assert report.passed > 0


def test_full_default_family_all_256_inputs():
    report = validate_compiler()
    assert report.method == "bounded"
    assert report.total == 1806
    assert report.scope["size"] == 256
    assert (report.passed, len(report.rejected)) == (1020, 786)
    assert report.rejected[0] == (43, "overflow", (0, 1))
