"""Validate notation v3 in static exports and Chrome-rendered site pages."""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from opulse.notation3 import ALLOWED_DISPLAY_CHARS, Mark, kind_of, lex, parse_expr, to_ascii, to_display

PROSE_EXCEPTIONS = frozenset("\u00a0©·¶−▸▾✓✗↳")
CJK = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]")
BLOCK = re.compile(r'"notation3"\s*:\s*')
BARE_CHIP = re.compile(r'^[@?#~]?[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\([A-Za-z0-9_,. ]*\))?$')


def bare_chip(text):
    return isinstance(text, str) and bool(BARE_CHIP.fullmatch(text.strip()))


def check_pair(display, ascii_text, label):
    problems = []
    if not isinstance(display, str) or not isinstance(ascii_text, str):
        return [f"{label}: missing display/ascii pair"]
    try:
        if to_ascii(display) != ascii_text:
            problems.append(f"{label}: display -> ASCII mismatch")
        if to_display(ascii_text) != display:
            problems.append(f"{label}: ASCII -> display mismatch")
    except (ValueError, TypeError, RecursionError) as error:
        problems.append(f"{label}: invalid formula: {error}")
    return problems


def check_index_origin(mark, origin, label):
    if not isinstance(mark, str) or not isinstance(origin, str):
        return []
    try:
        tokens = lex(mark)
    except ValueError:
        return []
    for token in tokens:
        if token.kind != 'MARK':
            continue
        numbered_given = token.value.index_kind == 'given_num'
        if origin != 'given' and numbered_given:
            return [f'{label}: defined entry has leading-zero index']
        if origin == 'given' and token.value.index_kind == 'def':
            return [f'{label}: given entry has defined index']
    return []


def family_problem(entry):
    """The glyph family of a legend mark must tell the entry's kind (DEBATE rule 1)."""
    kind = entry.get("produces") if entry.get("kind") == "template" else entry.get("kind")
    try:
        expr = parse_expr(entry.get("mark") or "")
    except (ValueError, TypeError):
        return "unparseable legend mark"
    if expr.tag == "group":  # a given BIN sign used as an operation value: (+)
        return None if kind == "operation" else f"sign mark for a {kind}"
    inner = expr.args[0] if expr.tag == "bare" and expr.args else None
    mark = inner.args[0] if inner is not None and inner.args and isinstance(inner.args[0], Mark) else None
    if mark is None:
        return "legend mark is not a mark"
    family = kind_of(mark)
    return None if family == kind else f"{family} glyph for a {kind}"


def check_block(block, label):
    problems = []
    if not isinstance(block, dict) or block.get("version") != 1 or not isinstance(block.get("worlds"), dict):
        return [f"{label}: invalid notation3 block"]
    for world_id, world in block["worlds"].items():
        scope = f"{label}:{world_id}"
        if not isinstance(world, dict):
            problems.append(f"{scope}: invalid world entry")
            continue
        legend = world.get("legend", [])
        if not isinstance(legend, list):
            problems.append(f"{scope}: invalid legend")
            continue
        marks, displays = set(), set()
        for index, entry in enumerate(legend):
            location = f"{scope}.legend[{index}]"
            if not isinstance(entry, dict):
                problems.append(f"{location}: invalid legend entry")
                continue
            mark, display = entry.get("mark"), entry.get("display")
            problems.extend(check_pair(display, mark, location))
            problems.extend(check_index_origin(mark, entry.get('origin'), location))
            if mark in marks or display in displays:
                problems.append(f"{location}: non-injective legend")
            marks.add(mark)
            displays.add(display)
            problem = family_problem(entry)
            if problem:
                problems.append(f"{location}: {problem} ({entry.get('name')!r})")
            if entry.get("signature") is not None:
                signature = entry["signature"]
                problems.extend(check_pair(signature.get("display"), signature.get("ascii"), location + ".signature"))
        for machine, formula in world.get("formulas", {}).items():
            location = f"{scope}.formulas[{machine!r}]"
            problems.extend(check_pair(formula.get("display"), formula.get("ascii"), location))
            if formula.get("signature") is not None:
                signature = formula["signature"]
                problems.extend(check_pair(signature.get("display"), signature.get("ascii"), location + ".signature"))
        for machine, segments in world.get("prose", {}).items():
            for index, segment in enumerate(segments):
                if segment[0] == "f":
                    problems.extend(check_pair(segment[1] if len(segment) > 1 else None,
                                               segment[2] if len(segment) > 2 else None,
                                               f"{scope}.prose[{machine!r}][{index}]"))
                elif segment[0] != "t":
                    problems.append(f"{scope}.prose[{machine!r}][{index}]: invalid segment")
    return problems


