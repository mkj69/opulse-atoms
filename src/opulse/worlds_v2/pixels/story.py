"""Twelve kernel-defined constructions over rectangular public pixel grids."""

import importlib.util
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    compute_layer,
)
from opulse.atoms.values import Bottom, Card
from opulse.worlds_v2.pixels import hosts
from opulse.worlds_v2.pixels.world import new_library


@lru_cache(maxsize=1)
def oracle():
    source = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/pixels.py"
    spec = importlib.util.spec_from_file_location("pixels_depth_oracle", source)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def convert(value):
    reference = oracle()
    if isinstance(value, bool):
        return hosts.boolean(value)
    if isinstance(value, reference.Grid):
        return hosts.to_card(value.rows)
    if isinstance(value, reference.Island):
        return Card("Island", "val", (hosts.to_card(value.image.rows),))
    if isinstance(value, reference.Shape):
        return Card("Shape", "val", (convert(reference.Island(value.image)),))
    if isinstance(value, tuple) and len(value) == 2 and all(type(part) is int for part in value):
        return hosts.point(*value)
    if isinstance(value, (list, tuple)):
        return hosts.list_of(*(convert(item) for item in value))
    return value


def object_rows(value):
    while isinstance(value, Card) and value.sort in ("Island", "Shape") and value.tag == "val" and len(value.fields) == 1:
        value = value.fields[0]
    return hosts.from_card(value)


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


EMPTY = lit(hosts.list_of())


def test(name, *args):
    return n.Test(call(name, *args))


def when(condition, yes, no):
    return n.Case(((condition, yes),), no)


def fold(items, initial, update, name="fold", item_name="item"):
    body = when(test("is_empty", var("items")), var("result"),
                n.Let(item_name, call("head", var("items")),
                      call(name, call("tail", var("items")), update)))
    return n.Rec(name, ("items", "result"), body, (items, initial), call("length", var("items")))


def points(image):
    row_points = n.Rec("point_row", ("columns", "line"),
                       when(test("is_empty", var("columns")), EMPTY,
                            call("cons", call("point", call("head", var("columns")), var("line")),
                                 call("point_row", call("tail", var("columns")), var("line")))),
                       (call("range_int", call("width", image)), var("row")), call("length", var("columns")))
    return n.Rec("point_rows", ("lines",),
                 when(test("is_empty", var("lines")), EMPTY,
                      n.Let("row", call("head", var("lines")),
                            call("concat", row_points, call("point_rows", call("tail", var("lines")))))),
                 (call("range_int", call("height", image)),), call("length", var("lines")))


def selected(image, lit_flag=True):
    return fold(points(image), EMPTY,
                when(test("eq", call("cell", image, var("item")), lit(hosts.boolean(lit_flag))),
                     call("concat", var("result"), call("cons", var("item"), EMPTY)), var("result")),
                "selected_points")


def neighbors(position):
    x_value, y_value = var("neighbor_x"), var("neighbor_y")
    return n.Let("neighbor_x", call("x_coord", position),
                 n.Let("neighbor_y", call("y_coord", position),
                       call("list4", call("point", call("sub", x_value, lit(1)), y_value),
                            call("point", call("add", x_value, lit(1)), y_value),
                            call("point", x_value, call("sub", y_value, lit(1))),
                            call("point", x_value, call("add", y_value, lit(1))))))


def inside(image, position):
    return n.And(n.And(test("lt", lit(-1), call("x_coord", position)),
                       test("lt", call("x_coord", position), call("width", image))),
                 n.And(test("lt", lit(-1), call("y_coord", position)),
                       test("lt", call("y_coord", position), call("height", image))))


def reach(image, seed, lit_flag=True):
    candidate_valid = n.And(inside(image, var("candidate")),
                            n.And(test("eq", call("cell", image, var("candidate")), lit(hosts.boolean(lit_flag))),
                                  n.And(n.Not(test("member", var("candidate"), var("seen"))),
                                        n.And(n.Not(test("member", var("candidate"), var("rest"))),
                                              n.Not(test("member", var("candidate"), var("fresh")))))))
    new_neighbors = n.Rec("check_neighbors", ("candidates", "fresh"),
                          when(test("is_empty", var("candidates")), var("fresh"),
                               n.Let("candidate", call("head", var("candidates")),
                                     call("check_neighbors", call("tail", var("candidates")),
                                          when(candidate_valid,
                                               call("concat", var("fresh"), call("cons", var("candidate"), EMPTY)),
                                               var("fresh"))))),
                          (neighbors(var("current")), EMPTY), call("length", var("candidates")))
    body = when(test("is_empty", var("pending")), var("seen"),
                n.Let("current", call("head", var("pending")),
                      n.Let("rest", call("tail", var("pending")),
                            call("walk_reach", call("concat", var("rest"), new_neighbors),
                                 call("cons", var("current"), var("seen"))))))
    return n.Rec("walk_reach", ("pending", "seen"), body,
                 (call("cons", seed, EMPTY), EMPTY), "fuel")


