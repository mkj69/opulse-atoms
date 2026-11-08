"""Published research and catalogue claims track their versioned data."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD_DATA = ROOT / "docs/assets/data/worlds_v2"
CHALLENGE = ROOT / "docs/assets/data/challenge/v2.json"


def test_versions_research_cost_comes_from_the_independent_edits_row():
    export = json.loads((WORLD_DATA / "versions.json").read_text())
    row = next(row for row in export["story"] if row["name"] == "apply")
    example = next(example for example in row["examples"]
                   if example["text"].count("Patch.patch<") == 2)
    page = (ROOT / "docs/research/index.md").read_text()
    assert "ok" in example["outcome"]
    assert f"with {example['steps']} layer-0 steps" in page
    assert "`apply` operation that changes two independent document paths" in page
    assert f"`{example['ascii']}`" not in page
    assert "displayed call is not runnable parser source" in page
    assert "33 proposed layer-0 steps" not in page


def test_grammar_research_cost_comes_from_a_real_parse_count_row():
    export = json.loads((WORLD_DATA / "grammar.json").read_text())
    row = next(row for row in export["story"] if row["name"] == "parse_count")
    example = row["examples"][0]
    page = (ROOT / "docs/research/experiments.md").read_text()
    assert "ok" in example["outcome"]
    assert "ascii" not in example
    # Notation v3: the page describes the recorded machine call instead of displaying it as a formula.
    assert f"stores {example['steps']:,} layer-0 steps for the parse-count observation on eight operands separated by plus signs" in page
    assert example["text"] not in page
    assert "historical export uses machine notation, not a v3 display formula" in page
    assert "114 layer-0 steps" not in page


def test_route_is_designed_not_runnable_in_legacy_integer_world():
    catalogue = json.loads(CHALLENGE.read_text())
    route = catalogue["paths"]["six_kinds_one_world"]
    declaration = json.loads((ROOT / "worlds/decl" / f"{route['world']}.json").read_text())
    page = (ROOT / "docs/play/ladders.md").read_text()
    script = (ROOT / "docs/assets/js/atoms2/ladders.js").read_text()
    assert declaration["dialect"] == "legacy-v1"
    assert len(route["steps"]) == 6
    assert "Legacy-v1 integer world" in page
    assert "its definitions cannot run in that world" in page
    assert "Tasks below are separate" in page
    assert "Follow the six-kind design route tagged " in script
    assert "or select a separate task below" in script



def test_reference_distinguishes_world_exports_from_the_index():
    index = json.loads((WORLD_DATA / "index.json").read_text())
    page = (ROOT / "docs/reference/api.md").read_text()
    assert "excluding `index.json`" in page
    assert f"`{index['schema']}`: `docs/assets/data/worlds_v2/index.json`" in page
    for path in WORLD_DATA.glob("*.json"):
        if path.name != "index.json":
            assert json.loads(path.read_text())["schema"] == "opulse.world_v2_export/1"
