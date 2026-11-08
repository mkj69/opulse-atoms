"""Gate published copy, loaded assets, and shipped English-site scripts."""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from ui_ascii_mirror import assert_ascii_legacy_mirror

from opulse.notation3 import ALLOWED_DISPLAY_CHARS
from tools.site_gates.n3_roundtrip import PROSE_EXCEPTIONS

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SITE_CHARS = ALLOWED_DISPLAY_CHARS | PROSE_EXCEPTIONS
FORBIDDEN = re.compile("[^\\x00-\\x7f" + re.escape("".join(sorted(ALLOWED_SITE_CHARS))) + "]|scratchpad|/tmp/|cx_wt", re.IGNORECASE)
SCRIPT_ASSETS = re.compile(r"(?:fetch|import)\s*\(\s*['\"]([^'\"]+\.(?:js|json)(?:\?[^'\"]*)?)['\"]")
CSS_IMPORT = re.compile(r"@import\s+(?:url\(\s*)?(?:['\"]([^'\"]+\.css(?:\?[^'\"]*)?)['\"]|([^\s)'\"]+\.css(?:\?[^\s)'\"]*)?))\s*\)?", re.IGNORECASE)
CSS_CONTENT = re.compile(r"\bcontent\s*:\s*((?:\\.|[^;{}])*)", re.IGNORECASE)
CSS_ESCAPE = re.compile(r"\\([0-9a-fA-F]{1,6})(?:\s)?|\\(.)", re.DOTALL)
JS_UNICODE_ESCAPE = re.compile(r"\\(?:u([dD][89abAB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}|[0-9a-fA-F]{4})|u\{([0-9a-fA-F]{1,6})\}|x([0-9a-fA-F]{2}))")


def escaped_character(match):
    """Decode one JS/JSON escape; a UTF-16 surrogate pair is one astral character."""
    value = next(group for group in match.groups() if group is not None)
    if "\\u" in value:
        high, low = (int(part, 16) for part in value.split("\\u"))
        return chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00))
    return chr(int(value, 16))


# Characters the pre-v3 gate rejected that notation v3 does not allow.
VENDOR_CSS_REJECTED = frozenset("⟦⟧⦅⦆◉⊙⁺⁻—–←↔↟≈≠≤≥÷▦") - ALLOWED_DISPLAY_CHARS
LEGACY_REJECTED = frozenset("⟦⟧⦅⦆⊙⁺⁻⊕⊗⊝⊞⊟⊠∧∨⊻⊼⊽¬∃∄∩∪⊂⊃∋∉⊎⊓⊔∑∏∐∫∮√∛∜∞∂∇∆←↑↔↕↖↗↘↙⇐⇑⇓⇔↩↪↺↻⇄⇆⟲⇉")


class PublishedPage(HTMLParser):
    VOID: ClassVar[set[str]] = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.visible = []
        self.assets = []
        self.inline_scripts = []
        self.inline_json = []
        self.in_script = False
        self.in_json = False

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        parent_hidden = self.hidden[-1] if self.hidden else False
        if tag not in self.VOID:
            self.hidden.append(parent_hidden or tag in {"head", "script", "style", "template", "svg"}
                               or "hidden" in attributes or attributes.get("aria-hidden") == "true")
        if tag == "script" and attributes.get("src"):
            self.assets.append(attributes["src"])
        if tag == "script" and not attributes.get("src") and attributes.get("type", "") not in {"application/json", "application/ld+json"}:
            self.in_script = True
        if tag == "script" and attributes.get("type") == "application/json":
            self.in_json = True
        if tag == "link" and "stylesheet" in attributes.get("rel", "").split() and attributes.get("href"):
            self.assets.append(attributes["href"])
        if tag in {"img", "iframe", "object"} and attributes.get("src", "").endswith(".json"):
            self.assets.append(attributes["src"])

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
            self.in_json = False
        if self.hidden:
            self.hidden.pop()

    def handle_data(self, data):
        if self.in_script:
            self.inline_scripts.append((data, *self.getpos()))
        if self.in_json:
            self.inline_json.append((data, *self.getpos()))
        if self.hidden and not self.hidden[-1]:
            self.visible.append((data, *self.getpos()))


def findings(text, filename, line=1, column=1, *, bilingual=False):
    from test_prepub_cleanup import CJK

    previous = 0
    for match in FORBIDDEN.finditer(text):
        between = text[previous:match.start()]
        lines = between.count("\n")
        if lines:
            line += lines
            column = len(between.rsplit("\n", 1)[-1]) + 1
        else:
            column += len(between)
        if not bilingual or not CJK.fullmatch(match.group()):
            yield f"{filename}:{line}:{column}: {match.group()!r}"
        column += len(match.group())
        previous = match.end()


def javascript_literals(source):
    """Yield source offsets and contents of quoted JS text, skipping comments and code."""
    position = 0
    while position < len(source):
        if source.startswith("//", position):
            end = source.find("\n", position + 2)
            position = len(source) if end < 0 else end
        elif source.startswith("/*", position):
            end = source.find("*/", position + 2)
            position = len(source) if end < 0 else end + 2
        elif source[position] in "'\"`":
            quote = source[position]
            start = position + 1
            position = start
            while position < len(source):
                if source[position] == "\\":
                    position += 2
                elif source[position] == quote:
                    break
                else:
                    position += 1
            yield start, source[start:position]
            position += 1
        else:
            position += 1


def javascript_findings(source, filename, *, bilingual=False):
    from test_prepub_cleanup import CJK

    for offset, text in javascript_literals(source):
        prefix = source[:offset]
        yield from findings(text, filename, prefix.count("\n") + 1,
                            len(prefix.rsplit("\n", 1)[-1]) + 1, bilingual=bilingual)
        for match in JS_UNICODE_ESCAPE.finditer(text):
            character = escaped_character(match)
            if FORBIDDEN.search(character) and not (bilingual and CJK.fullmatch(character)):
                escaped_prefix = source[:offset + match.start()]
                current_line = escaped_prefix.count("\n") + 1
                current_column = len(escaped_prefix.rsplit("\n", 1)[-1]) + 1
                yield f"{filename}:{current_line}:{current_column}: {character!r} (escaped)"


