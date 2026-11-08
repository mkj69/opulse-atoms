"""Static and pure rendered notation-v3 release gates."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.site_gates.n3_roundtrip import (
    SNAPSHOT,
    StaticFormulas,
    bare_chip,
    check_block,
    check_index_origin,
    check_pair,
    check_rendered,
    check_static_site,
    page_urls,
)

ROOT = Path(__file__).resolve().parents[1]
pytest_plugins = ("test_site_ascii",)


def example_block():
    return {"version": 1, "worlds": {"integer": {
        "legend": [{"mark": "\\dia_6", "display": "♦₆", "kind": "operation", "signature": {
            "display": "¹♦₆ : ℤ → ℤ", "ascii": "^1\\dia_6 : \\bbZ -> \\bbZ"}}],
        "formulas": {"f6(x)": {"display": "♦₆(x)", "ascii": "\\dia_6(x)",
                                "signature": {"display": "♦₆ : ℤ → ℤ", "ascii": "\\dia_6 : \\bbZ -> \\bbZ"}}},
        "prose": {"Use f6": [["t", "Use "], ["f", "♦₆(x)", "\\dia_6(x)"]]}}}}


def test_block_pairs_and_injective_legend():
    assert check_block(example_block(), "fixture") == []


def test_numbered_given_origin_gate():
    assert check_index_origin('\\dia_07', 'given', 'mark') == []
    assert any('defined index' in problem for problem in
               check_index_origin('\\dia_7', 'given', 'mark'))
    assert any('leading-zero' in problem for problem in
               check_index_origin('\\dia_07', 'invented', 'mark'))
    block = example_block()
    block['worlds']['integer']['legend'].append({'mark': '\\dia_07', 'display': '♦₀₇',
                                                 'origin': 'invented', 'signature': None})
    assert any('leading-zero' in problem for problem in check_block(block, 'fixture'))
    violations = {'numbered_givens': ['♦₀₇']}
    assert any('numbered given' in problem for problem in
               check_rendered([], [], '', violations))


def test_block_rejects_each_mismatched_pair_and_duplicate_legend():
    block = example_block()
    block["worlds"]["integer"]["formulas"]["f6(x)"]["ascii"] = "\\dia_7(x)"
    assert any("mismatch" in finding for finding in check_block(block, "fixture"))
    block = example_block()
    block["worlds"]["integer"]["legend"].append(block["worlds"]["integer"]["legend"][0].copy())
    assert any("non-injective" in finding for finding in check_block(block, "fixture"))


def test_static_html_formula_gate(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "data.json").write_text(json.dumps({"notation3": example_block()}), encoding="utf-8")
    (site / "index.html").write_text('<span class="n3" data-n3-ascii="\\dia_6"><i>♦</i>₆</span>', encoding="utf-8")
    assert check_static_site(site) == ([], 1)
    (site / "index.html").write_text('<span class="n3 n3-missing" data-n3-ascii="\\dia_7">♦₆</span>', encoding="utf-8")
    problems, blocks = check_static_site(site)
    assert blocks == 1 and any("mismatch" in problem for problem in problems)
    assert any("n3-missing" in problem for problem in problems)


def test_missing_static_ascii_attribute_rejected():
    parser = StaticFormulas()
    parser.feed('<code class="n3">♦₆</code>')
    assert check_pair(parser.elements[0]["text"], parser.elements[0]["ascii"], "fixture")


def test_rendered_snapshot_rejects_bad_formula_missing_and_visible_text():
    assert check_rendered([{"text": "♦₆", "ascii": "\\dia_6"}], [], "Use ♦₆ ©") == []
    findings = check_rendered([{"text": "♦₆", "ascii": "\\dia_7"}], ["bad"], "☃ 中文 [object Object]")
    assert any("mismatch" in finding for finding in findings)
    assert any("n3-missing" in finding for finding in findings)
    assert any("disallowed" in finding for finding in findings)
    assert any("CJK" in finding for finding in findings)
    assert any("[object Object]" in finding for finding in findings)


def test_rendered_snapshot_accepts_indexed_mark_and_constructor_chip():
    violations = {key: [] for key in ("unindexed", "separators", "bare_chips", "right_superscripts")}
    assert check_rendered([{"text": "♣₄()", "ascii": "\\club_4()"}], [], "♣₄() L3", violations) == []


def test_bare_chip_classification_catches_dotted_frames_without_mark_glyphs():
    bare = ["Hour.make", "Vec.Stored", "@Sort.part", "Sort.part()", "Sort.part(x)", "cons"]
    marked = ["ℍ₃", "ℍ₃ make", "♣₅()", "♦₆", "Sort.part(♦₆)", "", "not recorded"]
    assert all(bare_chip(text) for text in bare)
    assert not any(bare_chip(text) for text in marked)
    assert len(check_rendered([], [], "", {"bare_chips": bare + marked})) == len(bare)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_rendered_snapshot_excludes_part_and_layer_badges():
    script = """
