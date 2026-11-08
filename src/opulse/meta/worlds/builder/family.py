"""Finite modular-world template family (atoms-meta section 6; atoms-v2 section 19.3)."""

from opulse.atoms import library
from opulse.atoms import nodes as n
from opulse.atoms.spec import Contract, Definition, Edge, OperationSpec, TemplateSpec
from opulse.atoms.values import Card
from opulse.meta import generators
from opulse.meta.builder import world_value as V
from opulse.meta.worlds.builder import hosts, story, world


def modular_world(size):
    """Independent finite-table oracle used only for evidence, never invented bodies."""
    return V.world(f"zn{size}", 1, [V.range_sort("digit", 0, size - 1)],
                   [V.table("add", "combine", ["digit", "digit"], "digit", [],
                            [V.row([left, right], V.val((left + right) % size))
                             for left in range(size) for right in range(size)])],
                   ["Var", "Lit", "Call", "Let", "Case", "Rec"], "measure", [],
                   "full_state", ["operation", "object", "observation", "combinator"], story.tags())


def _make_world():
    call, var, lit = story.call, n.Var, n.Lit
    prototype = modular_world(2)
    size = var("arg0")
    index = var("index")
    left = call("int_div", index, size)
    right = call("int_mod", index, size)
    cell = call("mk", lit("cell"), lit("val"), story.list_of(
        call("int_mod", call("int_add", left, right), size)))
    row = call("mk", lit("row"), lit("row"), story.list_of(story.list_of(left, right), cell))
    rows = n.Rec("make_rows", ("index", "rows"),
                 n.Case(((n.Test(call("int_eq", index, call("int_mul", size, size))), var("rows")),),
                        call("make_rows", call("int_add", index, lit(1)),
                             call("list_append", var("rows"), row))),
                 (lit(0), lit(Card("list", "items"))),
                 call("int_sub", call("int_mul", size, size), index))
    sort = call("with_field", lit(V.range_sort("digit", 0, 1)), lit(2),
                call("int_sub", size, lit(1)))
    operation = call("with_field", lit(V.table("add", "combine", ["digit", "digit"],
                                           "digit", [], [])), lit(5), rows)
    named = call("with_field", lit(prototype), lit(0),
                 call("str_concat", lit("zn"), call("int_text", size)))
    return call("with_field", call("with_field", named, lit(2), story.list_of(sort)),
                lit(3), story.list_of(operation))


def creation():
    """Check the template as a recorded family and each world in its own pipeline."""
    lib = story.BuilderLibrary(world.declaration(), hosts.atoms())
    body = _make_world()
    make = Definition("make_zn", "operation", "invented", 1,
                      tuple(sorted(n.references(body))),
                      OperationSpec("make_zn", "transform", (Edge("int"),), Edge("world"),
                                    "Construct a total modular-addition table"), body)
    lib.write(make)
    lib.check(make.name)
    domain = [(size,) for size in range(3, 8)]
    lib.make_callable(make.name, domain)
    lib.verify(make.name, library.VerifyRequest("bounded", domain,
               {"domain": "five moduli from 3 through 7", "size": len(domain)},
               reference=lambda size: modular_world(size)))
    lib.account(make.name)
    lib.promote(make.name, Contract("Exact modular tables for moduli 3 through 7"))
    generated = n.to_json(story.call("make_zn", n.Lit("$n")))
    pattern = {"form": "constant", "body": generated, "definition_body": generated}
    template = Definition("Zn", "template", "invented", 2, ("make_zn",),
                          TemplateSpec("Zn", (("n", "int"),), "object", pattern,
                                       {"family": [{"n": size} for size in range(3, 8)]}),
                          story.call("make_zn", n.Lit(3)))
    lib.write(template)

    def request(index, args, member):
        size = args["n"]
        return library.VerifyRequest("bounded", ((),),
               {"domain": f"one world Zn[{size}]", "size": 1},
               reference=lambda size=size: modular_world(size))

    original = library._VERIFIERS.get("object")
    library.register_kind("object", verifier=story._verify_object)
    try:
        members = generators.instantiate_family(lib, "Zn", [{"n": size} for size in range(3, 8)],
                                                 request)
    finally:
        if original is None:
            library._VERIFIERS.pop("object", None)
        else:
            library._VERIFIERS["object"] = original
    for member in members:
        lib.account(member.name)
        lib.promote(member.name, Contract(f"World Zn[{member.spec.extra['template']['args']['n']}]"))
    lib.account("Zn")
    lib.promote("Zn", Contract("Bounded family Zn[3] through Zn[7]"))
    return lib, members
