"""Given pixel actions and generic constructors, accessors and list primitives."""

from functools import lru_cache

from opulse.atoms.values import Bottom, Card, boolean


def point(x_coord, y_coord):
    if type(x_coord) is not int or type(y_coord) is not int:
        return Bottom("invalid")
    return Card("point", "xy", (x_coord, y_coord))


def _position(position):
    if (not isinstance(position, Card) or position.sort != "point" or position.tag != "xy"
            or len(position.fields) != 2 or any(type(value) is not int for value in position.fields)):
        return Bottom("invalid")
    return position.fields


def x_coord(position):
    result = _position(position)
    return result if isinstance(result, Bottom) else result[0]


def y_coord(position):
    result = _position(position)
    return result if isinstance(result, Bottom) else result[1]


def list_of(*items):
    return Card("list", "items", items)


def _items(items):
    return items.fields if isinstance(items, Card) and (items.sort, items.tag) == ("list", "items") else None


def grid(rows):
    items = _items(rows)
    if items is None or not 1 <= len(items) <= 32 or not isinstance(items[0], str) or not 1 <= len(items[0]) <= 32:
        return Bottom("range")
    if any(not isinstance(row, str) or len(row) != len(items[0]) or set(row) - {".", "#"} for row in items):
        return Bottom("grid")
    return Card("grid", "rows", (rows,))


def to_card(value):
    return grid(list_of(*value))


@lru_cache(maxsize=4096)
def _connected(rows):
    lit = {(x_coord, y_coord) for y_coord, row in enumerate(rows)
           for x_coord, pixel in enumerate(row) if pixel == "#"}
    if not lit:
        return False
    reached = {next(iter(lit))}
    frontier = list(reached)
    while frontier:
        x_coord, y_coord = frontier.pop()
        for neighbor in ((x_coord - 1, y_coord), (x_coord + 1, y_coord),
                         (x_coord, y_coord - 1), (x_coord, y_coord + 1)):
            if neighbor in lit and neighbor not in reached:
                reached.add(neighbor)
                frontier.append(neighbor)
    return reached == lit


def from_card(value):
    if isinstance(value, Card) and value.sort in ("Island", "Shape") and value.tag == "val" and len(value.fields) == 1:
        inner = value.fields[0]
        if value.sort == "Island" and (not isinstance(inner, Card) or inner.sort != "grid"):
            return Bottom("invalid")
        if value.sort == "Shape" and (not isinstance(inner, Card) or inner.sort != "Island"
                                      or inner.tag != "val" or len(inner.fields) != 1):
            return Bottom("invalid")
        result = from_card(inner)
        if isinstance(result, Bottom) or not _connected(result):
            return Bottom("invalid")
        if value.sort == "Shape" and (not any(row[0] == "#" for row in result)
                                      or not any(row[-1] == "#" for row in result)
                                      or "#" not in result[0] or "#" not in result[-1]):
            return Bottom("invalid")
        return result
    if isinstance(value, Card) and value.sort == "grid" and value.tag == "rows" and len(value.fields) == 1:
        result = _items(value.fields[0])
        if (result is not None and 1 <= len(result) <= 32 and isinstance(result[0], str)
                and 1 <= len(result[0]) <= 32 and all(isinstance(row, str) and len(row) == len(result[0])
                                                      and not set(row) - {".", "#"} for row in result)):
            return result
    return Bottom("invalid")


def rows(image):
    result = from_card(image)
    return result if isinstance(result, Bottom) else list_of(*result)


def width(image):
    result = from_card(image)
    return result if isinstance(result, Bottom) else len(result[0])


def height(image):
    result = from_card(image)
    return result if isinstance(result, Bottom) else len(result)


def cell(image, position):
    result = from_card(image)
    coordinates = _position(position)
    if isinstance(result, Bottom) or isinstance(coordinates, Bottom):
        return Bottom("invalid")
    x_coord_value, y_coord_value = coordinates
    return boolean(0 <= y_coord_value < len(result) and 0 <= x_coord_value < len(result[0])
                   and result[y_coord_value][x_coord_value] == "#")


def light(image, position):
    result = from_card(image)
    coordinates = _position(position)
    if isinstance(result, Bottom) or isinstance(coordinates, Bottom):
        return Bottom("invalid")
    x_coord_value, y_coord_value = coordinates
    if not 0 <= y_coord_value < len(result) or not 0 <= x_coord_value < len(result[0]):
        return Bottom("range")
    updated = list(result)
    row = updated[y_coord_value]
    updated[y_coord_value] = row[:x_coord_value] + "#" + row[x_coord_value + 1:]
    return to_card(updated)


