"""Independent browser checker and page regression tests for the Metro design."""

import heapq
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/assets/data/atoms2/roads.json"
CHECKER = ROOT / "docs/assets/js/atoms2/roads.js"
NODE = shutil.which("node")


def test_fixture_graph_and_true_dependencies():
    data = json.loads(FIXTURE.read_text())
    assert data["status"] == "design" and len(data["graph"]["nodes"]) == 12
    assert len(data["graph"]["edges"]) == 23
    assert set(range(13)) == {entry["layer"] for entry in data["tower"]}
    definitions = {entry["name"]: entry for entry in data["tower"]}
    for entry in data["tower"]:
        assert entry["declaration"].endswith("given" if entry["layer"] == 0 else f'L{entry["layer"]}')
        for parent in entry["depends_on"]:
            assert parent in definitions and definitions[parent]["layer"] < entry["layer"]
    assert definitions["?survives"]["depends_on"] == ["@failures", "@explore"]
    assert definitions["worst"]["depends_on"] == ["Worst", "@failures", "best", "cost"]


def test_map_does_not_extend_over_closed_roads_and_truncates_on_closure():
    result = run_js("""
const assert = require('node:assert/strict');
const roads = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
let route = roads.extendMapRoute(graph, [], ['AB'], 'A');
assert.deepEqual(route, ['A']);
assert.equal(roads.extendMapRoute(graph, route, ['AB'], 'B'), null);
assert.deepEqual(route, ['A']);
route = roads.extendMapRoute(graph, route, [], 'B');
assert.deepEqual(route, ['A', 'B']);
assert.equal(roads.extendMapRoute(graph, route, [], 'L'), null);
assert.deepEqual(roads.extendMapRoute(graph, route, [], 'B'), ['A']);
const continuation = Object.keys(graph.edges).find(id => id.includes('B') && id !== 'AB');
assert(continuation);
route = roads.extendMapRoute(graph, route, [], continuation.replace('B', ''));
assert.equal(route.length, 3);
assert.deepEqual(roads.closeMapRoad(route, 'AB'), ['A']);
assert.deepEqual(roads.closeMapRoad(route, continuation), ['A', 'B']);
assert.deepEqual(roads.closeMapRoad(route, 'AC'), route);
assert.equal(roads.routeCost(graph, roads.closeMapRoad(route, 'AB'), ['AB']), null);
console.log(JSON.stringify({blocked: roads.extendMapRoute(graph, ['A'], ['AB'], 'B'), truncated: roads.closeMapRoad(route, 'AB')}));
""")
    assert result == {"blocked": None, "truncated": ["A"]}
    source = CHECKER.read_text()
    assert 'const next = extendMapRoute(graph, route, fieldsToList(closedField), id);' in source
    assert 'const remaining = closeMapRoad(route, id);' in source
    assert 'Route shortened because road ' in source


def test_challenge_keyboard_map_clicks_never_select_a_closed_edge():
    result = run_js("""
const assert = require('node:assert/strict');
const data = require(process.argv[2]);
class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.events = {}; this.attributes = {}; this.value = '';
    this.classList = {toggle() {}};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, handler) { this.events[name] = handler; }
  click() { this.events.click({currentTarget: this}); }
}
const closed = new Element('input'), route = new Element('input'), report = new Element('p');
const map = new Element('div'), zoom = new Element('button'), cue = new Element('p');
const edgeList = new Element('p'), form = new Element('form'), reveal = new Element('button');
const all = new Element('div');
const targets = {'[data-roads-zoom]': zoom, '[data-roads-map]': map,
  '[data-roads-map-cue]': cue, '[data-roads-report]': report,
  'input[name="closed"]': closed, 'input[name="route"]': route,
  '[data-roads-edge-list]': edgeList, 'form': form,
  '[data-roads-reveal]': reveal, '[data-roads-all]': all};
const challenge = {querySelector: selector => targets[selector]};
global.window = {location: {search: ''}};
global.document = {readyState: 'complete', currentScript: {src: 'http://localhost/assets/js/atoms2/roads.js'},
  querySelector: selector => selector.includes('[data-roads-challenge]') ? challenge : null,
  querySelectorAll: () => [], createElement: tag => new Element(tag),
  createElementNS: (_, tag) => new Element(tag)};
global.fetch = async () => ({ok: true, json: async () => data});
require(process.argv[1]);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  const controls = map.children.find(child => child.tag === 'details').children[1].children;
  const button = text => controls.find(control => control.textContent === text);
  const roadAB = controls.find(control => control.textContent.startsWith('Road AB ('));
  assert(roadAB);
  button('Junction A').click();
  roadAB.click();
  button('Junction B').click();
  assert.equal(route.value, 'A');
  assert.match(report.textContent, /open road/);
  roadAB.click();
  button('Junction B').click();
  assert.equal(route.value, 'A, B');
  roadAB.click();
  assert.equal(route.value, 'A');
  assert.match(report.textContent, /Route shortened because road AB closed/);
  closed.value = '';
  closed.events.input();
  route.value = 'A, B';
  route.events.input();
  closed.value = 'AB';
  closed.events.input();
  assert.equal(route.value, 'A');
  assert.match(report.textContent, /Route shortened because a selected road is closed/);
  route.value = 'A, B';
  route.events.input();
  assert.equal(route.value, 'A');
  console.log(JSON.stringify({route: route.value, closed: closed.value}));
})().catch(error => { console.error(error); process.exitCode = 1; });
""")
    assert result == {"route": "A", "closed": "AB"}