def regions(image, lit_flag=True):
    body = when(test("is_empty", var("remaining")), var("groups"),
                n.Let("component", reach(image, call("head", var("remaining")), lit_flag),
                      call("scan_regions", call("without", var("remaining"), var("component")),
                           call("cons", var("component"), var("groups")))))
    return n.Rec("scan_regions", ("remaining", "groups"), body,
                 (selected(image, lit_flag), EMPTY), call("length", var("remaining")))


def paint(image, cells):
    return fold(cells, call("empty_grid", image), call("light", var("result"), var("item")), "paint_points")


def island_body():
    return when(n.And(test("eq", call("grid", call("rows", var("x"))), var("x")),
                      test("eq", call("islands", var("x")), lit(1))), lit(True), lit(False))


def flood_body():
    return when(n.Not(inside(var("image"), var("position"))), call("fail", lit("range")),
                when(n.Not(test("cell", var("image"), var("position"))), call("fail", lit("empty")),
                     call("Island.make", paint(var("image"), reach(var("image"), var("position"))))))


def grow_body():
    image = var("image")
    def update():
        return fold(neighbors(var("item")), var("result"),
                    when(inside(image, var("neighbor")), call("light", var("result"), var("neighbor")), var("result")),
                    "grow_neighbors", "neighbor")
    expanded = fold(selected(image), image, update(), "grow_cells")
    return n.Let("image", call("Island.base", var("arg0")), call("Island.make", expanded))


def map_body():
    group = call("head", var("groups"))
    transformed = call("f", call("flood", var("image"), call("head", group)))
    mapped = var("mapped_grid")
    good = n.And(test("eq", call("width", mapped), call("width", var("image"))),
                 test("eq", call("height", mapped), call("height", var("image"))))
    merge = fold(selected(mapped), var("result"), call("light", var("result"), var("item")), "merge_component")
    body = when(test("is_empty", var("groups")), var("result"),
                n.Let("mapped", transformed,
                      n.Let("mapped_grid", call("unwrap", var("mapped")),
                            when(good, call("each_component", call("tail", var("groups")), merge),
                                 call("fail", lit("shape"))))))
    return n.Rec("each_component", ("groups", "result"), body,
                 (regions(var("image")), call("empty_grid", var("image"))),
                 call("length", var("groups")))


def touches(image, component):
    position = var("item")
    edge = n.Or(n.Or(test("eq", call("x_coord", position), lit(0)),
                      test("eq", call("y_coord", position), lit(0))),
                n.Or(test("eq", call("x_coord", position), call("sub", call("width", image), lit(1))),
                     test("eq", call("y_coord", position), call("sub", call("height", image), lit(1)))))
    return fold(component, lit(False), when(edge, lit(True), var("result")), "touches_edge")


def holes_body():
    return fold(regions(var("arg0"), False), lit(0),
                when(n.Test(touches(var("arg0"), var("item"))), var("result"),
                     call("add", var("result"), lit(1))), "count_holes")


def shape_body():
    image = var("image")
    cells = var("cells")
    def extremum(direction, operation, initial):
        return fold(cells, initial, call(operation, var("result"), call(direction, var("item"))),
                    "extent_" + operation + "_" + direction)
    left, top = extremum("x_coord", "min_int", call("width", image)), extremum("y_coord", "min_int", call("height", image))
    right, bottom = extremum("x_coord", "max_int", lit(0)), extremum("y_coord", "max_int", lit(0))
    shifted = call("point", call("sub", call("x_coord", var("item")), var("left")),
                   call("sub", call("y_coord", var("item")), var("top")))
    body = fold(cells, call("blank", call("add", call("sub", right, var("left")), lit(1)),
                             call("add", call("sub", bottom, var("top")), lit(1))),
                call("light", var("result"), shifted), "crop_cells")
    return n.Let("image", call("Island.base", var("x")),
                 n.Let("cells", selected(image),
                       n.Let("left", left, n.Let("top", top, call("Island.make", body)))))


