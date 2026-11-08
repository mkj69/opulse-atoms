"""Exact code-argument execution laws (atoms-meta 2.5-2.7)."""

from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library
from opulse.atoms.spec import CombinatorSpec, Definition, Edge, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl
from opulse.meta import code, engine


def setup():
    add = kernel.Atom("add", 2, lambda left, right: left + right)
    atom_spec = OperationSpec("add", "combine", (Edge("int"), Edge("int")), Edge("int"), "addition")
    world = WorldDecl("code_arguments", 1, "atoms-v2", {}, {}, (), (atom_spec,),
                      {"recursion": "fuel", "nodes": list(n.NODE_NAMES)}, {}, {})
    library = Library(world, (add,))

    def operation(name, body, dependencies=()):
        spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"), "kernel body",
                             extra={"input_names": ["value"]})
        return Definition(name, "operation", "invented", 1, dependencies, spec, body, status="callable")

    inc = operation("inc", n.Call("add", (n.Var("value"), n.Lit(1))), ("add",))
    double = operation("double", n.Call("add", (n.Var("value"), n.Var("value"))), ("add",))
    nested = operation("nested", n.Call("inc", (n.Var("value"),)), ("inc",))
    twice_body = n.Call("f", (n.Call("f", (n.Var("value"),)),))
    twice = Definition("apply_twice", "combinator", "invented", 1, (),
                       CombinatorSpec("apply_twice", ("f", "value"), ("f",), twice_body),
                       twice_body, status="callable")
    mixed_body = n.Call("g", (n.Call("f", (n.Var("value"),)), n.Lit(1)))
    mixed = Definition("mixed", "combinator", "invented", 1, (),
                       CombinatorSpec("mixed", ("f", "g", "value"), ("f", "g"), mixed_body),
                       mixed_body, status="callable")
    library._definitions.update({definition.name: definition for definition in
                                 (inc, double, nested, twice, mixed)})
    digests = {"add": code.atom_digest(atom_spec)}
    scope = kernel.DictScope((add, engine.eval_atom((add,), digests), engine.run_atom((add,), digests)))
    return library, scope, digests


def test_quote_eval_matches_library_for_invented_arguments_and_nested_deps():
    library, scope, _ = setup()
    comb = code.quote_from_library(library, "apply_twice")
    for name, expected, steps in (("inc", 6, 2), ("double", 16, 2), ("nested", 6, 2)):
        args = code.quote_args(library, (kernel.FnRef(name), 4))
        result = engine.call("eval", (comb, args), scope, trace=True)
        ordinary = library.run("apply_twice", (kernel.FnRef(name), 4), trace=True)
        assert (result.outcome, result.steps) == (ordinary.outcome, ordinary.steps) == (Ok(expected), steps)
        assert result.trace.children[0].steps == steps
        assert args.fields[0].sort == "code"
        if name == "nested":
            assert len(code.items(args.fields[0].fields[4])) == 1
            eval_frame = result.trace.children[0]
            twice_frame = eval_frame.children[0]
            argument_name = "#" + code.code_hash(args.fields[0])
            dependency_name = "#" + code.code_hash(code.items(args.fields[0].fields[4])[0])
            assert (eval_frame.name, twice_frame.name, twice_frame.steps) == (
                "eval", "#" + code.code_hash(comb), 2)
            assert [(child.name, child.steps) for child in twice_frame.children] == [
                (argument_name, 1), (argument_name, 1)]
            assert [(child.name, child.steps) for child in twice_frame.children[0].children] == [
                (dependency_name, 1)]


