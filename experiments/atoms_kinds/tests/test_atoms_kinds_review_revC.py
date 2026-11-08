"""Regression for incomplete open-kinds analysis input."""

import json
from pathlib import Path

from atoms_kinds.harness import analyze


def test_partial_episode_analysis_is_diagnostic():
    results = Path(__file__).resolve().parents[1] / "runs/dryrun_object/results.jsonl"
    rows = [json.loads(results.read_text(encoding="utf-8").splitlines()[0])]
    assert rows[0]["stage"] == 1
    analysis = analyze(rows, resamples=5)
    assert analysis["primary"]["decision"] == "diagnostic"
    assert analysis["episodes"][0]["stage2_accuracy"] is None
    assert set(analysis["episodes"][0]["reuse_per_kind"].values()) == {0.0}
