"""Every world export: a showcase marked answer_checked stores the answer that was checked (B5)."""

import json
from pathlib import Path

import pytest

EXPORTS = sorted((Path(__file__).resolve().parents[2] / "docs/assets/data/worlds_v2").glob("*.json"))


def _showcases(data):
    return data.get("showcase", []) if isinstance(data, dict) else []


def test_world_exports_exist():
    assert any(_showcases(json.loads(path.read_text(encoding="utf-8"))) for path in EXPORTS)


@pytest.mark.parametrize("path", EXPORTS, ids=[path.stem for path in EXPORTS])
def test_checked_showcases_store_their_answer(path):
    for case in _showcases(json.loads(path.read_text(encoding="utf-8"))):
        if case.get("answer_checked") is True:
            assert "answer" in case and case["answer"] not in (None, "", [], {}), (path.name, case.get("angle"))