def test_argument_preflight_rejects_foreign_noncanonical_and_invented_fn():
    library, scope, _ = setup()
    comb = code.quote_from_library(library, "apply_twice")
    argument = code.quote_from_library(library, "inc")
    atom = code.items(argument.fields[3])[0]
    foreign = replace(atom, fields=("add", "changed"))
    wrong_digest = replace(argument, fields=(*argument.fields[:3], code.lst((foreign,)), argument.fields[4]))
    bad_sig = replace(argument, fields=(argument.fields[0], code.sig_op([], ("int", "bottom")),
                                        *argument.fields[2:]))
    noncanonical = replace(argument, fields=(*argument.fields[:2],
                                             code.encode_node(n.Let("named", n.Var("x0"),
                                                                    n.Call("add", (n.Var("named"), n.Lit(1))))),
                                             *argument.fields[3:]))
    assert not code.is_canonical(noncanonical)
    for value, reason in ((wrong_digest, "foreign_code"), (bad_sig, "ill_formed"),
                          (noncanonical, "ill_formed"),
                          (code.lst((code._expr("fn", "inc"), 4)), "ill_formed")):
        args = value if isinstance(value, Card) and value.sort == "list" else code.lst((value, 4))
        result = engine.call("eval", (comb, args), scope, trace=True)
        assert (result.outcome, result.steps) == (Bottom(reason), 0)
    nested = code.quote_from_library(library, "nested")
    dependency = code.items(nested.fields[4])[0]
    foreign_dependency = replace(dependency, fields=(*dependency.fields[:3],
                                                     code.lst((foreign,)), dependency.fields[4]))
    nested = replace(nested, fields=(*nested.fields[:4], code.lst((foreign_dependency,))))
    assert engine.call("eval", (comb, code.lst((nested, 4))), scope).outcome == Bottom("ill_formed")
    assert engine.call("eval", (comb, code.lst((comb, 4))), scope).outcome == Bottom("ill_formed")
    assert engine.call("eval", (comb, code.lst((code._expr("fn", "missing"), 4))), scope).outcome == Bottom(
        "ill_formed")


def test_mixed_given_and_code_arguments_run_budget_and_inline():
    library, scope, _ = setup()
    mixed = code.quote_from_library(library, "mixed")
    args = code.quote_args(library, (kernel.FnRef("inc"), kernel.FnRef("add"), 4))
    result = engine.call("eval", (mixed, args), scope)
    ordinary = library.run("mixed", (kernel.FnRef("inc"), kernel.FnRef("add"), 4))
    assert (result.outcome, result.steps) == (ordinary.outcome, ordinary.steps) == (Ok(6), 2)
    twice = code.quote_from_library(library, "apply_twice")
    for budget, outcome, steps in ((1, Card("result", "out", (1,)), 1),
                                    (2, Card("result", "ok", (6,)), 2)):
        run = engine.call("run", (twice, code.quote_args(library, (kernel.FnRef("inc"), 4)), budget), scope)
        assert (run.outcome, run.steps) == (Ok(outcome), steps)
    for program, arguments, expected in ((twice, code.quote_args(library, (kernel.FnRef("nested"), 4)), Ok(6)),
                                         (mixed, args, Ok(6))):
        literal = n.Call("eval", (n.Lit(program), n.Lit(arguments)))
        original = engine.evaluate(literal, scope=scope)
        unfolded = engine.evaluate(engine.inline(literal, scope), scope=scope)
        assert (original.outcome, original.steps) == (unfolded.outcome, unfolded.steps) == (expected, 2)


def test_operation_code_that_calls_its_parameter_takes_a_code_argument():
    from opulse.atoms import nodes as n
    from opulse.atoms.values import Bottom
    from opulse.meta import code as C
    from opulse.meta import engine
    from opulse.meta import gen_code as G

    def resolve(name):
        return C.Resolved(digest=G.DIGESTS[name]) if name in G.DIGESTS else None

    inc = C.make_code("operation", G.SIG, ("x",), n.Call("add", (n.Var("x"), n.Lit(1))), resolve)
    sig = C.sig_op((("int", "bottom"), ("int", "bottom")), ("int", "bottom"))
    apply_twice = C.make_code("operation", sig, ("f", "x"),
                              n.Call("f", (n.Call("f", (n.Var("x"),)),)), resolve)
    run = engine.call("eval", (apply_twice, C.lst((inc, 5))), G.scope())
    assert run.outcome.value == 7 and run.steps == 2
    assert engine.call("eval", (apply_twice, C.lst((3, 5))), G.scope()).outcome == Bottom("ill_formed")
