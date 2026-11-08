"""Finite integer lists: stable merges, inversion counts, and minimal swap proofs.

All public values are immutable. Indices in a trace are zero-based: index i swaps
the elements at positions i and i+1. No randomness or external packages are used.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class Bottom(Exception):
    """An invalid object/undefined operation, not a regular list value."""


def integer(value):
    if type(value) is not int:
        raise Bottom("expected Int")
    return value


def list_value(*values):
    return tuple(integer(value) for value in values)


def nil():
    return ()


def cons(value, values):
    if values and type(value) is not type(head(values)):
        raise Bottom("mixed list")
    return (value,) + tuple(values)


def head(values):
    if not values:
        raise Bottom("empty")
    return values[0]


def tail(values):
    if not values:
        raise Bottom("empty")
    return tuple(values[1:])


def lt(first, second):
    return first < second


def le(first, second):
    return first <= second


def eq(first, second):
    return first == second


def ne(first, second):
    return first != second


def add(first, second):
    return integer(first) + integer(second)


def sub(first, second):
    return integer(first) - integer(second)


def then(first, second, value):
    return second(first(value))


def items(values):
    return tuple(values)


def length(values):
    return len(values)


def split_at(values, count):
    if type(count) is not int or count < 0 or count > len(values):
        raise Bottom("invalid split")
    if count == 0:
        return Pair(nil(), tuple(values))
    split_rest = split_at(tail(values), sub(count, 1))
    return Pair(cons(head(values), split_rest.first), split_rest.second)


def half_floor(value):
    return integer(value) // 2


@dataclass(frozen=True)
class Pair:
    first: object
    second: object


@dataclass(frozen=True)
class NonEmpty:
    values: tuple

    def __post_init__(self):
        if not self.values:
            raise Bottom("empty")
        object.__setattr__(self, "values", list_value(*self.values))


def as_list(nonempty):
    if not isinstance(nonempty, NonEmpty):
        raise Bottom("expected NonEmpty")
    return nonempty.values


def fold(combine, values, seed):
    result = seed
    for value in values:
        result = combine(value, result)
    return result


def reverse(values):
    return fold(cons, values, nil())


def palindrome(values):
    return eq(items(values), items(reverse(values)))


@dataclass(frozen=True)
class Run:
    key: int
    count: int

    def __post_init__(self):
        integer(self.key)
        integer(self.count)
        if self.count < 1:
            raise Bottom("nonpositive count")


def rle(values):
    def append_or_extend(value, runs):
        if runs and eq(runs[-1].key, value):
            return runs[:-1] + (Run(value, add(runs[-1].count, 1)),)
        return runs + (Run(value, 1),)

    return fold(append_or_extend, values, ())


def stable_merge(compare, left, right):
    output = []
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        if compare(left[left_index], right[right_index]):
            output.append(left[left_index])
            left_index += 1
        else:
            output.append(right[right_index])
            right_index += 1
    return tuple(output) + tuple(left[left_index:]) + tuple(right[right_index:])


def sort(values):
    values = tuple(values)
    if len(values) <= 1:
        return values
    halves = split_at(values, half_floor(len(values)))
    return stable_merge(le, sort(halves.first), sort(halves.second))


def merge_count(compare, left, right):
    left_index = right_index = crossed = 0
    while left_index < len(left) and right_index < len(right):
        if compare(left[left_index], right[right_index]):
            left_index += 1
        else:
            crossed = add(crossed, sub(len(left), left_index))
            right_index += 1
    return Pair(stable_merge(compare, left, right), crossed)


def inversions(values):
    values = tuple(values)
    if len(values) <= 1:
        return 0
    halves = split_at(values, half_floor(len(values)))
    crossed = merge_count(le, sort(halves.first), sort(halves.second)).second
    return add(add(inversions(halves.first), inversions(halves.second)), crossed)


def trace(values):
    current = list(values)
    target = sort(values)
    swaps = []
    for position, wanted in enumerate(target):
        found = next(index for index in range(position, len(current))
                     if eq(current[index], wanted))
        for index in reverse(tuple(range(position, found))):
            current[index], current[index + 1] = current[index + 1], current[index]
            swaps.append(index)
    assert tuple(current) == target
    assert len(swaps) == inversions(values)
    return tuple(swaps)


def certificate(values, steps):
    current = list(values)
    for step in steps:
        if type(step) is not int or step < 0 or step + 1 >= len(current):
            return False
        if not lt(current[step + 1], current[step]):
            return False
        current[step], current[step + 1] = current[step + 1], current[step]
    return (eq(tuple(current), sort(values))
            and eq(rle(current), rle(sort(values)))
            and eq(len(steps), inversions(values)))


@lru_cache(maxsize=None)
def possible_inversions(size, wanted):
    if wanted < 0 or wanted > size * (size - 1) // 2:
        return False
    if size == 0:
        return wanted == 0
    return any(possible_inversions(size - 1, wanted - rank)
               for rank in range(size) if rank <= wanted)


def lexicographic_inverse(sorted_values, wanted):
    available = list(sorted_values)
    if len(available) != len(set(available)) or tuple(available) != sort(available):
        raise Bottom("inverse requires strictly increasing target")
    if not possible_inversions(len(available), wanted):
        raise Bottom("impossible inversion count")
    result = []
    while available:
        for rank, value in enumerate(available):
            if possible_inversions(len(available) - 1, wanted - rank):
                result.append(value)
                available.pop(rank)
                wanted -= rank
                break
        else:
            raise AssertionError("missing inversion witness")
    return tuple(result)


def ascii_value(value):
    if isinstance(value, Pair):
        return f"Pair<{ascii_value(value.first)}, {ascii_value(value.second)}>"
    if isinstance(value, NonEmpty):
        return "NonEmpty<" + ", ".join(map(str, value.values)) + ">"
    if isinstance(value, Run):
        return f"Run<{value.key}, {value.count}>"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, tuple):
        return "List<" + ", ".join(map(ascii_value, value)) + ">"
    return str(value)


def ascii_list(values):
    return ascii_value(tuple(values))


DATA_A = list_value(9, 1, 4, 9, -2, 7, 4, 1, 0, 9, 3, -2, 8, 3, 7, 0,
                    5, 5, -1, 8, 4, 2, 7, -1, 6, 2, 8, 6, 0, 3, 5, 1)
DATA_C = list_value(6, 2, 6, 0, 4, 3, 6, 1, 2, 5, 0, 5, 3, 4, 1, 6,
                    2, 0, 4, 5, 1, 3, 6, 0, 5, 2, 4, 1, 3, 6)
INVERSE_TARGET = tuple(range(1, 16))
INVERSE_COUNT = 73


def self_test():
    try:
        head(nil())
        raise AssertionError("empty head accepted")
    except Bottom as error:
        assert str(error) == "empty"
    try:
        tail(nil())
        raise AssertionError("empty tail accepted")
    except Bottom as error:
        assert str(error) == "empty"
    try:
        NonEmpty(nil())
        raise AssertionError("empty refinement accepted")
    except Bottom:
        pass
    try:
        Run(3, 0)
        raise AssertionError("invalid run accepted")
    except Bottom:
        pass
    assert then(lambda value: cons(8, value), reverse, (2, 3)) == (3, 2, 8)
    assert head(cons(1, (2,))) == 1 and tail(cons(1, (2,))) == (2,)
    assert lt(2, 3) and le(3, 3) and eq(4, 4) and ne(4, 5)
    assert add(5, 3) == 8 and sub(5, 3) == 2
    assert items((1, 2)) == (1, 2) and length((1, 2)) == 2
    assert split_at((3, 5, 7), 2) == Pair((3, 5), (7,))
    assert half_floor(5) == 2 and as_list(NonEmpty((1, 2))) == (1, 2)
    assert cons(Run(3, 2), nil()) == (Run(3, 2),)
    mutable = [2, 1]
    sealed = NonEmpty(mutable)
    mutable.append(8)
    assert as_list(sealed) == (2, 1)
    try:
        split_at((2,), 2)
        raise AssertionError("out-of-range split accepted")
    except Bottom:
        pass

    examples = [
        ("NonEmpty<List<4, 1, 4>>", NonEmpty(list_value(4, 1, 4))),
        ("@fold[cons](as_list(NonEmpty<List<4, 1, 2>>), List<>)",
         fold(cons, as_list(NonEmpty(list_value(4, 1, 2))), ())),
        ("reverse(List<4, 1, 2>)", reverse((4, 1, 2))),
        ("?palindrome{List<4, 1, 4>}", palindrome((4, 1, 4))),
        ("Run<4, 3>", Run(4, 3)),
        ("rle(List<4, 4, 1, 1, 1, 4>)", rle((4, 4, 1, 1, 1, 4))),
        ("@stable_merge[le](List<1, 3, 3>, List<2, 3, 5>)",
         stable_merge(le, (1, 3, 3), (2, 3, 5))),
        ("sort(List<4, 1, 4, 2, 1>)", sort((4, 1, 4, 2, 1))),
        ("@merge_count[le](List<1, 3, 3>, List<2, 3, 5>)",
         merge_count(le, (1, 3, 3), (2, 3, 5))),
        ("?inversions{List<4, 1, 4, 2, 1>}", inversions((4, 1, 4, 2, 1))),
        ("trace(List<3, 1, 2, 1>)", trace((3, 1, 2, 1))),
        ("?certificate{List<3, 1, 2, 1>, List<0, 2, 1, 2>}",
         certificate((3, 1, 2, 1), (0, 2, 1, 2))),
    ]
    a_inversions = inversions(DATA_A)
    a_runs = rle(sort(DATA_A))
    inverse = lexicographic_inverse(INVERSE_TARGET, INVERSE_COUNT)
    c_forward = inversions(DATA_C)
    c_backward = inversions(reverse(DATA_C))
    c_equal_pairs = sum(run.count * (run.count - 1) // 2 for run in rle(sort(DATA_C)))
    showcases = [
        (f"Compute (?inversions{{{ascii_list(DATA_A)}}}, "
         f"rle(sort({ascii_list(DATA_A)})), ?length{{trace({ascii_list(DATA_A)})}}). "
         "Inversions are strict; list indices are zero-based.",
         f"({a_inversions}, {ascii_value(a_runs)}, {length(trace(DATA_A))})"),
        ("Invert: find the lexicographically smallest permutation xs of "
         f"{ascii_list(INVERSE_TARGET)} such that "
         f"eq(sort(xs), {ascii_list(INVERSE_TARGET)}) and "
         f"eq(?inversions{{xs}}, {INVERSE_COUNT}). Strict inversions; return xs.",
         ascii_list(inverse)),
        ("Decide whether eq(add(?inversions{xs}, ?inversions{reverse(xs)}), "
         f"435) for xs = {ascii_list(DATA_C)}. "
         "Give the Boolean, both counts and the number of equal-value index pairs.",
         f"({ascii_value(eq(add(c_forward, c_backward), 435))}, "
         f"{c_forward}, {c_backward}, {c_equal_pairs})"),
    ]
    assert len(examples) == 12
    assert all(certificate(values, trace(values))
               for values in ((), (1,), (1, 1), (3, 1, 2, 1), DATA_A, DATA_C))
    assert not certificate((1, 1), (0,))
    assert not certificate((2, 1), ())
    assert not certificate((2, 1), (2,))
    assert sort(inverse) == INVERSE_TARGET and inversions(inverse) == INVERSE_COUNT
    for position, value in enumerate(inverse):
        remaining = tuple(item for item in INVERSE_TARGET if item not in inverse[:position])
        rank = remaining.index(value)
        used = sum(tuple(item for item in INVERSE_TARGET if item not in inverse[:index]).index(candidate)
                   for index, candidate in enumerate(inverse[:position]))
        assert all(not possible_inversions(len(remaining) - 1,
                                           INVERSE_COUNT - used - smaller_rank)
                   for smaller_rank in range(rank))
    assert c_forward + c_backward + c_equal_pairs == len(DATA_C) * (len(DATA_C) - 1) // 2
    for size in range(1, 7):
        from itertools import product
        for values in product(range(3), repeat=size):
            slow = sum(values[first] > values[second]
                       for first in range(size) for second in range(first + 1, size))
            assert inversions(values) == slow
            assert len(trace(values)) == slow
            assert certificate(values, trace(values))

    catalog = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert catalog["id"] == "lists"
    assert len(catalog["tower"]) == len(examples)
    for layer, (expression, computed) in zip(catalog["tower"], examples):
        assert layer["example"] == expression
        actual = ascii_value(computed)
        assert layer["value"] == actual, (expression, actual)
    assert len(catalog["showcase"]) == len(showcases)
    for entry, (prompt, answer) in zip(catalog["showcase"], showcases):
        assert entry["prompt"] == prompt, entry["prompt"]
        assert entry["answer"] == answer, (entry["answer"], answer)
    print("OK")


if __name__ == "__main__":
    self_test()
