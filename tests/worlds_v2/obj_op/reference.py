"""Reference semantics and executable answer checks for obj_op.

No new combinator or observation is implemented: both are fixed at layer zero.
This file checks mathematical results, not fuel certificates or universal proofs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import reduce
from itertools import pairwise
from math import gcd
from pathlib import Path

MAX_INT = 10**120 - 1
MAX_CYCLES = 32
MAX_BANDS = 4096


class Bottom(ValueError):
    pass


def bounded(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or abs(value) > MAX_INT:
        raise Bottom("range")
    return value


@dataclass(frozen=True)
class Band:
    lo: int
    hi: int

    def __post_init__(self) -> None:
        bounded(self.lo)
        bounded(self.hi)
        if self.lo > self.hi:
            raise Bottom("band_order")


@dataclass(frozen=True)
class Cycle:
    residue: int
    period: int

    def __post_init__(self) -> None:
        bounded(self.residue)
        bounded(self.period)
        if self.period <= 0:
            raise Bottom("period")
        object.__setattr__(self, "residue", self.residue % self.period)


def egcd(left: int, right: int) -> tuple[int, int, int]:
    if right == 0:
        return left, 1, 0
    gcd, x, y = egcd(right, left % right)
    return gcd, y, x - (left // right) * y


def join(left: Cycle, right: Cycle) -> Cycle:
    gcd, inverse, _ = egcd(left.period, right.period)
    delta = right.residue - left.residue
    if delta % gcd:
        raise Bottom("incompatible")
    quotient = right.period // gcd
    multiplier = ((delta // gcd) * inverse) % quotient
    return Cycle(bounded(left.residue + left.period * multiplier),
                 bounded(left.period * quotient))


@dataclass(frozen=True)
class Plan:
    cycles: tuple[Cycle, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.cycles) <= MAX_CYCLES:
            raise Bottom("plan_size")


def compile_plan(plan: Plan) -> Cycle:
    return reduce(join, plan.cycles)


@dataclass(frozen=True)
class Window:
    plan: Plan
    lo: int
    hi: int
    compiled: Cycle = None

    def __post_init__(self) -> None:
        bounded(self.lo)
        bounded(self.hi)
        if self.lo > self.hi:
            raise Bottom("window_order")
        object.__setattr__(self, "compiled", compile_plan(self.plan))


def first_hit(window: Window) -> int:
    cycle = window.compiled
    candidate = bounded(window.lo + (cycle.residue - window.lo) % cycle.period)
    if candidate > window.hi:
        raise Bottom("no_hit")
    return candidate


@dataclass(frozen=True)
class Blackout:
    window: Window
    bands: tuple[Band, ...]

    def __post_init__(self) -> None:
        if len(self.bands) > MAX_BANDS:
            raise Bottom("blackout_size")
        clipped = sorted(
            (Band(max(band.lo, self.window.lo), min(band.hi, self.window.hi))
             for band in self.bands
             if band.lo <= self.window.hi and band.hi >= self.window.lo),
            key=lambda band: (band.lo, band.hi),
        )
        merged = []
        for band in clipped:
            if merged and band.lo <= merged[-1].hi + 1:
                last = merged[-1]
                merged[-1] = Band(last.lo, max(last.hi, band.hi))
            else:
                merged.append(band)
        object.__setattr__(self, "bands", tuple(merged))


def clear_hit(masked: Blackout) -> int:
    cursor = masked.window.lo
    for band in masked.bands:
        if cursor < band.lo:
            try:
                return first_hit(Window(masked.window.plan, cursor, band.lo - 1))
            except Bottom as error:
                if str(error) != "no_hit":
                    raise
        cursor = band.hi + 1
        if cursor > masked.window.hi:
            raise Bottom("no_hit")
    return first_hit(Window(masked.window.plan, cursor, masked.window.hi))


def render(value: object) -> str:
    if isinstance(value, Cycle):
        return f"Cycle<{value.residue}, {value.period}>"
    if isinstance(value, Plan):
        return "Plan<" + ", ".join(map(render, value.cycles)) + ">"
    if isinstance(value, Window):
        return f"Window<{render(value.plan)}, {value.lo}, {value.hi}>"
    if isinstance(value, Blackout):
        bands = ", ".join(f"Band<{band.lo}, {band.hi}>" for band in value.bands)
        return f"Blackout<{render(value.window)}" + (", " + bands if bands else "") + ">"
    return str(value).lower() if isinstance(value, bool) else str(value)


def outcome(call, *args) -> str:
    try:
        return render(call(*args))
    except Bottom as error:
        return f"Bottom({error})"


class Reader:
    """Parse the literal calls in the card, not the declaration meta-language."""

    token_pattern = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|-?[0-9]+|[<>,()]|\S")

    def __init__(self, text: str, variables: dict[str, int] | None = None):
        self.tokens = self.token_pattern.findall(text)
        self.position = 0
        self.variables = variables or {}

    def take(self, expected: str | None = None) -> str:
        if self.position >= len(self.tokens):
            raise ValueError("unexpected end of expression")
        token = self.tokens[self.position]
        self.position += 1
        if expected is not None and token != expected:
            raise ValueError(f"expected {expected}, found {token}")
        return token

    def read(self):
        name = self.take()
        if re.fullmatch(r"-?[0-9]+", name):
            return int(name)
        if name in self.variables:
            return self.variables[name]
        marker = self.take()
        if marker not in ("<", "("):
            raise ValueError(f"invalid call {name}")
        end = ">" if marker == "<" else ")"
        arguments = []
        if self.tokens[self.position] != end:
            while True:
                arguments.append(self.read())
                if self.tokens[self.position] != ",":
                    break
                self.take(",")
        self.take(end)
        constructors = {
            "Cycle": lambda args: Cycle(*args),
            "Plan": lambda args: Plan(tuple(args)),
            "Band": lambda args: Band(*args),
            "Window": lambda args: Window(*args),
            "Blackout": lambda args: Blackout(args[0], tuple(args[1:])),
            "join": lambda args: join(*args),
            "compile": lambda args: compile_plan(*args),
            "first_hit": lambda args: first_hit(*args),
            "clear_hit": lambda args: clear_hit(*args),
        }
        if name not in constructors or (marker == "<") != name[0].isupper():
            raise ValueError(f"invalid object/operation: {name}{marker}")
        return constructors[name](arguments)


def evaluate(expression: str, variables: dict[str, int] | None = None) -> str:
    reader = Reader(expression, variables)
    try:
        result = reader.read()
        assert reader.position == len(reader.tokens), expression
        return render(result)
    except Bottom as error:
        return f"Bottom({error})"


def expressions_in(prompt: str, variables: dict[str, int] | None = None) -> list[str]:
    answers = []
    for match in re.finditer(r"clear_hit\(", prompt):
        reader = Reader(prompt[match.start():], variables)
        answers.append(render(reader.read()))
    return answers


ANCHOR = 1_735_689_600
PERIODS = (7 * 86400, 9 * 86400, 11 * 86400, 13 * 86400)
CASE_EPOCH = ANCHOR + 67 * 86400 + 12345
CASE_CYCLES = tuple(Cycle(CASE_EPOCH, period) for period in PERIODS)
BASE_PLAN = Plan(CASE_CYCLES)
BASE_PERIOD = compile_plan(BASE_PLAN).period
BASE_WINDOW = Window(BASE_PLAN, CASE_EPOCH - 3_000_000,
                     CASE_EPOCH + 5 * BASE_PERIOD + 54_321)
CASE_BANDS = (
    Band(CASE_EPOCH - 2_555_555, CASE_EPOCH + 19_765_432),
    Band(CASE_EPOCH + 17_456_789, CASE_EPOCH + 2 * BASE_PERIOD + 31_234_567),
    Band(CASE_EPOCH + 2 * BASE_PERIOD + 30_000_000,
         CASE_EPOCH + 3 * BASE_PERIOD + 3_456_789),
    Band(CASE_EPOCH + 3 * BASE_PERIOD + 3_000_000,
         CASE_EPOCH + 4 * BASE_PERIOD - 1),
)
INVERSE_STEP = 77 * 86400
INVERSE_WINDOW_LO = CASE_EPOCH - 123_456
INVERSE_WINDOW_HI = CASE_EPOCH + 3 * INVERSE_STEP + 350
INVERSE_BANDS = (
    Band(CASE_EPOCH - 200, CASE_EPOCH + 12_345),
    Band(CASE_EPOCH + 11_000, CASE_EPOCH + 45_000),
    Band(CASE_EPOCH + 3 * INVERSE_STEP + 100,
         CASE_EPOCH + 3 * INVERSE_STEP + 300),
)


def inverse_mask(phase9: int, phase13: int) -> Blackout:
    plan = Plan((CASE_CYCLES[0], Cycle(phase9, PERIODS[1]),
                 CASE_CYCLES[2], Cycle(phase13, PERIODS[3])))
    return Blackout(Window(plan, INVERSE_WINDOW_LO, INVERSE_WINDOW_HI), INVERSE_BANDS)


def inverse_solutions() -> tuple[tuple[int, int], ...]:
    baseline = Plan((CASE_CYCLES[0], CASE_CYCLES[2]))
    first = first_hit(Window(baseline, INVERSE_WINDOW_LO, INVERSE_WINDOW_HI))
    assert first == CASE_EPOCH and compile_plan(baseline).period == INVERSE_STEP
    all_hits = tuple(range(first, INVERSE_WINDOW_HI + 1, INVERSE_STEP))
    assert all_hits == tuple(CASE_EPOCH + index * INVERSE_STEP for index in range(4))
    candidates = tuple(target for target in all_hits
                       if CASE_EPOCH + INVERSE_STEP <= target <= CASE_EPOCH + 3 * INVERSE_STEP)
    assert all(INVERSE_BANDS[0].lo <= first <= band.hi
               for band in INVERSE_BANDS[:2])
    solutions = tuple((target % PERIODS[1], target % PERIODS[3])
                      for target in candidates)
    assert len(set(solutions)) == 3
    for pair, target in zip(solutions, candidates):
        assert clear_hit(inverse_mask(*pair)) == target
    return solutions


def format_solutions(solutions: tuple[tuple[int, int], ...]) -> str:
    return "; ".join(f"({phase9}, {phase13})" for phase9, phase13 in solutions)


def compute_cases() -> dict[str, str]:
    left = Cycle(ANCHOR, PERIODS[0])
    right = Cycle(ANCHOR, PERIODS[1])
    small_plan = Plan((left, right))
    small_window = Window(small_plan, ANCHOR - 1000, ANCHOR + 50_000_000)
    small_blackout = Blackout(small_window, (
        Band(ANCHOR - 100, ANCHOR + 10_000),
        Band(ANCHOR + 9000, ANCHOR + 20_000),
    ))
    compute_mask = Blackout(BASE_WINDOW, CASE_BANDS)
    redundant_plan = Plan(BASE_PLAN.cycles + (Cycle(CASE_EPOCH, 77 * 86400),))
    different_window = Window(redundant_plan, BASE_WINDOW.lo, BASE_WINDOW.hi)
    different_mask = Blackout(different_window, CASE_BANDS[:2])
    return {
        "L1": outcome(Cycle, ANCHOR, PERIODS[0]),
        "L2": outcome(join, left, right),
        "L3": render(small_plan),
        "L4": outcome(compile_plan, small_plan),
        "L5": render(small_window),
        "L6": outcome(first_hit, small_window),
        "L7": render(small_blackout),
        "L8": outcome(clear_hit, small_blackout),
        "Compute": outcome(clear_hit, compute_mask),
        "Invert": format_solutions(inverse_solutions()),
        "Decide": render(clear_hit(compute_mask) == clear_hit(different_mask)),
    }


def verify() -> None:
    card = json.loads((Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/obj_op.json")
                      .read_text(encoding="utf-8"))
    assert card["id"] == "obj_op" and card["open_kinds"] == ["object", "operation"]
    assert card["fixed_kinds"] == ["combinator", "observation"]
    assert len(card["tower"]) == 8 and len(card["ladder"]) == 5
    assert {layer["kind"] for layer in card["tower"]} == {"object", "operation"}
    assert len(card["showcase"]) == 3
    assert card["tags"]["open_kinds"] == card["open_kinds"]
    assert card["rejected_fixes"] == []
    actual = compute_cases()
    for layer in card["tower"]:
        assert actual[f"L{layer['layer']}"] == layer["value"], layer
        assert evaluate(layer["example"]) == layer["value"], layer
    for showcase in card["showcase"]:
        assert actual[showcase["angle"]] == showcase["answer"], showcase
        if showcase["angle"] == "Compute":
            assert expressions_in(showcase["prompt"]) == [showcase["answer"]], showcase
        elif showcase["angle"] == "Invert":
            assert "0..777599" in showcase["prompt"]
            assert "0..1123199" in showcase["prompt"]
            for pair, target in zip(inverse_solutions(),
                                    (CASE_EPOCH + index * INVERSE_STEP
                                     for index in range(1, 4))):
                assert expressions_in(showcase["prompt"],
                                      {"r9": pair[0], "r13": pair[1]}) == [str(target)]
            assert format_solutions(inverse_solutions()) == showcase["answer"]
        else:
            parsed = expressions_in(showcase["prompt"])
            assert len(parsed) == 2 and render(parsed[0] == parsed[1]) == showcase["answer"]
            assert parsed == [str(CASE_EPOCH + 4 * BASE_PERIOD),
                              str(CASE_EPOCH + 3 * BASE_PERIOD)], showcase
    assert set(actual) == {f"L{index}" for index in range(1, 9)} | {
        "Compute", "Invert", "Decide"}

    assert BASE_PERIOD == 778_377_600
    assert compile_plan(BASE_PLAN) == join(join(join(BASE_PLAN.cycles[0], BASE_PLAN.cycles[1]),
                                          BASE_PLAN.cycles[2]), BASE_PLAN.cycles[3])
    assert tuple(cycle.residue for cycle in CASE_CYCLES) == (271545, 444345, 357945, 530745)
    for left, right in pairwise(CASE_CYCLES):
        assert (right.residue - left.residue) % gcd(left.period, right.period) == 0
    assert Blackout(BASE_WINDOW, CASE_BANDS).bands == (
        Band(CASE_BANDS[0].lo, CASE_BANDS[-1].hi),)
    assert clear_hit(Blackout(BASE_WINDOW, CASE_BANDS)) == CASE_EPOCH + 4 * BASE_PERIOD
    assert outcome(join, CASE_CYCLES[0], Cycle(CASE_EPOCH + 1, 21 * 86400)) == "Bottom(incompatible)"
    assert len(inverse_solutions()) == 3
    assert first_hit(Window(Plan((CASE_CYCLES[0], CASE_CYCLES[2])),
                            INVERSE_WINDOW_LO, INVERSE_WINDOW_HI)) == CASE_EPOCH
    assert outcome(join, Cycle(0, 6), Cycle(1, 9)) == "Bottom(incompatible)"
    assert outcome(first_hit, Window(Plan((Cycle(0, 10),)), 1, 9)) == "Bottom(no_hit)"
    assert outcome(clear_hit, Blackout(Window(Plan((Cycle(0, 10),)), 0, 20),
                                             (Band(0, 20),))) == "Bottom(no_hit)"
    assert outcome(Cycle, 0, 0) == "Bottom(period)"
    assert outcome(Window, Plan((Cycle(1, 2), Cycle(0, 2))), 0, 10) == "Bottom(incompatible)"
    print("OK")


if __name__ == "__main__":
    verify()
