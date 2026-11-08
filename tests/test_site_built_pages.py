"""The built English site never ships a stringified object (review round 25 G1)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_built_page_contains_an_object_placeholder(tmp_path):
    from mkdocs.commands.build import build
    from mkdocs.config import load_config

    config = load_config(str(ROOT / "mkdocs.yml"))
    config.site_dir = str(tmp_path / "site")
    build(config)
    pages = sorted((tmp_path / "site").rglob("*.html"))
    assert len(pages) > 20
    offenders = [str(page.relative_to(tmp_path / "site")) for page in pages
                 if "[object Object]" in page.read_text(encoding="utf-8", errors="replace")]
    assert offenders == []
