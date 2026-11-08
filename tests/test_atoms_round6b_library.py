"""Round-six library evidence and entry regressions (spec sections 4, 8, 9, 11)."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_atoms_library import definition, fixture, ready

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import (
    BridgeSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.world import WorldDecl


def world(name="edge", operations=(), objects=(), dialect="atoms-v2", params=None):
    return WorldDecl(name, 1, dialect, params or {}, {}, tuple(objects), tuple(operations),
                     {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {},
                     open_kinds=("operation", "object", "bridge"))


def test_checked_scope_does_not_adopt_caller_bounds():
    lib = fixture()
    ready(lib, definition("f", n.Call("succ", (n.Var("arg0"),)), ("succ",), 1, ("arg0",)), ((0,),))
    lib.verify("f", VerifyRequest("exhaustive", ((0,),),
                                  {"domain": "all integers", "size": 1, "checked": {"size": 999}},
                                  reference=lambda value: value + 1))
    scope = lib.promote("f", Contract("checked only at zero")).evidence.scope
    assert scope["domain"] == "all integers"
    assert scope["checked"]["size"] == 1
    assert scope["checked"]["bounds"] == {"0": {"min": 0, "max": 0}}
    assert len(scope["checked"]["sha256"]) == 64
    assert lib.derived_world().scopes()["f"]["checked"] == scope["checked"]
    stored = deepcopy(lib.to_dict())
    stored["definitions"][0]["evidence"]["scope"].pop("checked")
    restored = Library.from_dict(stored, lib.world, lib.atoms).get("f")
    assert restored.status == "callable"
    assert restored.evidence is None
    assert restored.contract is None


def test_self_and_transitive_references_cannot_verify():
    lib = fixture()
    ready(lib, definition("f", n.Lit(777), (), 1, ("arg0",)), ((0,),))
    for reference in ("f", "dependent"):
        if reference == "dependent":
            dependent = definition("dependent", n.Call("f", (n.Var("arg0"),)), ("f",), 2,
                                   ("arg0",))
            ready(lib, dependent, ((0,),))
        with pytest.raises(PipelineError, match="reference depends"):
            lib.verify("f", VerifyRequest("exhaustive", ((0,),), {"domain": "zero", "size": 1},
                                          reference=reference))
    obj = ObjectSpec("R", "refine", base="int", valid=n.Call("f", (n.Var("x"),)))
    lib.write(Definition("R", "object", "invented", 1, (), obj, None))
    with pytest.raises(PipelineError, match="reference depends"):
        lib.verify("f", VerifyRequest("exhaustive", ((0,),), {"domain": "zero", "size": 1},
                                      reference="R.make"))


def test_atom_reassignment_invalidates_live_evidence():
    lib = fixture()
    ready(lib, definition("f", n.Call("succ", (n.Var("arg0"),)), ("succ",), 1, ("arg0",)), ((0,),))
    lib.verify("f", VerifyRequest("exhaustive", ((0,),), {"domain": "zero", "size": 1},
                                  reference=lambda value: value + 1))
    lib.promote("f", Contract("successor"))
    lib.atoms = tuple(replace(atom, fn=lambda value: value + 2) if atom.name == "succ" else atom
                      for atom in lib.atoms)
    assert lib.get("f").status == "callable"
    assert not lib.derived_world().promoted


def test_bridge_attached_world_change_invalidates_live_and_reloaded():
    from opulse.atoms.bridges import bridge_defn

    source_op = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "inc")
    target_op = OperationSpec("plus", "transform", (Edge("int"),), Edge("int"), "plus")
    source = Library(world("source", (source_op,)), (kernel.Atom("inc", 1, lambda value: value + 1),))
    target = Library(world("target", (target_op,)), (kernel.Atom("plus", 1, lambda value: value + 1),))
    source.attach_world("target@1", target)
    spec = BridgeSpec("transfer", "source@1:int", "target@1:int", n.Var("x"), None,
                      (("inc", "plus"),))
    source.write(Definition("transfer", "bridge", "invented", 1, (), spec, bridge_defn(spec).body))
    source.check("transfer")
    source.make_callable("transfer", ((0,),))
    source.verify("transfer", VerifyRequest("bounded", ((0,), (1,)),
                                             {"domain": "bound <= 1", "size": 2}))
    source.promote("transfer", Contract("commutes"))
    stored = source.to_dict()
    assert "target@1" in source.get("transfer").evidence.scope["attached"]
    target.atoms = (kernel.Atom("plus", 1, lambda value: value + 2),)
    assert source.get("transfer").status == "callable"
    assert not source.derived_world().promoted
    loaded = Library.from_dict(stored, source.world, source.atoms, {"target@1": target})
    assert loaded.get("transfer").status == "callable"
    target.atoms = (kernel.Atom("plus", 1, lambda value: value + 1),)
    target.world = replace(target.world, operations=(replace(target_op, rule="changed"),))
    reloaded = Library.from_dict(stored, source.world, source.atoms, {"target@1": target})
    assert reloaded.get("transfer").evidence is None


def _invented_transform(lib, name, body, depends_on):
    spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"), name,
                         extra={"input_names": ["x"]})
    layer = 1 + max((lib.get(dependency).layer for dependency in depends_on), default=0)
    lib.write(Definition(name, "operation", "invented", layer, depends_on, spec, body))
    lib.check(name)
    lib.make_callable(name, ((0,), (1,)))


def _promoted_definition_bridge(transitive=False):
    from opulse.atoms.bridges import bridge_defn

    source_op = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "inc")
    target_op = OperationSpec("plus", "transform", (Edge("int"),), Edge("int"), "plus")
    target_add = OperationSpec("add", "transform", (Edge("int"), Edge("int")), Edge("int"), "add")
    source = Library(world("source", (source_op,)), (kernel.Atom("inc", 1, lambda value: value + 1),))
    target = Library(world("target", (target_op, target_add)),
                     (kernel.Atom("plus", 1, lambda value: value + 1),
                      kernel.Atom("add", 2, lambda left, right: left + right)))
    if transitive:
        _invented_transform(target, "helper", n.Call("plus", (n.Var("x"),)), ("plus",))
    _invented_transform(target, "double", n.Call("helper" if transitive else "plus", (n.Var("x"),)),
                        ("helper" if transitive else "plus",))
    source.attach_world("target@1", target)
    spec = BridgeSpec("transfer", "source@1:int", "target@1:int",
                      n.Call("double", (n.Var("x"),)), None, (("inc", "plus"),))
    source.write(Definition("transfer", "bridge", "invented", target.get("double").layer + 1,
                            ("double",), spec,
                            bridge_defn(spec).body))
    source.check("transfer")
    source.make_callable("transfer", ((0,), (1,)))
    source.verify("transfer", VerifyRequest("bounded", ((0,), (1,)),
                                            {"domain": "bound <= 1", "size": 2}))
    source.promote("transfer", Contract("commutes"))
    return source, target


def test_bridge_target_definition_rewrite_invalidates_live_and_reloaded():
    source, target = _promoted_definition_bridge()
    stored = source.to_dict()
    assert source.run("transfer", (3,)).outcome == Ok(4)
    old = target.get("double")
    target.replace("double", replace(old, body=n.Call("add", (n.Var("x"), n.Lit(100))),
                                    depends_on=("add",), status="written", evidence=None,
                                    contract=None))
    target.check("double")
    target.make_callable("double", ((0,), (1,)))
    assert source.run("transfer", (3,)).outcome == Ok(103)
    assert source.get("transfer").status == "callable"
    assert source.get("transfer").evidence is None
    assert not source.derived_world().promoted
    assert Library.from_dict(stored, source.world, source.atoms,
                             {"target@1": target}).get("transfer").status == "callable"


def test_bridge_unrelated_target_definition_change_keeps_promotion():
    source, target = _promoted_definition_bridge()
    _invented_transform(target, "unrelated", n.Lit(7), ())
    assert source.get("transfer").status == "promoted"
    old = target.get("unrelated")
    target.replace("unrelated", replace(old, body=n.Lit(8), status="written"))
    assert source.get("transfer").status == "promoted"


def test_bridge_transitive_target_definition_change_invalidates():
    source, target = _promoted_definition_bridge(transitive=True)
    old = target.get("helper")
    target.replace("helper", replace(old, body=n.Lit(100), status="written"))
    assert source.get("transfer").status == "callable"
    assert not source.derived_world().promoted


def test_bridge_target_definition_discard_invalidates():
    source, target = _promoted_definition_bridge()
    old = target.get("double")
    target.replace("double", replace(old, body=n.Lit(7), status="written"))
    target.discard("double")
    assert source.get("transfer").status == "callable"


def test_bridge_target_interface_definition_change_invalidates():
    from opulse.atoms.bridges import bridge_defn

    source_op = OperationSpec("inc", "transform", (Edge("int"),), Edge("int"), "inc")
    target_op = OperationSpec("plus", "transform", (Edge("int"),), Edge("int"), "plus")
    step_op = OperationSpec("step", "transform", (Edge("int"),), Edge("int"), "step")
    source = Library(world("source", (source_op,)), (kernel.Atom("inc", 1, lambda value: value + 1),))
    target = Library(world("target", (step_op,)), (kernel.Atom("step", 1, lambda value: value + 1),))
    target.write(Definition("plus", "operation", "invented", 1, ("step",), target_op,
                            n.Call("step", (n.Var("arg0"),))))
    target.check("plus")
    target.make_callable("plus", ((0,), (1,)))
    source.attach_world("target@1", target)
    spec = BridgeSpec("transfer", "source@1:int", "target@1:int", n.Var("x"), None,
                      (("inc", "plus"),))
    source.write(Definition("transfer", "bridge", "invented", 1, (), spec, bridge_defn(spec).body))
    source.check("transfer")
    source.make_callable("transfer", ((0,),))
    source.verify("transfer", VerifyRequest("bounded", ((0,), (1,)),
                                            {"domain": "bound <= 1", "size": 2}))
    source.promote("transfer", Contract("commutes"))
    old = target.get("plus")
    target.replace("plus", replace(old, body=n.Lit(100), status="written"))
    assert source.get("transfer").status == "callable"


def test_bridge_source_definition_is_covered_by_deps_hash():
    from opulse.atoms.bridges import bridge_defn

    source, target = _promoted_definition_bridge()
    source_op = OperationSpec("allowed", "decide", (Edge("int"),), Edge("bool"), "allowed",
                              extra={"input_names": ["x"]})
    source.write(Definition("allowed", "operation", "invented", 1, (), source_op, n.Lit(True)))
    source.check("allowed")
    source.make_callable("allowed", ((0,), (1,)))
    spec = BridgeSpec("guarded", "source@1:int", "target@1:int",
                      n.Call("double", (n.Var("x"),)), n.Call("allowed", (n.Var("x"),)),
                      (("inc", "plus"),))
    source.write(Definition("guarded", "bridge", "invented", target.get("double").layer + 1,
                            ("allowed", "double"), spec, bridge_defn(spec).body))
    source.check("guarded")
    source.make_callable("guarded", ((0,), (1,)))
    source.verify("guarded", VerifyRequest("bounded", ((0,), (1,)),
                                           {"domain": "bound <= 1", "size": 2}))
    source.promote("guarded", Contract("commutes"))
    before = source.deps_hash("guarded")
    old = source.get("allowed")
    source.replace("allowed", replace(old, body=n.Lit(False), status="written"))
    assert source.deps_hash("guarded") != before
    assert source.get("guarded").status == "callable"


def test_operation_verifier_copies_mutable_arguments():
    operation = OperationSpec("mutator", "transform", (Edge("any"),), Edge("int"), "mutator")

    def mutator(values):
        values.append(5)
        return len(values)

    lib = Library(world(operations=(operation,)), (kernel.Atom("mutator", 1, mutator),))
    spec = OperationSpec("f", "transform", (Edge("any"),), Edge("int"), "mutator",
                         extra={"input_names": ["values"]})
    lib.write(Definition("f", "operation", "invented", 1, ("mutator",), spec,
                         n.Call("mutator", (n.Var("values"),))))
    lib.check("f")
    lib.make_callable("f", (([],),))
    data = []

    def reference(values):
        assert values == []
        return 1

    lib.verify("f", VerifyRequest("exhaustive", ((data,),), {"domain": "one list", "size": 1},
                                  reference=reference))
    assert data == []


def test_unfold_equivalence_checks_steps(monkeypatch):
    lib = fixture()
    ready(lib, definition("f", n.Call("succ", (n.Var("arg0"),)), ("succ",), 1, ("arg0",)), ((0,),))
    monkeypatch.setattr(kernel, "inline", lambda *_: n.Lit(1))
    with pytest.raises(PipelineError, match="unfold_equivalence counterexample"):
        lib.verify("f", VerifyRequest("exhaustive", ((0,),), {"domain": "zero", "size": 1},
                                      reference=lambda value: value + 1))


@pytest.mark.parametrize("rule,input_value,expected", [
    ("saturate(0,10)", 42, Ok(10)),
    ("saturate(0,10)", -7, Ok(0)),
])
def test_invented_input_and_output_edges_inline(rule, input_value, expected):
    lib = Library(world(), ())
    spec = OperationSpec("clamped", "transform", (Edge("int", rule),), Edge("int", rule),
                         "identity", extra={"input_names": ["value"]})
    lib.write(Definition("clamped", "operation", "invented", 1, (), spec, n.Var("value")))
    lib.check("clamped")
    lib.make_callable("clamped", ((input_value,),))
    run = lib.run("clamped", (input_value,))
    unfolded = kernel.inline(n.Call("clamped", (n.Lit(input_value),)), lib.scope())
    inline_run = kernel.evaluate(unfolded, scope=lib.scope())
    assert run.outcome == expected
    assert run.steps == 2
    assert (run.outcome, run.steps) == (inline_run.outcome, inline_run.steps)


def test_given_explicit_saturate_edges():
    spec = OperationSpec("identity", "transform", (Edge("int", "saturate(0, 10)"),),
                         Edge("int", "saturate(0, 10)"), "identity")
    lib = Library(world(operations=(spec,)), (kernel.Atom("identity", 1, lambda value: value),))
    assert lib.run("identity", (42,)).outcome == Ok(10)
    assert lib.run("identity", (-7,)).outcome == Ok(0)


def test_normalize_input_and_output_canonicalize_before_validity():
    valid = n.Call("between", (n.Var("x"),))
    canon = n.Call("mod12", (n.Var("x"),))
    refined = ObjectSpec("hour", "refine", base="int", valid=valid, canon=canon)
    operations = (OperationSpec("between", "decide", (Edge("int"),), Edge("bool"), "between"),
                  OperationSpec("mod12", "transform", (Edge("int"),), Edge("int"), "mod12"))
    lib = Library(world(operations=operations, objects=(refined,)),
                  (kernel.Atom("between", 1, lambda value: 0 <= value < 12),
                   kernel.Atom("mod12", 1, lambda value: value % 12)))
    spec = OperationSpec("hourly", "transform", (Edge("hour", "normalize"),),
                         Edge("hour", "normalize"), "normalize", extra={"input_names": ["value"]})
    lib.write(Definition("hourly", "operation", "invented", 1, (), spec, n.Lit(13)))
    lib.check("hourly")
    lib.make_callable("hourly", ((-4,),))
    assert lib.run("hourly", (-4,)).outcome == Ok(Card("hour", "val", (1,)))


def test_bottom_input_rejects_invalid_representation():
    refined = ObjectSpec("positive", "refine", base="int", valid=n.Call("positive_check", (n.Var("x"),)))
    check = OperationSpec("positive_check", "decide", (Edge("int"),), Edge("bool"), "positive")
    lib = Library(world(objects=(refined,), operations=(check,)),
                  (kernel.Atom("positive_check", 1, lambda value: value > 0),))
    spec = OperationSpec("test", "transform", (Edge("positive", "bottom"),), Edge("int"),
                         "one", extra={"input_names": ["value"]})
    lib.write(Definition("test", "operation", "invented", 1, (), spec, n.Lit(1)))
    lib.check("test")
    lib.make_callable("test", ((1,),))
    assert lib.run("test", (-1,)).outcome == Bottom("invalid")
    assert lib.run("test", (Card("positive", "val", (-1,)),)).outcome == Bottom("invalid")


@pytest.mark.parametrize("value", [8, Card("Residue", "val", (8,))])
def test_bottom_edge_keeps_valid_noncanonical_values(value):
    refined = ObjectSpec("Residue", "refine", base="int", valid=n.Call("positive", (n.Var("x"),)),
                         canon=n.Call("reduce", (n.Var("x"),)))
    operations = (OperationSpec("positive", "decide", (Edge("int"),), Edge("bool"), "positive"),
                  OperationSpec("reduce", "transform", (Edge("int"),), Edge("int"), "reduce"))
    lib = Library(world(objects=(refined,), operations=operations),
                  (kernel.Atom("positive", 1, lambda number: number > 0),
                   kernel.Atom("reduce", 1, lambda number: number % 3)))
    spec = OperationSpec("identity", "transform", (Edge("Residue", "bottom"),),
                         Edge("Residue", "bottom"), "identity", extra={"input_names": ["item"]})
    lib.write(Definition("identity", "operation", "invented", 1, (), spec, n.Var("item")))
    lib.check("identity")
    lib.make_callable("identity", ((value,),))
    expected = Ok(Card("Residue", "val", (8,)))
    direct = lib.run("identity", (value,))
    unfolded = kernel.evaluate(kernel.inline(n.Call("identity", (n.Lit(value),)), lib.scope()),
                               scope=lib.scope())
    assert (direct.outcome, direct.steps) == (unfolded.outcome, unfolded.steps)
    assert direct.outcome == expected
    assert lib.run("identity", (Card("Residue", "val", (-8,)),)).outcome == Bottom("invalid")


def test_refined_saturate_output_enters_make():
    refined = ObjectSpec("level", "refine", base="int", valid=n.Lit(True))
    lib = Library(world(objects=(refined,)), ())
    spec = OperationSpec("clip", "transform", (), Edge("level", "saturate(0, 10)"), "clip")
    lib.write(Definition("clip", "operation", "invented", 1, (), spec, n.Lit(42)))
    lib.check("clip")
    lib.make_callable("clip", ((),))
    assert lib.run("clip", ()).outcome == Ok(Card("level", "val", (10,)))


def test_legacy_fold_output_and_nonlegacy_rejection():
    spec = OperationSpec("folded", "transform", (), Edge("int", "fold(legacy)"), "folded")
    lib = Library(world(dialect="legacy-v1", params={"semantics": {"bound": 10}}), ())
    lib.write(Definition("folded", "operation", "invented", 1, (), spec, n.Lit(13)))
    lib.check("folded")
    lib.make_callable("folded", ((),))
    assert lib.run("folded", ()).outcome == Ok(3)
    modern = Library(world(), ())
    modern.write(Definition("folded", "operation", "invented", 1, (), spec, n.Lit(13)))
    with pytest.raises(PipelineError, match="fold entry requires legacy-v1"):
        modern.check("folded")


def test_run_hashes_world_once(monkeypatch):
    lib = fixture()
    original = WorldDecl.world_hash
    calls = []

    def counted(declaration):
        calls.append(declaration)
        return original(declaration)

    monkeypatch.setattr(WorldDecl, "world_hash", counted)
    assert lib.run("succ", (1,)).outcome == Ok(2)
    assert calls == [lib._world]
    assert lib.run("succ", (2,)).outcome == Ok(3)
    assert calls == [lib._world, lib._world]
