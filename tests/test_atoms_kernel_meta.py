"""Metered atoms and memoized recursion (atoms-v2 spec sections 6 and 11.I1)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom, Defn, DictScope, Limits, call, evaluate, inline
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.core.semantics import NAN


def _scope():
    def safe(fn):
        return lambda *args: NAN if any(arg is NAN for arg in args) else fn(*args)

    return DictScope(atoms=[Atom("add", 2, safe(lambda left, right: left + right)),
                            Atom("dec", 1, safe(lambda value: value - 1)),
                            Atom("positive", 1, safe(lambda value: value > 0)),
                            Atom("bad", 0, lambda: Bottom("bad"))])


@pytest.mark.parametrize("dialect", ["atoms-v2", "legacy-v1"])
def test_metered_eval_has_direct_cost_and_trace(dialect):
    quoted = Defn("quoted", ("value",), n.Call("dec", (n.Var("value"),)))
    world = _scope().extend([quoted])
    world.atoms["eval"] = Atom("eval", 2, lambda ctx, code, value: ctx.call(code, (value,)),
                               cost=7, metered=True)
    direct = call("quoted", (9,), world, trace=True, dialect=dialect)
    metered = call("eval", (quoted, 9), world, trace=True, dialect=dialect)
    assert (metered.outcome, metered.steps, metered.work) == (direct.outcome, direct.steps, direct.work)
    assert [child.name for child in metered.trace.children] == ["eval"]
    assert [child.name for child in metered.trace.children[0].children] == ["quoted"]
    assert metered.trace.children[0].steps == 1
    wrapper = Defn("wrapper", ("value",), n.Call("eval", (n.Lit(quoted), n.Var("value"))))
    world = world.extend([wrapper])
    original = call("wrapper", (9,), world, dialect=dialect)
    expanded = evaluate(inline(n.Call("wrapper", (n.Lit(9),)), world), scope=world, dialect=dialect)
    assert (original.outcome, original.steps) == (expanded.outcome, expanded.steps)


def test_metered_budget_scope_and_nested_calls():
    inner = Defn("inner", ("value",), n.Call("dec", (n.Var("value"),)))
    wrapper = Defn("wrapper", ("value",), n.Call("inner", (n.Var("value"),)))
    world = _scope()
    world.atoms["eval"] = Atom("eval", 2, lambda ctx, budget, value: ctx.call(
        wrapper, (value,), extra_defns=(inner,), budget=budget), metered=True)
    assert call("eval", (1, 5), world).outcome == Ok(4)
    failed = call("eval", (0, 5), world)
    assert (failed.outcome, failed.steps) == (Unknown("fuel"), 0)
    assert world.resolve("wrapper") is None and world.resolve("inner") is None
    outer = Defn("outer", (), n.Call("eval", (n.Lit(0), n.Lit(5))))
    world = world.extend([outer])
    world.atoms["nested"] = Atom("nested", 0, lambda ctx: ctx.call("outer", ()), metered=True)
    result = call("nested", (), world, trace=True)
    assert result.outcome == Unknown("fuel")
    assert [child.name for child in result.trace.children[0].children] == ["outer"]
    assert result.trace.children[0].children[0].children[0].name == "eval"
    successful = Defn("successful", (), n.Call("eval", (n.Lit(1), n.Lit(5))))
    world = world.extend([successful])
    world.atoms["nested_ok"] = Atom("nested_ok", 0, lambda ctx: ctx.call("successful", ()),
                                    metered=True)
    assert (call("nested_ok", (), world).outcome, call("nested_ok", (), world).steps) == (Ok(4), 1)
    assert call("eval", (4, 5), world, limits=Limits(fuel=0)).outcome == Unknown("fuel")
    world.atoms["recover"] = Atom("recover", 0, lambda ctx: (
        ctx.call(wrapper, (5,), extra_defns=(inner,), budget=0),
        ctx.call(wrapper, (5,), extra_defns=(inner,), budget=1))[1], metered=True)
    assert (call("recover", (), world).outcome, call("recover", (), world).steps) == (Unknown("fuel"), 1)


def _recursion(memo, branching=2, stop=0, measure="legacy"):
    recursive = n.Call("fib", (n.Call("dec", (n.Var("value"),)),))
    body = n.Case(((n.Test(n.Call("positive", (n.Var("value"),))),
                    n.Call("add", (recursive, recursive)) if branching == 2 else recursive),),
                  n.Call("bad") if stop else n.Lit(1))
    return n.Rec("fib", ("value",), body, (n.Lit(6),), measure, memo)


def test_memo_reduces_work_without_reducing_charges():
    plain = evaluate(_recursion(False), scope=_scope(), trace=True)
    cached = evaluate(_recursion(True), scope=_scope(), trace=True)
    assert (plain.outcome, plain.steps, plain.jumps) == (cached.outcome, cached.steps, cached.jumps)
    assert cached.work < plain.work / 2

    def frames(frame):
        yield frame
        for child in frame.children:
            yield from frames(child)

    hits = [frame for frame in frames(cached.trace) if frame.memo_hit]
    assert hits and all(hit.name == "fib" and hit.steps > 0 and hit.children for hit in hits)


@settings(max_examples=320, deadline=None)
@given(start=st.integers(min_value=0, max_value=7), fuel=st.one_of(st.none(), st.integers(0, 100)),
       branching=st.integers(1, 2), stop=st.booleans(), measured=st.booleans(),
       legacy=st.booleans(), depth=st.integers(2, 12), nodes=st.one_of(st.none(), st.integers(1, 30)))
def test_memo_matches_plain_with_resources(start, fuel, branching, stop, measured, legacy, depth, nodes):
    world = _scope()
    measure = n.Var("value") if measured else "fuel"
    expr = _recursion(False, branching, stop, measure)
    expr = replace(expr, args=(n.Lit(start),))
    limits = Limits(fuel=fuel, max_depth=depth, max_nodes=nodes)
    dialect = "legacy-v1" if legacy else "atoms-v2"
    plain = evaluate(expr, scope=world, limits=limits, trace=True, dialect=dialect)
    memo = evaluate(replace(expr, memo=True), scope=world, limits=limits, trace=True, dialect=dialect)
    assert (memo.outcome, memo.steps, memo.jumps) == (plain.outcome, plain.steps, plain.jumps)
    assert memo.work <= memo.steps


def test_memo_preserves_value_type_and_inlining():
    world = _scope()
    expr = n.Rec("again", ("value",), n.Var("value"), (n.Lit(True),), memo=True)
    assert evaluate(expr, scope=world).outcome == Ok(True)
    assert inline(expr, world).memo
    for fuel in range(15):
        plain = evaluate(_recursion(False), scope=world, limits=Limits(fuel=fuel))
        memo = evaluate(_recursion(True), scope=world, limits=Limits(fuel=fuel))
        assert (plain.outcome, plain.steps) == (memo.outcome, memo.steps)
