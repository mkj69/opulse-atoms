"""Cross-check proposed timestamped layer-zero hosts against the depth oracle."""

import importlib.util
import sys
from itertools import product
from pathlib import Path

from opulse.atoms.values import Bottom, Card
from opulse.worlds_v2.kitchen import depth_hosts

SOURCE = Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/kitchen.py"
SPEC = importlib.util.spec_from_file_location("kitchen_depth_oracle", SOURCE)
oracle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = oracle
SPEC.loader.exec_module(oracle)


def encode(value):
    return Card("State", "state", (value.time, value.lots, value.jobs))


def compare(actual, expected):
    if isinstance(expected, oracle.Bottom):
        assert actual == Bottom(expected.reason)
    else:
        assert actual == encode(expected.value)


def test_recipe_starts_and_ticks_on_all_small_initial_stocks():
    for amounts in product(range(3), repeat=4):
        initial = depth_hosts.state(*amounts)
        reference = oracle.state(*amounts)
        assert initial == encode(reference)
        assert depth_hosts.stock(initial) == oracle.stock(reference)
        assert depth_hosts.busy(initial) == oracle.busy(reference)
        for recipe in oracle.RECIPES:
            compare(getattr(depth_hosts, recipe)(initial), oracle.start(reference, recipe))
        compare(depth_hosts.tick(initial), oracle.tick(reference))


def test_concurrent_starts_fifo_and_expiry():
    reference = oracle.state(4, 2, 2, 2)
    actual = encode(reference)
    for recipe in ("simmer", "whisk"):
        actual = getattr(depth_hosts, recipe)(actual)
        reference = oracle.start(reference, recipe).value
        assert actual == encode(reference)
    assert depth_hosts.whisk(actual) == Bottom("station")
    for _ in range(5):
        actual = depth_hosts.tick(actual)
        reference = oracle.tick(reference).value
        assert actual == encode(reference)
    assert depth_hosts.stock(actual) == oracle.stock(reference)
    assert depth_hosts.tick(Card("State", "state", (24, (), ()))) == Bottom("horizon")


def test_invalid_state_is_not_silently_accepted():
    assert depth_hosts.state(9, 0, 0, 0) == Bottom("invalid")
    malformed = Card("State", "state", (0, (("dough", -1, 1),), ()))
    assert depth_hosts.stock(malformed) == Bottom("invalid")
    assert depth_hosts.mix(malformed) == Bottom("invalid")
