"""Surface prompts for operation tasks (docs/spec/atoms-v2.md, section 12)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from opulse.atoms.values import Card, boolean, decode_outcome, encode, outcome_equal
from opulse.tasks_v2 import engine
from opulse.tasks_v2.angles.operation import (
    ANGLES,
    VERSIONS,
    WORLD_NAMES,
    _rows,
    generate,
)
from opulse.tasks_v2.ascii import names, to_ascii_expression
from opulse.tasks_v2.build import build
from opulse.tasks_v2.grade import executable_task
from opulse.tasks_v2.render import render, show_examples, show_scope, show_value
from opulse.tasks_v2.task import Task, default_boundary, default_observation


@pytest.mark.parametrize(("value", "expected"), [
    (encode(5), "5"), (encode(-3), "-3"),
    (encode("ab"), '"ab"'), (encode(Card("list[int]", "list", (1, 2))), "List<1, 2>"),
    (encode(boolean(True)), "true"), (encode(boolean(False)), "false"),
    ({"bottom": "undefined"}, "NaN"), ({"t": "nan", "v": None}, "NaN"),
])
def test_value(value, expected):
    assert show_value(value, "integer@1") == expected


def test_scopes():
    params = [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}]
    assert show_scope({"domains": [[encode(item) for item in range(-12, 13)]]}, params[:1]) == "a ∈ -12..12"
    assert show_scope({"domains": [[encode(0), encode(2), encode(5)]]}, params[:1]) == "a ∈ {0, 2, 5}"
    assert show_scope({"domains": [[encode(3)]]}, params[:1]) == "a ∈ {3}"
    assert show_scope({"domains": [[encode(0), encode(1)], [encode(3), encode(4)]]}, params) == (
        "a ∈ 0..1, b ∈ 3..4")
    assert show_scope({"inputs": [[encode(a), encode(b)] for a, b in
                                  itertools.product(range(2), range(3, 5))]}, params) == (
        "a ∈ 0..1, b ∈ 3..4")
    assert show_scope({"inputs": [[encode(0), encode(3)], [encode(1), encode(4)]]}, params) == (
        "(a, b) ∈ {(0, 3), (1, 4)}")
    strings = [encode("".join(chars)) for length in range(4)
               for chars in itertools.product("ab", repeat=length)]
    lists = [encode(Card("list[int]", "list", tuple(items))) for length in range(4)
             for items in itertools.product((0, 1), repeat=length)]
    assert show_scope({"domains": [strings]}, [{"name": "s", "type": "str"}]) == (
        's ∈ all strings of length ≤ 3 over {"a", "b"}')
    assert show_scope({"domains": [lists]}, [{"name": "xs", "type": "list[int]"}]) == (
        "xs ∈ all lists of length ≤ 3 over {0, 1}")
    old_lists = [{"t": "list", "v": list(items)} for length in range(4)
                 for items in itertools.product((0, 1), repeat=length)]
    assert show_scope({"domains": [old_lists]}, [{"name": "xs", "type": "list[int]"}]) == (
        "xs ∈ all lists of length ≤ 3 over {0, 1}")
    assert "all lists" not in show_scope({"domains": [lists[:-1]]},
                                         [{"name": "xs", "type": "list[int]"}])


@pytest.mark.parametrize(("definition", "expected"), [
    ("f a = { a }", "f 2 = 5"),
    ("a ⊕ b = { a }", "2 ⊕ 3 = 5"),
    ("a ! = { a }", "2 ! = 5"),
])
def test_examples(definition, expected):
    params = [{"name": "a"}, {"name": "b"}] if " b " in definition else [{"name": "a"}]
    values = [encode(2), encode(3)][:len(params)]
    assert show_examples([{"inputs": values, "output": {"ok": encode(5)}}], definition, params) == expected


def test_string_example_does_not_replace_inside_a_rendered_value():
    params = [{"name": "a"}, {"name": "b"}]
    assert show_examples([{"inputs": [encode("b"), encode("a")], "output": {"ok": encode("ab")}}],
                         "a ⊕ b = { a }", params) == '"b" ⊕ "a" = "ab"'


def test_frozen_prompts_and_build(tmp_path):
    root = Path("worlds/tasks")
    total = 0
    for world in WORLD_NAMES:
        for path in build(world, 0, 8, tmp_path):
            committed = root / path.relative_to(tmp_path)
            assert committed.read_bytes() == path.read_bytes()
            total += committed.stat().st_size
            for sample in json.loads(committed.read_text(encoding="utf-8")):
                prompt = sample["prompt"]["en"]
                assert prompt.isascii()
                assert "'t':" not in prompt and '"t":' not in prompt
                assert prompt.splitlines()[-1].startswith("Answer format:")
    assert total < 1_000_000


def test_text_render_hook():
    task = generate("integer", "compute")
    assert render(task, "text") == {"text": task.prompt["en"]}
    with pytest.raises(ValueError, match="text modality"):
        render(task, "image")
    with pytest.raises(ValueError, match="text modality"):
        generate("integer", "compute", modality="audio")


def test_hidden_input_and_answer_shapes():
    for angle in ANGLES:
        task = generate("integer", angle)
        assert task.prompt["en"].splitlines()[-1].startswith("Answer format:")


def _check_example_trace(sample):
    question = sample["question"]
    prompt = sample["prompt"]["en"]
    expression = prompt.split("\nExample trace: ", 1)[1].splitlines()[0]
    trace = prompt.split("\nTrace:\n", 1)[1].split("\nAnswer format:", 1)[0]
    assert expression != question["expression"]
    definitions = executable_task(Task.from_dict(sample)).question["definitions"]
    legacy_expression = next(example["expression"] for example in
                             _rows(sample["world"].split("@")[0])[
                                 {value: key for key, value in names(sample["world"])[0].items()}[
                                     question["operator"]]]["examples"]
                             if to_ascii_expression(sample["world"], example["expression"],
                                                    definitions) == expression)
    outcome = engine.evaluate(sample["world"], definitions, legacy_expression, 10000)[0]
    assert not outcome_equal(outcome, decode_outcome(sample["reference"]["outcome"]))
    assert trace.splitlines()[-1] != "= " + show_value(sample["reference"]["outcome"], sample["world"])


def test_committed_traces_do_not_evaluate_question():
    traced = 0
    for world in WORLD_NAMES:
        for path in sorted((Path("worlds/tasks") / f"{world}@{VERSIONS[world]}").glob("operation_*.json")):
            for sample in json.loads(path.read_text(encoding="utf-8")):
                prompt = sample["prompt"]["en"]
                if "\nTrace:\n" in prompt:
                    _check_example_trace(sample)
                    traced += 1
                if sample["angle"] == "compute":
                    assert "\nExample trace: " in prompt
                if sample["angle"] == "invert":
                    assert "\nTrace:\n" not in prompt
    assert traced == len(WORLD_NAMES) * 8


def test_example_trace_obeys_boundary_and_observation():
    ordinary = generate("integer", "compute")
    kept = default_boundary()
    kept["keep_names"] = [ordinary.question["operator"]]
    opaque = generate("integer", "compute", boundary=kept)
    opened = default_boundary()
    opened["open_names"] = [ordinary.question["operator"]]
    unfolded = generate("integer", "compute", boundary=opened)
    atoms = default_boundary()
    atoms["depth"] = 0
    layer_zero = generate("integer", "compute", boundary=atoms)
    for task in (ordinary, opaque, unfolded, layer_zero):
        _check_example_trace(task.to_dict())
        assert task.reference == ordinary.reference
    assert "one opaque step" in opaque.prompt["en"]
    assert "f6(" not in opaque.prompt["en"].split("\nTrace:\n", 1)[1]
    assert "f6(" in unfolded.prompt["en"].split("\nTrace:\n", 1)[1]
    assert "layer-0 step" in layer_zero.prompt["en"].split("\nTrace:\n", 1)[1]
    assert "f1(" not in layer_zero.prompt["en"].split("\nTrace:\n", 1)[1]
    hidden = default_observation()
    hidden["show"]["input"] = "hidden"
    assert "\nTrace:\n" not in generate("integer", "compute", observation=hidden).prompt["en"]
    results = default_observation()
    results["channels"] = ["results"]
    assert "\nTrace:\n" not in generate("integer", "compute", observation=results).prompt["en"]
