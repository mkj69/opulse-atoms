"""Exact metered execution and unfolding checks (atoms-meta sections 2.5-2.7, 8)."""

import os
import random
import subprocess
import sys
from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.atoms.verify import unfold_equivalent
from opulse.meta import code, engine

DIGESTS = {name: "digest-" + name for name in ("add", "dec", "zero", "fail", "eval", "run")}
ATOMS = (
    kernel.Atom("add", 2, lambda left, right: left + right),
    kernel.Atom("dec", 1, lambda value: value - 1),
    kernel.Atom("zero", 1, lambda value: value == 0),
    kernel.Atom("fail", 0, lambda: Bottom("broken")),
)
OP = code.sig_op([("int", "bottom")], ("int", "bottom"))


def resolve(*names, dependencies=None):
    dependencies = dependencies or {}
    return lambda name: (code.Resolved(code=dependencies[name]) if name in dependencies else
                         code.Resolved(digest=DIGESTS[name]) if name in names else None)


def scope():
    return kernel.DictScope((*ATOMS, engine.eval_atom(ATOMS, DIGESTS),
                             engine.run_atom(ATOMS, DIGESTS)))


def test_extended_scope_shadows_parent_without_changing_parent():
    parent = kernel.DictScope(ATOMS)
    replacement = kernel.Defn("add", ("left", "right"), n.Var("right"))
    extended = engine._extend(parent, (replacement,))
    assert extended.resolve("add") is replacement
    assert extended.resolve("dec") is parent.resolve("dec")
    assert parent.resolve("add") is ATOMS[0]


def make(body, kind="operation", sig=OP, params=("value",), names=(), dependencies=None):
    return code.make_code(kind, sig, params, body, resolve(*names, dependencies=dependencies))


def evaluate_code(program, args=(), operation="eval", fuel=None, trace=True):
    payload = (program, code.lst(args))
    if operation == "run":
        raise AssertionError("use engine.call for run budgets")
    return engine.call(operation, payload, scope(), kernel.Limits(fuel=fuel), trace=trace)


def test_core_parity_and_metered_context():
    ordinary = kernel.DictScope(ATOMS, (kernel.Defn("double", ("x",), n.Call("add", (n.Var("x"), n.Var("x")))),))
    programs = (n.Call("double", (n.Lit(4),)), n.Call("fail"),
                n.Case(((n.Test(n.Call("zero", (n.Lit(0),))), n.Lit(7)),), n.Lit(9)))
    for program in programs:
        for fuel in (None, 0, 1, 2):
            limits = kernel.Limits(fuel=fuel)
            assert engine.evaluate(program, scope=ordinary, limits=limits, trace=True) == kernel.evaluate(
                program, scope=ordinary, limits=limits, trace=True)

    def twice(ctx, value):
        return ctx.call(kernel.Defn("helper", ("x",), n.Call("add", (n.Var("x"), n.Var("x")))), (value,))

    metered = kernel.DictScope((*ATOMS, engine.MeteredAtom("twice", 1, twice)))
    assert isinstance(metered.resolve("twice"), kernel.Atom)
    assert (metered.resolve("twice").cost, metered.resolve("twice").strict,
            metered.resolve("twice").metered) == (0, True, True)
    result = engine.call("twice", (4,), metered, trace=True)
    native = kernel.call("twice", (4,), metered, trace=True)
    assert (native.outcome, native.steps) == (Ok(8), 1)
    assert native.trace.children[0].metered
    assert (result.outcome, result.steps) == (Ok(8), 1)
    outer = result.trace.children[0]
    assert (outer.name, outer.given, outer.metered, outer.steps) == ("twice", True, True, 1)
    assert [(child.name, child.steps) for child in outer.children] == [("helper", 1)]
    assert [child.name for child in outer.children[0].children] == ["add"]