def css_findings(source, filename):
    source = css_without_comments(source)
    for declaration in CSS_CONTENT.finditer(source):
        value = declaration.group(1)
        for match in re.finditer(r"(['\"])((?:\\.|(?!\1).)*?)\1", value, re.DOTALL):
            text = match.group(2)
            prefix = source[:declaration.start(1) + match.start(2)]
            line, column = prefix.count("\n") + 1, len(prefix.rsplit("\n", 1)[-1]) + 1
            yield from findings(text, filename, line, column)
            for escape in CSS_ESCAPE.finditer(text):
                character = chr(int(escape.group(1), 16)) if escape.group(1) else escape.group(2)
                if FORBIDDEN.search(character):
                    yield f"{filename}:{line + text[:escape.start()].count(chr(10))}:{column}: {character!r} (escaped)"


def css_without_comments(source):
    return re.sub(r"/\*.*?\*/", lambda match: re.sub(r"[^\n]", " ", match.group()), source, flags=re.DOTALL)


def first_party_asset(site, page, url):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path.endswith((".js", ".json", ".css")):
        return None
    target = (site / parsed.path.lstrip("/")) if parsed.path.startswith("/") else (page.parent / unquote(parsed.path))
    target = target.resolve()
    return target if target.is_relative_to(site.resolve()) and target.is_file() else None


@pytest.fixture(scope="module")
def published_site(tmp_path_factory):
    target = tmp_path_factory.mktemp("published-ascii")
    subprocess.run([sys.executable, "-m", "mkdocs", "build", "--clean", "--site-dir", str(target)],
                   cwd=ROOT, check=True, capture_output=True, text=True, timeout=600)
    return target


def test_every_built_page_internal_link_resolves(published_site):
    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.targets = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "a" and attributes.get("href"):
                self.targets.append(attributes["href"])

    missing = []
    for page in published_site.rglob("*.html"):
        links = Links()
        links.feed(page.read_text(encoding="utf-8"))
        origin = "https://site.test/opulse-atoms/" + page.relative_to(published_site).as_posix()
        for href in links.targets:
            target = urlsplit(urljoin(origin, href))
            if target.netloc != "site.test" or not target.path.startswith("/opulse-atoms/"):
                continue
            path = unquote(target.path.removeprefix("/opulse-atoms/"))
            destination = published_site / path
            if not (destination / "index.html" if path.endswith("/") or not destination.suffix else destination).is_file():
                missing.append((page.relative_to(published_site).as_posix(), href))
    assert not missing, missing[:30]


def scan_site(site):
    problems = []
    assets = set()
    ignored = {"rebuild_pages": 0, "redirects": 0}
    for page in sorted(site.rglob("*.html")):
        relative = page.relative_to(site).as_posix()
        html = page.read_text(encoding="utf-8")
        parsed = PublishedPage()
        parsed.feed(html)
        for url in parsed.assets:
            asset = first_party_asset(site, page, url)
            if asset:
                assets.add(asset)
        for text, _, _ in parsed.inline_scripts:
            for url in SCRIPT_ASSETS.findall(text):
                asset = first_party_asset(site, page, url)
                if asset:
                    assets.add(asset)
        for text, line, column in parsed.visible:
            problems.extend(findings(text, relative, line, column))
        for text, line, column in parsed.inline_scripts:
            prefix = "\n" * (line - 1) + " " * (column - 1)
            problems.extend(javascript_findings(prefix + text, relative))
        for text, line, column in parsed.inline_json:
            problems.extend(findings(text, relative, line, column))
    assets.update((site / "assets/js").rglob("*.js"))
    if (site / "assets/playground/examples.js").is_file():
        assets.add(site / "assets/playground/examples.js")
    pending = list(assets)
    while pending:
        source = pending.pop()
        source_text = source.read_text(encoding="utf-8")
        urls = SCRIPT_ASSETS.findall(source_text) if source.suffix == ".js" else [first or second for first, second in CSS_IMPORT.findall(css_without_comments(source_text))] if source.suffix == ".css" else []
        for url in urls:
            asset = first_party_asset(site, source, url)
            if asset and asset not in assets:
                assets.add(asset)
                pending.append(asset)
    for asset in sorted(assets):
        relative = asset.relative_to(site).as_posix()
        if relative.startswith("assets/stylesheets/"):
            # Material's vendor CSS carries localized text; keep the pre-v3 glyph check there.
            problems.extend(f"{relative}: {character!r}" for character in sorted(
                set(asset.read_text(encoding="utf-8")) & VENDOR_CSS_REJECTED))
            continue
        source = asset.read_text(encoding="utf-8")
        from test_prepub_cleanup import SHARED_BILINGUAL_JS
        bilingual = asset.name in SHARED_BILINGUAL_JS or relative.startswith("assets/js/worlds/")
        problems.extend(javascript_findings(source, relative, bilingual=bilingual) if asset.suffix == ".js"
                        else css_findings(source, relative) if asset.suffix == ".css"
                        else findings(source, relative))
    return problems, ignored, len(assets)


def test_published_ascii_gate(published_site):
    problems, ignored, assets = scan_site(published_site)
    assert not problems, "\n".join(problems[:80]) + f"\n(allowlist: {ignored}; referenced assets: {assets})"


def built_notation_findings(site):
    from test_prepub_cleanup import CJK, SHARED_BILINGUAL_JS

    for path in sorted(site.rglob("*")):
        if path.suffix not in {".html", ".js", ".json", ".css", ".svg", ".txt", ".xml"} or not path.is_file():
            continue
        relative = path.relative_to(site)
        localized = (relative.parts[:2] == ("assets", "javascripts") or
                     relative.parts[:2] == ("assets", "stylesheets"))
        bilingual = relative.name in SHARED_BILINGUAL_JS or relative.parts[:3] == ("assets", "js", "worlds")
        translated = (bilingual or relative.parts[:3] == ("assets", "data", "worlds_v2") or
                      relative.parts[:2] == ("research", "bundles"))
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            def disallowed(character, *, path=path, line=line, localized=localized, translated=translated):
                return (character in LEGACY_REJECTED or
                        not (character == "–" and path.suffix == ".js" and line.lstrip().startswith("//")) and
                        not localized and not (translated and CJK.fullmatch(character)) and
                        ord(character) > 127 and character not in ALLOWED_SITE_CHARS)

            for character in line:
                if disallowed(character):
                    yield f"{relative}:{line_number}: {character!r}"
            for escaped in JS_UNICODE_ESCAPE.finditer(line):
                character = escaped_character(escaped)
                if disallowed(character):
                    yield f"{relative}:{line_number}: escaped {character!r}"
            if path.suffix == ".css":
                for escaped in CSS_ESCAPE.finditer(line):
                    if escaped.group(1) and not (line.startswith('html[lang^="zh"]') and
                                                  CJK.fullmatch(chr(int(escaped.group(1), 16)))) and disallowed(chr(int(escaped.group(1), 16))):
                        yield f"{relative}:{line_number}: escaped CSS glyph"
            if path.suffix == ".html":
                decoded = unescape(line)
                if decoded != line and any(disallowed(character) for entity in re.findall(r"&(?:#\d+|#x[\da-fA-F]+|[a-zA-Z]+);", line)
                                           for character in unescape(entity)):
                    yield f"{relative}:{line_number}: encoded HTML glyph"


