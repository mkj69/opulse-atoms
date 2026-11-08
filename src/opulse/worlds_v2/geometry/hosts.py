"""Given lattice operations and generic structural/arithmetic primitives only."""

from math import gcd as math_gcd

from opulse.atoms.values import Bottom, Card


def point(x, y):
    if type(x) is not int or type(y) is not int or not (0 <= x <= 32 and 0 <= y <= 32):
        return Bottom("range")
    return Card("Point", "xy", (x, y))


def valid_point(value):
    return (isinstance(value, Card) and value.sort == "Point" and value.tag == "xy"
            and len(value.fields) == 2 and all(type(part) is int and 0 <= part <= 32 for part in value.fields))


def to_card(value):
    if valid_point(value):
        return value
    if isinstance(value, tuple) and len(value) <= 24 and all(valid_point(vertex) for vertex in value):
        return Card("Path", "points", value)
    return Bottom("invalid")


def from_card(value):
    if valid_point(value):
        return value
    if (isinstance(value, Card) and value.sort == "Path" and value.tag == "points" and
            len(value.fields) <= 24 and all(valid_point(vertex) for vertex in value.fields)):
        return value.fields
    return Bottom("invalid")


def path(vertices):
    if not isinstance(vertices, tuple) or len(vertices) > 24:
        return Bottom("size")
    if not all(valid_point(vertex) for vertex in vertices):
        return Bottom("range")
    return tuple(vertices)


def points(vertices):
    return vertices if isinstance(vertices, tuple) and len(vertices) <= 24 and all(
        valid_point(vertex) for vertex in vertices) else Bottom("size")


def move(vertex, dx, dy):
    if not valid_point(vertex) or type(dx) is not int or type(dy) is not int or not (-32 <= dx <= 32 and -32 <= dy <= 32):
        return Bottom("range")
    return point(vertex.fields[0] + dx, vertex.fields[1] + dy)


def turn(vertex, quarter):
    if not valid_point(vertex) or type(quarter) is not int or not 0 <= quarter <= 3:
        return Bottom("range")
    x, y = (part - 16 for part in vertex.fields)
    for _ in range(quarter):
        x, y = -y, x
    return point(x + 16, y + 16)


def flip(vertex):
    if not valid_point(vertex):
        return Bottom("range")
    return point(32 - vertex.fields[0], vertex.fields[1])


def cross(first, second, third):
    if not all(valid_point(vertex) for vertex in (first, second, third)):
        return Bottom("range")
    ax, ay = first.fields
    bx, by = second.fields
    cx, cy = third.fields
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_meet(first, second, third, fourth):
    turns = (cross(first, second, third), cross(first, second, fourth),
             cross(third, fourth, first), cross(third, fourth, second))
    if any(isinstance(value, Bottom) for value in turns):
        return Bottom("range")
    first_turn, second_turn, third_turn, fourth_turn = turns
    if first_turn == second_turn == third_turn == fourth_turn == 0:
        return (max(min(first.fields[0], second.fields[0]), min(third.fields[0], fourth.fields[0]))
                <= min(max(first.fields[0], second.fields[0]), max(third.fields[0], fourth.fields[0]))
                and max(min(first.fields[1], second.fields[1]), min(third.fields[1], fourth.fields[1]))
                <= min(max(first.fields[1], second.fields[1]), max(third.fields[1], fourth.fields[1])))
    return first_turn * second_turn <= 0 and third_turn * fourth_turn <= 0


def x(vertex):
    return vertex.fields[0] if valid_point(vertex) else Bottom("range")


def y(vertex):
    return vertex.fields[1] if valid_point(vertex) else Bottom("range")


def at(items, index):
    return items[index] if isinstance(items, tuple) and type(index) is int and 0 <= index < len(items) else Bottom("index")


def length(items):
    return len(items) if isinstance(items, tuple) else Bottom("invalid")


def empty(items):
    return not items if isinstance(items, tuple) else Bottom("invalid")


def head(items):
    return at(items, 0)


def tail(items):
    return items[1:] if isinstance(items, tuple) else Bottom("invalid")


def cons(item, items):
    return (item, *items) if isinstance(items, tuple) else Bottom("invalid")


def append(items, item):
    return (*items, item) if isinstance(items, tuple) else Bottom("invalid")


def reverse(items):
    return items[::-1] if isinstance(items, tuple) else Bottom("invalid")


def rotate(items, count):
    return items[count:] + items[:count] if isinstance(items, tuple) and type(count) is int and 0 <= count <= len(items) else Bottom("index")


def concat(first, second):
    return first + second if isinstance(first, tuple) and isinstance(second, tuple) else Bottom("invalid")


def singleton(item):
    return (item,)


def sorted_items(items):
    def key(item):
        if isinstance(item, Card):
            return key(item.fields)
        if isinstance(item, tuple):
            return tuple(key(part) for part in item)
        return item

    return tuple(sorted(items, key=key)) if isinstance(items, tuple) else Bottom("invalid")


def eq(first, second):
    return first == second


def lt(first, second):
    return first < second


def le(first, second):
    return first <= second


def add(first, second):
    return first + second


def sub(first, second):
    return first - second


def mul(first, second):
    return first * second


def div(first, second):
    return first // second if type(first) is type(second) is int and second != 0 else Bottom("invalid")


def absolute(value):
    return abs(value)


def gcd(first, second):
    return math_gcd(first, second)


def minimum(first, second):
    return min(first, second)


def maximum(first, second):
    return max(first, second)
