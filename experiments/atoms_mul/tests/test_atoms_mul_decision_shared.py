"""Regression tests for the analysis rules shared by the three experiments."""

import pytest
from atoms_mul.analysis.decision import (
    bootstrap_difference,
    bootstrap_median_ratio,
    complete_ids,
    difference_decision,
    intervals,
    percentile,
    ratio_decision,
    require_complete,
)
from hypothesis import given
from hypothesis import strategies as st


def test_percentile_and_intervals_interpolate_sorted_samples():
    assert percentile([4, 0], 0.25) == 1
    assert intervals([0, 4]) == ([0.1, 3.9], [0.2, 3.8])


def test_bootstrap_difference_has_frozen_shape_and_seed():
    sample = bootstrap_difference([1, 2], [0, 0], 20)
    assert sample == bootstrap_difference([1, 2], [0, 0], 20)
    assert sample["difference"] == 1.5
    assert sample["n"] == [2, 2]
    assert sample["ci90"][0] <= sample["ci95"][0]


def test_bootstrap_ratio_preserves_optional_interval_and_zero_reference():
    assert bootstrap_median_ratio([2], [1], 8) == {"ratio": 2, "ci95": [2, 2]}
    assert bootstrap_median_ratio([2], [1], 8, include_90=True)["ci90"] == [2, 2]
    assert bootstrap_median_ratio([2], [0], 8, include_90=True)["ci90"] is None
    assert bootstrap_median_ratio([2], [0, 1], 8)["reason"] == (
        "A bootstrap reference median is zero")


@given(st.permutations([0, 1, 2]))
def test_complete_ids_ignores_order_but_not_repeated_or_foreign_ids(order):
    records = [{"item_id": index} for index in order]
    assert complete_ids(records, range(3), field="item_id")
    assert not complete_ids(records[:-1] + [records[0]], range(3), field="item_id")
    assert not complete_ids(records[:-1] + [{"item_id": 3}], range(3), field="item_id")


@given(st.permutations([0, 1, 2]))
def test_require_complete_accepts_exact_episode_set(order):
    assert require_complete(order, 3)
    assert not require_complete(order[:-1], 3)
    assert not require_complete([*order, 3], 3)
    assert not require_complete([*order, order[0]], 3)


@pytest.mark.parametrize("ci95,ci90,difference,expected", [
    ([0.01, 0.4], [0.02, 0.3], 0.11, "value"),
    ([-0.1, 0.1], [-0.1, 0.1], 0, "no value"),
    ([-0.2, 0.2], [-0.2, 0.2], 0, "inconclusive"),
])
def test_difference_decision(ci95, ci90, difference, expected):
    primary = {"ci95": ci95, "ci90": ci90, "difference": difference}
    assert difference_decision(primary, 0.1, positive="value", equivalent="no value") == expected
    if expected == "no value":
        assert difference_decision(primary, 0.1, positive="value", equivalent="no value",
                                   strict_equivalence=True) == "inconclusive"


@pytest.mark.parametrize("ci95,ci90,expected", [
    ([0.5, 0.8], [0.6, 0.7], "saves"),
    ([0.85, 1.15], [0.9, 1.1], "no saving"),
    ([0.8, 1.2], [0.85, 1.15], "inconclusive"),
    (None, None, "inconclusive"),
])
def test_ratio_decision(ci95, ci90, expected):
    assert ratio_decision({"ci95": ci95, "ci90": ci90}, 0.1,
                          positive="saves", equivalent="no saving") == expected
