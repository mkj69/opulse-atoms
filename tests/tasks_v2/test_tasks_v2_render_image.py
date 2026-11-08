"""Checks for image observations and accessible ASCII equivalents."""

from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.tasks_v2.hooks import show
from opulse.tasks_v2.render_image import (
    render_computer,
    render_robot,
    render_value,
    render_value_notation,
)
from opulse.worlds import action
from opulse.worlds_v2.computer import machine

_NS = "{http://www.w3.org/2000/svg}"
_SAMPLES = Path(__file__).resolve().parents[2] / "worlds/tasks/images"


def _parse(svg: str, fidelity: str, description: str):
    root = ElementTree.fromstring(svg)
    assert root.tag == _NS + "svg"
    assert root.attrib["data-fidelity"] == fidelity
    assert root.attrib["data-shows"]
    assert root.findtext(_NS + "title")
    assert root.findtext(_NS + "desc") == description
    assert len(svg.encode("utf-8")) < 20_000
    return root


def test_robot_compact_full_view_and_unchanged_truth():
    state = action.initial_state(4, 4, 3)
    state = replace(state, robot=(1, 1), facing=action.Direction("E"),
                    terrain=("....", "...~", "....", "...."),
                    stacks=tuple(("R", "B") if index == 6 else () for index in range(16)),
                    bridges=((3, 1),), held="bridge_kit")
    before = state.to_dict()
    svg = render_robot(state)
    assert render_robot(state) == svg
    root = _parse(svg, "lossy", action.render_state(state))
    assert "B2" in "".join(root.itertext())
    assert "bridge_kit" in root.findtext(_NS + "desc")
    assert state.to_dict() == before


@given(st.integers(min_value=1, max_value=16), st.integers(min_value=1, max_value=16))
@settings(max_examples=32)
def test_robot_cell_geometry_tracks_map_without_extra_columns(width, height):
    state = action.initial_state(width, height, 3)
    root = _parse(render_robot(state), "lossy", action.render_state(state))
    cells = root.findall(f'.//{_NS}rect[@data-cell]')
    if width * height > 100:
        assert not cells
        assert len(root.findall(f'.//{_NS}path')) == 1
        rows = root.findall(f'.//{_NS}text')
        assert len(rows) == height
        assert [row.text for row in rows] == [
            ''.join(cell.ljust(3) for cell in line.split())
            for line in action.render_state(state).splitlines()[:-1]
        ]
        return
    assert len(cells) == width * height
    assert {cell.attrib['data-cell'] for cell in cells} == {
        f'{column},{row}' for row in range(height) for column in range(width)}
    assert (int(root.attrib['width']), int(root.attrib['height'])) == (width * 32 + 32, height * 32 + 32)
    centers = {(float(cell.attrib['x']) + float(cell.attrib['width']) / 2,
                float(cell.attrib['y']) + float(cell.attrib['height']) / 2) for cell in cells}
    for text in root.findall(f'.//{_NS}text'):
        assert (float(text.attrib['x']), float(text.attrib['y'])) in centers
        assert text.attrib['text-anchor'] == 'middle'
        assert text.attrib['dominant-baseline'] == 'central'


def test_robot_symbols_and_facing_fit_their_cells():
    base = action.initial_state(4, 2, 3)
    state = replace(base, terrain=(".B#~", "...."), bridges=((3, 0),),
                    stacks=tuple(("R", "B") if index == 0 else () for index in range(8)),
                    tools=tuple("bridge_kit" if index == 1 else "" for index in range(8)),
                    robot=(0, 1), facing=action.Direction("N"), held="R")
    root = _parse(render_robot(state), "lossy", action.render_state(state))
    assert len(root.findall(f'.//{_NS}rect[@data-cell]')) == 8
    assert len(root.findall(f'.//{_NS}polygon')) == 1
    assert {text.text for text in root.findall(f'.//{_NS}text')} == {"2", "T"}
    assert root.find(f'.//{_NS}rect[@data-cell="1,0"]').attrib['fill'] == '#d8a234'
    assert root.find(f'.//{_NS}polygon').attrib['transform'] == 'translate(32 64)'


@given(st.sampled_from(action.COLOURS))
def test_hidden_cells_never_enter_learner_view(secret):
    base = action.initial_state(4, 4, 4)
    base = replace(base, robot=(1, 1), facing=action.Direction("E"))
    altered = replace(base, stacks=tuple((secret, "G") if index == 0 else stack
                                         for index, stack in enumerate(base.stacks)))
    assert render_robot(base, learner_view=True, probes=("front_wall", "front_height")) == render_robot(
        altered, learner_view=True, probes=("front_wall", "front_height"))
    root = ElementTree.fromstring(render_robot(altered, learner_view=True, probes=("front_wall",)))
    assert root.attrib["data-fidelity"] == "lossy"
    assert root.findtext(_NS + "desc") == "probes: front_wall: false"
    assert "height" not in "".join(root.itertext())


def test_front_probe_values_are_not_confused_with_the_full_state():
    base = action.initial_state(4, 4, 4)
    state = replace(base, robot=(1, 1), facing=action.Direction("E"),
                    stacks=tuple(("R", "B") if index == 6 else stack
                                 for index, stack in enumerate(base.stacks)))
    svg = render_robot(state, learner_view=True, probes=("front_height", "front_colour"))
    _parse(svg, "lossy", "probes: front_colour: \"B\"\nfront_height: 2")
    assert "R" not in ElementTree.fromstring(svg).findtext(_NS + "desc")
    with pytest.raises(ValueError, match="unknown robot probe"):
        render_robot(state, learner_view=True, probes=("back_colour",))


