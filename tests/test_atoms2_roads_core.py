"""Regressions for the promoted Metro run and its browser cross-check."""

import json
import shutil
import subprocess
from dataclasses import replace
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest

from opulse.atoms.notation import print_definition
from opulse.atoms.spec import Cost
from opulse.atoms.values import decode, encode_outcome
from tools.atoms2_roads_export import (
    OUTPUT,
    SMALL_EDGES,
    TARGETS,
    build_card_library,
    build_export,
    input_digest,
    outside_checked_scope,
    partial_graph_scope,
    small_graph,
)

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def artifact():
    return json.loads(OUTPUT.read_text())


@pytest.fixture(scope="module")
def library():
    return build_card_library()


def test_roads_export_regenerates_identically(artifact, library):
    from opulse.notation3.export import add_notation3

    assert artifact == add_notation3(build_export(library), 'atoms2', source='atoms2/roads_core.json')
    assert artifact["inputs_sha256"] == input_digest()


def test_roads_layers_and_promoted_evidence(artifact, library):
    records = library.records()
    for card in artifact["cards"]:
        definition = records[card["name"]]
        invented = {name.split(".")[0] for name in definition.depends_on
                    if name.split(".")[0] in records and records[name.split(".")[0]].origin == "invented"}
        assert set(card["invented_dependencies"]) == invented
        assert card["layer"] == definition.layer == 1 + max(
            (records[name].layer for name in invented), default=0)
        assert card["evidence"]["content_hash"] == definition.evidence.content_hash
        assert card["evidence"]["scope"] == partial_graph_scope(definition.evidence.scope)
        assert card["status"] == "promoted"
        assert card["declaration"].endswith(" L" + str(card["layer"]))
        if card["declaration_label"].startswith("Printed from"):
            bare = replace(definition, status="written", evidence=None, contract=None,
                           cost=Cost(), id=None)
            assert card["declaration"] == print_definition(bare)
            assert "re-parses: yes" in card["declaration_label"]
        else:
            assert card["declaration_label"].startswith("Design summary (printer unavailable: ")
    assert {card["name"] for card in artifact["cards"] if card["declaration_label"].startswith("Printed from")} == {"failures"}
    assert "Design summary (not parseable source)" not in (ROOT / "docs/learn/index.md").read_text()


def test_roads_complete_scope_counts_weight_assignments_not_topologies(artifact):
    checked_weights = list(product((1, 2, 3, 4), repeat=len(SMALL_EDGES)))
    assert SMALL_EDGES == (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))
    assert len({small_graph(weights) for weights in checked_weights}) == 256
    assert {weights[0] for weights in checked_weights} == {1, 2, 3, 4}
    for card in artifact["cards"]:
        scope = card["evidence"]["scope"]
        assert scope["partial"] is False
        assert scope["size"] == 256
        assert scope["domain_total"] == 4 ** 4 == 256
        assert scope["topology"] == "one 4-node topology"
        assert "all 256 weightings" in scope["domain"]
        assert "all 256 weightings" in scope["description"]


def test_roads_scope_rejects_changed_family():
    with pytest.raises(ValueError, match="fixed four-node topology"):
        partial_graph_scope({"domain": "60 assorted 4-node graphs", "size": 60})
    with pytest.raises(ValueError, match="verification count"):
        partial_graph_scope({"domain": "all 60 weightings (each road weight 1..4) of the fixed connected 4-node, 4-road graph A-B, A-C, B-D, C-D; 60 inputs", "size": 60})


def test_roads_legacy_partial_scope_stays_partial():
    scope = partial_graph_scope({"domain": "4-node, 4-road graphs with edge weights 1..4", "size": 60})
    assert scope["partial"] is True
    assert scope["domain_total"] == 256
    assert scope["topology"] == "one 4-node topology"


def test_roads_complete_scope_distinguishes_metro_from_fixed_topology():
    scope = {"domain": "all 256 weightings (each road weight 1..4) of the fixed connected "
                       "4-node, 4-road graph A-B, A-C, B-D, C-D; 256 RouteRaw(...) inputs",
             "size": 256}
    assert not outside_checked_scope(scope, (small_graph((1, 2, 3, 4)),))
    assert not outside_checked_scope(scope, (small_graph((4, 4, 4, 4)),))
    from opulse.worlds_v2.roads import depth_hosts
    assert outside_checked_scope(scope, (depth_hosts.METRO,))