def test_world_metered_atom_evidence_hash_is_process_stable():
    script = """from opulse.atoms.library import atoms_digest
from opulse.meta.worlds.code.hosts import atoms as code_atoms
from opulse.meta.worlds.builder.hosts import atoms as builder_atoms
print(atoms_digest(code_atoms()), atoms_digest(builder_atoms()))
"""
    digests = [subprocess.run((sys.executable, "-c", script), check=True, capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": seed}).stdout.strip()
               for seed in ("1", "2")]
    assert digests[0] == digests[1]
    assert all(len(digest) == 64 for digest in digests[0].split())


def test_quote_eval_six_cases_exact_outcomes_and_steps():
    inc = make(n.Call("add", (n.Var("value"), n.Lit(1))), names=("add",))
    dep = make(n.Call("#" + code.code_hash(inc), (n.Var("value"),)),
               dependencies={"#" + code.code_hash(inc): inc})
    rec = make(n.Rec("loop", ("i",), n.Case(((n.Test(n.Call("zero", (n.Var("i"),))), n.Lit(5)),),
                                               n.Call("loop", (n.Call("dec", (n.Var("i"),)),))),
                         (n.Var("value"),), "fuel"), names=("zero", "dec"))
    failed = make(n.Case(((n.Test(n.Call("fail")), n.Lit(8)),), n.Lit(9)),
                  sig=code.sig_op([], ("int", "bottom")), params=(), names=("fail",))
    comb = make(n.Call("f", (n.Call("f", (n.Var("value"),)),)), kind="combinator",
                sig=code.sig_comb(2, (0,)), params=("f", "value"))
    constant = make(n.Lit(17), kind="object", sig=code.sig_const(), params=())
    cases = ((inc, (3,), Ok(4), 1), (dep, (3,), Ok(4), 1),
             (rec, (2,), Ok(5), 5), (failed, (), Bottom("nan_condition"), 1),
             (comb, (code._expr("fn", "dec"), 4), Ok(2), 2),
             (constant, (), Ok(17), 0))
    definitions = {}
    for index, (program, _, _, _) in enumerate(cases):
        kind, sig, body = program.fields[:3]
        if kind == "operation":
            params = (("value",) if index in (0, 1) else ("x0",)) if code.sig_arity(sig) else ()
            spec = OperationSpec(f"program{index}", "transform", tuple(Edge("int") for _ in params),
                                 Edge("int"), "kernel body", extra={"input_names": list(params)})
        elif kind == "combinator":
            params = ("x0", "x1")
            spec = CombinatorSpec(f"program{index}", params, ("x0",), n.Lit(0))
        else:
            spec = ObjectSpec(f"program{index}", "constant", body=n.Lit(17))
        source = (n.Call("inc", (n.Var("value"),)) if program == dep else
                  n.Call("add", (n.Var("value"), n.Lit(1))) if program == inc else
                  code.decode_node(body))
        definitions[program] = Definition(f"program{index}", kind, "invented", 1, (), spec, source)
    for program, args, expected, steps in cases:
        quoted = code.quote(definitions[program], lambda name: definitions[inc] if name == "inc" else None,
                            DIGESTS)
        assert quoted == program
        decoded = code.decode(program)
        direct_args = tuple(kernel.FnRef("dec") if isinstance(arg, Card) and arg.tag == "fn" else arg
                            for arg in args)
        direct = engine.call(decoded.main.name, direct_args,
                             kernel.DictScope(ATOMS, (decoded.main, *decoded.deps)), trace=True)
        actual = evaluate_code(program, args)

        def layer_zero(frame):
            if frame.given and not frame.children and frame.steps:
                return [(frame.name, frame.inputs, frame.outcome, frame.steps)]
            return [step for child in frame.children for step in layer_zero(child)]

        assert (direct.outcome, direct.steps) == (expected, steps)
        assert (actual.outcome, actual.steps) == (expected, steps)
        assert layer_zero(actual.trace) == layer_zero(direct.trace)
        eval_frame = actual.trace.children[0]
        assert (eval_frame.name, eval_frame.kind, eval_frame.given, eval_frame.steps) == (
            "eval", "operation", True, steps)
        assert [frame.name for frame in eval_frame.children] == [decoded.main.name]
        assert eval_frame.children[0].steps == steps
        literal = n.Call("eval", (n.Lit(program), n.Lit(code.lst(args))))
        unfolded = engine.evaluate(engine.inline(literal, scope()), scope=scope())
        assert (unfolded.outcome, unfolded.steps) == (expected, steps)
        if steps:
            assert evaluate_code(program, args, fuel=steps - 1).outcome == Unknown("fuel")
        assert evaluate_code(program, args, fuel=steps).outcome == expected


def test_run_ok_err_out_and_outer_fuel():
    program = make(n.Call("add", (n.Var("value"), n.Lit(1))), names=("add",))
    for budget, fuel, expected, steps in (
        (1, None, Ok(Card("result", "ok", (5,))), 1),
        (0, None, Ok(Card("result", "out", (0,))), 0),
        (4, 0, Unknown("fuel"), 0),
    ):
        result = engine.call("run", (program, code.lst((4,)), budget), scope(),
                             kernel.Limits(fuel=fuel), trace=True)
        assert (result.outcome, result.steps) == (expected, steps)
        assert result.trace.children[0].steps == steps
    failed = make(n.Call("fail"), sig=code.sig_op([], ("int", "bottom")), params=(), names=("fail",))
    assert engine.call("run", (failed, code.lst(), 1), scope()).outcome == Ok(
        Card("result", "err", ("broken",)))
    twice = make(n.Call("add", (n.Call("add", (n.Var("value"), n.Lit(1))), n.Lit(1))),
                 names=("add",))
    for fuel, expected in ((None, Ok(Card("result", "out", (1,)))),
                           (2, Ok(Card("result", "out", (1,)))),
                           (1, Ok(Card("result", "out", (1,)))), (0, Unknown("fuel"))):
        result = engine.call("run", (twice, code.lst((4,)), 1), scope(),
                             kernel.Limits(fuel=fuel), trace=True)
        assert (result.outcome, result.steps) == (expected, 1 if fuel != 0 else 0)


def test_run_nested_call_limit_is_out_not_depth():
    endless = make(n.Rec("loop", (), n.Call("loop"), (), "fuel"),
                   sig=code.sig_op([], ("int", "bottom")), params=())
    result = engine.call("run", (endless, code.lst(), 3), scope())
    assert result.outcome == Ok(Card("result", "out", (3,)))
    assert result.steps == 0


def test_outer_run_budget_wins_over_nested_run_budget():
    inner = make(n.Call("add", (n.Var("value"), n.Lit(1))), names=("add",))
    outer = make(n.Call("run", (n.Lit(inner), n.Lit(code.lst((4,))), n.Lit(2))),
                 sig=code.sig_op([], ("result", "bottom")), params=(), names=("run",))
    assert engine.call("run", (outer, code.lst(), 0), scope()).outcome == Ok(
        Card("result", "out", (0,)))
    assert engine.call("run", (outer, code.lst(), 1), scope()).outcome == Ok(
        Card("result", "ok", (Card("result", "ok", (5,)),)))
    short = make(n.Call("run", (n.Lit(inner), n.Lit(code.lst((4,))), n.Lit(0))),
                 sig=code.sig_op([], ("result", "bottom")), params=(), names=("run",))
    assert engine.call("run", (short, code.lst(), 2), scope()).outcome == Ok(
        Card("result", "ok", (Card("result", "out", (0,)),)))


def test_nested_eval_and_preflight():
    inner = make(n.Call("add", (n.Var("value"), n.Lit(1))), names=("add",))
    outer = make(n.Call("eval", (n.Lit(inner), n.Lit(code.lst((4,))))),
                 sig=code.sig_op([], ("int", "bottom")), params=(), names=("eval",))
    nested = evaluate_code(outer)
    assert (nested.outcome, nested.steps) == (Ok(5), 1)
    assert evaluate_code(outer, fuel=0).outcome == Unknown("fuel")
    assert [child.name for child in nested.trace.children[0].children[0].children] == ["eval"]
    assert [child.name for child in nested.trace.children[0].children[0].children[0].children] == [
        code.decode(inner).main.name]
    literal = n.Call("eval", (n.Lit(outer), n.Lit(code.lst())))
    unfolded = engine.evaluate(engine.inline(literal, scope()), scope=scope())
    assert (unfolded.outcome, unfolded.steps) == (Ok(5), 1)
    assert evaluate_code(inner).outcome == Bottom("arity")
    assert evaluate_code(inner, (4,), fuel=0).outcome == Unknown("fuel")
    changed = kernel.DictScope((*ATOMS, engine.eval_atom(ATOMS, {**DIGESTS, "add": "changed"})))
    assert engine.call("eval", (inner, code.lst((4,))), changed).outcome == Bottom("foreign_code")
    bad = Card("code", "def", ("operation", OP, code.encode_node(n.Call("missing", (n.Var("x0"),))),
                                  code.lst(), code.lst()))
    assert evaluate_code(bad, (4,)).outcome == Bottom("ill_formed")
    undeclared = Card("code", "def", ("operation", OP,
                                         code.encode_node(n.Call("add", (n.Var("x0"), n.Lit(1)))),
                                         code.lst(), code.lst()))
    assert evaluate_code(undeclared, (4,)).outcome == Bottom("ill_formed")
    wrong_sig = Card("code", "def", ("operation", code.sig_obs(()), code.encode_node(n.Lit(1)),
                                        code.lst(), code.lst()))
    assert evaluate_code(wrong_sig).outcome == Bottom("ill_formed")
    free = Card("code", "def", ("operation", OP, code.encode_node(n.Var("unbound")),
                                   code.lst(), code.lst()))
    assert evaluate_code(free, (4,)).outcome == Bottom("ill_formed")
    missing_fn = Card("code", "def", ("operation", OP, code.encode_node(n.Lit(kernel.FnRef("missing"))),
                                         code.lst(), code.lst()))
    assert evaluate_code(missing_fn, (4,)).outcome == Bottom("ill_formed")
    broken_jump = Card("code", "def", ("operation", code.sig_op([], ("int", "bottom")),
                                     code.encode_node(n.Blocks((), "entry", (("entry", n.Block((), n.Jump("lost"))),))),
                                     code.lst(), code.lst()))
    assert evaluate_code(broken_jump).outcome == Bottom("ill_formed")
    closed = kernel.DictScope((*ATOMS, engine.eval_atom(ATOMS, DIGESTS, frozenset({"Lit", "Var"}))))
    assert engine.call("eval", (inner, code.lst((4,))), closed).outcome == Bottom("ill_formed")
    observation = make(n.Lit(2), kind="observation", sig=code.sig_obs(()), params=())
    assert evaluate_code(observation).outcome == Bottom("not_callable")


def test_inline_literal_and_thirty_boundary_values():
    rng = random.Random(4242)
    boundaries = [Boundary.unfold_all(), Boundary.unfold_none(), Boundary(depth=1),
                  Boundary(open_names=frozenset({"eval"})), Boundary(open_paths=frozenset({(0,)}))]

    def transparent(node):
        return replace(node, given=node.given and not node.children,
                       children=[transparent(child) for child in node.children])

    for _ in range(30):
        amount = rng.randrange(1, 5)
        body = n.Var("value")
        for _ in range(amount):
            body = n.Call(rng.choice(("add", "dec")), (body, n.Lit(1)) if rng.randrange(2)
                          and isinstance(body, n.Var) else (body,))
            if body.fn == "add" and len(body.args) == 1:
                body = n.Call("add", (body.args[0], n.Lit(1)))
            if body.fn == "dec" and len(body.args) == 2:
                body = n.Call("dec", (body.args[0],))
        program = make(body, names=("add", "dec"))
        node = n.Call("eval", (n.Lit(program), n.Lit(code.lst((rng.randrange(5),)))))
        result = engine.evaluate(node, scope=scope(), trace=True)
        assert result.trace.children[0].given
        assert unfold_equivalent(transparent(result.trace), boundaries).ok
        unfolded = engine.evaluate(engine.inline(node, scope()), scope=scope())
        assert (result.outcome, result.steps) == (unfolded.outcome, unfolded.steps)