def test_review_r12_home_and_learn_draw_only_fixture_dependency_edges():
    home = (ROOT / "docs/index.md").read_text()
    learn = (ROOT / "docs/learn/index.md").read_text()
    source = CHECKER.read_text()
    assert 'data-roads-home-deps' in home
    assert 'Five dependent steps' not in home
    assert 'Selected dependency path' not in learn
    assert 'card.invented_dependencies.join(", ")' in source
    assert 'card.dependencies.join(", ")' in source
    result = run_js("""
global.document = {
  currentScript: {src: 'http://localhost/assets/js/atoms2/roads.js'},
  readyState: 'complete',
  querySelector() { return null; },
  createElement() { return {dataset: {}, children: [], append(...children) { this.children.push(...children); }}; }
};
global.A2 = {token(name) { return {dataset: {}, textContent: name}; }};
const roads = require(process.argv[1]);
const tower = require(process.argv[2]).tower;
const names = ['Route', 'cost', '@explore', 'best', '?optimal'];
const items = new Map(tower.map(item => [item.name, item]));
function drawnEdges(selected, buttons) {
  const container = document.createElement('ol');
  roads.dependencyRows(tower, selected).forEach(row =>
    roads.appendDependencyRow(container, row, items, buttons ? document.createElement('button') : null));
  return container.children.flatMap(entry => {
    const prerequisites = entry.children.at(-1);
    return prerequisites.children.filter(child => child && child.dataset && child.dataset.prerequisite)
      .map(child => [child.dataset.prerequisite, entry.dataset.name]);
  });
}
const all = tower.map(item => item.name);
console.log(JSON.stringify({home: drawnEdges(names, false), learn: drawnEdges(all, true)}));
""")
    fixture = json.loads(FIXTURE.read_text())
    for field, names in (("home", ["Route", "cost", "@explore", "best", "?optimal"]),
                         ("learn", [entry["name"] for entry in fixture["tower"]])):
        expected = [[parent, entry["name"]] for entry in fixture["tower"]
                    if entry["name"] in names for parent in entry["depends_on"]]
        assert result[field] == expected
    assert ["cost", "@explore"] not in result["home"]
    assert ["cost", "best"] in result["home"]


def test_road_and_research_badges_have_source_and_drawer_records():
    pages = ["index.md", "learn/index.md", "play/challenge.md",
             "research/index.md", "research/protocols.md", "research/experiments.md"]
    for filename in pages:
        page = (ROOT / "docs" / filename).read_text()
        for badge in re.findall(r'<(?:span|button)[^>]*class="[^"]*(?:a2-badge|ar-badge)[^"]*"[^>]*>.*?</(?:span|button)>', page):
            assert 'data-research-source="' in badge and "Designed example (" in badge, filename
        sources = re.findall(r'<span[^>]*data-(?:roads-badge|research-source="([^"]+)")[^>]*>(.*?)</span>', page)
        assert sources, filename
        if filename in ("index.md", "learn/index.md"):
            assert all(label == "See the core run artifact for the check scope"
                       for _, label in sources), filename
            assert 'A2.runBadge' in (ROOT / "docs/assets/js/atoms2/roads.js").read_text()
        else:
            assert all(label.startswith("Designed example (") and
                       ("design" in label or "audit template" in label) for _, label in sources), filename
    roads = (ROOT / "docs/assets/js/atoms2/roads.js").read_text()
    research = (ROOT / "docs/assets/js/atoms2/research-ui.js").read_text()
    assert 'root.A2.badge("design", {record})' in roads
    assert 'kit.badge("design", {record: record})' in research


