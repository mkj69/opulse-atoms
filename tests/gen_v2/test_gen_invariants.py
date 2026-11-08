import random
import time
from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import CombinatorSpec, Contract, Definition, Edge, OperationSpec
from opulse.gen_v2.admit import admit
from opulse.gen_v2.audit import audit
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import toy, toy_truth


def _state():
    world = toy.gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))


def _operation(name, body, layer, inputs=("int",)):
    spec = OperationSpec(name, "transform", tuple(Edge(sort) for sort in inputs), Edge("int"),
                         "generated", extra={"input_names": [f"x{index}" for index in range(len(inputs))]})
    definition = Definition(name, "operation", "invented", layer, tuple(sorted(n.references(body))), spec, body)
    return Candidate(definition, Signature(inputs, "int"), "test")


def _populated():
    state = _state()
    first = _operation("f1", n.Call("add", (n.Var("x0"), n.Lit(2))), 1)
    second = _operation("f2", n.Call("mul", (n.Call("f1", (n.Var("x0"),)), n.Lit(2))), 2)
    assert isinstance(admit(state, first), Entry)
    assert isinstance(admit(state, second), Entry)
    return state


def test_audit_admitted_operations_and_seeded_sample():
    state = _populated()
    report = audit(state)
    assert report.ok, report.failures
    assert report.checked["operation"] == 2
    assert report.timings["total_seconds"] >= 0
    assert audit(state, sample=1, seed=19).checked["operation"] == 1


def test_audit_detects_corrupted_scope_and_body():
    state = _populated()
    original = state.library.get("f2")
    bad_evidence = replace(original.evidence, scope={**original.evidence.scope, "size": 1})
    state.library._definitions["f2"] = replace(original, evidence=bad_evidence)
    report = audit(state)
    assert any(failure.name == "f2" and failure.invariant == "I4" for failure in report.failures)
    bad_evidence = replace(original.evidence, scope={**original.evidence.scope, "domain": "corrupted"})
    state.library._definitions["f2"] = replace(original, evidence=bad_evidence)
    assert any(failure.name == "f2" and failure.invariant == "I4" for failure in audit(state).failures)
    checked = {**original.evidence.scope["checked"], "sha256": "0" * 64}
    bad_evidence = replace(original.evidence, scope={**original.evidence.scope, "checked": checked})
    state.library._definitions["f2"] = replace(original, evidence=bad_evidence)
    assert any(failure.name == "f2" and failure.invariant == "I4" for failure in audit(state).failures)
    state.library._definitions["f2"] = replace(original, body=n.Lit(999))
    report = audit(state)
    assert any(failure.name == "f2" and failure.invariant in ("I1", "dependency")
               for failure in report.failures)


def test_audit_detects_layer_and_missing_dependency():
    state = _populated()
    original = state.library.get("f2")
    state.library._definitions["f2"] = replace(original, layer=1)
    assert any(failure.invariant == "layer" for failure in audit(state).failures)
    state.library._definitions["f2"] = replace(original, depends_on=("missing",))
    assert any(failure.invariant == "dependency" for failure in audit(state).failures)


def test_audit_combinator_called_by_operation():
    state = _populated()
    body = n.Call("slot", (n.Call("slot", (n.Var("value"),)),))
    spec = CombinatorSpec("k3", ("slot", "value"), ("slot",), body)
    definition = Definition("k3", "combinator", "invented", 1, (), spec, body)
    first = tuple((value,) for value in state.sorts["int"].values[:2])  # a size prefix (bound 2)
    request = VerifyRequest("bounded", first,
                            {"domain": "bounded: the first 2 probe values of int", "size": 2, "bound": 2,
                             "op_family": ["inc", "dec"]},
                            extra={"op_family": ["inc", "dec"]})
    library = state.library
    library.write(definition)
    library.check("k3")
    library.make_callable("k3", ((kernel.FnRef("inc"), 1),))
    library.verify("k3", request)
    library.account("k3")
    library.promote("k3", Contract("unfold equivalent"))
    state.entries["k3"] = Entry("k3", "combinator", 1, Signature(("int",), "int",
                                (Signature(("int",), "int"),)), "test", ())
    use = _operation("f3", n.Call("k3", (n.Lit(kernel.FnRef("f2")), n.Var("x0"))), 2)
    assert isinstance(admit(state, use), Entry)
    report = audit(state)
    assert not report.ok and any("request unavailable" in failure.detail for failure in report.failures)
    state.requests["k3"] = request
    state.entries["k3"].meta["slot_families"] = {"slot": ("inc", "dec")}
    report = audit(state)
    assert report.ok, report.failures
    assert report.checked["combinator"] == 1


