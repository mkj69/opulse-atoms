"""The saved AML track is represented in the core without changing the grader."""

import hashlib
import json
import random
from dataclasses import replace

import pytest
from atoms_mul.kernel import Library as AmlLibrary
from atoms_mul.kernel import evaluate, load_world, parse_program
from atoms_mul.kernel.core_library import (
    DECLARATIONS,
    MUTUAL_RECURSION,
    CoreMirror,
    atoms,
    compile_definition,
    load_decl,
    mirror_sort,
    mirror_world,
    write_decls,
)
from atoms_mul.kernel.evaluate import _operation
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl

REP = "op MUL(a: Nat, b: Nat) -> Nat = if is_zero(a) then 0 else add(b, MUL(pred(a), b))"
WORLD_HASHES = {
    "A": "47c581d335de03dec00d19180fa0fbf97293a81ee86b7d53bfc3e09de82a6c71",
    "B": "aee259097a92b9e9935fb8da1164152e6a5cfeda8a40341de162677b2ec3d3ba",
    "C": "3e80f0c65923b448db99ce8abdd0041aa2edfa520f645f38e17e06ed6ddac8c5",
}


def saved(text, names):
    library = AmlLibrary()
    return library.add_from_program(parse_program(text), names, "task")


def test_mirror_sort_preserves_bool_and_maps_nat_to_int():
    assert mirror_sort("Nat") == "int"
    assert mirror_sort("Bool") == "bool"


def test_mirror_world_normalizes_operation_edges_without_rewriting_declarations():
    for group in "ABC":
        declaration = mirror_world(group)
        for operation in declaration.operations:
            assert all(edge.sort in ("int", "bool") for edge in operation.inputs)
            assert operation.output.sort in ("int", "bool")
        assert any(operation.output.sort == "nat" for operation in load_decl(group).operations)


@given(st.integers(min_value=0, max_value=10**9))
def test_literal_nat_results_remain_callable_and_sort_checked(value):
    entry = saved(f"op constant() -> Nat = {value}", ["constant"])[0]
    mirror = CoreMirror("B")
    report, = mirror.mirror((entry,))
    assert report["problems"] == []
    assert mirror.library.run("constant", ()).outcome == Ok(value)


def test_bool_result_cannot_be_mirrored_as_nat():
    entry = saved("op bad(a: Nat) -> Nat = is_zero(a)", ["bad"])[0]
    report, = CoreMirror("B").mirror((entry,))
    assert any("output: expected int, got bool" in problem for problem in report["problems"])


def test_world_declarations_load_and_hash_stably():
    for group in "ABC":
        declaration = load_decl(group)
        encoded = json.loads((DECLARATIONS / f"atoms_mul_{group}.json").read_text())
        assert declaration.to_dict() == WorldDecl.from_dict(encoded).to_dict()
        assert WorldDecl.from_dict(encoded).world_hash() == declaration.world_hash()
        assert declaration.observation["judge_view"] == "full_state"
        assert declaration.combinators["recursion"] == "fuel"
        assert declaration.open_kinds == ("operation",)
        assert {op.name for op in declaration.operations} == set(load_world(group).operations)
        assert declaration.world_hash() == WORLD_HASHES[group]
        source_digest = hashlib.sha256(
            (DECLARATIONS.parents[1] / "atoms_mul" / "kernel" / "ops.py").read_bytes()
        ).hexdigest()
        assert set(declaration.lock["host_digests"]) == {
            *(op.impl["host"] for op in declaration.operations),
            declaration.objects[0].valid["host"],
        }
        assert set(declaration.lock["host_digests"].values()) == {source_digest}
        assert all(op.impl["digest"] == source_digest for op in declaration.operations)


def test_committed_declarations_equal_regenerated(tmp_path):
    for group in "ABC":
        (tmp_path / f"atoms_mul_{group}.json").write_bytes(
            (DECLARATIONS / f"atoms_mul_{group}.json").read_bytes())
    write_decls(tmp_path)
    for group in "ABC":
        assert (tmp_path / f"atoms_mul_{group}.json").read_bytes() == (
            DECLARATIONS / f"atoms_mul_{group}.json").read_bytes()


@pytest.mark.parametrize("group", list("ABC"))
def test_atoms_match_experiment_operations(group):
    samples = [(0, 0), (2, 3), (0, 1), (10**9, 2),
               (True, 1), (-1, 2), (10**9 + 1, 2), (7, 9)]
    for atom in atoms(group):
        for pair in samples:
            args = pair[:atom.arity]
            actual = atom.fn(*args)
            expected = _operation(atom.name, args)
            assert type(actual).__name__ == type(expected).__name__
            assert actual == type(actual)(expected.value if hasattr(expected, "value") else expected.reason)
            assert atom.cost == 1
    assert "mul" not in {atom.name for atom in atoms("B")}


def test_recursive_multiplication_promotes_with_scoped_evidence():
    entry = saved(REP, ["MUL"])[0]
    compiled = compile_definition(entry, {"MUL": entry})
    assert isinstance(compiled.body, nodes.Rec)
    assert compiled.body.measure == "fuel"
    mirror = CoreMirror("B")
    report, = mirror.mirror([{"definition": entry, "mul_equivalent": True}])
    assert report["core_status"] == "promoted" and not report["problems"]
    assert report["evidence"]["method"] == "exhaustive"
    assert report["evidence"]["scope"]["size"] == 256
    assert report["evidence"]["scope"]["checked"]["size"] == 256
    assert report["evidence"]["scope"]["checked"]["bounds"] == {
        "0": {"min": 0, "max": 15}, "1": {"min": 0, "max": 15}}
    assert report["cost"]["steps"]["max"] > 0
    promoted, = mirror.derived_world().promoted
    assert promoted.contract.guarantees == "result = a * b for a, b in 0..15; no state"
    assert mirror.derived_world().scopes()["MUL"] == promoted.evidence.scope
    derived_operations = {op.name for op in load_decl("B").operations} | {
        definition.name for definition in mirror.derived_world().promoted
    }
    assert derived_operations == ({op.name for op in load_decl("A").operations} - {"mul"}) | {"MUL"}


