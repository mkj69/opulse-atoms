"""Test file basenames are unique across every pytest testpath.

The test folders have no __init__.py files, so pytest's default "prepend" import mode imports
each test module under its bare basename. Two test files with the same basename make a
one-process run of the whole suite stop with "import file mismatch".
"""

from collections import defaultdict
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_test_module_basenames_are_unique_across_testpaths():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    testpaths = config["tool"]["pytest"]["ini_options"]["testpaths"]
    assert "tests" in testpaths
    seen = defaultdict(list)
    for folder in testpaths:
        for path in sorted((ROOT / folder).rglob("*.py")):
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                seen[path.name].append(path.relative_to(ROOT).as_posix())
    duplicates = {name: paths for name, paths in seen.items() if len(paths) > 1}
    assert not duplicates, duplicates
