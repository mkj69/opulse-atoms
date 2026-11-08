"""Law checks, scoped rewrite steps, and replay invariants (atoms-v2 spec 0.4)."""

import json
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms import laws as laws_module
from opulse.atoms import library as library_module
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.laws import (
    RewriteError,
    check_law,
    derivation_length,
    make_law_callable,
    replay_rewrite,
    rewrite,
    verify_law,
)
from opulse.atoms.library import (
    Library,
    PipelineError,
    exhaustive,
    register_kind,
    sampled,
)
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    Evidence,
    LawSpec,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok, outcome_equal
from opulse.atoms.world import WorldDecl


def call(name, *args):
    return nodes.Call(name, args)


def law(name, vars, left, right):
    statement = call("eq", left, right)
    return Definition(name, "law", "invented", 1, tuple(sorted(nodes.references(statement))),
                      LawSpec(name, vars, statement), statement)


@pytest.fixture(autouse=True)
def law_obligations(monkeypatch):
    monkeypatch.setitem(library_module.REQUIRED_CHECKS, "law", frozenset({"holds"}))


def integer_library():
    operations = (
        ("add", ("int", "int"), "int", lambda left, right: left + right),
        ("mul", ("int", "int"), "int", lambda left, right: left * right),
        ("eq", ("int", "int"), "bool", lambda left, right: left == right),
    )
    specs = tuple(OperationSpec(name, "decide" if name == "eq" else "combine",
                                tuple(Edge(sort) for sort in inputs), Edge(output), name)
                  for name, inputs, output, _ in operations)
    world = WorldDecl("law-integers", 1, "atoms-v2", {}, {},
                      (ObjectSpec("int", "given"),), specs,
                      {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("law", "operation"))
    register_kind("law", check_law, verify_law)
    return Library(world, [kernel.Atom(name, len(inputs), fn)
                           for name, inputs, _, fn in operations])


def promote_law(lib, definition, domain=range(8)):
    lib.write(definition)
    lib.check(definition.name)
    make_law_callable(lib.get(definition.name), lib, ((0,) * len(definition.spec.vars),))
    count = len(definition.spec.vars)
    verified = lib.verify(definition.name, exhaustive((domain,) * count, "integer inputs 0..7"))
    assert "values" in verified.evidence.scope
    lib.promote(definition.name, Contract("integer equation"))
    return lib.get(definition.name)


def comm_law(name="add_comm"):
    return law(name, (("a", "int"), ("b", "int")),
               call("add", nodes.Var("a"), nodes.Var("b")),
               call("add", nodes.Var("b"), nodes.Var("a")))


def test_law_checker_accepts_any_and_unknown_sorts():
    original = integer_library()
    operations = tuple(replace(op, inputs=(Edge("any"), Edge("unknown")), output=Edge("unknown"))
                       if op.name == "add" else op for op in original.world.operations)
    lib = Library(replace(original.world, operations=operations), original.atoms)
    definition = law("unknown_add", (("a", "any"), ("b", "unknown")),
                     call("add", nodes.Var("a"), nodes.Var("b")),
                     call("add", nodes.Var("b"), nodes.Var("a")))
    assert check_law(definition, lib) == []
    lib.write(definition)
    lib.check(definition.name)
    make_law_callable(lib.get(definition.name), lib, ((1, 2),))
    request = exhaustive(((1, 2), (2, 1)), "one any/unknown tuple")
    assert "holds" in lib.verify(definition.name, request).evidence.checks


def test_check_law_rejects_unbound_var_bad_sort_nonboolean_and_missing_call():
    lib = integer_library()
    original = comm_law()
    assert check_law(original, lib) == []
    assert "unknown law variable or sort" in str(check_law(replace(original, spec=replace(original.spec,
                                                                                           vars=(("a", "Ghost"), ("b", "int")))), lib))
    assert "undeclared law variable" in str(check_law(law("free", (("a", "int"),), nodes.Var("x"),
                                                       nodes.Var("a")), lib))
    assert "unresolved law call" in str(check_law(law("missing", (), call("unknown"), nodes.Lit(1)), lib))
    assert "boolean sort" in str(check_law(Definition("nonbool", "law", "invented", 1, (),
                            LawSpec("nonbool", (), nodes.Lit(12)), nodes.Lit(12)), lib))


def test_verifier_catches_false_law_bottom_and_unknown():
    lib = integer_library()
    false = law("false", (("a", "int"),), nodes.Var("a"), nodes.Lit(0))
    result = verify_law(false, lib, exhaustive((range(3),), "integers 0..2"))
    assert not result.ok and "counterexample" in result.problems[0]
    lib.write(false)
    lib.check(false.name)
    make_law_callable(lib.get(false.name), lib, ((0,),))
    with pytest.raises(PipelineError, match="counterexample"):
        lib.verify(false.name, exhaustive((range(3),), "integers 0..2"))
    lib.atoms += (kernel.Atom("bad", 1, lambda value: Bottom("undefined")),)
    lib.world = replace(lib.world, operations=lib.world.operations +
                        (OperationSpec("bad", "transform", (Edge("int"),), Edge("int"), "bad"),))
    broken = law("bottom", (("a", "int"),), call("bad", nodes.Var("a")), nodes.Lit(0))
    assert not verify_law(broken, lib, exhaustive((range(2),), "integers 0..1")).ok


def test_unknown_outcome_cannot_verify(monkeypatch):
    lib = integer_library()
    monkeypatch.setattr(laws_module, "DEFAULT_VERIFY_FUEL", 0)
    result = verify_law(comm_law(), lib, exhaustive((range(2), range(2)), "integer pairs 0..1"))
    assert not result.ok
    assert "Unknown" in result.problems[0]


def test_callable_samples_and_scope_requirements(monkeypatch):
    lib = integer_library()
    definition = comm_law()
    lib.write(definition)
    lib.check(definition.name)
    with pytest.raises(ValueError, match="arity"):
        make_law_callable(lib.get(definition.name), lib, ((1,),))
    with pytest.raises(ValueError, match="samples"):
        make_law_callable(lib.get(definition.name), lib, ())
    monkeypatch.setattr(laws_module, "DEFAULT_VERIFY_FUEL", 0)
    with pytest.raises(PipelineError, match="unknown"):
        make_law_callable(lib.get(definition.name), lib, ((1, 2),))
    request = replace(exhaustive((range(2), range(2)), "0..1 pairs"),
                      scope={"domain": "0..1 pairs", "size": 3})
    assert "exact domain" in verify_law(definition, lib, request).problems[0]


def test_nested_both_directions_and_repeated_variable_matching():
    lib = integer_library()
    rule = promote_law(lib, comm_law())
    before = call("mul", nodes.Lit(3), call("add", nodes.Lit(1), nodes.Lit(2)))
    after = call("mul", nodes.Lit(3), call("add", nodes.Lit(2), nodes.Lit(1)))
    assert rewrite(before, rule, lib, at=(1,)) == after
    assert rewrite(before, "#add_comm", lib, at=(1,)) == after
    assert rewrite(after, rule, lib, "rtl", (1,)) == before
    assert derivation_length(replay_rewrite(before, after, rule, lib, {})) == 1
    repeat = law("repeat", (("a", "int"),), call("add", nodes.Var("a"), nodes.Var("a")),
                 call("mul", nodes.Lit(2), nodes.Var("a")))
    promote_law(lib, repeat)
    with pytest.raises(RewriteError, match="does not match"):
        rewrite(call("add", nodes.Lit(1), nodes.Lit(2)), lib.get("repeat"), lib)
    assert rewrite(call("add", nodes.Lit(2), nodes.Lit(2)), lib.get("repeat"), lib) == call(
        "mul", nodes.Lit(2), nodes.Lit(2))
    with pytest.raises(RewriteError, match="does not match"):
        rewrite(call("add", nodes.Lit(1), nodes.Lit(True)), lib.get("repeat"), lib)


def test_distributivity_derivation_and_scope_refusal():
    lib = integer_library()
    promote_law(lib, comm_law())
    promote_law(lib, law("mul_comm", (("a", "int"), ("b", "int")),
                         call("mul", nodes.Var("a"), nodes.Var("b")),
                         call("mul", nodes.Var("b"), nodes.Var("a"))))
    distribute = promote_law(lib, law("distrib", (("a", "int"), ("b", "int"), ("c", "int")),
                                      call("mul", nodes.Var("a"), call("add", nodes.Var("b"), nodes.Var("c"))),
                                      call("add", call("mul", nodes.Var("a"), nodes.Var("b")),
                                           call("mul", nodes.Var("a"), nodes.Var("c")))))
    before = call("mul", nodes.Lit(3), call("add", nodes.Lit(1), nodes.Lit(2)))
    after = rewrite(before, distribute, lib)
    assert after == call("add", call("mul", nodes.Lit(3), nodes.Lit(1)),
                         call("mul", nodes.Lit(3), nodes.Lit(2)))
    derivation = replay_rewrite(before, after, distribute, lib, {})
    assert derivation.charged_steps == kernel.evaluate(after, scope=lib.scope()).steps
    assert derivation.rewrite_steps == 0
    assert derivation.steps[0].path == ()
    outside = call("mul", nodes.Lit(9), call("add", nodes.Lit(1), nodes.Lit(2)))
    with pytest.raises(RewriteError, match="scope"):
        replay_rewrite(outside, rewrite(outside, distribute, lib), distribute, lib, {})
    assert lib.get("distrib").evidence.scope["size"] == 8 ** 3
    assert lib.get("distrib").contract.guarantees == "integer equation"
    restored = Library.from_dict(json.loads(json.dumps(lib.to_dict())), lib.world, lib.atoms)
    assert replay_rewrite(before, after, restored.get("distrib"), restored, {}).charged_steps == derivation.charged_steps
    assert restored.get("distrib").contract == distribute.contract


def test_large_domain_requires_scope_predicate():
    lib = integer_library()
    tautology = law("tautology", (("a", "int"),), nodes.Var("a"), nodes.Var("a"))
    request = exhaustive((range(10_001),), "integers 0..10000")
    assert "predicate" in verify_law(tautology, lib, request).problems[0]
    request.scope["predicate"] = call("eq", nodes.Var("a"), nodes.Var("a"))
    result = verify_law(tautology, lib, request)
    assert result.ok and "values" not in request.scope
    assert isinstance(request.scope["predicate"], dict)
    assert len(request.scope["value_hashes"]) == 10_001
    checked = replace(tautology, evidence=Evidence("exhaustive", request.scope, checks=result.checks))
    assert laws_module._in_scope(checked, {"a": nodes.Lit(10_000)}, lib, {}, lib.scope())
    assert not laws_module._in_scope(checked, {"a": nodes.Lit(10_001)}, lib, {}, lib.scope())
    request.scope["predicate"] = call("eq", nodes.Var("missing"), nodes.Lit(1))
    assert "undeclared" in verify_law(tautology, lib, request).problems[0]


def test_card_scope_values_roundtrip_and_do_not_alias_request():
    lib = integer_library()
    eq = replace(lib.world.operations[-1], inputs=(Edge("any"), Edge("any")))
    lib.world = replace(lib.world, objects=lib.world.objects + (ObjectSpec("token", "given"),),
                        operations=lib.world.operations[:-1] + (eq,))
    defn = law("token_eq", (("a", "token"),), nodes.Var("a"), nodes.Var("a"))
    request = exhaustive(((Card("token", "one"),),), "one token")
    result = verify_law(defn, lib, request)
    assert result.ok
    scope = json.loads(json.dumps(request.scope))
    assert scope["values"][0][0].startswith("{")
    assert laws_module._read_scope_value(scope["values"][0][0]) == Card("token", "one")


def test_unpromoted_and_tampered_law_cannot_replay():
    lib = integer_library()
    legitimate = promote_law(lib, comm_law())
    before = call("add", nodes.Lit(1), nodes.Lit(2))
    after = rewrite(before, legitimate, lib)
    with pytest.raises(RewriteError, match="promoted"):
        rewrite(before, replace(legitimate, status="verified"), lib)
    with pytest.raises(RewriteError, match="stale"):
        replay_rewrite(before, after, replace(legitimate, spec=replace(legitimate.spec,
                         statement=call("eq", nodes.Lit(0), nodes.Lit(1)))), lib, {})
    with pytest.raises(RewriteError, match="law step"):
        replay_rewrite(before, call("mul", nodes.Lit(1), nodes.Lit(2)), legitimate, lib, {})
    false_axiom = replace(law("false_axiom", (("a", "int"),), nodes.Var("a"), nodes.Lit(0)),
                          origin="given", layer=0, status="promoted")
    with pytest.raises(RewriteError, match="disagrees"):
        replay_rewrite(nodes.Lit(1), nodes.Lit(0), false_axiom, lib, {})
    true_axiom = replace(comm_law("true_axiom"), origin="given", layer=0, status="promoted")
    assert replay_rewrite(before, after, true_axiom, lib, {}).rewrite_steps == 0
    lib.atoms += (kernel.Atom("new_atom", 0, lambda: 0),)
    with pytest.raises(RewriteError, match="stale"):
        replay_rewrite(before, after, legitimate, lib, {})


def test_sampled_law_never_promotes():
    lib = integer_library()
    definition = comm_law()
    lib.write(definition)
    lib.check(definition.name)
    make_law_callable(lib.get(definition.name), lib, ((1, 2),))
    lib.verify(definition.name, sampled(lambda randomizer: (randomizer.randrange(8),
                      randomizer.randrange(8)), 12, 41, "sampled pairs"))
    with pytest.raises(PipelineError, match="sampled"):
        lib.promote(definition.name, Contract("commutative"))


@settings(max_examples=40, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=7), min_size=3, max_size=3),
       st.booleans(), st.booleans(), st.booleans())
