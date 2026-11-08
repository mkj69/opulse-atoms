"""Regression checks for the two atoms-v2 Learn pages and their example data."""

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
DATA = ROOT / "docs/assets/data/atoms2"
JS = ROOT / "docs/assets/js/atoms2"


@pytest.mark.parametrize("page,script,data", [
    ("kinds", "learn-kinds.js", "grammar.json"),
    ("checks", "learn-checks.js", "checks.json"),
])
def test_page_wiring(page, script, data):
    text = (ROOT / "docs/learn" / f"{page}.md").read_text()
    assert f'../../assets/js/atoms2/{script}' in text
    assert f'../../assets/data/atoms2/{data}' in text
    assert '../../assets/css/learn.css' in text
    assert '../../assets/js/atoms2/learn-evidence.js' in text
    assert '../../assets/data/atoms2/walk.json' in text
    assert "<noscript>" in text
    assert "This page is being rebuilt" not in text
    # Notation v3 glyphs may appear only inside display formulas and inline code.
    prose = re.sub(r'<code class="n3"[^>]*>.*?</code>|`[^`\n]+`', "", text)
    assert not re.search(r"[⟨⟩⟦⟧⦅⦆ℤℚ♠♦○◉◆◇■★▲♣⊙⁺⁻—–]", prose)


def test_grammar_has_six_unique_kinds_and_distinct_depends():
    grammar = json.loads((DATA / "grammar.json").read_text())
    cards = grammar["cards"]
    assert [card["kind"] for card in cards] == [
        "object", "operation", "combinator", "observation", "law", "bridge"]
    assert len({card["name"] for card in cards}) == 6
    assert [card["layer"] for card in cards] == [1, 1, 2, 3, 4, 2]
    assert all(card["definition"] and card["depends_on"] and card["effect"] for card in cards)
    assert "obj Frac = Quot[Pair<Int, Int>, reduce] L2" == grammar["template"]["instances"][0]["definition"]
    assert "obj Hour = Quot[Int, mod12] L2" == grammar["template"]["instances"][1]["definition"]
    assert [mode["name"] for mode in grammar["modes"]] == [
        "Fixpoint until stable", "Memoized recursion", "Turns", "Derived folds"]
    assert grammar["digits"] == len(re.findall(r"\d+", grammar["expression"])) == 8


def test_copyable_examples_have_no_placeholder_and_each_mode_has_a_result():
    grammar = json.loads((DATA / "grammar.json").read_text())
    assert all("..." not in card["name"] for card in grammar["cards"])
    assert all(card["job"] and card["form"] for card in grammar["cards"])
    assert all(item["example"] and item["result"] and item["evidence"].startswith("Designed canonicalization:")
               for item in grammar["template"]["instances"])
    assert all(mode["example"] and mode["result"] for mode in grammar["modes"])
    assert all(mode["result"].startswith("Designed ") for mode in grammar["modes"]
               if mode["name"] != "Memoized recursion")
    assert "core chart run above returns 429" in grammar["modes"][1]["result"]
    script = (JS / "learn-kinds.js").read_text()
    assert "../../reference/" in script
    assert "The grammar core runs " in script
    assert "outside that checked domain" in script
    assert "separate calculation, not a second core certificate" in script


