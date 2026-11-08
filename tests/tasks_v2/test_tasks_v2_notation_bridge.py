"""ASCII learner answer and prompt invariants for generic task worlds."""

import json
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms import nodes, notation
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok, boolean, decode_outcome
from opulse.tasks_v2.angles import combinator, object, observation
from opulse.tasks_v2.fixtures import computer_world, toy_world
from opulse.tasks_v2.generic import _text, generate, grade, parse_answer_definition
from opulse.tasks_v2.grade_kinds import grade as grade_kind


@given(st.integers(min_value=-10000, max_value=10000))
def test_value_round_trip(number):
    text = notation.print_value(number)
    assert notation.print_value(notation.parse_value(text)) == text


@given(st.lists(st.integers(min_value=-100, max_value=100), min_size=1, max_size=5))
def test_expression_round_trip(numbers):
    expression = nodes.Call("add", (nodes.Lit(numbers[0]), nodes.Lit(numbers[-1])))
    text = notation.print_expr(expression)
    assert notation.print_expr(notation.parse_expr(text)) == text


def test_ascii_definitions_grade_like_node_json():
    world = toy_world()
    for name in ("normalized", "plus_one", "twice", "parity"):
        for angle in ("induce", "create"):
            task = generate(world, name, angle, seed=7, index=0)
            body = nodes.from_json(task.reference["definition"])
            text = notation.print_expr(body, world.library())
            assert notation.print_expr(notation.parse_expr(text, world.library()), world.library()) == text
            assert grade(world, task, text).correct == grade(world, task,
                                                              {"body": task.reference["definition"]}).correct
            assert '"t":' not in task.prompt["en"]
            assert all(char == "\n" or 32 <= ord(char) < 127 for char in task.prompt["en"])


def test_ascii_value_grades_like_node_json_outcome():
    world = toy_world()
    task = generate(world, "plus_one", "compute", seed=1, index=0)
    expected = decode_outcome(task.reference["outcome"])
    assert isinstance(expected, Ok)
    assert grade(world, task, notation.print_value(expected.value)).correct
    assert grade(world, task, task.reference["outcome"]).correct


def test_bottom_value_round_trip():
    outcome = Bottom("bad input")
    assert notation.parse_value(notation.print_value(outcome)) == outcome


def test_generic_boolean_card_accepts_ascii_value():
    world = toy_world()
    world.library()._definitions["always_true"] = Definition(
        "always_true", "operation", "invented", 1, (),
        OperationSpec("always_true", "transform", (), Edge("bool"), "true"),
        nodes.Lit(boolean(True)), status="callable")
    task = generate(world, "always_true", "compute", seed=1, index=0)
    assert grade(world, task, "true").correct
    assert grade(world, task, task.reference["outcome"]).correct


def test_ascii_definition_parser_accepts_declaration_and_expression():
    body = nodes.Call("inc", (nodes.Var("arg0"),))
    declaration = "op plus_one(arg0: int) -> int = inc(arg0) L1"
    assert parse_answer_definition(declaration) == (body, None)
    assert parse_answer_definition("inc(arg0)") == (body, None)
    assert parse_answer_definition({"body": nodes.to_json(body)}) == (body, None)


def test_every_reference_body_round_trip():
    for world in (toy_world(), computer_world()):
        for definition in world.library().definitions.values():
            if not isinstance(definition.body, nodes.NODE_TYPES):
                continue
            text = _text(world, definition.body)
            assert notation.print_expr(notation.parse_expr(text, world.library()), world.library()) == text


def test_computer_program_ascii_grades_like_node_json():
    world = computer_world()
    task = generate(world, "mul", "induce", seed=4, index=0)
    text = _text(world, world.library().get("mul").body)
    assert grade(world, task, text).correct == grade(world, task,
                                                     {"body": task.reference["definition"]}).correct
    assert grade(world, task, text).correct


def test_kind_angle_definition_answers_match_json():
    for module in (object, combinator, observation):
        for angle in ("induce", "create"):
            task = module.generate(angle, 7, 0)
            reference = task.reference["definition"]
            if module is object and angle == "create":
                text = "\n".join(f"{name} = {notation.print_expr(nodes.from_json(body))}"
                                 for name, body in reference.items() if name != "interface")
                text += "\n" + "\n".join(f"{name} = {notation.print_expr(nodes.from_json(body))}"
                                             for name, body in reference["interface"].items())
            else:
                body = reference["body"] if module is observation else reference
                text = notation.print_expr(nodes.from_json(body))
            assert grade_kind(task, text).correct == grade_kind(task, reference).correct
            assert grade_kind(task, text).correct


def test_kind_value_answers_match_json():
    for module in (object, combinator):
        task = module.generate("compute", 7, 0)
        value = decode_outcome(task.reference["outcome"])
        assert isinstance(value, Ok)
        assert grade_kind(task, notation.print_value(value.value)).correct == grade_kind(
            task, task.reference["outcome"]).correct
    observation_task = observation.generate("compute", 7, 1)
    expected = decode_outcome(observation_task.reference["outcome"])
    assert isinstance(expected, Ok)
    answer = "true" if expected.value.tag == "true" else "false"
    assert grade_kind(observation_task, answer).correct == grade_kind(
        observation_task, observation_task.reference["outcome"]).correct
    object_task = object.generate("invert", 7, 1)
    witness = object_task.reference["answer"]
    from opulse.tasks_v2.kernel_engine import unwire

    fraction = unwire(witness)
    text = notation.print_value(Card("Frac", "Frac", fraction.fields))
    assert grade_kind(object_task, text).correct == grade_kind(object_task, witness).correct


def test_frozen_prompts_are_printable_ascii_without_node_json():
    root = Path(__file__).resolve().parents[2] / "worlds/tasks"
    for path in root.rglob("*.json"):
        records = json.loads(path.read_text(encoding="utf-8"))
        for record in records if isinstance(records, list) else (records,):
            prompt = record.get("prompt", "")
            text = prompt.get("en", "") if isinstance(prompt, dict) else prompt
            assert all(char == "\n" or 32 <= ord(char) < 127 for char in text), path
            assert '"t":' not in text and '"kind":' not in text and '"type":' not in text, path