def test_road_evidence_records_browser_scope_without_v2_artifact():
    result = run_js("""
const checker = require(process.argv[1]);
const data = require(process.argv[2]);
console.log(JSON.stringify(checker.roadsEvidence(data, data.graph, '/assets/data/atoms2/roads.json')));
""")
    assert result["evidence"]["scope"]["size"] == 277
    assert "0 to 88" in result["evidence"]["scope"]["description"]
    assert "Browser computation enumerates closures and simple routes" in result["evidence"]["scope"]["description"]
    assert result["artifact"]["file"] == "docs/assets/data/atoms2/roads.json"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_research_records_use_export_or_unrun_audit_template():
    if NODE is None:
        pytest.skip("node is not installed")
    script = """
const {researchEvidence} = require(process.argv[1]);
const versions = require(process.argv[2]);
const grammar = require(process.argv[3]);
const audit = require(process.argv[4]);
console.log(JSON.stringify(['versions', 'grammar'].map((source, i) =>
  researchEvidence(source, i ? grammar : versions, '/assets/data/worlds_v2/' + source + '.json')
).concat(researchEvidence('audit', audit, '/research/action-audit-v1.json'))));
"""
    result = subprocess.run([NODE, "-e", script,
                             str(ROOT / "docs/assets/js/atoms2/research-ui.js"),
                             str(ROOT / "docs/assets/data/worlds_v2/versions.json"),
                             str(ROOT / "docs/assets/data/worlds_v2/grammar.json"),
                             str(ROOT / "docs/research/action-audit-v1.json")],
                            capture_output=True, text=True, check=True)
    records = json.loads(result.stdout)
    assert [record["artifact"]["version"] for record in records[:2]] == [1, 1]
    assert all("no policy, model or ablation result" in record["scope"]["description"] for record in records[:2])
    assert records[2]["artifact"]["schema"] == "opulse.audit_template/1"
    assert "No run result" in records[2]["scope"]["description"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_research_badges_render_inspectable_source_records():
    if NODE is None:
        pytest.skip("node is not installed")
    script = """
const {renderBadges} = require(process.argv[1]);
const versions = require(process.argv[2]);
const badges = ['versions', 'versions', 'bad-source'].map(source => ({dataset:{researchSource:source},
  replaceWith(button) {this.button = button;}}));
const page = {querySelectorAll(selector) {
  if (selector === '[data-research-source]') return badges.slice(0, 2);
  return badges.filter(badge => selector.includes('"' + badge.dataset.researchSource + '"')).slice(0, 2);
}};
let fetches = 0;
global.fetch = async () => {fetches++; return {ok:true, json:async () => versions};};
const kit = {badge(status, options) {const classes = [];
  return {status, record:options.record, classes, classList:{add(value) {classes.push(value);}}};}};
renderBadges(page, kit, 'https://example.test/assets/js/atoms2/research-ui.js').then(() =>
  console.log(JSON.stringify({fetches, rendered:badges.slice(0, 2).map(b =>
    [b.button.status, b.button.record.artifact.file, b.button.classes.includes('ar-badge')])})));
"""
    result = subprocess.run([NODE, "-e", script,
                             str(ROOT / "docs/assets/js/atoms2/research-ui.js"),
                             str(ROOT / "docs/assets/data/worlds_v2/versions.json")],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"fetches": 1, "rendered": [
        ["design", "docs/assets/data/worlds_v2/versions.json", True],
        ["design", "docs/assets/data/worlds_v2/versions.json", True]]}


def run_js(script):
    if NODE is None:
        pytest.skip("node is not installed")
    result = subprocess.run([NODE, "-e", script, str(CHECKER), str(FIXTURE)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_challenge_fill_events_do_not_throw_but_svg_click_text_does():
    result = run_js("""
const {bindWitness} = require(process.argv[1]);
function field() {
  const handlers = {};
  return {value: '', addEventListener(type, handler) {handlers[type] = handler;},
    dispatchEvent(event) {if (handlers[event.type]) handlers[event.type](event);}};
}
const closed = field(), route = field(), report = {textContent: ''};
const maps = [];
bindWitness(closed, route, report, () => maps.push([closed.value, route.value]));
for (const [field, value] of [[closed, ''], [route, 'A, D, F, H, K, L']]) {
  field.value = value;
  field.dispatchEvent({type: 'input'});
  field.dispatchEvent({type: 'change'});
}
let clickError;
try {
  const controls = [{role: 'button'}, {innerText: 'Check answer', click() {}}];
  controls.find(item => item.innerText.trim() === 'Check answer');
} catch (error) {clickError = error.name;}
console.log(JSON.stringify({maps, report: report.textContent, clickError}));
""")
    assert result == {
        "maps": [["", ""], ["", "A, D, F, H, K, L"]],
        "report": "Answer changed. Check again.",
        "clickError": "TypeError",
    }


def test_all_checker_functions_and_confirmed_numbers():
    data = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
const candidate = ['A','D','F','H','K','L'];
const cases = checker.closures(graph, 2);
const best = checker.shortest(graph, 'A', 'L');
const worst = checker.worst(graph, 'A', 'L');
const result = {
  compares: [checker.compareLists(['AB','AD'],['AB','AC']), checker.compareLists(['A','D'],['A','C'])],
  closures: [checker.closures(graph, 0).length, checker.closures(graph, 1).length, cases.length],
  distinct: new Set(cases.map(item => item.join(','))).size,
  routes: checker.routes(graph,'A','L').length,
  costs: [checker.routeCost(graph,candidate), checker.routeCost(graph,['A','H','L']),
          checker.routeCost(graph,['A','D','A','L']), checker.routeCost(graph,candidate,['AD'])],
  best, worst, mincut: checker.mincut(graph,'A','L'),
  survival: cases.every(closed => checker.shortest(graph,'A','L',closed) !== null),
  judge: checker.judge(graph, worst.closed,worst.route),
  reversed: checker.judge(graph, worst.closed.slice().reverse(),worst.route),
  wrong: checker.judge(graph, [],best.route),
  invalid: checker.judge(graph,['NO'],best.route),
  nonoptimal: checker.judge(graph,[],candidate)
};
console.log(JSON.stringify(result));
""")
    assert data["compares"][0] > 0 and data["compares"][1] > 0
    assert data["closures"] == [1, 24, 277] and data["distinct"] == 277
    assert data["routes"] == 419 and data["costs"] == [12, None, None, None]
    assert data["best"] == {"route": ["A", "D", "G", "I", "K", "L"], "cost": 11}
    assert data["worst"]["cost"] == 13
    assert len(data["worst"]["closed"]) == 2
    assert data["worst"]["route"][0] == "A" and data["worst"]["route"][-1] == "L"
    assert data["mincut"] == ["AB", "AC", "AD"] and data["survival"]
    assert data["judge"]["correct"] and data["judge"]["cases"] == 277
    assert data["reversed"]["correct"] and data["reversed"]["closed"] == data["worst"]["closed"]
    assert not data["invalid"]["correct"]
    assert data["wrong"]["counterexample"]["cost"] > data["best"]["cost"]
    assert data["nonoptimal"]["counterexample"]["cost"] == 11


def test_checker_rejects_bad_budget_and_endpoints():
    result = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
const errors = [];
for (const fn of [() => checker.closures(graph,3), () => checker.routes(graph,'A','A'),
                  () => checker.mincut(graph,'X','L')]) {
  try { fn(); errors.push(false); } catch (error) { errors.push(true); }
}
console.log(JSON.stringify(errors));
""")
    assert result == [True, True, True]


def test_round_h_judge_returns_specific_error_or_valid_route():
    result = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
const worst = checker.worst(graph, 'A', 'L');
const cases = [
  checker.judge(graph, ['NO'], ['A', 'D', 'G', 'I', 'K', 'L']),
  checker.judge(graph, ['AB', 'AB'], ['A', 'D', 'G', 'I', 'K', 'L']),
  checker.judge(graph, ['AB', 'AD', 'AC'], ['A', 'D', 'G', 'I', 'K', 'L']),
  checker.judge(graph, ['AB'], ['A', 'H', 'L']),
  checker.judge(graph, worst.closed, checker.shortest(graph, 'A', 'L').route),
  checker.judge(graph, [], ['A', 'D', 'F', 'H', 'K', 'L'])
];
console.log(JSON.stringify(cases));
""")
    assert result[0]["reason"] == "Unknown road ID: NO."
    assert result[1]["reason"] == "Closed road IDs must be distinct; received AB, AB."
    assert result[2]["reason"] == "At most two roads may close; received 3."
    assert result[3]["counterexample"]["closed"] == ["AB"]
    assert result[3]["counterexample"]["route"][0] == "A"
    assert result[3]["counterexample"]["route"][-1] == "L"
    assert len(result[4]["counterexample"]["closed"]) == 2
    assert result[4]["counterexample"]["cost"] == 13
    assert result[5]["counterexample"]["cost"] == 11


def test_round_h_route_issue_identifies_exact_invalid_step():
    issues = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
console.log(JSON.stringify([
  checker.routeIssue(graph, [], []),
  checker.routeIssue(graph, ['B', 'E', 'L'], []),
  checker.routeIssue(graph, ['A', 'X', 'L'], []),
  checker.routeIssue(graph, ['A', 'D', 'A', 'C', 'E', 'H', 'L'], []),
  checker.routeIssue(graph, ['A', 'H', 'L'], []),
  checker.routeIssue(graph, ['A', 'D', 'G', 'I', 'K', 'L'], ['AD']),
  checker.routeIssue(graph, ['A', 'D', 'G', 'I', 'K', 'L'], [])
]));
""")
    assert issues == [
        "Provide at least two route junctions from A to L.",
        "Route must begin at A and end at L.",
        "Unknown junction: X.",
        "Repeated junction: A.",
        "No road joins A and H.",
        "Road AD is closed.",
        None,
    ]


def test_round_h_judge_reports_disconnecting_closure_without_fake_route():
    result = run_js("""
const checker = require(process.argv[1]);
const graph = {nodes: ['A', 'L'], edges: {AL: 1}};
console.log(JSON.stringify(checker.judge(graph, ['AL'], ['A', 'L'])));
""")
    assert result == {
        "correct": False,
        "reason": "Road AL is closed.",
        "counterexample": {"disconnected": ["AL"]},
    }


def test_round_h_survival_toggle_and_compact_map_contract():
    learn = (ROOT / "docs/learn/index.md").read_text()
    challenge = (ROOT / "docs/play/challenge.md").read_text()
    source = CHECKER.read_text()
    styles = (ROOT / "docs/assets/css/atoms2-roads.css").read_text()
    assert 'data-roads-survives type="button" aria-pressed="true">Hide survival prerequisites' in learn
    assert 'data-roads-path aria-label="Selected definitions with direct prerequisites"' in learn
    assert '<details class="roads-inventory">' in learn
    assert 'clearSelection() : highlight("?survives")' in source
    assert 'const coreRows = core.cards.filter(card => selectedCore.has(card.name));' in source
    assert 'The judge shows a valid route when yours fails' in challenge
    assert '.roads-map-home svg { min-width: 620px; }' in styles
    assert 'color-mix(in srgb, var(--md-default-fg-color, #203044) 60%, transparent)' in styles


def test_review_r10_challenge_map_fits_and_offers_readable_zoom():
    challenge = (ROOT / "docs/play/challenge.md").read_text()
    styles = (ROOT / "docs/assets/css/atoms2-roads.css").read_text()
    assert 'data-roads-zoom aria-pressed="false" aria-controls="roads-metro-map"' in challenge
    assert 'id="roads-metro-map" class="roads-map-wrap roads-map-challenge"' in challenge
    assert 'The whole map, from A to L, is shown.' in challenge
    assert '.roads-map-challenge svg { min-width: 0; }' in styles
    assert '.roads-map-challenge.is-zoomed svg { min-width: 720px; }' in styles
    assert '.roads-map-zoom, .roads-map-cue { display: block; }' in styles


def test_review_r10_map_zoom_resets_scroll_and_updates_accessible_cue():
    result = run_js("""
const {setMapZoom} = require(process.argv[1]);
const classes = new Set();
const container = {scrollLeft: 410, classList: {toggle(name, active) {
  if (active) classes.add(name); else classes.delete(name);
}}};
const button = {attributes: {}, setAttribute(name, value) {this.attributes[name] = value;}};
const cue = {};
setMapZoom(container, button, cue, true);
const zoomed = {classes: [...classes], scroll: container.scrollLeft, pressed: button.attributes['aria-pressed'],
  button: button.textContent, cue: cue.textContent};
container.scrollLeft = 310;
setMapZoom(container, button, cue, false);
console.log(JSON.stringify({zoomed, fitted: {classes: [...classes], scroll: container.scrollLeft,
  pressed: button.attributes['aria-pressed'], button: button.textContent, cue: cue.textContent}}));
""")
    assert result == {
        "zoomed": {"classes": ["is-zoomed"], "scroll": 0, "pressed": "true",
                   "button": "Fit whole map",
                   "cue": "Swipe the map sideways to see every road, or fit the whole map."},
        "fitted": {"classes": [], "scroll": 0, "pressed": "false",
                   "button": "Zoom in on map",
                   "cue": "The whole map, from A to L, is shown. Zoom in to read road labels."},
    }


def test_every_closure_matches_independent_dijkstra():
    graph = json.loads(FIXTURE.read_text())["graph"]
    edges = graph["edges"]
    names = sorted(edges)
    expected = []
    for closed in [()] + [(edge,) for edge in names] + [
        (first, second) for index, first in enumerate(names) for second in names[index + 1:]
    ]:
        blocked = set(closed)
        queue = [(0, "A")]
        seen = set()
        while queue:
            cost, current = heapq.heappop(queue)
            if current in seen:
                continue
            if current == "L":
                expected.append(cost)
                break
            seen.add(current)
            for edge, weight in edges.items():
                if edge in blocked or current not in edge:
                    continue
                other = edge[0] if edge[1] == current else edge[1]
                if other not in seen:
                    heapq.heappush(queue, (cost + weight, other))
        else:
            expected.append(None)
    actual = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
console.log(JSON.stringify(checker.closures(graph,2).map(closed => checker.shortest(graph,'A','L',closed)?.cost ?? null)));
""")
    assert actual == expected
    assert max(expected) == 13 and expected.count(None) == 0


def test_pages_replace_operations_only_story_with_road_thread():
    home = (ROOT / "docs/index.md").read_text()
    learn = (ROOT / "docs/learn/index.md").read_text()
    challenge = (ROOT / "docs/play/challenge.md").read_text()
    assert "Invent the pieces; then build with them." in home
    assert 'class="op-poster"' in home and "data-roads-home" in home
    assert "data-roads-survives" in learn and "277" in learn and "data-roads-given-layers" in learn
    assert "data-roads-challenge" in challenge and "one witness" in challenge
    assert "integer or NaN" not in home and "Three ways to combine" not in home
    for page in (home, learn, challenge):
        assert "atoms2-roads.css" in page
        assert "atoms2/roads.js" in page
        if page == challenge:
            assert '<p class="roads-badge"><span data-roads-badge>Designed example (roads design record)</span></p>' in page
        else:
            assert '<p class="roads-badge"><span data-roads-badge>See the core run artifact for the check scope</span></p>' in page


def test_review_b_home_has_theme_poster_full_chain_and_map():
    home = (ROOT / "docs/index.md").read_text()
    script = (ROOT / "docs/assets/js/atoms2/roads.js").read_text()
    assert "  - toc" in home
    assert 'assets/css/atoms2-roads.css' in home and 'assets/js/atoms2/roads.js' in home
    assert 'body[data-md-color-scheme="slate"] .op-poster-light' in home
    assert 'body:not([data-md-color-scheme="slate"]) .op-poster-dark' in home
    assert 'data-roads-chain' in home and 'data-roads-map' in home
    assert 'data-roads-answer' in home and 'data-roads-step' in home
    assert 'chain.querySelectorAll("button")' in script and 'updateMap({ route: askedRoute' in script
    assert 'best: index === steps.length - 1 ? bestRoute.route : []' in script


def test_review_b_challenge_map_and_accessible_inputs():
    challenge = (ROOT / "docs/play/challenge.md").read_text()
    script = (ROOT / "docs/assets/js/atoms2/roads.js").read_text()
    assert 'data-roads-map' in challenge and 'data-roads-edge-list' in challenge
    assert 'Answer shape and scope' in challenge
    assert '"aria-pressed"' in script and 'controls.addEventListener("keydown"' not in script
    assert 'closedField.addEventListener("input", changed)' in script
    assert 'routeField.addEventListener("input", changed)' in script
    assert 'syncMap();' in script
    assert 'params.get("check") === "1"' in script
    assert 'params.get("reveal") === "1"' in script
    assert 'docs/assets/data/atoms2/roads.json' not in challenge


def test_map_layout_has_all_weighted_roads():
    result = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
console.log(JSON.stringify(checker.mapLayout(graph)));
""")
    graph = json.loads(FIXTURE.read_text())["graph"]
    assert len(result) == 23
    assert {road["id"]: road["weight"] for road in result} == graph["edges"]
    assert all(len(road["label"]) == 2 for road in result)
    assert len({tuple(road["label"]) for road in result}) == 23


