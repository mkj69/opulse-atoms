"""Regression coverage for dynamically indexed world pages and open-kind sets."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.mkdocs_hooks import on_files, world_detail_markdown

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
OPEN_KINDS = {
    "op_only": ["operation"],
    "obs_only": ["observation"],
    "comb_only": ["combinator"],
    "obj_op": ["object", "operation"],
    "comb_obs": ["combinator", "observation"],
    "obj_only": ["object"],
}


def fixture_docs(tmp_path, title='Quote: "A"', full=False):
    docs = tmp_path / "docs"
    if full:
        shutil.copytree(ROOT / "docs", docs, copy_function=os.symlink, symlinks=True)
    data = docs / "assets/data/worlds_v2"
    data.mkdir(parents=True, exist_ok=True)
    export = json.loads((ROOT / "docs/assets/data/worlds_v2/roads.json").read_text())
    export.update(world="op_only", title=title, open_kinds=["operation"])
    index = (data / "index.json")
    if index.exists():
        contents = json.loads(index.read_text())
        index.unlink()
    else:
        contents = {"schema": "opulse.world_v2_index/1", "worlds": []}
    contents["worlds"] = [{"world": "op_only", "file": "op_only.json", "title": title, "wave": 1}]
    export_file = data / "op_only.json"
    if export_file.exists():
        export_file.unlink()
    export_file.write_text(json.dumps(export), encoding="utf-8")
    index.write_text(json.dumps(contents), encoding="utf-8")
    return docs


def test_generated_page_build_and_existing_page_preserved(tmp_path):
    from mkdocs.commands.build import build
    from mkdocs.config import load_config
    from mkdocs.structure.files import Files

    docs = fixture_docs(tmp_path, full=True)
    config = load_config(str(ROOT / "mkdocs.yml"))
    config.docs_dir = str(docs)
    config.site_dir = str(tmp_path / "site")
    config.plugins._current_plugin = None
    generated = on_files(Files([]), config)
    assert [item.src_uri for item in generated] == ["worlds/op_only/index.md"]
    generated_page = next(iter(generated)).content_string
    assert generated_page.startswith('---\ntitle: "Quote: \\"A\\""')
    assert 'data-world="op_only"' in generated_page
    assert 'data-root="../../"' in generated_page
    assert generated_page.isascii()
    build(config)
    page = (tmp_path / "site/worlds/op_only/index.html").read_text(encoding="utf-8")
    assert 'data-world="op_only"' in page
    assert '<html lang="en"' in page
    assert 'worlds-v2.css' in page and 'catalog-ui.js' in page
    assert "Quote: &quot;A&quot;" in page or 'Quote: "A"' in page
    assert 'href: path(mount, "worlds/" + world.world + "/")' in (
        ROOT / "docs/assets/js/worlds/catalog-ui.js").read_text()
    assert (tmp_path / "site/worlds/index.html").is_file()

    existing = docs / "worlds/op_only/index.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# Existing page\n", encoding="utf-8")
    assert len(on_files(Files([]), config)) == 0


@pytest.mark.parametrize("world_id,title", [("../escape", "Good"), ("op_only", "Title outside ASCII: cafe\u00e9")])
def test_bad_world_metadata_fails_closed(tmp_path, world_id, title):
    from mkdocs.structure.files import Files

    docs = fixture_docs(tmp_path, title=title)
    data = docs / "assets/data/worlds_v2"
    index = json.loads((data / "index.json").read_text())
    index["worlds"][0]["world"] = world_id
    (data / "index.json").write_text(json.dumps(index))
    with pytest.raises(ValueError):
        on_files(Files([]), SimpleNamespace(docs_dir=str(docs), site_dir=str(tmp_path / "site"), use_directory_urls=True))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_open_kind_exact_sets_cover_six_new_worlds_and_preserve_contains():
    script = r"""
      const root = process.argv[1];
      const kinds = JSON.parse(process.argv[2]);
      require(root + '/docs/assets/js/atoms2/kit.js');
      require(root + '/docs/assets/js/atoms2/tower.js');
      const ui = require(root + '/docs/assets/js/worlds/catalog-ui.js');
      const worlds = Object.entries(kinds).map(([world, open_kinds]) =>
        ({world, title:world, open_kinds, wave:1, story:[]}));
      const result = Object.fromEntries(worlds.map(world => {
        const set = ui.openKindsSet(world);
        return [world.world, {set, label:ui.openKindsLabel(set),
          exact:ui.filterWorlds(worlds, {open_kinds_set:set}).map(item => item.world),
          contains:ui.filterWorlds(worlds, {open_kinds:world.open_kinds[0]}).map(item => item.world)}];
      }));
      console.log(JSON.stringify(result));
    """
    result = json.loads(subprocess.run([NODE, "-e", script, str(ROOT), json.dumps(OPEN_KINDS)],
                                       capture_output=True, text=True, check=True).stdout)
    assert result["op_only"]["set"] == "operation"
    assert result["op_only"]["label"] == "operation only"
    assert result["obj_op"]["label"] == "object + operation"
    assert result["op_only"]["exact"] == ["op_only"]
    assert result["obj_op"]["exact"] == ["obj_op"]
    assert result["obj_op"]["contains"] == ["obj_op", "obj_only"]
    assert result["comb_obs"]["exact"] == ["comb_obs"]
    assert result["comb_only"]["exact"] == ["comb_only"]
    assert result["obs_only"]["exact"] == ["obs_only"]
    assert result["obj_only"]["exact"] == ["obj_only"]


def test_title_escaping_and_open_kind_label():
    assert 'title: "Colon: \\"quote\\""' in world_detail_markdown("example", 'Colon: "quote"')
