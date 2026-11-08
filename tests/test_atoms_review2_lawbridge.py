"""Regression checks for review-round-two law, bridge, and library findings."""

import functools
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_atoms_bridges import definition, library, request
from test_atoms_laws import comm_law, integer_library, promote_law

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import BridgeContext, bridge_defn, verify_bridge
from opulse.atoms.laws import RewriteError, _substitute, replay_rewrite, rewrite
from opulse.atoms.library import Library, PipelineError, atoms_digest
from opulse.atoms.spec import BridgeSpec, Contract, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Card, Ok


def test_empty_binary_pairs_cannot_verify_or_promote():
    lib = library(atoms=(kernel.Atom("shift", 1, lambda value: value + 1),
                         kernel.Atom("add", 2, lambda left, right: left + right)))
    spec = BridgeSpec("bad", "Int", "Int", n.Call("shift", (n.Var("x"),)),
                      interface=(("add", "add"),))
    defn = definition(spec)
    assert not verify_bridge(defn, lib, request((0, 1), pairs=())).ok
    lib.write(defn)
    lib.check(defn.name)
    lib.make_callable(defn.name, ((0,),))
    with pytest.raises(PipelineError, match="no checked pairs"):
        lib.verify(defn.name, request((0, 1), pairs=()))


def test_colliding_cross_world_calls_choose_source_for_map():
    source = library("clock", (kernel.Atom("scale", 1, lambda value: value + 1),
                               kernel.Atom("src_add", 2, lambda left, right: left + right)), ("Hour",))
    target = library("integers", (kernel.Atom("scale", 1, lambda value: value * 2),
                                  kernel.Atom("dst_add", 2, lambda left, right: left + right)), ("Int",))
    spec = BridgeSpec("map", "clock@1:Hour", "integers@1:Int",
                      n.Call("scale", (n.Var("x"),)), interface=(("src_add", "dst_add"),))
    context = BridgeContext(source, target)
    result = verify_bridge(definition(spec), context, request((0, 1), bridge_context=context))
    assert not result.ok
    assert any("commutes" in problem for problem in result.problems)
    assert kernel.call("map", (0,), source.scope().extend((bridge_defn(spec),))).outcome == Ok(1)
    assert target.run("scale", (1,)).outcome == Ok(2)


@settings(deadline=None)
@given(st.integers(min_value=0, max_value=10))
def test_target_sort_enforced_for_every_mapped_value(value):
    lib = library(atoms=(kernel.Atom("plus", 2, lambda left, right: left + right),))
    defn = definition(BridgeSpec("to_bool", "Int", "bool", n.Var("x")))
    result = verify_bridge(defn, lib, request((value,)))
    assert not result.ok and any("target sort" in problem for problem in result.problems)


def test_target_card_sort_enforced():
    lib = library(sorts=("Int", "Other"))
    defn = definition(BridgeSpec("to_other", "Int", "Other", n.Lit(Card("Int", "v"))))
    assert not verify_bridge(defn, lib, request((1,))).ok


def test_attached_world_supports_bridge_pipeline():
    source = library("clock", (), ("Hour",))
    target = library("integers", (kernel.Atom("to_int_op", 1, lambda value: value),), ("Int",))
    spec = BridgeSpec("to_int", "clock@1:Hour", "integers@1:Int",
                      n.Call("to_int_op", (n.Var("x"),)))
    source.attach_world("integers@1", target)
    source.write(definition(spec))
    source.check(spec.name)
    source.make_callable(spec.name, ((0,),))
    source.verify(spec.name, request((0, 1)))
    assert source.promote(spec.name, Contract("identity translation")).status == "promoted"
    assert source.run(spec.name, (1,)).outcome == Ok(1)
    restored = Library.from_dict(source.to_dict(), source.world, source.atoms,
                                 {"integers@1": target})
    assert restored.get(spec.name).status == "promoted"
    assert restored.run(spec.name, (1,)).outcome == Ok(1)