def erase(image, position):
    result = from_card(image)
    coordinates = _position(position)
    if isinstance(result, Bottom) or isinstance(coordinates, Bottom):
        return Bottom("invalid")
    x_coord_value, y_coord_value = coordinates
    if not 0 <= y_coord_value < len(result) or not 0 <= x_coord_value < len(result[0]):
        return Bottom("range")
    updated = list(result)
    row = updated[y_coord_value]
    updated[y_coord_value] = row[:x_coord_value] + "." + row[x_coord_value + 1:]
    return to_card(updated)


def identity(value):
    if isinstance(value, Card) and value.sort in ("Island", "Shape") and isinstance(from_card(value), Bottom):
        return Bottom("invalid")
    return value


def pixels(image):
    return rows(image)


def area(image):
    result = from_card(image)
    return result if isinstance(result, Bottom) else sum(row.count("#") for row in result)


def empty_grid(image):
    result = from_card(image)
    return result if isinstance(result, Bottom) else to_card(["." * len(result[0]) for _ in result])


def blank(width_value, height_value):
    if type(width_value) is not int or type(height_value) is not int or not 1 <= width_value <= 32 or not 1 <= height_value <= 32:
        return Bottom("range")
    return to_card(["." * width_value for _ in range(height_value)])


def list4(first, second, third, fourth):
    return list_of(first, second, third, fourth)


def list8(first, second, third, fourth, fifth, sixth, seventh, eighth):
    return list_of(first, second, third, fourth, fifth, sixth, seventh, eighth)


def nth(items, index):
    result = _items(items)
    return result[index] if result is not None and type(index) is int and 0 <= index < len(result) else Bottom("range")


def sorted_list(items):
    result = _items(items)
    return list_of(*sorted(result)) if result is not None and all(isinstance(item, str) for item in result) else Bottom("invalid")


def min_int(left, right):
    return min(left, right) if type(left) is int and type(right) is int else Bottom("invalid")


def max_int(left, right):
    return max(left, right) if type(left) is int and type(right) is int else Bottom("invalid")


def unwrap(image):
    result = from_card(image)
    return result if isinstance(result, Bottom) else to_card(result)


def add(left, right):
    return left + right if type(left) is int and type(right) is int else Bottom("invalid")


def sub(left, right):
    return left - right if type(left) is int and type(right) is int else Bottom("invalid")


def lt(left, right):
    return boolean(left < right) if type(left) is int and type(right) is int else Bottom("invalid")


def eq(left, right):
    from opulse.atoms.values import value_equal
    return boolean(value_equal(left, right))


def length(items):
    result = _items(items)
    return len(result) if result is not None else Bottom("invalid")


def head(items):
    result = _items(items)
    return result[0] if result else Bottom("empty")


def tail(items):
    result = _items(items)
    return list_of(*result[1:]) if result else Bottom("empty")


def cons(item, items):
    result = _items(items)
    return list_of(item, *result) if result is not None else Bottom("invalid")


def concat(left, right):
    first, second = _items(left), _items(right)
    return list_of(*first, *second) if first is not None and second is not None else Bottom("invalid")


def member(item, items):
    result = _items(items)
    return boolean(item in result) if result is not None else Bottom("invalid")


def without(items, excluded):
    first, second = _items(items), _items(excluded)
    return list_of(*(item for item in first if item not in second)) if first is not None and second is not None else Bottom("invalid")


def is_empty(items):
    result = _items(items)
    return boolean(not result) if result is not None else Bottom("invalid")


def range_int(bound):
    return list_of(*range(bound)) if type(bound) is int and 0 <= bound <= 1024 else Bottom("range")


def text_join(separator, items):
    result = _items(items)
    return separator.join(result) if isinstance(separator, str) and result is not None and all(isinstance(item, str) for item in result) else Bottom("invalid")


def text_pad2(value):
    return f"{value:02d}" if type(value) is int and 0 <= value <= 99 else Bottom("range")


def text_concat(left, right):
    return left + right if isinstance(left, str) and isinstance(right, str) else Bottom("invalid")


def text_min(items):
    result = _items(items)
    return min(result) if result and all(isinstance(item, str) for item in result) else Bottom("empty")


def fail(reason):
    return Bottom(reason) if isinstance(reason, str) else Bottom("invalid")