def check_rendered(elements, missing, visible_text, violations=None):
    """Check a browser snapshot or a tiny fixture without requiring Chrome."""
    problems = []
    for index, element in enumerate(elements):
        problems.extend(check_pair(element.get("text"), element.get("ascii"), f".n3[{index}]"))
        if isinstance(element.get("text"), str) and "::" in element["text"]:
            problems.append(f".n3[{index}]: legacy constructor separator")
    violations = violations or {}
    for label, key in (("non-given unindexed mark", "unindexed"),
                       ("numbered given on non-given entry", "numbered_givens"),
                       ("legacy constructor separator", "separators"),
                       ("nullary constructor of a constant", "nullary_constants"),
                       ("bare identifier chip", "bare_chips"),
                       ("right superscript chip", "right_superscripts")):
        for index, text in enumerate(violations.get(key, [])):
            if key == "bare_chips" and not bare_chip(text):
                continue
            if key == "separators" and any(isinstance(element.get("text"), str) and
                                            element["text"].startswith(text) for element in elements):
                continue
            problems.append(f"{label}[{index}]: {text!r}")
    for index, element in enumerate(missing):
        problems.append(f".n3-missing[{index}]: {element!r}")
    if "[object Object]" in visible_text:
        problems.append("visible text: [object Object]")
    for character in sorted(set(visible_text)):
        if CJK.fullmatch(character):
            problems.append(f"visible text: CJK {character!r}")
        elif ord(character) > 127 and character not in ALLOWED_DISPLAY_CHARS | PROSE_EXCEPTIONS:
            problems.append(f"visible text: disallowed {character!r}")
    return problems


