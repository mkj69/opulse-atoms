"""Given atoms of code@1 (atoms-meta section 2.3)."""

from functools import lru_cache

from opulse.atoms import kernel
from opulse.atoms.values import Bottom, Card, value_equal
from opulse.meta import cards, code, code_world
from opulse.meta.arith import add, div, is_zero, lt, mul, sub


def eq(left, right):
    return value_equal(left, right)


def tag_of(value):
    return cards.tag_of(value)


def field(value, index):
    return cards.field(value, index)


def with_field(value, index, replacement):
    replaced = cards.with_field(value, index, replacement)
    return replaced if isinstance(replaced, Bottom) else mk(replaced.sort, replaced.tag, code.lst(replaced.fields))


def mk(sort, tag, fields_list):
    try:
        value = cards.mk(sort, tag, fields_list)
        if isinstance(value, Bottom):
            return Bottom("invalid")
        fields = value.fields
        fields_schema = _tags().get(sort, {}).get(tag)
        if sort == "expr" and tag == "rec" and len(fields) == 6 and fields[5] is True:
            fields = fields[:5]  # memoized Rec carries a sixth host-boolean field (atoms-meta 2.1)
        if fields_schema is None or (sort != "list" and len(fields) != len(fields_schema)):
            return Bottom("invalid")
        if sort == "list":
            return code.lst(fields)
        for item, (_, expected) in zip(fields, fields_schema):
            actual = item.sort if isinstance(item, Card) else (
                "int" if type(item) is int else "str" if type(item) is str else None)
            if expected != "any" and actual != expected:
                return Bottom("invalid")
        return code.canonicalize(value) if sort == "code" else value
    except (code.CodeError, TypeError, ValueError, KeyError, IndexError):
        return Bottom("invalid")


@lru_cache(maxsize=1)
def _tags():
    from .world import load_world
    return {obj.name: obj.tags for obj in load_world().objects if obj.tags}


def list_len(values):
    return cards.list_len(values)


def list_get(values, index):
    return cards.list_get(values, index)


def list_append(values, item):
    return cards.list_append(values, item)


def list_cons(item, values):
    try:
        return code.lst((item, *code.items(values)))
    except code.CodeError:
        return Bottom("invalid")


def str_eq(left, right):
    return cards.str_eq(left, right)


def code_hash(value):
    return code_world.code_hash(value)


def size(value):
    return cards.size(value)


RULES = {
    "add": (2, add), "sub": (2, sub), "mul": (2, mul), "div": (2, div),
    "is_zero": (1, is_zero), "eq": (2, eq), "lt": (2, lt),
    "tag_of": (1, tag_of), "field": (2, field), "with_field": (3, with_field),
    "mk": (3, mk), "list_len": (1, list_len), "list_get": (2, list_get),
    "list_append": (2, list_append), "list_cons": (2, list_cons),
    "str_eq": (2, str_eq), "code_hash": (1, code_hash), "size": (1, size),
}


def atoms():
    given = tuple(kernel.Atom(name, arity, fn) for name, (arity, fn) in RULES.items())
    from .world import load_world
    world = load_world()
    shared = code_world.atoms(given, world)
    return (*given, *shared[1:])
