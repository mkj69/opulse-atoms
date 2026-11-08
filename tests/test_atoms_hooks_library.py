"""Library hooks for given combinators, dependencies, and sealing (spec sections 8-12)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.boundary import Boundary
from opulse.atoms.combinators import standard_combinators, verify_combinator
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.observations import observe
from opulse.atoms.spec import (
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Card, Ok
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl


def library(combinators=(), objects=()):
    operations = tuple(OperationSpec(name, "transform", tuple(Edge("int") for _ in range(arity)),
                                     Edge("int"), name)
                       for name, arity in (("zero", 0), ("succ", 1), ("inc", 1)))
    world = WorldDecl("hooks", 1, "atoms-v2", {}, {}, tuple(objects), operations,
                      {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel", "library": combinators}, {}, {})
    atoms = (kernel.Atom("zero", 0, lambda: 0), kernel.Atom("succ", 1, lambda value: value + 1),
             kernel.Atom("inc", 1, lambda value: value + 2))
    return Library(world, atoms)


def operation(name, body, depends_on, layer):
    spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"), name,
                         extra={"input_names": ["arg0"]})
    return Definition(name, "operation", "invented", layer, tuple(depends_on), spec, body)


def checked_callable(lib, definition):
    lib.write(definition)
    lib.check(definition.name)
    return lib.make_callable(definition.name, ((1,),))


@pytest.mark.parametrize("as_name", [True, False])
def test_given_combinators_are_promoted_and_callable(as_name):
    twice = next(spec for spec in standard_combinators() if spec.name == "twice")
    entry = "twice" if as_name else twice.to_dict()
    lib = library((entry,))
    assert lib.get("twice").origin == "given"
    assert lib.get("twice").status == "promoted" and lib.get("twice").layer == 0
    assert lib.run("twice", (kernel.FnRef("succ"), 1)).outcome == Ok(3)
    assert lib.scope().resolve("twice").kind == "combinator"


@given(value=st.integers(min_value=-100, max_value=100))
@settings(max_examples=15, deadline=None)
def test_given_combinator_unfolding_and_boundary(value):
    lib = library(("twice",))
    run = lib.run("twice", (kernel.FnRef("succ"), value), trace=True)
    unfolded = kernel.inline(nodes.Call("twice", (nodes.Lit(kernel.FnRef("succ")), nodes.Lit(value))),
                             lib.scope())
    expanded = kernel.evaluate(unfolded, scope=lib.scope())
    assert run.outcome == expanded.outcome == Ok(value + 2)
    assert run.steps == expanded.steps
    assert unfold_equivalent_calls(run.trace, (Boundary(), Boundary.unfold_all())).ok


def test_sealed_private_calls_are_rejected_at_library_boundary():
    secret = ObjectSpec("Secret", "compose", tags={"box": (("value", "int"),)},
                        sealed=True, interface=("Secret.box",))
    lib = library(objects=(secret,))
    private = "Secret.value"
    assert private in lib.scope().atoms
    assert kernel.call(private, (Card("Secret", "box", (3,)),), lib.scope()).outcome == Ok(3)
    with pytest.raises(PipelineError, match="sealed object private"):
        lib.run(private, (0,))
    with pytest.raises(PipelineError, match="sealed object private"):
        _check_private(lib, private)
    with pytest.raises(PipelineError, match="sealed object private"):
        Library.from_dict(lib.to_dict(), lib.world, lib.atoms)


def test_sealed_private_reference_cannot_be_passed_to_given_combinator():
    secret = ObjectSpec("Secret", "compose", tags={"box": (("value", "int"),)},
                        sealed=True, interface=("Secret.box",))
    lib = library(("twice",), (secret,))
    with pytest.raises(PipelineError, match="sealed object private"):
        lib.run("twice", (kernel.FnRef("Secret.value"), Card("Secret", "box", (2,))))


def _check_private(lib, private):
    lib.write(operation("peek", nodes.Call(private, (nodes.Var("arg0"),)), (private,), 1))
    lib.check("peek")


def test_callable_account_records_sample_steps_without_evidence():
    lib = library()
    checked_callable(lib, operation("bump", nodes.Call("succ", (nodes.Var("arg0"),)), ("succ",), 1))
    cost = lib.account("bump").cost
    assert cost.length > 0 and cost.steps["min"] == 1 and cost.steps["over"] == "samples"
    assert lib.get("bump").status == "callable"


def test_generated_operation_depends_on_invented_object():
    lib = library()
    shape = ObjectSpec("Shape", "compose", tags={"point": (("value", "int"),)})
    lib.write(Definition("Shape", "object", "invented", 1, (), shape, None))
    lib.check("Shape")
    lib.make_callable("Shape", ((1,),))
    body = nodes.Call("Shape.value", (nodes.Var("arg0"),))
    spec = OperationSpec("read", "transform", (Edge("Shape"),), Edge("int"), "read",
                         extra={"input_names": ["arg0"]})
    lib.write(Definition("read", "operation", "invented", 2, ("Shape.value",), spec, body))
    lib.check("read")
    original = lib.deps_hash("read")
    changed = replace(shape, tags={"point": (("value", "int"),), "empty": ()})
    lib.replace("Shape", Definition("Shape", "object", "invented", 1, (), changed, None))
    assert lib.deps_hash("read") != original


def test_literal_operations_change_layer_and_hashes_without_forcing_depends_on():
    twice = next(spec for spec in standard_combinators() if spec.name == "twice")
    lib = library((twice.to_dict(),))
    checked_callable(lib, operation("first", nodes.Call("succ", (nodes.Var("arg0"),)), ("succ",), 1))
    body = nodes.Call("twice", (nodes.Lit(kernel.FnRef("first")), nodes.Var("arg0")))
    checked_callable(lib, operation("higher", body, ("twice",), 2))
    assert "first" not in lib.get("higher").depends_on
    old_content, old_deps = lib.content_hash("higher"), lib.deps_hash("higher")
    modified = operation("first", nodes.Call("inc", (nodes.Var("arg0"),)), ("inc",), 1)
    lib.replace("first", modified)
    assert (lib.content_hash("higher"), lib.deps_hash("higher")) != (old_content, old_deps)
    with pytest.raises(PipelineError, match="layer must be at least 2"):
        other = library((twice.to_dict(),))
        checked_callable(other, operation("first", nodes.Call("succ", (nodes.Var("arg0"),)), ("succ",), 1))
        other.write(replace(operation("higher", body, ("twice",), 2), layer=1))
        other.check("higher")


def test_memory_references_are_required_and_invalidate_dependent_hashes():
    lib = library()
    memory = {"init": nodes.Call("zero", ()), "step": nodes.Call("succ", (nodes.Var("memory"),))}
    body = nodes.Call("inc", (nodes.Var("memory"),))
    spec = ObservationSpec("clock", (), body, memory)
    defn = Definition("clock", "observation", "invented", 1, ("zero", "succ", "inc"), spec, body)
    lib.write(defn)
    lib.check("clock")
    assert lib.deps_hash("clock")
    with pytest.raises(PipelineError, match="depends_on"):
        lib.write(replace(defn, name="bad", spec=replace(spec, name="bad"), depends_on=("inc",)))


def test_memory_step_dependency_sets_layer_and_hash():
    lib = library()
    tick_body = nodes.Call("inc", (nodes.Lit(1),))
    tick = ObservationSpec("tick", (), tick_body)
    lib.write(Definition("tick", "observation", "invented", 1, ("inc",), tick, tick_body))
    lib.check("tick")
    lib.make_callable("tick", ((0,),))
    memory = {"init": nodes.Call("zero", ()), "step": nodes.Call("tick", (nodes.Var("s"),))}
    body = nodes.Var("memory")
    spec = ObservationSpec("clock", (), body, memory)
    definition = Definition("clock", "observation", "invented", 2, ("zero", "tick"), spec, body)
    lib.write(definition)
    lib.check("clock")
    old_hashes = lib.content_hash("clock"), lib.deps_hash("clock")
    changed_body = nodes.Call("succ", (nodes.Lit(1),))
    lib.replace("tick", Definition("tick", "observation", "invented", 1, ("succ",),
                                    replace(tick, body=changed_body), changed_body))
    assert (lib.content_hash("clock"), lib.deps_hash("clock")) != old_hashes


@given(count=st.integers(min_value=1, max_value=8))
@settings(max_examples=8, deadline=None)
def test_memory_observation_leaves_input_facts_unchanged(count):
    lib = library()
    memory = {"init": nodes.Call("zero", ()), "step": nodes.Call("succ", (nodes.Var("memory"),))}
    body = nodes.Call("inc", (nodes.Var("memory"),))
    spec = ObservationSpec("clock", (), body, memory)
    defn = Definition("clock", "observation", "invented", 1, ("zero", "succ", "inc"), spec, body)
    states = list(range(count))
    assert observe(defn, lib, states) == [Ok(index + 3) for index in range(count)]
    assert states == list(range(count))


def test_verify_combinator_does_not_mutate_request_scope():
    twice = next(spec for spec in standard_combinators() if spec.name == "twice")
    lib = library()
    definition = Definition("twice", "combinator", "invented", 1, (), twice, twice.body)
    scope = {"domain": "bounded <=1", "size": 1, "op_family": ("succ",)}
    request = VerifyRequest("bounded", ((1,),), scope, extra={"op_family": ("succ",)})
    assert verify_combinator(definition, lib, request).ok
    assert scope == {"domain": "bounded <=1", "size": 1, "op_family": ("succ",)}


def test_scope_is_cached_until_the_library_changes():
    from opulse.atoms import kernel
    from opulse.atoms import nodes as n
    from opulse.atoms.library import Library
    from opulse.atoms.spec import Definition, Edge, OperationSpec
    from opulse.atoms.world import WorldDecl

    world = WorldDecl("w", 1, "atoms-v2", {}, {}, (), (OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "x+1"),),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    lib = Library(world, [kernel.Atom("inc", 1, lambda value: value + 1)])
    first = lib.scope()
    assert lib.scope().defns == first.defns and lib._cache["scope"][0] == lib._version()
    spec = OperationSpec("two", "transform", (Edge("int"),), Edge("int"), "x+2", extra={"input_names": ["x"]})
    lib.write(Definition("two", "operation", "invented", 1, ("inc",), spec, n.Call("inc", (n.Call("inc", (n.Var("x"),)),))))
    lib.check("two")
    lib.make_callable("two", [(1,)])
    assert "two" in lib.scope().defns and "two" not in first.defns
    first.defns["junk"] = None  # a caller's copy never leaks into the cache
    assert "junk" not in lib.scope().defns
