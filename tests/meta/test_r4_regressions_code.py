"""Core template provenance and memoized recursion regressions (meta 2.1-2.2)."""

from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Definition, Edge, OperationSpec, TemplateSpec
from opulse.atoms.templates import _encode_nodes, instantiate
from opulse.atoms.values import Bottom, Card, Ok
from opulse.meta import code, engine


def test_template_core_refs_are_canonical_and_runtime_valid():
    spec = TemplateSpec("Step", (("step", "int"),), "operation", _encode_nodes({
        "name": "made", "role": "transform", "rule": "step",
        "inputs": [{"sort": "int"}], "output": {"sort": "int"},
        "definition_body": n.Call("add", (n.Var("arg0"), n.Lit("$step"))),
    }))
    source = Definition("Step", "template", "invented", 1, (), spec, None)
    original = instantiate(source, {"step": 2}, "made")
    quoted = code.quote(original, lambda name: source if name == "Step" else None, {"add": "digest-add"})
    direct = code.instantiate_code(code.quote(source, lambda _: None, {}), (2,),
                                   lambda name: code.Resolved(digest="digest-add") if name == "add" else None)
    assert quoted == direct == code.canonicalize(direct)
    decoded = code.decode(quoted)
    assert tuple(dep.kind for dep in decoded.deps) == ("template",)
    assert decoded.main.body == n.Let("v0", n.Lit(kernel.FnRef(decoded.deps[0].name)),
                                      n.Call("add", (n.Var("x0"), n.Lit(2))))
    atoms = (kernel.Atom("add", 2, lambda left, right: left + right),)
    original_run = kernel.call("made", (3,), kernel.DictScope(atoms, (
        kernel.Defn("made", ("arg0",), original.body),)))
    meta_run = engine.call("eval", (quoted, code.lst((3,))), kernel.DictScope((
        *atoms, engine.eval_atom(atoms, {"add": "digest-add"}))))
    assert (original_run.outcome, original_run.steps) == (Ok(5), 1)
    assert (meta_run.outcome, meta_run.steps) == (Ok(5), 1)


def test_memo_recursion_round_trip_identity_and_inline():
    body = n.Rec("fib", ("value",), n.Case(((n.Test(n.Call("zero", (n.Var("value"),))),
                                              n.Lit(1)),), n.Call("add", (
        n.Call("fib", (n.Call("dec", (n.Var("value"),)),)),
        n.Call("fib", (n.Call("dec", (n.Var("value"),)),))))), (n.Var("arg0"),), "fuel", True)
    spec = OperationSpec("fib", "transform", (Edge("int"),), Edge("int"), "fib")
    def quote_body(expr):
        return code.quote(Definition("fib", "operation", "invented", 1, (), spec, expr),
                          lambda _: None, {name: "digest-" + name for name in ("zero", "add", "dec")})

    memo = quote_body(body)
    plain = quote_body(replace(body, memo=False))
    assert memo != plain and code.code_hash(memo) != code.code_hash(plain)
    assert len(code.encode_node(body).fields) == 6
    assert len(code.encode_node(replace(body, memo=False)).fields) == 5
    assert code.decode_node(code.encode_node(body)) == body
    assert code.decode_node(code.encode_node(replace(body, memo=False))) == replace(body, memo=False)
    assert code.canonicalize(memo) == memo and code.canonicalize(plain) == plain
    assert code.decode(memo).main.body.memo is True
    assert code.decode(plain).main.body.memo is False
    bad = Card("expr", "rec", (*memo.fields[2].fields[:5], False))
    with pytest.raises(code.CodeError, match="memo"):
        code.decode_node(bad)

    atoms = (kernel.Atom("zero", 1, lambda value: value == 0),
             kernel.Atom("add", 2, lambda left, right: left + right),
             kernel.Atom("dec", 1, lambda value: value - 1))
    digests = {atom.name: "digest-" + atom.name for atom in atoms}
    scope = kernel.DictScope((*atoms, engine.eval_atom(atoms, digests)))
    literal = n.Call("eval", (n.Lit(memo), n.Lit(code.lst((2,)))))
    direct = engine.evaluate(literal, scope=scope)
    plain_run = engine.evaluate(n.Call("eval", (n.Lit(plain), n.Lit(code.lst((2,))))), scope=scope)
    unfolded = engine.evaluate(engine.inline(literal, scope), scope=scope)
    baseline = engine.evaluate(n.Call("fib", (n.Lit(2),)),
                               scope=kernel.DictScope(atoms, (kernel.Defn("fib", ("arg0",), body),)))
    assert (direct.outcome, direct.steps) == (unfolded.outcome, unfolded.steps) == (
        baseline.outcome, baseline.steps) == (plain_run.outcome, plain_run.steps) == (Ok(4), 16)
    assert any(isinstance(node, n.Rec) and node.memo for node in n.walk(engine.inline(literal, scope)))


def test_code_world_mk_builds_memoized_rec_card():
    from opulse.atoms.nodes import Lit, Rec
    from opulse.meta.worlds.code.hosts import mk

    card = code.encode_node(Rec("loop", (), Lit(1), (), "fuel", True))
    assert mk("expr", "rec", code.lst(card.fields)) == card
    assert mk("expr", "rec", code.lst(card.fields[:5])) == code.encode_node(Rec("loop", (), Lit(1), (), "fuel"))
    assert isinstance(mk("expr", "rec", code.lst(card.fields[:5] + (1,))), Bottom)
