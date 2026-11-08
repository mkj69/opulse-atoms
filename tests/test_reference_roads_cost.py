"""The reference page's operation example agrees with the roads world's cost (review round 25 G3)."""

import json
import re
from pathlib import Path

from opulse.atoms import nodes, notation
from opulse.worlds_v2.roads import story

ROOT = Path(__file__).resolve().parents[1]


def test_reference_cost_is_a_marked_schematic_of_the_weighted_roads_cost():
    page = (ROOT / "docs/reference/index.md").read_text(encoding="utf-8")
    line = next(line for line in page.splitlines() if line.startswith("- **Operation:**"))
    source = re.search(r"`(op cost\(.*?)`", line).group(1)
    parsed = notation.parse_definition(source)
    real = next(definition for definition in story.definitions() if definition.name == "cost")
    # Same name, input sort, output sort and layer as the roads definition.
    assert parsed.name == real.name
    assert [edge.sort for edge in parsed.spec.inputs] == [edge.sort for edge in real.spec.inputs] == ["Route"]
    assert parsed.spec.output.sort == real.spec.output.sort == "Int"
    assert source.endswith(f" L{real.layer}")
    # The real body sums edge weights; the page says so and marks its own body as a schematic.
    assert {"edge", "add", "Route.vertices", "Route.graph"} <= nodes.references(real.body)
    assert "adds the road weights along a route" in line and "this line is a schematic" in line
    export = json.loads((ROOT / "docs/assets/data/worlds_v2/roads.json").read_text())
    example = next(row for row in export["story"] if row["name"] == "cost")["examples"][0]
    assert example["text"].endswith('List.items<"A", "D", "F", "H", "K", "L">>>)')
    assert f"({example['outcome']['ok']['v']} for A, D, F, H, K, L)" in line
    assert "length(route)" not in page
