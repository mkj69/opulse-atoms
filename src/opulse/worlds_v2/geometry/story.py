"""Kernel-defined, bounded exact lattice geometry."""

from dataclasses import replace
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import bounded
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Card

from . import hosts
from .world import new_library


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def test(name, *args):
    return n.Test(call(name, *args))


def choose(condition, true, false):
    return n.Case(((condition, true),), false)


def increment(value):
    return call("add", value, lit(1))


def decrement(value):
    return call("sub", value, lit(1))


def indexed(vertices, index):
    return call("at", vertices, index)


def edge(vertices, index):
    return (indexed(vertices, index), indexed(vertices, call("div", increment(index), call("length", vertices))))


def next_vertex(vertices, index):
    return indexed(vertices, choose(test("eq", increment(index), call("length", vertices)), lit(0), increment(index)))


def signed_area(vertices):
    current = var("area_index")
    first = indexed(vertices, lit(0))
    area = call("cross", first, indexed(vertices, current), next_vertex(vertices, current))
    return n.Rec("area_loop", ("area_index", "total"),
                 choose(test("eq", current, decrement(call("length", vertices))), var("total"),
                        call("area_loop", increment(current), call("add", var("total"), area))),
                 (lit(1), lit(0)), call("sub", call("length", vertices), current))


def point_less(first, second):
    return n.Or(test("lt", call("x", first), call("x", second)),
                n.And(test("eq", call("x", first), call("x", second)),
                      test("lt", call("y", first), call("y", second))))


def valid_ring():
    vertices = var("x")
    size = call("length", vertices)
    index = var("ring_index")
    other = var("other_index")
    left = indexed(vertices, index)
    following = next_vertex(vertices, index)
    previous = indexed(vertices, choose(test("eq", index, lit(0)), decrement(size), decrement(index)))
    right = indexed(vertices, other)
    other_following = next_vertex(vertices, other)
    distinct = n.Rec("distinct_loop", ("other_index",),
                     choose(test("eq", other, size), lit(True),
                            choose(test("eq", left, right), lit(False),
                                   call("distinct_loop", increment(other)))),
                     (increment(index),), call("sub", size, other))
    no_crossing = n.Rec("meet_loop", ("other_index",),
                        choose(test("eq", other, size), lit(True),
                               choose(n.Or(test("eq", other, increment(index)),
                                           n.And(test("eq", index, lit(0)),
                                                 test("eq", other, decrement(size)))),
                                      call("meet_loop", increment(other)),
                                      choose(test("segments_meet", left, following, right, other_following),
                                             lit(False), call("meet_loop", increment(other))))),
                        (increment(index),), call("sub", size, other))
    dot = call("add", call("mul", call("sub", call("x", left), call("x", previous)),
                                  call("sub", call("x", following), call("x", left))),
               call("mul", call("sub", call("y", left), call("y", previous)),
                                  call("sub", call("y", following), call("y", left))))
    not_reversed = n.Not(n.And(test("eq", call("cross", previous, left, following), lit(0)),
                               test("lt", dot, lit(0))))
    check = n.Rec("ring_loop", ("ring_index",),
                  choose(test("eq", index, size), lit(True),
                         choose(n.And(not_reversed, n.And(n.Test(distinct), n.Test(no_crossing))),
                                call("ring_loop", increment(index)), lit(False))),
                  (lit(0),), call("sub", size, index))
    return choose(n.And(test("le", lit(3), size), test("le", size, lit(24))),
                  choose(test("eq", signed_area(vertices), lit(0)), lit(False), check), lit(False))


def canonical_ring():
    vertices = var("x")
    index = var("canon_index")
    best = var("best_index")
    candidate = indexed(vertices, index)
    current = indexed(vertices, best)
    iteration = n.Rec("canonical_start", ("canon_index", "best_index"),
                      choose(test("eq", index, call("length", vertices)), best,
                             call("canonical_start", increment(index),
                                  choose(point_less(candidate, current), index, best))),
                      (lit(1), lit(0)), call("sub", call("length", vertices), index))
    return call("rotate", vertices, iteration)


def twice_area_body():
    return signed_area(call("Ring.base", var("r")))


def translate_body():
    source = call("Ring.base", var("r"))
    rest = var("translate_rest")
    mapped = n.Rec("translate_loop", ("translate_rest",),
                   choose(test("empty", rest), lit(()),
                          call("cons", call("then", var("f"), var("g"), call("head", rest)),
                               call("translate_loop", call("tail", rest)))),
                   (source,), call("length", rest))
    result = call("Ring.make", mapped)
    return n.Let("translated", result,
                 choose(test("eq", call("twice_area", var("translated")), call("twice_area", var("r"))),
                        var("translated"), lit(Bottom("not_isometry"))))