def test_every_built_file_has_no_old_notation(published_site):
    problems = list(built_notation_findings(published_site))
    assert not problems, "\n".join(problems[:80]) + f"\n({len(problems)} files with old notation)"


def test_legacy_exports_kept_only_if_used_and_aliased(published_site):
    worlds = published_site / "assets/data/worlds"
    assert len(list(worlds.glob("*.json"))) == 13
    assert not list(worlds.glob("*/*.json"))
    clock = json.loads((worlds / "clock.json").read_text(encoding="utf-8"))
    assert clock["operators"][0]["name"] == "f1"
    assert clock["curated"][0] == "f7"
    assert "v1_u" not in clock["operators"][0]["name"]
    assert (published_site / "assets/data/challenge/induce.json").exists()
    assert (published_site / "assets/data/challenge/v2.json").exists()
    assert not (published_site / "assets/data/challenge/expert.json").exists()
    assert not (published_site / "assets/javascripts/lunr/min/lunr.el.min.js").exists()


def test_legacy_export_codec_preserves_structure_and_aliases_operator_names():
    from tools.mkdocs_hooks import legacy_ascii

    original = {"ops": [{"name": "♦₆", "expression": "x ♦₆ y"}], "literal": "●", "foreign": "☃", "count": 12}
    converted = legacy_ascii(original)
    assert converted == {"ops": [{"name": "f6", "expression": "x f6 y"}],
                         "literal": "●", "foreign": "v1_u2603_", "count": 12}
    assert original["ops"][0]["name"] == "♦₆"


def test_material_glyph_rewrite_keeps_v3_symbols():
    from tools.mkdocs_hooks import replace_material_glyphs

    assert replace_material_glyphs('content:"◆"; content:"↓"; content:"⊞"') == (
        'content:"◆"; content:"↓"; content:"Win"')


def test_gate_checks_unreferenced_json_css_scripts_and_redirects(tmp_path):
    site = tmp_path / "site"
    for name, text in (("assets/data/unused.json", '{"example":"☃"}'),
                       ("assets/js/unused.js", 'const unused = "☃";'),
                       ("assets/css/unused.css", '/* ☃ */'),
                       ("old/index.html", '<meta http-equiv="refresh" content="0; url=/">☃'),
                       ("assets/data/escaped.json", r'{"example":"\u2603"}'),
                       ("assets/css/escaped.css", r'body::after{content:"\2603"}'),
                       ("old/entity.html", '&#x2603;')):
        output = site / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    assert len(list(built_notation_findings(site))) == 7


def test_legacy_preset_data_is_scanned(tmp_path):
    site = tmp_path / "site"
    preset = site / "assets/playground/examples.js"
    preset.parent.mkdir(parents=True)
    preset.write_text('window.OPULSE_PLAYGROUND_EXAMPLES = [{"expression": "a ☃"}];', encoding="utf-8")
    problems, _, _ = scan_site(site)
    assert any("assets/playground/examples.js" in problem and "☃" in problem for problem in problems)


def test_learn_newcomer_action_opens_challenge():
    page = (ROOT / "docs/learn/index.md").read_text(encoding="utf-8")
    assert "[Explore Play](../play/challenge/)" in page


def test_retired_visualizers_are_not_shipped(published_site):
    for filename in ("expviz.js", "kinds-legend.js", "opulse-anim.js", "opulse-vis.js", "stitch.js"):
        assert not (ROOT / "docs/assets/js" / filename).exists()
        assert not (published_site / "assets/js" / filename).exists()


def test_ascii_mirror_only_accepts_declared_copy_changes(tmp_path):
    mirror = tmp_path / "challenge.js"
    source = tmp_path / "source" / "challenge.js"
    source.parent.mkdir()
    mirror.write_text('const label = "Previous ← / Next →";', encoding="utf-8")
    source.write_text('const label = "Previous <- / Next ->";', encoding="utf-8")
    assert_ascii_legacy_mirror(source, mirror)
    source.write_text('const label = "Other <- / Next ->";', encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_ascii_legacy_mirror(source, mirror)


def test_unlinked_legacy_report_is_not_published(published_site):
    referring_pages = [page.relative_to(published_site).as_posix()
                       for page in published_site.rglob("*.html")
                       if not page.is_relative_to(published_site / "assets/report")
                       and "assets/report" in page.read_text(encoding="utf-8")]
    assert not referring_pages, referring_pages
    assert not (published_site / "assets/report/index.html").exists()
    assert not (published_site / "assets/report/graph.dot").exists()


def test_current_routes_do_not_ship_lab_mock(published_site):
    for route in ("index.html", "learn/index.html", "learn/kinds/index.html", "play/index.html",
                  "worlds/index.html", "research/index.html", "build/index.html", "reference/index.html"):
        html = (published_site / route).read_text(encoding="utf-8")
        parsed = PublishedPage()
        parsed.feed(html)
        assert not any(urlsplit(url).path.endswith("/atoms2/mock.js") for url in parsed.assets), route


def test_scanner_catches_entities_and_asset_payload(tmp_path):
    site = tmp_path / "site"
    page = site / "reference" / "index.html"
    page.parent.mkdir(parents=True)
    asset = site / "assets" / "example.json"
    asset.parent.mkdir()
    asset.write_text('{"example": "☃", "source": "/tmp/hidden"}', encoding="utf-8")
    page.write_text('<html><body><p>name &#x2603; — visible</p><script src="../assets/example.json"></script>'
                    '<div hidden>◆ ignored</div></body></html>', encoding="utf-8")
    problems, ignored, assets = scan_site(site)
    assert assets == 1 and ignored["rebuild_pages"] == 0
    assert any("reference/index.html" in problem and "☃" in problem for problem in problems)
    assert any("assets/example.json" in problem and "/tmp/" in problem for problem in problems)


def test_scanner_checks_embedded_json_even_in_legacy_pages(tmp_path):
    site = tmp_path / "site"
    page = site / "assets/report/index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<html><body><h1>Legacy-v1 report</h1>\n'
                    '<script type="application/json" id="data">{"notation":"☃"}</script>\n'
                    '<script>document.body.textContent = "—";</script></body></html>', encoding="utf-8")
    problems, ignored, _ = scan_site(site)
    assert ignored["rebuild_pages"] == 0
    assert any("assets/report/index.html:2:" in problem and "☃" in problem for problem in problems)
    assert any("assets/report/index.html:3:" in problem and "—" in problem for problem in problems)