@requires_node
def test_displayed_grammar_words_match_claimed_chart_count():
    grammar = json.loads((DATA / "grammar.json").read_text())
    word = grammar["input"]
    assert word.startswith("Word<") and word.endswith(">")
    tokens = word[5:-1].split(",")
    assert tokens[::2] == ["2"] * grammar["digits"]
    assert all(operator in ('"+"', '"*"') for operator in tokens[1::2])
    assert "".join(token.strip('"') for token in tokens) == grammar["expression"]
    assert grammar["cards"][3]["name"] == f"?parse_count{{{word}}}"

    memo = grammar["modes"][1]
    assert memo["example"] == f"@chart[one,multiply,identity,combine_count,zero]({word})"
    counts = [1]
    for size in range(1, grammar["digits"]):
        counts.append(sum(counts[left] * counts[size - 1 - left] for left in range(size)))
    core = json.loads((DATA / "grammar_core.json").read_text())
    stated_count = int(re.search(r"Ok\((\d+)\)", core["rows"]["observation"]["example"]["outcome"]).group(1))
    assert counts[-1] == stated_count == 429
    assert "429 binary parse trees" in (ROOT / "docs/learn/kinds.md").read_text()
    assert core["input"].startswith("Word.tokens<")
    assert core["rows"]["combinator"]["example"]["outcome"] == "Ok(429)"

    script = """
const assert = require('node:assert/strict');
global.window = global;
require('./docs/assets/js/atoms2/learn-kinds.js');
const data = require('./docs/assets/data/atoms2/grammar.json');
assert.equal(A2.learnKinds.countWordTrees(data.input), 429n);
assert.equal(A2.learnKinds.countWordTrees(data.input), A2.learnKinds.countTrees(data.digits));
assert.equal(A2.learnKinds.countWordTrees(data.modes[1].example.match(/Word<[^>]+>/)[0]), 429n);
assert.equal(A2.learnKinds.countWordTrees('Word<2,"+",2,"*",2,"+",2,"*",2,"+",2,"*",2,"+",2,"*",2>'), 1430n);
assert.throws(() => A2.learnKinds.countWordTrees('Word<2,+,>'), TypeError);
assert.throws(() => A2.learnKinds.countWordTrees('Word<2,+,2>'), TypeError);
assert.throws(() => A2.learnKinds.countWordTrees('Word<2,2>'), TypeError);
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_displayed_word_and_postfix_values_parse_as_source():
    from opulse.atoms.notation import parse_value

    grammar = json.loads((DATA / "grammar.json").read_text())
    values = [grammar["input"], grammar["detailed_tree"]["tree"],
              grammar["detailed_tree"]["postfix"]]
    values += [value for card in grammar["cards"] for value in re.findall(r"Word<[^>]+>", card["name"])]
    values += [value for mode in grammar["modes"] for value in re.findall(r"(?:Word|List)<[^>]+>", mode["example"] + mode["result"])]
    assert values
    for value in values:
        parse_value(value)


@requires_node
def test_walk_example_cost_matches_its_given_trace_not_just_body_range():
    walk = json.loads((DATA / "walk.json").read_text())
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./docs/assets/js/atoms2/learn-checks.js');
const walk = require('./docs/assets/data/atoms2/walk.json');
for (const item of walk.definitions) {
  const result = A2.learnChecks.exampleCost(item.example);
  assert.equal(result.total, item.example.layer0_steps);
}
const even = walk.definitions[0];
assert.equal(A2.learnChecks.exampleCost(even.example).total, 2);
assert.deepEqual(A2.learnChecks.exampleCost(even.example).calls.map(step => step.call), ['is_even', 'Even._pack']);
assert.equal(even.stages.find(stage => stage.station === 'verified').cost.steps.max, 1);
assert.throws(() => A2.learnChecks.exampleCost({ ...even.example, layer0_steps: 1 }), /Inconsistent/);
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
    source = (JS / "learn-checks.js").read_text()
    assert "Recorded body cost on " in source
    assert "Example trace: " in source


def test_prerequisite_and_selected_probe_states_are_explicit():
    kinds = (JS / "learn-kinds.js").read_text()
    checks = (JS / "learn-checks.js").read_text()
    assert "Six kinds at a glance" in kinds
    assert 'href: "#kind-" + edge.kind' in kinds
    assert "(invented " in kinds and "(given or library)" in kinds
    assert '"Selected: " + agent.name' in checks
    assert '"Switch to: "' in checks


@requires_node
def test_dependency_graph_has_only_declared_edges():
    grammar = json.loads((DATA / "grammar.json").read_text())
    cards = grammar["cards"]
    assert cards[0]["depends_on"] == ["Int", "Op"]
    assert cards[1]["depends_on"] == ["Word"]
    assert cards[2]["depends_on"] == ["split", "one", "multiply", "identity", "combine_count", "zero"]
    assert cards[3]["depends_on"] == ["@chart", "one", "multiply", "identity", "combine_count", "zero"]
    assert cards[5]["depends_on"] == ["ExprTree", "@fold"]
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./docs/assets/js/atoms2/learn-kinds.js');
const cards = require('./docs/assets/data/atoms2/grammar.json').cards;
const edges = A2.learnKinds.dependencyEdges(cards);
assert.deepEqual(edges[0].edges.map(edge => edge.kind), [null, null]);
assert.deepEqual(edges[1].edges.map(edge => edge.kind), [null]);
assert.deepEqual(edges[2].edges.map(edge => edge.kind), ['operation', null, null, null, null, null]);
assert.deepEqual(edges[3].edges.map(edge => edge.kind), ['combinator', null, null, null, null, null]);
assert.deepEqual(edges[5].edges.map(edge => edge.kind), ['object', null]);
assert(!edges[5].edges.some(edge => edge.kind === 'law'));
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_grammar_observation_uses_core_chart_without_proposed_probe():
    grammar = json.loads((DATA / "grammar.json").read_text())
    cards = grammar["cards"]
    observation = cards[3]
    core = json.loads((DATA / "grammar_core.json").read_text())
    assert "@chart[one,multiply,identity,combine_count,zero](w) L3" in observation["definition"]
    assert "read_parse_count" not in observation["definition"] + (JS / "learn-kinds.js").read_text()
    assert core["rows"]["observation"]["layer"] == observation["layer"]
    assert core["rows"]["observation"]["status"] == "bounded"
    assert "layer: row ? row.layer : card.layer" in (JS / "learn-kinds.js").read_text()


def test_grammar_layers_are_one_plus_deepest_direct_dependency():
    grammar = json.loads((DATA / "grammar.json").read_text())
    cards = grammar["cards"]
    names = {"ExprTree": 1, "split": 1, "@chart": 2, "?parse_count": 3,
             "#assoc_count": 4, "~to_rpn": 2}
    for card in cards:
        assert card["layer"] == 1 + max(names.get(dep, 0) for dep in card["depends_on"])
        assert card["definition"].endswith(f'L{card["layer"]}')
    assert cards[4]["depends_on"] == ["?parse_count", "binary_ops"]
    assert cards[5]["depends_on"] == ["ExprTree", "@fold"]
    core = json.loads((DATA / "grammar_core.json").read_text())
    assert [core["rows"][kind]["layer"] for kind in ("object", "operation", "combinator", "observation")] == [1, 1, 2, 3]


def test_checks_walkthrough_keeps_definition_dependencies_separate():
    checks = json.loads((DATA / "checks.json").read_text())
    observation = checks["walkthrough"]["inventions"][3]
    assert observation["declaration"].endswith("L2")
    assert "read_revision(r)" in observation["declaration"]
    assert "not a dependency" in observation["call"]
    script = (JS / "learn-checks.js").read_text()
    assert "These definitions do not form a connected dependency tower" in script
    assert "Spec 0.5 still rejects this call: bump_even and advance take the truth sort Even" in script
    assert "already observed or explicitly public values" in script
    assert "item.kind === \"observation\"" in script


def test_scoped_law_and_canonical_templates():
    kinds = (JS / "learn-kinds.js").read_text()
    grammar = json.loads((DATA / "grammar.json").read_text())
    assert '"Copy scoped proposed law "' in kinds
    assert "Core runs and remaining designs" in kinds
    assert 'row.evidence.method + " checks for " + row.name' in kinds
    assert 'unscopedRows.map(function (row) { return row.name; })' in kinds
    assert [(item["example"], item["result"]) for item in grammar["template"]["instances"]] == [
        ("Frac<2, 4>", "Frac<1, 2>"), ("Hour<14>", "Hour<2>")]


def test_four_kind_walkthrough_uses_the_kernel_ledger():
    walk = json.loads((DATA / "walk.json").read_text())
    assert [item["kind"] for item in walk["definitions"]] == [
        "object", "operation", "combinator", "observation"]
    for item in walk["definitions"]:
        assert item["failure"]["error"]
        for stage in item["stages"]:
            if stage["status"] == "promoted":
                assert stage["evidence"]["method"] in ("exhaustive", "bounded")
    page = (ROOT / "docs/learn/checks.md").read_text()
    assert "assets/data/atoms2/walk.json" in page
    script = (JS / "learn-checks.js").read_text()
    assert "Evidence rules before the walkthrough" in script
    assert "One 12-junction reachability" in script


def test_observation_copy_matches_exported_prior_result():
    walk = json.loads((DATA / "walk.json").read_text())
    combinator = next(item for item in walk["definitions"] if item["kind"] == "combinator")
    observation = next(item for item in walk["definitions"] if item["kind"] == "observation")
    result = combinator["example"]["outcome"]
    assert result.startswith("Ok(") and result.endswith(")")
    prior_result = result[3:-1]
    assert observation["example"]["input"] == f"?number{{{prior_result}}}"
    assert observation["example"]["trace"][-1]["call"] == "read_number"

    page = (ROOT / "docs/learn/checks.md").read_text()
    script = (JS / "learn-checks.js").read_text()
    combinator_name, input_value = combinator["example"]["input"].split("(", 1)
    escaped_input = input_value[:-1].replace("<", "&lt;").replace(">", "&gt;")
    escaped_result = prior_result.replace("<", "&lt;").replace(">", "&gt;")
    assert f'`{combinator_name}` on <code>{escaped_input}</code> returns <code>{escaped_result}</code>' in page
    assert "passes that result as the prior observation input to `observe`" in page
    assert "prior combinator's result is passed to observe" in script
    assert "observation receives the combinator's result as input" in script
    assert "does not call the combinator" in page
    assert "Spec 0.5 also permits pure combinators on observed values" in script
    assert "not passed into this observation" not in script
    assert "does not consume the combinator's output" not in page


def test_mobile_kind_forms_are_visible_and_role_details_follow_the_templates():
    script = (JS / "learn-kinds.js").read_text()
    css = (ROOT / "docs/assets/css/learn.css").read_text()
    assert 'class: "a2-learn-form"' in script
    assert 'class: "a2-learn-form-label" }, "Example: "' in script
    assert 'href: "#kind-" + card.kind' in script
    assert 'host.replaceChildren(overview, hero,' in script
    assert 'grid, chain, detailed,' in script
    mobile = css.split('@media (max-width: 680px) {\n  .a2-learn-overview', 1)[1]
    assert '.a2-learn-overview tr { display: block; min-width: 0;' in mobile
    assert '.a2-learn-overview td { display: block; min-width: 0;' in mobile
    assert '.a2-learn-form-label { display: inline;' in mobile


@requires_node
def test_lifecycle_switcher_shows_only_selected_kind_and_keeps_details():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
function el(tag, attrs = {}, children = []) {
  const node = { tag, attrs, children: Array.isArray(children) ? children : [children],
    hidden: attrs.hidden || false, id: attrs.id,
    appendChild(child) { this.children.push(child); },
    setAttribute(name, value) { this.attrs[name] = value; } };
  return node;
}
global.A2 = { el, badge: () => el('badge'), expr: text => text,
  hasRecordedScope: evidence => !!(evidence && evidence.scope && evidence.scope.checked && evidence.scope.checked !== 'unrecorded'),
  scopedBadge: () => el('badge'), runBadge: () => el('badge'),
  KIND6_META: Object.fromEntries(['object', 'operation', 'combinator', 'observation'].map(kind => [kind, { word: kind }])) };
require('./docs/assets/js/atoms2/learn-checks.js');
const walk = require('./docs/assets/data/atoms2/walk.json');
const section = A2.learnChecks.walkPanel(walk, '../../assets/data/atoms2/walk.json');
const switcher = section.children.find(node => node.attrs && node.attrs.class === 'a2-walk-switcher');
const grid = section.children.find(node => node.attrs && node.attrs.class === 'a2-walk-grid');
assert.equal(switcher.children.length, 4);
assert.deepEqual(grid.children.map(panel => panel.hidden), [false, true, true, true]);
assert(grid.children.every(panel => panel.children.some(child => child.tag === 'details')));
switcher.children[3].attrs.onclick();
assert.deepEqual(grid.children.map(panel => panel.hidden), [true, true, true, false]);
assert.deepEqual(switcher.children.map(button => button.attrs['aria-pressed']), ['false', 'false', 'false', 'true']);
assert.equal(switcher.children[3].attrs['aria-controls'], grid.children[3].id);
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
    css = (ROOT / "docs/assets/css/learn.css").read_text()
    assert '.a2-learn-pathway .a2-walk-grid > article[hidden] { display: none; }' in css
    assert 'repeat(4, minmax(0, 1fr))' not in css


def test_dark_mode_learn_token_palette_has_normal_text_contrast():
    css = (ROOT / "docs/assets/css/learn.css").read_text()
    tokens = re.findall(r'\[data-md-color-scheme="slate"\] \.a2-learn-app \.a2-k-\w+ \{ --a2-k: (#[0-9a-f]{6}); \}', css)
    assert len(tokens) == 6
    tokens += re.findall(r'\.a2-x-keyword \{ color: (#[0-9a-f]{6}); \}', css)
    assert len(tokens) == 7

    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                  for channel in channels]
        return sum(weight * channel for weight, channel in zip((.2126, .7152, .0722), linear))

    for color in tokens:
        assert (luminance(color) + .05) / (luminance("#40444c") + .05) >= 4.5


def test_checks_separate_agents_from_judge_and_certificate_is_not_real():
    checks = json.loads((DATA / "checks.json").read_text())
    assert len(checks["agents"]) == 2
    assert len({agent["probe"] for agent in checks["agents"]}) == 2
    assert all("card" not in agent["reading"].lower() for agent in checks["agents"])
    assert "full state" in (JS / "learn-checks.js").read_text()
    assert "NOT a verified artifact" in checks["scope"]
    assert checks["definition"] != checks["edited"]
    assert [item["method"] for item in checks["evidence"]] == [
        "Exhaustive", "Bounded", "Seeded sample"]
    assert 'atoms2/data.js' in (ROOT / 'docs/learn/checks.md').read_text()


def test_no_legacy_player_or_corrupted_legacy_export():
    assert not (ROOT / "docs/assets/js/learn.js").exists()
    assert not (ROOT / "tools/docs_learn.py").exists()
    assert not (ROOT / "docs/assets/data/learn.json").exists()
    for path in (DATA / "grammar.json", DATA / "checks.json", JS / "learn-kinds.js", JS / "learn-checks.js"):
        text = path.read_text()
        assert not re.search(r"[⟨⟩⟦⟧⦅⦆ℤℚ♠♦○◉◆◇■★▲♣⊙⁺⁻—–]", text)


def test_design_sources_do_not_expose_internal_paths():
    for name in ("grammar", "checks"):
        data = json.loads((DATA / f"{name}.json").read_text())
        sources = [data["source"]]
        if "trace" in data:
            sources.append(data["trace"]["source"])
        assert all(source.startswith("Design record: ") for source in sources)
        assert all(not re.search(r"scratchpad|/tmp/|cx_wt", source) for source in sources)


def test_six_kind_law_and_bridge_are_executable_but_grammar_designs_are_not():
    for name in ("kinds", "checks"):
        page = (ROOT / f"docs/learn/{name}.md").read_text()
        intro = page.split('<div class="a2-learn-app"', 1)[0]
        assert "core" in intro and "bridge" in intro and "law" in intro
        assert "not yet executable" not in intro
        assert "currently executes four kinds" not in intro

    grammar = json.loads((DATA / "grammar.json").read_text())
    for card in grammar["cards"]:
        if card["kind"] in ("law", "bridge"):
            assert "core can" in card["effect"]
            assert "No grammar-world" in card["effect"]
    script = (JS / "learn-kinds.js").read_text()
    assert 'card.kind === "observation"' in script
    assert "read_parse_count" not in script
    assert "The postfix bridge below remains a design" in script
    assert "The grammar core runs " in script
    assert 'A2.runBadge(observation, artifact)' in script
    assert "core checks new members of all six kinds" in script


def test_detailed_tree_matches_word_and_postfix_evaluation():
    grammar = json.loads((DATA / "grammar.json").read_text())
    tree = grammar["detailed_tree"]
    assert tree["tree"].startswith('ExprTree<"mul",')
    assert "".join(char for char in tree["grouping"] if char not in "()") == grammar["expression"]
    assert eval(compile(ast.parse(tree["grouping"], mode="eval"), "<grammar fixture>", "eval"),
                {"__builtins__": {}}, {}) == int(tree["value"])
    stack = []
    for token in (value.strip('"') for value in tree["postfix"][5:-1].split(",")):
        if token == "2":
            stack.append(2)
        else:
            right, left = stack.pop(), stack.pop()
            stack.append(left + right if token == "+" else left * right)
    assert stack == [int(tree["value"])]


@requires_node
def test_both_learn_pages_render_scoped_law_and_bridge():
    for name in ("kinds", "checks"):
        assert "A2.learnEvidence.render(walk, host.dataset.walk)" in (JS / f"learn-{name}.js").read_text()
    script = (JS / "learn-evidence.js").read_text()
    assert "one replayed rewrite" in script
    assert "commuting diagram" in script
    assert "A2.scopedBadge(item.evidence" in script
    assert "core_digest: record.core_digest" in script
    node_test = r"""
