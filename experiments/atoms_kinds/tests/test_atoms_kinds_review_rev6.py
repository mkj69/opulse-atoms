"""Independent reproductions of saved-definition and seal failures."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from atoms_kinds.ascii import parse
from atoms_kinds.harness import analyze, check_constructor, save
from atoms_kinds.policies import frac_definition
from atoms_kinds.world import make_library

from opulse.atoms import nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.values import Card, Ok


def test_review_invented_object_requires_full_bounded_scope_before_promotion():
    library = make_library("K2")
    status = save(library, (frac_definition(),), (2, 4))[0]
    evidence = library.get("Frac").evidence
    assert status["status"] == "promoted"
    assert evidence.method == "bounded"
    assert evidence.scope["size"] == 156
    assert evidence.scope["domain"] == "all Pair<num, den> with num, den in -6..6, den != 0"
    assert set(evidence.scope["obligations_checked"]) == {
        "canon_total", "canon_idempotent", "canon_keeps_valid", "respects_canon", "seal"}
    assert {"canon_total", "canon_idempotent", "canon_keeps_valid", "respects_canon"} <= set(evidence.checks)
    assert set(evidence.scope["interface"]) == set(library.get("Frac").spec.interface)


def test_review_constructor_respects_canon_and_rejects_disagreement():
    library = make_library("K2")
    definition = frac_definition()
    assert save(library, (definition,), (2, 4))[0]["status"] == "promoted"
    domain = ((Card("Pair", "pair", (2, 4)),),)
    assert check_constructor(library, definition, domain) is None
    bad = replace(definition, spec=replace(definition.spec,
                  canon=nodes.Lit(Card("Pair", "pair", (3, 4)))))
    with pytest.raises(PipelineError, match="constructor does not respect canon"):
        check_constructor(library, bad, domain)


def test_review_analysis_requires_every_distinct_frozen_task():
    records = [
        {"group": group, "episode": episode, "stage": stage,
         "task_id": f"S{stage}-sum-01", "correct": group == "K2",
         "api_error": False, "invented": [], "reused": [], "length": 1,
         "steps": 1, "boundary_steps": 1}
        for group in ("K1", "K2")
        for episode in range(40)
        for stage, count in ((1, 24), (2, 16))
        for _ in range(count)
    ]
    assert analyze(records, resamples=20)["primary"]["decision"] == "diagnostic"


def test_review_analysis_accepts_exact_frozen_task_ids():
    task_root = Path(__file__).resolve().parents[1] / "tasks"
    ids = {stage: [task["id"] for task in json.loads(
        (task_root / f"stage{stage}.json").read_text(encoding="utf-8"))["tasks"]]
           for stage in (1, 2)}
    records = [
        {"group": group, "episode": episode, "stage": stage, "task_id": task_id,
         "correct": group == "K2", "api_error": False, "invented": [], "reused": [],
         "length": 1, "steps": 1, "boundary_steps": 1}
        for group in ("K1", "K2") for episode in range(40)
        for stage in (1, 2) for task_id in ids[stage]
    ]
    assert analyze(records, resamples=20)["primary"]["decision"] == "value"


def test_review_rejected_helper_edit_preserves_previous_saved_definition():
    library = make_library("K1")
    original, _ = parse(
        "op helper(a: Int) -> Int = add(a, 1)\n"
        "save helper\n"
        "op solve(a: Int) -> Int = helper(a)"
    )
    assert save(library, original, (1,))[0]["status"] == "callable"
    replacement, _ = parse(
        "op helper(a: Int) -> Int = missing(a)\n"
        "save helper\n"
        "op solve(a: Int) -> Int = helper(a)"
    )
    assert "definition already exists: helper" in save(library, replacement, (1,))[0]["refusal"]
    assert library.run("helper", (1,)).outcome == Ok(2)


def test_review_saved_fraction_helper_can_call_saved_object_interface():
    library = make_library("K2")
    assert save(library, (frac_definition(),), (2, 4))[0]["status"] == "promoted"
    definitions, _ = parse(
        "op numerator(a: Int, b: Int) -> Int = Frac.num(Frac.make(Pair<a, b>))\n"
        "save numerator\n"
        "op solve(a: Int, b: Int) -> Int = numerator(a, b)"
    )
    statuses = save(library, definitions, (2, 4))
    assert "refusal" not in statuses[0], statuses
    assert library.run("numerator", (2, 4)).outcome == Ok(1)


@pytest.mark.parametrize("position", ("valid", "canon"))
def test_review_saved_object_canon_cannot_unseal_another_object(position):
    library = make_library("K2")
    assert save(library, (frac_definition(),), (2, 4))[0]["status"] == "promoted"
    valid = "if eq(Pair.den(x), 0) then false else true"
    canon = "Pair<Pair.num(x), Pair.den(x)>"
    if position == "valid":
        valid = "eq(Frac.base(Frac.make(x)), x)"
    else:
        canon = "Frac.base(Frac.make(x))"
    definitions, _ = parse(
        f"obj Probe = <num: Int, den: Int> where {valid} canon {canon} sealed (make, num, den)\n"
        "save Probe\n"
        "op solve(a: Int, b: Int) -> Pair = Pair<a, b>"
    )
    statuses = save(library, definitions, (2, 4))
    assert "private sealed operation" in statuses[0]["refusal"]