def test_scanner_checks_linked_legacy_configuration(tmp_path):
    site = tmp_path / "site"
    page = site / "reference/configuration/index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<html><body><p>Legacy-v1 reference: index_chars "☃"</p>'
                    '</body></html>', encoding="utf-8")
    problems, ignored, _ = scan_site(site)
    assert ignored["rebuild_pages"] == 0
    assert any("reference/configuration/index.html" in problem and "☃" in problem
               for problem in problems)


def test_findings_preserve_positions_after_multiple_hits():
    assert list(findings("☃x\n→—", "sample", 7, 4)) == [
        "sample:7:4: '☃'", "sample:8:2: '—'",
    ]


def test_scanner_follows_first_party_fetches(tmp_path):
    site = tmp_path / "site"
    page = site / "reference" / "index.html"
    page.parent.mkdir(parents=True)
    assets = site / "assets"
    assets.mkdir()
    (assets / "example.js").write_text('fetch("./example.json")', encoding="utf-8")
    (assets / "example.json").write_text('{"notation":"☃"}', encoding="utf-8")
    page.write_text('<html><body><script src="../assets/example.js"></script></body></html>', encoding="utf-8")
    problems, _, count = scan_site(site)
    assert count == 2
    assert any("assets/example.json" in problem for problem in problems)


def test_scanner_checks_inline_script_literals_not_comments(tmp_path):
    site = tmp_path / "site"
    page = site / "learn" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<html><body><script>// ◆ ignored\n'
                    'document.body.textContent = "☃";\n'
                    'document.body.title = "\\u2603";</script></body></html>', encoding="utf-8")
    problems, _, assets = scan_site(site)
    assert assets == 0
    assert len(problems) == 2
    assert all("learn/index.html" in problem for problem in problems)


def test_scanner_checks_linked_and_imported_css_content(tmp_path):
    site = tmp_path / "site"
    page = site / "learn" / "index.html"
    page.parent.mkdir(parents=True)
    css = site / "assets"
    css.mkdir()
    (css / "base.css").write_text('@import url(nested.css); /* content: "◆"; @import "ignored.css" */\n'
                                  'body::after{content:"☃"}', encoding="utf-8")
    (css / "nested.css").write_text('body::before{content:"\\2603 "}', encoding="utf-8")
    page.write_text('<html><head><link rel="stylesheet" href="../assets/base.css"></head>'
                    '<body></body></html>', encoding="utf-8")
    problems, _, assets = scan_site(site)
    assert assets == 2
    assert len(problems) == 2
    assert any("assets/base.css" in problem and "☃" in problem for problem in problems)
    assert any("assets/nested.css" in problem and "☃" in problem for problem in problems)


def test_scanner_checks_rendered_js_strings_but_not_comments(tmp_path):
    site = tmp_path / "site"
    page = site / "learn" / "index.html"
    page.parent.mkdir(parents=True)
    asset = site / "assets" / "example.js"
    asset.parent.mkdir()
    asset.write_text('// ◆ not displayed\nconst rule = /a\\/\\/b/;\n'
                     'button.textContent = "Frac☃";\n'
                     'button.title = `Result — ${value}`;\n'
                     'button.value = "\\u2603";\n', encoding="utf-8")
    page.write_text('<html><body><script src="../assets/example.js"></script></body></html>', encoding="utf-8")
    problems, _, count = scan_site(site)
    assert count == 1
    assert any("assets/example.js:3:" in problem and "☃" in problem for problem in problems)
    assert any("assets/example.js:4:" in problem and "—" in problem for problem in problems)
    assert any("assets/example.js:5:" in problem and "☃" in problem for problem in problems)
    assert not any("◆" in problem for problem in problems)


def test_scanner_audits_unlinked_published_scripts(tmp_path):
    site = tmp_path / "site"
    page = site / "worlds" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html><body>Worlds</body></html>", encoding="utf-8")
    scripts = site / "assets/js/worlds"
    scripts.mkdir(parents=True)
    (scripts / "sample-rules.js").write_text('const rule = `a ☃ b = b ☃ a`;\n', encoding="utf-8")
    (scripts / "sample-icon.js").write_text('const icon = "☃";\n', encoding="utf-8")
    (site / "assets/js/help.js").write_text('const example = "☃";\n', encoding="utf-8")
    problems, _, count = scan_site(site)
    assert count == 3
    assert any("assets/js/worlds/sample-rules.js:1:" in problem and "☃" in problem for problem in problems)
    assert any("assets/js/worlds/sample-icon.js:1:" in problem and "☃" in problem for problem in problems)
    assert any("assets/js/help.js:1:" in problem and "☃" in problem for problem in problems)


def test_scanner_checks_marked_redirects(tmp_path):
    site = tmp_path / "site"
    page = site / "api" / "legacy" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<html><head><meta http-equiv="refresh" content="0; url=/reference/">'
                    '<meta name="robots" content="noindex"></head><body>☃</body></html>', encoding="utf-8")
    assert any("api/legacy/index.html" in finding for finding in scan_site(site)[0])
    page.write_text('<html><body>☃ not a redirect</body></html>', encoding="utf-8")
    assert scan_site(site)[0]


def test_redirect_lookalike_outside_manifest_is_scanned(tmp_path):
    site = tmp_path / "site"
    page = site / "reference" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text('<html><head><meta http-equiv="refresh" content="0; url=/build/">'
                    '<meta name="robots" content="noindex"></head><body>☃</body></html>', encoding="utf-8")
    problems, ignored, _ = scan_site(site)
    assert ignored["redirects"] == 0
    assert any("reference/index.html" in problem for problem in problems)


