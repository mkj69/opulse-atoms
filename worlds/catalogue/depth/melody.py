"""Finite melody world: exact, transposition-invariant motif-cover arithmetic.

All functions are deterministic. Invalid typed values/actions raise Bottom(reason);
limits are part of this world's version, not host performance heuristics.
The bounded recurrences terminate in at most 64 positions; no audio is judged.
"""

from dataclasses import dataclass
import json
from pathlib import Path


class Bottom(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Bottom(reason)


def natural(value, maximum):
    require(type(value) is int and 0 <= value <= maximum, "range")
    return value


@dataclass(frozen=True)
class Melody:
    events: tuple

    def __post_init__(self):
        require(type(self.events) is tuple and 1 <= len(self.events) <= 64, "length")
        for event in self.events:
            require(type(event) is tuple and len(event) == 2, "event")
            pitch, duration = event
            require(type(pitch) is int and 48 <= pitch <= 84, "pitch")
            require(type(duration) is int and duration in (1, 2, 3, 4), "duration")


def melody(*events):
    return Melody(tuple(events))


def note_shift(event, semitones):
    require(type(semitones) is int and -12 <= semitones <= 12, "range")
    pitch, duration = event
    require(48 <= pitch + semitones <= 84, "pitch")
    return pitch + semitones, duration


def transpose(source, semitones):
    require(isinstance(source, Melody), "type")
    require(type(semitones) is int and -12 <= semitones <= 12, "range")
    return Melody(tuple(note_shift(event, semitones) for event in source.events))


def slice_events(source, start, length):
    require(isinstance(source, Melody), "type")
    natural(start, 63)
    natural(length, 64)
    require(length > 0 and start + length <= len(source.events), "slice")
    return Melody(source.events[start:start + length])


def concat(left, right):
    require(isinstance(left, Melody) and isinstance(right, Melody), "type")
    require(len(left.events) + len(right.events) <= 64, "capacity")
    return Melody(left.events + right.events)


def map_notes(transform, source):
    require(isinstance(source, Melody), "type")
    return Melody(tuple(transform(event, index) for index, event in enumerate(source.events)))


def events(source):
    require(isinstance(source, Melody), "type")
    return source.events


def beats(source):
    return sum(duration for _, duration in events(source))


# L1: sealed motif, relative to its first pitch; no root stored.
@dataclass(frozen=True)
class Motif:
    steps: tuple

    def __post_init__(self):
        require(type(self.steps) is tuple and 2 <= len(self.steps) <= 8, "motif_length")
        for step in self.steps:
            require(type(step) is tuple and len(step) == 2, "motif_step")
            offset, duration = step
            require(type(offset) is int and -36 <= offset <= 36, "motif_pitch")
            require(type(duration) is int and duration in (1, 2, 3, 4), "duration")
        require(self.steps[0][0] == 0, "anchor")


def motif(*steps):
    return Motif(tuple(steps))


# L2: both durations AND transposition-invariant intervals must match.
def occurs(source, pattern, start):
    require(isinstance(source, Melody) and isinstance(pattern, Motif), "type")
    natural(start, 63)
    if start + len(pattern.steps) > len(source.events):
        return False
    root = source.events[start][0]
    return all(event == (root + offset, duration)
               for event, (offset, duration) in zip(source.events[start:], pattern.steps))


# L3: higher-order, bounded scan; match must be a typed (Melody,Motif,Nat)->Bool op.
def scan(match, source, pattern):
    require(isinstance(source, Melody) and isinstance(pattern, Motif), "type")
    result = []
    for start in range(len(source.events) - len(pattern.steps) + 1):
        matched = match(source, pattern, start)
        require(type(matched) is bool, "match_result")
        if matched:
            result.append(start)
    return tuple(result)


# L4: do not discard durations when extracting contour.
def intervals(source):
    sequence = events(source)
    return tuple((next_event[0] - event[0], event[1])
                 for event, next_event in zip(sequence, sequence[1:]))


# L5: absolute register is bounded; map_notes retains durations.
def realize(pattern, root):
    require(isinstance(pattern, Motif), "type")
    natural(root, 84)
    require(root >= 48, "pitch")
    base = Melody(tuple((60, duration) for _, duration in pattern.steps))
    def pitch_note(event, index):
        pitch = root + pattern.steps[index][0]
        require(48 <= pitch <= 84, "pitch")
        return pitch, event[1]
    return map_notes(pitch_note, base)


# L6: extraction normalizes register, rejecting out-of-domain lengths.
def motif_at(source, start, length):
    require(2 <= natural(length, 8) <= 8, "motif_length")
    selected = events(slice_events(source, start, length))
    root = selected[0][0]
    return Motif(tuple((pitch - root, duration) for pitch, duration in selected))


# L7: finite sealed task object: library order matters for plan lexicography.
@dataclass(frozen=True)
class Score:
    melody: Melody
    library: tuple

    def __post_init__(self):
        require(isinstance(self.melody, Melody), "type")
        require(type(self.library) is tuple and 1 <= len(self.library) <= 12, "library_length")
        require(all(isinstance(pattern, Motif) for pattern in self.library), "type")
        require(len(set(self.library)) == len(self.library), "duplicate_motif")


def score(source, *library):
    return Score(source, tuple(library))


def matches_by_start(case, match):
    require(isinstance(case, Score), "type")
    result = [[] for _ in case.melody.events]
    for index, pattern in enumerate(case.library):
        for start in scan(match, case.melody, pattern):
            result[start].append((index, case.melody.events[start][0], len(pattern.steps)))
    return result


# L8: count every ordered, exact tiling without enumerating exponentially many plans.
def count_covers(match, case):
    choices = matches_by_start(case, match)
    counts = [0] * (len(choices) + 1)
    counts[-1] = 1
    for start in range(len(choices) - 1, -1, -1):
        counts[start] = sum(counts[start + length] for _, _, length in choices[start])
    return counts[0]


# L9: an observation, not a slot-compatible operation.
def cover_count(case):
    return count_covers(occurs, case)


# L10: shortest cover, then lexicographically smallest sequence of (index,root).
def best_cover(case):
    require(isinstance(case, Score), "type")
    if cover_count(case) == 0:
        raise Bottom("no_cover")
    choices = matches_by_start(case, occurs)
    plans = [None] * (len(choices) + 1)
    plans[-1] = ()
    for start in range(len(choices) - 1, -1, -1):
        candidates = []
        for index, root, length in choices[start]:
            tail = plans[start + length]
            if tail is not None:
                candidates.append(((index, root),) + tail)
        if candidates:
            plans[start] = min(candidates, key=lambda plan: (len(plan), plan))
    return plans[0]


# L11: slot accepts a typed (Motif,Nat)->Melody operation, never an observation.
def perform(emit, case, plan):
    require(isinstance(case, Score) and type(plan) is tuple and len(plan) > 0, "plan")
    rendered = None
    for item in plan:
        require(type(item) is tuple and len(item) == 2, "plan")
        index, root = item
        natural(index, len(case.library) - 1)
        part = emit(case.library[index], root)
        require(isinstance(part, Melody), "emit_result")
        rendered = part if rendered is None else concat(rendered, part)
    require(rendered == case.melody, "mismatch")
    return rendered


# L12: unique cover means EXACTLY one tiling, not merely one optimal plan.
def cover_report(case):
    count = cover_count(case)
    plan = best_cover(case) if count else None
    if plan is not None:
        perform(realize, case, plan)
    return count, plan, beats(case.melody)


def render(value):
    if isinstance(value, Melody):
        return "Melody<" + ",".join(f"({pitch},{duration})" for pitch, duration in value.events) + ">"
    if isinstance(value, Motif):
        return "Motif<" + ",".join(f"({pitch},{duration})" for pitch, duration in value.steps) + ">"
    if isinstance(value, Score):
        return "Score<" + render(value.melody) + "," + ",".join(render(pattern) for pattern in value.library) + ">"
    if value is None:
        return "None"
    if isinstance(value, bool):
        return str(value).lower()
    if type(value) is int:
        return str(value)
    if isinstance(value, tuple):
        return "List<" + ",".join(render(item) for item in value) + ">"
    raise TypeError(value)


def cases():
    alpha = motif((0, 1), (2, 1), (4, 2))
    beta = motif((0, 1), (2, 1))
    gamma = motif((0, 2), (-2, 1), (-4, 1), (-2, 2))
    delta = motif((0, 1), (0, 2), (-3, 1))
    epsilon = motif((0, 2), (-2, 1))
    zeta = motif((0, 1), (2, 1), (4, 2), (0, 2), (-2, 1))
    specification = ((alpha, 60), (gamma, 67), (delta, 65), (alpha, 62),
                     (zeta, 64), (gamma, 68), (alpha, 61), (delta, 70),
                     (zeta, 59), (alpha, 66))
    source = Melody(tuple(event for pattern, root in specification
                          for event in realize(pattern, root).events))
    full = score(source, alpha, beta, gamma, delta, epsilon, zeta)
    sparse = score(source, alpha, gamma, delta, zeta)
    return alpha, beta, gamma, delta, epsilon, zeta, source, full, sparse


def example_values():
    alpha, beta, gamma, delta, epsilon, zeta, source, full, sparse = cases()
    return (
        motif((0, 1), (2, 1), (4, 2)),
        occurs(source, alpha, 0),
        scan(occurs, source, alpha),
        intervals(slice_events(source, 0, 5)),
        realize(gamma, 67),
        motif_at(source, 3, 4),
        full,
        count_covers(occurs, full),
        cover_count(full),
        best_cover(full),
        perform(realize, full, best_cover(full)),
        cover_report(full),
    )


def showcase_values():
    *_, source, full, sparse = cases()
    return cover_report(full), best_cover(full), cover_report(sparse)


if __name__ == "__main__":
    alpha, beta, gamma, delta, epsilon, zeta, source, full, sparse = cases()
    assert len(source.events) == 36
    assert source == perform(realize, full, best_cover(full))
    def enumerate_plans(case):
        choices = matches_by_start(case, occurs)
        def walk(start):
            if start == len(choices):
                yield ()
            else:
                for index, root, length in choices[start]:
                    for tail in walk(start + length):
                        yield ((index, root),) + tail
        return tuple(walk(0))
    for case in (full, sparse):
        alternatives = enumerate_plans(case)
        assert len(alternatives) == cover_count(case)
        assert min(alternatives, key=lambda plan: (len(plan), plan)) == best_cover(case)
        assert all(perform(realize, case, plan) == case.melody for plan in alternatives)
    assert all(occurs(source, pattern, start)
               for pattern in full.library for start in scan(occurs, source, pattern))
    assert intervals(source)[0] == (2, 1)
    assert transpose(melody((60, 1), (62, 2)), 2) == melody((62, 1), (64, 2))
    for bad in (lambda: transpose(source, 13), lambda: realize(alpha, 84),
                lambda: slice_events(source, 35, 2),
                lambda: perform(realize, full, ((0, 60),))):
        try:
            bad()
        except Bottom:
            pass
        else:
            raise AssertionError("missing Bottom")
    payload = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["id"] == "melody" and len(payload["tower"]) == 12
    assert payload["fixtures"] == dict(zip(("A", "B", "C", "D", "E", "F", "M"),
                                           map(render, (alpha, beta, gamma, delta,
                                                        epsilon, zeta, source))))
    assert len(payload["showcase"]) == len(showcase_values())
    assert len(payload["tower"]) == len(example_values())
    assert {item["kind"] for item in payload["tower"]} == {"object", "operation", "combinator", "observation"}
    for item, actual in zip(payload["tower"], example_values()):
        assert item["value"] == render(actual), (item["layer"], render(actual))
    for item, actual in zip(payload["showcase"], showcase_values()):
        assert item["answer"] == render(actual), (item["angle"], render(actual))
    print("OK")
