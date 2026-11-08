"""Pre-registered episode-level analysis of multiplication experiment results."""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from .decision import (
    SEED,
    bootstrap_difference,
    bootstrap_median_ratio,
    complete_ids,
    difference_decision,
    require_complete,
)

MARGIN = 0.10
PLANNED_EPISODES = 40
STAGE_TASKS = {1: 24, 2: 16}
OUTCOMES = ("stage1_accuracy", "stage2_accuracy", "invention", "reuse",
            "total_length", "total_steps", "boundary_steps")


def episode_outcomes(records):
    """Aggregate task records into one observation per group and episode."""
    tracks = {record.get("track", "aml") for record in records}
    if len(tracks) > 1:
        raise ValueError("results contain more than one track")
    track = next(iter(tracks), "aml")
    if track not in ("aml", "machine"):
        raise ValueError(f"unknown analysis track: {track}")
    task_root = Path(__file__).resolve().parents[2] / "tasks"
    prefix = "machine_" if track == "machine" else ""
    frozen_ids = {
        stage: [task["id"] for task in json.loads(
            (task_root / f"{prefix}stage{stage}.json").read_text(encoding="utf-8"))["tasks"]]
        for stage in (1, 2)
    }
    episodes = defaultdict(list)
    seen = set()
    for record in records:
        key = (record["group"], record["episode"], record["stage"], record["task_id"])
        if key in seen:
            raise ValueError(f"Duplicate result: {key}")
        seen.add(key)
        episodes[key[:2]].append(record)

    result = {}
    for (group, episode), tasks in sorted(episodes.items()):
        stages = {stage: [task for task in tasks if task["stage"] == stage]
                  for stage in (1, 2)}
        valid = {stage: [task for task in stage_tasks if not task.get("api_error", False)]
                 for stage, stage_tasks in stages.items()}
        saved_names = set()
        length = 0
        for task in tasks:
            sizes = {item["name"]: item["size"] for item in task.get("defs_written", [])}
            length += task["length"] - sum(sizes[name] for name in sizes.keys() & saved_names)
            saved_names.update(task.get("saved", []))
        correct_stage2 = [task for task in valid[2] if task["correct"]]
        for task in correct_stage2:
            if task.get("steps") is None or task.get("boundary_steps") is None:
                raise ValueError("Correct stage-2 task has no step counts")
        result[(group, episode)] = {
            "group": group,
            "episode": episode,
            "api_errors": sum(bool(task.get("api_error", False)) for task in tasks),
            "stage1_accuracy": (sum(task["correct"] for task in valid[1]) / len(valid[1])
                                if valid[1] else None),
            "stage2_accuracy": (len(correct_stage2) / len(valid[2])
                                if all(complete_ids(stages[stage], frozen_ids[stage])
                                        for stage in (1, 2))
                                and len(stages[2]) - len(valid[2]) <= 2 else None),
            "invention": int(any(task.get("mul_equivalent") for task in tasks)),
            "reuse": (sum(bool(task.get("uses_library", False)) for task in stages[2])
                      / len(stages[2]) if stages[2] and group in ("A", "B") else None),
            "total_length": length,
            # Mean per correct stage-2 task, so that accuracy does not shrink the step count.
            "total_steps": (statistics.mean(task["steps"] for task in correct_stage2)
                            if correct_stage2 else None),
            "boundary_steps": (statistics.mean(task["boundary_steps"] for task in correct_stage2)
                               if correct_stage2 else None),
        }
    return list(result.values())