def turn_body():
    image = var("image")
    result = fold(selected(image), call("blank", call("height", image), call("width", image)),
                  call("light", var("result"),
                       call("point", call("sub", call("sub", call("height", image), lit(1)),
                                              call("y_coord", var("item"))), call("x_coord", var("item")))),
                  "turn_points")
    return n.Let("image", call("Island.base", call("Shape.base", var("arg0"))),
                 call("Shape.make", call("Island.make", result)))


def mirror_body():
    image = var("image")
    result = fold(selected(image), call("empty_grid", image),
                  call("light", var("result"),
                       call("point", call("sub", call("sub", call("width", image), lit(1)),
                                              call("x_coord", var("item"))), call("y_coord", var("item")))),
                  "mirror_points")
    return n.Let("image", call("Island.base", call("Shape.base", var("arg0"))),
                 call("Shape.make", call("Island.make", result)))


def dihedral_body():
    names = ("original", "rotated1", "rotated2", "rotated3",
             "reflected", "reflected1", "reflected2", "reflected3")
    result = call("list8", *(call("f", var(name)) for name in names))
    for name, previous in reversed(tuple(zip(names[1:], names[:-1]))):
        source = "original" if name == "reflected" else previous
        transform = "mirror" if name == "reflected" else "turn"
        result = n.Let(name, call(transform, var(source)), result)
    return n.Let("original", var("arg0"), result)


def signature_body():
    public_grid = call("grid", call("pixels", var("arg0")))
    public_shape = call("Shape.make", call("Island.make", public_grid))
    variants = call("dihedral", lit(kernel.FnRef("identity")), public_shape)
    patterns = fold(variants, EMPTY,
                    call("cons", call("text_concat", call("text_concat", call("text_concat",
                                      call("text_concat", call("text_pad2", call("height", var("item"))), lit("x")),
                                      call("text_pad2", call("width", var("item")))), lit(":")),
                                      call("text_join", lit("/"), call("rows", var("item")))),
                         var("result")), "shape_patterns")
    return call("text_min", patterns)


def equivalent_body():
    def signatures(image, suffix):
        result = fold(regions(image), EMPTY,
                      call("cons", call("signature", call("Shape.make", call("flood", image,
                                                                            call("head", var("item"))))), var("result")),
                      "component_signatures_" + suffix)
        return call("sorted_list", result)
    return call("eq", signatures(var("first"), "first"), signatures(var("second"), "second"))


def scan_body():
    return fold(points(var("image")), EMPTY,
                when(n.And(n.Not(test("cell", var("image"), var("item"))),
                           test("eq", call("f", call("light", var("image"), var("item"))), var("target"))),
                     call("concat", var("result"), call("cons", var("item"), EMPTY)), var("result")),
                "scan_candidates")


def definitions():
    entries = []
    def add(name, kind, body, sorts, output, params=None, op_params=()):
        if kind == "combinator":
            spec = CombinatorSpec(name, params, op_params, body)
        elif kind == "object":
            spec = ObjectSpec(name, "refine", base="grid" if name == "Island" else "Island",
                              valid=body if name == "Island" else
                              when(n.And(test("eq", call("Island.make", call("Island.base", var("x"))), var("x")),
                                         test("eq", call("islands", call("Island.base", var("x"))), lit(1))),
                                   lit(True), lit(False)),
                              canon=body if name == "Shape" else None)
        elif kind == "observation":
            spec = ObservationSpec(name, ("pixels",), body)
        else:
            spec = OperationSpec(name, "decide" if output in ("int", "bool") else "transform",
                                 tuple(Edge(sort, name=param) for sort, param in zip(sorts, params)),
                                 Edge(output), "Kernel-defined pixel construction.",
                                 extra={"input_names": list(params)})
        dependencies = n.all_dependencies(body) - (set(op_params) if kind == "combinator" else set())
        layer = compute_layer(dependencies, lambda dependency: next(
            (entry.layer for entry in entries if entry.name == dependency.split(".")[0]), 0))
        if kind == "object":
            body = None
            dependencies = n.references(spec.valid) | (n.references(spec.canon) if spec.canon else set())
        entries.append(Definition(name, kind, "invented", layer, tuple(sorted(dependencies)), spec, body))

    add("islands", "observation",
        call("length", regions(call("grid", call("pixels", var("arg0"))))), ("grid",), "int")
    add("Island", "object", island_body(), ("grid",), "island")
    add("flood", "operation", flood_body(), ("grid", "point"), "island", ("image", "position"))
    add("grow", "operation", grow_body(), ("island",), "island", ("arg0",))
    add("map_components", "combinator", map_body(), (), "grid", ("f", "image"), ("f",))
    add("holes", "observation", n.Let("arg0", call("grid", call("pixels", var("arg0"))), holes_body()),
        ("grid",), "int")
    add("Shape", "object", shape_body(), ("island",), "shape")
    add("turn", "operation", turn_body(), ("shape",), "shape", ("arg0",))
    add("mirror", "operation", mirror_body(), ("shape",), "shape", ("arg0",))
    add("dihedral", "combinator", dihedral_body(), (), "list", ("f", "arg0"), ("f",))
    add("signature", "observation", signature_body(), ("shape",), "str")
    add("euler", "operation", call("sub", call("islands", var("arg0")), call("holes", var("arg0"))),
        ("grid",), "int", ("arg0",))
    add("equivalent", "operation", equivalent_body(), ("grid", "grid"), "bool", ("first", "second"))
    add("scan_add", "combinator", scan_body(), (), "list", ("f", "image", "target"), ("f",))
    return entries