@pytest.mark.skipif(NODE is None, reason="Node unavailable")
def test_world_roads_scope_uses_recorded_complete_label():
    source = """
const A2 = require(process.argv[1]);
const world = require(process.argv[2]);
const evidence = world.story[0].evidence;
console.log(JSON.stringify({scope: evidence.scope, method: A2.evidenceRecord({evidence}).method}));
"""
    output = subprocess.check_output([NODE, "-e", source,
        str(ROOT / "docs/assets/js/atoms2/kit.js"),
        str(ROOT / "docs/assets/data/worlds_v2/roads.json")], text=True)
    result = json.loads(output)
    assert result["scope"]["size"] == 256
    assert "all 256 weightings" in result["scope"]["domain"]
    assert result["method"] == "bounded"


@pytest.mark.skipif(NODE is None, reason="Node unavailable")
def test_roads_complete_scope_renders_as_bounded_badge_with_evidence(artifact):
    source = """
const A2 = require(process.argv[1]);
global.document = {createTextNode(text) { return {textContent: text}; },
  createElement(tag) { return {tagName: tag, attributes: {},
  setAttribute(key, value) { this.attributes[key] = value; },
  addEventListener(key, handler) { this[key] = handler; },
  appendChild(child) { this.textContent = (this.textContent || '') + child.textContent; }}; }};
const core = require(process.argv[2]);
const evidence = core.cards[0].evidence;
const note = A2.scopedBadge(evidence, null,
  {file: 'roads_core.json', href: '/assets/data/atoms2/roads_core.json'});
console.log(JSON.stringify({tag: note.tagName, className: note.className,
  text: note.textContent, scope: A2.evidenceRecord({evidence}).method,
  click: typeof note.click}));
"""
    output = subprocess.check_output([NODE, "-e", source,
        str(ROOT / "docs/assets/js/atoms2/kit.js"), str(OUTPUT)], text=True)
    note = json.loads(output)
    assert note == {"tag": "button", "className": "a2-badge a2-badge-bounded",
                    "text": "Bounded: all 256 weightings of one 4-node topology",
                    "scope": "bounded", "click": "function"}


@pytest.mark.skipif(NODE is None, reason="Node unavailable")
def test_roads_partial_scope_keeps_partial_label():
    source = """
const A2 = require(process.argv[1]);
A2.el = (tag, attrs, text) => ({tag, text, addEventListener() {}});
const scope = {size: 12, partial: true, domain_total: 256, topology: 'one 4-node topology',
  checked: {size: 12, sha256: 'a'.repeat(64)}};
console.log(JSON.stringify(A2.scopedBadge({method: 'bounded', scope}, null, {})));
"""
    output = subprocess.check_output([NODE, "-e", source,
        str(ROOT / "docs/assets/js/atoms2/kit.js")], text=True)
    assert json.loads(output)["text"] == "partial check: 12 of 256 weightings of one 4-node topology"


def test_roads_checked_copy_is_generated_from_artifact_on_all_entry_pages():
    for path in (ROOT / "docs/index.md", ROOT / "docs/learn/index.md"):
        assert 'data-roads-badge>See the core run artifact for the check scope' in path.read_text()
    world = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert 'A2.scopedBadge(card.evidence, null' in world
    assert "partial check" not in "".join(path.read_text().lower() for path in
        (ROOT / "docs/index.md", ROOT / "docs/learn/index.md",
         ROOT / "docs/assets/js/worlds/catalog-ui.js",
         ROOT / "docs/assets/js/atoms2/roads.js"))


def test_every_displayed_metro_outcome_recomputed(artifact, library):
    for card in artifact["cards"]:
        case = card["example"]
        args = [decode(arg) for arg in case["args"]]
        for source in case.get("input_from", []):
            minted = library.run(source["target"], tuple(decode(arg) for arg in source["args"]))
            assert encode_outcome(minted.outcome) == source["outcome"]
            assert minted.steps == source["steps"]
            args[source["index"]] = minted.outcome.value
        again = library.run(case["target"], tuple(args))
        assert encode_outcome(again.outcome) == case["outcome"], card["name"]
        assert again.steps == case["steps"]
    failing = artifact["failing"]
    assert encode_outcome(library.run(failing["target"], tuple(decode(arg) for arg in failing["args"])).outcome) == failing["outcome"]
    cards = {card["name"]: card["example"] for card in artifact["cards"]}
    assert cards["optimal"]["outcome"]["ok"]["tag"] == "false"
    assert cards["survives"]["outcome"]["ok"]["tag"] == "true"
    assert cards["cut_certificate"]["outcome"]["ok"]["tag"] == "true"
    assert cards["cost"]["outcome"]["ok"]["v"] == 12
    assert cards["mincut"]["outcome"]["ok"]["f"][0]["f"] == [
        {"t": "str", "v": road} for road in ("AB", "AC", "AD")]
    assert failing["outcome"] == {"bottom": "invalid"}


