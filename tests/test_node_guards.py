"""Tests that run Node.js skip when Node.js is missing instead of erroring.

README.md says the page-script tests need Node.js on PATH and are skipped without it. A test
that starts node (through a module-level ``NODE = shutil.which("node")`` value, a helper in
NODE_HELPERS or a literal ``["node", ...]`` command), directly or through a fixture in the same
file, must carry a skip marker that mentions node, use ``skipif``, or call ``pytest.skip``.
"""

import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
# Repository helpers that start node themselves: tests/_node() and the challenge walk generator.
NODE_HELPERS = {"_node", "generate_walk"}


def _test_files():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for folder in config["tool"]["pytest"]["ini_options"]["testpaths"]:
        yield from sorted((ROOT / folder).rglob("test_*.py"))


def _segment(source, node):
    return ast.get_source_segment(source, node) or ""


def _node_variables(tree, source):
    names = set()
    for item in tree.body:
        if isinstance(item, ast.Assign):
            value = _segment(source, item.value)
            if ("which(" in value and '"node"' in value) or "OPULSE_NODE" in value:
                names |= {target.id for target in item.targets if isinstance(target, ast.Name)}
    return names


def _starts_node(function, variables):
    for item in ast.walk(function):
        if isinstance(item, ast.Name) and item.id in variables:
            return True
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id in NODE_HELPERS:
            return True
        if (isinstance(item, ast.List) and item.elts and isinstance(item.elts[0], ast.Constant)
                and item.elts[0].value == "node"):
            return True
    return False


def _guarded(function, source):
    for decorator in function.decorator_list:
        text = _segment(source, decorator)
        if "node" in text.lower() or "skipif" in text:
            return True
    for item in ast.walk(function):
        if isinstance(item, ast.Call) and _segment(source, item.func) in {"pytest.skip", "_node"}:
            return True
    return False


def _module_guarded(tree, source):
    for item in tree.body:
        if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "pytestmark"
                                                for target in item.targets):
            if "node" in _segment(source, item.value).lower():
                return True
    return False


def test_every_node_test_skips_without_node():
    offenders = []
    for path in _test_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        if _module_guarded(tree, source):
            continue
        variables = _node_variables(tree, source)
        functions = [item for item in tree.body if isinstance(item, ast.FunctionDef)]
        fixtures = {item.name: item for item in functions
                    if any("fixture" in _segment(source, decorator) for decorator in item.decorator_list)}
        risky = {name for name, item in fixtures.items()
                 if _starts_node(item, variables) and not _guarded(item, source)}
        grown = True
        while grown:
            grown = False
            for name, item in fixtures.items():
                if (name not in risky and not _guarded(item, source)
                        and {argument.arg for argument in item.args.args} & risky):
                    risky.add(name)
                    grown = True
        for item in functions:
            if not item.name.startswith("test_") or _guarded(item, source):
                continue
            if _starts_node(item, variables) or {argument.arg for argument in item.args.args} & risky:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}::{item.name}")
    assert not offenders, "node tests without a skip guard:\n" + "\n".join(offenders)
