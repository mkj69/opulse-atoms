"""Exact reproductions for review-16 engine and identity findings."""

import hashlib

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Definition, Evidence, TemplateSpec
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.meta import code, engine
from opulse.meta.identity import Ledger, dependency_hash


def test_rec_measure_obeys_caller_fuel_without_charging_steps():
    add = kernel.Atom("add", 2, lambda left, right: left + right)
    resolve = lambda name: code.Resolved(digest="d") if name == "add" else None
    body = n.Rec("loop", ("counter",), n.Var("counter"), (n.Lit(1),),
                 n.Call("add", (n.Var("counter"), n.Lit(0))))
    program = code.make_code("operation", code.sig_op((), ("int", "bottom")), (), body, resolve)
    decoded = code.decode(program)
    direct_scope = kernel.DictScope((add,), (decoded.main,))
    reflected_scope = kernel.DictScope((add, engine.eval_atom((add,), {"add": "d"})))
    for fuel, outcome in ((0, Unknown("fuel")), (1, Ok(1))):
        limits = kernel.Limits(fuel=fuel)
        direct = kernel.call(decoded.main.name, (), direct_scope, limits, trace=True)
        reflected = engine.call("eval", (program, code.lst()), reflected_scope, limits, trace=True)
        assert (direct.outcome, direct.steps) == (outcome, 0)
        assert (reflected.outcome, reflected.steps) == (outcome, 0)
        assert reflected.trace.children[0].steps == 0


def test_rec_measure_obeys_partially_consumed_fuel_and_nested_run():
    add = kernel.Atom("add", 2, lambda left, right: left + right)
    resolve = lambda name: code.Resolved(digest={"add": "d", "run": "r"}[name]) if name in (
        "add", "run") else None
    measured = n.Let("used", n.Call("add", (n.Lit(0), n.Lit(0))),
                     n.Rec("loop", ("counter",), n.Var("counter"), (n.Lit(1),),
                           n.Call("add", (n.Call("add", (n.Var("counter"), n.Lit(0))), n.Lit(0)))))
    inner = code.make_code("operation", code.sig_op((), ("int", "bottom")), (), measured, resolve)
    decoded = code.decode(inner)
    scope = kernel.DictScope((add, engine.eval_atom((add,), {"add": "d", "run": "r"}),
                              engine.run_atom((add,), {"add": "d", "run": "r"})))
    direct_scope = kernel.DictScope((add,), (decoded.main,))
    for fuel, outcome in ((1, Unknown("fuel")), (2, Ok(1))):
        limits = kernel.Limits(fuel=fuel)
        direct = kernel.call(decoded.main.name, (), direct_scope, limits)
        reflected = engine.call("eval", (inner, code.lst()), scope, limits)
        assert (direct.outcome, direct.steps) == (outcome, 1)
        assert (reflected.outcome, reflected.steps) == (outcome, 1)

    outer = code.make_code("operation", code.sig_op((), ("result", "bottom")), (),
                           n.Call("run", (n.Lit(inner), n.Lit(code.lst()), n.Lit(2))), resolve)
    exhausted = engine.call("eval", (outer, code.lst()), scope, kernel.Limits(fuel=1))
    assert (exhausted.outcome, exhausted.steps) == (Unknown("fuel"), 1)
    nested = engine.call("eval", (outer, code.lst()), scope, kernel.Limits(fuel=2))
    assert (nested.outcome, nested.steps) == (Ok(Card("result", "ok", (1,))), 1)


