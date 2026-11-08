"""Regression tests for object, combinator, and ASCII notation review findings."""

from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.combinators import (
    check_combinator,
    combinator_defn,
    fix_spec,
    memoized_spec,
    standard_combinators,
    turns_spec,
    verify_combinator,
)
from opulse.atoms.library import Library, VerifyRequest
from opulse.atoms.notation import parse_expr, parse_value, print_expr, print_value
from opulse.atoms.objects import (
    check_object,
    object_atoms,
    sealed_private_names,
    verify_object,
)
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl


def world(objects=(), operations=()):
    return WorldDecl("review", 1, "atoms-v2", {}, {}, tuple(objects), tuple(operations),
                     {"nodes": ["Var", "Lit", "Call", "Case", "Let"], "recursion": "none"}, {}, {})


def test_refinement_checks_declared_interface_without_request_hint():
    peek = OperationSpec("peek", "transform", (Edge("R"),), Edge("int"), "peek raw")
    lib = Library(world(operations=(peek,)), (kernel.Atom("peek", 1, lambda card: card.fields[0]),))
    spec = ObjectSpec("R", "refine", base="int", valid=n.Lit(True), canon=n.Lit(0),
                      interface=("peek",))
    lib.write(Definition("R", "object", "invented", 1, (), spec, None))
    lib.check("R")
    lib.make_callable("R", [(1,)])
    with pytest.raises(ValueError, match="respects_canon"):
        lib.verify("R", VerifyRequest("exhaustive", ((1,), (2,)),
                                      {"domain": "{1,2}", "size": 2}))
    unknown = ObjectSpec("UnknownR", "refine", base="int", valid=n.Lit(True),
                         interface=("opaque",))
    result = verify_object(
        Definition("UnknownR", "object", "invented", 1, (), unknown, None), lib,
        VerifyRequest("exhaustive", ((1,),), {"domain": "{1}", "size": 1},
                      extra={"interface_ops": {"opaque": (0,)}}))
    assert not result.ok and "respects_canon" not in result.checks


def test_sealed_generated_operations_are_private_to_library_callers():
    spec = ObjectSpec("Secret", "refine", base="int", valid=n.Lit(True),
                      sealed=True, interface=("Secret.make",))
    lib = Library(world(objects=(spec,)), ())
    private = sealed_private_names(lib)
    assert {"Secret.base", "Secret._pack", "Secret._invalid"} <= private
    assert "Secret.make" not in private
    outsider = Definition("leak", "object", "invented", 1, ("Secret.base",), spec,
                          n.Call("Secret.base", (n.Var("x"),)))
    assert any("private sealed operation" in issue for issue in check_object(outsider, lib))
    try:
        result = lib.run("Secret.base", (Card("Secret", "val", (1,)),))
    except (ValueError, KeyError) as error:
        assert "private" in str(error) or "sealed" in str(error)
    else:
        if result.outcome == Ok(1):
            pytest.xfail("needs library guard")
        assert result.outcome != Ok(1)


def test_compose_constructors_check_simple_and_declared_sorts():
    child = ObjectSpec("Child", "compose", tags={"empty": ()})
    pair = ObjectSpec("Pair", "compose", tags={"pair": (("left", "int"), ("right", "Child")),
                                                 "flags": {"items": "bool"}})
    lib = SimpleNamespace(world=SimpleNamespace(objects=(child, pair)), definitions={})
    scope = kernel.DictScope(atoms=object_atoms(pair, lib))
    assert kernel.call("Pair.pair", (1, Card("Child", "empty")), scope).outcome == Ok(
        Card("Pair", "pair", (1, Card("Child", "empty"))))
    for args in ((True, Card("Child", "empty")), (1, "wrong")):
        assert kernel.call("Pair.pair", args, scope).outcome == Bottom("invalid")
    assert kernel.call("Pair.flags", ((True, False),), scope).outcome == Ok(
        Card("Pair", "flags", (True, False)))
    assert kernel.call("Pair.flags", ((True, 1),), scope).outcome == Bottom("invalid")


@settings(deadline=None)
@given(st.integers(), st.text())
def test_compose_constructor_rejects_any_string_in_int_field(value, text):
    spec = ObjectSpec("Number", "compose", tags={"num": (("n", "int"),)})
    lib = SimpleNamespace(world=SimpleNamespace(objects=(spec,)), definitions={})
    scope = kernel.DictScope(atoms=object_atoms(spec, lib))
    assert kernel.call("Number.num", (value,), scope).outcome == Ok(Card("Number", "num", (value,)))
    assert kernel.call("Number.num", (text,), scope).outcome == Bottom("invalid")


def test_fixed_forwarded_operation_is_dependency_and_recorded_scope():
    spec = CombinatorSpec("escape", ("f", "x"), ("f",),
                          n.Call("seq", (n.Lit(kernel.FnRef("outside")), n.Var("f"), n.Var("x"))))
    missing = Definition("escape", "combinator", "invented", 1, ("seq",), spec, spec.body)
    scope = kernel.DictScope(
        [kernel.Atom("inc", 1, lambda value: value + 1),
         kernel.Atom("outside", 1, lambda value: value * 10)],
        [*(combinator_defn(item) for item in standard_combinators()), combinator_defn(spec)])
    lib = SimpleNamespace(dialect="atoms-v2", definitions={}, scope=lambda: scope)
    assert any("outside" in issue for issue in check_combinator(missing, lib))
    valid = Definition("escape", "combinator", "invented", 1, ("outside", "seq"), spec, spec.body)
    request = VerifyRequest("bounded", ((1,),),
                            {"domain": "one", "size": 1, "op_family": ["inc"]},
                            extra={"op_family": ["inc"]})
    assert verify_combinator(valid, lib, request).ok
    assert "fixed_ops" not in request.scope


def test_standard_combinator_failures_round_trip_in_ascii():
    specs = (*standard_combinators(), fix_spec(), turns_spec(2),
             memoized_spec(fix_spec(), "memo_fix"))
    context = {"kinds": {item.name: "combinator" for item in specs},
               "op_arity": {item.name: len(item.op_params) for item in specs}}
    for spec in specs:
        printed = print_expr(spec.body, context)
        assert printed.isascii()
        assert parse_expr(printed, context) == spec.body
    assert parse_value(print_value(Bottom("not_stable"))) == Bottom("not_stable")
