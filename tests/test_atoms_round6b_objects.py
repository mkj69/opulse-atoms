"""Object checking and promotion regressions (spec sections 4 and 9)."""

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom, Run
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import Contract, Definition, ObjectSpec
from opulse.atoms.values import Bottom, Card
from opulse.atoms.world import WorldDecl


def library(objects=(), operations=(), atoms=(), opened=("Var", "Call", "Lit"), recursion="none"):
    world = WorldDecl("object_review", 1, "atoms-v2", {}, {}, tuple(objects),
                      tuple(operations), {"nodes": list(opened), "recursion": recursion}, {}, {})
    return Library(world, atoms)


def request(domain, method="exhaustive", extra=None, seed=None):
    return VerifyRequest(method, tuple(domain), {"domain": "finite test domain", "size": len(domain)},
                         seed=seed, extra=extra or {})


@pytest.mark.parametrize("valid,canon,depends,opened,expected", [
    (n.Case(((n.Test(n.Lit(True)), n.Lit(True)),), n.Lit(False)), None, (),
     ("Var", "Call", "Lit"), "node Case is not opened"),
    (n.Call("undefined", (n.Var("x"),)), None, ("undefined",),
     ("Var", "Call", "Lit"), "unresolved call: undefined"),
    (n.Lit(True), n.Call("undefined", (n.Var("x"),)), ("undefined",),
     ("Var", "Call", "Lit"), "unresolved call: undefined"),
])
def test_refinement_nodes_get_general_checks(valid, canon, depends, opened, expected):
    atoms = (Atom("valid_int", 1, lambda value: value >= 0),)
    lib = library(atoms=atoms, opened=opened)
    spec = ObjectSpec("Refined", "refine", base="int", valid=valid, canon=canon)
    lib.write(Definition("Refined", "object", "invented", 1, depends, spec, None))
    with pytest.raises(ValueError, match=expected):
        lib.check("Refined")


def test_refinement_recursion_requires_terminating_opened_sublanguage():
    valid = n.Rec("walk", ("x",), n.Lit(True), (n.Var("x"),), "fuel")
    spec = ObjectSpec("Refined", "refine", base="int", valid=valid)
    lib = library(opened=("Var", "Call", "Lit", "Rec"), recursion="fuel")
    lib.write(Definition("Refined", "object", "invented", 1, (), spec, None))
    with pytest.raises(ValueError, match="valid Rec needs a measure node"):
        lib.check("Refined")


def test_same_as_requires_abstraction_or_only_sampled_evidence():
    given = ObjectSpec("Int", "given")
    spec = ObjectSpec("Refined", "refine", base="int", valid=n.Lit(True),
                      extra={"same_as": "Int"})
    lib = library(objects=(given,))
    lib.write(Definition("Refined", "object", "invented", 1, (), spec, None))
    lib.check("Refined")
    lib.make_callable("Refined", [(1,)])
    with pytest.raises(ValueError, match="same_as requires abs_commutes"):
        lib.verify("Refined", request(((1,),), method="bounded"))
    with pytest.raises(ValueError, match="abs_commutes needs at least one interface pair"):
        lib.verify("Refined", request(((1,),), extra={"abs": lambda item: item.fields[0]}))
    invalid = ObjectSpec("Filtered", "refine", base="int", valid=n.Lit(False))
    filtered_lib = library()
    filtered_lib.write(Definition("Filtered", "object", "invented", 1, (), invalid, None))
    filtered_lib.check("Filtered")
    filtered_lib.make_callable("Filtered", [(1,)])
    with pytest.raises(ValueError, match="abs_commutes needs at least one valid input"):
        filtered_lib.verify("Filtered", request(((1,),), extra={
            "abs": lambda item: item.fields[0], "interface_pairs": (("Filtered.base", "identity"),)}))

    lib.atoms += (Atom("increment_refined", 1, lambda value: Card("Refined", "val", (value.fields[0] + 1,))),
                  Atom("increment_int", 1, lambda value: value + 1))
    verification = request(((1,),), method="bounded", extra={
        "abs": lambda item: item.fields[0],
        "interface_ops": {"increment_refined": (0,)},
        "interface_pairs": (("increment_refined", "increment_int"),),
    })
    evidence = lib.verify("Refined", verification).evidence
    assert {"same_as", "abs_commutes"} <= set(evidence.checks)
    assert lib.promote("Refined", Contract("same interface on the bounded domain")).status == "promoted"


def test_refinement_without_same_as_can_promote_without_abstraction():
    spec = ObjectSpec("Positive", "refine", base="int", valid=n.Lit(True))
    lib = library()
    lib.write(Definition("Positive", "object", "invented", 1, (), spec, None))
    lib.check("Positive")
    lib.make_callable("Positive", [(1,)])
    evidence = lib.verify("Positive", request(((1,),))).evidence
    assert "abs_commutes" not in evidence.checks
    assert lib.promote("Positive", Contract("positive representation")).status == "promoted"


