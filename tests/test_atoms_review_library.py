"""Regressions for library and observation review findings (spec sections 7-12)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_atoms_library import definition, exhaustive, fixture, ready

from opulse.atoms import kernel, objects
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, PipelineError, VerifyRequest, atoms_digest
from opulse.atoms.observations import judge, observe
from opulse.atoms.spec import Contract, Definition, Edge, ObservationSpec, OperationSpec
from opulse.atoms.values import Card, Ok
from opulse.atoms.world import WorldDecl


def verified_operation():
    lib = fixture()
    ready(lib, definition("f", n.Call("succ", (n.Var("arg0"),)), ("succ",), 1, ("arg0",)), ((0,),))
    lib.verify("f", replace(exhaustive(((0,),), "zero"), reference=lambda value: value + 1))
    lib.promote("f", Contract("successor"))
    return lib


def counter_library():
    odd, even = (Card("counter", "value", (value,)) for value in (1, 2))
    operation = OperationSpec("parity", "decide", (Edge("counter"),), Edge("int"), "parity")
    world = WorldDecl("counter", 1, "atoms-v2", {}, {}, (), (operation,),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"},
                      {"truth": "counter", "probes": [{"name": "parity"}],
                       "capabilities": {"learner": {"probes": "all"}}}, {})
    lib = Library(world, [kernel.Atom("parity", 1, lambda state: state.fields[0] % 2,
                                      kind="observation")])
    body = n.Lit(1)
    lib.write(Definition("lie", "observation", "invented", 1, (),
                         ObservationSpec("lie", ("parity",), body), body))
    lib.check("lie")
    lib.make_callable("lie", ((odd,),))
    return lib, odd, even


def test_observation_checks_every_claimed_state():
    lib, odd, even = counter_library()
    request = VerifyRequest("bounded", ((odd,), (even,)), {"domain": "counter bound <=2", "size": 2},
                            reference=lambda state: state.fields[0] % 2, extra={"states": [odd]})
    with pytest.raises(PipelineError, match="reference mismatch"):
        lib.verify("lie", request)


def test_observation_without_reference_is_promoted_only_on_its_own_unfolding():
    # Board decision 11-05 (gen): no independent reference -> the claim is the observation's own
    # unfolding; the evidence says so (reference: none) and never invents a reference check.
    lib, odd, _ = counter_library()
    request = VerifyRequest("bounded", ((odd,),), {"domain": "counter bound <=1", "size": 1})
    evidence = lib.verify("lie", request).evidence
    assert "reference" not in evidence.checks and "unfold_equivalence" in evidence.checks
    assert evidence.scope["reference"] == "none"
    assert lib.promote("lie", Contract("parity")).status == "promoted"


def test_empty_verification_domain_is_rejected():
    lib = fixture()
    ready(lib, definition("f", n.Call("succ", (n.Var("arg0"),)), ("succ",), 1, ("arg0",)), ((0,),))
    with pytest.raises(PipelineError, match="scope"):
        lib.verify("f", VerifyRequest("exhaustive", (), {"domain": "empty", "size": 0}))


def test_missing_content_hash_drops_evidence():
    lib = verified_operation()
    data = lib.to_dict()
    data["definitions"][0]["body"] = n.to_json(n.Call("succ", (n.Lit(40),)))
    data["definitions"][0]["evidence"]["content_hash"] = ""
    loaded = Library.from_dict(data, lib.world, lib.atoms)
    assert loaded.get("f").status == "callable"
    assert not loaded.derived_world().promoted


def test_returned_records_cannot_mutate_library():
    lib = verified_operation()
    lib.get("f").spec.extra["input_names"] = ["corrupted"]
    lib.definitions["f"].evidence.scope["size"] = 123
    assert lib.get("f").spec.extra.get("input_names") != ["corrupted"]
    assert lib.get("f").evidence.scope["size"] == 1


def test_atom_implementation_digest_invalidates_evidence():
    lib = verified_operation()
    atoms = [replace(atom, fn=lambda value: value + 10) if atom.name == "succ" else atom
             for atom in lib.atoms]
    assert atoms_digest(atoms) != atoms_digest(lib.atoms)
    loaded = Library.from_dict(lib.to_dict(), lib.world, atoms)
    assert loaded.get("f").status == "callable"


def test_reload_rechecks_layers():
    # A declared layer may sit above what the dependencies require (design rows, round 7), never below.
    lib = verified_operation()
    data = lib.to_dict()
    data["definitions"][0]["layer"] = 999
    assert Library.from_dict(data, lib.world, lib.atoms).get("f").layer == 999
    data["definitions"][0]["depends_on"] = ["f"]  # a self-only dependency set cannot justify layer checks away
    with pytest.raises(PipelineError):
        Library.from_dict(data, lib.world, lib.atoms)


def test_world_hash_preserves_nested_semantic_keys():
    world = WorldDecl("w", 1, "atoms-v2", {"config": {"source": "v1"}}, {}, (), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    previous = world.world_hash()
    world.params["config"]["source"] = "v2"
    assert world.world_hash() != previous


@settings(deadline=None)
@given(st.text(min_size=1), st.text(min_size=1).filter(lambda value: value != "v1"))
def test_nested_source_is_semantic_in_world_and_definition(key, replacement):
    world = WorldDecl("w", 1, "atoms-v2", {"codec": {key: {"source": "v1"}}}, {}, (), (),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {})
    changed = replace(world, params={"codec": {key: {"source": replacement}}})
    assert world.world_hash() != changed.world_hash()
    spec = OperationSpec("f", "transform", (), Edge("int"), "constant",
                         extra={"codec": {"source": "v1"}})
    original = Definition("f", "operation", "invented", 1, (), spec, n.Lit(1))
    modified = replace(original, spec=replace(spec, extra={"codec": {"source": replacement}}))
    assert original.content_hash() != modified.content_hash()


def test_declared_output_sort_is_checked():
    lib = fixture()
    lib.write(definition("wrong_type", n.Lit("text"), (), 1, ("arg0",)))
    with pytest.raises(PipelineError, match="output: expected int, got str"):
        lib.check("wrong_type")


def test_load_rejects_closed_kind():
    lib = verified_operation()
    with pytest.raises(PipelineError, match="closed"):
        Library.from_dict(lib.to_dict(), replace(lib.world, open_kinds=()), lib.atoms)


def test_judge_uses_typed_equality():
    assert not judge("full_state", True, 1)
    truth = SimpleNamespace(value=Card("pair", "item", (True,)))
    answer = SimpleNamespace(value=Card("pair", "item", (1,)))
    assert not judge({"fields": ["value"]}, truth, answer)
    assert not judge(lambda state: state.value, truth, answer)


def test_memory_dependency_folds_over_same_history():
    class ObservationLibrary:
        dialect = "atoms-v2"
        world = SimpleNamespace(observation={"truth": "truth", "probes": [{"name": "p"}]},
                                operations=())

        def __init__(self):
            inner = ObservationSpec("inner", ("p",), n.Var("memory"),
                                    {"sort": "int", "init": n.Lit(0), "step": n.Var("p")})
            self.definitions = {"inner": Definition("inner", "observation", "invented", 1, (),
                                                     inner, inner.body)}

        def scope(self):
            return kernel.DictScope([kernel.Atom("p", 1, lambda state: state, kind="observation")],
                                    [kernel.Defn("inner", (), n.Var("memory"), kind="observation")])

        def get(self, name):
            return self.definitions[name]

    lib = ObservationLibrary()
    body = n.Call("inner", (n.Var("s"),))
    outer_spec = ObservationSpec("outer", ("p",), body)
    outer = Definition("outer", "observation", "invented", 2, ("inner",), outer_spec, body)
    assert observe(outer, lib, (1, 2, 3)) == [Ok(1), Ok(2), Ok(3)]


def test_run_refuses_sealed_private_names(monkeypatch):
    lib = fixture()
    monkeypatch.setattr(objects, "sealed_private_names", lambda library: {"succ"}, raising=False)
    with pytest.raises(PipelineError, match="private"):
        lib.run("succ", (1,))