def test_owned_pages_put_badges_before_example_copy():
    pages = [*sorted((ROOT / "docs/research").glob("*.md")),
             *sorted((ROOT / "docs/build").glob("*.md")),
             *(ROOT / "docs/reference" / name for name in
               ("index.md", "api.md", "glossary.md", "provenance.md"))]
    for page in pages:
        content = page.read_text(encoding="utf-8")
        assert not list(findings(content, page.name)), page
        for line in content.splitlines():
            if 'class="ar-badge' in line:
                assert line.strip().startswith("<span") and line.strip().endswith("</span>"), (page, line)
        assert "Designed example:" not in content and "**Legacy-v1:**" not in content, page


def test_research_and_builder_cards_label_their_examples_first():
    for name in ("research/index.md", "research/experiments.md", "build/world.md"):
        content = (ROOT / "docs" / name).read_text(encoding="utf-8")
        cards = re.findall(r'<section class="ar-card"[^>]*>(.*?)</section>', content, re.DOTALL)
        assert cards, name
        for card in cards:
            badge = card.find('<span class="ar-badge')
            assert badge >= 0, (name, card[:80])
            body = card.find("</p>", card.find('class="ar-number'))
            intervening = card[body + 4:badge].splitlines()
            assert badge > body and all(not line.strip() or line.lstrip().startswith("#")
                                        for line in intervening), (name, card[:100])


def test_copy_enhancer_renders_only_notation():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = r"""
const ui = require(process.argv[1]);
const cases = ['?top{body}', '#mul_comm', 'Frac<1, 2>', '@fixpoint[step](roads)',
  'eq(mul(a, b), mul(b, a))', 'PYTHONPATH=src', 'worlds/decl/v2/circuits@1.json'];
console.log(JSON.stringify(cases.map(text => ui.notation(text, false))));
"""
    result = subprocess.run([node, "-e", script, str(ROOT / "docs/assets/js/atoms2/research-ui.js")],
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == ["expr", "token", "expr", "expr", "expr", None, None]


def test_owned_page_assets_resolve_after_build(published_site):
    for route in ("research", "research/protocols", "research/experiments", "build", "build/world",
                  "reference", "reference/api", "reference/glossary", "reference/provenance"):
        page = published_site / route / "index.html"
        html = page.read_text(encoding="utf-8")
        for asset in ("assets/js/atoms2/research-ui.js", "assets/css/atoms2-research.css"):
            assert asset in html, (route, asset)
            relative = "../../" if "/" in route else "../"
            assert (page.parent / relative / asset).is_file(), (route, asset)
            assert f'{relative}{asset}' in html, (route, asset)


def test_reference_spec_version(published_site):
    spec = (ROOT / "docs/spec/atoms-v2.md").read_text(encoding="utf-8")
    version = re.search(r"Spec version: `(atoms-v2/[0-9.]+)`", spec).group(1)
    from tools.mkdocs_hooks import current_core_digest

    core_digest = current_core_digest()
    for name in ("index", "api", "provenance"):
        source = (ROOT / "docs/reference" / f"{name}.md").read_text(encoding="utf-8")
        output = published_site / "reference" / ("index.html" if name == "index" else f"{name}/index.html")
        html = output.read_text(encoding="utf-8")
        assert "{{ A2_SPEC_VERSION }}" in source
        assert version in html
        assert "A2_SPEC_VERSION" not in html
        assert not [v for v in re.findall(r"atoms-v2/[0-9.]+", html) if v != version]
    provenance = (published_site / "reference/provenance/index.html").read_text(encoding="utf-8")
    quickstart = (published_site / "build/index.html").read_text(encoding="utf-8")
    assert f"Core input SHA-256: <code>{core_digest}</code>" in provenance
    assert f"Executable (core SHA-256 {core_digest})" in quickstart


def test_reference_labels_follow_spec_and_kernel_at_render_time(tmp_path, monkeypatch):
    path = ROOT / "tools/mkdocs_hooks.py"
    spec = importlib.util.spec_from_file_location("mkdocs_hooks", path)
    hooks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hooks)
    alternate_spec = tmp_path / "spec.md"
    alternate_spec.write_text("Spec version: `atoms-v2/9.8` (test)\n", encoding="utf-8")
    monkeypatch.setattr(hooks, "SPEC", alternate_spec)
    monkeypatch.setattr(hooks, "current_core_digest", lambda: "a1234567")
    config = SimpleNamespace(docs_dir=str(ROOT / "docs"))
    page = SimpleNamespace(file=SimpleNamespace(src_uri="reference/provenance.md"))
    rendered = hooks.on_page_markdown("`{{ A2_SPEC_VERSION }}` / `{{ A2_CORE_DIGEST }}`", page, config, None)
    assert rendered == "`atoms-v2/9.8` / `a1234567`"
    page.file.src_uri = "build/index.md"
    assert hooks.on_page_markdown("Executable (core SHA-256 {{ A2_CORE_DIGEST }})", page, config, None) == "Executable (core SHA-256 a1234567)"
    config.docs_dir = str(tmp_path)
    assert hooks.on_page_markdown("{{ A2_SPEC_VERSION }}", page, config, None) == "{{ A2_SPEC_VERSION }}"
    alternate_spec.write_text("No spec version\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing atoms-v2 spec version"):
        hooks.current_spec_version()


def test_protocol_template_digest_and_honest_result(published_site):
    template = json.loads((published_site / "research/action-audit-v1.json").read_text(encoding="utf-8"))
    export = (published_site / "research" / template["world"]["export"]).resolve()
    assert export.is_relative_to(published_site.resolve()) and export.is_file()
    digest = hashlib.sha256(export.read_bytes()).hexdigest()
    assert digest == template["world"]["export_sha256"]
    assert json.loads(export.read_text(encoding="utf-8"))["decl"]["lock"]["world_hash"] == template["world"]["stored_declaration_lock_world_hash"]
    provenance = (published_site / "reference/provenance/index.html").read_text(encoding="utf-8")
    assert re.findall(r"SHA-256 file digest\s*<code>([a-f0-9]{64})</code>", provenance) == [digest]
    assert template["world"]["stored_declaration_lock_world_hash"] in provenance
    assert template["world"]["spec_revision"] is None
    assert template["status"] == "designed-example"
    assert template["checker_artifact"] is template["result"] is None
    protocols = (published_site / "research/protocols/index.html").read_text(encoding="utf-8")
    assert 'href="../action-audit-v1.json"' in protocols


