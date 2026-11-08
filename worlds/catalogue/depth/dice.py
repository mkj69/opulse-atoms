"""Exact finite dice, Bayesian inference, and an absorbing Markov walk.

Only rational finite distributions are used; the hidden die is drawn once and
retained in the state, not redrawn on every turn. Run with Python 3 directly.
"""

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import json
from pathlib import Path


@dataclass(frozen=True)
class Die:
    weights: tuple[int, int, int, int, int, int]

    def __post_init__(self):
        assert len(self.weights) == 6 and all(type(w) is int and w > 0 for w in self.weights)


class Dist:
    """Prelude dist[T]: canonical, normalized, finite positive rational mass."""

    def __init__(self, weights):
        combined = defaultdict(Fraction)
        for value, weight in weights:
            weight = Fraction(weight)
            assert weight >= 0
            combined[value] += weight
        assert combined and sum(combined.values()) == 1
        self.weights = {key: weight for key, weight in combined.items() if weight > 0}

    def __eq__(self, other):
        return isinstance(other, Dist) and self.weights == other.weights


def pure(value):
    return Dist([(value, Fraction(1))])


def roll(die):
    total_weight = sum(die.weights)
    return Dist((face, Fraction(weight, total_weight)) for face, weight in enumerate(die.weights, 1))


def jump(position, points, goal):
    assert 0 <= position <= goal and 2 <= points <= 12 and goal >= 2
    displacement = 2 if points >= 10 else 1 if points >= 7 else -1
    return min(goal, max(0, position + displacement))


def bind(distribution, operation):
    branches = []
    for value, outer_weight in distribution.weights.items():
        for result, inner_weight in operation(value).weights.items():
            branches.append((result, outer_weight * inner_weight))
    return Dist(branches)


def mass(distribution, event):
    return sum((weight for value, weight in distribution.weights.items() if value in event), Fraction(0))


FAIR = Die((1, 1, 1, 1, 1, 1))
TILT = Die((1, 1, 1, 1, 2, 6))


def independent(first, second):
    return bind(roll(first), lambda left: bind(roll(second), lambda right: pure((left, right))))


def total(pair):
    assert len(pair) == 2 and all(1 <= face <= 6 for face in pair)
    return sum(pair)


@dataclass(frozen=True)
class Event:
    lo: int
    hi: int

    def __post_init__(self):
        assert 2 <= self.lo <= self.hi <= 12

    def __contains__(self, pair):
        return self.lo <= total(pair) <= self.hi


def conditional(distribution, event, given):
    denominator = mass(distribution, given)
    if not denominator:
        raise ValueError("Bottom(domain): conditioning on a null event")
    return sum((weight for pair, weight in distribution.weights.items()
                if pair in event and pair in given), Fraction(0)) / denominator


def score(distribution, operation):
    return bind(distribution, lambda value: pure(operation(value)))


def mean(distribution):
    return sum((value * weight for value, weight in distribution.weights.items()), Fraction(0))


@dataclass(frozen=True)
class Belief:
    fair: Fraction
    tilt: Fraction

    def __post_init__(self):
        assert self.fair >= 0 and self.tilt >= 0 and self.fair + self.tilt == 1


def update(belief, observed):
    fair_likelihood = mass(independent(FAIR, FAIR), observed)
    tilt_likelihood = mass(independent(TILT, TILT), observed)
    evidence = belief.fair * fair_likelihood + belief.tilt * tilt_likelihood
    if not evidence:
        raise ValueError("Bottom(domain): impossible observation")
    return Belief(belief.fair * fair_likelihood / evidence,
                  belief.tilt * tilt_likelihood / evidence)


@dataclass(frozen=True)
class Walk:
    belief: Belief
    goal: int

    def __post_init__(self):
        assert type(self.goal) is int and 2 <= self.goal <= 32


@lru_cache(None)
def turn_scores(die_index):
    die = (FAIR, TILT)[die_index]
    return score(independent(die, die), total)


def step(walk, state):
    position, die_index = state
    assert 0 <= position <= walk.goal and die_index in (0, 1)
    if position == walk.goal:
        return pure(state)
    transitions = []
    for points, weight in turn_scores(die_index).weights.items():
        destination = jump(position, points, walk.goal)
        transitions.append(((destination, die_index), weight))
    return Dist(transitions)


def advance(walk, turns):
    assert type(turns) is int and turns >= 0
    distribution = Dist([((0, 0), walk.belief.fair), ((0, 1), walk.belief.tilt)])
    for _ in range(turns):
        distribution = bind(distribution, lambda state: step(walk, state))
    return distribution


def hit_prob(walk, turns):
    return mass(advance(walk, turns), {(walk.goal, 0), (walk.goal, 1)})