def test_learner_does_not_infer_unprobed_front_terrain_or_colour():
    base = action.initial_state(4, 4, 4)
    base = replace(base, robot=(1, 1), facing=action.Direction("E"))
    bench = replace(base, terrain=tuple("..B." if row == 1 else line
                                        for row, line in enumerate(base.terrain)),
                    stacks=tuple(("R",) if index == 6 else () for index in range(16)))
    visible = ("front_wall", "front_water", "holding")
    assert render_robot(base, learner_view=True, probes=visible) == render_robot(
        bench, learner_view=True, probes=visible)


@given(st.binary(min_size=256, max_size=256), st.integers(min_value=0, max_value=255))
@settings(max_examples=20, deadline=None)
def test_computer_all_bytes_are_lossless_and_highlights_are_pure(memory, address):
    state = machine.State(regs=(3, 41, 7, 255), mem=memory, zero=True, carry=False)
    original = machine.to_card(state)
    svg = render_computer(state, (address,))
    root = _parse(svg, "lossless", show(original))
    assert render_computer(state, (address,)) == svg
    assert len(root.findall(f'.//{_NS}text')) == 275
    assert f"{memory[address]:03d}" in " ".join(node.text or "" for node in root.findall(f'.//{_NS}text'))
    assert machine.to_card(state) == original


@given(st.binary(min_size=256, max_size=256))
@settings(max_examples=15, deadline=None)
def test_computer_memory_values_center_inside_cells(memory):
    root = _parse(render_computer(machine.State(mem=memory)), "lossless",
                  show(machine.to_card(machine.State(mem=memory))))
    table = root.find(f'.//{_NS}rect[@data-memory-table]')
    cell_width = float(table.attrib['data-cell-width'])
    cell_height = float(table.attrib['data-cell-height'])
    assert cell_width >= 11 * .6 * 3 + 8
    assert float(table.attrib['width']) == 16 * cell_width
    assert float(table.attrib['height']) == 16 * cell_height
    tile = root.find(f'.//{_NS}pattern/{_NS}rect')
    assert float(tile.attrib['width']) == cell_width
    assert float(tile.attrib['height']) == cell_height
    assert float(table.attrib['x']) + float(table.attrib['width']) + 8 <= float(root.attrib['width'])
    rows = root.findall(f'.//{_NS}g[@transform]')
    assert len(rows) == 16
    for row, group in enumerate(rows):
        assert group.attrib['transform'] == f'translate(50 {98 + row * 18})'
        values = group.findall(_NS + 'text')
        assert len(values) == 16
        for column, text in enumerate(values):
            left = column * cell_width
            assert left + 11 * .6 * 3 / 2 <= float(text.attrib['x'])
            assert float(text.attrib['x']) + 11 * .6 * 3 / 2 <= left + cell_width
            assert root.find(f'.//{_NS}g[@fill]').attrib['text-anchor'] == 'middle'
            assert text.text == f'{memory[row * 16 + column]:03d}'


def test_machine_rejects_invalid_highlights():
    with pytest.raises(ValueError, match="address"):
        render_computer(machine.State(), (256,))
    with pytest.raises(ValueError, match="address"):
        render_computer(machine.State(), (True,))


def test_largest_states_remain_under_size_limit():
    robot = action.State(32, 32, 16, ("." * 32,) * 32, (("R",) * 16,) * 1024,
                         ("",) * 1024, (), (0, 0), action.Direction("N"))
    _parse(render_robot(robot), "lossy", action.render_state(robot))
    computer = machine.State(mem=bytes([255] * 256))
    _parse(render_computer(computer, range(256)), "lossless", show(machine.to_card(computer)))


@given(st.integers(), st.text(max_size=100))
def test_fallback_is_lossless_text_in_image(number, text):
    for value in (number, text):
        svg = render_value(value)
        assert render_value(value) == svg
        _parse(svg, "lossless", render_value_notation(value))


def test_fallback_distinguishes_cards_and_outcomes():
    male, female = Card("Person", "male", (1,)), Card("Person", "female", (1,))
    assert render_value_notation(male) != render_value_notation(female)
    _parse(render_value(male), "lossless", render_value_notation(male))
    _parse(render_value(Ok(42)), "lossless", "Ok<42>")
    _parse(render_value(Bottom("blocked")), "lossless", 'Bottom<"blocked">')
    _parse(render_value(Unknown("fuel")), "lossless", 'Unknown<"fuel">')
    machine_card = Card("machine_state", "machine")
    notation = render_value_notation(machine_card)
    assert notation == "machine_state.machine<>"
    assert render_value(machine_card) != render_value(Ok(machine_card))
    _parse(render_value(machine_card), "lossless", notation)


def test_fallback_escapes_markup_without_changing_notation():
    value = '<script>"&</script>'
    svg = render_value(value)
    assert "<script>" not in svg
    _parse(svg, "lossless", render_value_notation(value))


def test_six_review_samples_are_parseable():
    samples = sorted(_SAMPLES.glob("*.svg"))
    assert len(samples) == 6
    for path in samples:
        root = ElementTree.parse(path).getroot()
        assert root.tag == _NS + "svg"
        assert root.attrib["data-fidelity"] in ("lossless", "lossy")
        assert len(path.read_bytes()) < 20_000
