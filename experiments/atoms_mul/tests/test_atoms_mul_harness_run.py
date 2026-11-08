"""Reproducibility and stored dry-run invariants."""

import json
from pathlib import Path

from atoms_mul.harness.run import run

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return [json.loads(line) for line in (ROOT / "runs" / name / "results.jsonl").read_text().splitlines()]


def test_deterministic_run(tmp_path):
    for directory in (tmp_path / "one", tmp_path / "two"):
        run(policy="inventor", groups=["B"], episodes=1, run_id="same", out=directory)
    for name in ("results.jsonl", "summary.json", "prompts.jsonl", "config.json"):
        assert (tmp_path / "one" / "same" / name).read_bytes() == (
            tmp_path / "two" / "same" / name).read_bytes()


def test_resume_reuses_finished_episodes(tmp_path):
    full = run(policy="inventor", groups=["B", "C"], episodes=1, run_id="full", out=tmp_path)
    partial = tmp_path / "part"
    run(policy="inventor", groups=["B"], episodes=1, run_id="part", out=tmp_path)
    # Rebuild the checkpoint of group B as an interrupted run would have left it.
    rows = [json.loads(line) for line in (partial / "results.jsonl").read_text().splitlines()]
    prompts = [json.loads(line) for line in (partial / "prompts.jsonl").read_text().splitlines()]
    for row in rows:
        row["run_id"] = "full2"
    (tmp_path / "full2").mkdir()
    config = json.loads((partial / "config.json").read_text())
    (tmp_path / "full2" / "episodes.jsonl").write_text(json.dumps({"config": config}) + "\n" + json.dumps(
        {"group": "B", "episode": 0, "records": rows, "prompts": prompts}) + "\n")
    resumed = run(policy="inventor", groups=["B", "C"], episodes=1, run_id="full2",
                  out=tmp_path, resume=True)
    assert (resumed / "results.jsonl").read_text().replace('"full2"', '"full"') == (
        full / "results.jsonl").read_text()
    assert not (resumed / "episodes.jsonl").exists()


def test_committed_dry_runs():
    inventor = load("dryrun_inventor")
    nosave = load("dryrun_nosave")
    unroll = load("dryrun_unroll")
    flaky = load("dryrun_flaky")
    for episode in (0, 1):
        variable = next(row for row in inventor if row["group"] == "B"
                        and row["episode"] == episode and row["family"] == "variable_scale")
        assert variable["mul_equivalent"]
    b2 = [row for row in inventor if row["group"] == "B" and row["stage"] == 2]
    a2 = [row for row in inventor if row["group"] == "A" and row["stage"] == 2]
    assert all(row["uses_library"] and row["boundary_steps"] < row["steps"]
               and row["correct"] for row in b2)
    assert all(row["correct"] for row in a2)
    assert not any(row["mul_equivalent"] for row in inventor if row["group"] == "A")
    # Saved definitions pass the atoms-v2 pipeline: the invented multiplication is promoted.
    mirrored = [item for row in inventor if row["group"] == "B" for item in row["core_library"]]
    assert mirrored and all(item["status"] == "promoted" and not item["problems"]
                            for item in mirrored)
    assert not any(row["core_library"] for row in inventor if row["group"] == "C")
    assert sum(row["steps"] for row in a2) < sum(row["steps"] for row in b2) / 3
    assert all(row["library_size_after"] == 0 and not row["saved"]
               for row in inventor if row["group"] == "C")
    assert sum(row["length"] for row in inventor if row["group"] == "B") < sum(
        row["length"] for row in nosave if row["group"] == "B")
    assert all(not row["correct"] for row in unroll if row["group"] in ("B", "C")
               and row["family"] == "variable_scale")
    assert all(row["correct"] and row["attempts"] == 3 and row["check_errors"] == 2
               for row in flaky)
