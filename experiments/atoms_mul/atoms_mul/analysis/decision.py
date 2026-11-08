"""Shared preregistered episode eligibility, bootstrap and decision rules."""

import random
import statistics

SEED = 20261104


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def intervals(draws):
    return ([percentile(draws, 0.025), percentile(draws, 0.975)],
            [percentile(draws, 0.05), percentile(draws, 0.95)])


def bootstrap_difference(left, right, resamples):
    generator = random.Random(SEED)
    draws = []
    for _ in range(resamples):
        draws.append(sum(generator.choice(left) for _ in left) / len(left)
                     - sum(generator.choice(right) for _ in right) / len(right))
    ci95, ci90 = intervals(draws)
    return {"difference": statistics.mean(left) - statistics.mean(right),
            "ci95": ci95, "ci90": ci90, "n": [len(left), len(right)]}


def bootstrap_median_ratio(left, right, resamples, *, include_90=False):
    reference = statistics.median(right)
    if reference == 0:
        result = {"ratio": None, "ci95": None, "reason": "Reference median is zero"}
        if include_90:
            result["ci90"] = None
        return result
    generator = random.Random(SEED)
    draws = []
    for _ in range(resamples):
        numerator = statistics.median(generator.choice(left) for _ in left)
        denominator = statistics.median(generator.choice(right) for _ in right)
        if denominator == 0:
            result = {"ratio": statistics.median(left) / reference, "ci95": None,
                      "reason": "A bootstrap reference median is zero"}
            if include_90:
                result["ci90"] = None
            return result
        draws.append(numerator / denominator)
    ci95, ci90 = intervals(draws)
    result = {"ratio": statistics.median(left) / reference, "ci95": ci95}
    if include_90:
        result["ci90"] = ci90
    return result


def complete_ids(rows, expected, *, field="task_id"):
    """Require one result for each frozen ID; callers check other assignments."""
    return len(rows) == len(expected) and {row.get(field) for row in rows} == set(expected)


def require_complete(episodes, planned):
    """Only the exact preregistered episode indexes permit a primary decision."""
    identifiers = list(episodes)
    return len(identifiers) == planned and set(identifiers) == set(range(planned))


def difference_decision(primary, margin, *, positive, equivalent, strict_equivalence=False):
    if primary["ci95"][0] > 0 and primary["difference"] >= margin:
        return positive
    lower, upper = primary["ci90"]
    if ((lower > -margin and upper < margin) if strict_equivalence
            else (lower >= -margin and upper <= margin)):
        return equivalent
    return "inconclusive"


def ratio_decision(primary, margin, *, positive, equivalent):
    if primary["ci95"] is not None:
        if primary["ci95"][1] < 1 - margin:
            return positive
        if primary["ci90"][0] >= 1 - margin and primary["ci90"][1] <= 1 + margin:
            return equivalent
    return "inconclusive"