def test_map_labels_are_normal_offset_and_do_not_overlap():
    layout = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
console.log(JSON.stringify(checker.mapLayout(graph)));
""")
    for index, road in enumerate(layout):
        x, y = road["label"]
        from_x, from_y = road["from"]
        to_x, to_y = road["to"]
        dx, dy = to_x - from_x, to_y - from_y
        along = ((x - from_x) * dx + (y - from_y) * dy) / (dx * dx + dy * dy)
        offset = abs((x - from_x) * dy - (y - from_y) * dx) / (dx * dx + dy * dy) ** .5
        assert .19 <= along <= .81 and 15 <= offset <= 49
        width = len(f'{road["id"]} {road["weight"]}') * 3.8 + 3
        assert width + 4 <= x <= 716 - width and 15 <= y <= 425
        for other in layout[:index]:
            other_x, other_y = other["label"]
            other_width = len(f'{other["id"]} {other["weight"]}') * 3.8 + 3
            assert abs(x - other_x) >= width + other_width + 4 or abs(y - other_y) >= 22


def test_map_label_chips_clear_non_own_roads():
    layout = run_js("""
const checker = require(process.argv[1]);
const graph = require(process.argv[2]).graph;
console.log(JSON.stringify(checker.mapLayout(graph)));
""")
    for road in layout:
        x, y = road["label"]
        half_width = len(f'{road["id"]} {road["weight"]}') * 3.8 + 3
        for other in layout:
            if other["id"] == road["id"]:
                continue
            start = 0.0
            end = 1.0
            for origin, distance, minimum, maximum in (
                (other["from"][0], other["to"][0] - other["from"][0], x - half_width, x + half_width),
                (other["from"][1], other["to"][1] - other["from"][1], y - 11, y + 11),
            ):
                if distance == 0:
                    if not minimum <= origin <= maximum:
                        end = -1
                else:
                    crossings = sorted(((minimum - origin) / distance, (maximum - origin) / distance))
                    start = max(start, crossings[0])
                    end = min(end, crossings[1])
            segment_length = sum((other["to"][axis] - other["from"][axis]) ** 2 for axis in (0, 1)) ** .5
            assert max(0, end - start) * segment_length <= 2.001, (road["id"], other["id"])


def test_home_and_challenge_use_the_same_label_layout():
    source = CHECKER.read_text()
    assert 'mapLayout(graph).forEach(({ id, weight, from, to, label: position })' in source
    assert 'labelGroup.append(svgElement("text", { x: position[0], y: position[1], class: "roads-edge-label" }' in source
    assert 'if (options.interactive) labelGroup.addEventListener("click", () => options.onRoad(id));' in source
    assert 'svg.append(labels);' in source
    assert 'class: "roads-label-chip"' in source
    assert 'if (options.interactive) group.append(svgElement("text"' not in source


def test_review_round_three_home_chain_ends_and_poster_follows_theme():
    home = (ROOT / "docs/index.md").read_text()
    script = CHECKER.read_text()
    styles = (ROOT / "docs/assets/css/atoms2-roads.css").read_text()
    assert home.index('data-roads-chain') < home.index('data-roads-map')
    assert '  - toc' in home and 'assets/js/opulse-video.js' not in home
    assert 'assets/css/opulse-video.css' not in home
    assert '<video' not in home and 'Watch the introduction' not in home
    assert 'timer = setInterval(advance, 520)' in script
    assert 'if (index < steps.length - 1) index++' in script
    assert 'if (index === steps.length - 1) {' in script and 'if (timer) stepStatus.textContent' in script
    assert 'index = (index + 1) % steps.length' not in script
    assert '"Replay recorded steps"' in script and 'play.click()' not in script
    assert 'body[data-md-color-scheme="slate"] .op-poster-light' in home
    assert 'body:not([data-md-color-scheme="slate"]) .op-poster-dark' in home
    assert '.op-poster img { display: block; width: 100%; height: auto; }' in home
    assert '.roads-chain-step .a2-tok, .roads-learn > p code, .roads-layers li .a2-x { white-space: nowrap; }' in styles
    assert '.roads-layers li .a2-tok-given { color: var(--a2-chip-ink, #fff); }' in styles


def test_review_round_three_survival_selected_with_named_prerequisites():
    data = json.loads(FIXTURE.read_text())
    definitions = {entry["name"]: entry for entry in data["tower"]}
    selected = set()

    def visit(name):
        if name in selected:
            return
        selected.add(name)
        for prerequisite in definitions[name]["depends_on"]:
            visit(prerequisite)

    visit("?survives")
    assert {"@failures", "@explore", "close", "Route", "?map"} <= selected
    assert "best" not in selected and "worst" not in selected
    script = CHECKER.read_text()
    learn = (ROOT / "docs/learn/index.md").read_text()
    assert 'highlight("?survives", false);' in script
    assert '"Selected target: " + name + ". Invented prerequisites shown: "' in script
    assert 'card.querySelector(".roads-role").textContent = isTarget ? "Target" : isPrerequisite ? "Prerequisite" : "";' in script
    assert 'card.classList.toggle("is-selected", isTarget)' in script
    assert learn.index('data-roads-deps') < learn.index('data-roads-layers') < learn.index('data-roads-given-layers')


def test_review_round_four_witness_change_clears_verdict_for_both_fields_and_map():
    result = run_js("""
