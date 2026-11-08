"""Exact, canonical, finite distribution primitives for the dice world."""

from collections import defaultdict
from fractions import Fraction
from functools import lru_cache

from opulse.atoms.values import Bottom, Card


def to_card(value):
    fraction = Fraction(value)
    return Card("fraction", "rational", (fraction.numerator, fraction.denominator))


def from_card(value):
    if (not isinstance(value, Card) or value.sort != "fraction" or value.tag != "rational"
            or len(value.fields) != 2 or any(type(field) is not int for field in value.fields)
            or value.fields[1] <= 0):
        return Bottom("invalid")
    fraction = Fraction(*value.fields)
    return fraction if to_card(fraction) == value else Bottom("invalid")


def die(*weights):
    return Card("die", "weights", weights)


FAIR = die(1, 1, 1, 1, 1, 1)
TILT = die(1, 1, 1, 1, 2, 6)


def valid_die(value):
    return (isinstance(value, Card) and value.sort == "die" and value.tag == "weights"
            and len(value.fields) == 6 and all(type(weight) is int and weight > 0 for weight in value.fields))


def valid_world_value(value):
    if isinstance(value, Card):
        try:
            hash(value)
        except TypeError:
            return _valid_card(value)
        return _valid_card_cached(value)
    if isinstance(value, (tuple, list, frozenset, set)):
        return all(valid_world_value(item) for item in value)
    if isinstance(value, dict):
        return all(valid_world_value(item) for pair in value.items() for item in pair)
    return True


@lru_cache(maxsize=32768)
def _valid_card_cached(value):
    return _valid_card(value)


def _valid_card(value):
    if value.sort in ("Event", "Belief", "Walk"):
        return all(valid_world_value(field) for field in value.fields)
    if value.sort == "dist":
        return valid_distribution(value)
    if not all(valid_world_value(field) for field in value.fields):
        return False
    if value.sort == "fraction":
        return isinstance(from_card(value), Fraction)
    if value.sort == "die":
        return valid_die(value)
    if value.sort == "event":
        if value.tag == "range":
            return len(value.fields) == 2 and all(type(bound) is int for bound in value.fields)
        return value.tag == "intersection" and len(value.fields) == 2 and all(
            isinstance(part, Card) and part.sort == "event" and part.tag == "range" for part in value.fields)
    if value.sort == "belief":
        return (value.tag == "weights" and len(value.fields) == 2
                and all(isinstance(from_card(part), Fraction) for part in value.fields))
    if value.sort == "walk":
        return (value.tag == "goal" and len(value.fields) == 2
                and isinstance(value.fields[0], Card) and value.fields[0].sort == "belief"
                and type(value.fields[1]) is int)
    if value.sort == "state":
        return (value.tag == "position_die" and len(value.fields) == 2
                and type(value.fields[0]) is int and value.fields[0] >= 0
                and type(value.fields[1]) is int and value.fields[1] in (0, 1))
    if value.sort == "pair":
        return value.tag == "ordered" and len(value.fields) == 2
    if value.sort == "weighted":
        return valid_entry(value)
    if value.sort == "bool":
        return value.tag in ("true", "false") and not value.fields
    return False


def event(lo, hi):
    return Card("event", "range", (lo, hi)) if type(lo) is int and type(hi) is int else Bottom("invalid")


def belief(fair, tilt):
    return Card("belief", "weights", (fair, tilt))


def walk(prior, goal):
    return Card("walk", "goal", (prior, goal))


def pair(first, second):
    return Card("pair", "ordered", (first, second)) if valid_world_value((first, second)) else Bottom("invalid")


def state(position, hidden):
    return Card("state", "position_die", (position, hidden)) if type(position) is int and position >= 0 and type(hidden) is int and hidden in (0, 1) else Bottom("domain")


def valid_entry(value):
    return (isinstance(value, Card) and value.sort == "weighted" and value.tag == "entry"
            and len(value.fields) == 3 and type(value.fields[1]) is int and value.fields[1] >= 0
            and type(value.fields[2]) is int and value.fields[2] > 0
            and valid_world_value(value.fields[0]))


def canon_distribution(value):
    if not isinstance(value, Card) or value.sort != "dist" or value.tag != "finite":
        return Bottom("invalid")
    weights = defaultdict(Fraction)
    for entry in value.fields:
        if not valid_entry(entry):
            return Bottom("invalid")
        item, numerator, denominator = entry.fields
        try:
            weights[item] += Fraction(numerator, denominator)
        except (TypeError, ValueError):
            return Bottom("invalid")
    if not weights or sum(weights.values(), Fraction()) != 1:
        return Bottom("invalid")
    items = sorted(((item, weight) for item, weight in weights.items() if weight), key=lambda entry: repr(entry[0]))
    return Card("dist", "finite", tuple(Card("weighted", "entry", (item, weight.numerator, weight.denominator)) for item, weight in items))


def valid_distribution(value):
    return isinstance(value, Card) and canon_distribution(value) == value


def distribution(entries):
    items = tuple(Card("weighted", "entry", (item, weight.numerator, weight.denominator)) for item, weight in entries)
    return canon_distribution(Card("dist", "finite", items)) if all(valid_world_value(item) for item in items) else Bottom("invalid")


