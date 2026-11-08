"""MkDocs hooks: make the ``opulse`` Pygments lexer available to code blocks.

An installed Opulse registers the lexer through its ``pygments.lexers`` entry point.
The documentation is often built from a source checkout instead, so this hook puts
``src/`` on the path and registers the lexer before any page is rendered.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from html import escape
from pathlib import Path
from shutil import copyfile

# MkDocs loads this hook by file path, so the repository root is not always importable.
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.export_digest import inputs_sha256

SRC = Path(__file__).resolve().parents[1] / "src"
ROOT = SRC.parent
REDIRECTS = ROOT / "docs" / "assets" / "data" / "redirects.json"
SPEC = ROOT / "docs" / "spec" / "atoms-v2.md"


def current_spec_version():
    match = re.search(r"^Spec version: `(atoms-v2/[0-9.]+)`", SPEC.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError("Missing atoms-v2 spec version")
    return match.group(1)


def current_core_digest():
    return inputs_sha256(ROOT, (ROOT / "src/opulse/atoms").glob("*.py"))[:12]


def on_page_markdown(markdown, page, config, files):
    if Path(config.docs_dir).resolve() != ROOT / "docs":
        return markdown
    source = page.file.src_uri
    if source == "reference/glossary.md":
        markdown = markdown.replace(
            "{{ A2_GLOSSARY_COMPARISON }}",
            glossary_volume_comparison(ROOT / "docs/assets/data/worlds_v2/shadows.json"),
        )
    if source in {"reference/index.md", "reference/api.md", "reference/provenance.md"}:
        markdown = markdown.replace("{{ A2_SPEC_VERSION }}", current_spec_version())
    if source == "reference/provenance.md":
        markdown = markdown.replace("{{ A2_CORE_DIGEST }}", current_core_digest())
    if source == "build/index.md":
        markdown = markdown.replace("{{ A2_CORE_DIGEST }}", current_core_digest())
    return markdown


def glossary_volume_pair():
    from opulse.atoms.values import Card
    from opulse.worlds_v2.shadows.deep_hosts import front, to_card, top

    first = to_card(((1, 2, 0), (4, 5, 1)))
    second = to_card(((1, 2, 3), (4, 5, 1)))
    if not (isinstance(first, Card) and isinstance(second, Card)
            and first.sort == second.sort == "Volume" and first != second
            and top(first) == top(second) and front(first) != front(second)):
        raise ValueError("shadows world code failed to construct the glossary observation pair")
    return first, second


def glossary_volume_comparison(path):
    export = json.loads(Path(path).read_text(encoding="utf-8"))
    if export.get("world") != "shadows" or export.get("version") != 1:
        raise ValueError("glossary needs the shadows world version 1 export")
    probes = export["decl"]["observation"]["capabilities"]["learner"]["probes"]
    if not ("top" in probes and "side" in probes and "front" not in probes):
        raise ValueError("shadows learner probes changed; revise the glossary comparison")
    from opulse.worlds_v2.shadows.deep_hosts import front, top
    first, second = glossary_volume_pair()
    output = (f"same full state: {first == second}\n"
              f"same top view: {top(first) == top(second)}\n"
              f"same front view: {front(first) == front(second)}")
    return f"""<span class="ar-badge ar-badge-executable">Executable</span>

The [shadows world export](../assets/data/worlds_v2/shadows.json), version 1, grants the `top` and `side` probes. Two distinct volumes built with its host constructors have the same top projection. Run this from the repository root with `PYTHONPATH=src`:

```python
from opulse.worlds_v2.shadows.deep_hosts import front, to_card, top

first = to_card(((1, 2, 0), (4, 5, 1)))
second = to_card(((1, 2, 3), (4, 5, 1)))
print("same full state:", first == second)
print("same top view:", top(first) == top(second))
print("same front view:", front(first) == front(second))
```

Output, computed at build time from the host functions:

```text
{output}
```

