"""The retired v1 legend is replaced by six ASCII kinds on live pages."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("Object", "Operation", "Combinator", "Observation", "Law", "Bridge")


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_six_kind_legend_uses_shared_ascii_renderer():
    kit = read("docs/assets/js/atoms2/kit.js")
    assert 'var KINDS6 = ["object", "operation", "combinator", "observation", "law", "bridge"]' in kit
    assert "KINDS6.map(function (kind) { return kindBadge(kind); })" in kit
    for spelling in ('Name<...>', 'name(...)', '@name[...]', '?name{...}', '#name', '~name'):
        assert spelling in kit
    for api in ("A2.KINDS6 = KINDS6", "A2.token = token", "A2.expr = expr"):
        assert api in kit
    config = read("mkdocs.yml")
    assert "  - assets/js/atoms2/kit.js" in config
    assert "  - assets/js/kinds-legend.js" not in config
    assert "  - assets/css/kinds-legend.css" not in config


def test_live_kind_pages_explain_every_kind_and_avoid_v1_symbols():
    learn = read("docs/learn/kinds.md")
    glossary = read("docs/reference/glossary.md")
    assert "# Six kinds" in learn
    assert 'data-a2-learn="kinds"' in learn
    assert 'src="../../assets/js/atoms2/learn-kinds.js"' in learn
    for kind in KINDS:
        assert f"| {kind} |" in glossary or f"| [{kind}](" in glossary
    # Notation v3: each of the six kinds has a round-trippable visible mark in the glossary.
    for spelling in ("𝔻₁(2, 4)", "a ♦₆ b", "Θ₁[♡₄₅] 3", "Ô₁⟨s⟩", "≡₁", "↝₁(m)"):
        assert spelling in glossary
    assert glossary.count('class="n3" data-n3-ascii=') >= 6
    for spelling in ("Frac<1, 2>", "cost(route)", "?top{body}", "#mul_comm", "~to_frac(x)"):
        assert spelling not in glossary
