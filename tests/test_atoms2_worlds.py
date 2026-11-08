"""Layer-0 declarations are computed from the published legacy worlds."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
SCRIPT = ROOT / "docs/assets/js/worlds/declare.js"
DATA = ROOT / "docs/assets/data/worlds"


def test_retired_world_viewers_are_not_shipped() -> None:
    for name in ("core.js", "tasks.js", "challenge.js"):
        assert not (ROOT / "docs/assets/js/worlds" / name).exists()


def test_legacy_renderers_have_ascii_copy_and_keep_registered_worlds() -> None:
    from test_site_ascii import javascript_findings

    directory = ROOT / "docs/assets/js/worlds"
    for name in ("successor", "integer", "clock", "bits", "strings", "lists",
                 "logic", "perm", "rel", "grid", "pitch", "action"):
        script = (directory / f"{name}.js").read_text(encoding="utf-8")
        assert not list(javascript_findings(script, name)), name
        assert f'register("{name}"' in script or f"register('{name}'" in script


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_pitch_shortener_uses_ascii_notation() -> None:
    if not NODE:
        pytest.skip("node is not installed")
    result = subprocess.run([NODE, "-e", """
      globalThis.window = globalThis;
      globalThis.matchMedia = () => ({matches: false});
      let shorten;
      globalThis.OpulseWorlds = {register: (name, renderer) => {shorten = renderer.shorten}};
      require(process.argv[1]);
      console.log(shorten('[[60, 1], [61, 2], [64, 2]]'));
    """, str(ROOT / "docs/assets/js/worlds/pitch.js")], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "Melody<C4, C#4:2, E4:2>"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_grid_shortener_uses_ascii_size() -> None:
    if not NODE:
        pytest.skip("node is not installed")
    result = subprocess.run([NODE, "-e", """
      globalThis.window = globalThis;
      globalThis.matchMedia = () => ({matches: false});
      let shorten;
      globalThis.OpulseWorlds = {register: (name, renderer) => {shorten = renderer.shorten}};
      require(process.argv[1]);
      console.log(shorten('[[1, 0, 1], [0, 1, 0]]'));
    """, str(ROOT / "docs/assets/js/worlds/grid.js")], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "Grid<2x3>"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_action_direction_labels_are_ascii() -> None:
    if not NODE:
        pytest.skip("node is not installed")
    result = subprocess.run([NODE, "-e", """
      const fs = require('node:fs');
      const vm = require('node:vm');
      const source = fs.readFileSync(process.argv[1], 'utf8');
      const context = {window: {OpulseWorlds: {register() {}}}, WeakMap};
      vm.createContext(context);
      vm.runInContext(source, context);
      console.log(vm.runInContext('shortValue({t: "direction", v: "W"})', context));
    """, str(ROOT / "docs/assets/js/worlds/action.js")], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "W"


def declare(world):
    if not NODE:
        pytest.skip("node is not installed")
    process = subprocess.run(
        [NODE, "-e", """
          const fs = require('node:fs');
          require(process.argv[1]);
          const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
          console.log(JSON.stringify(globalThis.OpulseWorldsDeclare.layer0(data)));
        """, str(SCRIPT), str(DATA / f"{world}.json")],
        check=True, capture_output=True, text=True,
    )
    return json.loads(process.stdout)


@pytest.mark.parametrize("world", ["integer", "lists", "grid", "action"])
def test_layer0_uses_published_atoms_and_value_types(world):
    source = json.loads((DATA / f"{world}.json").read_text())
    declaration = declare(world)
    types = {param["type"] for atom in source["atoms"] for param in atom["params"]}
    types.update(atom["result_type"] for atom in source["atoms"])
    expected_objects = {"robot state" if world == "action" and value == "state" else value for value in types}
    assert {entry["name"] for entry in declaration["objects"]} == expected_objects
    assert [entry["name"] for entry in declaration["operations"]] == [atom["name"] for atom in source["atoms"]]
    assert declaration["laws"] == declaration["bridges"] == []
    assert all(entry["kind"] == kind and entry["origin"] == "given" and entry["layer"] == 0
               for kind, field in (("object", "objects"), ("operation", "operations"),
                                   ("combinator", "combinators"), ("observation", "observations"))
               for entry in declaration[field])


def test_robot_probes_and_full_state_are_explicit():
    robot = declare("action")
    assert [entry["name"] for entry in robot["combinators"]] == ["Call", "Let", "Case", "Rec", "repeat_until"]
    names = {entry["name"] for entry in robot["observations"]}
    assert {"front_wall", "front_water", "inputs", "result", "full-state judging"} <= names
    assert "full-state judging" not in {entry["name"] for entry in declare("integer")["observations"]}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_missing_data_has_safe_declaration():
    if not NODE:
        pytest.skip("node is not installed")
    process = subprocess.run([NODE, "-e", """
      require(process.argv[1]);
      console.log(JSON.stringify(globalThis.OpulseWorldsDeclare.layer0()));
    """, str(SCRIPT)], check=True, capture_output=True, text=True)
    result = json.loads(process.stdout)
    assert result["objects"] == result["operations"] == []
    assert [entry["name"] for entry in result["combinators"]] == ["Call", "Let", "Case", "Rec"]
    assert [entry["name"] for entry in result["observations"]] == ["inputs", "result"]
    assert result["laws"] == result["bridges"] == []


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_legacy_panel_uses_six_kind_table_and_shows_empty_columns():
    if not NODE:
        pytest.skip("node is not installed")
    process = subprocess.run([NODE, "-e", """
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}, children = []) => ({tag, attrs, children: Array.isArray(children) ? children : [children],
        appendChild(child) {this.children.push(child)}, replaceChildren(...items) {this.children = items},
        classList: {add() {}}});
      A2.chip = entry => A2.el('span', {text:entry.name});
      A2.kindBadge = kind => A2.el('span', {text:kind});
      A2.catalog = null;
      A2.register = (name, fn) => {globalThis.legendMount = fn};
      require(root + '/docs/assets/js/worlds/declare.js');
      const legend = A2.el('div');
      globalThis.legendMount(legend);
      const panel = A2.el('div');
      globalThis.OpulseWorldsDeclare.render(panel, {world:'integer', atoms:[]}, A2);
      const columns = panel.children[0].children[1].children;
      console.log(JSON.stringify({legend:legend.children.map(item => item.attrs.text),
        columns:columns.map(item => item.children[0].children[0].attrs.text),
        empty:columns.slice(-2).map(item => item.children[1].children[0].attrs.text)}));
    """, str(ROOT)], check=True, capture_output=True, text=True)
    result = json.loads(process.stdout)
    assert result["legend"] == ["SIX KINDS / LAYER 0", "object", "operation", "combinator",
                                "observation", "law", "bridge"]
    assert result["columns"] == ["object", "operation", "combinator", "observation", "law", "bridge"]
    assert result["empty"] == ["None declared", "None declared"]
