"""Regressions for kernel accounting and unfolding (atoms-v2 sections 6, 10, 11, 13)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.golden import EngineResult, GoldenCase, compare_kernel
from opulse.atoms.kernel import (
    Atom,
    CallNode,
    Defn,
    DictScope,
    FnRef,
    Limits,
    call,
    evaluate,
    inline,
)
from opulse.atoms.values import Bottom, Ok, Unknown, boolean
from opulse.atoms.verify import unfold_equivalent_calls


def test_measure_has_separate_fuel_and_depth_limits():
    scope = DictScope(atoms=[Atom("measure", 1, lambda value: value, cost=2)])
    expr = n.Rec("f", ("x",), n.Var("x"), (n.Lit(3),), n.Call("measure", (n.Var("x"),)))
    for dialect in ("atoms-v2", "legacy-v1"):
        for program in (expr, inline(expr, scope)):
            run = evaluate(program, scope=scope, limits=Limits(fuel=0), dialect=dialect, trace=True)
            assert (run.outcome, run.steps, run.trace.children) == (Unknown("fuel"), 0, [])
        assert evaluate(expr, scope=scope, limits=Limits(fuel=2), dialect=dialect).outcome == Ok(3)

    def recursion():
        return n.Rec("inner", ("x",), n.Var("x"), (n.Lit(1),))

    depth = n.Rec("outer", ("x",), n.Var("x"), (n.Lit(1),), recursion())
    for program in (depth, inline(depth, scope)):
        assert evaluate(program, scope=scope, limits=Limits(max_depth=0)).outcome == Unknown("depth")
    bottom = n.Rec("f", ("x",), n.Var("x"), (n.Lit(1),), n.Lit(Bottom("bad")))
    assert evaluate(bottom, scope=scope).outcome == Bottom("measure")


def test_inline_preserves_definition_scope_and_renames_local_bindings():
    scope = DictScope([Atom("h", 0, lambda: 7), Atom("other", 0, lambda: 9)],
                      [Defn("g", (), n.Call("h"))])
    expr = n.Let("h", n.Lit(FnRef("other")), n.Call("g"))
    for dialect in ("atoms-v2", "legacy-v1"):
        direct = evaluate(expr, scope=scope, dialect=dialect)
        expanded = evaluate(inline(expr, scope), scope=scope, dialect=dialect)
        assert (direct.outcome, direct.steps) == (expanded.outcome, expanded.steps) == (Ok(7), 1)


def test_inline_fresh_names_do_not_capture_free_names_in_nested_definitions():
    scope = DictScope([Atom("__inline_arg_1", 0, lambda: 7)],
                      [Defn("g", (), n.Call("__inline_arg_1"))])
    expr = n.Let("h", n.Lit(FnRef("g")), n.Call("h"))
    for dialect in ("atoms-v2", "legacy-v1"):
        direct = evaluate(expr, scope=scope, dialect=dialect)
        expanded = evaluate(inline(expr, scope), scope=scope, dialect=dialect)
        assert (direct.outcome, direct.steps) == (expanded.outcome, expanded.steps) == (Ok(7), 1)


def test_inline_renames_blocks_vars_and_recursive_function_bindings():
    scope = DictScope([Atom("h", 0, lambda: 7), Atom("other", 0, lambda: 9)],
                      [Defn("g", (), n.Call("h"))])
    blocks = n.Blocks((("h", n.Lit(FnRef("other"))),), "entry",
                      (("entry", n.Block((), n.Halt(n.Call("g")))),))
    recursive = n.Rec("h", ("value",), n.Call("g"), (n.Lit(1),))
    for expr in (blocks, recursive):
        for dialect in ("atoms-v2", "legacy-v1"):
            direct = evaluate(expr, scope=scope, dialect=dialect)
            expanded = evaluate(inline(expr, scope), scope=scope, dialect=dialect)
            assert (direct.outcome, direct.steps) == (expanded.outcome, expanded.steps) == (Ok(7), 1)


@given(local=st.sampled_from(("h", "other", "g", "__inline_arg_1")),
       caller=st.sampled_from(("h", "other", "g")),
       target=st.sampled_from(("h", "other")),
       value=st.integers(-10, 10), dialect=st.sampled_from(("atoms-v2", "legacy-v1")))
@settings(max_examples=100, derandomize=True, deadline=None)
def test_inline_let_bound_fnrefs_and_scope_name_collisions(local, caller, target, value, dialect):
    scope = DictScope([Atom("h", 1, lambda item: item + 2),
                       Atom("other", 1, lambda item: item * 3)],
                      [Defn("g", ("input",), n.Let(local, n.Lit(FnRef(target)),
                                                  n.Call(local, (n.Var("input"),))))])
    expr = n.Let(caller, n.Lit(FnRef("other")), n.Call("g", (n.Lit(value),)))
    direct = evaluate(expr, scope=scope, dialect=dialect)
    expanded = evaluate(inline(expr, scope), scope=scope, dialect=dialect)
    assert (direct.outcome, direct.steps) == (expanded.outcome, expanded.steps)


def test_memo_hit_replays_subtree_and_verifier_rejects_missing_steps():
    scope = DictScope(atoms=[Atom("positive", 1, lambda value: boolean(value > 0)),
                             Atom("tick", 0, lambda: 1),
                             Atom("add", 2, lambda left, right: left + right)])
    sub = n.Call("f", (n.Lit(0),))
    expr = n.Rec("f", ("x",), n.Case(
        ((n.Test(n.Call("positive", (n.Var("x"),))), n.Call("add", (sub, sub))),),
        n.Call("tick")), (n.Lit(1),), "fuel", True)
    run = evaluate(expr, scope=scope, trace=True)
    boundary = Boundary.unfold_all()
    assert run.steps == sum(frame.steps for frame in flatten_calls(run.trace, boundary)) == 6
    assert unfold_equivalent_calls(run.trace, [boundary, Boundary.unfold_none()]).ok
    hit = run.trace.children[0].children[-2]
    assert hit.memo_hit and hit.children
    hit.children.clear()
    assert not unfold_equivalent_calls(run.trace, [boundary]).ok


def test_definition_own_steps_must_be_jumps():
    derived = CallNode("derived", "operation", 1, False, (0,), (), Ok(1), 2)
    root = CallNode(None, "root", 0, False, (), (), Ok(1), 2, [derived])
    assert not unfold_equivalent_calls(root, [Boundary.unfold_all()]).ok
    derived.jumps = 2
    assert unfold_equivalent_calls(root, [Boundary.unfold_all()]).ok


def test_metered_atom_children_verify_and_unfold():
    scope = DictScope(atoms=[Atom("tick", 0, lambda: 1),
                             Atom("meta", 0, lambda ctx: ctx.call("tick", ()), metered=True)])
    result = call("meta", (), scope, trace=True)
    assert (result.outcome, result.steps) == (Ok(1), 1)
    assert result.trace.children[0].metered
    assert unfold_equivalent_calls(result.trace, [Boundary.unfold_all(), Boundary.unfold_none()]).ok


def test_golden_checks_base_ops_even_when_trace_is_incomplete():
    case = GoldenCase("integer", "published", 1, "f", "f(x)", ("int",), (1,), 2,
                      [{"kind": "eval", "gate": "f", "value": {"t": "int", "v": 2}}],
                      "operator_example")
    steps = [{"kind": "eval", "gate": "f", "value": 2}]
    assert compare_kernel(case, EngineResult(2, steps, base_ops=1, trace_complete=False)) == []
    assert any("base_ops" in diff for diff in compare_kernel(
        case, EngineResult(2, steps, base_ops=999, trace_complete=False)))


def test_variables_never_shadow_scope_names_in_call_position():
    from opulse.atoms import nodes as n
    from opulse.atoms.kernel import Atom, Defn, DictScope, FnRef, evaluate, inline

    scope = DictScope([Atom("weekday", 1, lambda value: value % 7), Atom("other", 1, lambda value: -value)],
                      [Defn("nth", ("weekday", "day"), n.Call("weekday", (n.Var("day"),)))])
    expr = n.Call("nth", (n.Lit(3), n.Lit(9)))
    assert evaluate(expr, scope=scope).outcome == evaluate(inline(expr, scope), scope=scope).outcome
    assert evaluate(expr, scope=scope).outcome.value == 2  # the int parameter does not hide the operation
    shadow = n.Let("weekday", n.Lit(FnRef("other")), n.Call("weekday", (n.Lit(9),)))
    assert evaluate(shadow, scope=scope).outcome.value == 2
    assert evaluate(inline(shadow, scope), scope=scope).outcome.value == 2
