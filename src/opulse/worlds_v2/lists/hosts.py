"""Given structural list primitives and non-empty object rules."""

from opulse.atoms.values import Bottom, Card, boolean

NIL = Card("list", "nil")


def list_valid(value):
    item_kind = None
    while isinstance(value, Card) and value.sort == "list" and value.tag == "cons" and len(value.fields) == 2:
        item, value = value.fields
        if type(item) is int:
            current_kind = "int"
        elif (isinstance(item, Card) and item.sort == "Run" and item.tag == "val"
              and len(item.fields) == 1 and isinstance(item.fields[0], Card)
              and item.fields[0].sort == "pair" and item.fields[0].tag == "pair"
              and len(item.fields[0].fields) == 2 and type(item.fields[0].fields[0]) is int
              and type(item.fields[0].fields[1]) is int):
            current_kind = "run"
        else:
            return False
        if item_kind is not None and current_kind != item_kind:
            return False
        item_kind = current_kind
    return value == NIL


def to_card(items):
    result = NIL
    for item in reversed(tuple(items)):
        if not list_valid(Card("list", "cons", (item, result))):
            raise ValueError("invalid")
        result = Card("list", "cons", (item, result))
    return result


def from_card(value):
    if not list_valid(value):
        raise ValueError("invalid")
    result = []
    while value != NIL:
        result.append(value.fields[0])
        value = value.fields[1]
    return tuple(result)


def cons(item, items):
    return Card("list", "cons", (item, items)) if list_valid(Card("list", "cons", (item, items))) else Bottom("invalid")


def snoc(item, items):
    return to_card((*from_card(items), item)) if list_valid(items) and type(item) is int else Bottom("invalid")


def head(items):
    if not list_valid(items):
        return Bottom("invalid")
    return Bottom("empty") if items == NIL else items.fields[0]


head_run = head


def tail(items):
    if not list_valid(items):
        return Bottom("invalid")
    return Bottom("empty") if items == NIL else items.fields[1]


def is_empty(items):
    return boolean(items == NIL) if list_valid(items) else Bottom("invalid")


def length(items):
    if not list_valid(items):
        return Bottom("invalid")
    return len(from_card(items))


def items(value):
    return value if list_valid(value) else Bottom("invalid")


def same_list(left, right):
    return boolean(left == right) if list_valid(left) and list_valid(right) else Bottom("invalid")


def nil():
    return NIL


def lt(left, right):
    return boolean(left < right) if type(left) is type(right) is int else Bottom("invalid")


def le(left, right):
    return boolean(left <= right) if type(left) is type(right) is int else Bottom("invalid")


def ge(left, right):
    return boolean(left >= right) if type(left) is type(right) is int else Bottom("invalid")


def eq(left, right):
    return boolean(left == right)


def ne(left, right):
    return boolean(left != right)


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("invalid")


def sub(left, right):
    return left - right if type(left) is type(right) is int else Bottom("invalid")


def half_floor(value):
    return value // 2 if type(value) is int else Bottom("invalid")


def pair(left, right):
    return Card("pair", "pair", (left, right))


def first(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "pair" and value.tag == "pair" and len(value.fields) == 2 else Bottom("invalid")


def second(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "pair" and value.tag == "pair" and len(value.fields) == 2 else Bottom("invalid")


second_list = second
pair_lists = pair
eq_bool = eq


def split_at(items, index):
    if not list_valid(items) or type(index) is not int or not 0 <= index <= length(items):
        return Bottom("invalid")
    row = from_card(items)
    return pair(to_card(row[:index]), to_card(row[index:]))


def append(left, right):
    if not list_valid(left) or not list_valid(right):
        return Bottom("invalid")
    return to_card(from_card(left) + from_card(right))


def nth(items, index):
    if not list_valid(items) or type(index) is not int or not 0 <= index < length(items):
        return Bottom("invalid")
    return from_card(items)[index]


def replace_at(items, index, value):
    if not list_valid(items) or type(index) is not int or type(value) is not int or not 0 <= index < length(items):
        return Bottom("invalid")
    row = from_card(items)
    return to_card((*row[:index], value, *row[index + 1:]))


def run(key, count):
    if type(key) is not int or type(count) is not int or count <= 0:
        return Bottom("invalid")
    return Card("pair", "pair", (key, count))


def key(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "pair" and value.tag == "pair" and len(value.fields) == 2 else Bottom("invalid")


def count(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "pair" and value.tag == "pair" and len(value.fields) == 2 else Bottom("invalid")