def test_fnref_dependency_closure_eval_run_inline_and_unresolved():
    add = kernel.Atom("add", 2, lambda left, right: left + right)
    resolve = lambda name: code.Resolved(digest="d") if name == "add" else None
    unary = code.sig_op((("int", "bottom"),), ("int", "bottom"))
    inc = code.make_code("operation", unary, ("v",), n.Call("add", (n.Var("v"), n.Lit(1))), resolve)
    apply = code.make_code("combinator", code.sig_comb(2, (0,)), ("f", "x"),
                           n.Call("f", (n.Var("x"),)), resolve)

    def dependencies(name):
        return code.Resolved(code={"inc": inc, "apply": apply}[name]) if name in ("inc", "apply") else resolve(name)

    parent = code.make_code("operation", unary, ("x",),
                            n.Call("apply", (n.Lit(kernel.FnRef("inc")), n.Var("x"))), dependencies)
    decoded = code.decode(parent)
    assert code.is_canonical(parent)
    direct = kernel.call(decoded.main.name, (4,), kernel.DictScope((add,), (decoded.main, *decoded.deps)),
                         trace=True)
    scope = kernel.DictScope((add, engine.eval_atom((add,), {"add": "d"}),
                              engine.run_atom((add,), {"add": "d"})))
    reflected = engine.call("eval", (parent, code.lst((4,))), scope, trace=True)
    limited = engine.call("run", (parent, code.lst((4,)), 1), scope, trace=True)
    unfolded = engine.evaluate(engine.inline(n.Call("eval", (n.Lit(parent), n.Lit(code.lst((4,))))), scope),
                               scope=scope, trace=True)
    assert (direct.outcome, direct.steps) == (Ok(5), 1)
    assert (reflected.outcome, reflected.steps) == (Ok(5), 1)
    assert (limited.outcome, limited.steps) == (Ok(Card("result", "ok", (5,))), 1)
    assert (unfolded.outcome, unfolded.steps) == (Ok(5), 1)
    assert [child.name for child in reflected.trace.children[0].children] == [decoded.main.name]

    def given_steps(frame):
        if frame.given and not frame.children and frame.steps:
            return [(frame.name, frame.inputs, frame.outcome, frame.steps)]
        return [step for child in frame.children for step in given_steps(child)]

    assert given_steps(direct.trace) == given_steps(reflected.trace) == given_steps(unfolded.trace) == [
        ("add", (4, 1), Ok(5), 1)]
    assert engine.call("run", (parent, code.lst((4,)), 0), scope).outcome == Ok(
        Card("result", "out", (0,)))

    missing = code.make_code("operation", unary, ("x",), n.Lit(kernel.FnRef("missing")),
                             lambda name: code.Resolved(digest="forged") if name == "missing" else resolve(name))
    assert engine.call("eval", (missing, code.lst((4,))), scope).outcome == Bottom("ill_formed")
    non_operation = code.make_code("operation", unary, ("x",), n.Lit(kernel.FnRef("apply")), dependencies)
    assert code.is_canonical(non_operation)
    assert engine.call("eval", (non_operation, code.lst((4,))), scope).outcome == Bottom("ill_formed")

    nested = code.make_code("operation", unary, ("x",),
                            n.Call("apply", (n.Lit(kernel.FnRef("inc")), n.Var("x"))), dependencies)
    transitive = code.make_code("operation", unary, ("x",), n.Call("nested", (n.Var("x"),)),
                                lambda name: code.Resolved(code=nested) if name == "nested" else dependencies(name))
    assert code.is_canonical(transitive)
    result = engine.call("eval", (transitive, code.lst((4,))), scope)
    assert (result.outcome, result.steps) == (Ok(5), 1)


def test_dependency_commitment_excludes_origin_but_content_hash_keeps_it():
    pattern = {"name": "constant", "role": "transform", "rule": "constant",
               "inputs": [], "output": {"sort": "int"}, "definition_body": n.Lit(5)}

    def instantiate(name):
        template = code.quote(Definition(name, "template", "invented", 1, (),
                                         TemplateSpec(name, (), "operation", {**pattern, "name": name}), None),
                              lambda _: None, {})
        return code.instantiate_code(template, ())

    first = instantiate("Maker")
    second = instantiate("AnotherMaker")
    assert [dep.sort for dep in code.items(first.fields[4])] == ["code", "origin"]
    assert [dep.sort for dep in code.items(second.fields[4])] == ["code", "origin"]
    first_template = code.items(first.fields[4])[0]
    second_template = code.items(second.fields[4])[0]
    assert first_template == code.items(first.fields[4])[1].fields[0]
    assert second_template == code.items(second.fields[4])[1].fields[0]
    first_deps_hash = hashlib.sha256(code.code_hash(first_template).encode()).hexdigest()
    second_deps_hash = hashlib.sha256(code.code_hash(second_template).encode()).hexdigest()
    assert dependency_hash(first) == first_deps_hash
    assert dependency_hash(second) == second_deps_hash
    assert first_deps_hash != second_deps_hash
    assert code.code_hash(first) != code.code_hash(second)
    ledger = Ledger()
    digest = ledger.add(first, "w")
    ledger.attach_evidence(digest, "w", Evidence("bounded", {"domain": "0..2", "size": 3}, world_hash="w",
                                               deps_hash=first_deps_hash))
    assert ledger.record(digest, "w").deps_hash == first_deps_hash
    assert Ledger.from_dict(ledger.to_dict()).record(digest, "w") == ledger.record(digest, "w")


def test_template_argument_origin_changes_identity_not_dependency_commitment():
    template = code.quote(Definition(
        "Maker", "template", "invented", 1, (),
        TemplateSpec("Maker", (("unused", "int"),), "operation",
                     {"name": "constant", "role": "transform", "rule": "constant",
                      "inputs": [], "output": {"sort": "int"}, "definition_body": n.Lit(5)}),
        None), lambda _: None, {})
    first = code.instantiate_code(template, (1,))
    second = code.instantiate_code(template, (2,))
    assert code.items(first.fields[4])[0] == code.items(second.fields[4])[0] == template
    assert code.items(first.fields[4])[1] != code.items(second.fields[4])[1]
    assert dependency_hash(first) == dependency_hash(second) == hashlib.sha256(
        code.code_hash(template).encode()).hexdigest()
    assert code.code_hash(first) != code.code_hash(second)
