"""Deep-world geometry programs; every construction is a kernel node tree."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom

from .story import (
    call,
    choose,
    increment,
    indexed,
    lit,
    next_vertex,
    test,
    var,
)


def ring_vertices(ring):
    return call("Ring.base", ring)


def outer(region):
    return call("RegionPair.outer", call("Region.base", region))


def holes(region):
    return call("RegionPair.holes", call("Region.base", region))


def point_in_box(point, first, second):
    return n.And(n.And(test("le", call("minimum", call("x", first), call("x", second)), call("x", point)),
                       test("le", call("x", point), call("maximum", call("x", first), call("x", second)))),
                 n.And(test("le", call("minimum", call("y", first), call("y", second)), call("y", point)),
                       test("le", call("y", point), call("maximum", call("y", first), call("y", second)))))


def location_body():
    vertices = ring_vertices(var("ring"))
    index = var("index")
    first, second = indexed(vertices, index), next_vertex(vertices, index)
    crossing = n.And(
        n.Not(test("eq", test_value("lt", call("y", var("p")), call("y", first)),
                   test_value("lt", call("y", var("p")), call("y", second)))),
        n.Test(choose(test("lt", call("y", first), call("y", second)),
                      test_value("lt", call("cross", first, second, var("p")), lit(0)),
                      test_value("lt", lit(0), call("cross", first, second, var("p"))))))
    boundary = n.And(test("eq", call("cross", first, second, var("p")), lit(0)),
                     point_in_box(var("p"), first, second))
    return n.Rec("location_loop", ("index", "parity"),
                 choose(test("eq", index, call("length", vertices)),
                        choose(n.Test(var("parity")), lit(1), lit(-1)),
                        choose(boundary, lit(0),
                               call("location_loop", increment(index),
                                    choose(crossing, choose(n.Test(var("parity")), lit(False), lit(True)),
                                           var("parity"))))),
                 (lit(0), lit(False)), call("sub", call("length", vertices), index))


def test_value(name, *args):
    return call(name, *args)


def boundaries_body():
    first_path = ring_vertices(var("a"))
    second_path = ring_vertices(var("b"))
    first_index, second_index = var("index_a"), var("index_b")
    search_second = n.Rec("search_b", ("index_b",),
                          choose(test("eq", second_index, call("length", second_path)), lit(False),
                                 choose(test("segments_meet", indexed(first_path, first_index),
                                             next_vertex(first_path, first_index), indexed(second_path, second_index),
                                             next_vertex(second_path, second_index)), lit(True),
                                        call("search_b", increment(second_index)))),
                          (lit(0),), call("sub", call("length", second_path), second_index))
    return n.Rec("search_a", ("index_a",),
                 choose(test("eq", first_index, call("length", first_path)), lit(False),
                        choose(n.Test(search_second), lit(True), call("search_a", increment(first_index)))),
                 (lit(0),), call("sub", call("length", first_path), first_index))


def region_valid():
    base = var("x")
    outer_ring = call("RegionPair.outer", base)
    all_holes = call("RegionPair.holes", base)
    index = var("hole_index")
    other = var("other_index")
    hole = indexed(all_holes, index)
    later = indexed(all_holes, other)
    no_overlap = n.Rec("later_holes", ("other_index",),
                       choose(test("eq", other, call("length", all_holes)), lit(True),
                              choose(n.Or(test("_boundaries_meet", hole, later),
                                          n.Or(test("eq", call("_locate", hole,
                                                               indexed(ring_vertices(later), lit(0))), lit(1)),
                                               test("eq", call("_locate", later,
                                                               indexed(ring_vertices(hole), lit(0))), lit(1)))),
                                     lit(False), call("later_holes", increment(other)))),
                       (increment(index),), call("sub", call("length", all_holes), other))
    validated = n.Rec("validate_holes", ("hole_index",),
                      choose(test("eq", index, call("length", all_holes)), lit(True),
                             choose(n.And(test("eq", call("orientation", hole), lit("CW")),
                                          n.And(n.Not(test("_boundaries_meet", outer_ring, hole)),
                                                n.And(test("eq", call("_locate", outer_ring,
                                                                      indexed(ring_vertices(hole), lit(0))), lit(1)),
                                                      n.Test(no_overlap)))),
                                    call("validate_holes", increment(index)), lit(False))),
                      (lit(0),), call("sub", call("length", all_holes), index))
    return choose(n.And(test("eq", call("orientation", outer_ring), lit("CCW")),
                        test("le", call("length", all_holes), lit(4))), validated, lit(False))


def region_canon():
    return call("RegionPair.shape", call("RegionPair.outer", var("x")),
                call("sorted_items", call("RegionPair.holes", var("x"))))


def boundary_body():
    all_rings = call("cons", outer(var("r")), holes(var("r")))
    rings_left = var("rings_left")
    ring_path = ring_vertices(call("head", rings_left))
    index = var("boundary_index")
    first, second = indexed(ring_path, index), next_vertex(ring_path, index)
    step = call("gcd", call("absolute", call("sub", call("x", second), call("x", first))),
                call("absolute", call("sub", call("y", second), call("y", first))))
    ring_count = n.Rec("boundary_ring", ("boundary_index", "total"),
                       choose(test("eq", index, call("length", ring_path)), var("total"),
                              call("boundary_ring", increment(index), call("add", var("total"), step))),
                       (lit(0), lit(0)), call("sub", call("length", ring_path), index))
    return n.Rec("boundary_regions", ("rings_left", "total_boundary"),
                 choose(test("empty", rings_left), var("total_boundary"),
                        call("boundary_regions", call("tail", rings_left),
                             call("add", var("total_boundary"), ring_count))),
                 (all_rings, lit(0)), call("length", rings_left))


def interior_body():
    all_holes = holes(call("points", var("r")))
    rest = var("remaining_holes")
    area_sum = n.Rec("hole_areas", ("remaining_holes", "area_total"),
                     choose(test("empty", rest), var("area_total"),
                            call("hole_areas", call("tail", rest),
                                 call("add", var("area_total"), call("twice_area", call("head", rest))))),
                     (all_holes, call("twice_area", outer(call("points", var("r"))))),
                     call("length", rest))
    return call("div", call("add", call("sub", area_sum, call("boundary_lattice", call("points", var("r")))),
                            call("mul", lit(2), call("sub", lit(1), call("length", all_holes)))), lit(2))


def mapped_path(path, slot, name):
    rest = var(name)
    item = call("head", rest)
    mapped = (call("move", item, var("dx"), var("dy")) if slot == "shift"
              else call(slot, item))
    return n.Rec(name + "_loop", (name,),
                 choose(test("empty", rest), lit(()),
                        call("cons", mapped,
                             call(name + "_loop", call("tail", rest)))),
                 (path,), call("length", rest))


def mapped_region(region, slot):
    mapped_outer = call("Ring.make", mapped_path(ring_vertices(outer(region)), slot, "outer_left"))
    ring = var("hole_ring")
    mapped_holes = n.Rec("map_holes", ("hole_tail",),
                         choose(test("empty", var("hole_tail")), lit(()),
                                n.Let("hole_ring", call("head", var("hole_tail")),
                                      call("cons", call("Ring.make", mapped_path(ring_vertices(ring), slot,
                                                                                 "hole_points")),
                                           call("map_holes", call("tail", var("hole_tail")))))),
                         (holes(region),), call("length", var("hole_tail")))
    return n.Let("mapped_outer", mapped_outer,
                 n.Let("mapped_holes", mapped_holes,
                       choose(test("lt", call("twice_area", var("mapped_outer")), lit(0)),
                              call("Region.make", call("RegionPair.shape",
                                                       call("Ring.make", call("reverse", ring_vertices(var("mapped_outer")))),
                                                       reversed_holes(var("mapped_holes")))),
                              call("Region.make", call("RegionPair.shape", var("mapped_outer"),
                                                       var("mapped_holes"))))))


def reversed_holes(rings):
    rest = var("reverse_hole_tail")
    return n.Rec("reverse_holes", ("reverse_hole_tail",),
                 choose(test("empty", rest), lit(()),
                        call("cons", call("Ring.make", call("reverse", ring_vertices(call("head", rest)))),
                             call("reverse_holes", call("tail", rest)))),
                 (rings,), call("length", rest))


def all_vertices(region):
    remaining = var("collect_holes")
    return n.Rec("collect_vertices", ("collect_holes", "vertices_so_far"),
                 choose(test("empty", remaining), var("vertices_so_far"),
                        call("collect_vertices", call("tail", remaining),
                             call("concat", var("vertices_so_far"),
                                  ring_vertices(call("head", remaining))))),
                 (holes(region), ring_vertices(outer(region))), call("length", remaining))


def squared_distance(first, second):
    dx = call("sub", call("x", first), call("x", second))
    dy = call("sub", call("y", first), call("y", second))
    return call("add", call("mul", dx, dx), call("mul", dy, dy))


def all_distances_match():
    before, after = var("original_vertices"), var("mapped_vertices")
    first, second = var("distance_first"), var("distance_second")
    inner = n.Rec("compare_second", ("distance_second",),
                  choose(test("eq", second, call("length", before)), lit(True),
                         choose(test("eq", squared_distance(indexed(before, first), indexed(before, second)),
                                     squared_distance(indexed(after, first), indexed(after, second))),
                                call("compare_second", increment(second)), lit(False))),
                  (increment(first),), call("sub", call("length", before), second))
    return n.Rec("compare_first", ("distance_first",),
                 choose(test("eq", first, call("length", before)), lit(True),
                        choose(n.Test(inner), call("compare_first", increment(first)), lit(False))),
                 (lit(0),), call("sub", call("length", before), first))


def isometry_body():
    result = mapped_region(var("r"), "f")
    return n.Let("mapped", result,
                 n.Let("original_vertices", all_vertices(var("r")),
                       n.Let("mapped_vertices", mapped_path(var("original_vertices"), "f", "distance_points"),
                             choose(n.And(n.Test(all_distances_match()),
                                          test("eq", call("interior_lattice", var("r")),
                                               call("interior_lattice", var("mapped")))),
                                    var("mapped"), lit(Bottom("not_isometry"))))))


def inside_body():
    observed = call("points", var("r"))
    region = indexed(observed, lit(0))
    vertex = indexed(observed, lit(1))
    rest = var("remaining_holes")
    hole_outside = n.Rec("exclude_holes", ("remaining_holes",),
                         choose(test("empty", rest), lit(True),
                                choose(test("eq", call("_locate", call("head", rest), vertex), lit(-1)),
                                       call("exclude_holes", call("tail", rest)), lit(False))),
                         (holes(region),), call("length", rest))
    return choose(test("eq", call("_locate", outer(region), vertex), lit(1)), hole_outside, lit(False))


def overlap_body():
    observed = call("points", var("r"))
    left, right = indexed(observed, lit(0)), indexed(observed, lit(1))
    left_bounds, right_bounds = bounds(left), bounds(right)
    min_x = call("maximum", indexed(var("left_bounds"), lit(0)), indexed(var("right_bounds"), lit(0)))
    min_y = call("maximum", indexed(var("left_bounds"), lit(1)), indexed(var("right_bounds"), lit(1)))
    max_x = call("minimum", indexed(var("left_bounds"), lit(2)), indexed(var("right_bounds"), lit(2)))
    max_y = call("minimum", indexed(var("left_bounds"), lit(3)), indexed(var("right_bounds"), lit(3)))
    vertex = call("point", var("scan_x"), var("scan_y"))
    inner = n.Rec("scan_column", ("scan_y", "column_total"),
                  choose(test("lt", var("max_y"), var("scan_y")), var("column_total"),
                         call("scan_column", increment(var("scan_y")),
                              choose(n.And(test("inside", call("cons", left, call("singleton", vertex))),
                                           test("inside", call("cons", right, call("singleton", vertex)))),
                                     increment(var("column_total")), var("column_total")))),
                  (var("min_y"), var("scan_total")),
                  call("sub", increment(var("max_y")), var("scan_y")))
    scan = n.Rec("scan_overlap", ("scan_x", "scan_total"),
                 choose(test("lt", var("max_x"), var("scan_x")), var("scan_total"),
                        call("scan_overlap", increment(var("scan_x")), inner)),
                 (var("min_x"), lit(0)), call("sub", increment(var("max_x")), var("scan_x")))
    return n.Let("left_bounds", left_bounds,
                 n.Let("right_bounds", right_bounds,
                       n.Let("min_x", min_x, n.Let("min_y", min_y,
                             n.Let("max_x", max_x, n.Let("max_y", max_y,
                                  choose(n.And(test("le", var("min_x"), var("max_x")),
                                               test("le", var("min_y"), var("max_y"))), scan, lit(0))))))))


def bounds(region):
    vertices = ring_vertices(outer(region))
    rest = var("bounds_left")
    vertex = call("head", rest)
    result = call("cons", var("min_x"), call("cons", var("min_y"),
                  call("cons", var("max_x"), call("singleton", var("max_y")))))
    return n.Rec("bound_scan", ("bounds_left", "min_x", "min_y", "max_x", "max_y"),
                 choose(test("empty", rest), result,
                        call("bound_scan", call("tail", rest),
                             call("minimum", var("min_x"), call("x", vertex)),
                             call("minimum", var("min_y"), call("y", vertex)),
                             call("maximum", var("max_x"), call("x", vertex)),
                             call("maximum", var("max_y"), call("y", vertex)))),
                 (vertices, lit(32), lit(32), lit(0), lit(0)), call("length", rest))


def normalize_body():
    source = var("r")
    region_bounds = bounds(source)
    return n.Let("normal_bounds", region_bounds,
                 n.Let("dx", call("sub", lit(0), indexed(var("normal_bounds"), lit(0))),
                       n.Let("dy", call("sub", lit(0), indexed(var("normal_bounds"), lit(1))),
                             mapped_region(source, "shift"))))


def signature_canon():
    variants = lit(())
    for index in reversed(range(8)):
        variant = (call("isometry", lit(kernel.FnRef("d4_0")), var("x")) if index == 0 else
                   mapped_region(var("x"), f"d4_{index}"))
        candidate = call("_normalize", variant)
        variants = call("cons", candidate, variants)
    return call("head", call("sorted_items", variants))


def congruent_body():
    first = call("Signature.make", var("a"))
    second = call("Signature.make", var("b"))
    return call("eq", call("Signature.base", first), call("Signature.base", second))


def definitions():
    locate_body = location_body()
    locate = Definition("_locate", "operation", "invented", 2,
                        tuple(sorted(n.references(locate_body))),
                        OperationSpec("_locate", "decide", (Edge("Ring"), Edge("Point")), Edge("int"),
                                      "Exact signed location of a lattice point relative to a ring.",
                                      extra={"input_names": ["ring", "p"]}), locate_body)
    border_body = boundaries_body()
    borders = Definition("_boundaries_meet", "operation", "invented", 2,
                         tuple(sorted(n.references(border_body))),
                         OperationSpec("_boundaries_meet", "decide", (Edge("Ring"), Edge("Ring")), Edge("bool"),
                                       "Detect any shared boundary points between two rings.",
                                       extra={"input_names": ["a", "b"]}), border_body)
    pair = Definition("RegionPair", "object", "invented", 1, (),
                      ObjectSpec("RegionPair", "compose", tags={"shape": (("outer", "Ring"), ("holes", "List[Ring]"))}), None)
    valid, canon = region_valid(), region_canon()
    region_body = n.Let("accepted", valid, canon)
    region = Definition("Region", "object", "invented", 4,
                        tuple(sorted(n.references(region_body))),
                        ObjectSpec("Region", "refine", base="RegionPair", valid=valid, canon=canon), region_body)
    boundary = boundary_body()
    counter = Definition("boundary_lattice", "operation", "invented", 5,
                         tuple(sorted(n.references(boundary))),
                         OperationSpec("boundary_lattice", "transform", (Edge("Region"),), Edge("int"),
                                       "Count lattice points along all oriented boundary edges.",
                                       extra={"input_names": ["r"]}), boundary)
    interior = interior_body()
    inside_count = Definition("interior_lattice", "observation", "invented", 6,
                              tuple(sorted(n.references(interior))),
                              ObservationSpec("interior_lattice", ("points",), interior), interior)
    return locate, borders, pair, region, counter, inside_count


def later_definitions():
    body = isometry_body()
    isometry = Definition("isometry", "combinator", "invented", 7,
                          tuple(sorted(n.references(body) - {"f"})),
                          CombinatorSpec("isometry", ("f", "r"), ("f",), body), body)
    body = inside_body()
    inside = Definition("inside", "observation", "invented", 5,
                        tuple(sorted(n.references(body))), ObservationSpec("inside", ("points",), body), body)
    body = overlap_body()
    overlap = Definition("overlap_lattice", "observation", "invented", 6,
                         tuple(sorted(n.references(body))),
                         ObservationSpec("overlap_lattice", ("points",), body), body)
    normal_body = normalize_body()
    normal = Definition("_normalize", "operation", "invented", 5,
                        tuple(sorted(n.references(normal_body))),
                        OperationSpec("_normalize", "transform", (Edge("Region"),), Edge("Region"),
                                      "Translate a valid region to the origin of its bounding box.",
                                      extra={"input_names": ["r"]}), normal_body)
    canon = signature_canon()
    valid = test_value("eq", call("Region.make", call("Region.base", var("x"))), var("x"))
    signature_body = n.Let("accepted", valid, canon)
    signature = Definition("Signature", "object", "invented", 8,
                           tuple(sorted(n.references(signature_body))),
                           ObjectSpec("Signature", "refine", base="Region", valid=valid,
                                      canon=canon), signature_body)
    body = congruent_body()
    congruent = Definition("congruent", "operation", "invented", 9,
                           tuple(sorted(n.references(body))),
                           OperationSpec("congruent", "relate", (Edge("Region"), Edge("Region")), Edge("bool"),
                                         "Compare exact dihedral canonical forms including all holes.",
                                         extra={"input_names": ["a", "b"]}), body)
    return isometry, inside, normal, signature, congruent, overlap


def d4_definitions():
    for index in range(8):
        vertex = var("p")
        body = call("turn", call("flip", vertex) if index >= 4 else vertex, lit(index % 4))
        yield Definition(f"d4_{index}", "operation", "invented", 1,
                         tuple(sorted(n.references(body))),
                         OperationSpec(f"d4_{index}", "transform", (Edge("Point"),), Edge("Point"),
                                       "One of eight exact reflections and quarter rotations around the lattice center.",
                                       extra={"input_names": ["p"]}), body)
    body = call("move", call("turn", call("flip", var("p")), lit(1)), lit(-8), lit(-8))
    yield Definition("flip_q1_shift", "operation", "invented", 1,
                     tuple(sorted(n.references(body))),
                     OperationSpec("flip_q1_shift", "transform", (Edge("Point"),), Edge("Point"),
                                   "Reflect, rotate once, and displace by (-8,-8).",
                                   extra={"input_names": ["p"]}), body)
    body = call("move", call("turn", var("p"), lit(2)), lit(-8), lit(-8))
    yield Definition("half_shift", "operation", "invented", 1,
                     tuple(sorted(n.references(body))),
                     OperationSpec("half_shift", "transform", (Edge("Point"),), Edge("Point"),
                                   "Rotate twice, then displace by (-8,-8).",
                                   extra={"input_names": ["p"]}), body)
