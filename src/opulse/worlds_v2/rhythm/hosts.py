"""Layer-zero rotation, public probe, and generic scalar/list primitives."""

from math import lcm as math_lcm

from opulse.atoms.values import Bottom, Card


def to_card(events):
    if (not isinstance(events, tuple) or not 1 <= len(events) <= 512
            or any(type(event) is not int or event not in (0, 1, 2) for event in events)):
        return Bottom('invalid')
    return Card('rhythm', 'beats', events)


def from_card(value):
    if isinstance(value, Card) and value.sort in ('accented', 'cycle'):
        if value.tag != 'val' or len(value.fields) != 1 or not isinstance(value.fields[0], Card):
            return Bottom('invalid')
        base = value.fields[0]
        if base.sort != 'rhythm' or base.tag != 'beats':
            return Bottom('invalid')
        events = from_card(base)
        if isinstance(events, Bottom):
            return events
        if value.sort == 'accented' and 2 not in events:
            return Bottom('invalid')
        if value.sort == 'cycle' and any(
                len(events) % period == 0 and events == events[:period] * (len(events) // period)
                for period in range(1, len(events))):
            return Bottom('invalid')
        return events
    if not isinstance(value, Card) or value.sort != 'rhythm' or value.tag != 'beats':
        return Bottom('invalid')
    canonical = to_card(value.fields)
    return value.fields if canonical == value else Bottom('invalid')


def make_rhythm(events):
    return to_card(events)


def cells(value):
    if isinstance(value, tuple):
        return (value if len(value) == 2 and all(
            isinstance(item, Card) and not isinstance(from_card(item), Bottom) for item in value)
                else Bottom('invalid'))
    return from_card(value)


def valid_value(value):
    if isinstance(value, Card):
        if value.sort == 'bool':
            return value.tag in ('true', 'false') and not value.fields
        return not isinstance(from_card(value), Bottom)
    if isinstance(value, (tuple, list)):
        return all(valid_value(item) for item in value)
    if isinstance(value, dict):
        return all(valid_value(item) for pair in value.items() for item in pair)
    return True


def left(value, offset):
    events = from_card(value)
    if isinstance(events, Bottom) or type(offset) is not int:
        return Bottom('invalid')
    shift = offset % len(events)
    rotated = events[shift:] + events[:shift]
    base = to_card(rotated)
    return base if value.sort == 'rhythm' else Card(value.sort, 'val', (base,))


def identity(value):
    return value if valid_value(value) else Bottom('invalid')


def length(items):
    return len(items)


def at(items, index):
    if type(index) is not int or not 0 <= index < len(items):
        return Bottom('range')
    return items[index]


def index_of(items, value):
    return items.index(value) if value in items else -1


def append(items, value):
    return (*items, value)


def prefix(items, count):
    if type(count) is not int or not 0 <= count <= len(items):
        return Bottom('range')
    return items[:count]


def repeat(items, count):
    if type(count) is not int or count < 0 or len(items) * count > 512:
        return Bottom('range')
    return items * count


def indices(count):
    if type(count) is not int or not 0 <= count <= 512:
        return Bottom('range')
    return tuple(range(count))


def unique(items):
    return tuple(dict.fromkeys(items))


def sorted_list(items):
    return tuple(sorted(items))


def minimum(items):
    return min(items) if items else Bottom('empty')


def first(items):
    return at(items, 0)


def second(items):
    return at(items, 1)


def pair(first_value, second_value):
    return (first_value, second_value)


def triple(first_value, second_value, third_value):
    return (first_value, second_value, third_value)


def quad(first_value, second_value, third_value, fourth_value):
    return (first_value, second_value, third_value, fourth_value)


def add(first_value, second_value):
    return first_value + second_value


def sub(first_value, second_value):
    return first_value - second_value


def mod(first_value, second_value):
    return first_value % second_value if second_value else Bottom('range')


def div(first_value, second_value):
    return first_value // second_value if second_value else Bottom('range')


def lcm(first_value, second_value):
    result = math_lcm(first_value, second_value)
    return result if 1 <= result <= 512 else Bottom('range')


def eq(first_value, second_value):
    return first_value == second_value


def ne(first_value, second_value):
    return first_value != second_value


def lt(first_value, second_value):
    return first_value < second_value


def le(first_value, second_value):
    return first_value <= second_value


def maximum(first_value, second_value):
    return max(first_value, second_value)


def no_accent():
    return Bottom('no_accent')


def invalid():
    return Bottom('range')