const checker = require(process.argv[1]);
function field() {
  const listeners = {};
  return { addEventListener(name, callback) { listeners[name] = callback; },
    input() { listeners.input(); } };
}
const closed = field();
const route = field();
const report = { textContent: 'Correct. Cost 13' };
let updates = 0;
const onMapSelection = checker.bindWitness(closed, route, report, () => updates++);
route.input();
const afterRoute = report.textContent;
report.textContent = 'Correct. Cost 13';
closed.input();
const afterClosure = report.textContent;
report.textContent = 'Correct. Cost 13';
onMapSelection();
console.log(JSON.stringify({ afterRoute, afterClosure, afterMap: report.textContent, updates }));
""")
    assert result == {
        "afterRoute": "Answer changed. Check again.",
        "afterClosure": "Answer changed. Check again.",
        "afterMap": "Answer changed. Check again.",
        "updates": 3,
    }
    source = CHECKER.read_text()
    assert 'else if (closed.length < 2) closedField.value = [...closed, id].join(", ");' in source
    assert '          changed(false); announceMap(note);' in source
    assert '          changed(false); announceMap();' in source
    assert 'changed = bindWitness(closedField, routeField, report, syncMap);' in source


def test_review_round_four_home_map_and_poster_use_available_space():
    home = (ROOT / "docs/index.md").read_text()
    styles = (ROOT / "docs/assets/css/atoms2-roads.css").read_text()
    script = CHECKER.read_text()
    assert 'Start A / destination L' in home
    assert 'roads-map-and-notes' in home and 'class="op-poster"' in home
    assert '.roads-map-home svg { min-width: 620px; }' in styles
    assert '.roads-map-and-notes { display: grid;' in styles
    assert 'width: min(100%, 38rem)' in home
    assert 'if (index === steps.length - 1) {' in script and 'pause();' in script


def test_review_round_f_long_home_expression_wraps_without_changing_copy():
    home = (ROOT / "docs/index.md").read_text()
    script = CHECKER.read_text()
    styles = (ROOT / "docs/assets/css/atoms2-roads.css").read_text()
    # Notation v3: Home holds a slot that the script fills with the stored optimal call.
    assert "<span data-roads-optimal>" in home and 'home.querySelector("[data-roads-optimal]")' in script
    assert 'roadExpression(optimalText, {given: givenNames})' in script
    # Notation v3: declarations are looked up by their stored text; design text otherwise.
    assert 'const declaration = roadExpression(stored, {given: givenNames, design: !(root.N3 && root.N3.lookup(stored, "roads"))});' in script
    assert ".roads-card p .a2-expr { display: inline; white-space: normal; overflow-wrap: normal; }" in styles
    assert ".roads-card p .a2-expr .a2-x { display: inline-block; }" in styles
    assert '.roads-card [data-roads-report], .roads-card [data-roads-all] { overflow-wrap: anywhere; }' in styles
    assert ".roads-card p .a2-expr { display: inline-block;" not in styles


def test_road_expression_wraps_at_commas_without_mutating_copy():
    result = run_js("""