def test_replay_let_body_case_arm_and_rec_body():
    lib = integer_library()
    law = promote_law(lib, comm_law())
    left = n.Call("add", (n.Var("z"), n.Lit(1)))
    right = n.Call("add", (n.Lit(1), n.Var("z")))
    expr = n.Let("z", n.Lit(2), left)
    updated = n.Let("z", n.Lit(2), right)
    assert rewrite(expr, law, lib, at=(1,)) == updated
    assert replay_rewrite(expr, updated, law, lib, {}).steps[0].path == (1,)
    case = n.Case(((n.Test(n.Lit(True)), left),), n.Lit(0))
    rewritten_case = n.Case(((n.Test(n.Lit(True)), right),), n.Lit(0))
    assert rewrite(case, law, lib, at=(0,)) == rewritten_case
    assert replay_rewrite(case, rewritten_case, law, lib, {"z": 2}).steps[0].path == (0,)
    rec = n.Rec("loop", ("z",), left, (n.Lit(2),), "fuel")
    rewritten_rec = replace(rec, body=right)
    assert rewrite(rec, law, lib, at=(1,)) == rewritten_rec
    assert replay_rewrite(rec, rewritten_rec, law, lib, {}).steps[0].path == (1,)


def test_replacement_cannot_capture_let_bound_name():
    with pytest.raises(RewriteError, match="capture"):
        _substitute(n.Let("z", n.Lit(2), n.Var("a")), {"a": n.Var("z")})


def test_keyword_defaults_and_partial_arguments_change_digest():
    def implementation(value, *, delta=1):
        return value + delta

    before = atoms_digest((kernel.Atom("inc", 1, implementation),))
    implementation.__kwdefaults__["delta"] = 9
    assert atoms_digest((kernel.Atom("inc", 1, implementation),)) != before
    first = kernel.Atom("partial", 1, functools.partial(implementation, delta=1))
    second = kernel.Atom("partial", 1, functools.partial(implementation, delta=2))
    assert atoms_digest((first,)) != atoms_digest((second,))


def test_keyword_default_change_invalidates_promoted_evidence():
    from test_atoms_library import definition as operation_definition
    from test_atoms_library import fixture, ready

    lib = fixture()

    def increment(value, *, delta=1):
        return value + delta

    lib.atoms = tuple(replace(atom, fn=increment) if atom.name == "succ" else atom
                      for atom in lib.atoms)
    ready(lib, operation_definition("f", n.Call("succ", (n.Var("arg0"),)),
                                    ("succ",), 1, ("arg0",)), ((0,),))
    from opulse.atoms.library import VerifyRequest

    lib.verify("f", VerifyRequest("bounded", ((0,),), {"domain": "0 <= 1", "size": 1},
                                   reference=lambda value: value + 1))
    lib.promote("f", Contract("x+1"))
    increment.__kwdefaults__["delta"] = 9
    assert lib.derived_world().promoted == ()
    assert Library.from_dict(lib.to_dict(), lib.world, lib.atoms).get("f").status != "promoted"


def test_sealed_reference_in_dictionary_key_rejected():
    from opulse.atoms.world import WorldDecl

    secret = ObjectSpec("Secret", "compose", tags={"box": (("value", "int"),)},
                        sealed=True, interface=("Secret.box",))
    dispatch = OperationSpec("dispatch", "transform", (Edge("unknown"), Edge("Secret")),
                             Edge("int"), "dispatch")
    world = WorldDecl("w", 1, "atoms-v2", {}, {}, (secret,), (dispatch,),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    lib = Library(world, (kernel.Atom("dispatch", 2, lambda context, mapping, value:
                                      context.call(next(iter(mapping)).name, (value,)), metered=True),))
    with pytest.raises(PipelineError, match="sealed"):
        lib.run("dispatch", ({kernel.FnRef("Secret.value"): 0}, Card("Secret", "box", (5,))))


def test_definitions_are_fresh_and_records_are_read_only():
    lib = library(atoms=(kernel.Atom("inc", 1, lambda value: value + 1),))
    exposed = lib.definitions
    exposed["inc"].spec.extra["input_names"] = ["tampered"]
    assert "input_names" not in lib.definitions["inc"].spec.extra
    with pytest.raises(TypeError):
        lib.records()["inc"] = exposed["inc"]