def roll(value):
    if not valid_die(value):
        return Bottom("invalid")
    total = sum(value.fields)
    return distribution((face, Fraction(weight, total)) for face, weight in enumerate(value.fields, 1))


def pure(value):
    return distribution(((value, Fraction(1)),)) if valid_world_value(value) else Bottom("invalid")


def jump(position, points, goal):
    if any(type(value) is not int for value in (position, points, goal)) or not (0 <= position <= goal and goal >= 2 and 2 <= points <= 12):
        return Bottom("domain")
    change = 2 if points >= 10 else 1 if points >= 7 else -1
    return min(goal, max(0, position + change))


def entries(value):
    return value.fields if valid_distribution(value) else Bottom("invalid")


def item(entry):
    return entry.fields[0] if valid_entry(entry) else Bottom("invalid")


def weight(entry):
    return to_card(Fraction(*entry.fields[1:])) if valid_entry(entry) else Bottom("invalid")


def field(value, index):
    return value.fields[index] if isinstance(value, Card) and valid_world_value(value) and type(index) is int and 0 <= index < len(value.fields) else Bottom("invalid")


def make_entry(value, amount):
    fraction = from_card(amount)
    return Card("weighted", "entry", (value, fraction.numerator, fraction.denominator)) if valid_world_value(value) and isinstance(fraction, Fraction) and fraction >= 0 else Bottom("invalid")


def make_dist(items):
    return canon_distribution(Card("dist", "finite", items)) if isinstance(items, tuple) and all(valid_world_value(item) for item in items) else Bottom("invalid")


def fraction_op(left, right, op):
    first, second = from_card(left), from_card(right)
    return to_card(op(first, second)) if isinstance(first, Fraction) and isinstance(second, Fraction) else Bottom("invalid")


def multiply(left, right):
    return fraction_op(left, right, lambda first, second: first * second)


def add(left, right):
    return fraction_op(left, right, lambda first, second: first + second)


def divide(left, right):
    if from_card(right) == 0:
        return Bottom("domain")
    return fraction_op(left, right, lambda first, second: first / second)


def subtract(left, right):
    return fraction_op(left, right, lambda first, second: first - second)


def nth(items, index):
    return items[index] if isinstance(items, tuple) and type(index) is int and 0 <= index < len(items) else Bottom("invalid")


def replace_at(items, index, value):
    if not isinstance(items, tuple) or type(index) is not int or not 0 <= index < len(items):
        return Bottom("invalid")
    return items[:index] + (value,) + items[index + 1:]


def int_add(left, right):
    return left + right if type(left) is int and type(right) is int else Bottom("invalid")


def int_sub(left, right):
    return left - right if type(left) is int and type(right) is int else Bottom("invalid")


def int_mul_fraction(left, right):
    value = from_card(right)
    return to_card(left * value) if type(left) is int and isinstance(value, Fraction) else Bottom("invalid")


def equal(left, right):
    return left == right if valid_world_value((left, right)) else Bottom("invalid")


def less_equal(left, right):
    return left <= right if type(left) is int and type(right) is int else Bottom("invalid")


def is_empty(items):
    return not items if isinstance(items, tuple) else Bottom("invalid")


def head(items):
    return items[0] if isinstance(items, tuple) and items else Bottom("invalid")


def tail(items):
    return items[1:] if isinstance(items, tuple) and items else Bottom("invalid")


def cons(value, items):
    return (value, *items) if isinstance(items, tuple) else Bottom("invalid")


def length(items):
    return len(items) if isinstance(items, tuple) else Bottom("invalid")


def mass(dist, observed):
    if not valid_world_value((dist, observed)):
        return Bottom("invalid")
    if isinstance(observed, Card) and observed.sort == "event" and observed.tag == "range":
        lo, hi = observed.fields
        if not (type(lo) is int and type(hi) is int):
            return Bottom("invalid")
        select = lambda value: isinstance(value, Card) and value.sort == "pair" and type(value.fields[0]) is int and type(value.fields[1]) is int and lo <= sum(value.fields) <= hi
    elif isinstance(observed, Card) and observed.sort == "event" and observed.tag == "intersection":
        left, right = observed.fields
        if not all(isinstance(part, Card) and part.sort == "event" and part.tag == "range" and len(part.fields) == 2
                   and all(type(bound) is int for bound in part.fields)
                   for part in (left, right)):
            return Bottom("invalid")
        select = lambda value: isinstance(value, Card) and value.sort == "pair" and all(part.fields[0] <= sum(value.fields) <= part.fields[1] for part in (left, right))
    elif isinstance(observed, tuple):
        select = lambda value: value in observed
    else:
        return Bottom("invalid")
    return to_card(sum((Fraction(entry.fields[1], entry.fields[2]) for entry in dist.fields if select(entry.fields[0])), Fraction()))


def intersect(first, second):
    return Card("event", "intersection", (first, second)) if all(
        isinstance(part, Card) and part.sort == "event" and part.tag == "range" and valid_world_value(part)
        for part in (first, second)) else Bottom("invalid")
