"""Published operator families, boundaries, and grading invariants."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.values import (
    Bottom,
    Card,
    Ok,
    Unknown,
    decode_outcome,
    encode,
    encode_outcome,
    outcome_equal,
)
from opulse.tasks_v2 import engine
from opulse.tasks_v2.angles.operation import (
    ANGLES,
    WORLD_NAMES,
    _closure,
    _data,
    _host,
    _operator_size,
    _published_result,
    _rows,
    generate,
)
from opulse.tasks_v2.ascii import names, to_ascii_definition
from opulse.tasks_v2.build import build
from opulse.tasks_v2.grade import executable_task, grade
from opulse.tasks_v2.task import default_boundary, default_observation


def answer(task):
    return next(task.reference[key] for key in ("outcome", "answer", "choice", "definition")
                if key in task.reference)


@pytest.mark.parametrize("world", WORLD_NAMES)
@pytest.mark.parametrize("angle", ANGLES)
def test_seeded_tasks_and_reference_grading(world, angle):
    for index in (0, 1):
        task = generate(world, angle, 0, index)
        assert task == generate(world, angle, 0, index)
        assert grade(task, answer(task)).correct
        wrong = ({"unknown": "fuel"} if angle == "compute" else
                 [] if angle == "invert" else
                 {"true": not answer(task)["true"]} if angle == "decide" else
                 next(option for option in task.question["options"] if option != answer(task))
                 if angle == "describe" else "invalid definition")
        assert not grade(task, wrong).correct


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_diversity_and_published_origin(world):
    for angle in ANGLES:
        tasks = [generate(world, angle, 0, index) for index in range(8)]
        assert len({json.dumps(task.question, sort_keys=True) for task in tasks}) == 8
        assert len({task.question["operator"] for task in tasks}) >= 3
        if angle in ("compute", "induce", "create"):
            assert {task.question["form"] for task in tasks} == {"composition", "branching", "recursion"}
        if angle == "describe":
            assert len({task.question["options"].index(answer(task)) for task in tasks}) > 1
            assert all(len(task.question["options"]) >= 3 for task in tasks)
        if angle == "decide":
            assert {answer(task)["true"] for task in tasks} == {True, False}
        if angle == "create":
            assert {task.variant for task in tasks} == {"one_shot", "reusable"}
            for task in tasks:
                if task.variant == "reusable":
                    held_out = task.source["held_out"]
                    assert len(held_out) >= 2
                    assert all(row["length_without"] > row["length_with"] and "reference" in row
                               for row in held_out)
        assert all(task.question["operator"] in names(task.world)[0].values() for task in tasks)


def test_hole_solver_variants_and_rechecked_solutions():
    witness = generate("clock", "invert", index=0)
    assert len(witness.grader["scope"]["inputs"]) > 1
    assert grade(witness, witness.reference["answer"]).correct
    assert all(0 <= item[0]["v"] < 12 for item in witness.grader["scope"]["inputs"])
    assert not grade(witness, [encode(12)]).correct  # clock@2: 12 is not a canonical hour; outside the scope
    wrong = [item for item in witness.grader["scope"]["inputs"] if not grade(witness, item).correct]
    assert wrong and len(wrong) < len(witness.grader["scope"]["inputs"])
    solutions = generate("lists", "invert", index=1)
    expected = answer(solutions)
    assert len(expected) >= 2
    assert not grade(solutions, expected[:-1]).correct
    assert not grade(solutions, expected + expected[:1]).correct


def test_verdict_rechecks_law_counterexample():
    task = generate("integer", "decide", index=1)
    assert not answer(task)["true"]
    assert grade(task, answer(task)).correct
    assert grade(task, {"true": False, "counterexample": [[encode(-12), encode(-12)]]}).reason == "invalid_counterexample"
    identity = generate("integer", "decide", index=0)
    assert identity.question["claim"]["type"] == "right_identity"
    assert grade(identity, {"true": True}).correct
    equivalence = generate("clock", "decide", index=7)
    assert equivalence.question["claim"]["type"] == "equivalent"
    assert grade(equivalence, answer(equivalence)).correct


def test_definition_exhaustive_and_sampled_scopes():
    task = generate("integer", "induce", index=0)
    assert task.grader["scope"]["method"] == "exhaustive"
    assert len(task.grader["scope"]["domains"][0]) >= 25
    alternative = task.reference["definition"].replace("f6(a, a)", "(f6(a, a))")
    assert alternative != answer(task)
    assert grade(task, alternative).correct
    assert grade(task, "♡₁ a = { unknown a }").reason == "invalid_definition"
    assert not grade(task, "♡₁ a = { a }").correct
    sampled = replace(task, grader={**task.grader, "scope": {"sample": {
        "seed": 1, "count": 500, "domains": [[encode(-2), encode(1), encode(3)]]}}})
    assert grade(sampled, answer(sampled)).detail == {"scope": "sampled", "tested": 500}
    list_scope = generate("lists", "induce").grader["scope"]["domains"][0]
    string_scope = generate("strings", "induce").grader["scope"]["domains"][0]
    assert len(list_scope) == len(string_scope) == 15


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_induction_excludes_smaller_published_competitors(world):
    for index in range(8):
        task = generate(world, "induce", index=index)
        selected = _rows(world)[executable_task(task).question["operator"]]
        assert len(task.question["examples"]) >= 10
        assert task.question["identifiable"]["method"] == "greedy finite input range"
        for row in _rows(world).values():
            if (row["name"] == selected["name"] or row["params"] != selected["params"]
                    or row["result_type"] != selected["result_type"]
                    or _operator_size(world, row["name"]) >= _operator_size(world, selected["name"])):
                continue
            assert any(not outcome_equal(engine.call(
                task.world, _closure(world, [row["name"]]),
                row["name"], tuple(_host(value) for value in example["inputs"]), 10000)[0],
                decode_outcome(example["output"])) for example in task.question["examples"])


def test_bottom_unknown_and_fuel():
    task = generate("integer", "compute")
    bottom = replace(task, reference={"outcome": {"bottom": "div_zero"}})
    assert not grade(bottom, {"bottom": "undefined"}).correct
    assert grade(task, {"unknown": "fuel"}).reason == "unknown"
    assert isinstance(engine.evaluate("integer@1", {}, "(1 / 0)", 100)[0], Bottom)
    assert isinstance(engine.evaluate("integer@1", {}, "(1 + 2)", 0)[0], Unknown)
    assert engine.call("lists@1", {}, "⊞", ((1,), (2,)), 100)[0] == Ok(Card("list[int]", "list", (1, 2)))
    looping = replace(generate("integer", "induce"),
                      grader={"method": "definition", "fuel": 2,
                              "scope": {"inputs": [[encode(1)]]}})
    assert grade(looping, "♡₁ a = { ♡₁ a }").reason == "unknown"
    forbidden = replace(looping, question={**looping.question, "allowed_atoms": []})
    assert grade(forbidden, answer(forbidden)).reason == "forbidden_atom"


def test_boundary_and_observation_do_not_change_truth():
    ordinary = generate("integer", "compute")
    kept = default_boundary()
    kept["keep_names"] = [ordinary.question["operator"]]
    opaque = generate("integer", "compute", boundary=kept)
    opened = default_boundary()
    opened["depth"] = 0
    atoms = generate("integer", "compute", boundary=opened)
    assert ordinary.reference == opaque.reference == atoms.reference
    assert len({item.prompt["en"] for item in (ordinary, opaque, atoms)}) == 3
    assert "one opaque step" in opaque.prompt["en"]
    assert "♡₁" not in atoms.prompt["en"].split("Trace:", 1)[-1]
    explicitly_open = default_boundary()
    explicitly_open["open_names"] = [ordinary.question["operator"]]
    unfolded = generate("integer", "compute", boundary=explicitly_open)
    assert unfolded.reference == ordinary.reference
    assert unfolded.prompt["en"] != ordinary.prompt["en"]
    observation = default_observation()
    observation["channels"] = ["results"]
    narrowed = generate("integer", "compute", observation=observation)
    assert grade(ordinary, answer(ordinary)) == grade(narrowed, answer(ordinary))
    observation["show"]["input"] = "hidden"
    obscured = generate("integer", "compute", observation=observation)
    assert obscured.question["expression"] not in obscured.prompt["en"].split("Compute ")[-1]


def test_published_legacy_agreement():
    import random

    from opulse.bench.tasks import BenchBuilder
    from opulse.expression.nodes import from_ast

    for world in WORLD_NAMES:
        _, legacy = _data(world)
        compute = generate(world, "compute", index=0)
        compute_question = executable_task(compute).question
        selected = _rows(world)[compute_question["operator"]]["examples"][0]
        assert compute.reference["outcome"] == encode_outcome(engine.evaluate(
            compute.world, compute_question["definitions"], selected["expression"], 10000)[0])
        assert compute.reference["outcome"] == _published_result(selected["output"])
        settings, _ = engine._base(compute.world)
        oracle = engine._oracle(compute.world, compute_question["definitions"])
        builder = BenchBuilder(settings, oracle.registry, random.Random(0), min_definitions=0,
                               allow_nan=True, max_answer_share=1)
        tree = from_ast(oracle.parser.parse_expr(compute_question["expression"]), oracle.registry)
        assert builder._compute(tree, 0).answer == _host(selected["output"])
        contrast = generate(world, "compute", index=1)
        contrast_question = executable_task(contrast).question
        assert engine._oracle(world, contrast_question["definitions"]).parser.parse_expr(
            contrast_question["expression"]) == engine._oracle(
                world, contrast_question["definitions"]).parser.parse_expr(legacy["contrast"][0]["expression"])
        assert contrast.reference["outcome"] == encode_outcome(engine.evaluate(
            contrast.world, contrast_question["definitions"], contrast_question["expression"], 10000)[0])
        assert contrast.reference["outcome"] == _published_result(legacy["contrast"][0]["b"]["value"])
        swapped = engine._oracle(contrast.world, contrast_question["definitions"])
        swap_builder = BenchBuilder(settings, swapped.registry, random.Random(0), min_definitions=0,
                                    allow_nan=True, max_answer_share=1)
        swap_tree = from_ast(swapped.parser.parse_expr(contrast_question["expression"]), swapped.registry)
        assert swap_builder._compute(swap_tree, 0).answer == _host(legacy["contrast"][0]["b"]["value"])
        hole = generate(world, "invert")
        assert hole.question["solver"] == legacy["holes"][0]["check"]
        hole_question = executable_task(hole).question
        assert outcome_equal(engine.evaluate(world, hole_question["definitions"], hole_question["hole_expression"],
                                             10000, {"x": _host(answer(hole)[0])})[0],
                             decode_outcome(hole.question["target"]))
        decide = generate(world, "decide", index=0)
        assert "published_law" not in decide.question
        assert "published_law" in decide.source
        induce = generate(world, "induce")
        assert answer(induce) == to_ascii_definition(induce.world, _rows(world)[executable_task(induce).question["operator"]]["definition"], executable_task(induce).question["definitions"])
        create = generate(world, "create")
        assert answer(create) == to_ascii_definition(create.world, _rows(world)[executable_task(create).question["operator"]]["definition"], executable_task(create).question["definitions"])


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_compute_ignores_tampered_reference_and_respects_fuel(world):
    task = generate(world, "compute")
    forged = {"ok": encode(999999)}
    altered = replace(task, reference={"outcome": forged})
    assert not grade(altered, forged).correct
    assert grade(altered, answer(task)).correct
    starved = replace(task, grader={**task.grader, "fuel": 1})
    assert grade(starved, answer(task)).reason == "unknown"


def test_compute_rechecks_bottom_independent_of_reference():
    task = generate("integer", "compute")
    question = {**task.question, "expression": "div(1, 0)"}
    bottom = replace(task, question=question, reference={"outcome": {"ok": encode(42)}})
    assert grade(bottom, {"bottom": "div_zero"}).correct
    assert not grade(bottom, bottom.reference["outcome"]).correct


@settings(max_examples=12, deadline=None)
@given(st.integers(min_value=100000, max_value=1000000))
def test_forged_references_never_change_computed_answer(value):
    task = generate("integer", "compute")
    forged = {"ok": encode(value)}
    assert not grade(replace(task, reference={"outcome": forged}), forged).correct


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_decide_questions_do_not_publish_verdicts(world):
    for index in range(8):
        task = generate(world, "decide", index=index)
        assert "published_law" not in task.question
        assert "published_equivalence" not in task.question
        verdict = task.reference["answer"]
        pending = list(task.question.values())
        while pending:
            value = pending.pop()
            assert value != verdict
            if isinstance(value, dict):
                assert not {"holds", "counterexample", "published_law", "published_equivalence"} & value.keys()
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                assert json.dumps(verdict, sort_keys=True) not in value
        if task.family == "equivalence":
            assert "published_equivalence" in task.source
        else:
            assert "published_law" in task.source


def test_frozen_build(tmp_path):
    for world in WORLD_NAMES:
        for path in build(world, 0, 8, tmp_path):
            committed = Path("worlds/tasks") / path.relative_to(tmp_path)
            assert committed.read_bytes() == path.read_bytes()
            assert len(json.loads(path.read_text())) == 8