const {roadExpression} = require(process.argv[1]);
global.document = {
  createTextNode(text) { return {nodeType: 3, textContent: text}; },
  createElement(tagName) { return {nodeType: 1, tagName, textContent: ''}; }
};
global.A2 = {expr() {
  const expression = {childNodes: []};
  const pieces = ['?optimal', '{', 'Route', '<', 'Metro', ',A,D,F,H,K,L>}'];
  pieces.forEach((piece, index) => {
    const child = index === 0 || index === 2 || index === 4
      ? {nodeType: 1, textContent: piece}
      : {nodeType: 3, textContent: piece};
    child.replaceWith = (...nodes) => expression.childNodes.splice(expression.childNodes.indexOf(child), 1, ...nodes);
    expression.childNodes.push(child);
  });
  return expression;
}};
const expression = roadExpression('?optimal{Route<Metro,A,D,F,H,K,L>}');
console.log(JSON.stringify({copy: expression.childNodes.map(node => node.textContent).join(''),
  breaks: expression.childNodes.filter(node => node.tagName === 'wbr').length,
  segments: expression.childNodes.filter(node => node.nodeType === 3).map(node => node.textContent)}));
""")
    assert result == {
        "copy": "?optimal{Route<Metro,A,D,F,H,K,L>}",
        "breaks": 6,
        "segments": ["{", "<", ",", "A,", "D,", "F,", "H,", "K,", "L>}"],
    }


def test_given_road_atoms_have_no_layer_zero_caption_and_pass_expression_provenance():
    result = run_js("""