def test_inputs():
    reference = oracle()
    small = reference.Grid(("##.", "...", ".#."))
    connected = reference.Grid(("##.", ".#.", "..."))
    shape_grid = reference.Grid(("###", "#.."))
    image = convert(small)
    blob = convert(reference.Island(connected))
    asymmetric = convert(reference.Shape.make(reference.Island(shape_grid)))
    return {
        "islands": (image,), "Island": (convert(connected),),
        "flood": (image, hosts.point(0, 0)), "grow": (blob,),
        "map_components": (kernel.FnRef("grow"), image),
        "holes": (image,), "Shape": (blob,), "turn": (asymmetric,), "mirror": (asymmetric,),
        "dihedral": (kernel.FnRef("identity"), asymmetric), "signature": (asymmetric,),
        "euler": (image,), "equivalent": (image, image),
        "scan_add": (kernel.FnRef("euler"), image, 1),
    }


def combinator_reference(name, assignment, inputs):
    reference = oracle()
    image = reference.Grid(hosts.from_card(inputs[0]))
    function = ((lambda shape: reference.dihedral(reference.identity, shape)[1])
                if assignment["f"] == "turn" else getattr(reference, assignment["f"]))
    if name == "map_components":
        return convert(reference.map_components(function, image))
    if name == "dihedral":
        return convert(reference.dihedral(function, reference.Shape(image)))
    return convert(reference.scan_add(function, image, inputs[1]))


def reference_result(name, *args):
    reference = oracle()
    def unpack(value):
        if isinstance(value, Card) and value.sort in ("grid", "Island", "Shape"):
            grid_value = reference.Grid(object_rows(value))
            return reference.Grid(grid_value.rows) if value.sort == "grid" else (
                reference.Island(grid_value) if value.sort == "Island" else reference.Shape(grid_value))
        if isinstance(value, Card) and value.sort == "point":
            return tuple(value.fields)
        return value
    converted = [unpack(value) for value in args]
    actions = {
        "islands": reference.islands, "Island": reference.Island, "flood": reference.flood,
        "grow": reference.grow, "holes": reference.holes, "Shape": reference.Shape.make,
        "turn": lambda shape: reference.dihedral(reference.identity, shape)[1],
        "mirror": lambda shape: reference.dihedral(reference.identity, shape)[4],
        "signature": reference.signature, "euler": reference.euler, "equivalent": reference.equivalent,
    }
    try:
        return convert(actions[name](*converted))
    except reference.Bottom as error:
        return Bottom(str(error))


def depth_encode(value):
    reference = oracle()
    if isinstance(value, Card) and value.sort == "bool":
        return reference.encode(value.tag == "true")
    if isinstance(value, Card) and value.sort in ("grid", "Island", "Shape"):
        image = reference.Grid(object_rows(value))
        if value.sort == "Island":
            image = reference.Island(image)
        if value.sort == "Shape":
            image = reference.Shape(image)
        return reference.encode(image)
    if isinstance(value, Card) and value.sort == "point":
        return reference.encode(tuple(value.fields))
    if isinstance(value, Card) and value.sort == "list":
        return "List<" + ", ".join(depth_encode(item) for item in value.fields) + ">"
    return reference.encode(value)


