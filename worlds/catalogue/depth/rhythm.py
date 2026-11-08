"""Exact, finite reference semantics for the Opulse rhythm depth world.

All rotations retain their origin; only repeated *whole* periods are reduced.
Pitch, playback, and probabilistic hearing are not part of the judge.
"""

from dataclasses import dataclass
from itertools import product
from json import load
from math import lcm
from pathlib import Path


def digits(text):
    assert isinstance(text, str) and text and set(text) <= set("012")
    return tuple(map(int, text))


@dataclass(frozen=True)
class Rhythm:
    cells: tuple

    def __post_init__(self):
        assert 1 <= len(self.cells) <= 512 and set(self.cells) <= {0, 1, 2}


def rhythm(text):
    return Rhythm(digits(text))


def left(sequence, offset):
    assert isinstance(offset, int) and not isinstance(offset, bool)
    cells = sequence.cells
    shift = offset % len(cells)
    return type(sequence)(cells[shift:] + cells[:shift])


def seq(first, second, sequence):
    return second(first(sequence))


def cells(sequence):
    return sequence.cells


@dataclass(frozen=True)
class Accented:
    cells: tuple

    def __post_init__(self):
        assert 1 <= len(self.cells) <= 512 and set(self.cells) <= {0, 1, 2}
        assert 2 in self.cells


def accented(text):
    return Accented(digits(text))


def start_heavy(sequence):
    return left(sequence, sequence.cells.index(2))


def stack(first, second, sequence):
    a, b = first(sequence), second(sequence)
    assert len(a.cells) == len(b.cells)
    return Rhythm(tuple(map(max, zip(a.cells, b.cells))))


def offbeat(sequence):
    return sum(value == 2 for index, value in enumerate(sequence.cells) if index % 2)


