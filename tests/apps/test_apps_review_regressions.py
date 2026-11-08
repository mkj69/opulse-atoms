"""Regressions for the apps boundary with the tasks_v2 record shape."""

import json
import sys
import types

import pytest

from opulse.apps import core, grade, make, register_world
from opulse.apps.adapters import export_openai_jsonl
from opulse.apps.core import _ascii_world


@pytest.fixture
def v2_modules(monkeypatch):
    package = types.ModuleType("opulse.tasks_v2")
    package.__path__ = []
    angles = types.ModuleType("opulse.tasks_v2.angles")
    angles.__path__ = []
    operation = types.ModuleType("opulse.tasks_v2.angles.operation")
    operation.WORLD_NAMES = ("integer", "lists")
    ascii_codec = types.ModuleType("opulse.tasks_v2.ascii")
    task_module = types.ModuleType("opulse.tasks_v2.task")
    grade_module = types.ModuleType("opulse.tasks_v2.grade")

    class Task:
        def __init__(self, data):
            self.data = data
            for key, value in data.items():
                setattr(self, key, value)

        @classmethod
        def from_dict(cls, data):
            return cls(data)

        def to_dict(self):
            return self.data

    def generate(world, angle, seed, index, boundary, observation):
        definitions = {"j14": "op j14(a) = k15(a)", "k15": "op k15(a) = a + 1"}
        reference = "op i14(a) = mod(sum(a), 3)"
        data = {"id": f"{world}/{angle}/{index}", "world": f"{world}@1",
                "angle": angle, "kind": "operation", "answer_shape": "definition" if angle == "induce" else "value",
                "question": {"layer": 1, "definitions": definitions},
                "boundary": boundary, "prompt": {"en": f"World {world}@1. Definitions: layer-0 atoms only. "
                                                      "Return opulse.value/2 for j14(3)."},
                "reference": {"definition": reference} if angle == "induce" else {"outcome": {"ok": 4}}}
        return Task(data)

    def to_ascii_definition(world, definition, definitions=None):
        if definition.startswith("op "):
            raise ValueError("ASCII definitions need no legacy conversion")
        if definition == "i14 a = { a mod 3 }":
            return "op i14(a) = mod(sum(a), 3)"
        return definition

    def grade_v2(task, answer):
        expected = task.reference.get("definition", task.reference.get("outcome"))
        if isinstance(expected, str) and not expected.startswith("op "):
            expected = to_ascii_definition(task.world, expected)
        return types.SimpleNamespace(correct=answer == expected,
                                     reason="correct" if answer == expected else "invalid_definition")

    operation.generate = generate
    ascii_codec.to_ascii_definition = to_ascii_definition
    task_module.Task = Task
    grade_module.grade = grade_v2
    for name, module in (("opulse.tasks_v2", package), ("opulse.tasks_v2.angles", angles),
                         ("opulse.tasks_v2.angles.operation", operation),
                         ("opulse.tasks_v2.ascii", ascii_codec),
                         ("opulse.tasks_v2.task", task_module), ("opulse.tasks_v2.grade", grade_module)):
        monkeypatch.setitem(sys.modules, name, module)
    return operation, grade_module


def test_v2_prompt_preserves_ascii_and_newlines(v2_modules):
    original = v2_modules[0].generate

    def generate(*args, **kwargs):
        task = original(*args, **kwargs)
        task.prompt["en"] += "\nSecond line."
        return task

    v2_modules[0].generate = generate
    task = next(make("integer", level=3, angle="compute"))
    assert "World integer@1." in task["prompt"]
    assert "opulse.value/2" in task["prompt"]
    assert task["prompt"].isascii()
    assert "\nSecond line." in task["prompt"]


def test_legacy_codec_does_not_rewrite_ascii_identifiers():
    text = "World integer@1. Return opulse.value/2.\nUse a / b and ♦₆(a)."
    converted = _ascii_world("integer", text)
    assert "World integer@1. Return opulse.value/2.\n" in converted
    assert "a div b" in converted
    assert "f6(a)" in converted


def test_v2_prompt_includes_every_used_definition(v2_modules):
    for world in ("integer", "lists"):
        for angle in ("compute", "invert", "decide", "describe", "induce", "create"):
            for level in range(1, 6):
                task = next(make(world, level=level, angle=angle))
                definitions = task["_grading"]["task"]["question"]["definitions"]
                for name, definition in definitions.items():
                    assert name in task["prompt"]
                    assert definition in task["prompt"]
                assert "layer-0 atoms only" not in task["prompt"]


