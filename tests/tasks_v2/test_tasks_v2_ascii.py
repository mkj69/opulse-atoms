"""ASCII conversion for all published operation definitions and prompts."""

import json
from pathlib import Path

import pytest

from opulse.tasks_v2 import engine
from opulse.tasks_v2.angles.operation import (
    ANGLES,
    VERSIONS,
    WORLD_NAMES,
    _closure,
    _rows,
    generate,
)
from opulse.tasks_v2.ascii import (
    grade_ascii,
    names,
    parse_ascii_definition,
    parse_ascii_expression,
    to_ascii_definition,
    to_ascii_expression,
)
from opulse.tasks_v2.grade import executable_task


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_all_published_definitions_round_trip(world):
    world_id = f"{world}@{VERSIONS[world]}"
    operators, primitives = names(world_id)
    assert len(set(operators.values())) == len(operators)
    assert len(operators) == len(_rows(world))
    assert primitives
    for row in _rows(world).values():
        dependencies = _closure(world, row.get("uses", ()), exclude=(row["name"],))
        original = engine.parse_definition(world_id, row["definition"], dependencies)
        ascii_rule = to_ascii_definition(world_id, row["definition"], dependencies)
        assert ascii_rule.isascii() and ascii_rule.startswith("op ")
        reconstructed = parse_ascii_definition(world_id, ascii_rule)
        assert engine.parse_definition(world_id, reconstructed, dependencies) == original
        assert engine.parse_definition(world_id, parse_ascii_definition(world_id, ascii_rule + " L1"),
                                       dependencies) == original
        assert parse_ascii_definition(world_id, row["definition"]) == row["definition"]


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_published_example_expressions_and_prompt_surfaces(world):
    for row in _rows(world).values():
        dependencies = _closure(world, [row["name"]])
        for example in row["examples"]:
            assert to_ascii_expression(world, example["expression"], dependencies).isascii()
    for angle in ANGLES:
        for index in range(8):
            task = generate(world, angle, index=index)
            assert task.prompt["en"].isascii()
            assert task.open_kinds == ["operation"]


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_ascii_answers_are_graded(world):
    for angle in ("induce", "create"):
        task = generate(world, angle)
        rule = task.reference["definition"]
        assert grade_ascii(task, rule).correct
        assert grade_ascii(task, executable_task(task).reference["definition"]).correct


def test_grade_accepts_ascii_and_legacy_definitions():
    from opulse.tasks_v2.angles.operation import generate
    from opulse.tasks_v2.grade import grade

    task = generate("integer", "induce", index=0)
    legacy = executable_task(task).reference["definition"]
    ascii_answer = task.reference["definition"]
    assert grade(task, legacy).correct
    assert grade(task, ascii_answer).correct


def test_choice_accepts_ascii_option_names():
    from opulse.tasks_v2.angles.operation import generate
    from opulse.tasks_v2.grade import grade

    task = generate("integer", "describe", index=2)
    ascii_name = task.reference["choice"]
    assert ascii_name in task.prompt["en"]
    assert grade(task, ascii_name).correct and grade(task, executable_task(task).reference["choice"]).correct


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_ascii_expression_round_trip(world):
    task = generate(world, "compute", index=5)
    executable = executable_task(task)
    assert parse_ascii_expression(task.world, task.question["expression"]) == executable.question["expression"]


@pytest.mark.parametrize("world", WORLD_NAMES)
def test_committed_operation_payload_is_ascii(world):
    root = Path("worlds/tasks") / f"{world}@{VERSIONS[world]}"
    for angle in ANGLES:
        path = root / f"operation_{angle}.json"
        data = path.read_bytes()
        assert data.isascii(), path
        for task in json.loads(data):
            for field in ("question", "reference", "source", "prompt"):
                assert json.dumps(task[field], ensure_ascii=False).isascii(), (path, field)
