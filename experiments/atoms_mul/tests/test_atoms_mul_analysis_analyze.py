import json
from pathlib import Path

import pytest
from atoms_mul.analysis.analyze import analyze, episode_outcomes, main, render_markdown

TASK_ROOT = Path(__file__).resolve().parents[1] / "tasks"
FROZEN_IDS = {stage: [task["id"] for task in json.loads(
    (TASK_ROOT / f"stage{stage}.json").read_text())["tasks"]] for stage in (1, 2)}


def record(group, episode, stage, task_id, correct=False, **overrides):
    result = {"group": group, "episode": episode, "stage": stage, "task_id": task_id,
              "correct": correct, "length": 2, "defs_written": [], "saved": [],
              "mul_equivalent": [], "uses_library": False,
              "steps": 8 if correct else None, "boundary_steps": 4 if correct else None}
    result.update(overrides)
    return result


def groups(episodes, b_correct, c_correct):
    return [record(group, episode, stage, task_id,
                   stage == 2 and task < correct_count)
            for group, correct_count in (("B", b_correct), ("C", c_correct))
            for episode in range(episodes) for stage, ids in FROZEN_IDS.items()
            for task, task_id in enumerate(ids)]


def test_value_decision_and_deterministic_bootstrap(tmp_path):
    records = groups(40, 12, 7)
    first = analyze(records, resamples=150)
    assert first == analyze(records, resamples=150)
    assert first["decision"] == "value"
    assert first["comparisons"]["B-C"]["stage2_accuracy"]["difference"] == 5 / 16
    assert "A-B" not in first["comparisons"]
    run = Path(tmp_path)
    (run / "results.jsonl").write_text("".join(json.dumps(item) + "\n" for item in records))
    main(["--run", str(run), "--resamples", "150"])
    assert json.loads((run / "analysis.json").read_text()) == first
    assert "Primary decision: value" in (run / "analysis.md").read_text()


def test_equivalent_and_inconclusive_decisions():
    assert analyze(groups(40, 8, 8), 100)["decision"] == "no value"
    assert analyze(groups(2, 0, 16), 100)["decision"] == "diagnostic"
    assert analyze([record("B", 0, 2, "dot", api_error=True)], 20)["decision"] == "diagnostic"


def test_api_errors_excluded_from_accuracy_but_counted():
    records = [record("B", 0, 1, "one", True),
               record("B", 0, 1, "two", api_error=True),
               record("B", 0, 2, "three", True, uses_library=True),
               record("B", 0, 2, "four", api_error=True)]
    outcome = episode_outcomes(records)[0]
    assert outcome["api_errors"] == 2
    assert outcome["stage1_accuracy"] == 1
    assert outcome["stage2_accuracy"] is None
    assert outcome["reuse"] == 0.5
    assert outcome["total_steps"] == 8
    assert outcome["boundary_steps"] == 4


def test_saved_definition_cost_is_charged_once():
    records = [record("B", 0, 1, "first", length=10,
                      defs_written=[{"name": "accumulate", "size": 10}], saved=["accumulate"],
                      mul_equivalent=["accumulate"]),
               record("B", 0, 2, "second", True, length=13,
                      defs_written=[{"name": "accumulate", "size": 10},
                                    {"name": "solve", "size": 3}], uses_library=True)]
    outcome = episode_outcomes(records)[0]
    assert outcome["total_length"] == 13
    assert outcome["invention"] == 1
    assert outcome["reuse"] == 1


def test_zero_reference_median_ratio_is_undefined():
    result = analyze(groups(2, 0, 0), 20)
    assert result["median_ratios_B_C"]["total_steps"]["ratio"] is None
    assert result["median_ratios_B_C"]["total_steps"]["ci95"] is None


def test_primary_eligibility_requires_all_tasks_and_at_most_two_stage2_api_errors():
    records = groups(1, 16, 16)
    assert all(row["stage2_accuracy"] == 1 for row in episode_outcomes(records))
    for removed in (next(row for row in records if row["stage"] == stage) for stage in (1, 2)):
        remaining = [row for row in records if row is not removed]
        assert episode_outcomes(remaining)[0]["stage2_accuracy"] is None
    stage2 = [row for row in records if row["group"] == "B" and row["stage"] == 2]
    for task in stage2[:2]:
        task["api_error"] = True
    assert episode_outcomes(records)[0]["stage2_accuracy"] == 1
    stage2[2]["api_error"] = True
    assert episode_outcomes(records)[0]["stage2_accuracy"] is None


def test_primary_decision_requires_forty_eligible_in_each_group():
    records = groups(40, 16, 0)
    first_b = next(row for row in records if row["group"] == "B" and row["episode"] == 0)
    result = analyze([row for row in records if row is not first_b], 100)
    assert result["decision"] == "diagnostic"
    assert result["groups"]["B"]["primary_episodes"] == 39
    assert result["groups"]["C"]["primary_episodes"] == 40


@pytest.mark.parametrize("run_name", ["dryrun_inventor", "dryrun_machine_inventor"])
def test_committed_analysis_replays_byte_identically(run_name):
    run = Path(__file__).resolve().parents[1] / "runs" / run_name
    records = [json.loads(line) for line in (run / "results.jsonl").read_text().splitlines()]
    resamples = json.loads((run / "analysis.json").read_text())["resamples"]
    result = analyze(records, resamples)
    assert json.dumps(result, sort_keys=True, indent=1, ensure_ascii=False) + "\n" == (
        run / "analysis.json").read_text()
    assert render_markdown(result) == (run / "analysis.md").read_text()


def test_unknown_analysis_track_is_rejected():
    with pytest.raises(ValueError, match="unknown analysis track"):
        episode_outcomes([{"track": "unknown"}])
