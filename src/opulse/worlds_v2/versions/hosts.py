"""Twelve-path immutable documents and structural layer-zero primitives."""

import re

from opulse.atoms.values import Bottom, Card

PATHS = tuple(f"/{letter}" for letter in "abcdefghijkl")
TEXT = re.compile(r"[A-Za-z0-9]+\Z")
GONE = "Gone<>"


def valid_text(value):
    return isinstance(value, str) and (value == GONE or bool(TEXT.fullmatch(value)))


def doc(*values):
    if len(values) != 12 or not all(valid_text(value) for value in values):
        return Bottom("domain")
    return Card("Doc", "doc", tuple(values))


def base12():
    return doc(*("0",) * 12)


def valid_doc(value):
    return (isinstance(value, Card) and value.sort == "Doc" and value.tag == "doc"
            and len(value.fields) == 12 and all(valid_text(item) for item in value.fields))


def edit(document, path, value):
    if not valid_doc(document) or path not in PATHS or not valid_text(value):
        return Bottom("domain")
    items = list(document.fields)
    items[PATHS.index(path)] = value
    return doc(*items)


def read(document):
    return document if valid_doc(document) else Bottom("domain")


def identity_doc(document):
    return document if valid_doc(document) else Bottom("domain")


def history():
    return Card("History", "history", (Card("Version", "version", (0, GONE, base12())),))


def valid_history(value):
    if not isinstance(value, Card) or value.sort != "History" or value.tag != "history" or not value.fields:
        return False
    if value.fields[0] != Card("Version", "version", (0, GONE, base12())):
        return False
    for index, version in enumerate(value.fields):
        if (not isinstance(version, Card) or version.sort != "Version" or version.tag != "version"
                or len(version.fields) != 3 or version.fields[0] != index
                or not valid_doc(version.fields[2])):
            return False
        if index:
            parent = version.fields[1]
            if type(parent) is not int or not 0 <= parent < index:
                return False
            original = value.fields[parent].fields[2]
            if sum(left != right for left, right in zip(original.fields, version.fields[2].fields)) > 1:
                return False
    return True


def valid_choices(value):
    if not isinstance(value, Card) or value.sort != "Choices" or value.tag != "choices" or len(value.fields) != 1:
        return False
    pairs = value.fields[0]
    return (isinstance(pairs, tuple) and all(isinstance(pair, tuple) and len(pair) == 2
            and pair[0] in PATHS and pair[1] in ("base", "left", "right") for pair in pairs)
            and tuple(sorted(pairs)) == pairs and len({pair[0] for pair in pairs}) == len(pairs))


def read_version(versions, identifier):
    if not valid_history(versions) or type(identifier) is not int or not 0 <= identifier < len(versions.fields):
        return Bottom("domain")
    return versions.fields[identifier]


def fork(versions, parent, path, value):
    previous = read_version(versions, parent)
    if isinstance(previous, Bottom):
        return previous
    updated = edit(previous.fields[2], path, value)
    if isinstance(updated, Bottom):
        return updated
    return Card("History", "history", (*versions.fields, Card("Version", "version", (len(versions.fields), parent, updated))))


def at(document, path):
    if not valid_doc(document) or path not in PATHS:
        return Bottom("domain")
    return document.fields[PATHS.index(path)]


def card(sort, tag, fields):
    if (sort not in ("Doc", "Base12", "Gone", "Path", "Text", "History", "Version",
                     "List", "Choices", "Patches", "Clash", "str", "int", "bool", "Any")
            or not isinstance(tag, str) or not isinstance(fields, tuple)):
        return Bottom("domain")
    return Card(sort, tag, fields)


def field(value, index):
    if not isinstance(value, Card) or type(index) is not int or not 0 <= index < len(value.fields):
        return Bottom("domain")
    return value.fields[index]


def tag(value):
    return value.tag if isinstance(value, Card) else Bottom("domain")


def sort_of(value):
    return value.sort if isinstance(value, Card) else Bottom("domain")


def empty():
    return ()


def cons(item, items):
    return (item, *items) if isinstance(items, tuple) else Bottom("domain")


def append(items, item):
    return (*items, item) if isinstance(items, tuple) else Bottom("domain")


def head(items):
    return items[0] if isinstance(items, tuple) and items else Bottom("domain")


def tail(items):
    return items[1:] if isinstance(items, tuple) and items else Bottom("domain")


def is_empty(items):
    return not items if isinstance(items, tuple) else Bottom("domain")


def length(items):
    return len(items) if isinstance(items, tuple) else Bottom("domain")


def item_at(items, index):
    return items[index] if isinstance(items, tuple) and type(index) is int and 0 <= index < len(items) else Bottom("domain")


def eq(left, right):
    return left == right


def lt(left, right):
    if type(left) is type(right) and isinstance(left, (int, str)):
        return left < right
    return Bottom("domain")


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("domain")


def sub(left, right):
    return left - right if type(left) is type(right) is int else Bottom("domain")


def path_at(index):
    return PATHS[index] if type(index) is int and 0 <= index < len(PATHS) else Bottom("domain")


def reject(reason):
    return Bottom(reason) if isinstance(reason, str) else Bottom("domain")
