"""Round-six library regressions (atoms-v2 spec sections 4, 8, 9 and 11)."""

import os
import subprocess
import sys
from dataclasses import replace
from types import ModuleType

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import library as library_module
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, PipelineError, VerifyResult, atoms_digest
from opulse.atoms.spec import (
    Contract,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl


def world(objects=(), operations=(), atoms=(), open_kinds=None):
    declaration = WorldDecl("round6", 1, "atoms-v2", {}, {}, objects, operations,
                            {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {},
                            **({"open_kinds": open_kinds} if open_kinds else {}))
    return Library(declaration, atoms)


@pytest.mark.parametrize("checks,scope,accepted", [
    (("dependency", "facts_unchanged", "non_interference", "reference"), {}, True),
    (("dependency", "facts_unchanged", "non_interference", "unfold_equivalence"),
     {"reference": "none"}, True),
    (("dependency", "facts_unchanged", "non_interference", "unfold_equivalence"), {}, False),
    (("dependency", "facts_unchanged", "non_interference", "reference"),
     {"reference": "none"}, True),
    (("dependency", "facts_unchanged", "unfold_equivalence"), {"reference": "none"}, False),
])
def test_observation_promotion_alternative(monkeypatch, checks, scope, accepted):
    from opulse.atoms.library import VerifyRequest
    from opulse.atoms.spec import ObservationSpec

    lib = world(open_kinds=("observation",))
    body = n.Lit(0)
    lib.write(Definition("seen", "observation", "invented", 1, (),
                         ObservationSpec("seen", (), body), body))
    lib._definitions["seen"] = replace(lib.get("seen"), status="callable")
    monkeypatch.setitem(library_module._VERIFIERS, "observation",
                        lambda *_: VerifyResult(True, checks, [], [1]))
    request = VerifyRequest("bounded", ((0,),), {"domain": "bound <= 1", "size": 1, **scope})
    lib.verify("seen", request)
    if accepted:
        promoted = lib.promote("seen", Contract("observed"))
        if scope:
            assert promoted.evidence.scope["reference"] == scope["reference"]
    else:
        with pytest.raises(PipelineError, match="obligations not checked"):
            lib.promote("seen", Contract("observed"))


@pytest.mark.parametrize("enter,number,expected", [
    ("bottom", 4, Ok(Card("Positive", "val", (4,)))),
    ("normalize", 4, Ok(Card("Positive", "val", (4,)))),
    ("bottom", -1, Bottom("invalid")),
])
def test_refined_output_enters_edge(enter, number, expected):
    positive = ObjectSpec("Positive", "refine", base="int", valid=n.Call("positive", (n.Var("x"),)))
    operation = OperationSpec("positive", "decide", (Edge("int"),), Edge("bool"), "positive")
    lib = world((positive,), (operation,), (kernel.Atom("positive", 1, lambda value: value > 0),))
    spec = OperationSpec("produce", "transform", (), Edge("Positive", enter), "produce")
    definition = Definition("produce", "operation", "invented", 1, (), spec, n.Lit(number))
    lib.write(definition)
    lib.check("produce")
    lib.make_callable("produce", ((),))
    assert lib.run("produce", ()).outcome == expected
    assert lib.run("produce", ()).outcome == kernel.call("produce", (), lib.scope()).outcome


def test_refined_output_base_call_and_explicit_make():
    positive = ObjectSpec("Positive", "refine", base="int", valid=n.Lit(True))
    increment = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "inc")
    lib = world((positive,), (increment,), (kernel.Atom("inc", 1, lambda value: value + 1),))
    for name, body, depends_on in (
        ("base", n.Call("inc", (n.Lit(1),)), ("inc",)),
        ("made", n.Call("Positive.make", (n.Lit(2),)), ("Positive.make",)),
    ):
        spec = OperationSpec(name, "transform", (), Edge("Positive", "normalize"), name)
        lib.write(Definition(name, "operation", "invented", 1, depends_on, spec, body))
        lib.check(name)
        lib.make_callable(name, ((),))
        assert lib.run(name, ()).outcome == Ok(Card("Positive", "val", (2,)))


def test_refined_saturate_output_enters_make():
    positive = ObjectSpec("Positive", "refine", base="int", valid=n.Lit(True))
    lib = world((positive,))
    spec = OperationSpec("produce", "transform", (), Edge("Positive", "saturate(0, 10)"), "produce")
    lib.write(Definition("produce", "operation", "invented", 1, (), spec, n.Lit(2)))
    lib.check("produce")
    lib.make_callable("produce", ((),))
    assert lib.run("produce", ()).outcome == Ok(Card("Positive", "val", (2,)))


@settings(deadline=None)
@given(st.integers(min_value=-100, max_value=100))
def test_refined_output_matches_explicit_make(number):
    positive = ObjectSpec("Positive", "refine", base="int", valid=n.Lit(True))
    lib = world((positive,))
    spec = OperationSpec("produce", "transform", (), Edge("Positive", "normalize"), "produce")
    lib.write(Definition("produce", "operation", "invented", 1, (), spec, n.Lit(number)))
    lib.check("produce")
    lib.make_callable("produce", ((),))
    assert lib.run("produce", ()).outcome == lib.run("Positive.make", (number,)).outcome


def test_sealed_reference_scan_deep_card():
    sealed = ObjectSpec("Secret", "refine", base="int", valid=n.Lit(True),
                        sealed=True, interface=("Secret.base",))
    lib = world((sealed,))
    nested = kernel.FnRef("Secret.make")
    for _ in range(512):
        nested = Card("list", "cons", (nested,))
    with pytest.raises(PipelineError, match="sealed object private name"):
        lib.run("Secret.base", (nested,))


def test_generated_object_operation_uses_owner_layer():
    lib = world(open_kinds=("object", "operation"))
    obj = ObjectSpec("Patch", "refine", base="int", valid=n.Lit(True))
    lib.write(Definition("Patch", "object", "invented", 1, (), obj, None))
    lib.check("Patch")
    lib.make_callable("Patch", ((1,),))
    spec = OperationSpec("wrap", "transform", (), Edge("Patch"), "wrap")
    body = n.Call("Patch.make", (n.Lit(1),))
    lib.write(Definition("wrap", "operation", "invented", 2, ("Patch.make",), spec, body))
    lib.check("wrap")


def test_law_run_binds_typed_variables():
    lib = world(atoms=(kernel.Atom("eq", 2, lambda left, right: left == right),),
                open_kinds=("law",))
    statement = n.Call("eq", (n.Var("left"), n.Var("right")))
    spec = LawSpec("same", (("left", "int"), ("right", "int")), statement)
    lib.write(Definition("same", "law", "invented", 1, ("eq",), spec, statement))
    lib._definitions["same"] = replace(lib.get("same"), status="callable")
    assert lib.run("same", (2, 2)).outcome == Ok(True)
    assert lib.run("same", (2, 3)).outcome == Ok(False)


def _digest_helper(value):
    return value + 1


def _digest_wrapper(value):
    return _digest_helper(value)


_digest_module = ModuleType("digest_reference")


def _module_digest_wrapper(value):
    return _digest_module.step(value)


def test_digest_follows_global_helper_and_callable_cost():
    namespace = _digest_wrapper.__globals__
    original_helper = _digest_helper
    atom = kernel.Atom("x", 1, _digest_wrapper, cost=lambda value: value)
    before = atoms_digest((atom,))
    try:
        namespace["_digest_helper"] = lambda value: value + 2
        assert atoms_digest((atom,)) != before
        namespace["_digest_helper"] = original_helper
        assert atoms_digest((replace(atom, cost=lambda value: value + 1),)) != before
    finally:
        namespace["_digest_helper"] = original_helper


def test_digest_follows_module_global_helper():
    module = _digest_module
    original_step = module.step if hasattr(module, "step") else None
    module.step = _digest_helper
    try:
        original = atoms_digest((kernel.Atom("step", 1, _module_digest_wrapper),))
        module.step = lambda value: value + 2
        assert atoms_digest((kernel.Atom("step", 1, _module_digest_wrapper),)) != original
    finally:
        if original_step is None:
            del module.step
        else:
            module.step = original_step


def test_digest_stable_across_processes():
    script = ("from opulse.atoms.kernel import Atom; from opulse.atoms.library import atoms_digest; "
              "print(atoms_digest((Atom('x', 1, lambda value: value + 1, "
              "cost=lambda value: value * 2),)))")
    env = {**os.environ, "PYTHONPATH": "src"}
    first = subprocess.check_output([sys.executable, "-c", script], env=env)
    second = subprocess.check_output([sys.executable, "-c", script], env=env)
    assert first == second
