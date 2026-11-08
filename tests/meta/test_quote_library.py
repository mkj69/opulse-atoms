"""Real library snapshots and Merkle dependency identity (meta spec 3.3, 3.2 and 8.I4)."""

import hashlib
from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library, PipelineError, exhaustive
from opulse.atoms.spec import Contract, Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl
from opulse.meta.code import code_hash, decode, quote_from_library
from opulse.meta.identity import Ledger, LedgerError


def library(atom_version="given-v1"):
    ops = (
        ("add", ("int", "int"), "int", lambda left, right: left + right, "combine"),
        ("sub", ("int", "int"), "int", lambda left, right: left - right, "combine"),
        ("is_zero", ("int",), "bool", lambda value: value == 0, "decide"),
    )
    specs = tuple(OperationSpec(name, role, tuple(Edge(sort) for sort in inputs), Edge(output), name,
                                impl={"host": "opulse.meta.identity:atom", "digest": hashlib.sha256(
                                    (atom_version if name == "add" else name).encode()).hexdigest()})
                  for name, inputs, output, _, role in ops)
    world = WorldDecl("meta_identity_test", 1, "atoms-v2", {}, {}, (ObjectSpec("int", "given"),),
                      specs, {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                              "recursion": "fuel"}, {}, {})
    atoms = [kernel.Atom(name, len(inputs), implementation) for name, inputs, _, implementation, _ in ops]
    return Library(world, atoms)


def definition(name, body, depends_on, layer=1, param="x"):
    spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"), name,
                         extra={"input_names": [param]})
    return Definition(name, "operation", "invented", layer, tuple(depends_on), spec, body)


def double(name="double", param="x", atom="add"):
    return definition(name, n.Call(atom, (n.Var(param), n.Var(param))), (atom,), param=param)


def quad(dep="double", name="quad", param="x"):
    return definition(name, n.Call(dep, (n.Call(dep, (n.Var(param),)),)), (dep,), 2, param)


def ready(lib, defn):
    lib.write(defn)
    lib.check(defn.name)
    lib.make_callable(defn.name, ((2,),))


def verify_and_promote(lib, name, reference, contract):
    lib.verify(name, replace(exhaustive((range(3),), "integers 0..2"), reference=reference))
    lib.promote(name, Contract(contract))


def test_from_library_promotion_and_dependency_replacement():
    lib = library()
    ready(lib, double())
    verify_and_promote(lib, "double", lambda value: value * 2, "double")
    ready(lib, quad())
    verify_and_promote(lib, "quad", lambda value: value * 4, "quad")
    run = lib.run("quad", (2,), trace=True)
    assert run.outcome == Ok(8) and run.steps == 2 and run.jumps == 0
    assert run.trace.name is None and run.trace.kind == "root" and run.trace.steps == 2
    assert [child.name for child in run.trace.children] == ["quad"]
    assert run.trace.children[0].steps == 2
    assert [child.name for child in run.trace.children[0].children] == ["double", "double"]
    assert [child.children[0].name for child in run.trace.children[0].children] == ["add", "add"]
    world_hash = lib.world.world_hash()
    before = Ledger.from_library(lib)
    double_hash, quad_hash = before.resolve("double"), before.resolve("quad")
    assert before.record(double_hash, world_hash).status == "promoted"
    assert before.record(quad_hash, world_hash).evidence == (
        replace(lib.get("quad").evidence, deps_hash=before.record(quad_hash, world_hash).deps_hash),)
    assert before.record(quad_hash, world_hash).contract == lib.get("quad").contract
    assert decode(before.record(quad_hash, world_hash).code).main.body.fn == "#" + double_hash
    assert before.to_dict() == Ledger.from_dict(before.to_dict()).to_dict()

    changed_body = n.Call("sub", (n.Var("x"), n.Var("x")))
    with pytest.raises(PipelineError, match="immutable"):
        lib.replace("double", definition("double", changed_body, ("sub",)))
    new_version = lib.replace("double", definition("double", changed_body, ("sub",)),
                              force_new_version=True)
    assert new_version.name == "double.v2" and new_version.evidence is None
    assert lib.get("double").status == "promoted" and lib.get("double").contract == Contract("double")
    assert lib.get("quad").status == "promoted" and lib.get("quad").evidence is not None
    lib.check("double.v2")
    lib.make_callable("double.v2", ((2,),))
    after = Ledger.from_library(lib)
    assert after.resolve("double") == double_hash
    assert after.resolve("quad") == quad_hash
    assert after.record(quad_hash, world_hash) == before.record(quad_hash, world_hash)
    assert after.record(after.resolve("double.v2"), world_hash).evidence == ()
    with pytest.raises(LedgerError, match="exhaustive or bounded"):
        after.promote(after.resolve("double.v2"), world_hash, Contract("not reverified"))
    with pytest.raises(PipelineError, match="verified"):
        lib.promote("double.v2", Contract("not reverified"))

    before.add(after.record(after.resolve("double.v2"), world_hash).code, world_hash, "double")
    assert before.history == [("double", double_hash, after.resolve("double.v2"))]
    assert before.record(quad_hash, world_hash).status == "promoted"
    assert decode(before.record(quad_hash, world_hash).code).main.body.fn == "#" + double_hash
    with pytest.raises(LedgerError, match="immutable"):
        before.attach_evidence(quad_hash, world_hash, before.record(quad_hash, world_hash).evidence[0])


def test_renaming_dependency_and_parameters_preserves_quoted_hash():
    original = library()
    ready(original, double())
    ready(original, quad())
    changed_names = library()
    ready(changed_names, double("twice", "other"))
    ready(changed_names, quad("twice", "four_times", "number"))
    assert code_hash(quote_from_library(original, "double")) == code_hash(quote_from_library(changed_names, "twice"))
    assert code_hash(quote_from_library(original, "quad")) == code_hash(quote_from_library(changed_names, "four_times"))


def test_same_hash_alias_cannot_downgrade_promoted_record():
    lib = library()
    ready(lib, double())
    verify_and_promote(lib, "double", lambda value: value * 2, "twice input")
    ready(lib, double("alias", "other"))
    ledger = Ledger.from_library(lib)
    digest = ledger.resolve("double")
    assert ledger.resolve("alias") == digest
    record = ledger.record(digest, lib.world.world_hash())
    assert record.status == "promoted" and record.contract == Contract("twice input")
    assert record.evidence == (replace(lib.get("double").evidence, deps_hash=record.deps_hash),)


def test_fresh_libraries_stable_and_host_digest_changes_hash():
    first, second, foreign = library(), library(), library("given-v2")
    for lib in (first, second, foreign):
        ready(lib, double())
        ready(lib, quad())
    for name in ("double", "quad"):
        assert code_hash(quote_from_library(first, name)) == code_hash(quote_from_library(second, name))
        assert code_hash(quote_from_library(first, name)) != code_hash(quote_from_library(foreign, name))
    assert first.world.world_hash() != foreign.world.world_hash()