def test_property_rewrites_preserve_outcome_and_boundary(values, reverse, nested_first, nested_second):
    lib = integer_library()
    rule = promote_law(lib, comm_law())
    first, second, multiplier = values
    first_term = call("add", nodes.Lit(0), nodes.Lit(first)) if nested_first else nodes.Lit(first)
    second_term = call("mul", nodes.Lit(1), nodes.Lit(second)) if nested_second else nodes.Lit(second)
    expr = call("mul", nodes.Lit(multiplier), call("add", first_term, second_term))
    direction = "rtl" if reverse else "ltr"
    rewritten = rewrite(expr, rule, lib, direction, (1,))
    derivation = replay_rewrite(expr, rewritten, rule, lib, {})
    original_run = kernel.evaluate(expr, scope=lib.scope(), trace=True)
    rewritten_run = kernel.evaluate(rewritten, scope=lib.scope(), trace=True)
    assert outcome_equal(original_run.outcome, rewritten_run.outcome)
    assert derivation.charged_steps == rewritten_run.steps
    assert original_run.steps == rewritten_run.steps
    assert original_run.outcome == Ok(multiplier * (first + second))
    for run in (original_run, rewritten_run):
        for boundary in (Boundary.unfold_all(), Boundary.unfold_none()):
            visible = flatten_calls(run.trace, boundary)
            assert sum(step.steps for step in visible) == run.steps
        assert run.outcome == Ok(multiplier * (first + second))
