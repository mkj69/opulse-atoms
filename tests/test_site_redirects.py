import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from mkdocs_hooks import redirect_routes, write_redirects


def test_each_legacy_page_has_a_redirect():
    config = json.loads((ROOT / "docs/assets/data/redirects.json").read_text(encoding="utf-8"))
    routes = redirect_routes()
    assert routes["spec/atoms-v2/"] == "reference/spec/"
    for source in config["paths"]:
        alias = Path(source)
        path = alias.parent if alias.name == "index.md" else alias.with_suffix("")
        assert routes[path.as_posix().strip("./") + "/"] == config["paths"][source]
    for source in ("challenge.md", "getting-started/quickstart.md",
                   "guide/notation.md", "guide/use-for-training.md", "guide/visual-tour.md", "reference/semantics.md"):
        assert not (ROOT / "docs" / source).exists()
        assert source in config["paths"]
    for source in (ROOT / "docs/api").rglob("*.md"):
        alias = source.relative_to(ROOT / "docs").with_suffix("")
        if alias.name == "index":
            alias = alias.parent
        assert routes[alias.as_posix() + "/"] == "reference/api/"


def test_all_retired_markdown_is_redirected():
    docs = ROOT / "docs"
    retired = ["about", "api", "blog", "getting-started", "guide", "lab", "stitching"]
    mapped = json.loads((docs / "assets/data/redirects.json").read_text(encoding="utf-8"))
    sources = set(mapped["paths"])
    for folder in retired:
        for page in (docs / folder).rglob("*.md"):
            assert page.relative_to(docs).as_posix() in sources or any(
                page.relative_to(docs).as_posix().startswith(prefix)
                for prefix in mapped["prefixes"]
            )


def test_redirect_pages_are_canonical_and_escaped(tmp_path):
    write_redirects(tmp_path, "https://mkj69.github.io/opulse-atoms/", {"why/": "research/"})
    html = (tmp_path / "why/index.html").read_text(encoding="utf-8")
    assert 'content="0; url=https://mkj69.github.io/opulse-atoms/research/"' in html
    assert '<link rel="canonical" href="https://mkj69.github.io/opulse-atoms/research/">' in html
    assert 'name="robots" content="noindex"' in html


def test_redirect_source_validation(monkeypatch, tmp_path):
    source = tmp_path / "redirects.json"
    source.write_text('{"paths":{"../bad.md":"research/"},"prefixes":{}}', encoding="utf-8")
    monkeypatch.setattr("mkdocs_hooks.REDIRECTS", source)
    with pytest.raises(ValueError, match="Invalid redirect source"):
        redirect_routes()


def test_redirect_targets_exist_in_complete_build(tmp_path):
    if not (ROOT / "docs/build/index.md").exists():
        pytest.skip("Build page is pending its owner; recheck after integration")
    from mkdocs.commands.build import build
    from mkdocs.config import load_config

    config = load_config(str(ROOT / "mkdocs.yml"))
    config.site_dir = str(tmp_path / "site")
    build(config)
    for old_url, target in redirect_routes().items():
        assert (tmp_path / "site" / old_url / "index.html").is_file()
        assert (tmp_path / "site" / target / "index.html").is_file()
