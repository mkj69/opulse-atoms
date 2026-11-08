"""Exact, immutable reference semantics for the Opulse versions depth pass."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
import json
import re


PATHS = tuple(f"/{letter}" for letter in "abcdefghijkl")
TEXT_PATTERN = re.compile(r"[A-Za-z0-9]+\Z")


def text(value: str | None) -> str:
    return "Gone<>" if value is None else value


@dataclass(frozen=True)
class Doc:
    values: tuple[str | None, ...] = ("0",) * 12

    def __post_init__(self):
        if len(self.values) != 12 or any(value is not None and (not isinstance(value, str) or not TEXT_PATTERN.fullmatch(value)) for value in self.values):
            raise ValueError("Doc needs exactly twelve optional texts")

    def get(self, path: str) -> str | None:
        return self.values[PATHS.index(path)]

    def replace(self, path: str, value: str | None) -> Doc:
        position = PATHS.index(path)
        values = list(self.values)
        values[position] = value
        return Doc(tuple(values))

    def __str__(self):
        changes = ",".join(f"{path}={text(value)}" for path, value in zip(PATHS, self.values) if value != "0")
        return f"Doc<12:{changes}>"


BASE = Doc()


@dataclass(frozen=True)
class Version:
    identifier: int
    parent: int | None
    doc: Doc


@dataclass(frozen=True)
class History:
    versions: tuple[Version, ...] = (Version(0, None, BASE),)

    def __post_init__(self):
        if not self.versions or self.versions[0] != Version(0, None, BASE):
            raise ValueError("history must start from Base12")
        for identifier, version in enumerate(self.versions[1:], 1):
            if version.identifier != identifier or version.parent is None or not 0 <= version.parent < identifier:
                raise ValueError("version identifiers and parents must form a rooted DAG")


def fork(history: History, parent: int, path: str, value: str | None) -> History:
    previous = read_version(history, parent)
    child = Version(len(history.versions), parent, edit(previous.doc, path, value))
    return History(history.versions + (child,))


def read_version(history: History, identifier: int) -> Version:
    if identifier < 0 or identifier >= len(history.versions):
        raise ValueError("unknown version identifier")
    return history.versions[identifier]


def edit(doc: Doc, path: str, value: str | None) -> Doc:
    return doc.replace(path, value)


def read(doc: Doc) -> Doc:
    return doc


def fix(function, *arguments):
    return lambda doc: function(doc, *arguments)


@dataclass(frozen=True, order=True)
class Patch:
    path: str
    old: str | None
    new: str | None

    def __post_init__(self):
        if self.path not in PATHS or any(value is not None and (not isinstance(value, str) or not TEXT_PATTERN.fullmatch(value)) for value in (self.old, self.new)):
            raise ValueError("unknown path")

    def __str__(self):
        return f"Patch<{self.path},{text(self.old)},{text(self.new)}>"


@dataclass(frozen=True)
class Patches:
    items: tuple[Patch, ...]

    def __post_init__(self):
        if tuple(sorted(self.items)) != self.items or len({patch.path for patch in self.items}) != len(self.items):
            raise ValueError("patches must have unique, sorted paths")

    def __str__(self):
        return f"Patches<{','.join(map(str, self.items))}>"


def patches(*items: Patch) -> Patches:
    return Patches(tuple(sorted(items)))


def delta(before: Doc, after: Doc) -> Patches:
    return patches(*(Patch(path, old, new) for path, old, new in zip(PATHS, before.values, after.values) if old != new))


def chain(operations, doc: Doc) -> Doc:
    for operation in operations:
        doc = operation(doc)
    return doc


class GuardError(ValueError):
    pass


def apply(doc: Doc, changes: Patches) -> Doc:
    if any(doc.get(patch.path) != patch.old for patch in changes.items):
        raise GuardError("atomic transaction rejected: stale old value")
    for patch in changes.items:
        doc = edit(doc, patch.path, patch.new)
    return doc


@dataclass(frozen=True, order=True)
class Clash:
    path: str
    base: str | None
    left: str | None
    right: str | None

    def __post_init__(self):
        if self.path not in PATHS or len({self.base, self.left, self.right}) != 3:
            raise ValueError("clash requires three distinct values")
        if any(value is not None and (not isinstance(value, str) or not TEXT_PATTERN.fullmatch(value)) for value in (self.base, self.left, self.right)):
            raise ValueError("invalid clash text")

    def __str__(self):
        return f"Clash<{self.path},{text(self.base)},{text(self.left)},{text(self.right)}>"


@dataclass(frozen=True)
class Merge:
    doc: Doc
    clashes: tuple[Clash, ...] = ()

    def __post_init__(self):
        if tuple(sorted(self.clashes)) != self.clashes or len({clash.path for clash in self.clashes}) != len(self.clashes):
            raise ValueError("clashes must have unique, sorted paths")
        if any(self.doc.get(clash.path) != clash.base for clash in self.clashes):
            raise ValueError("a conflicted path must retain its base value")

    def __str__(self):
        tail = "".join(f",{clash}" for clash in self.clashes)
        return f"Merge<{self.doc}{tail}>"


def three_way(left, right, base: Doc) -> Merge:
    left_doc, right_doc = left(base), right(base)
    left_changes, right_changes = delta(base, left_doc), delta(base, right_doc)
    left_by_path = {patch.path: patch.new for patch in left_changes.items}
    right_by_path = {patch.path: patch.new for patch in right_changes.items}
    merged = base
    clashes = []
    for path in PATHS:
        left_changed, right_changed = path in left_by_path, path in right_by_path
        left_value, right_value = left_doc.get(path), right_doc.get(path)
        if left_changed and right_changed and left_value != right_value:
            clashes.append(Clash(path, base.get(path), left_value, right_value))
        elif left_changed or right_changed:
            merged = edit(merged, path, right_value if right_changed else left_value)
    return Merge(merged, tuple(clashes))


def conflict_paths(merge: Merge) -> tuple[str, ...]:
    return tuple(clash.path for clash in merge.clashes)


def display(value):
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, tuple) and all(isinstance(path, str) and path in PATHS for path in value):
        return f"List<{','.join(value)}>"
    return str(value)


@dataclass(frozen=True)
class Choices:
    values: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if tuple(sorted(self.values)) != self.values or len(dict(self.values)) != len(self.values):
            raise ValueError("choices must be unique and sorted")
        if any(path not in PATHS or side not in ("base", "left", "right") for path, side in self.values):
            raise ValueError("invalid choice")

    def __str__(self):
        return f"Choices<{','.join(f'{path}={side}' for path, side in self.values)}>"


def resolve(merge: Merge, choices: Choices) -> Doc:
    if tuple(path for path, _ in choices.values) != conflict_paths(merge):
        raise ValueError("one choice is required for every conflict, and only conflicts")
    result = merge.doc
    for clash, (_, side) in zip(merge.clashes, choices.values):
        result = edit(result, clash.path, getattr(clash, side))
    return result


def commute(base: Doc, first: Patches, second: Patches) -> bool:
    try:
        return apply(apply(base, first), second) == apply(apply(base, second), first)
    except GuardError:
        return False


def invert(changes: Patches) -> Patches:
    return patches(*(Patch(patch.path, patch.new, patch.old) for patch in changes.items))


@dataclass(frozen=True)
class Replay:
    doc: Doc
    applied: int
    blocked: int
    clashes: tuple[Clash, ...] = ()

    def __post_init__(self):
        if self.applied < 0 or self.blocked not in (0, self.applied + 1):
            raise ValueError("invalid replay position")
        Merge(self.doc, self.clashes)
        if (self.blocked == 0) != (not self.clashes):
            raise ValueError("blocked replay must have conflicts and successful replay cannot")

    def __str__(self):
        tail = "".join(f",{clash}" for clash in self.clashes)
        return f"Replay<{self.doc},applied={self.applied},blocked={self.blocked}{tail}>"


def rebase(onto, steps, base: Doc) -> Replay:
    original = base
    deltas = []
    for step in steps:
        successor = step(original)
        changes = delta(original, successor)
        assert apply(successor, invert(changes)) == original
        deltas.append((original, successor))
        original = successor
    current = onto(base)
    for index, (old, new) in enumerate(deltas, 1):
        merged = three_way(lambda _: current, lambda _: new, old)
        if conflict_paths(merged):
            return Replay(merged.doc, index - 1, index, merged.clashes)
        current = merged.doc
    return Replay(current, len(deltas), 0)


def tx(*triples) -> object:
    return fix(apply, patches(*(Patch(*triple) for triple in triples)))


def examples():
    left = tx(("/a", "0", "x"), ("/b", "0", "y"))
    right = tx(("/a", "0", "z"), ("/c", "0", "w"))
    collision = three_way(left, right, BASE)
    return [
        Patch("/a", "0", "x"),
        delta(BASE, chain((fix(edit, "/a", "x"), fix(edit, "/b", "y")), BASE)),
        chain((fix(edit, "/a", "x"), fix(edit, "/b", "y")), BASE),
        apply(BASE, patches(Patch("/a", "0", "x"), Patch("/b", "0", "y"))),
        Merge(BASE, (Clash("/a", "0", "x", "y"),)),
        collision,
        conflict_paths(collision),
        resolve(collision, Choices((("/a", "right"),))),
        commute(BASE, patches(Patch("/a", "0", "x")), patches(Patch("/b", "0", "y"))),
        invert(patches(Patch("/a", "0", "x"), Patch("/b", "0", "y"))),
        Replay(BASE, 0, 0),
        rebase(tx(("/b", "0", "y")), (tx(("/a", "0", "x")), tx(("/c", "0", "z"))), BASE),
    ]


def showcases():
    branch = tx(("/a", "0", "R"), ("/d", "0", "D"), ("/h", "0", "H"), ("/j", "0", "J"))
    history = (
        tx(("/a", "0", "R"), ("/b", "0", "B")),
        tx(("/b", "B", "B2"), ("/e", "0", "E")),
        tx(("/f", "0", "F"), ("/g", "0", "G")),
        tx(("/d", "0", "X"), ("/i", "0", "I")),
        tx(("/k", "0", "K")),
    )
    first = rebase(branch, history, BASE)

    left = tx(("/a", "0", "X"), ("/c", "0", "C"), ("/e", "0", "E"), ("/g", "0", "G"))
    right = tx(("/a", "0", "Y"), ("/c", "0", "Z"), ("/e", "0", "Q"), ("/h", "0", "H"))
    merged = three_way(left, right, BASE)
    target_choices = Choices((("/a", "right"), ("/c", "base"), ("/e", "left")))
    target = resolve(merged, target_choices)
    solutions = [
        Choices(tuple(zip(conflict_paths(merged), sides)))
        for sides in product(("base", "left", "right"), repeat=len(merged.clashes))
        if resolve(merged, Choices(tuple(zip(conflict_paths(merged), sides)))) == target
    ]
    assert solutions == [target_choices]

    onto = tx(("/b", "0", "X"), ("/h", "0", "H"))
    steps = (tx(("/b", "0", "X"), ("/c", "0", "C")), tx(("/b", "X", "Y"), ("/d", "0", "D")))
    replay = rebase(onto, steps, BASE)
    final = chain(steps, BASE)
    one_shot = three_way(onto, lambda _: final, BASE)
    noncommuting = commute(BASE, delta(BASE, onto(BASE)), delta(BASE, final))
    third = replay.blocked == 0 and bool(one_shot.clashes) and not noncommuting
    return first, target_choices, third, (merged, target, replay, one_shot, noncommuting)


def main():
    payload = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["id"] == "versions"
    assert len(payload["tower"]) == 12 and {item["kind"] for item in payload["tower"]} == {"object", "operation", "combinator", "observation"}
    assert len(payload["ladder"]) == 5 and len(payload["showcase"]) == 3
    for item, actual in zip(payload["tower"], examples()):
        assert item["value"] == display(actual), (item["layer"], actual)
    expected = showcases()
    for item, actual in zip(payload["showcase"], expected[:3]):
        assert item["answer"] == display(actual), (item["angle"], actual)
    assert read(BASE) == BASE
    history = fork(fork(History(), 0, "/a", "x"), 0, "/b", "y")
    assert read_version(history, 1) == Version(1, 0, edit(BASE, "/a", "x"))
    assert read_version(history, 2) == Version(2, 0, edit(BASE, "/b", "y"))
    history = fork(history, 1, "/c", "z")
    assert read_version(history, 3) == Version(3, 1, edit(edit(BASE, "/a", "x"), "/c", "z"))
    assert read_version(history, 2).doc == edit(BASE, "/b", "y")
    assert apply(BASE, delta(BASE, edit(BASE, "/a", None))).get("/a") is None
    assert apply(BASE, patches(Patch("/a", "0", "x"), Patch("/b", "0", "y"))) == edit(edit(BASE, "/a", "x"), "/b", "y")
    try:
        apply(BASE, patches(Patch("/a", "0", "x"), Patch("/b", "wrong", "y")))
    except GuardError:
        assert BASE.get("/a") == "0"
    else:
        raise AssertionError("partially applied failed transaction")
    assert apply(apply(BASE, delta(BASE, expected[3][1])), invert(delta(BASE, expected[3][1]))) == BASE
    assert expected[3][2].blocked == 0 and expected[3][3].clashes and expected[3][4] is False
    for left_value, right_value in product(("0", "x", "y", None), repeat=2):
        left_doc, right_doc = edit(BASE, "/a", left_value), edit(BASE, "/a", right_value)
        merged = three_way(lambda _: left_doc, lambda _: right_doc, BASE)
        if left_value != "0" and right_value != "0" and left_value != right_value:
            assert conflict_paths(merged) == ("/a",)
            assert resolve(merged, Choices((("/a", "left"),))) == left_doc
            assert resolve(merged, Choices((("/a", "right"),))) == right_doc
        else:
            assert not merged.clashes and merged.doc == (right_doc if right_value != "0" else left_doc)
    assert rebase(fix(apply, patches(Patch("/a", "0", "x"))), (), BASE) == Replay(edit(BASE, "/a", "x"), 0, 0)
    print("OK")


if __name__ == "__main__":
    main()