const badge = (text, name) => ({textContent:text, classList:{contains:value => value === name}});
const chips = [
  {childNodes:[badge('ℍ₃', 'n3'), badge('make', 'a2-part-badge'), badge('L2', 'a2-layer-badge')]},
  {childNodes:[badge('Hour.make', 'plain'), badge('L2', 'a2-layer-badge')]},
  {childNodes:[badge('♣₅', 'n3'), badge('L3', 'a2-layer-badge')]}
].map(chip => ({...chip, closest: () => null, textContent: chip.childNodes.map(node => node.textContent).join('')}));
globalThis.document = {body: {innerText: ''}, querySelectorAll: selector => selector === '.a2-tok' ? chips : []};
globalThis.window = {N3: null};
globalThis.getComputedStyle = () => ({content: 'none'});
console.log(JSON.stringify(eval(process.argv[1]).violations.bare_chips));
"""
    result = subprocess.run([shutil.which("node"), "-e", script, SNAPSHOT], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    visible = json.loads(result.stdout)
    assert visible == ["ℍ₃", "Hour.make", "♣₅"]
    assert check_rendered([], [], "", {"bare_chips": visible}) == [
        "bare identifier chip[1]: 'Hour.make'",
    ]


def test_rendered_snapshot_rejects_each_supervisor_violation():
    violations = {"unindexed": ["♦"], "separators": ["𝕃₂::nil"],
                  "bare_chips": ["cons"], "right_superscripts": ["♦₆"]}
    findings = check_rendered([], [], "", violations)
    assert len(findings) == 4
    assert all(any(label in finding for finding in findings) for label in
               ("unindexed mark", "constructor separator", "bare identifier", "right superscript"))


def test_rendered_snapshot_rejects_legacy_separator_even_without_browser_metadata():
    assert any("constructor separator" in finding for finding in
               check_rendered([{"text": "𝕃₂::nil", "ascii": "\\bbL_2::nil"}], [], ""))


def test_built_site_notation3_contract(published_site):
    problems, count = check_static_site(published_site)
    assert not problems, "\n".join(problems[:80])
    source = json.loads((ROOT / "docs/assets/data/worlds_v2/integer.json").read_text(encoding="utf-8"))
    if "notation3" in source:
        assert count > 0


def test_rendered_gate_covers_nav_and_world_pages():
    urls = page_urls(ROOT)
    assert "/" in urls and "/worlds/" in urls
    assert any(url.startswith("/worlds/") and url != "/worlds/" for url in urls)


def test_rendered_gate_rejects_nullary_constructor_of_a_capitalised_form():
    from tools.site_gates.n3_roundtrip import check_rendered

    problems = check_rendered([], [], "", {"nullary_constants": ["𝔸₃()"]})
    assert problems == ["nullary constructor of a constant[0]: '𝔸₃()'"]
    assert check_rendered([], [], "", {"nullary_constants": []}) == []


def test_legend_glyph_family_must_tell_the_kind():
    from tools.site_gates.n3_roundtrip import family_problem

    assert family_problem({"mark": "\\dia_6", "kind": "operation"}) is None
    assert family_problem({"mark": "\\dia_07", "kind": "operation"}) is None
    assert family_problem({"mark": "(+)", "kind": "operation"}) is None
    assert family_problem({"mark": "\\bbK_4", "kind": "template", "produces": "object"}) is None
    assert family_problem({"mark": "\\hatY", "kind": "operation"}) == "observation glyph for a operation"
    assert family_problem({"mark": "\\bbA", "kind": "operation"}) == "object glyph for a operation"
    assert family_problem({"mark": "\\dia_1", "kind": "object"}) == "operation glyph for a object"


def test_every_published_legend_mark_family_tells_its_kind():
    from tools.notation3_export import DATA_JS, targets
    from tools.site_gates.n3_roundtrip import family_problem

    checked, problems = 0, []
    for path in targets():
        text = path.read_text(encoding="utf-8")
        if path == DATA_JS:
            block = json.JSONDecoder().raw_decode(text, text.index('"notation3":') + len('"notation3":'))[0]
        else:
            block = json.loads(text)["notation3"]
        for world, record in block["worlds"].items():
            for entry in record["legend"]:
                checked += 1
                problem = family_problem(entry)
                if problem:
                    problems.append((path.name, world, entry["name"], entry["kind"], entry["display"], problem))
    assert checked > 1000
    assert not problems, problems[:20]
