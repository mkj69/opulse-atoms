"""Layer-zero integers and generic, strictly evaluated data primitives."""

from math import gcd as integer_gcd

from opulse.atoms.values import Bottom, Card


def integer(value):
    return type(value) is int


def succ(value):
    return value + 1 if integer(value) else Bottom("type")


def add(left, right):
    return left + right if integer(left) and integer(right) else Bottom("type")


def neg(value):
    return -value if integer(value) else Bottom("type")


def gcd(left, right):
    return integer_gcd(left, right) if integer(left) and integer(right) else Bottom("type")


def value(number):
    return number if integer(number) else Bottom("type")


def lt(left, right):
    return left < right if integer(left) and integer(right) else Bottom("type")


def le(left, right):
    return left <= right if integer(left) and integer(right) else Bottom("type")


def eq(left, right):
    return left == right


def ne(left, right):
    return left != right


def sub(left, right):
    return left - right if integer(left) and integer(right) else Bottom("type")


def quotient(left, right):
    if not integer(left) or not integer(right):
        return Bottom("type")
    return Bottom("div0") if right == 0 else left // right


def failure(reason):
    return Bottom(reason) if isinstance(reason, str) else Bottom("type")


def pair(left, right):
    return Card("pair", "items", (left, right))


def first(item):
    return item.fields[0] if isinstance(item, Card) and item.sort == "pair" and len(item.fields) == 2 else Bottom("type")


def second(item):
    return item.fields[1] if isinstance(item, Card) and item.sort == "pair" and len(item.fields) == 2 else Bottom("type")


def list_empty():
    return Card("list", "items", ())


def cons(head, tail):
    return Card("list", "items", (head, *tail.fields)) if isinstance(tail, Card) and tail.sort == "list" else Bottom("type")


def append(items, item):
    return Card("list", "items", (*items.fields, item)) if isinstance(items, Card) and items.sort == "list" else Bottom("type")


def is_empty(items):
    return not items.fields if isinstance(items, Card) and items.sort == "list" else Bottom("type")


def head(items):
    return items.fields[0] if isinstance(items, Card) and items.sort == "list" and items.fields else Bottom("empty")


def tail(items):
    return Card("list", "items", items.fields[1:]) if isinstance(items, Card) and items.sort == "list" and items.fields else Bottom("empty")


def length(items):
    return len(items.fields) if isinstance(items, Card) and items.sort == "list" else Bottom("type")


def numerator(item):
    if isinstance(item, Card) and item.sort == "frac" and item.tag == "val":
        item = item.fields[0]
        return first(item)
    return item.fields[0] if isinstance(item, Card) and item.sort == "frac" and len(item.fields) == 2 else Bottom("type")


def denominator(item):
    if isinstance(item, Card) and item.sort == "frac" and item.tag == "val":
        return second(item.fields[0])
    return item.fields[1] if isinstance(item, Card) and item.sort == "frac" and len(item.fields) == 2 else Bottom("type")


def digits(continued):
    if isinstance(continued, Card) and continued.sort == "cf" and continued.tag == "val":
        return continued.fields[0]
    return continued.fields[0] if isinstance(continued, Card) and continued.sort == "cf" else Bottom("type")


def is_cf_data(value):
    return isinstance(value, Card) and value.sort == "list" and value.tag == "items"


def is_pair(value):
    return isinstance(value, Card) and value.sort == "pair" and value.tag == "items" and len(value.fields) == 2


def is_base(value, sort_name):
    return (type(value) is int if sort_name == "int" else is_pair(value) if sort_name == "pair" else False)


def count(natural):
    if isinstance(natural, Card) and natural.sort == "nat" and natural.tag == "val":
        return natural.fields[0]
    return natural.fields[0] if isinstance(natural, Card) and natural.sort == "nat" and len(natural.fields) == 1 else Bottom("type")