def test_v2_prompt_does_not_treat_partial_definition_as_complete(v2_modules):
    original = v2_modules[0].generate

    def generate(*args, **kwargs):
        task = original(*args, **kwargs)
        task.prompt["en"] = "World integer@1. Definitions: op j14(a) = k15(a)1. Compute j14(3)."
        return task

    v2_modules[0].generate = generate
    task = next(make("integer", angle="compute"))
    assert "Additional definitions: op j14(a) = k15(a); op k15(a) = a + 1." in task["prompt"]


def test_v2_definition_answer_is_not_rewritten(v2_modules):
    task = next(make("lists", angle="induce"))
    answer = task["_grading"]["task"]["reference"]["definition"]
    assert grade(task, answer)["correct"]
    assert grade(json.loads(json.dumps(task)), answer)["correct"]


def test_v2_generated_operation_names_are_not_rewritten(v2_modules):
    original = v2_modules[0].generate

    def generate(*args, **kwargs):
        task = original(*args, **kwargs)
        task.reference["definition"] = "op f1(a) = f6(a, a)"
        return task

    v2_modules[0].generate = generate
    task = next(make("integer", angle="induce"))
    assert grade(task, "op f1(a) = f6(a, a)")["correct"]


def test_portable_v2_task_does_not_register_redundant_judge(v2_modules):
    task = next(make("integer", angle="induce"))
    assert task["id"] not in core._JUDGES


def test_v2_export_uses_ascii_definition_codec(v2_modules, tmp_path):
    operation, grade_module = v2_modules
    operation.generate = lambda *args, **kwargs: v2_modules_task(args[0], args[1], kwargs)
    task = next(make("integer", angle="induce"))
    output = export_openai_jsonl([task], tmp_path / "examples.jsonl")
    assistant = json.loads(output.read_text().splitlines()[0])["messages"][1]["content"]
    assert assistant == "op i14(a) = mod(sum(a), 3)"
    from opulse.tasks_v2.task import Task

    assert grade_module.grade(Task.from_dict(task["_grading"]["task"]), assistant).correct


def test_v2_export_preserves_ascii_reference(v2_modules, tmp_path):
    task = next(make("integer", angle="induce"))
    output = export_openai_jsonl([task], tmp_path / "answers.jsonl")
    assistant = json.loads(output.read_text().splitlines()[0])["messages"][1]["content"]
    assert assistant == task["_grading"]["task"]["reference"]["definition"]


def test_real_v2_prompts_and_export_when_available(tmp_path):
    pytest.importorskip("opulse.tasks_v2.angles.operation")
    from opulse.tasks_v2.grade import grade as grade_v2
    from opulse.tasks_v2.task import Task

    for world in ("integer", "lists"):
        for angle in ("compute", "invert", "decide", "describe", "induce", "create"):
            for level in range(1, 6):
                task = next(make(world, level=level, angle=angle))
                raw = Task.from_dict(task["_grading"]["task"])
                for name, definition in raw.question.get("definitions", {}).items():
                    assert name in task["prompt"]
                    assert definition in task["prompt"]
                assert task["prompt"].isascii()
                if task["answer_shape"] == "definition":
                    output = export_openai_jsonl([task], tmp_path / "examples.jsonl")
                    assistant = json.loads(output.read_text().splitlines()[0])["messages"][1]["content"]
                    assert grade_v2(raw, assistant).correct
                    assert grade(task, assistant)["correct"]


def v2_modules_task(world, angle, kwargs):
    from opulse.tasks_v2.task import Task

    return Task({"id": "legacy-definition", "world": f"{world}@1", "angle": angle,
                 "kind": "operation", "answer_shape": "definition", "boundary": kwargs["boundary"],
                 "question": {"layer": 1, "definitions": {}},
                 "prompt": {"en": "World integer@1. Definitions: layer-0 atoms only."},
                 "reference": {"definition": "i14 a = { a mod 3 }"}})


@pytest.mark.parametrize("kind", ["law", "bridge"])
def test_registered_provider_accepts_six_kinds(kind):
    register_world("six-kinds", lambda *args: (
        {"id": f"six-kinds/{kind}", "prompt": "Check", "answer_shape": "verdict", "metadata": {}},
        lambda answer: {"correct": answer is True, "reason": "correct"}))
    task = next(make("six-kinds", open_kinds={kind}, kind=kind))
    assert grade(task, True)["correct"]


def test_provider_judge_survives_long_stream():
    register_world("long-stream", lambda *args: (
        {"id": f"long-stream/{args[-1]}", "prompt": "Check", "answer_shape": "verdict", "metadata": {}},
        lambda answer: {"correct": answer is True, "reason": "correct"}))
    stream = make("long-stream")
    first = next(stream)
    for _ in range(4096):
        next(stream)
    assert grade(first, True)["correct"]