def analyze(records, resamples=10000):
    if resamples < 1:
        raise ValueError("resamples must be positive")
    episodes = episode_outcomes(records)
    groups = {group: [row for row in episodes if row["group"] == group]
              for group in ("A", "B", "C") if any(row["group"] == group for row in episodes)}
    summary = {
        group: {"episodes": len(rows), "primary_episodes": sum(
                    row["stage2_accuracy"] is not None for row in rows),
                "api_errors": sum(row["api_errors"] for row in rows),
                "means": {outcome: (statistics.mean(values) if values else None)
                          for outcome in OUTCOMES
                          for values in [[row[outcome] for row in rows if row[outcome] is not None]]},
                "medians": {outcome: (statistics.median(values) if values else None)
                            for outcome in ("total_length", "total_steps", "boundary_steps")
                            for values in [[row[outcome] for row in rows
                                            if row[outcome] is not None]]}}
        for group, rows in groups.items()
    }
    comparisons = {}
    for left_group, right_group in (("A", "B"), ("B", "C"), ("A", "C")):
        if left_group not in groups or right_group not in groups:
            continue
        pair = f"{left_group}-{right_group}"
        comparisons[pair] = {}
        for outcome in OUTCOMES:
            left = [row[outcome] for row in groups[left_group] if row[outcome] is not None]
            right = [row[outcome] for row in groups[right_group] if row[outcome] is not None]
            comparisons[pair][outcome] = (bootstrap_difference(left, right, resamples)
                                           if left and right else None)
    ratios = {}
    if "B" in groups and "C" in groups:
        for outcome in ("total_length", "total_steps", "boundary_steps"):
            left = [row[outcome] for row in groups["B"] if row[outcome] is not None]
            right = [row[outcome] for row in groups["C"] if row[outcome] is not None]
            ratios[outcome] = (bootstrap_median_ratio(left, right, resamples) if left and right
                               else {"ratio": None, "ci95": None, "reason": "No values"})

    primary = comparisons.get("B-C", {}).get("stage2_accuracy")
    eligible = {group: summary.get(group, {}).get("primary_episodes", 0)
                for group in ("B", "C")}
    if any(not require_complete((row["episode"] for row in groups.get(group, [])
                                 if row["stage2_accuracy"] is not None), PLANNED_EPISODES)
           for group in ("B", "C")):
        decision = "diagnostic"
        counts = set(eligible.values())
        if len(counts) == 1:
            comparison = "<" if eligible["B"] < PLANNED_EPISODES else "!="
            reason = (f"n={eligible['B']} eligible episodes per group {comparison} "
                      f"{PLANNED_EPISODES} pre-registered")
        else:
            reason = (f"B: {eligible['B']}, C: {eligible['C']} eligible episodes; "
                      f"need {PLANNED_EPISODES} per group pre-registered")
    else:
        decision = difference_decision(primary, MARGIN, positive="value", equivalent="no value")
        reason = {"value": "The 95% lower bound of B-C exceeds zero and the point estimate is at least 0.10.",
                  "no value": "The 90% CI for B-C lies entirely within [-0.10, 0.10].",
                  "inconclusive": "Neither the value nor the equivalence criterion is met; do not add episodes."}[decision]
    return {"episodes": episodes, "groups": summary, "comparisons": comparisons,
            "median_ratios_B_C": ratios, "decision": decision, "reason": reason,
            "resamples": resamples, "bootstrap_seed": SEED, "accuracy_margin": MARGIN,
            "relative_margin": MARGIN}


def render_markdown(result):
    def number(value):
        return "NA" if value is None else f"{value:.3f}"

    def interval(data, key):
        return "NA" if data is None else f"[{number(data[key][0])}, {number(data[key][1])}]"

    lines = ["# Multiplication experiment analysis", "",
             f"**Primary decision: {result['decision']}** - {result['reason']}", "",
             f"Bootstrap: {result['resamples']} within-group episode resamples; seed {SEED}.",
             ("API-error tasks are excluded from accuracy denominators and counted separately. "
              "An episode needs all 24 stage-1 and 16 stage-2 task records, with at most "
              "two stage-2 API errors; B and C each need 40 eligible episodes for a decision."),
             "", "## Groups", "",
             "| Group | Episodes | Primary eligible | API errors | Stage 1 | Stage 2 | Invention | Reuse | Length (median) | Steps (median) | Boundary (median) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for group, data in result["groups"].items():
        mean = data["means"]
        median = data["medians"]
        lines.append(f"| {group} | {data['episodes']} | {data['primary_episodes']} | {data['api_errors']} | "
                     f"{number(mean['stage1_accuracy'])} | {number(mean['stage2_accuracy'])} | "
                     f"{number(mean['invention'])} | {number(mean['reuse'])} | "
                     f"{number(median['total_length'])} | {number(median['total_steps'])} | "
                     f"{number(median['boundary_steps'])} |")
    lines += ["", "## Differences of episode means", "",
              "| Pair | Outcome | Difference | 95% CI | 90% CI |",
              "|---|---|---:|---|---|"]
    for pair, outcomes in result["comparisons"].items():
        for outcome, data in outcomes.items():
            lines.append(f"| {pair} | {outcome} | {number(data['difference'] if data else None)} | "
                         f"{interval(data, 'ci95')} | {interval(data, 'ci90')} |")
    lines += ["", "## B/C median ratios", "",
              "| Outcome | Ratio | 95% CI |", "|---|---:|---|"]
    for outcome, data in result["median_ratios_B_C"].items():
        ci = data["ci95"]
        lines.append(f"| {outcome} | {number(data['ratio'])} | "
                     f"{f'[{number(ci[0])}, {number(ci[1])}]' if ci else 'NA'} |")
    lines += ["", "A ratio below 1 favors B; the descriptive relative margin is 10%.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=10000)
    args = parser.parse_args(argv)
    with (args.run / "results.jsonl").open(encoding="utf-8") as source:
        records = [json.loads(line) for line in source if line.strip()]
    result = analyze(records, args.resamples)
    (args.run / "analysis.json").write_text(
        json.dumps(result, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.run / "analysis.md").write_text(render_markdown(result), encoding="utf-8")
    print(f"{result['decision']}: {result['reason']}")


if __name__ == "__main__":
    main()