def orientation_body():
    return choose(test("lt", lit(0), call("twice_area", call("points", var("r")))), lit("CCW"), lit("CW"))


def definitions():
    valid, canonical = valid_ring(), canonical_ring()
    ring_body = n.Let("accepted", valid, canonical)
    ring = Definition("Ring", "object", "invented", 1, tuple(sorted(n.references(ring_body))),
                      ObjectSpec("Ring", "refine", base="Path", valid=valid, canon=canonical), ring_body)
    area_body = twice_area_body()
    area = Definition("twice_area", "operation", "invented", 2,
                      tuple(sorted(n.references(area_body))), OperationSpec("twice_area", "transform", (Edge("Ring"),), Edge("int"),
                                                    "Signed shoelace double area of a valid ring.",
                                                    extra={"input_names": ["r"]}), area_body)
    move_body = translate_body()
    translate = Definition("translate", "combinator", "invented", 3,
                           tuple(sorted(n.references(move_body) - {"f", "g"})),
                           CombinatorSpec("translate", ("f", "g", "r"), ("f", "g"), move_body), move_body)
    observe_body = orientation_body()
    orientation = Definition("orientation", "observation", "invented", 3,
                             tuple(sorted(n.references(observe_body))),
                             ObservationSpec("orientation", ("points",), observe_body), observe_body)
    return ring, area, translate, orientation


def support_definitions():
    for name, dx, dy in (("shift_x", 1, 0), ("shift_y", 0, 1), ("shift_xy", 1, 2)):
        body = call("move", var("p"), lit(dx), lit(dy))
        yield Definition(name, "operation", "invented", 1, ("move",),
                         OperationSpec(name, "transform", (Edge("Point"),), Edge("Point"),
                                       "Translate a bounded point one lattice unit.",
                                       extra={"input_names": ["p"]}), body)


def reference_ring(vertices):
    from worlds.catalogue.depth import geometry as reference
    try:
        return reference.Ring(*(vertex.fields for vertex in vertices))
    except reference.Bottom:
        return Bottom("invalid")


def ring_card(reference_ring_value):
    return Card("Ring", "val", (tuple(hosts.point(*vertex) for vertex in reference_ring_value.vertices),))


def region_base(reference_region):
    return Card("RegionPair", "shape", (ring_card(reference_region.outer),
                                        tuple(ring_card(hole) for hole in reference_region.holes)))


def region_card(reference_region):
    return Card("Region", "val", (region_base(reference_region),))


def region_family():
    from worlds.catalogue.depth import geometry as reference
    cases = [reference.Region(reference.Ring((x_coord, y_coord), (x_coord + 8, y_coord),
                                             (x_coord + 8, y_coord + 8), (x_coord, y_coord + 8)),
                              (reference.Ring((x_coord + 3, y_coord + 3), (x_coord + 3, y_coord + 5),
                                              (x_coord + 5, y_coord + 5), (x_coord + 5, y_coord + 3)),))
             for x_coord, y_coord in product(range(7), repeat=2)]
    cases.append(reference.fixtures()[1])
    return tuple(cases)


def reference_region(value):
    from worlds.catalogue.depth import geometry as reference
    base = value.fields[0]
    return reference.Region(reference_ring(base.fields[0].fields[0]),
                            tuple(reference_ring(hole.fields[0]) for hole in base.fields[1]))


def small_region_family():
    from worlds.catalogue.depth import geometry as reference
    return tuple(reference.Region(reference.Ring((x_coord, y_coord), (x_coord + 2, y_coord),
                                                 (x_coord, y_coord + 2)))
                 for x_coord, y_coord in product(range(1, 8), range(1, 9)))


