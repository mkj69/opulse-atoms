"""Repository folders must not shadow third-party packages when Python runs from the root."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Optional dependencies that opulse code imports lazily (apps exporters, integrations).
THIRD_PARTY = ("datasets", "pyarrow", "pandas", "lm_eval", "inspect_ai", "nnsight",
               "torch", "transformers", "verl", "trl")


def test_no_top_level_folder_is_named_like_an_optional_dependency():
    assert [name for name in THIRD_PARTY if (ROOT / name).is_dir()] == []


def test_optional_dependencies_resolve_to_real_packages_from_the_repository_root():
    # A namespace package (spec without origin) here is a repository folder, not the dependency,
    # and would make pytest.importorskip and the apps exporters accept a fake module.
    script = (
        "import importlib.util, json, sys\n"
        "specs = {name: importlib.util.find_spec(name) for name in sys.argv[1:]}\n"
        "print(json.dumps(sorted(name for name, spec in specs.items()\n"
        "                        if spec is not None and spec.origin in (None, 'namespace'))))\n"
    )
    result = subprocess.run([sys.executable, "-c", script, *THIRD_PARTY], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == []
