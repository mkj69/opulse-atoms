"""Invented twelve-card structures, all unfolded into given card/list atoms."""

from itertools import permutations

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
)
from opulse.atoms.values import Card

from . import hosts
from .world import new_library


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def seq(*items):
    return Card("sequence", "items", items)


def cycle(*items):
    return Card("Cycle", "val", (seq(*items),))


def collection(items):
    return seq(*(hosts.to_card(item) for item in items))


def test(name, *args):
    return n.Test(call(name, *args))


def choice(condition, yes, no):
    return n.Case(((condition, yes),), no)


def define(name, kind, spec, body, layers):
    expressions = [body]
    if kind == "object":
        expressions.extend((spec.valid, spec.canon))
    dependencies = tuple(sorted(set().union(*(n.references(expr) for expr in expressions
                                               if isinstance(expr, n.NODE_TYPES))) - set(getattr(spec, "op_params", ()))))
    layer = 1 + max((layers.get(dependency, layers.get(dependency.split(".")[0], 0))
                     for dependency in dependencies), default=0)
    layers[name] = layer
    return Definition(name, kind, "invented", layer, dependencies, spec, body)


def operation(name, args, output, body, layers):
    spec = OperationSpec(name, "transform", tuple(Edge(sort, name=param) for param, sort in args),
                         Edge(output), f"Unfold {name} into counted visible primitives.",
                         extra={"input_names": [param for param, _ in args]})
    return define(name, "operation", spec, body, layers)