def test_audit_empty_state_and_bad_sample():
    state = _state()
    assert audit(state).ok
    try:
        audit(state, sample=-1)
    except ValueError:
        pass
    else:
        assert False, "negative sample must fail"


def test_audit_300_entries_under_20_seconds():
    state = _state()
    for index in range(300):
        name = f"f{index + 10}"
        body = n.Call("add", (n.Var("x0"), n.Lit(index + 2)))
        candidate = _operation(name, body, 1)
        admitted = admit(state, candidate)
        assert isinstance(admitted, Entry), admitted
    start = time.monotonic()
    report = audit(state)
    assert report.ok, report.failures[:3]
    assert report.checked["operation"] == 300
    assert time.monotonic() - start <= 20


def test_audit_compose_refine_and_constant_objects():
    moves = pytest.importorskip("opulse.gen_v2.moves.object").MOVES
    state = _populated()
    randomizer = random.Random(29)
    for index in range(24):
        candidate = moves[index % len(moves)](state, randomizer)
        if candidate is not None:
            admit(state, candidate)
    assert {state.library.get(entry.name).spec.form for entry in state.entries.values()
            if entry.kind == "object"} >= {"compose", "refine", "constant"}
    report = audit(state)
    assert report.ok, report.failures
    assert report.checked["object"] > 0


def test_audit_generated_observations_with_and_without_memory():
    state = generate(toy_truth.gen_world(), target=12, seed=4, per_kind_min=0, layer_target=0)
    assert any(entry.meta.get("memory") for entry in state.entries.values())
    order = tuple(state.entries)
    report = audit(state)
    assert report.ok, report.failures
    assert not report.skipped
    assert report.checked["observation"] == 12
    assert tuple(state.entries) == order

    name = next(iter(state.entries))
    original = state.library.get(name)
    state.library._definitions[name] = replace(original, body=n.Lit(999))
    assert any(failure.name == name and failure.invariant in ("I1", "I3")
               for failure in audit(state, sample=None).failures)
    state.library._definitions[name] = original
    checked = dict(original.evidence.scope["checked"])
    assert checked["by"] == "generator"
    forged = replace(original.evidence, scope={**original.evidence.scope, "checked": {**checked, "by": "library"}})
    state.library._definitions[name] = replace(original, evidence=forged)
    assert any(failure.name == name and failure.invariant == "I4" for failure in audit(state).failures)
    state.library._definitions[name] = original
    memory_name = next(entry.name for entry in state.entries.values() if entry.meta.get("memory"))
    memory_record = state.library.get(memory_name)
    state.library._definitions[memory_name] = replace(memory_record, body=n.Lit(999),
                                                       spec=replace(memory_record.spec, body=n.Lit(999)))
    assert any(failure.name == memory_name for failure in audit(state).failures)


def test_audit_generated_combinator_and_refine_object_corruption():
    state = generate(toy.gen_world(), target=12, seed=4, per_kind_min=0, layer_target=0)
    assert {entry.kind for entry in state.entries.values()} >= {"combinator", "object"}
    report = audit(state)
    assert report.ok, report.failures
    assert not report.skipped
    combinator = next(entry.name for entry in state.entries.values() if entry.kind == "combinator")
    original = state.library.get(combinator)
    state.library._definitions[combinator] = replace(original, body=n.Lit(999))
    assert any(failure.name == combinator for failure in audit(state).failures)
    state.library._definitions[combinator] = original

    refined = next(entry.name for entry in state.entries.values()
                   if entry.kind == "object" and state.library.get(entry.name).spec.form == "refine")
    original = state.library.get(refined)
    state.library._definitions[refined] = replace(original, spec=replace(original.spec, canon=n.Lit("bad")))
    assert any(failure.name == refined for failure in audit(state).failures)
    state.library._definitions[refined] = original
    composed = next(entry.name for entry in state.entries.values()
                    if entry.kind == "object" and state.library.get(entry.name).spec.form == "compose")
    original = state.library.get(composed)
    state.library._definitions[composed] = replace(original, body=n.Lit(999))
    assert any(failure.name == composed and failure.invariant == "I1" for failure in audit(state).failures)
