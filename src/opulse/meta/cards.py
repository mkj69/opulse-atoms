"""Shared layer-0 card mechanics (atoms-meta section 2.3)."""

from opulse.atoms.library import atoms_digest
from opulse.atoms.values import Bottom, Card, boolean
from opulse.meta import code


def tag_of(value):
    return value.tag if isinstance(value, Card) else Bottom("invalid")


def field(value, index):
    if not isinstance(value, Card) or type(index) is not int or not 0 <= index < len(value.fields):
        return Bottom("invalid")
    return value.fields[index]


def with_field(value, index, replacement):
    if not isinstance(value, Card) or type(index) is not int or not 0 <= index < len(value.fields):
        return Bottom("invalid")
    fields = list(value.fields)
    fields[index] = replacement
    return Card(value.sort, value.tag, tuple(fields))


def mk(sort, tag, fields):
    try:
        if type(sort) is not str or type(tag) is not str:
            return Bottom("invalid")
        return Card(sort, tag, code.items(fields))
    except (ValueError, TypeError):
        return Bottom("invalid")


def list_len(value):
    try:
        return len(code.items(value))
    except (ValueError, TypeError):
        return Bottom("invalid")


def list_get(value, index):
    try:
        values = code.items(value)
        return values[index] if type(index) is int and 0 <= index < len(values) else Bottom("invalid")
    except (ValueError, TypeError):
        return Bottom("invalid")


def list_append(value, item):
    try:
        return code.lst((*code.items(value), item))
    except (ValueError, TypeError):
        return Bottom("invalid")


def list_concat(left, right):
    try:
        return code.lst((*code.items(left), *code.items(right)))
    except (ValueError, TypeError):
        return Bottom("invalid")


def str_eq(left, right):
    return boolean(type(left) is str and type(right) is str and left == right)


def size(value, leaf_cost=1):
    return 1 + sum(size(item, leaf_cost) for item in value.fields) if isinstance(value, Card) else leaf_cost


def promote_output(ledger, digest, world_hash, atoms, contract):
    """Require current code and layer-0 commitments on a ledger output (meta 9.I4)."""
    evidence = ledger.record(digest, world_hash).evidence
    if not evidence or evidence[-1].content_hash != digest or (
            evidence[-1].atoms_hash != atoms_digest(atoms)):
        raise ValueError("output evidence must commit current code and atoms")
    ledger.promote(digest, world_hash, contract)