const assert = require('node:assert/strict');
global.window = global;
global.A2 = {
  expr: text => text,
  badge: (status, options) => ({status, options}),
  hasRecordedScope: evidence => !!(evidence && evidence.scope && evidence.scope.checked && evidence.scope.checked !== 'unrecorded'),
  scopedBadge: (evidence, label, artifact) => ({status:evidence.method, label, artifact}),
  el: (tag, attrs, contents) => ({tag, attrs, contents})
};
require('./docs/assets/js/atoms2/learn-evidence.js');
const walk = require('./docs/assets/data/atoms2/walk.json');
const panel = A2.learnEvidence.render(walk, '../../assets/data/atoms2/walk.json');
assert.equal(panel.tag, 'section');
const cards = panel.contents[2].contents;
assert.equal(cards.length, 2);
assert.deepEqual(cards.map(card => card.contents[0].status), ['bounded', 'bounded']);
assert.equal(cards[0].contents[0].artifact.content_hash, walk.law_and_bridge.law.evidence.content_hash);
assert.equal(cards[1].contents[0].artifact.content_hash, walk.law_and_bridge.bridge.evidence.content_hash);
assert(cards[0].contents[3].contents.includes('64 inputs'));
assert(cards[1].contents[3].contents.includes('16 inputs'));
assert(cards[0].contents.at(-1).contents.includes('designed rewrite'));
assert.equal(cards[0].contents[1].contents, 'Law: one replayed rewrite');
assert.equal(cards[1].contents[1].contents, 'Bridge: one commuting diagram');
"""
    subprocess.run(["node", "-e", node_test], cwd=ROOT, check=True)


def test_design_declarations_use_code_not_explanatory_prose():
    from opulse.atoms.notation import parse_definition

    grammar = json.loads((DATA / "grammar.json").read_text())
    for card in grammar["cards"]:
        assert card["definition"].startswith({
            "object": "obj ", "operation": "op ", "combinator": "comb ",
            "observation": "obs ", "law": "law ", "bridge": "bridge ",
        }[card["kind"]])
        assert re.search(r" L\d+$", card["definition"])
        assert parse_definition(card["definition"]).kind == card["kind"]
        assert not re.search(r"finished, legal|memoized recursion on substrings|postfix traversal|for unparenthesized binary", card["definition"])
    assert parse_definition(grammar["template"]["definition"]).kind == "template"
    assert all(re.fullmatch(r"obj \w+ = Quot\[.+\] L\d+", item["definition"])
               for item in grammar["template"]["instances"])
    assert all(parse_definition(item["definition"]).kind == "object"
               for item in grammar["template"]["instances"])


@requires_node
def test_hash_binding_waits_for_original_and_ignores_stale_completions():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
const digests = [];
Object.defineProperty(global, 'crypto', {configurable: true, value: {subtle: {digest(algorithm, bytes) {
  assert.equal(algorithm, 'SHA-256');
  return new Promise((resolve, reject) => digests.push({text: new TextDecoder().decode(bytes), resolve, reject}));
}}}});
require('./docs/assets/js/atoms2/learn-checks.js');
const results = [];
const errors = [];
const compare = A2.learnChecks.definitionHashState('original', (original, current) => {
  results.push({original, current});
}, error => errors.push(error));
const initial = compare('original');
const edit = compare('edited');
assert.deepEqual(digests.map(item => item.text), ['original', 'original', 'edited']);
function settle(entry, byte) { entry.resolve(Uint8Array.from({length: 32}, () => byte).buffer); }
settle(digests[2], 2);
settle(digests[1], 1);
Promise.resolve().then(() => {
  assert.deepEqual(results, []);
  settle(digests[0], 1);
  return Promise.all([initial, edit]);
}).then(() => {
  assert.equal(results.length, 1);
  assert.equal(results[0].original, '01'.repeat(32));
  assert.equal(results[0].current, '02'.repeat(32));
  assert(!A2.learnChecks.certificateApplies(results[0].original, results[0].current));
  const restore = compare('original');
  settle(digests[3], 1);
  return restore;
}).then(() => {
  assert.equal(results.length, 2);
  assert(A2.learnChecks.certificateApplies(results[1].original, results[1].current));
  assert.deepEqual(errors, []);
}).catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_status_badges_precede_headings_and_stack_above_hero_title():
    css = (ROOT / "docs/assets/css/learn.css").read_text()
    assert re.search(r"\.a2-learn-app \.a2-badge\s*\{[^}]*display: table", css)
    assert re.search(r"\.a2-learn-app \.a2-learn-hero strong\s*\{[^}]*display: block", css)
    for name in ("learn-kinds", "learn-checks"):
        script = (JS / f"{name}.js").read_text()
        assert not re.search(r'el\("h[23]",\s*\{\},\s*"[^"]+"\),\s*A2\.badge', script)


@requires_node
def test_exact_browser_count_lookup_and_hash_binding():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
global.crypto = require('node:crypto').webcrypto;
require('./docs/assets/js/atoms2/kit.js');
require('./docs/assets/js/atoms2/learn-kinds.js');
require('./docs/assets/js/atoms2/learn-checks.js');
require('./docs/assets/js/atoms2/data.js');
assert.equal(A2.learnKinds.countTrees(1), 1n);
assert.equal(A2.learnKinds.countTrees(8), 429n);
assert.equal(A2.learnKinds.countTrees(9), 1430n);
assert.throws(() => A2.learnKinds.countTrees(0), RangeError);
assert.throws(() => A2.learnKinds.countTrees(49), RangeError);
assert.equal(A2.learnChecks.traceApply(true, 6).outcome, 'Bottom(guard)');
assert.equal(A2.learnChecks.traceApply(true, 6).steps, 4);
assert.equal(A2.learnChecks.traceApply(false, 6).outcome, 'Ok(Doc<12:/a=Q,/l=R>)');
assert.equal(A2.learnChecks.traceApply(false, 6).steps, 6);
assert.equal(A2.learnChecks.traceApply(true, 3).outcome, 'Unknown(fuel)');
assert.equal(A2.learnChecks.traceApply(true, 3).steps, 3);
assert.equal(A2.learnChecks.traceApply(false, 0).steps, 0);
assert.throws(() => A2.learnChecks.traceApply(true, -1), RangeError);
const fixpoint = A2.learnChecks.fixpointBreakdown(A2.kernelData);
assert.match(fixpoint.outcome, /^Ok\(List<"A", "B"/);
assert.equal(fixpoint.total, 19);
assert.deepEqual(fixpoint.children.map(child => child.steps), [19]);
assert.deepEqual(fixpoint.expanded.map(child => child.steps), [1,1,1,1,15]);
assert.equal(A2.learnChecks.fixpointBreakdown(null), null);
(async () => {
  const original = await A2.learnChecks.hashDefinition('obs ?lamps{view} = all(view)');
  const again = await A2.learnChecks.hashDefinition('obs ?lamps{view} = all(view)');
  const changed = await A2.learnChecks.hashDefinition('obs ?lamps{view} = last(view)');
  assert.equal(original, again);
  assert.match(original, /^[a-f0-9]{64}$/);
  assert.notEqual(original, changed);
  assert(A2.learnChecks.certificateApplies(original, again));
  assert(!A2.learnChecks.certificateApplies(original, changed));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_checks_page_names_the_recorded_law_and_bridge_scopes():
    walk = json.loads((DATA / "walk.json").read_text())["law_and_bridge"]
    law_size = walk["law"]["evidence"]["scope"]["size"]
    bridge_size = walk["bridge"]["evidence"]["scope"]["size"]
    assert walk["law"]["evidence"]["method"] == walk["bridge"]["evidence"]["method"] == "bounded"
    page = (ROOT / "docs/learn/checks.md").read_text()
    sentence = (f"The law records {law_size} checked input pairs and the bridge {bridge_size} "
                "checked inputs; their badges describe those bounded scopes.")
    assert page.count(sentence) == 2
    noscript = page.split("<noscript>", 1)[1].split("</noscript>", 1)[0]
    assert sentence in noscript
    assert "does not record checked inputs" not in page
    assert "no check badges" not in page
    assert "checked-input scopes are not recorded" not in page
