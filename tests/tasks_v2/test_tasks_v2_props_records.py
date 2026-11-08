"""Task-record and task-grading properties (atoms-v2 spec sections 11-12)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.values import Bottom, Ok, Unknown, encode_outcome, outcome_equal
from opulse.tasks_v2 import grade, grade_kinds
from opulse.tasks_v2.angles import combinator, object, observation, operation
from opulse.tasks_v2.task import (
    ANGLES,
    CHANNELS,
    KINDS,
    Task,
    default_boundary,
    default_observation,
)


@st.composite
def records(draw):
    angle = draw(st.sampled_from(ANGLES))
    kind = draw(st.sampled_from(KINDS))
    shape = draw(st.sampled_from({"compute": ("value",), "invert": ("one_witness", "all_solutions"),
                                 "decide": ("verdict",), "describe": ("choice",),
                                 "induce": ("definition",), "create": ("definition",)}[angle]))
    boundary = default_boundary()
    boundary["depth"] = draw(st.one_of(st.none(), st.integers(0, 12)))
    boundary["kinds"] = draw(st.lists(st.sampled_from(KINDS), unique=True))
    boundary["open_names"] = draw(st.lists(st.sampled_from(("alpha", "beta")), unique=True))
    boundary["keep_names"] = draw(st.lists(st.sampled_from(
        tuple({"alpha", "beta"} - set(boundary["open_names"]))), unique=True)) if len(boundary["open_names"]) < 2 else []
    observation_settings = default_observation()
    observation_settings["channels"] = draw(st.lists(st.sampled_from(CHANNELS), unique=True))
    return Task("test/1", "toy@1", angle, kind, "sample",
                draw(st.sampled_from(("one_shot", "reusable"))) if angle == "create" else None,
                boundary, observation_settings, shape, "full_state", {}, {"en": "Task."}, {},
                {"method": {"value": "exact_value", "one_witness": "witness",
                            "all_solutions": "solution_set", "verdict": "verdict",
                            "choice": "choice", "definition": "definition"}[shape],
                 "fuel": draw(st.integers(1, 20000)), "scope": {}}, {"generator": "property"})


@settings(derandomize=True, max_examples=48, deadline=None)
@given(records())
def test_record_round_trip_and_invalid_mutations(record):
    data = record.to_dict()
    assert Task.from_dict(data).to_dict() == data
    for key, bad in (("angle", "not_an_angle"), ("kind", "not_a_kind"),
                     ("schema", "opulse.task/0"), ("answer_shape", "bad"),
                     ("boundary", {**data["boundary"], "depth": -1}),
                     ("observation", {**data["observation"], "channels": ["invalid"]}),
                     ("grader", {**data["grader"], "fuel": 0})):
        with pytest.raises(ValueError):
            Task.from_dict({**data, key: bad})
    with pytest.raises(ValueError):
        Task.from_dict({key: value for key, value in data.items() if key != "question"})
    data["boundary"]["depth"] = -1
    assert record.boundary["depth"] != -1


@settings(derandomize=True, max_examples=15, deadline=None)
@given(st.sampled_from((object, observation, combinator)), st.sampled_from(ANGLES),
       st.integers(0, 7))
def test_kind_grader_accepts_reference(module, angle, index):
    task = module.generate(angle, 0, index)
    answer = (task.reference["outcome"] if angle == "compute" else
              task.reference["answer"] if angle in ("invert", "decide") else
              task.reference["choice"] if angle == "describe" else task.reference["definition"])
    assert grade_kinds.grade(task, answer).correct
    if angle == "compute":
        assert not grade_kinds.grade(task, {"unknown": "fuel"}).correct
    if angle == "invert":
        members = task.reference["answer"] if task.answer_shape == "all_solutions" else [task.reference["answer"]]
        for member in members:
            witness_task = replace(task, answer_shape="one_witness",
                                   grader={**task.grader, "method": "witness"},
                                   reference={"answer": member})
            assert grade_kinds.grade(witness_task, member).correct
        for candidate in task.grader["scope"]["inputs"]:
            if candidate not in members:
                assert not grade_kinds.grade(witness_task, candidate).correct
                break


@pytest.mark.parametrize("module", (object, observation, combinator))
@pytest.mark.parametrize("angle", ANGLES)
def test_every_kind_angle_reference(module, angle):
    task = module.generate(angle, 0, 0)
    answer = (task.reference["outcome"] if angle == "compute" else
              task.reference["answer"] if angle in ("invert", "decide") else
              task.reference["choice"] if angle == "describe" else task.reference["definition"])
    assert grade_kinds.grade(task, answer).correct


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from(operation.WORLD_NAMES), st.sampled_from(ANGLES), st.integers(0, 7))
def test_operation_grader_accepts_reference(world, angle, index):
    task = operation.generate(world, angle, 0, index)
    answer = (task.reference["outcome"] if angle == "compute" else
              task.reference["answer"] if angle in ("invert", "decide") else
              task.reference["choice"] if angle == "describe" else task.reference["definition"])
    assert grade.grade(task, answer).correct
    if angle == "compute":
        assert not grade.grade(task, {"unknown": "fuel"}).correct
    if angle == "invert" and task.answer_shape == "one_witness":
        for candidate in task.grader["scope"]["inputs"]:
            if candidate != answer and not grade.grade(task, candidate).correct:
                assert not grade.grade(task, candidate).correct
                break


@pytest.mark.parametrize("angle", ANGLES)
def test_every_operation_angle_reference(angle):
    task = operation.generate("integer", angle, 0, 0)
    answer = (task.reference["outcome"] if angle == "compute" else
              task.reference["answer"] if angle in ("invert", "decide") else
              task.reference["choice"] if angle == "describe" else task.reference["definition"])
    assert grade.grade(task, answer).correct


@settings(derandomize=True, max_examples=24)
@given(st.text(alphabet="abc", max_size=5), st.text(alphabet="xyz", max_size=5))
def test_bottom_equal_unknown_never_equal(first, second):
    assert outcome_equal(Bottom(first), Bottom(second))
    assert not outcome_equal(Unknown(first), Unknown(first))
    assert not outcome_equal(Unknown(first), Ok(0))
    assert encode_outcome(Bottom(first)) == {"bottom": first}


@settings(derandomize=True, max_examples=16)
@given(st.text(alphabet="abc", max_size=5), st.text(alphabet="xyz", max_size=5))
def test_exact_value_grader_accepts_any_bottom_reason_but_not_unknown(first, second):
    # Grading executes the question (review 2, finding 9), so the question itself must fail.
    task = operation.generate("integer", "compute", 0, 0)
    task = replace(task, question={**task.question, "expression": "div(7, 0)"},
                   reference={"outcome": {"bottom": first}})
    assert grade.grade(task, {"bottom": second}).correct
    assert not grade.grade(task, {"unknown": "fuel"}).correct
