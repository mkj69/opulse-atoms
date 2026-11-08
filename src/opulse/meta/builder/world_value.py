"""Finite world values and content identity (atoms-meta, section 6.1)."""

import hashlib
import json

from opulse.atoms.values import Card, encode
from opulse.meta.code import items, lst


def enum(name, tags):
    return Card("sort", "enum", (name, lst(tags)))


def range_sort(name, lo, hi):
    return Card("sort", "range", (name, lo, hi))


def val(value):
    return Card("cell", "val", (value,))


def err(reason):
    return Card("cell", "err", (reason,))


def row(inputs, out):
    return Card("row", "row", (lst(inputs), out))


def table(name, role, inputs, output, errors, rows, cost=1):
    return Card("op", "table", (name, role, lst(inputs), output, lst(errors), lst(rows), cost))


def body(name, code):
    return Card("op", "body", (name, code))


def tag(key, value):
    return Card("tag", "tag", (key, lst(value) if isinstance(value, (tuple, list)) else value))


def law(name, code):
    """A boolean statement code value over its declared, finite variables (section 6.1)."""
    return Card("law", "statement", (name, code))


def world(name, version, sorts, ops, nodes, recursion, probes, judge_view, open_kinds, tags, laws=()):
    fields = (name, version, lst(sorts), lst(ops), lst(nodes), recursion,
              lst(probes), judge_view, lst(open_kinds), lst(tags))
    return Card("world", "world", fields + ((lst(laws),) if laws else ()))


def _value_key(value):
    if type(value) is int:
        return (0, value)
    if isinstance(value, str):
        return (1, value)
    if isinstance(value, Card):
        return (2, value.sort, value.tag, tuple(_value_key(field) for field in value.fields))
    raise ValueError("invalid table input")


def canonicalize(card):
    """Normalize unordered lists, preserving sort, op and probe declaration order."""
    if not isinstance(card, Card) or card.sort != "world" or card.tag != "world" or len(card.fields) not in (10, 11):
        raise ValueError("not a world value")
    name, version, sorts, ops, nodes, recursion, probes, view, kinds, tags = card.fields[:10]
    normalized = []
    for op in items(ops):
        if isinstance(op, Card) and op.sort == "op" and op.tag == "table" and len(op.fields) == 7:
            op_name, role, inputs, output, errors, rows, cost = op.fields
            rows = sorted(items(rows), key=lambda entry: tuple(_value_key(value)
                                                             for value in items(entry.fields[0])))
            op = table(op_name, role, items(inputs), output, sorted(items(errors)), rows, cost)
        normalized.append(op)
    normalized_tags = []
    for entry in items(tags):
        if isinstance(entry, Card) and entry.sort == "tag" and entry.tag == "tag" and len(entry.fields) == 2:
            key, value = entry.fields
            if isinstance(value, Card) and value.sort == "list" and value.tag == "items":
                value = lst(sorted(items(value)))
            entry = Card("tag", "tag", (key, value))
        normalized_tags.append(entry)
    return world(name, version, items(sorts), normalized, items(nodes), recursion, items(probes),
                 view, sorted(items(kinds)), sorted(normalized_tags, key=lambda entry: entry.fields[0]),
                 sorted(items(card.fields[10]), key=lambda entry: entry.fields[0]
                        if isinstance(entry, Card) and entry.fields else "")
                 if len(card.fields) == 11 else ())


def world_hash(card):
    data = json.dumps(encode(canonicalize(card)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(("opulse.worldvalue/1\n" + data).encode()).hexdigest()


def show(card):
    name, version, sorts, ops, _, _, probes, *_ = canonicalize(card).fields
    return (f"World<{name}@{version}: sorts " + ", ".join(item.fields[0] for item in items(sorts))
            + "; ops " + ", ".join(item.fields[0] for item in items(ops))
            + "; probes " + ", ".join(items(probes)) + ">")
