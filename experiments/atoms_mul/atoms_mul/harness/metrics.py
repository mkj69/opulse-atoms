"""Descriptive task and episode summaries (inference lives in analysis)."""

import statistics
from collections import defaultdict


def summarize(records, config):
    stages = defaultdict(list)
    episodes = defaultdict(list)
    for record in records:
        stages[(record["group"], record["stage"])].append(record)
        episodes[(record["group"], record["episode"])].append(record)

    def describe(rows):
        valid = [row for row in rows if not row.get("api_error", False)]
        correct = [row for row in valid if row["correct"]]
        step_rows = [row for row in correct if row["steps"] is not None]
        return {"accuracy": sum(row["correct"] for row in valid) / len(valid) if valid else None,
                "mean_attempts": statistics.mean(row["attempts"] for row in rows) if rows else None,
                "mean_length": statistics.mean(row["length"] for row in rows) if rows else None,
                "total_length": sum(row["length"] for row in rows),
                "mean_steps": statistics.mean(row["steps"] for row in step_rows) if step_rows else None,
                "episodes_with_mul_equivalent": len({row["episode"] for row in rows
                                                      if row["mul_equivalent"]}),
                "reuse_rate": sum(row["uses_library"] for row in rows) / len(rows) if rows else None}

    per_episode = []
    for (group, episode), rows in sorted(episodes.items()):
        for stage in (1, 2):
            subset = [row for row in rows if row["stage"] == stage]
            if subset:
                per_episode.append({"group": group, "episode": episode, "stage": stage,
                                    **describe(subset)})
    return {"config": config,
            "groups": {group: {str(stage): describe(stages[(group, stage)])
                               for stage in (1, 2)} for group in config["groups"]},
            "episodes": per_episode}
