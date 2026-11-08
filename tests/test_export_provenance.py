"""Published exports must be independent of the repository's Git history."""

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exporters_do_not_stamp_git_revisions():
    sources = list((ROOT / "tools").glob("*.py"))
    sources += list((ROOT / "src").rglob("*.py"))
    for source in sources:
        if source.relative_to(ROOT).parts[:4] == ("src", "opulse", "worlds_real", "git"):
            continue
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"\bgit\b[^\n]{0,100}\b(?:log|rev-parse)\b", text), source
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            words = [item.value for item in node.elts if isinstance(item, ast.Constant)
                     and isinstance(item.value, str)]
            assert not ("git" in words and {"log", "rev-parse"}.intersection(words)), source


def test_committed_exports_have_no_commit_keys():
    paths = list((ROOT / "docs/assets/data/atoms2").glob("*.json"))
    paths.append(ROOT / "src/opulse/worlds_v2/computer2/data/mul_into.evidence.json")
    for path in paths:
        def check(value):
            if isinstance(value, dict):
                assert not {"core_commit", "kernel_commit", "commit"}.intersection(value), path
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        check(json.loads(path.read_text(encoding="utf-8")))

    assert '"commit"' not in (ROOT / "docs/assets/js/atoms2/data.js").read_text(encoding="utf-8")


def test_core_run_exporters_hash_every_tools_module_the_core_source_imports():
    tree = ast.parse((ROOT / "tools/atoms2_core_source.py").read_text(encoding="utf-8"))
    imported = {node.module.split(".", 1)[1] for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tools.")}
    assert "atoms2_parse_status" in imported
    for exporter in ("atoms2_grammar_export", "atoms2_roads_export", "atoms2_tower_export"):
        source = (ROOT / "tools" / f"{exporter}.py").read_text(encoding="utf-8")
        for module in imported:
            assert f'"tools/{module}.py"' in source, (exporter, module)