The export grants learners `top` and `side`, not `front`; the front comparison is an external check, not a learner action. A learner reading only `?top{{body}}` cannot distinguish this pair. The judge view is full state, so a matching observation does not establish equality. This is a host-level computation on constructed values, **not** a kernel verification record. The export has no sealed object pair: `Volume` is given and unsealed. [Observation rules](index.md#evaluation-and-accounting) explain the boundary between probes and truth."""


def redirect_routes():
    """Return the old published URLs and their new page URLs."""
    data = json.loads(REDIRECTS.read_text(encoding="utf-8"))
    sources = dict(data["paths"])
    for prefix, target in data["prefixes"].items():
        for page in (ROOT / "docs" / prefix).rglob("*.md"):
            sources[page.relative_to(ROOT / "docs").as_posix()] = target
    routes = {}
    for source, target in sources.items():
        page = Path(source)
        if page.suffix != ".md" or page.is_absolute() or ".." in page.parts:
            raise ValueError(f"Invalid redirect source: {source}")
        alias = page.parent if page.name == "index.md" else page.with_suffix("")
        old_url = alias.as_posix().strip("./") + "/"
        if old_url == target:
            raise ValueError(f"Redirect points to itself: {source}")
        if old_url in routes and routes[old_url] != target:
            raise ValueError(f"Conflicting redirect: {source}")
        routes[old_url] = target
    return routes


def write_redirects(site_dir, site_url, routes):
    """Replace legacy output with small same-site redirect pages."""
    site_dir = Path(site_dir)
    for old_url, new_url in routes.items():
        target = site_url.rstrip("/") + "/" + new_url.lstrip("/")
        safe_target = escape(target, quote=True)
        output = site_dir / old_url / "index.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0; url={safe_target}">'
            f'<link rel="canonical" href="{safe_target}">'
            '<meta name="robots" content="noindex"></head><body>'
            f'<p>This page moved to <a href="{safe_target}">{safe_target}</a>.</p>'
            '</body></html>\n', encoding="utf-8")


def legacy_ascii(value):
    from opulse.atoms.notation import legacy_symbol_to_ascii
    from opulse.notation3 import ALLOWED_DISPLAY_CHARS

    if isinstance(value, dict):
        return {legacy_ascii(key): legacy_ascii(item) for key, item in value.items()}
    if isinstance(value, list):
        return [legacy_ascii(item) for item in value]
    if not isinstance(value, str):
        return value

    def alias(match):
        symbol = match.group()
        try:
            return legacy_symbol_to_ascii(symbol)
        except ValueError:
            return "".join(f"v1_u{ord(char):04X}_" for char in symbol)

    value = re.sub(r"[^\x00-\x7f][₀-₉]+", alias, value)
    return "".join(char if char.isascii() or char in ALLOWED_DISPLAY_CHARS
                   else f"v1_u{ord(char):04X}_" for char in value)


def replace_material_glyphs(contents):
    from opulse.notation3 import ALLOWED_DISPLAY_CHARS

    for glyph, ascii_key in (("◆", ""), ("⊞", "Win"), ("↓", "down"), ("←", "left"),
                             ("→", "right"), ("↑", "up")):
        if glyph not in ALLOWED_DISPLAY_CHARS:
            contents = contents.replace(f'content:"{glyph}"', f'content:"{ascii_key}"')
    return contents


def on_config(config):
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from opulse.display.pygments_lexer import register

    register()
    return config


def world_detail_markdown(world_id, title):
    """Render the shared detail-page shell for an indexed world without a page."""
    if not title.isascii():
        raise ValueError(f"Non-ASCII English world title for {world_id}")
    safe_title = json.dumps(title, ensure_ascii=True)
    return f'''---
title: {safe_title}
hide:
  - navigation
  - toc
---

<link rel="stylesheet" href="../../assets/css/worlds-v2.css">

<div class="w2-page" data-worlds-v2 data-world="{world_id}" data-root="../../" aria-live="polite">
Loading the versioned {world_id} world export...
</div>

<script defer src="../../assets/js/atoms2/tower.js"></script>
<script defer src="../../assets/js/worlds/catalog-ui.js"></script>
'''


