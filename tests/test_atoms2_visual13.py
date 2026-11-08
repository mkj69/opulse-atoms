"""Regressions for the ten round-13 visual findings."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "docs/assets/css"
JS = ROOT / "docs/assets/js"


def source(path: Path) -> str:
    return path.read_text()


def rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return match.group(1)


def test_catalogue_shows_all_tag_fields_without_expanding() -> None:
    catalog = source(JS / "worlds/catalog-ui.js")
    assert 'var full = A2.worlds.fieldChips(world);' in catalog
    assert 'cardTags(world, star).forEach(function (part) { card.appendChild(part); });' in catalog
    assert '"All world tags"' not in catalog


@pytest.mark.skipif(not shutil.which("node"), reason="Node is not installed")
def test_multivalue_tag_fields_render_individual_wrapping_chips() -> None:
    script = """
      const A2 = require(process.argv[1] + '/docs/assets/js/atoms2/kit.js');
      globalThis.document = {readyState:'loading', addEventListener() {}, querySelectorAll:() => [],
        createElement(tag) { return {tag, children:[],
        appendChild(child) {this.children.push(child)}, setAttribute() {}, textContent:''}; }};
      require(process.argv[1] + '/docs/assets/js/atoms2/tower.js');
      const chips = A2.worlds.fieldChips({tags:{domain:'math', modalities:['text','image'],
        reasoning:['search','planning']}, open_kinds:['object','operation']});
      console.log(JSON.stringify(chips.children.map(child => child.textContent)));
    """
    result = subprocess.run(["node", "-e", script, str(ROOT)], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ('["domain: math","modalities: text","modalities: image",'
                                     '"open kinds: object","open kinds: operation",'
                                     '"reasoning: search","reasoning: planning"]')
    assert "flex-wrap: wrap" in rule(source(CSS / "worlds-v2.css"), "\n.w2-tags")


def test_play_route_kind_names_are_badges_not_invented_atoms() -> None:
    ladders = source(JS / "atoms2/ladders.js")
    assert "control.prepend(root.A2.kindBadge(task.kind))" in ladders
    assert "A2.token(task.kind" not in ladders


def test_law_double_bar_is_border_not_source_prefix() -> None:
    styles = source(CSS / "atoms2.css")
    assert ".a2-tok.a2-k-law::before" not in styles
    assert "border-top-width: 4px" in styles
    assert "border-style: double" in styles


def test_observation_chip_wraps_full_copyable_expression() -> None:
    styles = source(CSS / "learn.css")
    token = rule(styles, ".a2-learn-app .a2-tok")
    assert "white-space: normal" in token
    assert "overflow-wrap: anywhere" in token
    assert "text-overflow: ellipsis" not in token


def test_trace_outcomes_use_result_style() -> None:
    tower = source(JS / "atoms2/tower.js")
    assert 'class: "a2-v-result w2-trace-outcome"' in tower
    # Notation v3: recorded strings use formulas and structured outcomes use the value renderer.
    assert 'typeof step.outcome === "string" ? A2.expr(step.outcome, { given: given, world: worldName })' in tower
    assert 'A2.value(step.outcome, { world: worldName })' in tower
    assert "color: var(--op-cyan)" in rule(source(CSS / "atoms2.css"), ".a2-v-result")


def test_home_and_worlds_selection_use_focus_not_result_color() -> None:
    shared = source(CSS / "atoms2.css")
    roads = source(CSS / "atoms2-roads.css")
    assert "var(--op-amber)" in rule(shared, '.a2-btn[aria-pressed="true"]')
    assert "var(--op-cyan)" not in rule(shared, '.a2-btn[aria-pressed="true"]')
    assert "var(--op-amber" in rule(roads, ".roads-layers li.is-selected")


def test_play_reveals_are_neutral_while_pinned_result_remains_cyan() -> None:
    css = source(CSS / "atoms2-boundary.css")
    for selector in (".a2-boundary-caption", ".a2-boundary-row.is-new"):
        assert "var(--op-cyan)" not in rule(css, selector)
        assert "var(--a2-new-bg)" not in rule(css, selector)
    assert "var(--a2-panel)" in rule(css, "@keyframes a2-boundary-reveal")
    assert "color: var(--op-cyan)" in rule(css, ".a2-boundary-pinned .a2-v")


def test_layer_superscripts_are_not_repeated_next_to_chips() -> None:
    learn = source(JS / "atoms2/learn-kinds.js")
    tower = source(JS / "atoms2/tower.js")
    assert 'A2.KIND6_META[card.kind].word)' in learn
    assert 'word + " / L"' not in learn
    assert '" / COMPUTED L"' not in tower
    assert '" / DECLARED "' in tower


def test_law_is_visually_distinct_from_amber_in_both_themes() -> None:
    shared = source(CSS / "atoms2.css")
    learn = source(CSS / "learn.css")
    assert "--a2-law: #59625b" in shared
    assert "--a2-law: #b4c1b9" in shared
    assert "--a2-k: #b4c1b9" in learn
