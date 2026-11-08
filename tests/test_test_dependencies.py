"""Every module a test file imports at module level is installed by `pip install -e '.[dev,site]'`.

CI installs exactly these extras, so a test module that imports anything else fails to collect
on a fresh runner. Optional integrations must use pytest.importorskip inside the test instead.
"""

import ast
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
# Import name -> distribution name, where they differ.
DISTRIBUTION = {"yaml": "pyyaml", "z3": "z3-solver", "bs4": "beautifulsoup4"}
# Packages that come with a declared distribution (mkdocs-material brings pymdownx, etc.).
PROVIDED_BY = {"pymdownx": "mkdocs-material", "material": "mkdocs-material", "_pytest": "pytest"}


def _declared():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = list(project["dependencies"])
    for extra in ("dev", "site"):
        requirements += project["optional-dependencies"][extra]
    return {re.split(r"[<>=!;\[ ]", item, maxsplit=1)[0].strip().lower() for item in requirements}


def _local_names():
    names = {"opulse", "tests", "conftest", "tools", "examples", "docs", "experiments"}
    for folder in (ROOT / "tests", ROOT / "tools", ROOT / "examples", ROOT / "experiments"):
        for path in folder.rglob("*.py"):
            names.add(path.stem)
        names.update(path.name for path in folder.rglob("*") if path.is_dir())
    return names


def _module_level_imports(tree):
    body = list(tree.body)
    while body:
        node = body.pop(0)
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]
        elif isinstance(node, ast.Try):
            # try/except ImportError fallbacks: the first branch that imports must be installed.
            body = list(node.body) + body
        elif isinstance(node, ast.If):
            body = list(node.body) + list(node.orelse) + body


def test_module_level_test_imports_are_installed_by_dev_and_site_extras():
    declared = _declared()
    local = _local_names()
    missing = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in _module_level_imports(tree):
            if name in sys.stdlib_module_names or name in local or name in {"tomli", "tomllib"}:
                continue
            distribution = PROVIDED_BY.get(name, DISTRIBUTION.get(name, name)).lower().replace("_", "-")
            if distribution not in declared:
                missing.append(f"{path.relative_to(ROOT)}: {name}")
    assert not missing, "test modules import packages not in [dev,site]:\n" + "\n".join(missing)


def test_site_extra_covers_the_site_build_and_its_tests():
    declared = _declared()
    assert {"mkdocs", "mkdocs-material", "mkdocstrings", "beautifulsoup4", "pygments"} <= declared
