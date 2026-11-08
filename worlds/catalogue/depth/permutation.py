"""Exact, bounded twelve-position permutation world; run directly to check JSON."""

import json
from collections import deque
from math import lcm
from pathlib import Path


SIZE = 12
LIMIT = 4096
I = tuple(range(1, SIZE + 1))
R = (12,) + tuple(range(1, SIZE))
S = (1, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2)


def perm(values):
    result = tuple(values)
    if len(result) != SIZE or set(result) != set(I):
        raise ValueError("Perm must contain each position 1..12 exactly once")
    return result


def swap(first, second, state):
    perm(state)
    if not (1 <= first <= SIZE and 1 <= second <= SIZE):
        raise ValueError("swap indices must lie in 1..12")
    result = list(state)
    result[first - 1], result[second - 1] = result[second - 1], result[first - 1]
    return tuple(result)


def then(first, second, state):
    return second(first(state))


def cards(state):
    return perm(state)


def cycle(indices):
    result = tuple(indices)
    if not (2 <= len(result) <= SIZE) or len(set(result)) != len(result):
        raise ValueError("Cycle must have 2..12 distinct positions")
    if any(index not in I for index in result) or result[0] != min(result):
        raise ValueError("Cycle must start with its smallest position")
    return result


def rotate(indices, state):
    cycle(indices)
    perm(state)
    result = state
    for offset in range(len(indices) - 2, -1, -1):
        result = swap(indices[offset], indices[offset + 1], result)
    return result


def power(move, times, state):
    if not isinstance(times, int) or times < 0:
        raise ValueError("power requires a natural-number exponent")
    perm(state)
    result = state
    for _ in range(times):
        result = then(lambda item: item, move, result)
        perm(result)
    return result


def cycles(state):
    cards(state)
    unseen = set(I)
    result = []
    while unseen:
        start = min(unseen)
        current = start
        component = []
        while current in unseen:
            unseen.remove(current)
            component.append(current)
            current = state[current - 1]
        if current != start:
            raise ValueError("not a permutation")
        if len(component) > 1:
            result.append(cycle(component))
    return tuple(result)


def inverse(state):
    result = I
    for component in cycles(state):
        result = rotate(component, result)
    return result


def sign(state):
    return "odd" if sum(len(component) - 1 for component in cycles(state)) % 2 else "even"


def compose(first, second):
    cards(first)
    result = first
    for component in cycles(second):
        backwards = cycle((component[0],) + component[:0:-1])
        result = rotate(backwards, result)
    return result


def closure(first_move, second_move, start):
    cards(start)
    discovered = {start}
    queue = deque((start,))
    while queue:
        state = queue.popleft()
        for move in (first_move, second_move):
            successor = perm(move(state))
            if successor not in discovered:
                if len(discovered) == LIMIT:
                    raise ValueError("Bottom: generated closure exceeds 4096 states")
                discovered.add(successor)
                queue.append(successor)
    for move in (first_move, second_move):
        if len({perm(move(state)) for state in discovered}) != len(discovered):
            raise ValueError("Bottom: closure slot is not bijective on its orbit")
    return tuple(sorted(discovered))


class Subgroup:
    def __init__(self, first, second):
        self.members = closure(
            lambda state: compose(state, perm(first)),
            lambda state: compose(state, perm(second)), I
        )

    def __eq__(self, other):
        return isinstance(other, Subgroup) and self.members == other.members


def order(state):
    result = 1
    for component in cycles(state):
        result = lcm(result, len(component))
    return result


def conjugate(first, second):
    return compose(compose(inverse(second), first), second)


def center(group):
    return tuple(member for member in group.members
                 if all(conjugate(member, other) == member for other in group.members))


def render(value):
    if isinstance(value, Subgroup):
        return "Subgroup<" + render(value.members) + ">"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        if len(value) == SIZE and set(value) == set(I) and all(isinstance(x, int) for x in value):
            return "Perm<" + ",".join(map(str, value)) + ">"
        if not value:
            return "Set<>"
        if isinstance(value[0], tuple) and len(value[0]) == SIZE:
            return "Set<" + ",".join(render(item) for item in value) + ">"
        if isinstance(value[0], tuple):
            return "List<" + ",".join("Cycle<" + ",".join(map(str, item)) + ">" for item in value) + ">"
        return "Cycle<" + ",".join(map(str, value)) + ">"
    raise TypeError(type(value))


def examples():
    group = Subgroup(R, S)
    half_turn = power(lambda state: compose(state, R), 6, I)
    centralizer_involutions = tuple(
        member for member in group.members
        if conjugate(S, member) == S and order(member) == 2 and sign(member) == "odd"
    )
    return (
        [
            cycle((1, 2, 3, 4)),
            rotate((1, 2, 3, 4), I),
            power(lambda state: rotate((1, 2, 3, 4), state), 3, I),
            cycles(S),
            inverse(R),
            sign(S),
            compose(R, S),
            closure(lambda state: swap(1, 2, state), lambda state: swap(3, 4, state), I),
            Subgroup(I, S),
            order(compose(R, S)),
            conjugate(R, S),
            center(group),
        ],
        [
            centralizer_involutions,
            center(group) == tuple(sorted((I, half_turn))),
            order(compose(S, conjugate(S, power(lambda state: compose(state, R), 5, I)))),
        ],
    )


if __name__ == "__main__":
    assert perm(I) == I
    assert cards(swap(1, 12, I)) == (12,) + I[1:-1] + (1,)
    assert then(lambda state: swap(1, 2, state), lambda state: swap(2, 3, state), I) == (2, 3, 1) + I[3:]
    assert compose(R, inverse(R)) == I
    assert compose(inverse(R), R) == I
    assert power(lambda state: compose(state, R), 12, I) == I
    assert sign(compose(R, S)) == ("odd" if sign(R) != sign(S) else "even")
    group = Subgroup(R, S)
    for first in group.members:
        assert compose(first, inverse(first)) == I
        assert power(lambda state: compose(state, first), order(first), I) == I
        for second in group.members:
            assert compose(first, second) in group.members
            assert sign(compose(first, second)) == ("even" if sign(first) == sign(second) else "odd")
    try:
        closure(lambda state: I, lambda state: swap(1, 2, state), I)
    except ValueError as error:
        assert "not bijective" in str(error)
    else:
        raise AssertionError("a non-bijective slot must not define a group closure")
    tower_values, showcase_values = examples()
    source = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert len(source["tower"]) == len(tower_values) == 12
    assert len(source["showcase"]) == len(showcase_values) == 3
    for entry, value in zip(source["tower"], tower_values):
        assert entry["value"] == render(value), (entry["layer"], entry["value"], render(value))
    for entry, value in zip(source["showcase"], showcase_values):
        assert entry["answer"] == render(value), (entry["angle"], entry["answer"], render(value))
    assert len(group.members) == 24
    assert len(center(group)) == 2
    print("OK")
