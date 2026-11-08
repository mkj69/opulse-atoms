"""Review-6 regressions for metered code preflight and scope isolation."""

import random
from dataclasses import replace

import pytest

from opulse.atoms import kernel, objects
from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.meta import code, engine
from opulse.meta import gen_code as G
from opulse.meta.worlds.code.world import library


def _program(body, params=(), digest=None, output="int"):
    resolver = lambda name: (code.Resolved(digest=digest if digest is not None else G.DIGESTS[name])
                             if digest is not None or name in G.DIGESTS else None)
    return code.make_code("operation", code.sig_op((('int', 'bottom'),) * len(params),
                                                    (output, 'bottom')), params, body, resolver)


def test_atom_replacement_and_scope_mutation_do_not_poison_cache():
    lib = library()
    assert lib.run("add", (1, 2)).outcome == Ok(3)
    scope = lib.scope()
    scope.atoms["add"] = kernel.Atom("add", 2, lambda left, right: 100)
    assert lib.run("add", (1, 2)).outcome == Ok(3)
    lib.atoms = tuple(kernel.Atom("add", 2, lambda left, right: 500) if atom.name == "add" else atom
                      for atom in lib.atoms)
    assert lib.run("add", (1, 2)).outcome == Ok(500)
    digest = code.atom_digest(next(op for op in lib.world.operations if op.name == "add"))
    reflected = code.make_code("operation", code.sig_op((), ("int", "bottom")), (),
                               n.Call("add", (n.Lit(1), n.Lit(2))),
                               lambda name: code.Resolved(digest=digest))
    assert lib.run("eval", (reflected, code.lst())).outcome == Ok(500)


def test_world_change_rebinds_metered_digest():
    lib = library()

    def program():
        digest = code.atom_digest(next(op for op in lib.world.operations if op.name == "add"))
        return code.make_code("operation", code.sig_op((), ("int", "bottom")), (),
                              n.Call("add", (n.Lit(1), n.Lit(2))),
                              lambda name: code.Resolved(digest=digest))

    old = program()
    assert (lib.run("eval", (old, code.lst())).outcome,
            lib.run("run", (old, code.lst(), 3)).outcome) == (Ok(3), Ok(code.Card("result", "ok", (3,))))
    lib.world = replace(lib.world, operations=tuple(
        replace(op, rule="CHANGED RULE") if op.name == "add" else op for op in lib.world.operations))
    assert lib.run("eval", (old, code.lst())).outcome == Bottom("foreign_code")
    assert lib.run("eval", (program(), code.lst())).outcome == Ok(3)


def test_reentrant_scope_reader_cannot_mutate_stored_definition(monkeypatch):
    lib = library()
    original = objects._objects
    leaked = []

    def inspect(target):
        if target is lib:
            leaked.append(lib.definitions["add"])
        return original(target)

    monkeypatch.setattr(objects, "_objects", inspect)
    lib.scope()
    assert leaked and leaked[0] is not lib._definitions["add"]
    leaked[0].spec.extra["tampered"] = True
    assert "tampered" not in lib.get("add").spec.extra


@pytest.mark.parametrize("wrapper", ["direct", "let", "rec"])
def test_operation_argument_call_arity_preflight(wrapper):
    call = n.Call("f", (n.Var("x"),))
    body = (call if wrapper == "direct" else
            n.Let("saved", n.Lit(0), call) if wrapper == "let" else
            n.Rec("loop", ("y",), call, (n.Var("x"),), "y"))
    caller = _program(body, ("f", "x"))
    nullary = _program(n.Lit(17))
    scope = G.scope()
    for name, arguments in (("eval", (caller, code.lst((nullary, 2)))),
                            ("run", (caller, code.lst((nullary, 2)), 1)),
                            ("eval", (caller, code.lst((code._expr("fn", "add"), 2))))):
        result = engine.call(name, arguments, scope, trace=True)
        assert (result.outcome, result.steps) == (Bottom("ill_formed"), 0)