def on_files(files, config):
    from mkdocs.structure.files import File

    docs_dir = Path(config.docs_dir)
    if not (docs_dir / "assets/data/worlds_v2/index.json").exists():
        return files
    index = json.loads((docs_dir / "assets/data/worlds_v2/index.json").read_text(encoding="utf-8"))
    known = {file.src_uri for file in files}
    for entry in index["worlds"]:
        world_id = entry["world"]
        if not isinstance(world_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", world_id):
            raise ValueError(f"Invalid world id: {world_id!r}")
        page_uri = f"worlds/{world_id}/index.md"
        if page_uri in known or (docs_dir / page_uri).exists():
            continue
        export_file = docs_dir / "assets/data/worlds_v2" / f"{world_id}.json"
        if entry.get("file") != export_file.name:
            raise ValueError(f"Invalid world export filename for {world_id}")
        export = json.loads(export_file.read_text(encoding="utf-8"))
        if export.get("world") != world_id or not isinstance(export.get("title"), str):
            raise ValueError(f"Invalid world export for {world_id}")
        files.append(File.generated(config, page_uri,
                                    content=world_detail_markdown(world_id, export["title"])))
        known.add(page_uri)
    return files


def fill_action_provenance(site_dir):
    site_dir = Path(site_dir)
    action_export = site_dir / "assets/data/worlds_v2/action.json"
    action_data = json.loads(action_export.read_text(encoding="utf-8"))
    replacements = {
        "{{ A2_ACTION_EXPORT_SHA256 }}": hashlib.sha256(action_export.read_bytes()).hexdigest(),
        "{{ A2_ACTION_LOCK_WORLD_HASH }}": action_data["decl"]["lock"]["world_hash"],
    }
    for path in (site_dir / "reference/provenance/index.html",
                 site_dir / "research/action-audit-v1.json"):
        contents = path.read_text(encoding="utf-8")
        for placeholder, value in replacements.items():
            if placeholder not in contents:
                raise ValueError(f"Missing provenance placeholder {placeholder} in {path}")
            contents = contents.replace(placeholder, value)
        path.write_text(contents, encoding="utf-8")


def on_post_build(config):
    """Localize the Chinese site; strip Chinese data and redirect old English pages."""
    if Path(config.docs_dir).resolve() == ROOT / "docs_zh":
        localized = ROOT / "docs_zh" / "snippets" / "localized_assets"
        site_assets = Path(config.site_dir) / "assets"
        for source in localized.rglob("*"):
            if source.is_file():
                copyfile(source, site_assets / source.relative_to(localized))
        return

    if (Path(config.config_file_path).resolve() != ROOT / "mkdocs.yml"
            or config.theme["language"] != "en"
            or config.get("extra", {}).get("translated_paths")):
        return

    def english_only(value):
        if isinstance(value, dict):
            return {key: english_only(item) for key, item in value.items()
                    if key != "zh" and not key.endswith("_zh")}
        if isinstance(value, list):
            return [english_only(item) for item in value]
        return value

    for path in (Path(config.site_dir) / "assets" / "data").rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        relative = path.relative_to(Path(config.site_dir) / "assets" / "data")
        if (relative.parent == Path("worlds") or relative == Path("challenge/induce.json")):
            data = legacy_ascii(english_only(data))
        else:
            data = english_only(data)
        path.write_text(json.dumps(data, ensure_ascii=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
    for path in (Path(config.site_dir) / "assets" / "stylesheets").glob("main.*.min.css"):
        contents = replace_material_glyphs(path.read_text(encoding="utf-8"))
        path.write_text(contents, encoding="utf-8")
    (Path(config.site_dir) / "assets/javascripts/lunr/min/lunr.el.min.js").unlink(missing_ok=True)
    fill_action_provenance(config.site_dir)
    write_redirects(config.site_dir, config.site_url, redirect_routes())
