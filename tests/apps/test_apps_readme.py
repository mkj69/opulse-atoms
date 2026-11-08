"""The apps guide lives with the package (its old site page redirects) and names real API."""

import ast
import importlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "src/opulse/apps/README.md"


def code_blocks():
    return re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), flags=re.DOTALL)


def test_retired_site_page_redirects_and_the_guide_ships_with_the_package():
    assert not (ROOT / "docs/guide/use-for-training.md").exists()
    redirects = json.loads((ROOT / "docs/assets/data/redirects.json").read_text(encoding="utf-8"))
    assert "guide/use-for-training.md" in redirects["paths"]
    assert README.is_file()
    assert len(code_blocks()) >= 3


def test_every_opulse_name_the_guide_imports_exists():
    imported = []
    for block in code_blocks():
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.ImportFrom) and node.module.startswith("opulse"):
                imported += [(node.module, alias.name) for alias in node.names]
    assert imported
    missing = [f"{module}.{name}" for module, name in imported
               if not hasattr(importlib.import_module(module), name)]
    assert missing == []
