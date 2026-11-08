"""Challenge answers must not be committed with the public catalogue."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs/assets/data/challenge/v2.json"


def contains_challenge_answer(value: object, identifiers: set[str], mapped: bool = False) -> bool:
    if isinstance(value, dict):
        mapped = mapped or (isinstance(value.get("id"), str) and value["id"] in identifiers)
        if mapped and any(key.casefold() in {"reference", "answer"} for key in value):
            return True
        return any(
            contains_challenge_answer(item, identifiers, mapped or key in identifiers)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_challenge_answer(item, identifiers, mapped) for item in value)
    return False


def test_challenge_answer_detection() -> None:
    identifiers = {"world/compute/1"}
    assert contains_challenge_answer({"world/compute/1": {"reference": 12}}, identifiers)
    assert contains_challenge_answer({"tasks": [{"id": "world/compute/1", "grading": {"answer": 12}}]}, identifiers)
    assert not contains_challenge_answer({"different": {"reference": 12}}, identifiers)
    assert not contains_challenge_answer({"id": "world/compute/1", "answer_format": "value"}, identifiers)


def test_no_tracked_challenge_answers() -> None:
    catalogue = json.loads(CATALOGUE.read_text())
    identifiers = {
        task["id"]
        for ladder in catalogue["ladders"].values()
        for task in ladder
    }
    identifiers.update(task["id"] for task in catalogue["paths"]["six_kinds_one_world"]["steps"])
    assert identifiers
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "docs", "tools"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode().strip("\0").split("\0")
    for name in tracked:
        if name.endswith(".json") and (ROOT / name).is_file():
            assert not contains_challenge_answer(json.loads((ROOT / name).read_text()), identifiers), name