const roads = require(process.argv[1]);
const tower = require(process.argv[2]).tower;
const given = tower.filter(item => item.layer === 0).map(item => item.name);
global.A2 = {expr(text, options) { return {text, options, childNodes: []}; }};
const expression = roads.roadExpression('obj Route<g: Roads> L1', {given});
console.log(JSON.stringify({given, caption: roads.layerPrefix(0), invented: roads.layerPrefix(8),
  copied: expression.text, passed: expression.options.given}));
""")
    expected = [entry["name"] for entry in json.loads(FIXTURE.read_text())["tower"] if entry["layer"] == 0]
    assert result == {"given": expected, "caption": "", "invented": "L8 ",
                      "copied": "obj Route<g: Roads> L1", "passed": expected}
    source = CHECKER.read_text()
    assert 'const givenNames = tower.filter(item => item.layer === 0).map(item => item.name);' in source
    assert 'button.append(layerPrefix(item.layer), label(item.name, item.kind, item.layer));' in source


def test_review_r9_layers_derive_from_dependencies_not_fixture_layer_numbers():
    result = run_js("""
const roads = require(process.argv[1]);
const fixture = require(process.argv[2]);
const tower = roads.towerLayers(fixture.tower);
const layerByName = new Map(tower.map(entry => [entry.name, entry.layer]));
const layers = Object.fromEntries(tower.map(entry => [entry.name, entry.layer]));
const sorted = tower.every((entry, index) => !index || tower[index - 1].layer <= entry.layer);
const declarationsMatch = tower.every(entry => entry.declaration.endsWith(entry.layer === 0 ? ' given' : ' L' + entry.layer));
const dependenciesMatch = tower.every(entry => entry.layer === (entry.declaration.endsWith(' given') ? 0 :
  1 + Math.max(0, ...entry.depends_on.map(name => layerByName.get(name)))));