def test_action_digest_is_derived_from_published_bytes(tmp_path):
    from tools.mkdocs_hooks import fill_action_provenance

    export = tmp_path / "assets/data/worlds_v2/action.json"
    provenance = tmp_path / "reference/provenance/index.html"
    template = tmp_path / "research/action-audit-v1.json"
    for path in (export, provenance, template):
        path.parent.mkdir(parents=True)
    provenance_source = "SHA-256 file digest <code>{{ A2_ACTION_EXPORT_SHA256 }}</code>; {{ A2_ACTION_LOCK_WORLD_HASH }}"
    template_source = '{"digest": "{{ A2_ACTION_EXPORT_SHA256 }}", "lock": "{{ A2_ACTION_LOCK_WORLD_HASH }}"}'
    for value in ("first", "second"):
        export.write_text(json.dumps({"decl": {"lock": {"world_hash": value}}}), encoding="utf-8")
        provenance.write_text(provenance_source, encoding="utf-8")
        template.write_text(template_source, encoding="utf-8")
        fill_action_provenance(tmp_path)
        digest = hashlib.sha256(export.read_bytes()).hexdigest()
        assert digest in provenance.read_text(encoding="utf-8")
        assert value in provenance.read_text(encoding="utf-8")
        assert json.loads(template.read_text(encoding="utf-8")) == {"digest": digest, "lock": value}
    with pytest.raises(ValueError, match="Missing provenance placeholder"):
        fill_action_provenance(tmp_path)


def test_reference_example_declarations_parse():
    from opulse.atoms.notation import parse_definition, print_definition

    source = (ROOT / "docs/reference/index.md").read_text(encoding="utf-8")
    examples = re.findall(r"^- \*\*(?:Object|Operation|Combinator|Observation|Law|Bridge):\*\* (?:`([^`]+)`|<code data-a2-expr>([^<]+)</code>)", source, re.MULTILINE)
    assert len(examples) == 6
    for plain, encoded in examples:
        example = plain or unescape(encoded)
        parsed = parse_definition(example)
        assert print_definition(parsed) == example


def test_build_and_reference_do_not_advertise_circuits_as_a_runnable_quickstart(published_site):
    for route in ("build/world", "reference/api"):
        html = (published_site / route / "index.html").read_text(encoding="utf-8")
        assert "runnable circuits" not in html.lower()
        assert "circuits quickstart" not in html.lower()
    world = (published_site / "build/world/index.html").read_text(encoding="utf-8")
    assert "Planned:" in world and "core-only quickstart" in world
    assert "KeyError" not in world
    build = (published_site / "build/index.html").read_text(encoding="utf-8")
    assert "Planned:" in build and "world-builder command" in build
    assert "KeyError" not in build


def test_build_never_claims_circuits_status_without_build_hook():
    for name in ("index", "world"):
        page = (ROOT / "docs/build" / f"{name}.md").read_text(encoding="utf-8")
        assert "new_library()" in page and "build_depth_library()" in page
        assert "Circuits build status: not published." in page
        assert "Executable (source constructors" not in page
        assert "new_library()` completes" not in page
    command = (ROOT / "docs/build/index.md").read_text(encoding="utf-8")
    assert "from opulse.worlds_v2.circuits.world import new_library" in command
    assert "from opulse.worlds_v2.circuits.story import build_depth_library" in command
    assert "constructor()" in command


def test_research_experiments_allow_pure_combinators_but_keep_grammar_design_only():
    page = (ROOT / "docs/research/experiments.md").read_text(encoding="utf-8")
    # Notation v3: machine names in this prose became descriptions (intended visible change).
    assert "parse-count sketch reads a parse-count probe" in page
    assert "spec 0.5 also permits an observation to apply a pure combinator" in page
    assert "grammar tower is still a design until rebuilt and checked" in page
    assert "cannot act or read the truth except through probes" in page


def test_featured_ladder_observation_has_spec_05_design_status():
    page = (ROOT / "docs/play/ladders.md").read_text(encoding="utf-8")
    script = (ROOT / "docs/assets/js/atoms2/ladders.js").read_text(encoding="utf-8")
    assert "Spec 0.5 permits the proposed <code>?sum_numerator</code>" in page
    assert "still needs a rebuilt world and checked export" in page
    assert "Spec 0.5 allows pure dependencies for ?sum_numerator" in script
    assert "no rebuilt, checked 0.5 export" in script


def test_reference_uses_only_canonical_public_links(published_site):
    reference = (published_site / "reference/index.html").read_text(encoding="utf-8")
    api = (published_site / "reference/api/index.html").read_text(encoding="utf-8")
    assert 'href="spec/"' in reference
    pages = (reference, api) + tuple(
        (published_site / "reference" / name / "index.html").read_text(encoding="utf-8")
        for name in ("glossary", "provenance")
    )
    for html in pages:
        for retired in ("cli", "configuration", "semantics"):
            assert f'href="../{retired}/"' not in html
    provenance = (published_site / "reference/provenance/index.html").read_text(encoding="utf-8")
    assert 'href="../spec/"' in provenance
    assert "docs/reference/cli.md" in api
    assert "docs/reference/configuration.md" in api


def _docs_reference_generator():
    path = ROOT / "tools/docs_reference.py"
    spec = importlib.util.spec_from_file_location("docs_reference", path)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


def test_reference_generator_uses_ascii_aliases_in_english():
    generator = _docs_reference_generator()
    english = generator.config_page()
    assert english == (ROOT / "docs/reference/configuration.md").read_text(encoding="utf-8")
    assert "Legacy-v1 symbols shown as ASCII aliases" in english
    assert "f0 (U+2295)" in english
    assert not FORBIDDEN.search(english)
    chinese_source = generator.config_page(legacy_symbols=True)
    assert 'index_chars: "₀₁₂₃₄₅₆₇₈₉"' in chinese_source
    assert "| `circled` | ⊕ ⊗ ⊝ |" in chinese_source


@pytest.mark.skipif(not (ROOT / "docs_zh").is_dir(),
                    reason="docs_zh/ is not part of this checkout (the public tree ships the English site only)")