def test_shadowed_operation_parameter_is_not_misidentified():
    caller = _program(n.Let("f", n.Lit(2), n.Call("add", (n.Var("f"), n.Var("x")))), ("f", "x"))
    result = engine.call("eval", (caller, code.lst((3, 4))), G.scope())
    assert (result.outcome, result.steps) == (Ok(6), 1)
    rec = n.Rec("f", ("y",), n.Case(((n.Test(n.Call("is_zero", (n.Lit(0),))), n.Lit(8)),),
                                        n.Call("f", (n.Var("y"),))), (n.Var("x"),), "fuel")
    shadowed = _program(rec, ("f", "x"))
    result = engine.call("eval", (shadowed, code.lst((3, 4))), G.scope())
    assert (result.outcome, result.steps) == (Ok(8), 1)


def test_inline_keeps_foreign_and_ill_formed_literal_eval():
    foreign = _program(n.Call("add", (n.Lit(1), n.Lit(2))), digest="not-the-world-digest")
    malformed = replace(foreign, fields=("operation", code.sig_op((), ("int", "bottom")),
                                         code._expr("lit", 3), *foreign.fields[3:]))
    for value, reason in ((foreign, "foreign_code"), (malformed, "ill_formed")):
        expr = n.Call("eval", (n.Lit(value), n.Lit(code.lst())))
        assert engine.inline(expr, G.scope()) == expr
        original = engine.evaluate(expr, scope=G.scope())
        expanded = engine.evaluate(engine.inline(expr, G.scope()), scope=G.scope())
        assert (original.outcome, original.steps) == (expanded.outcome, expanded.steps) == (Bottom(reason), 0)


def test_eval_and_run_random_arity_inputs_never_raise():
    rng = random.Random(607)
    caller = _program(n.Call("f", (n.Var("x"),)), ("f", "x"))
    operation = tuple(_program(n.Lit(17), ("x", "y")[:arity]) for arity in (0, 1, 2))
    for _ in range(100):
        arg = rng.choice(operation)
        arguments = (caller, code.lst((arg, rng.randrange(10))))
        for name, values in (("eval", arguments), ("run", (*arguments, 5))):
            result = engine.call(name, values, G.scope())
            assert isinstance(result.outcome, (Ok, Bottom))


def test_four_nested_runs_with_intervening_eval_and_competing_deadlines():
    leaf = _program(n.Call("add", (n.Lit(1), n.Lit(2))))

    def nested(budgets):
        first = _program(n.Call("run", (n.Lit(leaf), n.Lit(code.lst()), n.Lit(budgets[0]))),
                         output="result")
        through_eval = _program(n.Call("eval", (n.Lit(first), n.Lit(code.lst()))), output="result")
        second = _program(n.Call("run", (n.Lit(through_eval), n.Lit(code.lst()),
                                         n.Lit(budgets[1]))), output="result")
        third = _program(n.Call("run", (n.Lit(second), n.Lit(code.lst()), n.Lit(budgets[2]))),
                         output="result")
        return third

    def ok(value):
        return Card("result", "ok", (value,))

    tied = engine.call("run", (nested((1, 1, 1)), code.lst(), 1), G.scope(), trace=True)
    assert (tied.outcome, tied.steps) == (Ok(ok(ok(ok(ok(3))))), 1)
    inner_deadline = engine.call("run", (nested((0, 2, 2)), code.lst(), 2), G.scope())
    assert (inner_deadline.outcome, inner_deadline.steps) == (Ok(ok(ok(ok(Card("result", "out", (0,)))))), 0)
    outer_deadline = engine.call("run", (nested((2, 2, 2)), code.lst(), 0), G.scope())
    assert (outer_deadline.outcome, outer_deadline.steps) == (Ok(Card("result", "out", (0,))), 0)
    fuel = engine.call("run", (nested((2, 2, 2)), code.lst(), 2), G.scope(),
                       kernel.Limits(fuel=0))
    assert (fuel.outcome, fuel.steps) == (Unknown("fuel"), 0)
