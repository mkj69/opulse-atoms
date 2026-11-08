"""Library name lifecycle and cross-world lexical scope (spec sections 9 and 11)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import Library, PipelineError, checked_scope
from opulse.atoms.spec import BridgeSpec, Definition, Edge, OperationSpec
from opulse.atoms.values import Ok, outcome_equal
from opulse.atoms.world import WorldDecl


def world(name, atoms):
    return Library(WorldDecl(name, 1, "atoms-v2", {}, {}, (), (),
                             {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {},
                             open_kinds=("operation", "bridge")), atoms)


def operation(name, body, dependencies, arity=1):
    spec = OperationSpec(name, "transform", tuple(Edge("int") for _ in range(arity)),
                         Edge("int"), name, extra={"input_names": ["x", "y"][:arity]})
    return Definition(name, "operation", "invented", 1, dependencies, spec, body)


def test_checked_scope_public_alias_and_invalid_domains():
    from opulse.atoms.library import _checked_scope

    domain = ((1, 4), (3, 7))
    assert checked_scope(domain) == _checked_scope(domain)
    assert checked_scope(domain)["bounds"] == {"0": {"min": 1, "max": 3},
                                                "1": {"min": 4, "max": 7}}
    with pytest.raises(PipelineError, match="nonempty"):
        checked_scope(())
    with pytest.raises(PipelineError, match="equal arity"):
        checked_scope(((1,), (2, 3)))


@pytest.mark.parametrize("status", ("written", "checked"))
def test_discard_allows_rewriting_refused_definition(status):
    lib = world("source", (kernel.Atom("inc", 1, lambda value: value + 1),))
    original = operation("draft", nodes.Call("inc", (nodes.Var("x"),)), ("inc",))
    lib.write(original)
    if status == "checked":
        lib.check("draft")
    assert lib.discard("draft").status == status
    replacement = replace(original, body=nodes.Lit(12), depends_on=())
    lib.write(replacement)
    lib.check("draft")
    lib.make_callable("draft", ((1,),))
    assert lib.run("draft", (3,)).outcome == Ok(12)
    with pytest.raises(PipelineError, match="written or checked"):
        lib.discard("draft")
    with pytest.raises(PipelineError, match="written or checked"):
        lib.discard("inc")


def test_discard_refuses_dependents():
    lib = world("source", ())
    lib.write(operation("first", nodes.Var("x"), ()))
    lib.write(operation("second", nodes.Call("first", (nodes.Var("x"),)), ("first",)))
    with pytest.raises(PipelineError, match="dependents: second"):
        lib.discard("first")


def test_qualifying_calls_respects_local_recursive_function():
    body = nodes.Rec("add", ("x",), nodes.Call("add", (nodes.Var("x"),)),
                     (nodes.Call("add", (nodes.Lit(1), nodes.Lit(2))),), "fuel")
    qualified = kernel.qualify_calls(body, "target@1", {"add"})
    assert qualified.args == (nodes.Call("target@1:add", (nodes.Lit(1), nodes.Lit(2))),)
    assert qualified.body == nodes.Call("add", (nodes.Var("x"),))


def collision_worlds():
    source = world("source", (kernel.Atom("add", 3, lambda first, second, third: first + second + third),
                              kernel.Atom("nonnegative", 1, lambda value: value >= 0)))
    target = world("target", (kernel.Atom("add", 2, lambda first, second: first + second),))
    source.attach_world("target@1", target)
    target.attach_world("source@1", source)
    helper = operation("double", nodes.Call("add", (nodes.Var("x"), nodes.Var("x"))), ("add",))
    target.write(helper)
    target.check("double")
    target.make_callable("double", ((2,),))
    spec = BridgeSpec("translate", "source@1:int", "target@1:int",
                      nodes.Call("double", (nodes.Var("x"),)),
                      nodes.Call("nonnegative", (nodes.Var("x"),)))
    source.write(Definition("translate", "bridge", "invented", 2,
                            ("double", "nonnegative"), spec, bridge_defn(spec).body))
    source.check("translate")
    source.make_callable("translate", ((2,),))
    caller = replace(operation("twice_over", nodes.Call("translate", (nodes.Var("x"),)),
                               ("translate",)), layer=3)
    source.write(caller)
    source.check("twice_over")
    source.make_callable("twice_over", ((2,),))
    return source, target


@settings(deadline=None)
@given(st.integers(min_value=0, max_value=100))
def test_cross_world_qualified_scope_matches_unfolded_execution(value):
    source, target = collision_worlds()
    scope = source.scope()
    assert isinstance(scope, kernel.ChainScope)
    assert scope.resolve("source@1:add").arity == 3
    assert scope.resolve("target@1:add").arity == 2
    assert source.local_scope().resolve("add").arity == 3
    assert target.local_scope().resolve("add").arity == 2
    assert source.run("translate", (value,)).outcome == Ok(value * 2)
    assert source.run("twice_over", (value,)).outcome == Ok(value * 2)
    call = nodes.Call("translate", (nodes.Lit(value),))
    named = kernel.evaluate(call, scope=scope)
    expanded = kernel.evaluate(kernel.inline(call, scope), scope=scope)
    assert outcome_equal(named.outcome, expanded.outcome)
    assert named.steps == expanded.steps


def test_target_bridge_sees_its_own_world_under_collision():
    _, target = collision_worlds()
    spec = BridgeSpec("back", "target@1:int", "source@1:int",
                      nodes.Call("add", (nodes.Var("x"), nodes.Lit(2), nodes.Lit(3))))
    target.write(Definition("back", "bridge", "invented", 1, ("add",),
                            spec, bridge_defn(spec).body))
    target.check("back")
    target.make_callable("back", ((4,),))
    assert target.run("back", (4,)).outcome == Ok(9)
    assert target.run("twice_over", (4,)).outcome == Ok(8)