class StaticFormulas(HTMLParser):
    VOID = frozenset(["area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                      "meta", "param", "source", "track", "wbr"])

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.missing = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if "n3-missing" in classes:
            self.missing.append(tag)
        if tag not in self.VOID:
            element = None
            if "n3" in classes:
                element = {"text": "", "ascii": attributes.get("data-n3-ascii")}
                self.elements.append(element)
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        for element in self.stack:
            if element is not None:
                element["text"] += data


def check_static_site(site):
    problems, blocks = [], 0
    for path in sorted(site.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(site)
        if path.suffix == ".html":
            parser = StaticFormulas()
            parser.feed(path.read_text(encoding="utf-8"))
            for index, element in enumerate(parser.elements):
                problems.extend(check_pair(element["text"], element["ascii"], f"{relative} .n3[{index}]"))
            problems.extend(f"{relative}: .n3-missing[{index}]" for index in range(len(parser.missing)))
        if path.suffix not in {".json", ".js"}:
            continue
        source = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            data = json.loads(source)
            found = [data["notation3"]] if isinstance(data, dict) and "notation3" in data else []
        else:
            found = []
            for match in BLOCK.finditer(source):
                try:
                    block, _ = json.JSONDecoder().raw_decode(source, match.end())
                    found.append(block)
                except json.JSONDecodeError:
                    problems.append(f"{relative}: malformed notation3 JS block")
        for index, block in enumerate(found):
            blocks += 1
            problems.extend(check_block(block, f"{relative} notation3[{index}]"))
    return problems, blocks


SNAPSHOT = r"""(() => {
  const formulas = [...document.querySelectorAll('.n3')];
  const chips = [...document.querySelectorAll('.a2-tok')].filter(e => !e.closest('.n3-legend'));
  const n3 = window.N3;
  const entries = n3 ? n3.worldIds().flatMap(world => n3.legend(world)) : [];
  return {
    elements: formulas.map(e => ({text: e.textContent, ascii: e.getAttribute('data-n3-ascii')})),
    missing: [...document.querySelectorAll('.n3-missing')].map(e => e.textContent.slice(0, 120)),
    visible: document.body.innerText,
    violations: {
      unindexed: n3 ? formulas.flatMap(e => {
        try { return n3.lex(e.textContent).filter(token => token.type === 'MARK' && token.given &&
          entries.some(entry => entry.display === token.display && entry.origin !== 'given'))
          .map(token => token.text); } catch (_) { return []; }
      }) : [],
      numbered_givens: n3 ? formulas.flatMap(e => {
        try { return n3.lex(e.textContent).filter(token => token.type === 'MARK' &&
          /_0[1-9][0-9]*/.test(token.ascii) &&
          entries.some(entry => entry.display === token.display && entry.origin !== 'given'))
          .map(token => token.text); } catch (_) { return []; }
      }) : [],
      separators: formulas.filter(e => e.textContent.includes('::')).map(e => e.textContent.slice(0, 120)),
      nullary_constants: n3 ? formulas.flatMap(e => {
        // A zero-argument constructor call of a capitalised form must print as the constant.
        try {
          const tokens = n3.lex(e.textContent);
          return tokens.filter((token, index) => token.type === 'MARK' && tokens[index + 1] &&
            tokens[index + 1].ascii === '(' && tokens[index + 2] && tokens[index + 2].ascii === ')' && (() => {
              // .n3 elements carry no world, so flag a mark only when every legend entry that
              // displays it (any registered world) is a constructor of a capitalised form.
              const same = entries.filter(entry => entry.display === token.display);
              return same.length > 0 && same.every(entry => entry.form_of &&
                /^[A-Z]/.test(String(entry.name).split('.').pop()));
            })()).map(token => token.text + '()');
        } catch (_) { return []; }
      }) : [],
      bare_chips: chips.map(e => [...e.childNodes]
        .filter(node => !node.classList?.contains('a2-layer-badge') && !node.classList?.contains('a2-part-badge'))
        .map(node => node.textContent).join('').trim()).filter(Boolean),
      right_superscripts: [...document.querySelectorAll('.a2-tok, .a2-chip')].filter(e => {
        const content = getComputedStyle(e, '::after').content;
        return content && content !== 'none' && content !== 'normal' && content !== '""';
      }).map(e => e.textContent.slice(0, 120))
    }
  };
})()"""


def page_urls(root):
    try:
        import tomllib as tomli
    except ModuleNotFoundError:
        import tomli

    config = tomli.loads((root / "tools/site_gates/sitecheck.toml").read_text(encoding="utf-8"))
    urls = set(config["include"])
    urls.update("/" + path.relative_to(root / "docs").with_suffix("").as_posix().removesuffix("/index") + "/"
                for path in (root / "docs/worlds").glob("*/index.md"))
    return sorted(urls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path, help="built MkDocs site directory")
    parser.add_argument("--output", type=Path, default=Path("/tmp/opulse-n3-roundtrip.json"))
    args = parser.parse_args()
    from sitecheck.browser import Chrome
    from sitecheck.discovery import serve

    root = Path(__file__).resolve().parents[2]
    report = {"site": str(args.site.resolve()), "pages": {}, "findings": []}
    with serve(args.site.resolve()) as base, Chrome(timeout=150) as chrome:
        for url in page_urls(root):
            try:
                chrome.open(base.rstrip("/") + url, 1440)
                chrome.pump(2)
                snapshot = chrome.evaluate(SNAPSHOT)
                findings = check_rendered(snapshot["elements"], snapshot["missing"], snapshot["visible"], snapshot["violations"])
                report["pages"][url] = {"formulas": len(snapshot["elements"]), "findings": findings}
                report["findings"].extend(f"{url}: {finding}" for finding in findings)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                report["pages"][url] = {"findings": [str(error)]}
                report["findings"].append(f"{url}: {error}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(report['pages'])} pages; {len(report['findings'])} findings; {args.output}")
    return bool(report["findings"])


if __name__ == "__main__":
    raise SystemExit(main())