def test_entry_claim_cannot_replace_core_verification():
    entry = replace(saved(REP, ["MUL"])[0], evidence={"equivalent": True,
                                                     "scope": "a,b in [0,15]"})
    report, = CoreMirror("B").mirror([entry])
    assert report["core_status"] == "callable"
    assert report["evidence"] is None


def test_bad_multiplication_remains_callable_with_counterexample():
    entry = saved("op MUL(a: Nat, b: Nat) -> Nat = succ(add(a, b))", ["MUL"])[0]
    mirror = CoreMirror("B")
    report, = mirror.mirror([{"definition": entry, "mul_equivalent": True}])
    assert report["core_status"] == "callable"
    assert any("counterexample" in problem for problem in report["problems"])
    assert not mirror.derived_world().promoted


def test_constant_scale_and_dependencies_remain_callable():
    entries = saved("op double(x: Nat) -> Nat = add(x, x) op quad(x: Nat) -> Nat = double(double(x))",
                    ["double", "quad"])
    mirror = CoreMirror("B")
    reports = mirror.mirror(entries)
    assert [report["core_status"] for report in reports] == ["callable", "callable"]
    assert mirror.library.get("quad").depends_on == ("double",)
    assert mirror.library.get("quad").layer == 2
    assert all(report["cost"]["length"] > 0 for report in reports)
    assert all(report["cost"]["steps"]["max"] > 0 for report in reports)
    assert mirror.library.run("quad", (3,)).outcome == Ok(12)


def test_mutual_recursion_is_reported_without_writing():
    entries = saved("op left(x: Nat) -> Nat = right(x) op right(x: Nat) -> Nat = left(x)", ["left", "right"])
    assert compile_definition(entries[0], {entry.name: entry for entry in entries}) is None
    mirror = CoreMirror("B")
    reports = mirror.mirror(entries)
    assert all(report["problems"] == [MUTUAL_RECURSION] for report in reports)
    assert all(name not in mirror.library.definitions for name in ("left", "right"))


def test_every_stored_definition_matches_experiment_on_seeded_inputs():
    entries = saved(REP + "\nop twice(x: Nat) -> Nat = add(x, x)\nop composed(a: Nat, b: Nat) -> Nat = twice(MUL(a, b))",
                    ["MUL", "twice", "composed"])
    mirror = CoreMirror("B")
    assert all(not report["problems"] for report in mirror.mirror(entries))
    aml_library = AmlLibrary()
    program = parse_program(REP + "\nop twice(x: Nat) -> Nat = add(x, x)\nop composed(a: Nat, b: Nat) -> Nat = twice(MUL(a, b))")
    aml_library.add_from_program(program, ["MUL", "twice", "composed"], "task")
    rng = random.Random(20261104)
    for entry in entries:
        for _ in range(50):
            args = tuple(rng.randrange(12) for _ in entry.params)
            core_run = mirror.library.run(entry.name, args)
            aml_run = evaluate(entry.name, args, world=load_world("B"), library=aml_library)
            assert core_run.steps == aml_run.steps
            assert type(core_run.outcome).__name__ == type(aml_run.outcome).__name__
            assert core_run.outcome.value == aml_run.outcome.value


def test_promotion_requires_verification_and_mirror_is_deterministic():
    entry = saved(REP, ["MUL"])[0]
    first, second = CoreMirror("B"), CoreMirror("B")
    assert first.mirror([entry])[0]["core_status"] == "callable"
    with pytest.raises(PipelineError, match="verified"):
        first.library.promote("MUL", Contract())
    accounted = first.library.account("MUL")
    assert accounted.cost.length > 0
    assert accounted.cost.steps["max"] > 0
    assert second.mirror([entry])[0]["core_status"] == "callable"
    assert first.library.to_dict() == second.library.to_dict()
    promoted_first, promoted_second = CoreMirror("B"), CoreMirror("B")
    for mirror in (promoted_first, promoted_second):
        assert mirror.mirror([{"definition": entry, "mul_equivalent": True}])[0]["core_status"] == "promoted"
    assert promoted_first.library.to_dict() == promoted_second.library.to_dict()
    assert promoted_first.derived_world().to_dict() == promoted_second.derived_world().to_dict()


def test_world_c_rejects_storage():
    entry = saved("op double(x: Nat) -> Nat = add(x, x)", ["double"])[0]
    report, = CoreMirror("C").mirror([entry])
    assert report["core_status"] is None
    assert "saving definitions is not available" in report["problems"][0]


def test_bad_entries_are_reported_without_interrupting_later_saves():
    entry = saved("op double(x: Nat) -> Nat = add(x, x)", ["double"])[0]
    mirror = CoreMirror("B")
    reports = mirror.mirror([None, {"name": "broken"}, entry])
    assert reports[0]["problems"] == ["saved definition needs a name"]
    assert reports[1]["core_status"] is None and reports[1]["problems"]
    assert reports[2]["core_status"] == "callable"
