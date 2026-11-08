"""Regression coverage for the fifth published UI sweep."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_spec_tables_have_keyboard_scroll_and_a_visible_cue():
    page = (ROOT / "docs/reference/spec.md").read_text()
    assert "../../assets/js/atoms2/spec-tables.js" in page
    assert "../../assets/css/atoms2-spec-tables.css" in page
    script = r"""
const assert = require('node:assert/strict');
const { enhance } = require('./docs/assets/js/atoms2/spec-tables.js');
const classes = new Set();
const previous = {children: [], insertBefore(child, sibling) {
  this.children.splice(this.children.indexOf(sibling), 0, child);
}};
const table = {tagName: 'table', closest: () => classes.has('a2-spec-table-scroll') ? wrapper : null,
  parentNode: previous};
previous.children.push(table);
let wrapper;
global.document = {createElement: tag => tag === 'div' ? (wrapper = {
  tagName: tag, classList: {add: name => classes.add(name)}, attrs: {},
  setAttribute(key, value) { this.attrs[key] = value; },
  appendChild(child) {previous.children.splice(previous.children.indexOf(child), 1); child.parentNode = this;}
}) : {tagName: tag}};
const container = {querySelectorAll: () => [table]};
enhance(container);
enhance(container);
assert.equal(previous.children.length, 2);
assert.equal(previous.children[0].tagName, 'p');
assert.match(previous.children[0].textContent, /arrow keys/);
assert.equal(wrapper.attrs.tabindex, '0');
assert.equal(wrapper.attrs.role, 'region');
assert.equal(wrapper.attrs['aria-describedby'], previous.children[0].id);
"""
    subprocess.run([NODE, "-e", script], cwd=ROOT, check=True)
    css = (ROOT / "docs/assets/css/atoms2-spec-tables.css").read_text()
    assert "overflow-x: auto" in css and ":focus-visible" in css


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_law_and_bridge_have_scope_for_the_shared_badge_helper():
    script = r"""
const assert = require('node:assert/strict');
const A2 = require('./docs/assets/js/atoms2/kit.js');
const walk = require('./docs/assets/data/atoms2/walk.json');
const {law, bridge} = walk.law_and_bridge;
for (const [item, size] of [[law, 64], [bridge, 16]]) {
  assert.equal(A2.hasRecordedScope(item.evidence), true);
  assert.equal(A2.evidenceRecord({evidence: item.evidence}).size, size);
  assert.equal(A2.evidenceRecord({evidence: item.evidence}).artifact.contentHash,
    item.evidence.content_hash);
  assert.equal(item.evidence.scope.checked.size, size);
  assert.match(item.evidence.scope.checked.sha256, /^[0-9a-f]{64}$/);
  assert.match(item.evidence.checker, /^opulse[.]atoms[.]/);
}
"""
    subprocess.run([NODE, "-e", script], cwd=ROOT, check=True)


def test_world_cards_show_result_first_and_collapse_long_source_and_inputs():
    tower = (ROOT / "docs/assets/js/atoms2/tower.js").read_text()
    assert tower.index('"First recorded result"') < tower.index('"Inspect full ASCII source"')
    assert tower.index('"Recorded result and scope"') < tower.index('"Call and recorded inputs"')
    assert 'text("summary", "Inspect full ASCII source")' in tower
    # Notation v3: the design disclosure identifies the visible source format.
    assert 'text("summary", "Inspect full design text (not notation v3 source)")' in tower
    # Notation v3: long-value disclosure uses the current 320-character cutoff.
    assert 'value.length <= 320' in tower
    assert 'matchMedia("(max-width: 600px)").matches' in tower
    assert 'class: "w2-trace"' in tower
    catalog = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    # Notation v3: the inputs render one value each, still after the recorded outcome.
    assert catalog.index('exported.appendChild(node("p", "Recorded outcome"') < catalog.index(
        'exported.appendChild(typeof matchMedia')
    assert '"Inspect recorded inputs"), inputs]) : inputs);' in catalog


def test_worlds_display_export_empty_state_only_without_showcases():
    catalog = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert '"No published showcase"' in catalog
    assert 'href: source, text: "Inspect the world export"' in catalog
    assert 'if (world.design) showcase.appendChild(node("p", "Design modalities:' in catalog
    assert 'var hasShowcase = Array.isArray(world.showcase) && world.showcase.length > 0;' in catalog
    assert 'if (hasShowcase) publishedShowcases(showcase, world, source);' in catalog


def test_first_tower_intro_is_narrow_and_has_shorter_sentences():
    css = (ROOT / "docs/assets/css/atoms2-first-tower.css").read_text()
    assert ".first-tower .first-tower-intro { max-width: 72ch;" in css
    for name in ("docs/index.md", "docs/learn/index.md"):
        text = (ROOT / name).read_text()
        intro = text.split('<p class="first-tower-intro">', 1)[1].split("</p>", 1)[0]
        assert "It does not call" in intro
        assert "probe; it does not call" not in intro
