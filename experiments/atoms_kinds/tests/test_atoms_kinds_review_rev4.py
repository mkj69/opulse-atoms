"""Independent review reproductions for experiment 3."""

from dataclasses import replace

import pytest
from atoms_kinds.ascii import parse
from atoms_kinds.harness import analyze, run_episode, save
from atoms_kinds.policies import ScriptedPolicy, frac_definition
from atoms_kinds.tasks import generate
from atoms_kinds.world import make_library

from opulse.atoms import nodes
from opulse.atoms.values import FALSE, TRUE, Card, Ok


def test_review_prompt_specifies_given_operation_semantics():
    _, prompts = run_episode(ScriptedPolicy("operations"), "K1", 0, (generate(1)[:1], ()), max_attempts=1)
    prompt = prompts[0]["prompt"]
    assert "div(-7, 3) = -2" in prompt
    assert "mod(-7, 3) = 2" in prompt
    assert "gcd(-7, -3) = 1" in prompt
    assert "division by zero" in prompt


def test_review_pair_returning_operation_is_saveable_in_k1():
    definitions, _ = parse("op pack(a: Int, b: Int) -> Pair = Pair<a, b>\n"
                           "save pack\nop solve(a: Int) -> Pair = pack(a, 2)")
    library = make_library("K1")
    statuses = save(library, definitions, (1, 2))
    assert "refusal" not in statuses[0], statuses
    assert library.run("pack", (1, 2)).outcome == Ok(Card("Pair", "pair", (1, 2)))


@pytest.mark.parametrize("group", ("K1", "K2", "K3"))
def test_review_pair_readers_are_valid_saved_dependencies(group):
    definitions, _ = parse("op first(a: Int, b: Int) -> Int = Pair.num(Pair<a, b>)\n"
                           "save first\nop solve(a: Int, b: Int) -> Int = first(a, b)")
    library = make_library(group)
    statuses = save(library, definitions, (5, 7))
    assert statuses == [{"name": "first", "kind": "operation", "status": "callable"}]
    assert library.run("first", (5, 7)).outcome == Ok(5)


def test_review_operation_name_cannot_trigger_special_verification():
    definitions, _ = parse("op norm_num(a: Int) -> Int = add(a, 1)\n"
                           "save norm_num\nop solve(a: Int) -> Int = norm_num(a)")
    library = make_library("K1")
    statuses = save(library, definitions, (1,))
    assert statuses[0]["status"] == "callable", statuses
    assert library.get("norm_num").evidence is None
    assert library.get("norm_num").contract is None
    assert library.run("norm_num", (1,)).outcome == Ok(2)


def test_review_frac_object_promotes_with_scoped_evidence():
    library = make_library("K2")
    assert save(library, (frac_definition(),), (2, 4))[0]["status"] == "promoted"
    evidence = library.get("Frac").evidence
    assert evidence is not None and evidence.method == "bounded"
    assert evidence.scope["size"] == 156
    assert {"canon_total", "canon_idempotent", "canon_keeps_valid", "respects_canon"} <= set(evidence.checks)
    assert library.get("Frac").contract is not None


def test_review_failing_canon_reports_counterexample():
    original = frac_definition()
    bad_spec = replace(original.spec, canon=nodes.Call("Pair.pair", (nodes.Lit(1), nodes.Lit(0))))
    statuses = save(make_library("K2"), (replace(original, spec=bad_spec),), (2, 4))
    assert "canon_keeps_valid" in statuses[0]["refusal"]
    assert "Card(" in statuses[0]["refusal"]


def test_review_saved_definition_can_depend_on_previous_layer():
    definitions, _ = parse("op plus1(a: Int) -> Int = add(a, 1)\n"
                           "save plus1\n"
                           "op plus2(a: Int) -> Int = plus1(plus1(a)) L2\n"
                           "save plus2\n"
                           "op solve(a: Int) -> Int = plus2(a)")
    library = make_library("K1")
    statuses = save(library, definitions, (1,))
    assert all("refusal" not in status for status in statuses), statuses
    assert library.run("plus2", (1,)).outcome == Ok(3)


def test_review_wrong_layer_is_learner_visible():
    definitions, _ = parse("op plus1(a: Int) -> Int = add(a, 1)\n"
                           "save plus1\nop plus2(a: Int) -> Int = plus1(a) L3\n"
                           "save plus2\nop solve(a: Int) -> Int = plus2(a)")
    statuses = save(make_library("K1"), definitions, (1,))
    assert "layer must be 2, got 3" in statuses[1]["refusal"]


def test_review_implicit_layer_is_computed_and_explicit_l0_rejected():
    definitions, _ = parse("op plus1(a: Int) -> Int = add(a, 1)\n"
                           "save plus1\nop plus2(a: Int) -> Int = plus1(a)\n"
                           "save plus2\nop solve(a: Int) -> Int = plus2(a)")
    library = make_library("K1")
    assert all("refusal" not in row for row in save(library, definitions, (3,)))
    assert library.get("plus2").layer == 2
    with pytest.raises(ValueError, match="layer must be positive"):
        parse("op plus1(a: Int) -> Int = add(a, 1) L0\n"
              "save plus1\nop solve(a: Int) -> Int = plus1(a)")


def test_review_object_evidence_tracks_saved_operation_dependency():
    operation, _ = parse("op valid_den(a: Int) -> Int = add(a, 0)\n"
                         "save valid_den\nop solve(a: Int) -> Int = valid_den(a)")
    original = frac_definition()
    is_zero = nodes.Call("eq", (nodes.Call("valid_den", (nodes.Call("Pair.den", (nodes.Var("x"),)),)),
                                nodes.Lit(0)))
    valid = nodes.Case(((nodes.Test(is_zero), nodes.Lit(FALSE)),), nodes.Lit(TRUE))
    library = make_library("K2")
    assert save(library, operation, (4,))[0]["status"] == "callable"
    statuses = save(library, (replace(original, layer=0, spec=replace(original.spec, valid=valid)),), (2, 4))
    assert statuses[0]["status"] == "promoted", statuses
    assert library.get("Frac").layer == 2
    assert "valid_den" in library.get("Frac").depends_on
    assert library.get("Frac").evidence.deps_hash
    assert library.run("Frac.make", (Card("Pair", "pair", (1, 0)),)).outcome.reason == "invalid"


def test_review_analysis_needs_preregistered_episode_count():
    records = [
        {"group": group, "episode": 0, "stage": stage, "correct": group == "K2",
         "api_error": False, "invented": [], "reused": [], "length": 1,
         "steps": 1, "boundary_steps": 1}
        for group in ("K1", "K2") for stage in (1, 2)
        for _ in range(24 if stage == 1 else 16)
    ]
    assert analyze(records, resamples=20)["primary"]["decision"] == "diagnostic"
