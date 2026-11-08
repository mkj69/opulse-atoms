import json
import os
import tempfile
from pathlib import Path

import pytest

from opulse.core import OperatorRegistry
from opulse.core.starting_sets import export_starting_set
from opulse.tasks_v2.challenge_grade import build_grading, verify_grading

ROOT = Path(__file__).resolve().parents[1]
requires_zh_site = pytest.mark.skipif(
    not (ROOT / "docs_zh").is_dir(), reason="Chinese site docs_zh/ is absent from the public export"
)
_starting_dir = tempfile.TemporaryDirectory(prefix="opulse-test-atoms-")
INITIAL_OPERATORS = Path(_starting_dir.name) / "initial_operators.jsonl"
export_starting_set("integer", INITIAL_OPERATORS)
export_starting_set("atomic", INITIAL_OPERATORS.parent / "atomic_operators.jsonl")
LEGACY_OPERATORS_1K = Path(os.environ["OPULSE_LEGACY_OPERATORS_1K"]) if "OPULSE_LEGACY_OPERATORS_1K" in os.environ else None


@pytest.fixture
def registry() -> OperatorRegistry:
    return OperatorRegistry.from_jsonl(INITIAL_OPERATORS)


@pytest.fixture(scope="session")
def operators(tmp_path_factory) -> Path:
    """A small generated operator set (three layers), built once per test session."""
    from opulse.cli.main import main

    path = tmp_path_factory.mktemp("operators") / "ops.jsonl"
    assert main(["operators", "--out", str(path), "--layers", "20", "10", "6", "--seed", "3"]) == 0
    return path


@pytest.fixture(scope="session")
def challenge_grading_path(tmp_path_factory) -> Path:
    """A private grading file built once per session in a temporary directory."""
    path = tmp_path_factory.mktemp("challenge_v2") / "grading.json"
    assert verify_grading(build_grading(path))
    return path


@pytest.fixture(scope="session")
def challenge_grading(challenge_grading_path):
    """The private grading records; tests that request this see OPULSE_CHALLENGE_GRADING set."""
    return json.loads(challenge_grading_path.read_bytes())


@pytest.fixture(autouse=True)
def _challenge_grading_environment(request):
    """Point OPULSE_CHALLENGE_GRADING at the session file only while a test that requests it runs.

    A session-wide assignment would leak into later tests and their subprocesses, so
    ``challenge_grade --build`` would write somewhere other than build/challenge_v2/.
    This fixture is autouse so that Hypothesis tests can still request the session data.
    """
    if "challenge_grading" not in request.fixturenames:
        yield
        return
    path = request.getfixturevalue("challenge_grading_path")
    monkeypatch = request.getfixturevalue("monkeypatch")
    monkeypatch.setenv("OPULSE_CHALLENGE_GRADING", str(path))
    yield