@pytest.mark.skipif(NODE is None, reason="Node unavailable")
def test_metro_browser_checker_agrees_with_core_and_detects_tampering(artifact):
    source = """
const roads = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
const core = require(process.argv[3]);
const checks = roads.coreRoadEvidence(core, graph);
core.cards.find(card => card.name === 'optimal').example.outcome.ok.tag = 'true';
let tamperingRejected = false;
try { roads.coreRoadEvidence(core, graph); } catch (error) { tamperingRejected = /disagree/.test(error.message); }
console.log(JSON.stringify({checks, tamperingRejected}));
"""
    output = subprocess.check_output([NODE, "-e", source,
        str(ROOT / "docs/assets/js/atoms2/roads.js"),
        str(ROOT / "docs/assets/data/atoms2/roads.json"), str(OUTPUT)], text=True)
    result = json.loads(output)
    assert all(result["checks"].values())
    assert result["tamperingRejected"]


def test_core_run_copy_does_not_revert_to_design_claims():
    pages = [ROOT / "docs/index.md", ROOT / "docs/learn/index.md"]
    for page in pages:
        text = page.read_text()
        assert "roads_core.json" in text
        assert "still a design proposal" not in text
        assert "whether these qualify needs a checked roads world" not in text
    world = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert "cut observation has no rebuilt, checked 0.5 export" not in world
    assert "roads_core.json" in world


def test_metro_worst_is_not_mislabelled_as_a_fast_core_run():
    assert "worst" not in TARGETS
    world = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert '["cost", "best", "optimal", "survives", "mincut", "cut_certificate"]' in world
    browser = (ROOT / "docs/assets/js/atoms2/roads.js").read_text()
    assert 'const answer = worst(graph, "A", "L");' in browser
    assert 'cards.get("worst").example' not in browser


def test_card_library_skips_only_expensive_unshown_definition(monkeypatch):
    import tools.atoms2_roads_export as exporter
    from opulse.worlds_v2.roads import story

    original = story.definitions
    seen = []

    def build():
        seen.extend(definition.name for definition in story.definitions())
        return "selected library"

    monkeypatch.setattr(exporter, "build_library", build)
    assert build_card_library() == "selected library"
    assert set(seen) == {definition.name for definition in original()} - {"worst"}
    assert story.definitions is original


def test_route_case_records_constructor_for_replay():
    from opulse.atoms.values import Card, Ok
    from tools.atoms2_roads_export import run_case

    raw = Card("RouteRaw", "route", ("graph", "A"))
    route = Card("Route", "val", (raw,))

    def run(name, args, trace=False):
        assert name in {"Route.make", "cost"}
        assert args == ((raw,) if name == "Route.make" else (route,))
        outcome = Ok(route if name == "Route.make" else 7)
        return SimpleNamespace(outcome=outcome, steps=3, trace=SimpleNamespace(name=name, steps=3, children=[]))

    case = run_case(SimpleNamespace(run=run), "cost", (route,), "cost(Route<graph,A>)")
    assert case["input_from"] == [{"index": 0, "target": "Route.make", "args": [case["args"][0]["f"][0]],
                                  "outcome": {"ok": case["args"][0]}, "steps": 3}]


def test_roads_check_uses_only_source_pinned_complete_export(tmp_path, monkeypatch):
    import sys

    import tools.atoms2_roads_export as exporter

    target = tmp_path / "roads_core.json"
    monkeypatch.setattr(exporter, "OUTPUT", target)
    monkeypatch.setattr(exporter, "input_digest", lambda: "source-digest")
    monkeypatch.setattr(exporter, "selected_definitions", lambda: [type("Card", (), {"name": "Route"})()])
    calls = []

    def rebuild():
        calls.append(True)
        result = {"schema": "opulse.roads_core/1", "world": "roads",
                  "map": "Metro", "cards": [{"name": "Route", "example": {"steps": 42}}],
                  "failing": {"outcome": {"bottom": "invalid"}}, "inputs_sha256": "source-digest"}
        result["payload_sha256"] = exporter.payload_digest(result)
        return result

    monkeypatch.setattr(exporter, "build_export", rebuild)
    monkeypatch.setattr(sys, "argv", ["atoms2_roads_export.py"])
    exporter.main()
    monkeypatch.setattr(sys, "argv", ["atoms2_roads_export.py", "--check"])
    exporter.main()
    assert len(calls) == 1

    changed = json.loads(target.read_text())
    changed["cards"][0]["example"]["steps"] += 1
    target.write_text(json.dumps(changed))
    with pytest.raises(SystemExit, match="1"):
        exporter.main()
    assert len(calls) == 2
    monkeypatch.setattr(sys, "argv", ["atoms2_roads_export.py"])
    exporter.main()
    assert json.loads(target.read_text())["cards"][0]["example"]["steps"] == 42
