"""Kernel execution and unfolding invariants (spec sections 3, 6 and 11.I1)."""

import random

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.kernel import (
    Atom,
    Defn,
    DictScope,
    FnRef,
    Limits,
    call,
    catch_atom,
    defined_atom,
    evaluate,
    inline,
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.core.semantics import NAN


def scope():
    def nan_safe(fn):
        return lambda *args: NAN if any(value is NAN for value in args) else fn(*args)

    return DictScope(atoms=[Atom("add", 2, nan_safe(lambda left, right: left + right)),
                            Atom("dec", 1, nan_safe(lambda value: value - 1)),
                            Atom("positive", 1, nan_safe(lambda value: value > 0)),
                            Atom("bad", 0, lambda: NAN),
                            Atom("byte_add", 2, nan_safe(lambda left, right: (left + right) % 256)),
                            defined_atom(), catch_atom()])


def test_strict_short_circuit_and_outcomes():
    visited = []
    world = scope()
    world.atoms["visit"] = Atom("visit", 0, lambda: visited.append(1))
    expression = n.Call("add", (n.Call("bad"), n.Call("visit")))
    result = evaluate(expression, scope=world)
    assert result.outcome == Bottom("undefined")
    assert result.steps == 1 and not visited
    assert evaluate(n.Call("catch", (n.Call("bad"),)), scope=world).outcome == Ok(
        Card("lift", "bot", ("undefined",)))
    assert evaluate(n.Call("defined", (n.Call("bad"),)), scope=world).outcome == Ok(False)
    assert evaluate(n.Call("defined", (n.Lit(Unknown("nodes")),)), scope=world).outcome == Unknown("nodes")
    assert DictScope(atoms=world.atoms, defns=world.defns).resolve("add") == world.resolve("add")


def test_legacy_bottom_flows_through_calls_and_bindings():
    visited = []
    world = scope().extend(defns=[Defn("ignore", ("unused", "value"), n.Var("value")),
                                  Defn("pass_through", ("value",), n.Var("value"))])
    world.atoms["visit"] = Atom("visit", 0, lambda: visited.append("visited") or 9)
    world.atoms["inspect"] = Atom("inspect", 2, lambda left, right: (left is NAN, right), cost=3)
    world.atoms["legacy_defined"] = Atom("legacy_defined", 1, lambda value: 0 if value is NAN else 1)
    expression = n.Call("inspect", (n.Call("bad"), n.Call("visit")))
    result = evaluate(expression, scope=world, dialect="legacy-v1", trace=True)
    assert (result.outcome, result.steps, visited) == (Ok((True, 9)), 5, ["visited"])
    # Argument calls are the caller's work: they precede the call as siblings.
    assert [child.name for child in result.trace.children] == ["bad", "visit", "inspect"]
    assert result.trace.children[-1].inputs == (Bottom("undefined"), 9)
    assert call("legacy_defined", (NAN,), world, dialect="legacy-v1").outcome == Ok(0)
    assert call("pass_through", (NAN,), world, dialect="legacy-v1").outcome == Bottom("undefined")
    ignored = n.Call("ignore", (n.Call("bad"), n.Call("visit")))
    assert evaluate(ignored, scope=world, dialect="legacy-v1").outcome == Ok(9)
    assert evaluate(ignored, scope=world).steps == 1
    bound = n.Let("unused", n.Call("bad"), n.Call("defined", (n.Var("unused"),)))
    assert evaluate(bound, scope=world, dialect="legacy-v1").outcome == Ok(False)
    assert evaluate(bound, scope=world).outcome == Bottom("undefined")
    assert evaluate(n.Case(((n.Test(n.Var("unused")), n.Lit(1)),)),
                    {"unused": Bottom("x")}, world, dialect="legacy-v1").outcome == Bottom("nan_condition")
    assert evaluate(n.Call("inspect", (n.Call("bad"), n.Lit(Unknown("other")))),
                    scope=world, dialect="legacy-v1").steps == 1
    assert evaluate(n.Call("inspect", (n.Call("bad"), n.Lit(Unknown("other")))),
                    scope=world, dialect="legacy-v1").outcome == Unknown("other")
    with pytest.raises(ValueError, match="dialect"):
        evaluate(n.Lit(1), dialect="unknown")


def test_legacy_recursive_bottom_and_fuel_measure():
    world = scope()
    ignore = n.Rec("ignore", ("unused",), n.Lit(42), (n.Call("bad"),), "fuel")
    assert evaluate(ignore, scope=world, dialect="legacy-v1").outcome == Ok(42)
    assert evaluate(ignore, scope=world).outcome == Bottom("undefined")
    infinite = n.Rec("again", ("value",), n.Call("again", (n.Var("value"),)),
                     (n.Lit(0),), "fuel")
    for measure in ("fuel", "legacy"):
        program = n.Rec(infinite.fn, infinite.params, infinite.body, infinite.args, measure)
        assert evaluate(program, scope=world, limits=Limits(max_depth=4)).outcome == Unknown("depth")
        assert evaluate(program, scope=world, limits=Limits(fuel=0, max_depth=4)).outcome == Unknown("depth")
    decrementing = countdown("fuel")
    assert evaluate(decrementing, {"start": 5}, world, Limits(fuel=3)).outcome == Unknown("fuel")
    assert evaluate(decrementing, {"start": 5}, world).outcome == Ok(0)


def test_trace_node_limit_independent_of_fuel():
    world = scope()
    program = n.Let("one", n.Call("dec", (n.Lit(3),)),
                    n.Let("two", n.Call("dec", (n.Var("one"),)),
                          n.Call("dec", (n.Var("two"),))))
    for dialect in ("atoms-v2", "legacy-v1"):
        bounded = evaluate(program, scope=world, trace=True, dialect=dialect,
                           limits=Limits(max_nodes=3))
        assert (bounded.outcome, bounded.steps) == (Unknown("nodes"), 2)
        assert len(bounded.trace.children) == 2
        assert bounded.trace.outcome == Unknown("nodes")
        assert evaluate(program, scope=world, trace=True, dialect=dialect,
                        limits=Limits(max_nodes=4)).outcome == Ok(0)
        assert evaluate(program, scope=world, trace=False, dialect=dialect,
                        limits=Limits(max_nodes=1)).outcome == Ok(0)
        empty = evaluate(program, scope=world, trace=True, dialect=dialect,
                         limits=Limits(max_nodes=0))
        assert empty.outcome == Unknown("nodes") and empty.trace is None
    zero_cost = DictScope(atoms=[Atom("tick", 0, lambda: 1, cost=0)])
    looping = n.Blocks((), "loop", (("loop", n.Block(
        (("value", n.Call("tick")),), n.Jump("loop"))),))
    bounded = evaluate(looping, scope=zero_cost, trace=True, limits=Limits(max_nodes=25))
    assert bounded.outcome == Unknown("nodes")
    assert len(bounded.trace.children) == 24
    assert bounded.steps == bounded.jumps == 24


def test_case_conditions_and_branch_order():
    world = scope()
    assert evaluate(n.Case(((n.Test(n.Call("bad")), n.Lit(1)),)), scope=world).outcome == Bottom("nan_condition")
    assert evaluate(n.Case(((n.Test(n.Lit(Unknown("nodes"))), n.Lit(1)),)), scope=world).outcome == Unknown("nodes")
    assert evaluate(n.Case(((n.Test(n.Lit(False)), n.Lit(1)),)), scope=world).outcome == Bottom("no_branch")
    chosen = n.Case(((n.Or(n.Test(n.Lit(True)), n.Test(n.Call("bad"))), n.Lit(7)),), n.Call("bad"))
    assert evaluate(chosen, scope=world).outcome == Ok(7)
    assert evaluate(n.Case(((n.And(n.Test(n.Lit(False)), n.Test(n.Call("bad"))), n.Lit(1)),), n.Lit(2)), scope=world).outcome == Ok(2)
    assert evaluate(n.Case(((n.Not(n.Test(n.Lit(Card("bool", "false")))), n.Lit(8)),)), scope=world).outcome == Ok(8)


def countdown(measure="legacy"):
    return n.Rec("loop", ("count",), n.Case(
        ((n.Test(n.Call("positive", (n.Var("count"),))),
          n.Call("loop", (n.Call("dec", (n.Var("count"),)),))),), n.Var("count")),
        (n.Var("start"),), measure)


def test_recursion_measure_depth_and_fuel():
    world = scope()
    good = evaluate(countdown(n.Var("count")), {"start": 7}, world)
    assert good.outcome == Ok(0) and good.steps == 15
    violated = n.Rec("loop", ("count",), n.Call("loop", (n.Var("count"),)),
                     (n.Lit(1),), n.Var("count"))
    assert evaluate(violated, scope=world).outcome == Bottom("measure")
    shadowed = n.Rec("loop", ("count",), n.Let("count", n.Lit(100),
        n.Call("loop", (n.Lit(0),))), (n.Lit(1),), n.Var("count"))
    assert evaluate(shadowed, scope=world, limits=Limits(max_depth=3)).outcome == Bottom("measure")
    assert evaluate(countdown(), {"start": 9999}, world).outcome == Ok(0)
    assert evaluate(countdown(), {"start": 10000}, world).outcome == Unknown("depth")
    exhausted = evaluate(countdown(), {"start": 50}, world, Limits(fuel=4))
    assert exhausted.outcome == Unknown("fuel") and exhausted.steps == 4
    expensive = DictScope(atoms=[Atom("expensive", 0, lambda: 7, cost=3)])
    assert call("expensive", (), expensive, Limits(fuel=2)).outcome == Unknown("fuel")
    assert call("expensive", (), expensive, Limits(fuel=2)).steps == 0
    assert call("expensive", (), expensive, Limits(fuel=3)).steps == 3
    assert evaluate(n.Blocks((), "spin", (("spin", n.Block((), n.Jump("spin"))),)),
                    scope=world, limits=Limits(fuel=3)).steps == 3


def test_trace_higher_order_and_let():
    world = scope().extend(defns=[Defn("twice", ("f", "x"),
        n.Call("f", (n.Call("f", (n.Var("x"),)),)), kind="combinator", layer=2)])
    result = call("twice", (FnRef("dec"), 5), world, trace=True)
    assert result.outcome == Ok(3) and result.steps == 2
    root = result.trace
    assert root.path == () and root.children[0].name == "twice"
    assert root.children[0].path == (0,)
    inner, outer = root.children[0].children
    assert (inner.name, inner.path, inner.inputs) == ("dec", (0, 0), (5,))
    assert (outer.name, outer.path, outer.inputs) == ("dec", (0, 1), (4,))
    assert not inner.children and not outer.children
    assert root.steps == root.children[0].steps == inner.steps + outer.steps
    assert evaluate(inline(n.Call("twice", (n.Lit(FnRef("dec")), n.Lit(5))), world), scope=world).steps == 2
    assert evaluate(n.Let("x", n.Call("dec", (n.Lit(5),)),
                          n.Call("add", (n.Var("x"), n.Var("x")))), scope=world).steps == 2
    with pytest.raises(KeyError):
        call("missing", (), world)


def test_trace_jumps_and_unfold_capture():
    world = scope().extend(defns=[Defn("program", ("x",), n.Blocks(
        (("total", n.Var("x")),), "start", (("start", n.Block(
            (("total", n.Call("dec", (n.Var("total"),))),), n.Jump("end"))),
            ("end", n.Block((), n.Halt(n.Var("total"))))))),
        Defn("capture", ("x",), n.Call("add", (n.Var("x"), n.Lit(1)))),
        Defn("free", ("x",), n.Call("add", (n.Var("x"), n.Var("y"))))])
    result = call("program", (8,), world, trace=True)
    frame = result.trace.children[0]
    assert (result.outcome, result.steps, result.jumps) == (Ok(7), 2, 1)
    assert frame.steps == sum(child.steps for child in frame.children) + 1
    # Lexical scope: a body sees only its parameters, and inlining never captures caller names.
    expr = n.Let("__inline_arg_1", n.Lit(7), n.Call("capture", (n.Var("__inline_arg_1"),)))
    assert evaluate(expr, scope=world).outcome == Ok(8)
    assert evaluate(inline(expr, world), scope=world).outcome == Ok(8)
    with pytest.raises(KeyError):
        evaluate(n.Let("y", n.Lit(1), n.Call("free", (n.Lit(2),))), scope=world)


def test_blocks_byte_multiplication():
    world = scope()
    program = n.Blocks((("value", n.Var("a")), ("count", n.Var("b")), ("total", n.Lit(0))),
                       "check", (("check", n.Block((), n.CondJump(
                           n.Test(n.Call("positive", (n.Var("count"),))), "loop", "end"))),
                                 ("loop", n.Block((("total", n.Call("byte_add", (n.Var("total"), n.Var("value")))),
                                                    ("count", n.Call("dec", (n.Var("count"),)))), n.Jump("check"))),
                                 ("end", n.Block((), n.Halt(n.Var("total"))))))
    for left in range(256):
        for right in range(16):
            result = evaluate(program, {"a": left, "b": right}, world)
            assert result.outcome == Ok(left * right % 256)
            assert result.jumps == 2 * right + 1
            assert result.steps == 5 * right + 2


def test_unfold_equivalence_seeded():
    rng = random.Random(4873)
    world = scope().extend(defns=[Defn("identity", ("x",), n.Var("x")),
                                   Defn("choose", ("x",), n.Case(((n.Test(n.Call("positive", (n.Var("x"),))),
                                                                     n.Call("dec", (n.Var("x"),))),), n.Lit(0))),
                                   Defn("recursive", ("start",), countdown()),
                                   Defn("ignore", ("unused", "start"), n.Var("start")),
                                   Defn("check", ("unused", "start"),
                                        n.Call("defined", (n.Var("unused"),)))])
    for _ in range(220):
        seed = rng.randrange(7)
        mode = rng.randrange(5)
        body = (n.Call("add", (n.Var("start"), n.Lit(seed))) if mode == 0 else
                n.Case(((n.Test(n.Call("positive", (n.Var("start"),))),
                         n.Call("dec", (n.Var("start"),))),), n.Lit(seed)) if mode == 1 else
                countdown(n.Var("count")) if mode == 2 else
                n.Call("ignore", (n.Call("bad"), n.Var("start"))) if mode == 3 else
                n.Call("check", (n.Call("bad"), n.Var("start"))))
        generated = world.extend(defns=[Defn("generated", ("start",), body)])
        expression = n.Call("generated", (n.Call("bad") if rng.randrange(4) == 0
                                            else n.Lit(rng.randrange(7)),))
        unfolded = inline(expression, generated)
        for dialect in ("atoms-v2", "legacy-v1"):
            original = evaluate(expression, scope=generated, dialect=dialect)
            expanded = evaluate(unfolded, scope=generated, dialect=dialect)
            assert (original.outcome, original.steps) == (expanded.outcome, expanded.steps)
    recursive = Defn("self", ("x",), n.Case(((n.Test(n.Call("positive", (n.Var("x"),))),
                              n.Call("self", (n.Call("dec", (n.Var("x"),)),))),), n.Var("x")))
    world = world.extend(defns=[recursive])
    for count in range(12):
        expr = n.Call("self", (n.Lit(count),))
        unfolded = inline(expr, world)
        for dialect in ("atoms-v2", "legacy-v1"):
            original = evaluate(expr, scope=world, dialect=dialect)
            expanded = evaluate(unfolded, scope=world, dialect=dialect)
            assert (original.outcome, original.steps) == (expanded.outcome, expanded.steps)


def test_nested_evaluation_does_not_deadlock():
    inner = DictScope(atoms=[Atom("dec", 1, lambda value: value - 1)])
    outer = DictScope(atoms=[Atom("nested", 1, lambda value: evaluate(
        n.Call("dec", (n.Lit(value),)), scope=inner).outcome, cost=0)])
    assert evaluate(n.Call("nested", (n.Lit(5),)), scope=outer).outcome == Ok(4)


def test_unmemoized_work_matches_charged_steps():
    world = scope()
    for dialect in ("atoms-v2", "legacy-v1"):
        for fuel in (None, 0, 2, 15):
            run = evaluate(countdown("fuel"), {"start": 5}, world,
                           Limits(fuel=fuel), dialect=dialect)
            assert run.work == run.steps