def linear_solve(matrix, vector):
    """Exact elimination; any zero pivot requires a row swap, not rounding."""
    size = len(vector)
    rows = [list(row) + [right] for row, right in zip(matrix, vector)]
    for column in range(size):
        pivot = next((row for row in range(column, size) if rows[row][column]), None)
        if pivot is None:
            raise ValueError("Bottom(domain): non-absorbing chain")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        factor = rows[column][column]
        rows[column] = [entry / factor for entry in rows[column]]
        for row in range(size):
            if row != column and rows[row][column]:
                factor = rows[row][column]
                rows[row] = [current - factor * pivot_entry
                             for current, pivot_entry in zip(rows[row], rows[column])]
    result = [row[-1] for row in rows]
    assert all(sum(coefficient * answer for coefficient, answer in zip(original, result)) == right
               for original, right in zip(matrix, vector))
    return result


def hitting(walk):
    states = [(position, die_index) for die_index in (0, 1)
              for position in range(walk.goal)]
    indices = {state: index for index, state in enumerate(states)}
    matrix = []
    for state in states:
        row = [Fraction(int(state == other)) for other in states]
        for successor, probability in step(walk, state).weights.items():
            if successor in indices:
                row[indices[successor]] -= probability
        matrix.append(row)
    solutions = linear_solve(matrix, [Fraction(1)] * len(states))
    return walk.belief.fair * solutions[indices[(0, 0)]] + walk.belief.tilt * solutions[indices[(0, 1)]]


PRIOR = Belief(Fraction(1, 2), Fraction(1, 2))
HIGH = Event(10, 12)
POSTERIOR = update(PRIOR, HIGH)
POST_WALK = Walk(POSTERIOR, 6)
LOW = Event(2, 4)


def as_text(value):
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, Event):
        return f"Event<{value.lo},{value.hi}>"
    if isinstance(value, Belief):
        return f"Belief<{value.fair},{value.tilt}>"
    if isinstance(value, Walk):
        return f"Walk<{as_text(value.belief)},{value.goal}>"
    return str(value)


def example_values():
    fair_pair = independent(FAIR, FAIR)
    tilt_pair = independent(TILT, TILT)
    return [
        mass(fair_pair, {(6, 6)}),
        total((4, 5)),
        HIGH,
        conditional(fair_pair, HIGH, Event(7, 12)),
        mass(score(tilt_pair, total), {12}),
        mean(score(tilt_pair, total)),
        PRIOR,
        POSTERIOR,
        POST_WALK,
        mass(advance(POST_WALK, 3), {(6, 0), (6, 1)}),
        hit_prob(POST_WALK, 8),
        hitting(POST_WALK),
    ]


def first_past(walk, threshold, limit):
    for turns in range(limit + 1):
        if hit_prob(walk, turns) > threshold:
            return turns
    raise ValueError("no witness in the stated finite domain")


def showcase_values():
    updated_twice = update(POSTERIOR, LOW)
    return [
        hitting(POST_WALK),
        first_past(POST_WALK, Fraction(3, 4), 40),
        hitting(Walk(updated_twice, 6)) < Fraction(10),
    ]


def main():
    expected_examples = (
        "1/36", "9", "Event<10,12>", "2/7", "1/4", "28/3",
        "Belief<1/2,1/2>", "Belief<6/25,19/25>",
        "Walk<Belief<6/25,19/25>,6>", "131617/1166400",
        "104334629407094911/128391846454886400",
        "285152650332223286664/40483655031833058175",
    )
    expected_showcases = (
        "285152650332223286664/40483655031833058175", "7", "false",
    )
    assert tuple(map(as_text, example_values())) == expected_examples
    assert tuple(map(as_text, showcase_values())) == expected_showcases
    assert mass(roll(FAIR), {6}) == Fraction(1, 6)
    assert sum(roll(TILT).weights.values()) == 1
    assert bind(pure(FAIR), roll) == roll(FAIR)
    assert POSTERIOR == Belief(Fraction(6, 25), Fraction(19, 25))
    assert hit_prob(POST_WALK, 0) == 0
    assert hit_prob(POST_WALK, 3) == mass(advance(POST_WALK, 3), {(6, 0), (6, 1)})
    assert all(sum(step(POST_WALK, (position, die_index)).weights.values()) == 1
               for die_index in (0, 1) for position in range(7))
    path = Path(__file__).with_suffix(".json")
    if path.exists():
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert catalog["id"] == "dice" and len(catalog["tower"]) == 12
        assert len(catalog["showcase"]) == 3
        for index, (layer, actual) in enumerate(zip(catalog["tower"], example_values()), 1):
            assert layer["layer"] == index and layer["value"] == as_text(actual), (index, actual)
        for task, actual in zip(catalog["showcase"], showcase_values()):
            assert task["answer"] == as_text(actual), (task["angle"], actual)
    print("OK")


if __name__ == "__main__":
    main()
