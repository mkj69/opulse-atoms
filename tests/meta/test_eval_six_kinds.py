"""Exact evaluation and preflight for law, bridge, and template code (meta 2.5-2.6)."""

from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import Library
from opulse.atoms.spec import (
    BridgeSpec,
    Definition,
    Edge,
    LawSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl
from opulse.meta import code, engine


def setup():
    atom_specs = (
        OperationSpec("eq", "decide", (Edge("int"), Edge("int")), Edge("bool"), "equal"),
        OperationSpec("positive", "decide", (Edge("int"),), Edge("bool"), "positive"),
        OperationSpec("add", "combine", (Edge("int"), Edge("int")), Edge("int"), "addition"),
        OperationSpec("fail", "decide", (), Edge("bool"), "failure"),
    )
    atoms = (kernel.Atom("eq", 2, lambda left, right: left == right),
             kernel.Atom("positive", 1, lambda value: value > 0),
             kernel.Atom("add", 2, lambda left, right: left + right),
             kernel.Atom("fail", 0, lambda: Bottom("broken")))
    world = WorldDecl("six_kinds", 1, "atoms-v2", {}, {}, (), atom_specs,
                      {"recursion": "fuel", "nodes": list(n.NODE_NAMES)}, {}, {})
    library = Library(world, atoms)
    law_body = n.Call("eq", (n.Var("left"), n.Var("right")))
    bridge = BridgeSpec("increment", "int", "int", n.Call("add", (n.Var("x"), n.Lit(1))),
                        n.Call("positive", (n.Var("x"),)))
    definitions = (
        Definition("same", "law", "invented", 1, (),
                   LawSpec("same", (("left", "int"), ("right", "int")), law_body),
                   law_body, status="callable"),
        Definition("increment", "bridge", "invented", 1, (), bridge,
                   bridge_defn(bridge).body, status="callable"),
    )
    library._definitions.update((definition.name, definition) for definition in definitions)
    digests = {spec.name: code.atom_digest(spec) for spec in atom_specs}
    scope = kernel.DictScope((*atoms, engine.eval_atom(atoms, digests), engine.run_atom(atoms, digests)))
    return library, scope, digests


def test_quote_eval_law_and_bridge_exact_steps_traces_and_inline():
    library, scope, _ = setup()
    for name, cases in (("same", (((2, 2), Ok(True), 1), ((2, 3), Ok(False), 1))),
                        ("increment", (((2,), Ok(3), 2), ((0,), Bottom("outside_domain"), 1)))):
        program = code.quote_from_library(library, name)
        for args, outcome, steps in cases:
            literal = n.Call("eval", (n.Lit(program), n.Lit(code.lst(args))))
            result = engine.evaluate(literal, scope=scope, trace=True)
            ordinary = (kernel.evaluate(library.get(name).spec.statement,
                                        dict(zip((key for key, _ in library.get(name).spec.vars), args)),
                                        library.scope(), trace=True) if name == "same" else
                        library.run(name, args, trace=True))
            unfolded = engine.evaluate(engine.inline(literal, scope), scope=scope, trace=True)
            assert (result.outcome, result.steps) == (ordinary.outcome, ordinary.steps) == (outcome, steps)
            assert (unfolded.outcome, unfolded.steps) == (outcome, steps)
            frame = result.trace.children[0]
            assert (frame.name, frame.kind, frame.given, frame.steps) == ("eval", "operation", True, steps)
            assert [(child.name, child.kind, child.steps) for child in frame.children] == [
                ("#" + code.code_hash(program), "law" if name == "same" else "bridge", steps)]


def test_law_sort_arity_and_bridge_domain_preflight():
    library, scope, digests = setup()
    law = code.quote_from_library(library, "same")
    bridge = code.quote_from_library(library, "increment")
    for program, args, reason in ((law, (1,), "arity"), (law, (1, "one"), "ill_formed"),
                                  (bridge, (), "arity")):
        literal = n.Call("eval", (n.Lit(program), n.Lit(code.lst(args))))
        result = engine.evaluate(literal, scope=scope)
        assert (result.outcome, result.steps) == (Bottom(reason), 0)
        assert engine.inline(literal, scope) == literal
    for program in (law, bridge):
        metadata = code.items(program.fields[3])
        foreign = replace(program, fields=(*program.fields[:3], code.lst((replace(
            metadata[0], fields=(metadata[0].fields[0], "foreign")), *metadata[1:])), program.fields[4]))
        assert engine.call("eval", (foreign, code.lst((1,) * code.sig_arity(program.fields[1]))),
                           scope).outcome == Bottom("foreign_code")
    failure = code.make_code("law", code.sig_law(()), (), n.Call("fail"),
        lambda name: code.Resolved(digest=digests[name]) if name in digests else None)
    literal = n.Call("eval", (n.Lit(failure), n.Lit(code.lst(()))))
    direct = engine.evaluate(literal, scope=scope)
    unfolded = engine.evaluate(engine.inline(literal, scope), scope=scope)
    assert (direct.outcome, direct.steps) == (unfolded.outcome, unfolded.steps) == (Bottom("broken"), 1)


def test_run_budget_and_template_provenance_dependency():
    library, scope, digests = setup()
    for name, args, budget, outcome, steps in (
            ("same", (1, 2), 0, Card("result", "out", (0,)), 0),
            ("same", (1, 2), 1, Card("result", "ok", (False,)), 1),
            ("increment", (2,), 1, Card("result", "out", (1,)), 1),
            ("increment", (0,), 1, Card("result", "err", ("outside_domain",)), 1)):
        result = engine.call("run", (code.quote_from_library(library, name), code.lst(args), budget), scope)
        assert (result.outcome, result.steps) == (Ok(outcome), steps)

    pattern = {"name": "incremented", "role": "transform", "rule": "add",
               "inputs": [{"sort": "int", "enter": "bottom"}], "output": {"sort": "int", "enter": "bottom"},
               "definition_body": n.Call("add", (n.Var("arg0"), n.Lit("$amount"))),
               "input_names": ["arg0"]}
    template = code.quote(Definition("factory", "template", "invented", 1, (),
                                     TemplateSpec("factory", (("amount", "int"),), "operation", pattern), None),
                          lambda _: None, {})
    assert (engine.call("eval", (template, code.lst(())), scope).outcome,
            engine.call("run", (template, code.lst(()), 5), scope).outcome) == (
                Bottom("not_callable"), Bottom("not_callable"))
    produced = code.instantiate_code(template, (1,), lambda name: code.Resolved(digest=digests[name])
                                     if name in digests else None)
    assert code.items(produced.fields[4])[-1].sort == "origin"
    assert (engine.call("eval", (produced, code.lst((4,))), scope).outcome,
            engine.call("run", (produced, code.lst((4,)), 1), scope).outcome) == (
                Ok(5), Ok(Card("result", "ok", (5,))))
    parent = code.make_code("operation", code.sig_op((("int", "bottom"),), ("int", "bottom")),
                            ("value",), n.Call("incremented", (n.Var("value"),)),
                            lambda name: code.Resolved(code=produced) if name == "incremented" else
                            code.Resolved(digest=digests[name]) if name in digests else None)
    literal = n.Call("eval", (n.Lit(parent), n.Lit(code.lst((4,)))))
    direct = engine.evaluate(literal, scope=scope)
    unfolded = engine.evaluate(engine.inline(literal, scope), scope=scope)
    assert (direct.outcome, direct.steps) == (unfolded.outcome, unfolded.steps) == (Ok(5), 1)
