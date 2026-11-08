"""Kernel-backed object, observation and combinator task coverage."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.values import Ok, boolean, outcome_equal, truth
from opulse.tasks_v2 import build_kinds, grade_kinds, library_defs
from opulse.tasks_v2 import grade as legacy_grade
from opulse.tasks_v2 import kernel_engine as engine
from opulse.tasks_v2.angles import combinator, object, observation, operation
from opulse.tasks_v2.task import Task


@pytest.mark.parametrize("module", (object, observation, combinator))
@pytest.mark.parametrize("angle", object.ANGLES)
def test_matrix(module, angle):
    tasks = [module.generate(angle, 42, index) for index in range(8)]
    assert tasks == [module.generate(angle, 42, index) for index in range(8)]
    assert len({json.dumps(task.question, sort_keys=True) for task in tasks}) == 8
    for task in tasks:
        assert Task.from_dict(task.to_dict()) == task
        answer = next(task.reference[key] for key in ("outcome", "answer", "choice", "definition") if key in task.reference)
        assert grade_kinds.grade(task, answer).correct
        if angle == "compute":
            bad = {"ok": engine.wire("wrong")}
        elif angle == "invert":
            bad = [] if task.answer_shape == "all_solutions" else {"t": "int", "v": 9999}
        elif angle == "decide":
            bad = {"true": not answer["true"]}
        elif angle == "describe":
            bad = "not an option"
        elif module is object:
            bad = (n.to_json(n.Call("num", (n.Var("x"),))) if angle == "induce" else
                   {**answer, "canon": n.to_json(n.Call("num", (n.Var("x"),)))})
        elif module is observation:
            bad = {**answer, "reads": ["front_colour"]}
        else:
            bad = n.to_json(n.Call("f", (n.Var("x"),)))
        assert not grade_kinds.grade(task, bad).correct


def test_frozen_samples(tmp_path):
    files = build_kinds.build(0, 8, tmp_path)
    assert len(files) == 19
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "worlds/tasks"
    for path in files:
        assert path.read_bytes() == (root / path.relative_to(tmp_path)).read_bytes()
        for task in json.loads(path.read_text()):
            prompt = task["prompt"]["en"]
            assert all(char in "\n\r\t" or 32 <= ord(char) <= 126 for char in prompt)
            assert "Answer format:" in prompt
            assert '{"t":' not in prompt and "{'t':" not in prompt
            assert '"state_delta"' not in prompt and "opulse.value/2 JSON" not in prompt
            if task["angle"] == "describe":
                assert task["family"] not in prompt
                assert all(task["family"] not in option for option in task["question"]["options"])
                assert "target T" in prompt and "->" in prompt
                assert all(option in prompt for option in task["question"]["options"])
            else:
                assert task["family"] in prompt
            if task["angle"] == "invert":
                assert "Allowed" in prompt or "Candidate operations" in prompt
                assert task["question"]["target"] is not None
                assert engine._notation(task["question"]["target"]) in prompt
            if task["angle"] == "decide":
                assert "Decide" in prompt or "Does" in prompt
                if "claim" in task["question"]:
                    assert task["question"]["claim"] in prompt


def test_reference_diversity_and_nontrivial_fraction_inversion():
    for module in (object, observation, combinator):
        families = {module.generate(angle, 0, index).family
                    for angle in module.ANGLES for index in range(8)}
        assert len(families) >= 3
    for index in range(8):
        task = object.generate("invert", 0, index)
        target = engine.unwire(task.question["target"])
        assert all(engine.unwire(raw) != target for raw in task.grader["scope"]["inputs"])
        assert task.reference["answer"]


def test_distinct_decision_claims_are_rechecked():
    for index in (4, 5):
        task = object.generate("decide", 0, index)
        assert "partner" in task.question
        assert grade_kinds.grade(task, task.reference["answer"]).correct
        assert not grade_kinds.grade(task, {"true": not task.reference["answer"]["true"]}).correct
    for index in (2, 3):
        task = combinator.generate("decide", 0, index)
        assert task.question["mode"] in ("seq_swap", "fold_sum")
        assert grade_kinds.grade(task, task.reference["answer"]).correct
        assert not grade_kinds.grade(task, {"true": not task.reference["answer"]["true"]}).correct
    memory = observation.generate("decide", 0, 3)
    assert memory.question["mode"] == "memory_distinguish"
    assert grade_kinds.grade(memory, memory.reference["answer"]).correct
    assert not grade_kinds.grade(memory, {"true": False}).correct


def test_description_alternatives_are_real_and_distinguishable():
    records, definitions = library_defs.records()
    names = {record.name for record in records}
    assert {"fraction", "fraction_raw", "fraction_positive"} <= names
    alternatives = object.generate("describe", 3, 0).question["options"]
    assert all("fraction" not in option for option in alternatives)
    raw = engine.fraction(2, 4)
    negative = engine.fraction(-1, 2)
    assert engine.run("integer@1", n.Call("fraction", (n.Lit(raw),)), definitions).outcome != engine.run(
        "integer@1", n.Call("fraction_raw", (n.Lit(raw),)), definitions).outcome
    assert engine.run("integer@1", n.Call("fraction", (n.Lit(negative),)), definitions).outcome != engine.run(
        "integer@1", n.Call("fraction_positive", (n.Lit(negative),)), definitions).outcome


def test_describe_examples_refute_each_other_definition():
    definitions = library_defs.records()[1]
    for index in range(8):
        for module in (object, observation, combinator):
            task = module.generate("describe", 0, index)
            examples = task.question["examples"]
            for option in task.question["options"]:
                if module is object:
                    name = ("fraction_raw" if option.startswith("Preserve each") else
                            "fraction_positive" if "discard" in option else "fraction")
                    outputs = [engine.run("integer@1", n.Call(name, (n.Lit(engine.unwire(raw)),)),
                                          definitions).outcome.value for raw, _ in examples]
                    expected = [engine.unwire(output) for _, output in examples]
                elif module is observation:
                    name = ("front_wall_only" if option.startswith("The wall") else
                            "front_water_only" if option.startswith("The water") else "front_free")
                    outputs = [observation.observed(name, engine.unwire(raw)) for raw, _ in examples]
                    expected = [truth(engine.unwire(output)) for _, output in examples]
                else:
                    outputs = []
                    expected = [sample["output"] for sample in examples]
                    for sample in examples:
                        if task.family == "fold":
                            function = ("sub" if option.startswith("Apply subtraction") else
                                        "mul" if option.startswith("Apply multiplication") else "add")
                            args = (kernel.FnRef(function), sample["initial"], engine.unwire(sample["input"]))
                            name = "fold"
                        elif option.startswith("Apply a second"):
                            name = "seq"
                            args = (kernel.FnRef(sample["function"]), kernel.FnRef(sample["second"]), sample["input"])
                        elif option.startswith("Apply the passed operation exactly three"):
                            name = "repeat"
                            args = (kernel.FnRef(sample["function"]), 3, sample["input"])
                        else:
                            name = "twice"
                            args = (kernel.FnRef(sample["function"]), sample["input"])
                        result = engine.run("integer@1", n.Call(name, tuple(n.Lit(arg) for arg in args)),
                                            definitions).outcome
                        assert isinstance(result, Ok)
                        outputs.append(result.value)
                assert (outputs == expected) == (option == task.reference["choice"])


def test_opened_decision_definitions_cover_each_named_side():
    for index in range(8):
        for module in (object, observation, combinator):
            task = module.generate("decide", 0, index)
            prompt = task.prompt["en"]
            assert "Opened definition: " in prompt
            assert task.family in prompt
            if module is object and "operation" in task.question:
                assert f"op {task.question['operation']}(" in prompt
            if module is combinator:
                assert task.question["claim"] in prompt
                if task.question.get("mode") == "fold_sum":
                    assert "op isum(" in prompt
                elif task.question.get("mode") != "seq_swap":
                    assert "comb @repeat[" in prompt
            assert "isum(List<xs>).." not in prompt


def test_operation_grading_is_unchanged():
    task = operation.generate("integer@1", "compute", 2, 0)
    assert grade_kinds.grade(task, task.reference["outcome"]) == legacy_grade.grade(
        task, task.reference["outcome"])


def test_kind_boundary_and_unfolding():
    records, definitions = library_defs.records()
    opened_steps = {
        "fraction": [("fraction_canon", 1)], "fraction_raw": [("fraction_raw_base", 1)],
        "fraction_positive": [("fraction_positive_base", 1)], "ilist": [("cons", 1)],
        "three": [("natural_succ", 1)] * 3, "ilen": [("loop", 10)],
        "isum": [("loop", 13)], "iappend": [("loop", 9)],
        "frac_add": [("frac_add_base", 1)], "frac_mul": [("frac_mul_base", 1)],
        "front_free": [("front_wall", 1), ("front_water", 1)],
        "front_wall_only": [("front_wall", 1)], "front_water_only": [("front_water", 1)],
        "blocked_count": [("front_wall", 1), ("front_water", 1)],
        "twice": [("neg", 1)] * 2, "seq": [("neg", 1)] * 2,
        "repeat": [("iterate", 10)], "fold": [("reduce", 13)],
    }
    samples = {
        "fraction": ("integer@1", (engine.fraction(2, 4),)),
        "fraction_raw": ("integer@1", (engine.fraction(2, 4),)),
        "fraction_positive": ("integer@1", (engine.fraction(-2, 4),)),
        "ilist": ("integer@1", (2, engine.ilist((3,)))),
        "three": ("successor@1", ()),
        "ilen": ("integer@1", (engine.ilist((1, 2, 3)),)),
        "isum": ("integer@1", (engine.ilist((1, 2, 3)),)),
        "iappend": ("integer@1", (engine.ilist((1, 2)), engine.ilist((3,)))),
        "frac_add": ("integer@1", (engine.fraction(1, 2), engine.fraction(1, 3))),
        "frac_mul": ("integer@1", (engine.fraction(1, 2), engine.fraction(2, 3))),
        "front_free": ("action@1", (observation.states(0, 0)[0],)),
        "front_wall_only": ("action@1", (observation.states(0, 0)[0],)),
        "front_water_only": ("action@1", (observation.states(0, 0)[0],)),
        "blocked_count": ("action@1", (observation.states(0, 0)[1], 2)),
        "twice": ("integer@1", (kernel.FnRef("neg"), 3)),
        "repeat": ("integer@1", (kernel.FnRef("neg"), 3, 3)),
        "seq": ("integer@1", (kernel.FnRef("neg"), kernel.FnRef("neg"), 3)),
        "fold": ("integer@1", (kernel.FnRef("add"), 0, engine.ilist((1, 2, 3)))),
    }
    for record in records:
        world, args = samples[record.name]
        scope = engine.scope(world, definitions)
        node = n.Call(record.name, tuple(n.Lit(item) for item in args))
        original = engine.run(world, node, definitions, trace=True)
        unfolded = engine.run(world, kernel.inline(node, scope), definitions)
        assert not (original.outcome is None)
        assert outcome_equal(original.outcome, unfolded.outcome), record.name
        assert original.steps == unfolded.steps, record.name
        trace = original.trace
        assert trace is not None
        closed = flatten_calls(trace, Boundary())
        opened = flatten_calls(trace, Boundary(open_names=frozenset({record.name}),
                                                       kinds=frozenset({record.kind})))
        assert [(step.name, step.steps) for step in closed] == [(record.name, original.steps)]
        assert [(step.name, step.steps) for step in opened] == opened_steps[record.name]
        assert record.name not in {step.name for step in opened}
        for boundary in (Boundary(), Boundary(open_names=frozenset({record.name}), kinds=frozenset({record.kind}))):
            assert original.steps == engine.run(world, node, definitions).steps
    for record in records:
        assert not record.validate()
        assert record.evidence.method in ("exhaustive", "bounded")
    scope = engine.scope("integer@1", definitions)
    trace = engine.run("integer@1", n.Call("MUL", (n.Lit(3), n.Lit(4))), definitions, trace=True).trace
    assert trace is not None
    visible = flatten_calls(trace, Boundary(depth=1, open_names=frozenset({"MUL"}),
                                            kinds=frozenset({"operation"})))
    assert [(step.name, step.steps) for step in visible] == (
        [("zero_test", 1), ("sub", 1), ("add", 1)] * 4 + [("zero_test", 1)])
    assert not {"MUL", "loop"} & {step.name for step in visible}


def test_obligations_reject_violations():
    values = [engine.fraction(num, den) for num in range(-12, 13) for den in range(-12, 13) if den]
    assert library_defs.verify_canon(lambda value: value.fields[1] != 0,
                                     engine.canonical, (lambda value: engine.canonical(value),), values)
    assert not library_defs.verify_canon(lambda value: True,
                                         lambda value: engine.fraction(value.fields[0] + 1, value.fields[1]),
                                         (), values)
    assert not library_defs.verify_canon(lambda value: True, engine.canonical,
                                         (lambda value: value.fields[0],), values)
    state = observation.states(0, 0)
    def evaluate(node, env=None):
        return kernel.evaluate(node, env or {}, engine.scope("action@1")).outcome
    forbidden = library_defs.ObservationSpec("leak", ("front_colour",),
                                               n.Call("front_colour", (n.Var("state"),)))
    assert not library_defs.verify_observation(forbidden, ("front_wall",), {}, state, evaluate)
    act = library_defs.ObservationSpec("act", ("front_wall",), n.Call("forward", (n.Var("state"),)))
    assert not library_defs.verify_observation(act, ("front_wall",), {"forward": "act"}, state, evaluate)
    correct = next(record.body for record in library_defs.records()[0] if record.name == "twice")
    wrong = n.Call("f", (n.Var("x"),))
    assert library_defs.verify_combinator(correct, correct, ("neg", "triangle"), (1, 2))
    assert not library_defs.verify_combinator(wrong, correct, ("neg", "triangle"), (1, 2))


def test_hidden_truth_is_still_judged():
    task = observation.generate("decide", 7, 1)
    assert task.observation["show"]["input"] == "hidden"
    assert task.judge_view == "full_state"
    assert grade_kinds.grade(task, task.reference["answer"]).correct
    visible = replace(task, observation={**task.observation, "show": {"input": "full_state", "result": "value"}})
    assert grade_kinds.grade(task, task.reference["answer"]) == grade_kinds.grade(visible, visible.reference["answer"])


def test_create_observation_accepts_other_separating_rules_and_safe_memory():
    task = observation.generate("create", 4, 1)
    blocked = n.Case(((n.Test(n.Call("front_wall", (n.Var("state"),))), n.Lit(boolean(True))),
                      (n.Test(n.Call("front_water", (n.Var("state"),))), n.Lit(boolean(True)))),
                     n.Lit(boolean(False)))
    candidate = {"reads": ["front_wall", "front_water"], "body": n.to_json(blocked),
                 "memory": {"sort": "int", "init": n.to_json(n.Lit(0)),
                            "step": n.to_json(n.Call("add", (n.Var("memory"), n.Lit(1))))}}
    assert grade_kinds.grade(task, candidate).correct
    leak = {**candidate, "memory": {**candidate["memory"], "step": n.to_json(
        n.Call("front_colour", (n.Var("state"),)))}}
    assert not grade_kinds.grade(task, leak).correct
    assert not grade_kinds.grade(observation.generate("induce", 4, 1), candidate).correct


def test_object_operation_claim_requires_rechecked_counterexample():
    task = object.generate("decide", 4, 0)
    assert task.question["operation"] == "raw_num"
    assert grade_kinds.grade(task, task.reference["answer"]).correct
    assert grade_kinds.grade(task, {"true": False,
                                    "counterexample": [task.question["right"], task.question["left"]]}).correct
    assert not grade_kinds.grade(task, {"true": False, "counterexample": [
        engine.wire(engine.fraction(1, 2)), engine.wire(engine.fraction(1, 3))]}).correct
    assert grade_kinds.grade(object.generate("decide", 4, 1), {"true": True}).correct


def test_object_definition_rejects_zero_denominator_as_valid():
    task = object.generate("create", 4, 0)
    answer = task.reference["definition"]
    assert grade_kinds.grade(task, answer).correct
    invalid = {**answer, "valid": n.to_json(n.Lit(boolean(True)))}
    assert not grade_kinds.grade(task, invalid).correct
    assert not grade_kinds.grade(task, {**answer, "canon": {1, 2}}).correct


def test_reusable_combinator_rejects_extra_steps_before_held_out_inputs():
    task = combinator.generate("create", 4, 1)
    body = n.Case(((n.Test(n.Call("zero_test", (n.Call("sub", (n.Var("x"), n.Lit(21))),))),
                    n.Lit(0)),), n.Call("f", (n.Call("f", (n.Var("x"),)),)))
    candidate = n.to_json(body)
    assert not grade_kinds.grade(replace(task, variant="one_shot"), candidate).correct
    assert not grade_kinds.grade(task, candidate).correct
    assert grade_kinds.grade(task, task.reference["definition"]).correct


def test_reusable_object_rechecks_held_out_interface():
    task = object.generate("create", 4, 1)
    task = replace(task, grader={**task.grader, "scope": {**task.grader["scope"], "fraction_bound": 2}})
    reference = task.reference["definition"]
    altered = {**reference, "interface": {**reference["interface"], "num": n.to_json(
        n.Case(((n.Test(n.Call("zero_test", (n.Call("sub", (
            n.Call("num", (n.Var("x"),)), n.Lit(13))),))), n.Lit(0)),),
               n.Call("num", (n.Var("x"),))))}}
    assert grade_kinds.grade(replace(task, variant="one_shot"), altered).correct
    assert not grade_kinds.grade(task, altered).correct


def test_boundary_opens_each_kind_without_changing_judgement():
    definitions = library_defs.records()[1]
    free_state = next(state for state in observation.states(4, 0)
                      if observation.observed("front_free", state))
    cases = (("successor@1", "three", (), "object", [("natural_succ", 1)] * 3, 3),
             ("action@1", "front_free", (free_state,), "observation",
              [("front_wall", 1), ("front_water", 1)], 2),
             ("integer@1", "twice", (kernel.FnRef("neg"), 3), "combinator", [("neg", 1)] * 2, 2))
    for world, name, args, kind, expected_open, count in cases:
        result = engine.run(world, n.Call(name, tuple(n.Lit(value) for value in args)), definitions, trace=True)
        assert result.trace is not None
        closed = flatten_calls(result.trace, Boundary())
        opened = flatten_calls(result.trace, Boundary(open_names=frozenset({name}), kinds=frozenset({kind})))
        assert [(step.name, step.steps) for step in closed] == [(name, count)]
        assert [(step.name, step.steps) for step in opened] == expected_open
        assert name not in {step.name for step in opened}
        assert {child for child, _ in expected_open}.isdisjoint(step.name for step in closed)
        assert result.steps == count
        assert result.steps == engine.run(world, kernel.inline(n.Call(name, tuple(n.Lit(value) for value in args)),
                                                         engine.scope(world, definitions)), definitions).steps


@pytest.mark.parametrize("module", (object, observation, combinator))
def test_task_boundary_changes_only_the_display(module):
    task = module.generate("compute", 6, 1)
    reference = task.reference["outcome"]
    shown = replace(task, boundary={**task.boundary, "open_names": [task.family],
                                    "kinds": [task.kind]})
    hidden = replace(task, boundary={**task.boundary, "open_names": [],
                                     "keep_names": [task.family]})
    assert grade_kinds.grade(shown, reference).correct
    assert grade_kinds.grade(hidden, reference).correct


@pytest.mark.parametrize("module,index", ((object, 11), (observation, 0), (combinator, 1)))
def test_resource_unknown_never_grades_correct(module, index):
    task = module.generate("compute", 9, index)
    limited = replace(task, grader={**task.grader, "fuel": 1})
    assert not grade_kinds.grade(limited, task.reference["outcome"]).correct


def test_compute_accepts_domain_bottom_but_not_unknown():
    task = object.generate("compute", 3, 1)
    task = replace(task, question={**task.question, "value": engine.wire(engine.fraction(1, 0))})
    assert grade_kinds.grade(task, {"bottom": "invalid"}).correct
    assert not grade_kinds.grade(task, {"unknown": "fuel"}).correct
