"""Estimate API calls and tokens from a dry-run prompts.jsonl file."""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from .llm_policy import DEFAULT_MAX_OUTPUT_TOKENS


def estimate(records, episodes=40, groups=("A", "B", "C"), attempts_mean=1.5,
             max_output=DEFAULT_MAX_OUTPUT_TOKENS, price_in=None, price_out=None, output_mean=300):
    if episodes < 1 or not 1 <= attempts_mean <= 3 or max_output < 0:
        raise ValueError("episodes must be positive, attempts-mean within [1, 3], max-output nonnegative")
    if (price_in is None) != (price_out is None):
        raise ValueError("provide both input and output prices")
    if any(price is not None and price < 0 for price in (price_in, price_out)):
        raise ValueError("prices must be nonnegative")
    prompts = defaultdict(list)
    for record in records:
        if record["group"] in groups:
            key = (record["group"], record["stage"], record["task_id"])
            prompts[key].append(math.ceil(len(record["prompt"]) / 4))
    missing = set(groups) - {key[0] for key in prompts}
    if missing:
        raise ValueError(f"No prompts for groups: {', '.join(sorted(missing))}")
    expected_calls = episodes * len(prompts) * attempts_mean
    worst_calls = episodes * len(prompts) * 3
    expected_input = episodes * attempts_mean * sum(sum(values) / len(values)
                                                       for values in prompts.values())
    worst_input = episodes * 3 * sum(max(values) for values in prompts.values())
    result = {"tasks_per_episode": len(prompts), "expected_calls": expected_calls,
              "worst_calls": worst_calls, "expected_input_tokens": expected_input,
              "worst_input_tokens": worst_input,
              "expected_output_tokens": expected_calls * min(output_mean, max_output),
              "worst_output_tokens": worst_calls * max_output}
    if price_in is not None:
        result["expected_cost_usd"] = (expected_input * price_in +
                                       result["expected_output_tokens"] * price_out) / 1_000_000
        result["worst_cost_usd"] = (worst_input * price_in +
                                    result["worst_output_tokens"] * price_out) / 1_000_000
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=40)
    parser.add_argument("--groups", default="A,B,C")
    parser.add_argument("--attempts-mean", type=float, default=1.5)
    parser.add_argument("--price-in", type=float)
    parser.add_argument("--price-out", type=float)
    parser.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--output-mean", type=int, default=300,
                        help="expected output tokens per call (worst case uses --max-output)")
    args = parser.parse_args(argv)
    groups = tuple(group.strip() for group in args.groups.split(",") if group.strip())
    if not groups or len(set(groups)) != len(groups):
        parser.error("groups must be a nonempty comma-separated list of unique names")
    with args.prompts.open(encoding="utf-8") as source:
        records = [json.loads(line) for line in source if line.strip()]
    try:
        result = estimate(records, args.episodes, groups, args.attempts_mean,
                          args.max_output, args.price_in, args.price_out, args.output_mean)
    except ValueError as error:
        parser.error(str(error))
    print("Metric                  Expected       Worst case")
    for label, prefix in (("Calls", "calls"), ("Input tokens", "input_tokens"),
                          ("Output tokens", "output_tokens"), ("Cost (USD)", "cost_usd")):
        expected_key = f"expected_{prefix}"
        if expected_key in result:
            print(f"{label:<23} {result[expected_key]:>12,.2f}  {result[f'worst_{prefix}']:>12,.2f}")


if __name__ == "__main__":
    main()
