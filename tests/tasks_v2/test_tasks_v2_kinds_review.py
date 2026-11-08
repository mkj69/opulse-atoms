"""Regressions for bounded kind grading (docs/spec/atoms-v2.md, sections 9 and 11)."""

import json
from dataclasses import replace
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms import notation
from opulse.atoms.values import boolean
from opulse.tasks_v2 import grade_kinds
from opulse.tasks_v2 import kernel_engine as engine
from opulse.tasks_v2.angles import (
    bridge,
    combinator,
    law,
    object,
    observation,
    template,
)
from opulse.tasks_v2.task import Task


def test_committed_definition_prompts_do_not_contain_target_bodies():
    root = Path(__file__).resolve().parents[2] / "worlds/tasks"
    for path in (*root.glob("*/object_induce.json"), *root.glob("*/object_create.json"),
                 *root.glob("*/combinator_induce.json"), *root.glob("*/combinator_create.json"),
                 *root.glob("*/observation_induce.json"), *root.glob("*/observation_create.json"),
                 *root.glob("*/law_induce.json"), *root.glob("*/law_create.json"),
                 *root.glob("*/bridge_induce.json"), *root.glob("*/bridge_create.json"),
                 *root.glob("templates/*_induce.json"), *root.glob("templates/*_create.json")):
        for record in json.loads(path.read_text(encoding="utf-8")):
            task = Task.from_dict(record)
            reference = task.reference.get("definition")
            prompt = "".join(task.prompt["en"].split())
            if task.kind == "observation":
                assert f"Opened definition: obs ?{task.question['concept']}" not in task.prompt["en"]
            if task.family == "template":
                assert '"body":' not in task.prompt["en"]
                continue
            if task.kind in ("law", "bridge"):
                bodies = [reference]
            elif task.kind == "object" and task.angle == "create":
                bodies = [notation.print_expr(n.from_json(body)) for name, body in reference.items()
                          if name != "interface"]
                bodies += [notation.print_expr(n.from_json(body)) for body in reference["interface"].values()]
            else:
                body = reference["body"] if task.kind == "observation" else reference
                bodies = [notation.print_expr(n.from_json(body))]
            for body in bodies:
                assert "".join(body.split()) not in prompt, (path, task.id, body)


@settings(deadline=None)
@given(st.sampled_from((object, observation, combinator, law, bridge, template)))
def test_generated_definition_prompts_hide_reference(module):
    for angle in ("induce", "create"):
        task = module.generate(angle, 0, 0)
        if module is template:
            target = "obj Quot[T, canon] = refine T canon(canon)"
        elif module in (law, bridge):
            target = task.reference["definition"]
        else:
            definition = task.reference["definition"]
            if module is object and angle == "create":
                definition = definition["canon"]
            elif module is observation:
                definition = definition["body"]
            target = notation.print_expr(n.from_json(definition))
        assert "".join(target.split()) not in "".join(task.prompt["en"].split())


@settings(deadline=None)
@given(st.sampled_from((object, observation, combinator)))
def test_kind_description_ignores_poisoned_reference_choice(module):
    for index in (0, 2, 4):
        task = module.generate("describe", 0, index)
        correct = task.reference["choice"]
        wrong = next(option for option in task.question["options"] if option != correct)
        poisoned = replace(task, reference={**task.reference, "choice": wrong})
        assert grade_kinds.grade(poisoned, correct).correct
        assert not grade_kinds.grade(poisoned, wrong).correct


def test_object_interface_compares_all_bounded_pairs():
    task = object.generate("create", 0, 0)
    answer = object.definition()
    original = n.from_json(answer["interface"]["fraction_eq"])
    first = n.Call("fraction_eq", (n.Var("left"), n.Lit(engine.fraction(1, 2))))
    second = n.Call("fraction_eq", (n.Var("right"), n.Lit(engine.fraction(1, 3))))
    answer["interface"]["fraction_eq"] = n.to_json(n.Case(
        ((n.Test(first), n.Case(((n.Test(second), n.Lit(boolean(True))),), original)),), original))
    assert grade_kinds.grade(task, object.definition()).correct
    assert not grade_kinds.grade(task, answer).correct


@settings(max_examples=6, deadline=None)
@given(st.integers(1, 2))
def test_object_bounded_interface_rejects_changed_constructor(denominator):
    task = object.generate("create", 0, 0)
    task = replace(task, grader={**task.grader, "scope": {**task.grader["scope"], "fraction_bound": 2}})
    answer = object.definition()
    answer["interface"]["make_fraction"] = n.to_json(n.Call("make_fraction", (n.Var("num"), n.Lit(denominator))))
    assert not grade_kinds.grade(task, answer).correct


def test_combinator_definition_rejects_extra_layer_zero_step():
    task = combinator.generate("induce", 0, 0)
    body = n.from_json(task.reference["definition"])
    extra = n.Let("extra", n.Call("zero_test", (n.Lit(0),)), body)
    assert grade_kinds.grade(task, task.reference["definition"]).correct
    assert not grade_kinds.grade(task, n.to_json(extra)).correct


@settings(max_examples=6, deadline=None)
@given(st.sampled_from((object, observation, combinator)))
def test_empty_all_solutions_only_when_scope_has_no_matches(module):
    task = module.generate("invert", 0, 0)
    target = (engine.wire(engine.fraction(999, 1)) if module is object else engine.wire(999999))
    task = replace(task, question={**task.question, "target": target},
                   answer_shape="all_solutions")
    assert grade_kinds.grade(task, []).correct
    assert not grade_kinds.grade(task, None).correct
    assert not grade_kinds.grade(task, "[]").correct
    assert not grade_kinds.grade(replace(task, answer_shape="one_witness",
                                         grader={**task.grader, "method": "witness"}), []).correct
    assert not grade_kinds.grade(task, ["outside scope"]).correct


def test_empty_answer_rejected_if_scope_has_match():
    task = object.generate("invert", 0, 0)
    assert task.reference["answer"]
    assert not grade_kinds.grade(task, []).correct


def test_wrong_counterexample_must_be_in_scope_and_refute_equality():
    task = object.generate("decide", 0, 2)
    assert grade_kinds.grade(task, task.reference["answer"]).correct
    assert not grade_kinds.grade(task, {"true": False, "counterexample": "outside scope"}).correct
    assert not grade_kinds.grade(task, {"true": False, "counterexample": [task.question["left"]] * 2}).correct


def test_old_frozen_decide_with_implicit_pair_scope_still_grades(challenge_grading):
    root = Path(__file__).resolve().parents[2]
    challenge = json.loads((root / "docs/assets/data/challenge/v2.json").read_text())
    grading = challenge_grading
    record = next(entry for entry in challenge["ladders"]["decide"]
                  if entry["kind"] == "object" and entry["world"] == "integer@1")
    # Review's public challenge hardening moved references and native tasks to private grading data.
    task = Task.from_dict(grading[record["id"]]["task"])
    assert grade_kinds.grade(task, grading[record["id"]]["reference"]).correct
    assert not grade_kinds.grade(task, {"true": False, "counterexample": "outside scope"}).correct


def test_definition_prompts_use_notation_not_node_json():
    for module in (object, observation, combinator):
        for angle in ("induce", "create"):
            prompt = module.generate(angle, 4, 0).prompt["en"]
            assert '"node":' not in prompt and "{'node':" not in prompt
            assert "Answer format:" in prompt
