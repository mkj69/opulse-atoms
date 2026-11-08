"""Twelve-card given actions and domain-independent sequence primitives."""

from opulse.atoms.values import Bottom, Card, boolean

IDENTITY = tuple(range(1, 13))
I = Card("permutation", "cards", IDENTITY)
R = Card("permutation", "cards", (12, *range(1, 12)))
S = Card("permutation", "cards", (1, *range(12, 1, -1)))
EMPTY = Card("sequence", "items", ())


def valid_permutation(value):
    return (isinstance(value, Card) and value.sort == "permutation" and value.tag == "cards"
            and len(value.fields) == 12 and all(type(item) is int for item in value.fields)
            and set(value.fields) == set(IDENTITY))


def valid_cycle(value):
    if not isinstance(value, Card) or value.sort != "Cycle" or value.tag != "val" or len(value.fields) != 1:
        return False
    positions = _items(value.fields[0])
    return (positions is not None and 2 <= len(positions) <= 12
            and all(type(position) is int and 1 <= position <= 12 for position in positions)
            and len(set(positions)) == len(positions) and positions[0] == min(positions))


def valid_subgroup(value):
    if not isinstance(value, Card) or value.sort != "Subgroup" or value.tag != "val" or len(value.fields) != 1:
        return False
    members = _items(value.fields[0])
    if members is None or not 1 <= len(members) <= 4096 or not all(valid_permutation(member) for member in members):
        return False
    arrangements = tuple(member.fields for member in members)
    member_set = set(arrangements)
    if len(member_set) != len(arrangements) or tuple(sorted(arrangements)) != arrangements or IDENTITY not in member_set:
        return False
    return all(tuple(left[right[position] - 1] for position in range(12)) in member_set
               for left in arrangements for right in arrangements)


def to_card(items):
    if isinstance(items, (tuple, list)) and len(items) == 12 and all(type(item) is int for item in items) and set(items) == set(IDENTITY):
        return Card("permutation", "cards", tuple(items))
    return Bottom("invalid")


def from_card(value):
    return value.fields if valid_permutation(value) else Bottom("invalid")


def swap(first, second, state):
    if not valid_permutation(state) or type(first) is not int or type(second) is not int or not 1 <= first <= 12 or not 1 <= second <= 12:
        return Bottom("invalid")
    items = list(state.fields)
    items[first - 1], items[second - 1] = items[second - 1], items[first - 1]
    return to_card(items)


def cards(state):
    if valid_permutation(state):
        return Card("sequence", "items", state.fields)
    if _items(state) is not None:
        return state
    if valid_subgroup(state):
        return Card("sequence", "items", tuple(Card("sequence", "items", item.fields)
                                               for item in state.fields[0].fields))
    return Bottom("invalid")


def pack(items):
    values = _items(items)
    return to_card(values) if values is not None else Bottom("invalid")


def _items(value):
    if isinstance(value, Card) and value.sort == "sequence" and value.tag == "items":
        return value.fields
    return None


def length(value):
    items = _items(value)
    return len(items) if items is not None else Bottom("invalid")


def at(value, index):
    items = _items(value)
    if items is None or type(index) is not int or not 0 <= index < len(items):
        return Bottom("invalid")
    return items[index]


def append(value, item):
    items = _items(value)
    return Card("sequence", "items", (*items, item)) if items is not None else Bottom("invalid")


def contains(value, item):
    items = _items(value)
    return boolean(item in items) if items is not None else Bottom("invalid")


def merge_visited(first, second):
    first_items, second_items = _items(first), _items(second)
    return sorted_unique(Card("sequence", "items", (*first_items, *second_items))) if first_items is not None and second_items is not None else Bottom("invalid")


def reverse(value):
    items = _items(value)
    return Card("sequence", "items", tuple(reversed(items))) if items is not None else Bottom("invalid")


def reverse_tail(value):
    items = _items(value)
    return Card("sequence", "items", (items[0], *reversed(items[1:]))) if items else Bottom("invalid")


def all_between(value, lower, upper):
    items = _items(value)
    return boolean(items is not None and all(type(item) is int and lower <= item <= upper for item in items))


def sorted_unique(value):
    items = _items(value)
    if items is None:
        return Bottom("invalid")
    if all(valid_permutation(item) for item in items):
        return Card("sequence", "items", tuple(sorted(set(items), key=lambda item: item.fields)))
    return Card("sequence", "items", tuple(sorted(set(items))))


def distinct(value):
    items = _items(value)
    return boolean(len(items) == len(set(items))) if items is not None else Bottom("invalid")


def smallest(value):
    items = _items(value)
    return min(items) if items else Bottom("empty")


def eq(first, second):
    return boolean(first == second)


def lt(first, second):
    return boolean(first < second) if type(first) is int and type(second) is int else Bottom("invalid")


def le(first, second):
    return boolean(first <= second) if type(first) is int and type(second) is int else Bottom("invalid")


def add(first, second):
    return first + second if type(first) is int and type(second) is int else Bottom("invalid")


def sub(first, second):
    return first - second if type(first) is int and type(second) is int else Bottom("invalid")


def rem(first, second):
    return first % second if type(first) is int and type(second) is int and second else Bottom("invalid")


def lcm(first, second):
    from math import lcm as arithmetic_lcm

    return arithmetic_lcm(first, second) if type(first) is int and type(second) is int else Bottom("invalid")


def is_perm(state):
    return boolean(valid_permutation(state))


def require_limit(value):
    return value if type(value) is int and value <= 4096 else Bottom("limit")


def require_bijective(value):
    return value if type(value) is int and value > 0 else Bottom("not_bijective")


def reject(reason):
    return Bottom(reason) if isinstance(reason, str) else Bottom("invalid")
