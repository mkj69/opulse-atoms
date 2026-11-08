"""Exact, bounded lattice geometry for the Opulse geometry depth pass.

All geometry is integer/rational; invalid inputs raise Bottom, never masquerading
as valid values.  The public example and showcase fixtures are checked against
geometry.json when run as a script.
"""

import json
from dataclasses import dataclass
from fractions import Fraction
from math import gcd
from pathlib import Path


class Bottom(ValueError):
    pass


def point(x, y):
    if type(x) is not int or type(y) is not int or not (0 <= x <= 32 and 0 <= y <= 32):
        raise Bottom("range")
    return x, y


def path(*vertices):
    if len(vertices) > 24:
        raise Bottom("size")
    return tuple(point(*vertex) for vertex in vertices)


def points(vertices):
    return path(*vertices)


def move(p, dx, dy):
    point(*p)
    if type(dx) is not int or type(dy) is not int or not (-32 <= dx <= 32 and -32 <= dy <= 32):
        raise Bottom("range")
    return point(p[0] + dx, p[1] + dy)


def turn(p, quarters):
    point(*p)
    if type(quarters) is not int or not 0 <= quarters <= 3:
        raise Bottom("range")
    x, y = p[0] - 16, p[1] - 16
    for _ in range(quarters):
        x, y = -y, x
    return point(x + 16, y + 16)


def flip(p):
    point(*p)
    return point(32 - p[0], p[1])


def then(first, second, p):
    return second(first(p))


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def edges(vertices):
    return list(zip(vertices, vertices[1:] + vertices[:1]))


def on_segment(p, a, b):
    return cross(a, b, p) == 0 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def segments_meet(a, b, c, d):
    orientations = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    first, second, third, fourth = orientations
    return ((first == 0 and on_segment(c, a, b)) or
            (second == 0 and on_segment(d, a, b)) or
            (third == 0 and on_segment(a, c, d)) or
            (fourth == 0 and on_segment(b, c, d)) or
            ((first > 0) != (second > 0) and (third > 0) != (fourth > 0)))


def signed_area2(vertices):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in edges(vertices))


def rotate_start(vertices):
    start = min(range(len(vertices)), key=lambda index: vertices[index])
    return vertices[start:] + vertices[:start]


@dataclass(frozen=True)
class Ring:
    vertices: tuple

    def __init__(self, *vertices):
        if not 3 <= len(vertices) <= 24:
            raise Bottom("size")
        clean = path(*vertices)
        if len(set(clean)) != len(clean) or signed_area2(clean) == 0:
            raise Bottom("flat")
        for index, current in enumerate(clean):
            previous, following = clean[index - 1], clean[(index + 1) % len(clean)]
            if cross(previous, current, following) == 0 and (
                    (current[0] - previous[0]) * (following[0] - current[0]) +
                    (current[1] - previous[1]) * (following[1] - current[1]) < 0):
                raise Bottom("self_intersection")
        boundary = edges(clean)
        for index, (a, b) in enumerate(boundary):
            for other in range(index + 1, len(boundary)):
                if other == index + 1 or (index == 0 and other == len(boundary) - 1):
                    continue
                if segments_meet(a, b, *boundary[other]):
                    raise Bottom("self_intersection")
        object.__setattr__(self, "vertices", rotate_start(clean))


def twice_area(ring):
    return signed_area2(ring.vertices)


def translate(first, second, ring):
    moved = Ring(*(then(first, second, vertex) for vertex in ring.vertices))
    assert twice_area(moved) == twice_area(ring)
    return moved


def orientation(ring):
    return "CCW" if twice_area(ring) > 0 else "CW"


def location(ring, p):
    x, y = p
    if any(on_segment(p, a, b) for a, b in edges(ring.vertices)):
        return 0
    inside = False
    for a, b in edges(ring.vertices):
        if (a[1] > y) != (b[1] > y):
            crossing = Fraction(a[0] * (b[1] - a[1]) + (y - a[1]) * (b[0] - a[0]), b[1] - a[1])
            if crossing > x:
                inside = not inside
    return 1 if inside else -1


