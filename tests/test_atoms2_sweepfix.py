"""Regressions for the world atlas and prose sweep."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from bs4 import BeautifulSoup
from mkdocs.config import load_config

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
CSS = ROOT / "docs/assets/css"


def test_published_front_matter_is_valid_yaml():
    config = load_config(str(ROOT / "mkdocs.yml"))
    pages = []
    for page in (ROOT / "docs").rglob("*.md"):
        if config["exclude_docs"].match_file(page.relative_to(ROOT / "docs").as_posix()):
            continue
        pages.append(page)
        source = page.read_text(encoding="utf-8")
        if not source.startswith("---\n"):
            continue
        opening, separator, _ = source[4:].partition("\n---\n")
        assert separator, page
        assert isinstance(yaml.safe_load(opening), dict), page
    assert len(pages) > 20
    action = yaml.safe_load((ROOT / "docs/worlds/action/index.md").read_text().split("\n---\n", 1)[0][4:])
    assert action["title"] == "Robot probes: corridor export and maze design"


def test_published_pages_do_not_render_front_matter(tmp_path):
    subprocess.run([sys.executable, "-m", "mkdocs", "build", "-q", "-f", str(ROOT / "mkdocs.yml"),
                    "-d", str(tmp_path / "site")], cwd=ROOT, check=True, capture_output=True, text=True)
    pages = list((tmp_path / "site").rglob("*.html"))
    assert len(pages) > 20
    for page in pages:
        soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
        content = soup.select_one(".md-content__inner")
        if content:
            assert not re.search(r"(?m)^\s*hide:\s*$", content.get_text("\n")), page
    action = BeautifulSoup((tmp_path / "site/worlds/action/index.html").read_text(), "html.parser")
    assert action.title.get_text().startswith("Robot probes: corridor export and maze design")
    breadcrumb = action.select_one(".op-breadcrumb").get_text(" ", strip=True)
    assert "Robot probes: corridor export and maze design" in breadcrumb
    assert "Index" not in breadcrumb


def test_prose_measure_is_scoped_to_paragraphs():
    roads = (CSS / "atoms2-roads.css").read_text()
    research = (CSS / "atoms2-research.css").read_text()
    worlds = (CSS / "worlds-v2.css").read_text()
    assert re.search(r"\.md-typeset \.first-tower \.first-tower-intro\s*\{\s*max-width: min\(72ch, 680px\);", roads)
    assert re.search(r"\.md-main__inner:not\(\[data-op-layout=\"app\"\]\) > \.md-content > \.md-content__inner\.md-typeset > p,\s*\.first-tower > p, \.roads-card > p\s*\{\s*max-width: min\(72ch, 680px\);", roads)
    assert re.search(r"\.ar-page > p, \.ar-page \.ar-callout > p\s*\{\s*max-width: min\(72ch, 600px\);", research)
    assert re.search(r"\.w2-hero > p:not\(\.w2-eyebrow\), \.w2-section > p\s*\{\s*max-width: 72ch;", worlds)
    assert ".first-tower .first-tower-intro { max-width: 72ch;" in (CSS / "atoms2-first-tower.css").read_text()


@pytest.mark.parametrize("world_name", ["action", "integer", "roads", "computer"])
def test_core_parser_note_distinguishes_design_from_recorded_tower(world_name):
    catalog = (ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    world = json.loads((ROOT / "docs/assets/data/worlds_v2" / (world_name + ".json")).read_text())
    assert len(world["story"]) >= 11
    assert '"Core parser: " + parsed + " of " + (world.story || []).length +' in catalog
    assert '" design declarations parse as ASCII source"' in catalog
    assert '"learn/checks/#world-export-limitations"' in catalog
    assert "## World export limitations" in (ROOT / "docs/learn/checks.md").read_text()
    assert 'class: "w2-parse-note"' in catalog


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_mobile_card_tags_expand_and_desktop_retains_full_set():
    script = r"""
      const root = process.argv[1];
      const A2 = require(root + '/docs/assets/js/atoms2/kit.js');
      A2.el = (tag, attrs = {}) => {
        const node = {tag, textContent: attrs.text || '', children: [], attrs: {...attrs}, hidden: false,
          classList: {add(value) {node.attrs.class = (node.attrs.class || '') + ' ' + value}},
          appendChild(child) {this.children.push(child)},
          setAttribute(key, value) {this.attrs[key] = value}, getAttribute(key) {return this.attrs[key]},
          addEventListener(key, handler) {this[key] = handler}};
        return node;
      };
      require(root + '/docs/assets/js/atoms2/tower.js');
      const {cardTags} = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const world = {world:'sample', tags:{domain:'math', modalities:['text','image'], star_kind:'law',
        reasoning:['proof','search'], visibility:'public'}, open_kinds:['object','law']};
      const [summary, full, button] = cardTags(world, 'law');
      const before = {summary: summary.children.map(child => child.textContent),
        full: full.children.map(child => child.textContent), control:button.attrs['aria-controls'],
        expanded:button.attrs['aria-expanded'], label:button.textContent};
      button.click();
      const opened = {expanded:button.attrs['aria-expanded'], label:button.textContent,
        full:full.attrs['data-expanded'], summaryHidden:summary.hidden};
      button.click();
      console.log(JSON.stringify({before, opened, closed:button.attrs['aria-expanded']}));
    """
    output = subprocess.run([NODE, "-e", script, str(ROOT)],
                            capture_output=True, text=True, check=True)
    rendered = json.loads(output.stdout)
    before = rendered["before"]
    assert before["summary"] == ["domain: math", "modalities: text", "modalities: image", "star kind: law"]
    assert len(before["full"]) > len(before["summary"])
    assert "reasoning: proof" in before["full"]
    assert before["label"] == f"Show all {len(before['full'])} tags"
    assert before["control"] == "w2-tags-sample" and before["expanded"] == "false"
    assert rendered["opened"] == {"expanded": "true", "label": "Show fewer tags", "full": "true", "summaryHidden": True}
    assert rendered["closed"] == "false"
    css = (CSS / "worlds-v2.css").read_text()
    mobile = css.split("@media (max-width: 600px) {\n  .w2-card .w2-card-tags-summary", 1)[1]
    assert '.w2-card .w2-card-all-tags { display: none; }' in mobile
    assert '.w2-card .w2-card-all-tags[data-expanded="true"] { display: flex; }' in mobile
    assert ".w2-card .w2-card-tags-summary, .w2-card .w2-card-tags-toggle { display: none; }" in css
