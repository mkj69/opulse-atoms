"""Boundary, observation, witness and ASCII invariants (atoms-v2 spec section 11)."""

from dataclasses import replace

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from test_tasks_v2_generic import toy_world

from opulse.atoms.boundary import Boundary
from opulse.tasks_v2 import generic, grade, grade_kinds
from opulse.tasks_v2.angles import combinator, object, observation, operation
from opulse.tasks_v2.task import ANGLES, CHANNELS, KINDS


@st.composite
def views(draw):
    opened = draw(st.lists(st.sampled_from(("plus_one", "twice", "front_free")), unique=True))
    kept = draw(st.lists(st.sampled_from(tuple(
        {"plus_one", "twice", "front_free"} - set(opened))), unique=True)) if len(opened) < 3 else []
    boundary = Boundary(depth=draw(st.one_of(st.none(), st.integers(0, 3))),
                        open_names=frozenset(opened), keep_names=frozenset(kept),
                        kinds=frozenset(draw(st.lists(st.sampled_from(KINDS), unique=True))))
    channels = draw(st.lists(st.sampled_from(CHANNELS), unique=True))
    return boundary, {"show": {"input": draw(st.sampled_from(("values", "hidden"))),
                                "result": "value"}, "channels": channels}


@settings(derandomize=True, max_examples=12, deadline=None)
@given(views(), st.sampled_from(("compute", "decide", "invert")), st.integers(0, 7))
def test_boundary_and_observation_only_change_display(view, angle, index):
    boundary, observation_settings = view
    world = toy_world()
    original = generic.generate(world, "plus_one", angle, seed=3, index=index)
    try:
        altered = generic.generate(world, "plus_one", angle, seed=3, index=index,
                                   boundary=boundary, observation=observation_settings)
    except ValueError as error:  # a boundary may keep an unpromoted target closed: no task (review 2, finding 3)
        assume("closed" not in str(error))
        raise
    assert altered.reference == original.reference
    if observation_settings["show"]["input"] != "hidden":  # hidden inputs leave the question (finding 4)
        assert altered.question == original.question
    answer = (original.reference["outcome"] if angle == "compute" else
              original.reference["witness"] if angle == "invert" and index % 2 == 0 else
              original.reference["solutions"] if angle == "invert" else original.reference)
    assert generic.grade(world, altered, answer) == generic.grade(world, original, answer)
    assert altered.boundary == boundary.to_dict()
    assert altered.observation == observation_settings


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from(("plus_one", "normalized", "twice", "parity")),
       st.sampled_from(ANGLES), st.integers(0, 3))
def test_generic_grades_reference_and_never_unknown(definition, angle, index):
    world = toy_world()
    task = generic.generate(world, definition, angle, seed=5, index=index)
    answer = (task.reference["outcome"] if angle == "compute" else
              task.reference["witness"] if angle == "invert" and task.answer_shape == "one_witness" else
              task.reference["solutions"] if angle == "invert" else
              task.reference if angle == "decide" else task.reference["choice"] if angle == "describe" else
              task.reference["definition"])
    assert generic.grade(world, task, answer).correct
    assert not generic.grade(world, task, {"unknown": "fuel"}).correct
    assert all(char == "\n" or 32 <= ord(char) <= 126 for char in task.prompt["en"])
    assert '"node":' not in task.prompt["en"]


@settings(derandomize=True, max_examples=16, deadline=None)
@given(st.sampled_from((object, observation, combinator)), st.sampled_from(("compute", "decide")),
       st.integers(0, 7), st.lists(st.sampled_from(CHANNELS), unique=True))
def test_kind_observation_does_not_change_fact(module, angle, index, channels):
    task = module.generate(angle, 1, index)
    answer = task.reference["outcome"] if angle == "compute" else task.reference["answer"]
    changed = replace(task, observation={"show": {"input": "hidden", "result": "hidden"},
                                         "channels": channels})
    assert changed.reference == task.reference
    assert grade_kinds.grade(changed, answer) == grade_kinds.grade(task, answer)


