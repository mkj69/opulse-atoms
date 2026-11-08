"""The README dry-run commands must reproduce every committed artifact exactly."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("aml", "inventor", "A,B,C", 2),
    ("aml", "nosave", "B,C", 2),
    ("aml", "unroll", "A,B,C", 1),
    ("aml", "flaky", "B", 1),
    ("machine", "inventor", "A,B,C", 2),
    ("machine", "nosave", "B,C", 2),
    ("machine", "unroll", "A,B,C", 1),
    ("machine", "flaky", "B", 1),
)


@pytest.mark.parametrize("track,policy,groups,episodes", CASES)
def test_readme_dry_run_reproduces_committed_bytes(tmp_path, track, policy, groups, episodes):
    name = "dryrun_" + ("machine_" if track == "machine" else "") + policy
    destination = tmp_path / name
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
        (str(ROOT.parents[1] / "src"), str(ROOT)))}
    subprocess.run([sys.executable, "-m", "atoms_mul.harness.run", "--track", track,
                    "--policy", policy, "--groups", groups, "--episodes", str(episodes),
                    "--run-id", name, "--out", str(tmp_path)], check=True, env=environment)
    if policy == "inventor":
        subprocess.run([sys.executable, "-m", "atoms_mul.analysis.analyze", "--run",
                        str(destination)], check=True, capture_output=True, env=environment)
        cost = subprocess.run([sys.executable, "-m", "atoms_mul.analysis.cost", "--prompts",
                               str(destination / "prompts.jsonl"), "--episodes", "40"],
                              check=True, capture_output=True, env=environment).stdout
        (destination / "cost.txt").write_bytes(cost)
    committed = ROOT / "runs" / name
    assert {path.name for path in destination.iterdir()} == {
        path.name for path in committed.iterdir()}
    for path in committed.iterdir():
        assert (destination / path.name).read_bytes() == path.read_bytes(), path.name
