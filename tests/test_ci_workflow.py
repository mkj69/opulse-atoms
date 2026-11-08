"""CI installs Opulse the way the library is meant to run: editable, from the checkout."""

import os
import re
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _steps(workflow, job):
    data = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    return data["jobs"][job]["steps"]


def test_ci_installs_editable_with_dev_and_site_extras():
    runs = [step.get("run", "") for step in _steps("ci.yml", "test")]
    installs = [run for run in runs if "pip install" in run]
    assert installs == ["python -m pip install -e '.[dev,site]'"]
    assert any(run.startswith("python -m pytest") for run in runs)
    assert not any("PYTHONPATH" in run for run in runs)


def test_ci_builds_the_site_with_strict_checks():
    runs = [step.get("run", "") for step in _steps("ci.yml", "test")]
    assert 'python -m mkdocs build --strict -f mkdocs.yml -d "$RUNNER_TEMP/site"' in runs
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "python -m mkdocs build --strict -f mkdocs.yml" in contributing
    assert "build_site_local.sh" not in contributing


def test_contributing_says_pypi_publishing_is_not_set_up():
    text = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    assert "PyPI publishing is not set up" in text and "no `v*` tag is created" in text


def test_release_tests_use_the_same_editable_install():
    runs = [step.get("run", "") for step in _steps("release.yml", "build")]
    assert any(run.startswith("python -m pip install -e '.[dev,site]'") for run in runs)


def test_contributing_documents_the_source_checkout_install():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert 'pip install -e ".[dev,site]"' in text
    assert "runs from a source checkout" in text


@pytest.mark.parametrize(("workflow", "job"), [("ci.yml", "test"), ("release.yml", "build")])
def test_workflows_set_up_node_for_the_page_script_tests(workflow, job):
    uses = [step.get("uses", "") for step in _steps(workflow, job)]
    assert any(item.startswith("actions/setup-node@") for item in uses)


def test_tests_find_node_on_path_not_at_a_machine_path():
    hard_coded = re.compile(r"[\"']/[^\"']*/bin/node[\"']")
    offenders = [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "tests").rglob("*.py"))
                 if hard_coded.search(path.read_text(encoding="utf-8"))]
    assert not offenders


@pytest.mark.skipif(not os.environ.get("CI"), reason="only CI must provide Node.js")
def test_ci_provides_node_so_node_tests_do_not_skip():
    assert os.environ.get("OPULSE_NODE") or shutil.which("node")


def test_pages_come_from_the_gh_pages_branch_not_a_workflow():
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "deploy-pages" not in text and "gh-deploy" not in text, path.name
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "from the `gh-pages` branch" in contributing
    assert "mkdocs build --strict" in contributing
    build = (ROOT / "tools/build_site.sh").read_text(encoding="utf-8")
    assert "mkdocs build --strict" in build and "touch site/.nojekyll" in build


def test_ci_runs_the_python_version_the_committed_digests_were_made_with():
    data = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert data["jobs"]["test"]["strategy"]["matrix"]["python-version"] == ["3.10"]
    release = [step.get("with", {}).get("python-version") for step in _steps("release.yml", "build")]
    assert "3.10" in release
    for name in ("README.md", "CONTRIBUTING.md"):
        assert "pass only on Python 3.10" in " ".join((ROOT / name).read_text(encoding="utf-8").split())
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        import tomli as tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.10,<3.11"
    assert not [item for item in project["classifiers"] if item.startswith("Programming Language :: Python :: 3.1")
                and item != "Programming Language :: Python :: 3.10"]
