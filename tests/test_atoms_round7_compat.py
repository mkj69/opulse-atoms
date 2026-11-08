"""Round-seven world compatibility regressions (spec sections 4.3, 8, 9, 11)."""

from copy import deepcopy
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom, Run
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import Contract, Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl


def library(objects=(), operations=(), atoms=()):
    world = WorldDecl("compat", 1, "atoms-v2", {}, {}, tuple(objects), tuple(operations),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("object", "operation"))
    return Library(world, atoms)


def request(*values):
    return VerifyRequest("bounded", tuple((value,) for value in values),
                         {"domain": "witnesses", "size": len(values)})


def test_bottom_refined_input_accepts_valid_noncanonical_and_rejects_invalid_card():
    refined = ObjectSpec("Positive", "refine", base="int",
                         valid=n.Call("positive", (n.Var("x"),)),
                         canon=n.Call("clamp", (n.Var("x"),)))
    spec = OperationSpec("consume", "transform", (Edge("Positive", "bottom"),),
                         Edge("int"), "consume")
    calls = []

    def consume(value):
        calls.append(value)
        return value.fields[0]

    lib = library((refined,), atoms=(Atom("positive", 1, lambda value: type(value) is int and value > 0),
                                      Atom("clamp", 1, lambda value: min(value, 2)),
                                      Atom("host_consume", 1, consume)))
    lib.write(Definition("consume", "operation", "invented", 1, ("host_consume",),
                         spec, n.Call("host_consume", (n.Var("arg0"),))))
    lib.check("consume")
    lib.make_callable("consume", [(Card("Positive", "val", (2,)),)])
    calls.clear()
    assert lib.run("consume", (Card("Positive", "val", (3,)),)).outcome == Ok(3)
    assert calls == [Card("Positive", "val", (3,))]
    calls.clear()
    for forged in (Card("Positive", "val", (0,)), Card("Positive", "val", (True,))):
        assert lib.run("consume", (forged,)).outcome == Bottom("invalid")
    assert calls == []
    assert lib.run("consume", (Card("Positive", "val", (2,)),)).outcome == Ok(2)


def test_missing_or_mismatched_checked_is_stale():
    lib = library()
    spec = ObjectSpec("Box", "compose", tags={"box": (("value", "int"),)})
    lib.write(Definition("Box", "object", "invented", 1, (), spec, None))
    lib.check("Box")
    lib.make_callable("Box", [(1,)])
    lib.verify("Box", request(1))
    lib.promote("Box", Contract("boxed integers"))
    stored = deepcopy(lib.to_dict())
    stored["definitions"][0]["evidence"]["scope"].pop("checked")
    missing = Library.from_dict(stored, lib.world, lib.atoms).get("Box")
    assert missing.status == "callable"
    assert missing.evidence is None
    assert missing.contract is None
    stale_data = deepcopy(lib.to_dict())
    stale_data["definitions"][0]["evidence"]["scope"]["checked"] = {"size": 999}
    stale = Library.from_dict(stale_data, lib.world, lib.atoms).get("Box")
    assert stale.status == "callable"
    assert stale.evidence is None
    stale_data["definitions"][0]["evidence"]["scope"]["checked"] = None
    assert Library.from_dict(stale_data, lib.world, lib.atoms).get("Box").status == "callable"


def test_no_verified_status_without_evidence_even_if_record_is_tampered():
    lib = library()
    spec = ObjectSpec("Box", "compose", tags={"box": (("value", "int"),)})
    lib.write(Definition("Box", "object", "invented", 1, (), spec, None))
    lib.check("Box")
    lib.make_callable("Box", [(1,)])
    lib._definitions["Box"] = replace(lib.get("Box"), status="verified")
    assert lib.get("Box").status == "callable"
    with pytest.raises(PipelineError, match="requires evidence"):
        lib._advance("Box", "verified")


def test_omitted_refinement_references_are_derived_for_layer_and_hash():
    lib = library(atoms=(Atom("valid_int", 1, lambda value: value > 0),))
    spec = ObjectSpec("Positive", "refine", base="int",
                      valid=n.Call("valid_int", (n.Var("x"),)))
    lib.write(Definition("Positive", "object", "invented", 1, (), spec, None))
    lib.check("Positive")
    assert "valid_int" in lib._dependency_names(lib.get("Positive"))
    explicit = library(atoms=lib.atoms)
    explicit.write(Definition("Positive", "object", "invented", 1, ("valid_int",), spec, None))
    assert lib.content_hash("Positive") == explicit.content_hash("Positive")
    assert lib.deps_hash("Positive") == explicit.deps_hash("Positive")
    lib.make_callable("Positive", [(1,)])
    lib.verify("Positive", request(1))
    assert lib.promote("Positive", Contract("positive integers")).status == "promoted"
    extra = library(atoms=lib.atoms)
    extra.write(Definition("Positive", "object", "invented", 1, ("valid_int", "valid_int"), spec, None))
    with pytest.raises(PipelineError, match="twice"):
        extra.check("Positive")


