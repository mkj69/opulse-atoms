"""Accessibility regression checks for the published MkDocs build and token palette."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "docs/assets/css/atoms2.css"
JS = ROOT / "docs/assets/js/atoms2"
MKDOCS = shutil.which("mkdocs")
KINDS = ("object", "operation", "combinator", "observation", "law", "bridge")


def luminance(color: str) -> float:
    components = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4
              for component in components]
    return sum(component * weight for component, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(first: str, second: str) -> float:
    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def palette(css: str, theme: str) -> dict[str, str]:
    selector = '[data-md-color-scheme="slate"]' if theme == "dark" else ':root, [data-md-color-scheme="default"]'
    block = css.split(selector + " {", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"(--a2-[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, BeautifulSoup]]:
    destination = tmp_path_factory.mktemp("a11y-site")
    subprocess.run([MKDOCS, "build", "--quiet", "-d", str(destination)], cwd=ROOT, check=True,
                   capture_output=True, text=True)
    return [(str(path.relative_to(destination)), BeautifulSoup(path.read_text(), "html.parser"))
            for path in sorted(destination.rglob("*.html"))]


def accessible_name(element) -> str:
    if element.get("aria-label"):
        return element["aria-label"].strip()
    ids = element.get("aria-labelledby", "").split()
    if ids:
        root = element
        while root.parent is not None:
            root = root.parent
        return " ".join(root.find(id=identifier).get_text(" ", strip=True)
                        for identifier in ids if root.find(id=identifier))
    if element.name == "img":
        return element.get("alt", "").strip()
    return element.get_text(" ", strip=True) or element.get("title", "").strip()


def field_has_name(field, soup: BeautifulSoup) -> bool:
    if field.get("aria-label") or field.get("aria-labelledby") or field.get("title"):
        return True
    if field.find_parent("label"):
        return True
    return bool(field.get("id") and soup.select(f'label[for="{field["id"]}"]'))


def failures(pages: list[tuple[str, BeautifulSoup]]) -> Counter:
    problems: Counter = Counter()
    for path, soup in pages:
        identifiers = [element["id"] for element in soup.select("[id]")]
        if len(identifiers) != len(set(identifiers)):
            problems["duplicate ids"] += len(identifiers) - len(set(identifiers))
        for button in soup.select("button, input[type=button], input[type=submit]"):
            if not accessible_name(button) and not button.get("value"):
                problems["unnamed buttons"] += 1
        for field in soup.select("input, select, textarea"):
            if field.get("type") in ("hidden", "button", "submit") or "md-toggle" in field.get("class", ()):
                continue
            if not field_has_name(field, soup):
                problems["unnamed fields"] += 1
        for image in soup.select("img"):
            if not image.has_attr("alt") and not image.get("aria-label"):
                problems["images without alternatives"] += 1
        for svg in soup.select("svg"):
            if svg.get("aria-hidden") == "true" or svg.get("aria-label") or svg.get("aria-labelledby") or svg.find(["title", "desc"]):
                continue
            if svg.find_parent(class_="md-icon") or svg.find_parent(class_="md-header__button"):
                continue
            named_link = svg.find_parent("a")
            if named_link and accessible_name(named_link):
                continue
            problems["figures without alternatives"] += 1
        for tablist in soup.select('[role="tablist"], [class*="tabs"]'):
            if tablist.get("role") != "tablist" and tablist.select('button[role="tab"]'):
                problems["tab strips without roles"] += 1
            if tablist.get("role") == "tablist" and not tablist.select('[role="tab"]'):
                problems["tablists without tabs"] += 1
    return problems


@pytest.mark.skipif(MKDOCS is None, reason="mkdocs is not installed")
def test_published_pages_have_named_controls_and_figure_alternatives(pages):
    names = {path for path, _ in pages}
    required = {"index.html", "learn/index.html", "learn/kinds/index.html", "learn/checks/index.html",
                "play/index.html", "play/challenge/index.html", "play/legacy/index.html",
                "worlds/index.html", "worlds/legacy/index.html", "research/index.html",
                "build/index.html", "reference/index.html"}
    assert required <= names
    counts = failures(pages)
    assert not counts, f"{len(pages)} built pages: {dict(counts)}"


def test_token_palette_meets_aa_on_both_themes():
    css = CSS.read_text()
    for theme in ("light", "dark"):
        colors = palette(css, theme)
        background = "#ffffff" if theme == "light" else "#0a0f1e"
        for kind in KINDS:
            color = colors[f"--a2-{kind}"]
            outlined = {"object": "#167243", "operation": "#b43b13"}.get(kind, color) if theme == "light" else color
            filled = colors["--a2-chip-ink"]
            assert contrast(outlined, background) >= 4.5, (theme, kind, "outlined")
            assert contrast(color, background) >= 4.5, (theme, kind, "formula glyph")
            assert contrast(color, filled) >= 4.5, (theme, kind, "filled")
        for variable in ("--a2-ink", "--a2-muted", "--a2-ok"):
            assert contrast(colors[variable], background) >= 4.5, (theme, variable)


def test_dynamic_tabs_and_road_controls_have_semantic_regressions():
    definition = (JS / "define.js").read_text()
    challenge = (ROOT / "docs/assets/js/challenge-modes.js").read_text()
    roads = (JS / "roads.js").read_text()
    boundary = (JS / "boundary.js").read_text()
    for source in (definition, challenge):
        assert 'role: "tabpanel"' in source or 'setAttribute("role", "tabpanel")' in source
        assert '"aria-controls"' in source or 'setAttribute("aria-controls"' in source
        assert '"ArrowRight"' in source and '"ArrowLeft"' in source
        assert "tabIndex" in source
    assert 'group.setAttribute("role", "button")' not in roads
    assert 'button.addEventListener("click", () => options.onRoad(id))' in roads
    assert 'button.addEventListener("click", () => options.onNode(id))' in roads
    assert '"Next lifecycle stage"' in definition
    assert "A2.reducedMotion()" in definition
    assert 'if (A2.reducedMotion()) {' in boundary and 'index = index === states.length - 1' in boundary
    assert 'let index = 0;' in roads and 'if (reducedMotion) play.hidden = true;' in roads


def test_contrast_helper_uses_linear_srgb():
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#ffffff", "#ffffff") == pytest.approx(1)
    assert contrast("#1d8a4e", "#000000") > 4.5


def test_palette_helper_reads_exact_theme_block():
    css = CSS.read_text()
    assert palette(css, "light")["--a2-object"] == "#1a7b46"
    assert palette(css, "dark")["--a2-object"] == "#5fd68f"


def test_accessible_name_and_failure_counter_reject_missing_names():
    valid = BeautifulSoup('<button aria-label="Run"></button><span id="name">Pause</span>'
                          '<button aria-labelledby="name"></button><img alt="">'
                          '<svg aria-hidden="true"></svg>', "html.parser")
    assert accessible_name(valid.button) == "Run"
    assert accessible_name(valid.select_one('[aria-labelledby="name"]')) == "Pause"
    assert accessible_name(valid.img) == ""
    labelled = BeautifulSoup('<label>Scope <input type="text"></label>', "html.parser")
    assert field_has_name(labelled.input, labelled)
    unlabeled = BeautifulSoup('<select><option>Unknown</option></select>', "html.parser")
    assert not field_has_name(unlabeled.find("select"), unlabeled)
    assert not failures([("valid.html", valid)])
    invalid = BeautifulSoup('<button></button><input type="text"><img src="diagram.svg"><svg></svg><div id="x"></div>'
                            '<div id="x"></div><div role="tablist"></div>', "html.parser")
    assert failures([("invalid.html", invalid)]) == Counter({
        "unnamed buttons": 1, "unnamed fields": 1, "images without alternatives": 1, "figures without alternatives": 1,
        "duplicate ids": 1, "tablists without tabs": 1,
    })
