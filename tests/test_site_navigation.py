from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_instant_navigation_stays_off():
    # Instant navigation re-runs inline scripts on page swap and fails on the
    # JSON data blocks that the tour widgets embed, which leaves them unrendered.
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "navigation.instant" not in config


def test_site_identity_and_global_assets():
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "https://mkj69.github.io/opulse-atoms/" in config
    assert "https://github.com/mkj69/opulse-atoms" in config
    assert "Endless concepts. Every step proven." not in (ROOT / "docs/assets/css/custom.css").read_text()
    for retired in ("assets/js/atoms2/define.js", "assets/js/learn.js", "assets/js/challenge.js",
                    "assets/css/playground.css", "assets/css/learn.css"):
        assert f"  - {retired}" not in config


def test_shell_header_and_footer_have_direct_links():
    header = (ROOT / "overrides/partials/header.html").read_text(encoding="utf-8")
    footer = (ROOT / "overrides/partials/footer.html").read_text(encoding="utf-8")
    assert "lockup-light.svg" in header and "lockup-dark.svg" in header
    assert "releases/latest" not in header
    assert "Continue:" in footer and ">Contribute<" in footer and ">Cite<" in footer


def test_legacy_exclusions_do_not_hide_new_pages():
    from mkdocs.config import load_config

    exclusions = load_config(str(ROOT / "mkdocs.yml"))["exclude_docs"]
    for current in ("play/challenge.md", "reference/glossary.md", "research/experiments.md"):
        assert not exclusions.match_file(current)
    assert exclusions.match_file("glossary.md")
    for legacy in ("challenge.md", "getting-started/quickstart.md",
                   "guide/notation.md", "guide/visual-tour.md", "experiments.md",
                   "worlds/curation-report.md"):
        assert not (ROOT / "docs" / legacy).exists()
        assert not exclusions.match_file(legacy)


def test_seven_sticky_tabs_and_mobile_mark():
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "    - navigation.tabs.sticky" in config
    for tab in ("Home", "Learn", "Play", "Worlds", "Research", "Build", "Reference"):
        assert f"  - {tab}:" in config
    header = (ROOT / "overrides/partials/header.html").read_text(encoding="utf-8")
    assert "assets/images/mark.svg" in header
    assert "partials/tabs.html" in header


def test_atoms_v2_spec_is_nested_under_reference_tab():
    from mkdocs.config import load_config

    nav = load_config(str(ROOT / "mkdocs.yml"))["nav"]
    reference = next(entry["Reference"] for entry in nav if "Reference" in entry)
    assert any(entry.get("Atoms v2 specification") == "reference/spec.md" for entry in reference)
    assert (ROOT / "docs/spec/atoms-v2.md").is_file()
    assert '--8<-- "docs/spec/atoms-v2.md"' in (ROOT / "docs/reference/spec.md").read_text()


def test_legacy_runner_operation_modes_use_one_operation_colour():
    styles = (ROOT / "docs/assets/css/playground.css").read_text()
    for mode in ("simple", "branch", "recursive"):
        assert styles.count(f"--opg-{mode}: var(--a2-operation);") == 2


def test_grammar_copy_uses_record_status_and_scope():
    script = (ROOT / "docs/assets/js/atoms2/learn-kinds.js").read_text()
    assert '"Core status: " + row.status' in script
    assert 'row.evidence.method + " checks for " + row.name' in script
    assert 'unscopedRows.map(function (row) { return row.name; })' in script
    assert "promoted with bounded evidence" not in script
    assert "chart and parse_count with bounded checks" not in script
    assert "(../worlds/index.md)" in (ROOT / "docs/learn/kinds.md").read_text()