@dataclass(frozen=True)
class Cycle:
    cells: tuple

    def __post_init__(self):
        assert 1 <= len(self.cells) <= 512 and set(self.cells) <= {0, 1, 2}
        for period in range(1, len(self.cells)):
            assert len(self.cells) % period or self.cells != self.cells[:period] * (len(self.cells) // period)


def cycle(value):
    raw = digits(value) if isinstance(value, str) else value.cells
    assert 1 <= len(raw) <= 512
    for period in range(1, len(raw) + 1):
        if len(raw) % period == 0 and raw == raw[:period] * (len(raw) // period):
            return Cycle(tuple(raw[:period]))
    raise AssertionError("unreachable")


def shift_cycle(value, offset):
    return left(value, offset)


def expanded(value, length):
    assert length % len(value.cells) == 0 and length <= 512
    return value.cells * (length // len(value.cells))


def phase_score(first, second, shift):
    assert 0 <= shift < len(second.cells)
    length = lcm(len(first.cells), len(second.cells))
    assert length <= 512
    a, b = expanded(first, length), expanded(shift_cycle(second, shift), length)
    return (sum(x != y for x, y in zip(a, b)),
            offbeat(Rhythm(tuple(map(max, zip(a, b))))))


def weave(first, second, a, b):
    first, second = a(first), b(second)
    length = lcm(len(first.cells), len(second.cells))
    assert length <= 512
    return cycle(Rhythm(tuple(map(max, zip(expanded(first, length), expanded(second, length))))))


def best_fit(first, second):
    return min((*phase_score(first, second, shift), shift)
               for shift in range(len(second.cells)))


def silence_weak(value):
    return cycle(Rhythm(tuple(2 if cell == 2 else 0 for cell in value.cells)))


def orbit(operation, value):
    return tuple(dict.fromkeys(operation(shift_cycle(value, shift))
                               for shift in range(len(value.cells))))


def phase_count(first, second):
    minimum = best_fit(first, second)[0]
    return sum(phase_score(first, candidate, 0)[0] == minimum
               for candidate in orbit(lambda value: value, second))


def infer_phase(observed, first, second, budget):
    assert isinstance(budget, int) and not isinstance(budget, bool) and 0 <= budget <= 512
    assert len(first.cells) <= 32 and len(second.cells) <= 32
    assert lcm(len(observed.cells), len(first.cells), len(second.cells)) <= 512
    candidates = []
    for shift_a, shift_b in product(range(len(first.cells)), range(len(second.cells))):
        mixed = weave(first, second, lambda value: shift_cycle(value, shift_a),
                      lambda value: shift_cycle(value, shift_b))
        mismatch, _ = phase_score(observed, mixed, 0)
        if mismatch <= budget:
            candidates.append((mismatch, offbeat(mixed), shift_a, shift_b))
    if not candidates:
        return ()
    minimum = min(candidate[0] for candidate in candidates)
    return tuple(sorted(candidate for candidate in candidates if candidate[0] == minimum))


def identity(value):
    return value


def render(value):
    if isinstance(value, (Rhythm, Accented, Cycle)):
        return f'{type(value).__name__}<"{"".join(map(str, value.cells))}">'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, tuple):
        tag = "List" if not value or isinstance(value[0], (Cycle, tuple)) else "Pair"
        return f'{tag}<{", ".join(map(render, value))}>'
    raise TypeError(value)


SOURCE = "020101002010"
OTHER = "2010010100200101"
ROOT = rhythm(SOURCE)
FIRST = cycle(SOURCE)
SECOND = cycle(OTHER)
FIFTEEN = cycle("201001010020010")


def calculated():
    samples = [
        accented(SOURCE),
        start_heavy(accented(SOURCE)),
        stack(start_heavy, identity, accented(SOURCE)),
        offbeat(stack(start_heavy, identity, accented(SOURCE))),
        cycle(rhythm("020101002010020101002010")),
        phase_score(FIRST, SECOND, 3),
        weave(FIRST, SECOND, identity, lambda value: shift_cycle(value, 3)),
        best_fit(FIRST, SECOND),
        silence_weak(FIRST),
        orbit(silence_weak, FIRST),
        phase_count(FIRST, SECOND),
        infer_phase(cycle("200201102211101211022010120201102012101212012010"),
                    FIRST, SECOND, 1),
    ]
    shows = [
        best_fit(FIRST, SECOND),
        infer_phase(cycle("200201102211101211022010120201102012101212012010"),
                    FIRST, SECOND, 1),
        phase_count(FIRST, SECOND) == 1,
    ]
    return samples, shows


def main():
    data = load((Path(__file__).with_suffix(".json")).open(encoding="utf-8"))
    samples, shows = calculated()
    assert len(data["tower"]) == len(samples) == 12
    assert len(data["showcase"]) == len(shows) == 3
    for index, (spec, actual) in enumerate(zip(data["tower"], samples), 1):
        assert spec["layer"] == index
        assert spec["value"] == render(actual), (index, spec["value"], render(actual))
    for index, (spec, actual) in enumerate(zip(data["showcase"], shows), 1):
        assert spec["answer"] == render(actual), (index, spec["answer"], render(actual))
    assert cycle("0202") == cycle("02")
    assert left(rhythm("020"), 4) == rhythm("200")
    assert seq(lambda value: left(value, 1), lambda value: left(value, 2),
                rhythm("2010")) == rhythm("0201")
    assert cells(ROOT) == ROOT.cells
    assert len(orbit(identity, FIRST)) == len(FIRST.cells)
    assert phase_score(FIRST, FIRST, 0)[0] == 0
    assert len(weave(FIFTEEN, SECOND, identity, identity).cells) == 240
    assert infer_phase(weave(FIFTEEN, SECOND, identity, identity),
                       FIFTEEN, SECOND, 0) == ((0, offbeat(weave(FIFTEEN, SECOND, identity, identity)), 0, 0),)
    print("OK")


if __name__ == "__main__":
    main()
