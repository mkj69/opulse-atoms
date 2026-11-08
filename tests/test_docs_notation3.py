"""Check documented notation v3 display and copy spellings."""

import html
import re
from pathlib import Path

import pytest

from opulse.notation3 import parse, show

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "README.md",
    "docs/learn/index.md",
    "docs/learn/kinds.md",
    "docs/reference/index.md",
    "docs/reference/glossary.md",
    "docs/spec/notation-v3.md",
)
FORMULA = re.compile(r'<code class="n3" data-n3-ascii="([^"]*)">(.*?)</code>')


@pytest.mark.parametrize('page', ('README.md', 'docs/reference/glossary.md',
                                  'docs/reference/index.md', 'docs/learn/kinds.md',
                                  'docs/spec/notation-v3.md'))
def test_docs_describe_numbered_givens(page):
    source = (ROOT / page).read_text(encoding='utf-8')
    assert 'starting 1 to 9' in source
    assert 'starting with 0' in source or 'leading-zero' in source
    assert 'no index' in source.lower()
    assert 'letter' in source


CASE_ROW = re.compile(
    r'^\| (C(?:[1-9]|1[0-9]|20)) \| <code class="n3" data-n3-ascii="[^"]*">(.*?)</code> \| <code>(.*?)</code> \|$',
    re.MULTILINE,
)


@pytest.mark.parametrize("page", PAGES)
def test_documented_display_formulas_round_trip(page):
    source = (ROOT / page).read_text(encoding="utf-8")
    formulas = FORMULA.findall(source)
    assert formulas, page
    for raw_ascii, raw_display in formulas:
        display = html.unescape(raw_display)
        ascii_copy = show(parse(display), True)
        assert html.unescape(raw_ascii) == ascii_copy, (page, display)
        assert show(parse(ascii_copy)) == display, (page, display)


def test_c_examples_have_matching_ascii_spellings():
    source = (ROOT / "docs/spec/notation-v3.md").read_text(encoding="utf-8")
    examples = CASE_ROW.findall(source)
    assert len(examples) == 36
    assert {label for label, _, _ in examples} == {f"C{number}" for number in range(1, 21)}
    for label, raw_display, raw_ascii in examples:
        display = html.unescape(raw_display)
        ascii_copy = html.unescape(raw_ascii)
        assert show(parse(display), True) == ascii_copy, label
        assert show(parse(ascii_copy)) == display, label
