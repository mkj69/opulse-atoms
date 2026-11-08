"""Bounded properties for the 0.4 kinds and modes (spec sections 11, 18, 19)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.bridges import bridge_defn, check_bridge, verify_bridge
from opulse.atoms.combinators import (
    combinator_defn,
    counter_atoms,
    fix_atoms,
    fix_spec,
    list_atoms,
    memoized_spec,
    turns_atoms,
    turns_spec,
)
from opulse.atoms.laws import (
    RewriteError,
    check_law,
    replay_rewrite,
    rewrite,
    verify_law,
)
from opulse.atoms.library import (
    Library,
    PipelineError,
    VerifyRequest,
    exhaustive,
    register_kind,
)
from opulse.atoms.objects import object_atoms
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.templates import (
    check_template,
    cite_template_evidence,
    instantiate,
    verify_template,
)
from opulse.atoms.values import Bottom, Card, Ok, outcome_equal
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl

PROPERTY = settings(max_examples=12, derandomize=True, deadline=None)


def call(name, *args):
    return n.Call(name, args)


def library(atoms, *, name="property-six"):
    operations = tuple(OperationSpec(atom.name, "combine", tuple(Edge("int") for _ in range(atom.arity)),
                                     Edge("bool" if atom.name in ("eq", "ge") else "int"), atom.name)
                       for atom in atoms)
    world = WorldDecl(name, 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),), operations,
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {},
                      open_kinds=("object", "operation", "combinator", "observation",
                                  "law", "bridge"))
    return Library(world, atoms)


def integer_library():
    return library((kernel.Atom("add", 2, lambda left, right: left + right),
                    kernel.Atom("mul", 2, lambda left, right: left * right),
                    kernel.Atom("eq", 2, lambda left, right: left == right)))


def law_definition(name, lhs, rhs):
    statement = call("eq", lhs, rhs)
    variables = tuple((name, "int") for name in ("a", "b", "c")
                      if any(isinstance(node, n.Var) and node.name == name
                             for node in n.walk(statement)))
    return Definition(name, "law", "invented", 1, tuple(sorted(n.references(statement))),
                      LawSpec(name, variables, statement), statement)


@given(operation=st.sampled_from(("add", "mul")), associative=st.booleans(),
       bound=st.integers(min_value=1, max_value=2),
       values=st.tuples(st.integers(0, 4), st.integers(0, 4), st.integers(0, 4)),
       tampered=st.sampled_from(("world_hash", "atoms_hash", "deps_hash", "content_hash")))
@PROPERTY
def test_laws_hold_rewrite_and_refuse_outside_scope(operation, associative, bound, values, tampered):
    lib = integer_library()
    register_kind("law", check_law, verify_law)
    first, second, third = (n.Var(name) for name in ("a", "b", "c"))
    lhs = (call(operation, call(operation, first, second), third) if associative
           else call(operation, first, second))
    rhs = (call(operation, first, call(operation, second, third)) if associative
           else call(operation, second, first))
    definition = law_definition("equation", lhs, rhs)
    lib.write(definition)
    lib.check("equation")
    lib.make_callable("equation", ((0,) * len(definition.spec.vars),))
    verified = lib.verify("equation", exhaustive((range(bound + 1),) *
                                                    len(definition.spec.vars), "finite cube"))
    assert {"holds", "equation"} <= set(verified.evidence.checks)
    assert verified.evidence.content_hash == lib.content_hash("equation")
    assert verified.evidence.world_hash == lib.world.world_hash()
    assert verified.evidence.deps_hash == lib._deps_hash("equation")
    lib.promote("equation", Contract("commutative or associative identity"))
    assert lib.get("equation").contract is not None
    inside = tuple(value % (bound + 1) for value in values)
    expression = call("mul", n.Lit(2), call(operation,
        call(operation, n.Lit(inside[0]), n.Lit(inside[1])), n.Lit(inside[2])) if associative
        else call(operation, n.Lit(inside[0]), n.Lit(inside[1])))
    changed = rewrite(expression, lib.get("equation"), lib, at=(1,))
    derivation = replay_rewrite(expression, changed, lib.get("equation"), lib, {})
    final = kernel.evaluate(changed, scope=lib.scope())
    assert outcome_equal(final.outcome, kernel.evaluate(expression, scope=lib.scope()).outcome)
    assert derivation.charged_steps == final.steps
    outside = call("mul", n.Lit(2), call(operation,
        call(operation, n.Lit(bound + 1), n.Lit(0)), n.Lit(0)) if associative
        else call(operation, n.Lit(bound + 1), n.Lit(0)))
    with pytest.raises(RewriteError, match="verified scope"):
        replay_rewrite(outside, rewrite(outside, lib.get("equation"), lib, at=(1,)),
                       lib.get("equation"), lib, {})
    promoted = lib.get("equation")
    lib._definitions["equation"] = replace(
        promoted, evidence=replace(promoted.evidence, **{tampered: "stale-hash"}))
    with pytest.raises(RewriteError, match="stale"):
        replay_rewrite(expression, changed, lib.get("equation"), lib, {})


@given(operation=st.sampled_from(("add", "mul")), offset=st.integers(1, 4),
       bound=st.integers(1, 4))
@PROPERTY
def test_false_laws_have_counterexamples_and_cannot_promote(operation, offset, bound):
    lib = integer_library()
    register_kind("law", check_law, verify_law)
    definition = law_definition("false_identity", call(operation, n.Var("a"), n.Var("b")),
                                call(operation, n.Var("a"), call("add", n.Var("b"), n.Lit(offset))))
    domain = exhaustive((range(bound + 1),) * len(definition.spec.vars), "finite cube")
    assert "counterexample" in verify_law(definition, lib, domain).problems[0]
    lib.write(definition)
    lib.check(definition.name)
    lib.make_callable(definition.name, ((0,) * len(definition.spec.vars),))
    with pytest.raises(PipelineError, match="counterexample"):
        lib.verify(definition.name, exhaustive((range(bound + 1),) *
                                               len(definition.spec.vars), "finite cube"))
    with pytest.raises(PipelineError):
        lib.promote(definition.name, Contract("false identity"))


@pytest.mark.parametrize("field", ("world_hash", "atoms_hash", "deps_hash", "content_hash"))
def test_law_promotion_rejects_mismatched_evidence_hashes(field):
    lib = integer_library()
    register_kind("law", check_law, verify_law)
    definition = law_definition("identity", call("add", n.Var("a"), n.Lit(0)), n.Var("a"))
    lib.write(definition)
    lib.check("identity")
    lib.make_callable("identity", ((0,),))
    lib.verify("identity", exhaustive((range(3),), "three integers"))
    verified = lib.get("identity")
    lib._definitions["identity"] = replace(
        verified, evidence=replace(verified.evidence, **{field: "mismatched"}))
    with pytest.raises(PipelineError, match="hash changed"):
        lib.promote("identity", Contract("additive identity"))


@given(scale=st.integers(1, 4), shift=st.integers(-4, 4),
       defect=st.integers(0, 3), value=st.integers(-5, 5),
       threshold=st.integers(-4, 4))
@PROPERTY
def test_affine_bridge_commutes_detects_defects_and_unfolds(scale, shift, defect, value, threshold):
    defect = max(threshold, defect)
    atoms = (kernel.Atom("source_next", 1, lambda item: item + 1),
             kernel.Atom("target_next", 1, lambda item: item + scale),
             kernel.Atom("affine", 1, lambda item: scale * item + shift),
             kernel.Atom("ge", 2, lambda left, right: left >= right),
             kernel.Atom("bad_affine", 1, lambda item: scale * item + shift + (item == defect)))
    lib = library(atoms)
    register_kind("bridge", check_bridge, verify_bridge)
    domain = call("ge", n.Var("x"), n.Lit(threshold))
    spec = BridgeSpec("convert", "int", "int", call("affine", n.Var("x")), domain,
                      (("source_next", "target_next"),))
    definition = Definition("convert", "bridge", "invented", 1, ("affine", "ge"), spec,
                            bridge_defn(spec).body)
    scope = lib.scope().extend((bridge_defn(spec),))
    expression = call("convert", n.Lit(value))
    direct = kernel.evaluate(expression, scope=scope, trace=True)
    inline = kernel.evaluate(kernel.inline(expression, scope), scope=scope)
    assert (direct.outcome, direct.steps) == (inline.outcome, inline.steps)
    assert direct.outcome == (Ok(scale * value + shift) if value >= threshold
                              else Bottom("outside_domain"))
    assert kernel.call("convert", (threshold - 1,), scope).outcome == Bottom("outside_domain")
    boundaries = [Boundary.unfold_all(), Boundary.unfold_none(),
                  Boundary(kinds=frozenset({"bridge"}), depth=0),
                  Boundary(open_names=frozenset({"convert"}))]
    assert unfold_equivalent_calls(direct.trace, boundaries).ok
    request = VerifyRequest("bounded", tuple((item,) for item in range(threshold, threshold + 4)),
                            {"domain": "four consecutive inputs", "size": 4})
    assert verify_bridge(definition, lib, request).ok
    broken = replace(spec, map=call("bad_affine", n.Var("x")))
    invalid = replace(definition, spec=broken, body=bridge_defn(broken).body,
                      depends_on=("bad_affine", "ge"))
    bad_request = VerifyRequest("bounded", tuple((item,) for item in range(defect, defect + 3)),
                                {"domain": "perturbation and successor", "size": 3})
    assert not verify_bridge(invalid, lib, bad_request).ok


def template_library():
    return library((kernel.Atom("add", 2, lambda left, right: left + right),))


def shift_template():
    pattern = {"role": "transform", "inputs": [{"sort": "int"}], "output": {"sort": "int"},
               "rule": "shift $amount", "input_names": ["arg0"],
               "definition_body": n.to_json(call("add", n.Var("arg0"), n.Lit("$amount")))}
    return Definition("Shift", "template", "invented", 1, (),
                      TemplateSpec("Shift", (("amount", "int"),), "operation", pattern), n.Lit(0))


@given(amount=st.integers(-6, 6), other=st.integers(-6, 6),
       input_value=st.integers(-6, 6), choice=st.integers(0, 3))
@PROPERTY
def test_template_identity_boundaries_and_family_evidence(amount, other, input_value, choice):
    lib = template_library()
    register_kind("template", check_template, verify_template)
    base = shift_template()
    lib._definitions[base.name] = base
    lib.check("Shift")
    lib.make_callable("Shift", [(amount,)])
    family = [{"amount": amount}]
    member_request = VerifyRequest("bounded", ((input_value,),), {"domain": "one input", "size": 1},
                                   reference=lambda item: item + amount)
    lib.verify("Shift", VerifyRequest("bounded", ((),),
        {"domain": "finite family", "size": 1, "family": family},
        extra={"family": family, "member_requests": [member_request]}))
    member = instantiate(lib.get("Shift"), family[0], "shift", lib=lib)
    assert member.content_hash() == instantiate(lib.get("Shift"), family[0], "shift", lib=lib).content_hash()
    if amount != other:
        assert member.content_hash() != instantiate(lib.get("Shift"), {"amount": other},
                                                    "shift", lib=lib).content_hash()
    assert cite_template_evidence(member, lib)
    if amount != other:
        assert not cite_template_evidence(instantiate(lib.get("Shift"), {"amount": other},
                                                      "other", lib=lib), lib)
    lib.write(member)
    lib.check("shift")
    lib.make_callable("shift", [(input_value,)])
    trace = lib.run("shift", (input_value,), trace=True)
    assert trace.outcome == Ok(input_value + amount)
    boundaries = [Boundary.unfold_all(), Boundary.unfold_none(),
                  Boundary(depth=choice, kinds=frozenset({"template", "operation"})),
                  Boundary(open_names=frozenset({"Shift"}), kinds=frozenset({"template"}))]
    assert unfold_equivalent_calls(trace.trace, boundaries).ok


@given(start=st.integers(0, 5), cap=st.integers(0, 6), height=st.integers(0, 9))
@PROPERTY
def test_fix_agrees_with_independent_iteration(start, cap, height):
    scope = kernel.DictScope([*counter_atoms(), *fix_atoms(),
        kernel.Atom("grow", 1, lambda item: min(item + 1, cap))], [combinator_defn(fix_spec())])
    expected = start
    result = Bottom("not_stable")
    for _ in range(height):
        next_value = min(expected + 1, cap)
        if next_value == expected:
            result = Ok(next_value)
            break
        expected = next_value
    actual = kernel.call("fix", (kernel.FnRef("grow"), start, height), scope)
    assert actual.outcome == result
    assert actual.work <= actual.steps


@given(index=st.integers(0, 6), base=st.integers(-3, 3))
@PROPERTY
def test_memo_recursion_preserves_outcome_and_charged_steps(index, base):
    body = n.Rec("fib", ("number",), n.Case((
        (n.Test(call("comb_le", n.Var("number"), n.Lit(1))), n.Lit(base)),),
        call("add", call("fib", call("comb_dec", n.Var("number"))),
             call("fib", call("comb_sub", n.Var("number"), n.Lit(2))))),
        (n.Var("input"),), n.Var("number"))
    plain = CombinatorSpec("plain", ("input",), (), body)
    memo = memoized_spec(plain)
    scope = kernel.DictScope([*counter_atoms(), kernel.Atom("add", 2, lambda left, right: left + right)],
                             [combinator_defn(plain), combinator_defn(memo)])
    original = kernel.call("plain", (index,), scope)
    cached = kernel.call(memo.name, (index,), scope)
    assert (cached.outcome, cached.steps) == (original.outcome, original.steps)
    assert cached.work <= cached.steps


@given(public=st.integers(-5, 5), secret=st.integers(-20, 20),
       alternate=st.integers(-20, 20), schedule=st.lists(st.integers(0, 1), max_size=5))
@PROPERTY
def test_turns_only_use_agents_own_observations(public, secret, alternate, schedule):
    moves = []
    atoms = [*counter_atoms(), *list_atoms(), *turns_atoms(),
             kernel.Atom("observe0", 1, lambda state: state[0]),
             kernel.Atom("observe1", 1, lambda state: state[1]),
             kernel.Atom("choose0", 1, lambda seen: moves.append((0, seen)) or seen + 1),
             kernel.Atom("choose1", 1, lambda seen: moves.append((1, seen)) or seen - 1),
             kernel.Atom("apply", 3, lambda move, agent, state: (
                 move if agent == 0 else state[0], move if agent == 1 else state[1]))]
    scope = kernel.DictScope(atoms, (combinator_defn(turns_spec(2)),))
    refs = tuple(kernel.FnRef(f"{action}{agent}") for agent in range(2)
                 for action in ("observe", "choose")) + (kernel.FnRef("apply"),)
    first = kernel.call("turns", (*refs, (public, secret), tuple(schedule)), scope)
    first_moves = tuple(moves)
    moves.clear()
    second = kernel.call("turns", (*refs, (public, alternate), tuple(schedule)), scope)
    second_moves = tuple(moves)
    moves.clear()
    third = kernel.call("turns", (*refs, (alternate, secret), tuple(schedule)), scope)
    assert first.outcome == Ok((public + schedule.count(0), secret - schedule.count(1)))
    assert second.outcome == Ok((public + schedule.count(0), alternate - schedule.count(1)))
    assert third.outcome == Ok((alternate + schedule.count(0), secret - schedule.count(1)))
    assert tuple(move for move in first_moves if move[0] == 0) == tuple(
        move for move in second_moves if move[0] == 0)
    assert tuple(move for move in first_moves if move[0] == 1) == tuple(
        move for move in moves if move[0] == 1)


@given(items=st.lists(st.integers(-5, 5), max_size=5))
@PROPERTY
def test_derived_fold_matches_host_list_fold(items):
    spec = ObjectSpec("List", "compose", tags={"nil": (), "cons": (("head", "int"), ("tail", "List"))})
    world = WorldDecl("fold-properties", 1, "atoms-v2", {}, {}, (), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    lib = Library(world, ())
    lib._definitions["List"] = Definition("List", "object", "invented", 1, (), spec, None)
    scope = kernel.DictScope([*counter_atoms(), *list_atoms(),
        kernel.Atom("on_nil", 0, lambda: 0),
        kernel.Atom("on_cons", 2, lambda head, tail: head + tail)], object_atoms(spec, lib))
    linked = Card("List", "nil", ())
    for item in reversed(items):
        linked = Card("List", "cons", (item, linked))
    actual = kernel.call("List.fold", (kernel.FnRef("on_nil"), kernel.FnRef("on_cons"), linked), scope)
    assert actual.outcome == Ok(sum(items))


@given(leaves=st.lists(st.integers(-5, 5), min_size=1, max_size=5))
@PROPERTY
def test_derived_fold_matches_host_tree_fold(leaves):
    spec = ObjectSpec("Tree", "compose", tags={"leaf": (("value", "int"),),
                                                "branch": (("left", "Tree"), ("right", "Tree"))})
    world = WorldDecl("tree-properties", 1, "atoms-v2", {}, {}, (spec,), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "measure"}, {}, {})
    lib = Library(world, ())
    derived = object_atoms(spec, lib)
    scope = kernel.DictScope([*counter_atoms(),
        kernel.Atom("on_leaf", 1, lambda value: value),
        kernel.Atom("on_branch", 2, lambda left, right: left + right),
        *(item for item in derived if isinstance(item, kernel.Atom))],
        [item for item in derived if isinstance(item, kernel.Defn)])
    tree = Card("Tree", "leaf", (leaves[0],))
    for leaf in leaves[1:]:
        tree = Card("Tree", "branch", (tree, Card("Tree", "leaf", (leaf,))))
    actual = kernel.call("Tree.fold", (kernel.FnRef("on_leaf"), kernel.FnRef("on_branch"), tree), scope)
    assert actual.outcome == Ok(sum(leaves))