def definitions():
    layers = {}
    position_list = var("x")
    valid = choice(n.And(n.And(test("le", lit(2), call("length", position_list)),
                               test("le", call("length", position_list), lit(12))),
                         n.And(test("all_between", position_list, lit(1), lit(12)),
                               n.And(test("distinct", position_list),
                                     test("eq", call("at", position_list, lit(0)), call("smallest", position_list))))),
                   lit(True), lit(False))
    yield define("Cycle", "object", ObjectSpec("Cycle", "refine", base="sequence", valid=valid,
                 sealed=True, interface=("Cycle.make", "Cycle.base")), None, layers)

    indices = call("Cycle.base", var("c"))
    rotate_body = n.Rec("turn", ("offset", "result"),
                        choice(test("eq", var("offset"), lit(0)), var("result"),
                               call("turn", call("sub", var("offset"), lit(1)),
                                    call("swap", call("at", indices, call("sub", var("offset"), lit(1))),
                                         call("at", indices, var("offset")), var("result")))),
                        (call("sub", call("length", indices), lit(1)), var("p")), var("offset"))
    yield operation("rotate", (("c", "Cycle"), ("p", "permutation")), "permutation", rotate_body, layers)

    yield operation("rotate_quad", (("p", "permutation"),), "permutation",
                    call("rotate", lit(cycle(1, 2, 3, 4)), var("p")), layers)
    yield operation("rotate_pair", (("p", "permutation"),), "permutation",
                    call("rotate", lit(cycle(1, 2)), var("p")), layers)

    power_body = n.Rec("power_local", ("remaining", "value"),
                       choice(test("eq", var("remaining"), lit(0)), var("value"),
                              call("power_local", call("sub", var("remaining"), lit(1)), call("f", var("value")))),
                       (var("times"), var("p")), var("remaining"))
    yield define("power", "combinator", CombinatorSpec("power", ("f", "times", "p"), ("f",), power_body), power_body, layers)

    view = call("cards", var("s"))
    visited = var("visited")
    spot = var("spot")
    next_spot = call("at", view, call("sub", spot, lit(1)))
    walk = n.Rec("follow", ("spot", "seen", "component"),
                 choice(test("contains", var("seen"), var("spot")), var("component"),
                        call("follow", next_spot, call("append", var("seen"), var("spot")),
                             call("append", var("component"), var("spot")))),
                 (var("index"), visited, lit(hosts.EMPTY)), call("sub", lit(13), call("length", var("seen"))))
    cycle_body = n.Rec("scan", ("index", "visited", "result"),
                       choice(test("eq", var("index"), lit(13)), var("result"),
                              choice(test("contains", visited, var("index")),
                                     call("scan", call("add", var("index"), lit(1)), visited, var("result")),
                                     n.Let("component", walk,
                                           call("scan", call("add", var("index"), lit(1)),
                                                call("merge_visited", visited, var("component")),
                                                choice(test("eq", call("length", var("component")), lit(1)), var("result"),
                                                       call("append", var("result"), var("component"))))))),
                       (lit(1), lit(hosts.EMPTY), lit(hosts.EMPTY)), call("sub", lit(13), var("index")))
    yield define("cycles", "observation", ObservationSpec("cycles", ("cards",), cycle_body), cycle_body, layers)

    components = call("cycles", var("p"))
    inverse_body = n.Rec("undo", ("index", "result"),
                         choice(test("eq", var("index"), call("length", components)), var("result"),
                                call("undo", call("add", var("index"), lit(1)),
                                     call("rotate", call("Cycle.make", call("at_seq", components, var("index"))), var("result")))),
                         (lit(0), lit(hosts.I)), call("sub", call("length", components), var("index")))
    yield operation("inverse", (("p", "permutation"),), "permutation", inverse_body, layers)

    signs = call("cycles", var("s"))
    sign_body = n.Rec("parity", ("index", "count"),
                      choice(test("eq", var("index"), call("length", signs)),
                             choice(test("eq", call("rem", var("count"), lit(2)), lit(0)), lit("even"), lit("odd")),
                             call("parity", call("add", var("index"), lit(1)),
                                  call("add", var("count"),
                                       call("sub", call("length", call("at", signs, var("index"))), lit(1))))),
                      (lit(0), lit(0)), call("sub", call("length", signs), var("index")))
    yield define("sign", "observation", ObservationSpec("sign", ("cards",), sign_body), sign_body, layers)

    right_components = call("cycles", var("b"))
    compose_body = n.Rec("apply", ("index", "result"),
                         choice(test("eq", var("index"), call("length", right_components)), var("result"),
                                call("apply", call("add", var("index"), lit(1)),
                                     call("rotate", call("Cycle.make", call("reverse_tail",
                                          call("at_seq", right_components, var("index")))), var("result")))),
                         (lit(0), var("a")), call("sub", call("length", right_components), var("index")))
    yield operation("compose", (("a", "permutation"), ("b", "permutation")), "permutation", compose_body, layers)

    for name, generator in (("compose_r", hosts.R), ("compose_s", hosts.S)):
        yield operation(name, (("p", "permutation"),), "permutation",
                        call("compose", var("p"), lit(generator)), layers)
    yield operation("swap34", (("p", "permutation"),), "permutation",
                    call("swap", lit(3), lit(4), var("p")), layers)
    yield operation("reset", (("p", "permutation"),), "permutation", lit(hosts.I), layers)

    current = call("at_perm", var("discovered"), var("index"))
    next_first = call("f", current)
    next_second = call("g", current)
    expanded_first = choice(test("contains", var("discovered"), var("first")), var("discovered"),
                            call("append", var("discovered"), var("first")))
    expanded_second = choice(test("contains", var("expanded"), var("second")), var("expanded"),
                             call("append", var("expanded"), var("second")))
    bfs = n.Rec("bfs", ("index", "discovered"),
                choice(test("eq", var("index"), call("length", var("discovered"))), var("discovered"),
                       n.Let("first", next_first,
                             choice(test("is_perm", var("first")),
                                    n.Let("expanded", expanded_first,
                                          n.Let("second", next_second,
                                                choice(test("is_perm", var("second")),
                                                       n.Let("updated", expanded_second,
                                                             n.Let("count", call("require_limit", call("length", var("updated"))),
                                                                   call("bfs", call("add", var("index"), lit(1)), var("updated")))),
                                                       call("reject", lit("invalid"))))), call("reject", lit("invalid"))))),
                (lit(0), call("append", lit(hosts.EMPTY), var("p"))), call("sub", lit(4097), var("index")))
    images = n.Rec("check_images", ("index", "first_images", "second_images"),
                   choice(test("eq", var("index"), call("length", var("found"))),
                          n.Let("count_first", call("length", call("sorted_unique", var("first_images"))),
                                n.Let("count_second", call("length", call("sorted_unique", var("second_images"))),
                                      n.Let("valid_first", call("require_bijective",
                                                                call("add", call("sub", var("count_first"),
                                                                                     call("length", var("found"))), lit(1))),
                                            n.Let("valid_second", call("require_bijective",
                                                                       call("add", call("sub", var("count_second"),
                                                                                            call("length", var("found"))), lit(1))),
                                                  call("sorted_unique", var("found")))))),
                          call("check_images", call("add", var("index"), lit(1)),
                               call("append", var("first_images"), call("f", call("at_perm", var("found"), var("index")))),
                               call("append", var("second_images"), call("g", call("at_perm", var("found"), var("index")))))),
                   (lit(0), lit(hosts.EMPTY), lit(hosts.EMPTY)), call("sub", call("length", var("found")), var("index")))
    closure_body = n.Let("found", bfs, images)
    yield define("closure", "combinator", CombinatorSpec("closure", ("f", "g", "p"), ("f", "g"),
                 closure_body), closure_body, layers)

    members = var("x")
    left_cards = call("cards", call("at_perm", members, var("left")))
    right_cards = call("cards", call("at_perm", members, var("right")))
    product_items = n.Rec("compose_positions", ("position", "items"),
                          choice(test("eq", var("position"), lit(12)), var("items"),
                                 call("compose_positions", call("add", var("position"), lit(1)),
                                      call("append", var("items"),
                                           call("at", left_cards,
                                                call("sub", call("at", right_cards, var("position")), lit(1)))))),
                          (lit(0), lit(hosts.EMPTY)), call("sub", lit(12), var("position")))
    product = call("pack", product_items)
    closed_with = n.Rec("check_right", ("right",),
                        choice(test("eq", var("right"), call("length", members)), lit(True),
                               choice(test("contains", members, product),
                                      call("check_right", call("add", var("right"), lit(1))), lit(False))),
                        (lit(0),), call("sub", call("length", members), var("right")))
    valid_members = n.Rec("check_left", ("left",),
                          choice(test("eq", var("left"), call("length", members)), lit(True),
                                 choice(test("is_perm", call("at_perm", members, var("left"))),
                                        call("check_left", call("add", var("left"), lit(1))), lit(False))),
                          (lit(0),), call("sub", call("length", members), var("left")))
    closed_members = n.Rec("check_pairs", ("left",),
                           choice(test("eq", var("left"), call("length", members)), lit(True),
                                  choice(n.Test(closed_with),
                                         call("check_pairs", call("add", var("left"), lit(1))), lit(False))),
                           (lit(0),), call("sub", call("length", members), var("left")))
    group_valid = choice(n.And(test("le", lit(1), call("length", members)),
                               test("le", call("length", members), lit(4096))),
                         choice(n.And(test("contains", members, lit(hosts.I)), n.Test(valid_members)),
                                closed_members, lit(False)), lit(False))
    yield define("Subgroup", "object", ObjectSpec("Subgroup", "refine", base="sequence", valid=group_valid,
                 canon=call("sorted_unique", var("x")), sealed=True,
                 interface=("Subgroup.make", "Subgroup.base")), None, layers)

    order_components = call("cycles", var("s"))
    order_body = n.Rec("accumulate", ("index", "current"),
                       choice(test("eq", var("index"), call("length", order_components)), var("current"),
                              call("accumulate", call("add", var("index"), lit(1)),
                                   call("lcm", var("current"), call("length", call("at_seq", order_components, var("index")))))),
                       (lit(0), lit(1)), call("sub", call("length", order_components), var("index")))
    yield define("order", "observation", ObservationSpec("order", ("cards",), order_body), order_body, layers)

    conjugate_body = call("compose", call("compose", call("inverse", var("b")), var("a")), var("b"))
    yield operation("conjugate", (("a", "permutation"), ("b", "permutation")), "permutation", conjugate_body, layers)

    members = call("cards", var("s"))
    candidate = var("candidate")
    other = var("other")
    position = var("position")
    commute = n.Rec("positions_commute", ("position",),
                    choice(test("eq", position, lit(12)), lit(True),
                           choice(test("eq", call("at", candidate, call("sub", call("at", other, position), lit(1))),
                                       call("at", other, call("sub", call("at", candidate, position), lit(1)))),
                                  call("positions_commute", call("add", position, lit(1))), lit(False))),
                    (lit(0),), call("sub", lit(12), position))
    all_commute = n.Rec("commutes_with_all", ("other_index",),
                        choice(test("eq", var("other_index"), call("length", members)), lit(True),
                               n.Let("other", call("at_seq", members, var("other_index")),
                                     choice(n.Test(commute), call("commutes_with_all", call("add", var("other_index"), lit(1))),
                                            lit(False)))),
                        (lit(0),), call("sub", call("length", members), var("other_index")))
    center_body = n.Rec("filter_center", ("index", "result"),
                        choice(test("eq", var("index"), call("length", members)), var("result"),
                               n.Let("candidate", call("at_seq", members, var("index")),
                                     call("filter_center", call("add", var("index"), lit(1)),
                                          choice(n.Test(all_commute), call("append", var("result"), call("pack", candidate)),
                                                 var("result"))))),
                        (lit(0), lit(hosts.EMPTY)), call("sub", call("length", members), var("index")))
    yield define("center", "observation", ObservationSpec("center", ("cards",), center_body), center_body, layers)