def test_compose_records_finite_values_for_promotion():
    spec = ObjectSpec("List", "compose", tags={"nil": (), "cons": (("head", "int"),
                                                                  ("tail", "List"))})
    lib = library()
    lib.write(Definition("List", "object", "invented", 1, (), spec, None))
    lib.check("List")
    lib.make_callable("List", [(0,)])
    partial_definition = lib.verify("List", request(((Card("List", "nil"),),)))
    partial = partial_definition.evidence
    assert partial_definition.status == "verified"
    assert partial.scope["untested_tags"] == ["cons"]
    assert partial.checks == ("finite_values_partial",)
    with pytest.raises(PipelineError, match="untested tags.*cons"):
        lib.promote("List", Contract("finite list constructors"))
    lib.replace("List", Definition("List", "object", "invented", 1, (), spec, None))
    lib.check("List")
    lib.make_callable("List", [(0,)])
    evidence = lib.verify("List", request(((0,),), extra={"witnesses": (1,)})).evidence
    assert evidence.scope["untested_tags"] == []
    assert evidence.checks == ("finite_values",)
    assert lib.promote("List", Contract("finite list constructors")).status == "promoted"


def test_compose_broken_recursive_constructor_is_checked_with_witnesses():
    class BrokenListLibrary(Library):
        def run(self, name, args, *additional, **options):
            if name == "List.cons":
                return Run(Bottom("broken_cons"), 1, 0, None)
            return super().run(name, args, *additional, **options)

    spec = ObjectSpec("List", "compose", tags={"nil": (), "cons": (("head", "int"),
                                                                  ("tail", "List"))})
    base = library()
    lib = BrokenListLibrary(base.world, base.atoms)
    lib.write(Definition("List", "object", "invented", 1, (), spec, None))
    lib.check("List")
    lib.make_callable("List", [(0,)])
    partial = lib.verify("List", request(((Card("List", "nil"),),)))
    assert partial.evidence.scope["untested_tags"] == ["cons"]
    with pytest.raises(PipelineError, match="untested tags.*cons"):
        lib.promote("List", Contract("broken list constructors"))
    lib.replace("List", Definition("List", "object", "invented", 1, (), spec, None))
    lib.check("List")
    lib.make_callable("List", [(0,)])
    with pytest.raises(PipelineError, match="finite_values constructor cons has no successful witness"):
        lib.verify("List", request(((0,),), extra={"witnesses": (1,)}))
    assert lib.get("List").status == "callable"


def test_compose_same_as_requires_checked_interface_pair():
    spec = ObjectSpec("Box", "compose", tags={"box": (("value", "int"),)},
                      extra={"same_as": "int"})
    lib = library(atoms=(Atom("identity", 1, lambda value: value),))
    lib.write(Definition("Box", "object", "invented", 1, (), spec, None))
    lib.check("Box")
    lib.make_callable("Box", [(2,)])
    with pytest.raises(ValueError, match="same_as requires abs_commutes"):
        lib.verify("Box", request(((2,),)))
    with pytest.raises(ValueError, match="abs_commutes needs at least one interface pair"):
        lib.verify("Box", request(((2,),), extra={"abs": lambda value: value.fields[0]}))
    with pytest.raises(ValueError, match="abs_commutes Box.value/identity"):
        lib.verify("Box", request(((2,),), extra={
            "abs": lambda value: value.fields[0] + 1,
            "interface_ops": {"Box.value": (0,)},
            "interface_pairs": (("Box.value", "identity"),),
        }))
    evidence = lib.verify("Box", request(((2,),), extra={
        "abs": lambda value: value.fields[0],
        "interface_ops": {"Box.value": (0,)},
        "interface_pairs": (("Box.value", "identity"),),
    })).evidence
    assert {"finite_values", "same_as", "abs_commutes"} <= set(evidence.checks)
    assert lib.promote("Box", Contract("box projects to int")).status == "promoted"


def test_same_as_sampled_evidence_cannot_promote():
    spec = ObjectSpec("Box", "compose", tags={"box": (("value", "int"),)},
                      extra={"same_as": "int"})
    lib = library()
    lib.write(Definition("Box", "object", "invented", 1, (), spec, None))
    lib.check("Box")
    lib.make_callable("Box", [(2,)])
    evidence = lib.verify("Box", request(((2,),), method="sampled", seed=7, extra={
        "interface_ops": {"Box.value": (0,)}, "reference_ops": {"Box.value": "Box.value"},
        "count": 4, "depth": 1,
    })).evidence
    assert {"finite_values", "same_as", "sampled"} <= set(evidence.checks)
    with pytest.raises(ValueError, match="sampled evidence cannot be promoted"):
        lib.promote("Box", Contract("box sampling"))
