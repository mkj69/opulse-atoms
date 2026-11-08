"""Independent reproductions for the spec-0.4 experiment migration."""

import json
from pathlib import Path

from atoms_kinds.harness import analyze, save
from atoms_kinds.policies import law_definition
from atoms_kinds.world import integer_atoms, make_library, make_world
from atoms_mul.analysis.cost import estimate
from atoms_mul.analysis.llm_policy import DEFAULT_MAX_OUTPUT_TOKENS, LLMPolicy
from atoms_mul.kernel import Library as AmlLibrary
from atoms_mul.kernel import check_program, load_world
from atoms_mul.kernel.core_library import CoreMirror
from atoms_mul.kernel.nodes import Call, Def, Program, Var

from opulse.atoms import library as core_library
from opulse.atoms.library import Library, VerifyRequest


def test_kinds_cost_estimate_matches_policy_cap():
    assert LLMPolicy.__init__.__kwdefaults__["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    records = [{"group": "K4", "stage": 1, "task_id": "sample", "prompt": "test"}]
    assert estimate(records, groups=("K4",))["worst_output_tokens"] == 40 * 3 * DEFAULT_MAX_OUTPUT_TOKENS


def test_review_k4_uses_native_verifier_without_process_wide_side_effects():
    before = (dict(core_library._CHECKERS), dict(core_library._VERIFIERS))
    assert type(make_library("K4")) is Library
    assert (dict(core_library._CHECKERS), dict(core_library._VERIFIERS)) == before
    independent = Library(make_world("K4"), integer_atoms())
    definition = law_definition()
    independent.write(definition)
    independent.check(definition.name)
    independent.make_callable(definition.name, ((2, 3),))
    verified = independent.verify(definition.name, VerifyRequest(
        "bounded", ((2, 3),), {"domain": "a=2, b=3", "size": 1}))
    assert "holds" in verified.evidence.checks


def test_review_mirror_rejects_bool_body_declared_as_nat():
    definition = Def("bad", ("a",), Call("is_zero", (Var("a"),)), ("Nat",), "Nat")
    program = Program((definition,), ())
    assert check_program(program, load_world("B"), AmlLibrary()) == [
        "result of bad expects Nat, got Bool"]
    entry, = AmlLibrary().add_from_program(program, ("bad",), "invalid-restored-entry")
    report, = CoreMirror("B").mirror((entry,))
    assert report["problems"], report


def test_review_k4_refused_law_is_not_counted_as_saved():
    library = make_library("K4")
    law = law_definition()
    assert save(library, (law,), (2, 3))[0]["status"] == "promoted"
    refused = save(library, (law,), (2, 3))[0]
    assert "definition already exists" in refused["refusal"]

    run_file = Path(__file__).resolve().parents[1] / "runs/dryrun_object/results.jsonl"
    records = [json.loads(line) for line in run_file.read_text().splitlines()]
    counts_before = analyze(records, resamples=5)["groups"]["K4"]["laws"]
    next(record for record in records if record["group"] == "K4")["statuses"].append(refused)
    counts_after = analyze(records, resamples=5)["groups"]["K4"]["laws"]
    for metric in ("saved", "verified", "promoted"):
        assert counts_after[metric] == counts_before[metric], metric