def test_reference_generator_uses_ascii_aliases_in_chinese():
    generator = _docs_reference_generator()
    english = generator.config_page()
    chinese_page = (ROOT / "docs_zh/reference/configuration.md").read_text(encoding="utf-8")
    assert generator.chinese_config_page(english, chinese_page) == chinese_page
    assert 'index_chars: "\\u2080\\u2081\\u2082\\u2083\\u2084\\u2085\\u2086\\u2087\\u2088\\u2089"' in chinese_page
    assert "| `circled` | f0 (U+2295)" in chinese_page
    assert not any(character in LEGACY_REJECTED for character in chinese_page)
    assert not re.search("scratchpad|/tmp/|cx_wt", chinese_page, re.IGNORECASE)


def test_legacy_cli_help_uses_ascii_aliases_for_original_expression():
    path = ROOT / "tools/docs_reference.py"
    spec = importlib.util.spec_from_file_location("docs_reference", path)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    page = (ROOT / "docs/reference/cli.md").read_text(encoding="utf-8")
    assert "f0(3, f1(4, 2))" in page
    assert "Legacy-v1 symbols shown as ASCII aliases" in page
    assert not FORBIDDEN.search(page)
    assert generator.ascii_cli_help("x: 3 ⊕ (4 ⊗ 2)") == "x: f0(3, f1(4, 2))"
    assert generator.cli_page() == page


def test_reference_claims_use_current_core_digest_and_do_not_treat_export_lock_as_current():
    from opulse.atoms.world import WorldDecl

    quickstart = (ROOT / "docs/build/index.md").read_text(encoding="utf-8")
    assert "Executable (core SHA-256 {{ A2_CORE_DIGEST }})" in quickstart
    for path in (ROOT / "docs/reference/index.md", ROOT / "docs/reference/provenance.md"):
        assert not re.search(r"(?:commit|kernel)\s+`?[0-9a-f]{8,40}`?", path.read_text(encoding="utf-8")), path
    export = json.loads((ROOT / "docs/assets/data/worlds_v2/action.json").read_text(encoding="utf-8"))
    stored = export["decl"]["lock"]["world_hash"]
    assert WorldDecl.from_dict(export["decl"]).world_hash() == stored
    prose = (ROOT / "docs/reference/provenance.md").read_text(encoding="utf-8")
    assert "{{ A2_ACTION_LOCK_WORLD_HASH }}" in prose and "stored value matches" in prose.lower()
    template = json.loads((ROOT / "docs/research/action-audit-v1.json").read_text(encoding="utf-8"))
    assert template["world"]["stored_declaration_lock_world_hash"] == "{{ A2_ACTION_LOCK_WORLD_HASH }}"


def test_owned_pages_distinguish_python_law_and_bridge_checks_from_browser_examples(published_site):
    for route in ("reference", "reference/api", "reference/glossary", "build/world"):
        html = (published_site / route / "index.html").read_text(encoding="utf-8")
        assert "not yet executable" not in html, route
        assert "law" in html and "bridge" in html, route
        assert "browser" in html or "this table does not run those checks" in html, route


def test_mobile_tables_have_accessible_scroll_cue():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    style = (ROOT / "docs/assets/css/atoms2-research.css").read_text(encoding="utf-8")
    assert '.ar-page .ar-table-scroll { max-width: 100%; overflow-x: auto;' in style
    script = r"""
const assert = require('node:assert/strict');
const ui = require(process.argv[1]);
const children = [];
const parent = { insertBefore(node) { children.push(node); } };
const table = { parentNode: parent, closest() { return null; }, querySelectorAll() { return []; } };
const glossary = { closest(selector) { return selector === '.ar-glossary' ? {} : null; } };
global.document = { createElement(tag) {
  return { tag, setAttribute(name, value) { this[name] = value; },
    appendChild(child) { this.child = child; } };
} };
const page = { querySelectorAll() { return [table, glossary]; } };
ui.wrapTables(page);
assert.equal(children.length, 2);
assert.equal(children[0].textContent, 'Scroll sideways to see every column.');
assert.equal(children[1].tag, 'div');
assert.equal(children[1].tabindex, '0');
assert.equal(children[1]['aria-label'], 'Scrollable reference table');
assert.equal(children[1].child, table);
const headers = ['Field', 'Minimum declaration', 'Why it matters'].map(textContent => ({ textContent }));
const cells = Array.from({ length: 3 }, () => ({ setAttribute(name, value) { this[name] = value; } }));
const row = { querySelectorAll() { return cells; } };
const stackedTable = { parentNode: parent, closest() { return null; },
  querySelectorAll(selector) { return selector === 'thead th' ? headers : [row]; } };
ui.wrapTables({ querySelectorAll() { return [stackedTable]; } });
assert.equal(children[2].textContent, 'Each row shows its fields below.');
assert.equal(children[3].className, 'ar-table-scroll ar-table-stack');
assert.equal(children[3]['aria-label'], 'Reference table, grouped by row');
assert.deepEqual(cells.map(cell => cell['data-label']), headers.map(header => header.textContent));
table.closest = selector => selector === '.ar-table-scroll' ? {} : null;
ui.wrapTables(page);
assert.equal(children.length, 4);
"""
    subprocess.run([node, "-e", script, str(ROOT / "docs/assets/js/atoms2/research-ui.js")],
                   check=True, capture_output=True, text=True)


def test_research_and_reference_round_four_copy(published_site):
    research = (published_site / "research/index.html").read_text(encoding="utf-8")
    reference = (published_site / "reference/index.html").read_text(encoding="utf-8")
    glossary = (published_site / "reference/glossary/index.html").read_text(encoding="utf-8")
    assert "Finite traces need external tests" in research
    assert research.index("A finite world fixes its operations") < research.index("FINITE RL")
    # Notation v3 shows defined operations infix; the old named-call rule is storage syntax only.
    assert "The display uses infix defined marks" in reference and "they are storage syntax" in reference
    assert "Copying does not verify a designed declaration" in glossary
    assert "ASCII examples are copyable notation" not in glossary


