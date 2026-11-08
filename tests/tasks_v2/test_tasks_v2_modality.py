"""Image task parity and frozen multimodal samples (spec sections 7 and 11)."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.tasks_v2 import build_kinds, grade_kinds, kernel_engine, render
from opulse.tasks_v2.angles import computer, observation, operation
from opulse.worlds import action
from opulse.worlds_v2.computer.verify import mul_program


@pytest.mark.parametrize("angle", observation.ANGLES)
@pytest.mark.parametrize("index", (0, 1))
def test_observation_modalities_have_identical_judgments(angle, index):
    text = observation.generate(angle, 0, index)
    image = observation.generate(angle, 0, index, modality="image")
    assert replace(image, modality="text", prompt=text.prompt) == text
    assert image.prompt["render"] == render.render(image, "image")
    assert image.prompt["en"].isascii() and "the image" in image.prompt["en"].lower()
    answer = next(image.reference[key] for key in ("outcome", "answer", "choice", "definition")
                  if key in image.reference)
    bad = ({"ok": kernel_engine.wire("bad")} if angle == "compute" else
           [] if angle == "invert" and image.answer_shape == "all_solutions" else
           {"t": "int", "v": 9999} if angle == "invert" else
           {"true": not answer["true"]} if angle == "decide" else
           "not an option" if angle == "describe" else
           {**answer, "reads": ["front_colour"]})
    for candidate in (answer, bad):
        assert grade_kinds.grade(text, candidate) == grade_kinds.grade(image, candidate)


def test_computer_modalities_have_identical_judgments():
    text = computer.build_tasks()
    images = computer.build_tasks(modality="image")
    assert len(text) == len(images)
    for original, image in zip(text, images):
        assert render.render(original, "text")["text"].startswith("Computer ")
        assert {key: value for key, value in image.items() if key not in ("modality", "prompt")} == original
        assert image["prompt"]["en"].isascii()
        assert "image" in image["prompt"]["en"]
        assert image["prompt"]["render"] == render.render(image, "image")
        if original["angle"] == "compute":
            answer = (63 if original["answer_form"] == "r0" else
                      {"regs": [6, 2, 0, 9], "mem": [0] * 256, "zero": True, "carry": False})
        elif original["angle"] == "invert":
            answer = 67 if original["answer_form"] == "one_witness" else [3, 67, 131, 195]
        elif original["angle"] == "decide":
            witness = computer.grade_computer(original, True)["counterexample"]
            answer = {"equivalent": False, "counterexample": witness}
        elif original["angle"] == "describe":
            answer = "multiply"
        else:
            answer = nodes.to_json(mul_program())
        for candidate in (answer, "invalid"):
            assert computer.grade_computer(original, candidate) == computer.grade_computer(image, candidate)
    assert "r3" not in images[0]["prompt"]["render"]["image_svg"]
    assert "r3=" in images[1]["prompt"]["render"]["image_svg"]
    assert "Input memory (addresses 0..255):" in images[1]["prompt"]["en"]


@given(color=st.sampled_from(action.COLOURS))
@settings(max_examples=6)
def test_buried_blocks_remain_in_prompt(color):
    candidates = observation.states(0, 0)
    state = candidates[0]
    stacks = list(state.stacks)
    stacks[state.index(0, 0)] = (color, "B")
    state = replace(state, stacks=tuple(stacks))
    with patch.object(observation, "states", return_value=[state, *candidates[1:]]):
        task = observation.generate("compute", 0, 0, modality="image")
    assert task.prompt["render"]["fidelity"] == "lossy"
    assert f"(0,0):{color}" in task.prompt["en"]
    assert "Maximum stack" not in task.prompt["en"]
    assert "maximum stack height: 2" in task.prompt["en"]


def test_hidden_image_does_not_reveal_ungranted_state():
    task = observation.generate("compute", 0, 1, modality="image")
    state = kernel_engine.unwire(task.question["state"])
    stacks = list(state.stacks)
    stacks[state.index(0, 0)] = ("R", "G")
    altered = replace(task, question={**task.question,
                                      "state": kernel_engine.wire(replace(state, stacks=tuple(stacks)))})
    assert render.render(task, "image") == render.render(altered, "image")
    assert "rows " not in task.prompt["en"]


def test_image_samples_are_reproducible_and_small(tmp_path):
    root = Path("worlds/tasks/modality")
    files = build_kinds.build_modality(0, tmp_path)
    assert len(files) == 6 + len(computer.build_tasks())
    for path in files:
        assert path.read_bytes() == (root / path.relative_to(tmp_path)).read_bytes()
        content = json.loads(path.read_text())
        for task in content if isinstance(content, list) else [content]:
            image = task["prompt"]["render"]
            svg = image["image_svg"]
            assert len(svg.encode("utf-8")) < 20_000
            parsed = ElementTree.fromstring(svg)
            assert parsed.attrib["data-fidelity"] == image["fidelity"]
            assert parsed.attrib["data-shows"] == image["shows"]
            assert task["modality"] == "image"


def test_text_only_operation_rejects_image():
    task = operation.generate("integer", "compute")
    with pytest.raises(ValueError, match="text modality"):
        render.render(task, "image")