def build_library():
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    oracle_path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/permutation.py"
    oracle_spec = spec_from_file_location("permutation_depth_reference", oracle_path)
    oracle = module_from_spec(oracle_spec)
    oracle_spec.loader.exec_module(oracle)

    library = new_library()
    states = [hosts.to_card((*item, *range(5, 13))) for item in permutations(range(1, 5))]
    states += [hosts.R, hosts.S, hosts.I]
    states += [hosts.to_card((*range(1, 5), *item, *range(9, 13)))
               for item in list(permutations(range(5, 9)))[:23]]
    cycles = [seq(*item) for length in (2, 3) for item in permutations(range(1, 7), length)
              if item[0] == min(item)]
    involutions = [hosts.swap(first, second, hosts.I)
                   for first in range(1, 12) for second in range(first + 1, 13)]
    subgroup_pairs = [(hosts.I, involution) for involution in involutions[:54]]
    samples = {
        "Cycle": (seq(1, 2, 3, 4),), "rotate": (cycle(1, 2, 3, 4), hosts.I),
        "rotate_quad": (hosts.I,), "rotate_pair": (hosts.I,),
        "power": (kernel.FnRef("rotate_quad"), 3, hosts.I), "cycles": (hosts.S,),
        "inverse": (hosts.R,), "sign": (hosts.S,), "compose": (hosts.R, hosts.S),
        "compose_r": (hosts.I,), "compose_s": (hosts.I,), "swap34": (hosts.I,),
        "reset": (hosts.I,), "closure": (kernel.FnRef("rotate_pair"), kernel.FnRef("swap34"), hosts.I),
        "Subgroup": (seq(hosts.I, hosts.S),), "order": (hosts.S,),
        "conjugate": (hosts.R, hosts.S), "center": (Card("Subgroup", "val", (seq(hosts.I, hosts.S),)),),
    }
    references = {
        "rotate": lambda component, state: hosts.to_card(oracle.rotate(component.fields[0].fields, state.fields)),
        "rotate_quad": lambda state: hosts.to_card(oracle.rotate((1, 2, 3, 4), state.fields)),
        "rotate_pair": lambda state: hosts.to_card(oracle.rotate((1, 2), state.fields)),
        "inverse": lambda state: hosts.to_card(oracle.inverse(state.fields)),
        "compose": lambda first, second: hosts.to_card(oracle.compose(first.fields, second.fields)),
        "compose_r": lambda state: hosts.to_card(oracle.compose(state.fields, hosts.R.fields)),
        "compose_s": lambda state: hosts.to_card(oracle.compose(state.fields, hosts.S.fields)),
        "swap34": lambda state: hosts.swap(3, 4, state),
        "reset": lambda state: hosts.I,
        "conjugate": lambda first, second: hosts.to_card(oracle.conjugate(first.fields, second.fields)),
        "cycles": lambda state: seq(*(seq(*component) for component in oracle.cycles(state.fields))),
        "sign": lambda state: oracle.sign(state.fields),
        "order": lambda state: oracle.order(state.fields),
        "center": lambda state: seq(*(item for item in state.fields[0].fields
                                       if all(oracle.compose(item.fields, other.fields) ==
                                              oracle.compose(other.fields, item.fields)
                                              for other in state.fields[0].fields))),
    }
    for entry in definitions():
        library.write(entry)
        library.check(entry.name)
        sample = samples[entry.name]
        library.make_callable(entry.name, (sample,))
        if entry.kind == "object":
            domain = (tuple((component,) for component in cycles[:65]) + ((seq(1, 1),), (seq(13, 2),))
                      if entry.name == "Cycle" else tuple((seq(first, second),) for first, second in subgroup_pairs))
            request = VerifyRequest("bounded", domain,
                                    {"domain": "all canonical 2-cycles in positions 1..6 and first 50 3-cycles, plus two invalid lists" if entry.name == "Cycle" else
                                     "54 distinct two-member lists (identity and a transposition on positions 1..12), up to 4096 members",
                                     "size": len(domain)})
        elif entry.kind == "combinator":
            domain = (tuple((times, state) for times in range(4) for state in states[:15])
                      if entry.name == "power" else tuple((state,) for state in states[:50]))
            family = ({"f": ["rotate_quad", "rotate_pair"]} if entry.name == "power" else
                      {"f": ["rotate_pair", "rotate_quad"], "g": ["swap34", "rotate_pair"]})
            request = VerifyRequest("bounded", domain,
                                    {"domain": "times up to 3 on 15 four-card states for two unary moves" if entry.name == "power" else
                                     "50 starts with at most 4 active positions (plus R and S); closure bound 4096, two slots with two moves each (200 runs)",
                                     "size": len(domain), "op_family": family}, extra={"op_family": family})
        elif entry.kind == "observation":
            domain = (tuple((Card("Subgroup", "val", (seq(first, second),)),)
                            for first, second in subgroup_pairs)
                      if entry.name == "center" else tuple((state,) for state in states[:27]))
            request = VerifyRequest("bounded", domain,
                                    {"domain": "54 distinct valid two-member subgroups (identity and a transposition on positions 1..12), histories in batches up to 5" if entry.name == "center" else
                                     "all 24 four-position permutations and the identity, R, S (27 states), histories in batches up to 5",
                                     "size": len(domain)}, reference=references[entry.name],
                                    extra={"states": [tuple(args[0] for args in domain[index:index + 5])
                                                      for index in range(0, len(domain), 5)]})
        else:
            domain = (tuple((cycle(*component.fields), state) for component in cycles[:5] for state in states[:11])
                      if entry.name == "rotate" else tuple((state,) for state in states)
                      if entry.name in ("inverse", "rotate_quad", "rotate_pair", "compose_r", "compose_s", "swap34", "reset") else
                      tuple((first, second) for first in states[:10] for second in states[:5]))
            if entry.name in ("inverse", "rotate_quad", "rotate_pair", "compose_r", "compose_s", "swap34", "reset"):
                domain = domain[:27]
            request = VerifyRequest("bounded", domain,
                                    {"domain": f"up to 55 bounded {entry.name} cases over positions 1..12",
                                     "size": len(domain)}, reference=references[entry.name])
        library.verify(entry.name, request)
        library.account(entry.name)
        library.promote(entry.name, Contract("Equal outcome, visible observations, and counted given-atom steps over the stated scope."))
    return library