def test_transitive_refined_sorts_upcast_but_do_not_downcast():
    objects = (ObjectSpec("Natural", "refine", base="int", valid=n.Lit(True)),
               ObjectSpec("Small", "refine", base="Natural", valid=n.Lit(True)))
    specs = (OperationSpec("read_int", "transform", (Edge("int"),), Edge("int"), "read"),
             OperationSpec("read_small", "transform", (Edge("Small"),), Edge("int"), "read"))
    lib = library(objects, specs, (Atom("read_int", 1, lambda value: value),
                                   Atom("read_small", 1, lambda value: value),))
    refined = ObjectSpec("Checked", "refine", base="Small",
                         valid=n.Call("read_int", (n.Var("x"),)))
    lib.write(Definition("Checked", "object", "invented", 1, (), refined, None))
    lib.check("Checked")
    accepted = Definition("accepted", "operation", "invented", 1, ("read_int",),
                          OperationSpec("accepted", "transform", (Edge("Small"),), Edge("int"), "read"),
                          n.Call("read_int", (n.Var("arg0"),)))
    lib.write(accepted)
    lib.check("accepted")
    rejected = Definition("rejected", "operation", "invented", 1, ("read_small",),
                          OperationSpec("rejected", "transform", (Edge("int"),), Edge("int"), "read"),
                          n.Call("read_small", (n.Var("arg0"),)))
    lib.write(rejected)
    with pytest.raises(PipelineError, match="expected Small, got int"):
        lib.check("rejected")


def test_compose_uses_nested_given_host_witnesses():
    given_list = ObjectSpec("List", "given")
    spec = ObjectSpec("PlanData", "compose", tags={"record": (("items", "List"),)})
    lib = library((given_list,))
    lib.write(Definition("PlanData", "object", "invented", 1, (), spec, None))
    lib.check("PlanData")
    lib.make_callable("PlanData", [((),)])
    evidence = lib.verify("PlanData", request(Card("PlanData", "record", ((1, 2),)))).evidence
    assert evidence.checks == ("finite_values",)
    assert evidence.scope["untested_tags"] == []


def test_compose_requires_a_built_base_tag():
    class FailedConstructor(Library):
        def run(self, name, args, *additional, **options):
            if name == "Box.box":
                return Run(Bottom("invalid"), 1, 0, None)
            return super().run(name, args, *additional, **options)

    spec = ObjectSpec("Box", "compose", tags={"box": (("value", "int"),)})
    base = library()
    lib = FailedConstructor(base.world, base.atoms)
    lib.write(Definition("Box", "object", "invented", 1, (), spec, None))
    lib.check("Box")
    lib.make_callable("Box", [(2,)])
    with pytest.raises(PipelineError, match="built base tag"):
        lib.verify("Box", request(2))


@settings(deadline=None)
@given(st.lists(st.integers(min_value=-5, max_value=5), min_size=1, max_size=5))
def test_compose_restricted_constructor_witnesses(values):
    spec = ObjectSpec("Patch", "compose", tags={"empty": (), "patch": (("value", "int"),)})
    lib = library()
    lib.write(Definition("Patch", "object", "invented", 1, (), spec, None))
    lib.check("Patch")
    lib.make_callable("Patch", [(0,)])
    evidence = lib.verify("Patch", request(*values)).evidence
    assert evidence.checks == ("finite_values",)
    assert evidence.scope["untested_tags"] == []


@settings(deadline=None)
@given(st.lists(st.integers(min_value=-5, max_value=5), min_size=1, max_size=5)
       .filter(lambda values: any(value >= 0 for value in values) and any(value < 0 for value in values)))
def test_compose_accepts_some_bottom_combinations_when_a_witness_succeeds(values):
    class RestrictedLibrary(Library):
        def run(self, name, args, *additional, **options):
            if name == "Patch.patch" and args[0] < 0:
                return Run(Bottom("invalid"), 1, 0, None)
            return super().run(name, args, *additional, **options)

    spec = ObjectSpec("Patch", "compose", tags={"empty": (), "patch": (("value", "int"),)})
    base = library()
    lib = RestrictedLibrary(base.world, base.atoms)
    lib.write(Definition("Patch", "object", "invented", 1, (), spec, None))
    lib.check("Patch")
    lib.make_callable("Patch", [(0,)])
    assert lib.verify("Patch", request(*values)).evidence.checks == ("finite_values",)
    lib.replace("Patch", Definition("Patch", "object", "invented", 1, (), spec, None))
    lib.check("Patch")
    lib.make_callable("Patch", [(0,)])
    with pytest.raises(PipelineError, match="no successful witness"):
        lib.verify("Patch", request(*[value for value in values if value < 0]))


def test_layer0_host_valid_rule_runs_at_edges():
    from opulse.atoms import kernel as k
    from opulse.atoms import nodes as nn
    from opulse.atoms.library import Library as Lib
    from opulse.atoms.spec import Definition as D
    from opulse.atoms.spec import Edge as E
    from opulse.atoms.spec import ObjectSpec as O
    from opulse.atoms.spec import OperationSpec as Op
    from opulse.atoms.world import WorldDecl as W

    word = O("word", "refine", base="str", valid={"host": "builtins:bool", "digest": "0" * 64})
    world = W("words", 1, "atoms-v2", {}, {}, (word,), (), {"nodes": list(nn.NODE_NAMES), "recursion": "fuel"}, {}, {})
    lib = Lib(world, [k.Atom("length", 1, len)])
    spec = Op("size", "transform", (E("word"),), E("int"), "length", extra={"input_names": ["w"]})
    lib.write(D("size", "operation", "invented", 1, ("length",), spec, nn.Call("length", (nn.Var("w"),))))
    lib.check("size")
    lib.make_callable("size", [("abc",)])
    assert lib.run("size", ("abc",)).outcome.value == 3
