"""Computer lab fixture and exact browser interpreter."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_computer_fuel_and_carry():
    script = """
const fixture = require(process.argv[1]);
const lab = require(process.argv[2]);
const original = fixture.left[fixture.left.length - 1];
const standard = lab.compute(fixture.left, fixture.right, original, 5000);
const altered = lab.compute(fixture.left, fixture.right, fixture.alternateFinalByte, 5000);
const starved = lab.compute(fixture.left, fixture.right, original, 256);
const boundary = lab.compute(fixture.left, fixture.right, original, standard.steps - 1);
let unsafe;
try { lab.compute([256], [1], 1, 100); } catch (error) { unsafe = error.name; }
console.log(JSON.stringify({standard, altered, starved, boundary, unsafe}));
"""
    fixture = ROOT / "docs/assets/data/atoms2/computer.json"
    interpreter = ROOT / "docs/assets/js/atoms2/lab-computer.js"
    result = subprocess.run([NODE, "-e", script, str(fixture), str(interpreter)], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert data["standard"]["modular"] == data["altered"]["modular"] == 40
    assert data["standard"]["wide"] == [40, 42, 1]
    assert data["altered"]["wide"] == [40, 171, 0]
    assert data["standard"]["steps"] == data["altered"]["steps"] == 3856
    assert data["starved"]["outcome"] == "Unknown(fuel)"
    assert data["starved"]["next"] == 0
    assert data["boundary"]["outcome"] == "Unknown(fuel)"
    assert data["unsafe"] == "RangeError"


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_register_snapshots_and_partial_fuel():
    script = """
const fixture = require(process.argv[1]);
const lab = require(process.argv[2]);
const byte = fixture.left[fixture.left.length - 1];
const full = lab.compute(fixture.left, fixture.right, byte, 5000);
const partial = lab.compute(fixture.left, fixture.right, byte, 256);
const firstPair = lab.compute(fixture.left, fixture.right, byte, 478);
console.log(JSON.stringify({full, partial, firstPair}));
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "docs/assets/data/atoms2/computer.json"),
         str(ROOT / "docs/assets/js/atoms2/lab-computer.js")],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    full, partial, first_pair = data["full"], data["partial"], data["firstPair"]
    assert len(full["trace"]) == full["steps"] + 1
    assert full["trace"][0]["phase"] == "Ready"
    assert full["trace"][2]["registers"]["A"] == 21
    assert full["trace"][3]["registers"]["B"] == 118
    assert full["trace"][478]["modular"] == (21 * 119) % 256
    assert full["trace"][-1]["registers"]["D"] == 40
    assert partial["outcome"] == "Unknown(fuel)"
    assert partial["steps"] == 256
    assert len(partial["trace"]) == 257
    assert partial["trace"][-1]["registers"]["B"] > 0
    assert partial["needed"] == 222
    assert first_pair["next"] == 1
    assert first_pair["needed"] == 434


def test_play_comparison_and_single_workshop_heading():
    lab = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    workshop = (ROOT / "docs/assets/js/atoms2/define.js").read_text()
    page = (ROOT / "docs/play/index.md").read_text()
    assert "Modular results match" in lab
    assert "Wide results differ" in lab
    assert "a2-computer-machines" in lab
    assert "a2-computer-registers" in lab
    assert "a2-computer-fuel-track" in lab
    assert "Try 256 fuel" in lab
    assert "THE ATOM WORKSHOP" not in workshop
    assert "Give an idea a name." not in workshop
    assert page.count("## Definition workshop") == 1


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_world_picker_opens_challenge_instead_of_leaving_computer_lab_visible():
    source = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    chooser = source[source.index("    function chooseWorld(world) {"):source.index("    var requestedWorld =")]
    script = """
const root = { location: { href: 'https://example.test/play/?world=roads',
  assign(value) { this.destination = value; } } };
const worldPicker = { value: 'computer' };
eval(process.argv[1]);
chooseWorld('roads');
const roads = { destination: root.location.destination, selected: worldPicker.value };
chooseWorld('computer');
console.log(JSON.stringify({roads, computer: worldPicker.value}));
"""
    result = subprocess.run([NODE, "-e", script, chooser], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert data["roads"] == {"destination": "https://example.test/play/challenge/", "selected": "computer"}
    assert data["computer"] == "computer"
    assert 'text: "Open the workshop", onclick: function () { chooseWorld("integer"); }' in source
    assert source.index('text: "Definition workshop"') < source.index('var panel = el(')


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_low_fuel_returns_exact_last_trace_snapshot():
    script = """
const lab = require(process.argv[1]);
console.log(JSON.stringify([0, 1, 2, 5, 6, 7].map(fuel => lab.compute([2, 4], [3, 2], 4, fuel))));
"""
    result = subprocess.run(
        [NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2/lab-computer.js")],
        check=True, capture_output=True, text=True,
    )
    for run in json.loads(result.stdout):
        last = run["trace"][-1]
        assert last["totalSteps"] == run["steps"]
        assert last["registers"] == run["registers"]
        assert last["modular"] == run["modular"]
        assert last["wide"] == run["wideDecimal"]


@requires_node
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_fuel_input_rejects_fractional_negative_and_empty_without_executing():
    script = """
const lab = require(process.argv[1]);
console.log(JSON.stringify(['-1', '2.5', '', '100001', '0', '3856'].map(lab.parseFuel)));
"""
    result = subprocess.run([NODE, "-e", script, str(ROOT / "docs/assets/js/atoms2/lab-computer.js")], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [None, None, None, None, 0, 3856]
    source = (ROOT / "docs/assets/js/atoms2/lab-computer.js").read_text()
    assert "if (!validFuel()) { invalidFuel(); return; }" in source
    assert "results = [];" in source