def build_library(*, stop_after=None):
    library = new_library()
    from worlds.catalogue.depth import geometry as reference
    points = tuple(hosts.point(x_coord, y_coord) for x_coord, y_coord in product(range(7), range(8)))
    paths = tuple((hosts.point(x_coord, y_coord), hosts.point(x_coord + 2, y_coord),
                   hosts.point(x_coord, y_coord + 2))
                  for x_coord, y_coord in product(range(5), repeat=2))
    paths += tuple(tuple(reversed(vertices)) for vertices in paths)
    rings = tuple(Card("Ring", "val", (tuple(hosts.point(*vertex) for vertex in reference_ring(vertices).vertices),))
                  for vertices in paths)
    from . import tower
    regions = region_family()
    small_regions = small_region_family()
    for definition in (*support_definitions(), *tower.d4_definitions(), *definitions(),
                       *tower.definitions(), *tower.later_definitions()):
        library.write(definition)
        library.check(definition.name)
        name = definition.name
        if name == "Ring":
            library.make_callable(name, ((paths[0],),))
            request = bounded((paths,), "bounded to 50 oriented triangles in 0..6 lattice")
        elif name in ("shift_x", "shift_y", "shift_xy", "half_shift", "flip_q1_shift") or name.startswith("d4_"):
            library.make_callable(name, ((points[0],),))
            request = bounded((points,), "bounded to 56 points, x in 0..6 and y in 0..7")
            def point_reference(vertex, operation=name):
                raw = vertex.fields
                if operation == "shift_x":
                    output = reference.move(raw, 1, 0)
                elif operation == "shift_y":
                    output = reference.move(raw, 0, 1)
                elif operation == "shift_xy":
                    output = reference.move(raw, 1, 2)
                elif operation == "half_shift":
                    output = reference.move(reference.turn(raw, 2), -8, -8)
                elif operation == "flip_q1_shift":
                    output = reference.move(reference.turn(reference.flip(raw), 1), -8, -8)
                else:
                    output = reference.turn(reference.flip(raw) if int(operation[-1]) >= 4 else raw,
                                            int(operation[-1]) % 4)
                return hosts.point(*output)
            request = replace(request, reference=point_reference)
        elif name == "twice_area":
            library.make_callable(name, ((rings[0],),))
            request = replace(bounded((rings,), "bounded to 50 oriented triangles in 0..6 lattice"),
                              reference=lambda ring: reference.twice_area(reference_ring(ring.fields[0])))
        elif name == "translate":
            library.make_callable(name, ((kernel.FnRef("shift_x"), kernel.FnRef("shift_y"), rings[0]),))
            examples = (ring_card(reference.fixtures()[0]),
                        ring_card(reference.Ring((2, 2), (6, 2), (2, 6))))
            request = bounded((rings[:48] + examples,),
                              "bounded to 48 small triangles and two displayed triangles under four shift pairs")
            family = ("shift_x", "shift_y")
            request = replace(request, scope={**request.scope, "op_family": list(family)},
                              extra={"op_family": family},
                              reference=lambda ops, inputs: Card("Ring", "val", (
                                  tuple(hosts.move(vertex,
                                                   int(ops["f"] == "shift_x") + int(ops["g"] == "shift_x"),
                                                   int(ops["f"] == "shift_y") + int(ops["g"] == "shift_y"))
                                        for vertex in inputs[0].fields[0]),)))
        elif name == "orientation":
            library.make_callable(name, ((rings[0],),))
            request = replace(bounded((rings,), "bounded to 50 oriented triangles in 0..6 lattice"),
                              reference=lambda ring: reference.orientation(reference_ring(ring.fields[0])))
        elif name == "_locate":
            library.make_callable(name, ((rings[0], hosts.point(1, 1)),))
            domain = tuple((ring, hosts.point(index % 6, (index // 6) % 6)) for index, ring in enumerate(rings))
            request = replace(bounded((domain,), "bounded to 50 oriented triangles and indexed points in 0..6 lattice"),
                              domain=domain,
                              reference=lambda ring, vertex: reference.location(reference_ring(ring.fields[0]), vertex.fields))
            request = replace(request, scope={**request.scope, "size": len(domain)})
        elif name == "_boundaries_meet":
            library.make_callable(name, ((rings[0], rings[1]),))
            domain = tuple((ring, rings[(index + 1) % len(rings)]) for index, ring in enumerate(rings))
            request = replace(bounded((domain,), "bounded to 50 oriented triangle pairs in 0..6 lattice"),
                              domain=domain, reference=lambda first, second:
                              reference.boundaries_meet(reference_ring(first.fields[0]),
                                                        reference_ring(second.fields[0])))
            request = replace(request, scope={**request.scope, "size": len(domain)})
        elif name == "RegionPair":
            sample = region_base(regions[-1])
            library.make_callable(name, ((sample.fields[0], sample.fields[1]),))
            request = bounded((tuple(region_base(case) for case in regions),),
                              "bounded to 49 translated one-hole squares and one two-hole region (50 cases)")
        elif name == "Region":
            library.make_callable(name, ((region_base(small_regions[0]),),))
            request = bounded((tuple(region_base(case) for case in regions),),
                              "bounded to 49 translated one-hole squares and one two-hole region (50 cases)")
        elif name == "boundary_lattice":
            library.make_callable(name, ((region_card(small_regions[0]),),))
            request = replace(bounded((tuple(region_card(case) for case in regions),),
                                      "bounded to 49 translated one-hole squares and one two-hole region (50 cases)"),
                              reference=lambda region: reference.boundary_lattice(
                                  reference.Region(reference_ring(region.fields[0].fields[0].fields[0]),
                                                   tuple(reference_ring(hole.fields[0]) for hole in region.fields[0].fields[1]))))
        elif name == "interior_lattice":
            library.make_callable(name, ((region_card(regions[-1]),),))
            request = replace(bounded((tuple(region_card(case) for case in regions),),
                                      "bounded to 49 translated one-hole squares and one two-hole region (50 cases)"),
                              reference=lambda region: reference.interior_lattice(reference_region(region)))
        elif name == "isometry":
            library.make_callable(name, ((kernel.FnRef("shift_x"), region_card(regions[-1])),))
            family = ("shift_x", "shift_y", "flip_q1_shift")
            request = bounded((tuple(region_card(case) for case in small_regions[:48]) +
                               (region_card(reference.fixtures()[1]), region_card(regions[3])),),
                              "bounded to 48 triangles and two displayed holed regions under three transforms")
            request = replace(request, scope={**request.scope, "op_family": list(family)},
                              extra={"op_family": family}, reference=lambda ops, inputs:
                              region_card(reference.isometry(
                                  lambda vertex: (reference.move(reference.turn(reference.flip(vertex), 1), -8, -8)
                                                  if ops["f"] == "flip_q1_shift" else
                                                  reference.move(vertex, int(ops["f"] == "shift_x"),
                                                                 int(ops["f"] == "shift_y"))),
                                  reference_region(inputs[0]))))
        elif name == "inside":
            library.make_callable(name, (((region_card(regions[-1]), hosts.point(8, 6)),),))
            domain = tuple(((region_card(case), hosts.point(index % 11, (index // 5) % 11)),)
                           for index, case in enumerate(small_regions))
            request = replace(bounded((domain,), "bounded to 56 triangular regions and points in 0..10 square"),
                              domain=domain, scope={"domain": "bounded to 56 triangular regions and points in 0..10 square",
                                                   "description": "bounded to 56 triangular regions and points in 0..10 square",
                                                   "size": len(domain)},
                              reference=lambda observed: reference.inside(reference_region(observed[0]),
                                                                          observed[1].fields))
        elif name == "_normalize":
            library.make_callable(name, ((region_card(regions[-1]),),))
            request = replace(bounded((tuple(region_card(case) for case in small_regions),),
                                      "bounded to 56 translated triangular regions"),
                              reference=lambda region: region_card(reference.isometry(
                                  lambda vertex: reference.move(vertex,
                                                                -min(p[0] for p in reference_region(region).outer.vertices),
                                                                -min(p[1] for p in reference_region(region).outer.vertices)),
                                  reference_region(region))))
        elif name == "Signature":
            library.make_callable(name, ((region_card(small_regions[0]),),))
            request = bounded((tuple(region_card(case) for case in small_regions[:50]),),
                              "bounded to 50 translated triangular regions")
        elif name == "congruent":
            library.make_callable(name, ((region_card(small_regions[0]), region_card(small_regions[1])),))
            domain = tuple((region_card(small_regions[index]), region_card(small_regions[(index + 7) % 56]))
                           for index in range(50))
            description = ("bounded to 50 pairs of translated triangular regions: "
                           "50 independent reference comparisons and one complete kernel unfold")
            request = replace(bounded((domain,), description),
                              domain=domain, scope={"domain": description,
                                                   "description": description,
                                                   "size": len(domain)},
                              reference=lambda first, second: reference.congruent(reference_region(first),
                                                                                  reference_region(second)))
        elif name == "overlap_lattice":
            library.make_callable(name, (((region_card(regions[-1]), region_card(regions[-1])),),))
            domain = tuple(((region_card(small_regions[index]), region_card(small_regions[(index + 7) % 56])),)
                           for index in range(50))
            request = replace(bounded((domain,), "bounded to 50 translated triangular region pairs on 33x33 grid"),
                              domain=domain, scope={"domain": "bounded to 50 translated triangular region pairs on 33x33 grid",
                                                   "description": "bounded to 50 translated triangular region pairs on 33x33 grid",
                                                   "size": len(domain)},
                              reference=lambda observed: reference.overlap_lattice(
                                  reference_region(observed[0]), reference_region(observed[1])))
        else:
            continue
        library.verify(name, request)
        if definition.kind == "combinator":
            checked = library.get(name)
            scope = {key: value for key, value in checked.evidence.scope.items() if key != "fixed_ops" or value}
            library._definitions[name] = replace(checked, evidence=replace(checked.evidence, scope=scope))
        library.account(name)
        library.promote(name, Contract("Exact lattice geometry within the recorded finite family."))
        if name == stop_after:
            return library
    from .templates import install_templates

    install_templates(library)
    return library