def boundaries_meet(first, second):
    return any(segments_meet(a, b, c, d) for a, b in edges(first.vertices) for c, d in edges(second.vertices))


@dataclass(frozen=True)
class Region:
    outer: Ring
    holes: tuple

    def __init__(self, outer, holes=()):
        holes = tuple(holes)
        if not isinstance(outer, Ring) or len(holes) > 4 or any(not isinstance(hole, Ring) for hole in holes):
            raise Bottom("size")
        if twice_area(outer) <= 0 or any(twice_area(hole) >= 0 for hole in holes):
            raise Bottom("orientation")
        for hole in holes:
            if boundaries_meet(outer, hole) or location(outer, hole.vertices[0]) != 1:
                raise Bottom("hole_outside")
        for index, hole in enumerate(holes):
            for other in holes[index + 1:]:
                if boundaries_meet(hole, other) or location(hole, other.vertices[0]) != -1 or location(other, hole.vertices[0]) != -1:
                    raise Bottom("holes_overlap")
        object.__setattr__(self, "outer", outer)
        object.__setattr__(self, "holes", tuple(sorted(holes, key=lambda item: item.vertices)))


def boundary_lattice(region):
    return sum(gcd(abs(b[0] - a[0]), abs(b[1] - a[1])) for ring in (region.outer,) + region.holes for a, b in edges(ring.vertices))


def interior_lattice(region):
    area2 = twice_area(region.outer) + sum(twice_area(hole) for hole in region.holes)
    count2 = area2 - boundary_lattice(region) + 2 * (1 - len(region.holes))
    assert count2 >= 0 and count2 % 2 == 0
    return count2 // 2


def isometry(transform, region):
    original = region.outer.vertices + tuple(vertex for hole in region.holes for vertex in hole.vertices)
    mapped = tuple(transform(vertex) for vertex in original)
    for index, first in enumerate(original):
        for other, second in enumerate(original[index + 1:], index + 1):
            if ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2 !=
                    (mapped[index][0] - mapped[other][0]) ** 2 + (mapped[index][1] - mapped[other][1]) ** 2):
                raise Bottom("not_isometry")
    outer = Ring(*(transform(vertex) for vertex in region.outer.vertices))
    holes = [Ring(*(transform(vertex) for vertex in hole.vertices)) for hole in region.holes]
    if twice_area(outer) < 0:
        outer = Ring(*reversed(outer.vertices))
        holes = [Ring(*reversed(hole.vertices)) for hole in holes]
    result = Region(outer, holes)
    assert interior_lattice(result) == interior_lattice(region)
    return result


def inside(region, p):
    point(*p)
    return location(region.outer, p) == 1 and all(location(hole, p) == -1 for hole in region.holes)


def signature(region):
    candidates = []
    for reflected in (False, True):
        for quarter in range(4):
            def transformed(vertex):
                x, y = vertex
                if reflected:
                    x = -x
                for _ in range(quarter):
                    x, y = -y, x
                return x, y

            raw_outer = tuple(transformed(vertex) for vertex in region.outer.vertices)
            raw_holes = [tuple(transformed(vertex) for vertex in hole.vertices) for hole in region.holes]
            all_vertices = raw_outer + tuple(vertex for hole in raw_holes for vertex in hole)
            minimum_x = min(vertex[0] for vertex in all_vertices)
            minimum_y = min(vertex[1] for vertex in all_vertices)

            def normalized(vertices, ccw):
                shifted = tuple((x - minimum_x, y - minimum_y) for x, y in vertices)
                if (signed_area2(shifted) > 0) != ccw:
                    shifted = shifted[::-1]
                return rotate_start(shifted)

            candidates.append((normalized(raw_outer, True), tuple(sorted(normalized(hole, False) for hole in raw_holes))))
    return min(candidates)


def congruent(first, second):
    return signature(first) == signature(second)


def overlap_lattice(first, second):
    return sum(inside(first, (x, y)) and inside(second, (x, y)) for x in range(33) for y in range(33))


