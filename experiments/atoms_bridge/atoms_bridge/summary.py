"""Stage-2-only aggregation and preregistered primary contrast."""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from atoms_mul.analysis.decision import (
    bootstrap_difference,
    bootstrap_median_ratio,
    complete_ids,
    ratio_decision,
    require_complete,
)
from atoms_mul.harness.metrics import summarize as shared_summarize
from atoms_mul.kernel import parse_program as parse_integer
from atoms_mul.kernel import size as integer_size

from .bridge import INTEGER_MUL

FIXED_SOURCE_AML_LENGTH = integer_size(parse_integer(INTEGER_MUL).defs[0])
TASK_FILE = Path(__file__).resolve().parents[2] / "atoms_mul/tasks/machine_stage2.json"
FROZEN_TASK_IDS = frozenset(task["id"] for task in json.loads(TASK_FILE.read_text())["tasks"])


def bootstrap_length_ratio(left, right, resamples):
    """Bootstrap the ratio of episode medians with the shared seed and percentiles."""
    return bootstrap_median_ratio(left, right, resamples, include_90=True)


def summarize(records, config):
    """Retain shared summaries and report transfer-specific bridge usage."""
    result = shared_summarize(records, config)
    for group in config["groups"]:
        rows = [item for item in records if item["group"] == group and item["stage"] == 2]
        result["groups"][group]["2"]["bridge_use_rate"] = (
            sum(item["uses_library"] for item in rows) / len(rows) if rows else None)
        result["groups"][group]["2"]["fixed_source_aml_length"] = (
            FIXED_SOURCE_AML_LENGTH if group == "B" else 0)
    return result


def analyze(records, resamples=10000):
    """Compare G2-G1 with the shared seeded bootstrap; G3 is diagnostic."""
    if resamples < 1:
        raise ValueError("resamples must be positive")
    per_episode = defaultdict(list)
    for record in records:
        if record["stage"] != 2:
            raise ValueError("this bridge experiment measures stage 2 only")
        per_episode[(record["group"], record["episode"])].append(record)
    rates = defaultdict(dict)
    lengths = defaultdict(dict)
    bridge_rates = defaultdict(dict)
    steps = defaultdict(dict)
    for (group, episode), rows in sorted(per_episode.items()):
        task_ids = {row["task_id"] for row in rows}
        if not task_ids <= FROZEN_TASK_IDS:
            raise ValueError("episode contains a task outside the frozen task IDs")
        if not complete_ids(rows, FROZEN_TASK_IDS):
            continue
        valid = [row for row in rows if not row.get("api_error", False)]
        if len(rows) - len(valid) <= 2 and valid:
            rates[group][episode] = statistics.mean(row["correct"] for row in valid)
            lengths[group][episode] = sum(row["length"] for row in rows)
            bridge_rates[group][episode] = statistics.mean(bool(row.get("uses_library")) for row in rows)
            correct_steps = [row["steps"] for row in valid if row["correct"] and row.get("steps") is not None]
            if correct_steps:
                steps[group][episode] = statistics.mean(correct_steps)

    def contrast(data, left, right):
        return (bootstrap_difference(list(data[left].values()), list(data[right].values()), resamples)
                if data[left] and data[right] else None)

    primary = (bootstrap_length_ratio(list(lengths["B"].values()), list(lengths["A"].values()), resamples)
               if lengths["B"] and lengths["A"] else None)
    accuracy = contrast(rates, "B", "A")
    complete = all(require_complete(lengths[group], 40) for group in ("A", "B"))
    decision = (ratio_decision(primary, 0.10, positive="transfer saves effort",
                               equivalent="no saving") if complete else "diagnostic")
    return {"primary_G2_over_G1_length": primary, "decision": decision,
            "secondary_accuracy_G2_minus_G1": accuracy,
            "secondary_accuracy_noninferior": (accuracy["ci95"][0] >= -0.10
                                               if complete and accuracy else None),
            "secondary_bridge_use_rate": {group: statistics.mean(values.values()) if values else None
                                          for group, values in bridge_rates.items()},
            "secondary_layer0_steps": {group: statistics.mean(values.values()) if values else None
                                       for group, values in steps.items()},
            "G3_diagnostic": contrast(rates, "C", "B")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=10000)
    args = parser.parse_args(argv)
    records = [json.loads(row) for row in (args.run / "results.jsonl").read_text().splitlines()]
    output = analyze(records, args.resamples)
    (args.run / "analysis.json").write_text(json.dumps(output, indent=1, sort_keys=True) + "\n")
    return output


if __name__ == "__main__":
    main()