console.log(JSON.stringify({layers, sorted, declarationsMatch, dependenciesMatch,
  originalClosure: fixture.tower.find(entry => entry.name === 'Closure').layer}));
""")
    assert result["layers"] == {
        "Roads": 0, "Edges": 0, "Worst": 0, "Metro": 0, "edge": 0,
        "?map": 0, "@chain": 0, "?size": 0, "Route": 1,
        "cost": 2, "@explore": 2, "best": 3, "?optimal": 4,
        "Closure": 1, "close": 2, "@failures": 3, "?survives": 4,
        "worst": 4, "mincut": 1, "?cut_certificate": 5,
    }
    assert result["originalClosure"] == 6
    assert result["sorted"] and result["declarationsMatch"] and result["dependenciesMatch"]


def test_review_r9_tower_rejects_unknown_cycles_and_givens_with_dependencies():
    result = run_js("""
const {towerLayers} = require(process.argv[1]);
const cases = [
  [{name: 'A', declaration: 'obj A L1', depends_on: ['B']}],
  [{name: 'A', declaration: 'obj A L1', depends_on: ['B']},
   {name: 'B', declaration: 'obj B L1', depends_on: ['A']}],
  [{name: 'A', declaration: 'obj A given', depends_on: ['B']},
   {name: 'B', declaration: 'obj B given', depends_on: []}],
  [{name: 'A', declaration: 'obj A given', depends_on: []},
   {name: 'A', declaration: 'obj A given', depends_on: []}]
];
console.log(JSON.stringify(cases.map(tower => { try { towerLayers(tower); return null; }
  catch (error) { return error.message; } })));
""")
    assert result == ["Unknown road dependency B", "Cyclic road dependency A",
                      "Given road definition has dependencies: A", "Duplicate road definition"]


def test_review_rv11_road_design_dependencies_are_not_misrepresented_as_unchecked_runs():
    result = run_js("""
const {observationDesignIssue} = require(process.argv[1]);
const tower = require(process.argv[2]).tower;
console.log(JSON.stringify(Object.fromEntries(tower.filter(item => item.kind === 'observation')
  .map(item => [item.name, observationDesignIssue(item, tower)]))));
""")
    assert result["?map"] == result["?size"] == ""
    for name in ("?optimal", "?survives", "?cut_certificate"):
        assert "Proposed dependencies:" in result[name]
        assert "Spec 0.5 permits pure definitions on observed values; whether these qualify needs a checked roads world." in result[name]
        assert "reject" not in result[name].lower()
    assert "cost, best" in result["?optimal"]
    assert "@failures, @explore" in result["?survives"]
    assert "mincut, close, @explore" in result["?cut_certificate"]
    home = (ROOT / "docs/index.md").read_text()
    learn = (ROOT / "docs/learn/index.md").read_text()
    for page in (home, learn):
        assert "proposed dependencies" not in page
        assert "whether these qualify needs a checked roads world" not in page
        assert "still a design proposal" not in page
        assert "roads_core.json" in page
    assert home.index('data-roads-home') < home.index('data-a2="first-tower"')
    assert learn.index('data-roads-learn') < learn.index('data-a2="first-tower"')
    assert ".roads-design-limit code, .roads-learn p code { white-space: nowrap; overflow-wrap: normal; word-break: normal; }" in (
        ROOT / "docs/assets/css/atoms2-roads.css").read_text()