def render(value):
    if isinstance(value, Ring):
        return "Ring<" + ",".join(str(vertex).replace(" ", "") for vertex in value.vertices) + ">"
    if isinstance(value, Region):
        return "Region<" + render(value.outer) + ",List<" + ",".join(render(hole) for hole in value.holes) + ">>"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return "(" + ",".join(render(item) for item in value) + ("," if len(value) == 1 else "") + ")"
    return str(value)


def fixtures():
    small = Ring((0, 0), (4, 0), (0, 4))
    outer = Ring((2, 2), (18, 2), (18, 16), (2, 16))
    first_hole = Ring((5, 5), (5, 9), (9, 9), (9, 5))
    second_hole = Ring((12, 5), (12, 9), (16, 5))
    region = Region(outer, (first_hole, second_hole))
    transformed = isometry(lambda p: move(turn(flip(p), 1), -8, -8), region)
    second = isometry(lambda p: move(turn(p, 2), -8, -8), region)
    shifted = isometry(lambda p: move(p, 1, 2), region)
    return small, region, transformed, second, shifted


def invert_target(source, target):
    matches = []
    target_min_x = min(vertex[0] for vertex in target.outer.vertices)
    target_min_y = min(vertex[1] for vertex in target.outer.vertices)
    for reflected in (False, True):
        for quarter in range(4):
            vertices = [turn(flip(p) if reflected else p, quarter) for p in source.outer.vertices]
            dx = target_min_x - min(vertex[0] for vertex in vertices)
            dy = target_min_y - min(vertex[1] for vertex in vertices)
            if -32 <= dx <= 32 and -32 <= dy <= 32:
                try:
                    candidate = isometry(lambda p: move(turn(flip(p) if reflected else p, quarter), dx, dy), source)
                    if candidate == target:
                        matches.append((reflected, quarter, dx, dy))
                except Bottom:
                    pass
    return matches


def verify():
    small, region, transformed, second, shifted = fixtures()
    tiny = Region(Ring((2, 2), (6, 2), (6, 6), (2, 6)))
    calculations = [
        small, twice_area(small), translate(lambda p: move(p, 1, 0), lambda p: move(p, 0, 1), small),
        orientation(small), region, boundary_lattice(region), interior_lattice(region), transformed,
        inside(region, (8, 6)), signature(tiny), congruent(region, transformed), overlap_lattice(region, shifted),
    ]
    cases = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert len(cases["tower"]) == len(calculations)
    for layer, computed in zip(cases["tower"], calculations):
        assert layer["value"] == render(computed), (layer["layer"], layer["value"], render(computed))
    answer_values = [
        (interior_lattice(region), boundary_lattice(region), overlap_lattice(region, shifted), overlap_lattice(transformed, second)),
        tuple(invert_target(region, transformed)),
        (congruent(region, transformed), congruent(region, second), overlap_lattice(transformed, second),
         overlap_lattice(region, shifted) == overlap_lattice(transformed, second)),
    ]
    for task, computed in zip(cases["showcase"], answer_values):
        assert task["answer"] == render(computed), (task["answer"], render(computed))
    assert not inside(region, (5, 5)) and not inside(region, (6, 6))
    assert points(path((2, 3), (3, 4))) == ((2, 3), (3, 4))
    assert sum(inside(region, (x, y)) for x in range(33) for y in range(33)) == interior_lattice(region)
    for reflected in (False, True):
        for quarter in range(4):
            variant = isometry(lambda vertex: turn(flip(vertex) if reflected else vertex, quarter), region)
            assert congruent(region, variant)
            assert interior_lattice(region) == interior_lattice(variant)
    for invalid in (lambda: Ring((0, 0), (2, 2), (0, 2), (2, 0)),
                    lambda: Ring((0, 0), (4, 0), (2, 0), (2, 2), (0, 2)),
                    lambda: Region(region.outer, (Ring(*reversed(region.outer.vertices)),)),
                    lambda: isometry(lambda vertex: point(vertex[0] + 1, vertex[1] + (vertex[1] % 2)), region)):
        try:
            invalid()
        except Bottom:
            pass
        else:
            raise AssertionError("invalid polygon accepted")
    print("OK")


if __name__ == "__main__":
    verify()