@settings(derandomize=True, max_examples=15, deadline=None)
@given(st.sampled_from((object, observation, combinator)), st.integers(0, 7))
def test_kind_inversion_checks_all_witnesses_and_nonmembers(module, index):
    task = module.generate("invert", 2, index)
    answer = task.reference["answer"]
    solutions = answer if task.answer_shape == "all_solutions" else [answer]
    witness = replace(task, answer_shape="one_witness", grader={**task.grader, "method": "witness"})
    for member in solutions:
        assert grade_kinds.grade(witness, member).correct
    nonmembers = [item for item in task.grader["scope"]["inputs"] if item not in solutions]
    if nonmembers and task.answer_shape == "all_solutions":
        assert not grade_kinds.grade(witness, nonmembers[index % len(nonmembers)]).correct


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from(operation.WORLD_NAMES), st.integers(0, 7))
def test_operation_inversion_checks_witnesses_and_nonmembers(world, index):
    task = operation.generate(world, "invert", 2, index)
    solutions = task.reference["answer"] if task.answer_shape == "all_solutions" else [task.reference["answer"]]
    witness = replace(task, answer_shape="one_witness", grader={**task.grader, "method": "witness"})
    for member in solutions:
        assert grade.grade(witness, member).correct
    nonmembers = [item for item in task.grader["scope"]["inputs"] if item not in solutions]
    if nonmembers and task.answer_shape == "all_solutions":
        assert not grade.grade(witness, nonmembers[index % len(nonmembers)]).correct


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from((object, observation, combinator)), st.integers(0, 7))
def test_kind_false_verdict_rechecks_counterexample(module, index):
    task = module.generate("decide", 0, index)
    if (task.reference["answer"]["true"] or module is observation or
            module is object and task.question["mode"] not in ("respects_canon", "respects_binary")):
        return
    assert grade_kinds.grade(task, task.reference["answer"]).correct
    assert not grade_kinds.grade(task, {"true": False, "counterexample": "outside scope"}).correct


def test_object_canonical_equality_rejects_wrong_counterexample():
    task = object.generate("decide", 0, 2)
    assert task.reference["answer"]["true"] is False
    assert not grade_kinds.grade(task, {"true": False, "counterexample": "outside scope"}).correct


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from(operation.WORLD_NAMES), st.integers(0, 7))
def test_operation_false_verdict_rechecks_counterexample(world, index):
    task = operation.generate(world, "decide", 0, index)
    if task.reference["answer"]["true"]:
        return
    assert grade.grade(task, task.reference["answer"]).correct
    assert not grade.grade(task, {"true": False, "counterexample": "outside scope"}).correct


@settings(derandomize=True, max_examples=20, deadline=None)
@given(st.sampled_from((object, observation, combinator)), st.sampled_from(ANGLES),
       st.integers(0, 7))
def test_generated_kind_prompts_are_ascii_not_node_json(module, angle, index):
    prompt = module.generate(angle, 4, index).prompt["en"]
    assert all(char == "\n" or 32 <= ord(char) <= 126 for char in prompt)
    if angle not in ("induce", "create"):
        assert '"node":' not in prompt and "{'node':" not in prompt


def test_object_induce_prompt_has_no_node_json():
    prompt = object.generate("induce", 4, 0).prompt["en"]
    assert '"node":' not in prompt and "{'node':" not in prompt


@settings(derandomize=True, max_examples=12, deadline=None)
@given(st.sampled_from(operation.WORLD_NAMES), st.sampled_from(ANGLES), st.integers(0, 7))
def test_generated_operation_prompts_are_ascii_not_node_json(world, angle, index):
    prompt = operation.generate(world, angle, 4, index).prompt["en"]
    assert all(char == "\n" or 32 <= ord(char) <= 126 for char in prompt)
    assert '"node":' not in prompt and "{'node':" not in prompt