def test_reference_links_published_spec_and_build_copy_names_source_scope():
    reference = (ROOT / "docs/reference/index.md").read_text(encoding="utf-8")
    quickstart = (ROOT / "docs/build/index.md").read_text(encoding="utf-8")
    world = (ROOT / "docs/build/world.md").read_text(encoding="utf-8")
    assert "[versioned specification](spec.md)" in reference
    assert "not a separate site destination" not in reference
    assert "Memoization (reuse of a cached subresult)" in reference
    assert "python -m pip install -e ." in quickstart
    assert "Optional: inspect the circuits source" in quickstart
    assert "Inspect an existing declaration" in world
    assert "index.md#optional-inspect-the-circuits-source" in world


def test_built_provenance_spec_link_resolves_to_published_spec(published_site):
    page = published_site / "reference/provenance/index.html"
    html = page.read_text(encoding="utf-8")
    match = re.search(r'<a href="([^"]+)">versioned core specification</a>', html)
    assert match, "The built provenance page must link the core specification"
    href = unescape(match.group(1))
    assert urlsplit(href).path == "../spec/"
    target = (page.parent / unquote(urlsplit(href).path) / "index.html").resolve()
    assert target == published_site / "reference/spec/index.html"
    assert target.is_file()


@pytest.mark.parametrize("page, heading, expected", [
    ("api.md", "Clock input: what changed from v1 to v2", "published add(11, 3): 2\nlegacy add(14, 0): 2\nv2 add(14, 0): 2\nv2 add(11, 3): 2"),
    ("glossary.md", "Observation is not truth", "same full state: False\nsame top view: True\nsame front view: False"),
])
def test_reference_flagship_python_runs_as_published(page, heading, expected):
    source = (ROOT / "docs/reference" / page).read_text(encoding="utf-8")
    if page == "glossary.md":
        from tools.mkdocs_hooks import glossary_volume_comparison

        source = source.replace("{{ A2_GLOSSARY_COMPARISON }}", glossary_volume_comparison(
            ROOT / "docs/assets/data/worlds_v2/shadows.json"))
    section = source.split(f"## {heading}\n", 1)[1]
    command = re.search(r"```python\n(.*?)\n```", section, re.DOTALL)
    output = re.search(r"```text\n(.*?)\n```", section, re.DOTALL)
    assert command and output
    assert output.group(1) == expected
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, "-c", command.group(1)], cwd=ROOT, env=environment,
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == expected


def test_clock_flagship_keeps_published_legacy_case_bytes():
    from opulse.atoms.golden import iter_cases

    source = (ROOT / "docs/assets/data/worlds/clock.json").read_text(encoding="utf-8")
    case = next(case for case in iter_cases("clock", main_only=True)
                if case.kind == "atom_example" and case.operator == "add")
    assert case.inputs == (11, 3) and case.expected_output == 2
    assert '"expression":"11 + 3","inputs":[{"t":"int","v":11},{"t":"int","v":3}],"output":{"t":"int","v":2}' in source
    assert 14 % 12 == 2
    spec = (ROOT / "docs/spec/atoms-v2.md").read_text(encoding="utf-8")
    assert "Entry rule `normalize` on every" in spec
    assert "`14` enters as `2`" in spec


def test_clock_flagship_runs_declared_edges():
    from opulse.atoms import kernel
    from opulse.atoms.values import Ok
    from opulse.tasks_v2 import kernel_engine, templates
    from opulse.tasks_v2.angles.template import clock_hour

    clock = templates.library("clock@2")
    hour = next(obj for obj in clock.world.objects if obj.name == "hour")
    add = next(op for op in clock.world.operations if op.name == "add")
    assert hour.form == "refine" and all(
        edge.sort == "hour" and edge.enter == "normalize" for edge in add.inputs
    )
    entry = clock_hour(14)
    assert isinstance(entry, Ok) and entry.value == 2
    outcome = kernel.call("add", (entry.value, 0), kernel_engine.scope("clock@2")).outcome
    assert isinstance(outcome, Ok) and outcome.value == 2
    # The declared edges reduce inputs on entry: 14 enters as hour 2.
    for inputs in ((14, 0), (11, 3)):
        declared = clock.run("add", inputs).outcome
        assert isinstance(declared, Ok) and declared.value.fields[0] == 2
    page = (ROOT / "docs/reference/api.md").read_text(encoding="utf-8")
    assert 'clock.run("add", inputs)' in page
    assert "int_mod_twelve" not in page
    assert "host add(2, 0): 2" not in page


def test_shadows_flagship_export_pair_observation_and_scope():
    from opulse.worlds_v2.shadows.deep_hosts import front, top
    from tools.mkdocs_hooks import glossary_volume_comparison, glossary_volume_pair

    export = json.loads((ROOT / "docs/assets/data/worlds_v2/shadows.json").read_text(encoding="utf-8"))
    decl = export["decl"]
    assert export["world"] == "shadows" and export["version"] == 1
    assert decl["observation"]["judge_view"] == "full_state"
    assert "top" in decl["observation"]["capabilities"]["learner"]["probes"]
    assert "front" not in decl["observation"]["capabilities"]["learner"]["probes"]
    assert next(entry for entry in decl["objects"] if entry["name"] == "Volume")["sealed"] is False
    first, second = glossary_volume_pair()
    assert first != second and top(first) == top(second) and front(first) != front(second)
    glossary = (ROOT / "docs/reference/glossary.md").read_text(encoding="utf-8")
    assert "{{ A2_GLOSSARY_COMPARISON }}" in glossary
    assert "The export has no sealed object pair" in glossary_volume_comparison(
        ROOT / "docs/assets/data/worlds_v2/shadows.json")
    assert "Design record: shadows world, depth pass (11-04)" in glossary


def test_glossary_terms_link_to_reference_rules():
    source = (ROOT / "docs/reference/glossary.md").read_text(encoding="utf-8")
    semantics = (ROOT / "docs/reference/index.md").read_text(encoding="utf-8")
    for term, anchor in re.findall(r"^\| \[([^]]+)\]\(index\.md#([a-z-]+)\)", source, re.MULTILINE):
        assert term and any(re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") == anchor
                            for heading in re.findall(r"^## (.+)$", semantics, re.MULTILINE))
    assert len(re.findall(r"^\| \[[^]]+\]\(index\.md#", source, re.MULTILINE)) == 17


def test_escaped_surrogate_pairs_decode_to_one_character():
    pair = JS_UNICODE_ESCAPE.search(r'"\ud835\udd3b"')
    assert escaped_character(pair) == "\U0001d53b"
    assert escaped_character(JS_UNICODE_ESCAPE.search(r'"\u2603"')) == "\u2603"