@lru_cache(maxsize=1)
def verification_inputs():
    reference = oracle()
    grids = tuple(reference.grid(3, 3, {(index % 3, index // 3)
                                        for index in range(9) if mask & (1 << index)})
                  for mask in range(512))
    cards = tuple(convert(image) for image in grids)
    connected = tuple(convert(reference.Island(image)) for image in grids if reference.islands(image) == 1)
    shapes = tuple(dict.fromkeys(convert(reference.Shape.make(reference.Island(image))) for image in grids
                                     if reference.islands(image) == 1))
    lit_seeds = tuple((image, hosts.point(index % 3, index // 3)) for image in cards
                      for index in range(9) if hosts.cell(image, hosts.point(index % 3, index // 3)) == hosts.boolean(True))
    pair_family = (cards[0], cards[1], cards[2], cards[3], cards[7], cards[15], cards[31], cards[511])
    scan_family = tuple(image for mask, image in enumerate(cards) if mask.bit_count() >= 6)[:50]
    return {
        "islands": tuple((image,) for image in cards),
        "Island": tuple((image,) for image in cards),
        "flood": lit_seeds,
        "grow": tuple((image,) for image in connected),
        "map_components": tuple((image,) for image in cards),
        "holes": tuple((image,) for image in cards),
        "Shape": tuple((image,) for image in connected),
        "turn": tuple((image,) for image in shapes),
        "mirror": tuple((image,) for image in shapes),
        "dihedral": tuple((image,) for image in shapes),
        "signature": tuple((image,) for image in shapes),
        "euler": tuple((image,) for image in cards),
        "equivalent": tuple((first, second) for first in pair_family for second in pair_family),
        "scan_add": tuple((image, target) for image in scan_family for target in (0, 1)),
    }


def build_library(evidence_fixture=None, limit=None):
    library = new_library()
    examples = test_inputs()
    domains = verification_inputs()
    for definition in definitions()[:limit]:
        library.write(definition)
        library.check(definition.name)
        args = examples[definition.name]
        library.make_callable(definition.name, (args,))
        if definition.kind == "combinator":
            family = {"map_components": ("grow", "identity"),
                      "dihedral": ("identity", "turn"),
                      "scan_add": ("euler", "islands")}[definition.name]
            domain = domains[definition.name]
            descriptions = {
                "map_components": "all 512 3x3 grids",
                "dihedral": "all 151 distinct canonical shapes from connected 3x3 grids",
                "scan_add": "50 first 3x3 grids with at least six lit cells and targets 0 and 1",
            }
            description = (f"bound: {descriptions[definition.name]}, {len(domain)} input tuples per slot "
                           f"and operation family {family}")
            request = VerifyRequest("bounded", domain,
                                    {"domain": description, "description": description,
                                     "size": len(domain), "op_family": list(family)},
                                    extra={"op_family": family},
                                    reference=lambda assignment, inputs, name=definition.name:
                                        combinator_reference(name, assignment, inputs))
        else:
            domain = domains[definition.name]
            descriptions = {
                "flood": "all 2304 lit start points across all 512 3x3 grids",
                "grow": "all 218 connected 3x3 islands",
                "Shape": "all 218 connected 3x3 islands",
                "turn": "all 151 distinct canonical shapes from connected 3x3 grids",
                "mirror": "all 151 distinct canonical shapes from connected 3x3 grids",
                "signature": "all 151 distinct canonical shapes from connected 3x3 grids",
                "equivalent": "all 64 ordered pairs from masks 0,1,2,3,7,15,31,511 on 3x3 grids",
            }
            description = descriptions.get(definition.name, "all 512 3x3 grids")
            method = "exhaustive" if definition.name in {"islands", "Island", "holes", "euler"} else "bounded"
            description = description if method == "exhaustive" else f"bound: {description}"
            request = VerifyRequest(method, domain,
                                    {"domain": description, "description": description, "size": len(domain)},
                                    extra={"fuel": 4_000_000} if definition.kind == "operation" else {},
                                    reference=lambda *values, name=definition.name: reference_result(name, *values))
        library.verify(definition.name, request)
        library.account(definition.name)
        if evidence_fixture is not None:
            saved = evidence_fixture[definition.name]
            if (library.get(definition.name).evidence.to_dict() != saved["evidence"] or
                    library.get(definition.name).cost.to_dict() != saved["cost"]):
                raise ValueError(f"stale 3x3 evidence fixture for {definition.name}")
        library.promote(definition.name, Contract(f"{definition.name} agrees with the bounded reference"))
    return library
