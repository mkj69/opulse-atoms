"""Counted kernel constructions for complete binary DFAs."""

from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import all_dependencies
from opulse.atoms.library import bounded
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
from opulse.atoms.values import Card, boolean

from . import hosts
from .world import new_library


def v(name):
    return n.Var(name)


def c(name, *args):
    return n.Call(name, args)


def l(value):
    return n.Lit(value)


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def let(name, value, body):
    return n.Let(name, value, body)


def rec(name, params, body, args, measure="fuel"):
    return n.Rec(name, tuple(params), body, tuple(args), measure)


def empty(sort="states"):
    return c("empty", l(sort))


def make_pair(left, right):
    return c("Pair.pair", left, right,
             c("make_row", c("start", left), c("start", right)),
             c("mul", c("count", left), c("count", right)))


def row_first(row):
    return c("row_first", row)


def row_second(row):
    return c("row_second", row)


def reachable_body():
    machine, order, cursor = v("machine"), v("order"), v("cursor")
    state = c("at", order, cursor)
    body = let("a", c("step", machine, state, l("a")),
           let("b", c("step", machine, state, l("b")),
           let("after_a", choose(c("contains", order, v("a")), order,
                                 c("append", order, v("a"))),
               c("visit", choose(c("contains", v("after_a"), v("b")),
                                  v("after_a"), c("append", v("after_a"), v("b"))),
                         c("add", cursor, l(1))))))
    return rec("visit", ("order", "cursor"),
               choose(c("less", cursor, c("length", order)), body, order),
               (c("cons", c("start", machine), empty()), l(0)))


def mode_condition(mode, first, second):
    both = n.And(n.Test(first), n.Test(second))
    either = n.Or(n.Test(first), n.Test(second))
    xor = n.Or(n.And(n.Test(first), n.Not(n.Test(second))),
               n.And(n.Not(n.Test(first)), n.Test(second)))
    left_only = n.And(n.Test(first), n.Not(n.Test(second)))
    return n.Case(((n.And(n.Test(c("equal", mode, l("and"))), both), l(boolean(True))),
                   (n.And(n.Test(c("equal", mode, l("or"))), either), l(boolean(True))),
                   (n.And(n.Test(c("equal", mode, l("xor"))), xor), l(boolean(True))),
                   (n.And(n.Test(c("equal", mode, l("left_not_right"))), left_only), l(boolean(True)))),
                  l(boolean(False)))


def combine_body():
    left, right, mode, index = (v(name) for name in ("left", "right", "mode", "index"))
    width = c("count", right)
    size = c("mul", c("count", left), width)
    lhs, rhs = c("div", index, width), c("mod", index, width)
    pair = v("pair")

    def target(letter):
        stepped = c("sync", l(kernel.FnRef("step")), l(kernel.FnRef("step")),
                    pair, c("make_row", lhs, rhs), l(letter))
        return c("add", c("mul", row_first(stepped), width), row_second(stepped))

    rows = rec("rows", ("index",),
               choose(c("less", index, size),
                      c("cons_row", c("make_row", target("a"), target("b")),
                        c("rows", c("add", index, l(1)))), empty("rows")),
               (l(0),), c("sub", size, index))
    finals = rec("finals", ("index",),
                 choose(c("less", index, size),
                        let("rest", c("finals", c("add", index, l(1))),
                            choose(mode_condition(mode, c("final", left, lhs), c("final", right, rhs)),
                                   c("cons", index, v("rest")), v("rest"))), empty()),
                 (l(0),), c("sub", size, index))
    machine = c("make_machine", size, c("add", c("mul", c("start", left), width),
                                               c("start", right)), finals, rows)
    modes = ("and", "or", "xor", "left_not_right")
    authorized = n.Test(c("equal", mode, l(modes[0])))
    for option in modes[1:]:
        authorized = n.Or(authorized, n.Test(c("equal", mode, l(option))))
    return n.Case(((authorized, let("pair", make_pair(left, right), machine)),),
                  c("make_machine", l(0), l(0), empty(), empty("rows")))


def empty_body():
    machine, states, index = v("machine"), v("states"), v("index")
    scan = rec("scan", ("index",),
               choose(c("less", index, c("length", states)),
                      choose(c("final", machine, c("at", states, index)),
                             l(boolean(False)), c("scan", c("add", index, l(1)))),
                      l(boolean(True))), (l(0),), c("sub", c("length", states), index))
    return let("states", c("reachable", machine), scan)


def trim_body():
    machine, states, index = v("machine"), v("states"), v("index")
    size, current = c("length", states), c("at", states, index)
    rows = rec("trim_rows", ("index",),
               choose(c("less", index, size),
                      c("cons_row", c("make_row",
                                c("index_of", states, c("step", machine, current, l("a"))),
                                c("index_of", states, c("step", machine, current, l("b")))),
                        c("trim_rows", c("add", index, l(1)))), empty("rows")),
               (l(0),), c("sub", size, index))
    finals = rec("trim_finals", ("index",),
                 choose(c("less", index, size),
                        let("rest", c("trim_finals", c("add", index, l(1))),
                            choose(c("final", machine, current),
                                   c("cons", index, v("rest")), v("rest"))), empty()),
                 (l(0),), c("sub", size, index))
    return let("states", c("reachable", machine), c("make_machine", size, l(0), finals, rows))


def refine_body():
    machine, index, blocks, signatures = (v(name) for name in ("machine", "index", "blocks", "signatures"))
    size = c("count", machine)
    initial = rec("init", ("index",),
                  choose(c("less", index, size),
                         c("cons", choose(c("final", machine, index), l(1), l(0)),
                           c("init", c("add", index, l(1)))), empty()),
                  (l(0),), c("sub", size, index))
    signature = c("make_signature", c("at", blocks, index),
                  c("at", blocks, c("move", machine, index, l("a"))),
                  c("at", blocks, c("move", machine, index, l("b"))))
    all_signatures = rec("signatures", ("index",),
                         choose(c("less", index, size), c("cons", signature,
                                c("signatures", c("add", index, l(1)))), empty("signatures")),
                         (l(0),), c("sub", size, index))
    updated = rec("number", ("index",),
                  choose(c("less", index, size),
                         c("cons", c("index_of", v("keys"), c("at", signatures, index)),
                           c("number", c("add", index, l(1)))), empty()),
                  (l(0),), c("sub", size, index))
    iteration = let("signatures", all_signatures,
                let("keys", c("sorted_unique", signatures),
                let("next_blocks", updated,
                    choose(c("equal", c("distinct_count", v("next_blocks")),
                                       c("distinct_count", blocks)), v("next_blocks"),
                           c("split", v("next_blocks"), c("add", v("rounds"), l(1)))))))
    return let("machine", c("Trim.base", c("Trim.make", machine)),
               rec("split", ("blocks", "rounds"),
                   choose(c("less", v("rounds"), size), iteration, blocks),
                   (initial, l(0)), c("sub", size, v("rounds"))))


def minimize_body():
    machine, blocks, labels, index = (v(name) for name in ("machine", "blocks", "labels", "index"))
    size = c("length", labels)
    representative = c("index_of", blocks, c("at", labels, index))
    def target(char):
        return c("index_of", labels, c("at", blocks, c("step", machine, representative, l(char))))
    rows = rec("quotient_rows", ("index",),
               choose(c("less", index, size),
                      c("cons_row", c("make_row", target("a"), target("b")),
                        c("quotient_rows", c("add", index, l(1)))), empty("rows")),
               (l(0),), c("sub", size, index))
    finals = rec("quotient_finals", ("index",),
                 choose(c("less", index, size),
                        let("rest", c("quotient_finals", c("add", index, l(1))),
                            choose(c("final", machine, representative),
                                   c("cons", index, v("rest")), v("rest"))), empty()),
                 (l(0),), c("sub", size, index))
    return let("machine", c("Trim.base", c("Trim.make", machine)),
               let("blocks", c("refine", l(kernel.FnRef("step")), machine),
                   let("labels", c("sorted_unique", blocks),
                       c("Trim.base", c("Trim.make", c("make_machine", size,
                                c("index_of", labels, c("at", blocks, l(0))), finals, rows))))))


def separate_body():
    left, right, machine, queue, seen = (v(name) for name in ("left", "right", "machine", "queue", "seen"))
    item = v("item")
    def enqueue(char, rest, visited):
        return let("target", c("step", machine, c("entry_state", item), l(char)),
                   let("new_queue", choose(c("contains", visited, v("target")), rest,
                                           c("append", rest, c("make_entry", v("target"),
                                              c("join_word", c("entry_word", item), l(char))))),
                       c("make_frontier", v("new_queue"),
                         choose(c("contains", visited, v("target")), visited,
                                c("append", visited, v("target"))))))
    body = let("item", c("head", queue),
           choose(c("final", machine, c("entry_state", item)), c("entry_word", item),
                  let("first", enqueue("a", c("tail", queue), seen),
                      let("second", enqueue("b", c("frontier_queue", v("first")),
                                            c("frontier_seen", v("first"))),
                          c("search", c("frontier_queue", v("second")),
                            c("frontier_seen", v("second")))))))
    search = rec("search", ("queue", "seen"),
                 choose(c("equal", c("length", queue), l(0)), l("none"), body),
                 (c("cons", c("make_entry", c("start", machine), l("")), empty("queue")),
                  c("cons", c("start", machine), empty())))
    return choose(c("equivalent", left, right), l("none"),
                  let("machine", c("combine", left, right, l("xor")), search))


def definitions():
    pair = ObjectSpec("Pair", "compose", tags={"pair": [["left", "automaton"],
                                                 ["right", "automaton"], ["initial", "row"],
                                                 ["capacity", "int"]]})
    trim = ObjectSpec("Trim", "refine", base="automaton", params=("machine",),
                      valid=c("machine_valid_atom", v("x")), canon=let("machine", v("x"), trim_body()))
    sync_body = c("make_row", c("move_left", c("Pair.left", v("pair")),
                                             row_first(v("states")), v("symbol")),
                          c("move_right", c("Pair.right", v("pair")),
                                              row_second(v("states")), v("symbol")))
    def op(name, params, output, body):
        spec = OperationSpec(name, "transform", tuple(Edge("automaton" if param in ("left", "right", "machine") else "str",
                                                     name=param) for param in params),
                             Edge(output), f"Construct {name} from finite DFA data.",
                             extra={"input_names": list(params)})
        return name, "operation", spec, body
    def comb(name, params, slots, body):
        return name, "combinator", CombinatorSpec(name, tuple(params), tuple(slots), body), body
    def obs(name, body, reads=("accept", "size", "step", "start", "final", "count",
                               "machine_valid_atom")):
        return name, "observation", ObservationSpec(name, reads, body), body
    cards = [
        ("Pair", "object", pair, None),
        ("reverse_move", "operation",
         OperationSpec("reverse_move", "transform", (Edge("automaton", name="machine"),
                       Edge("int", name="state"), Edge("str", name="symbol")), Edge("int"),
                       "Read the opposite alphabet symbol for slot-family verification.",
                       extra={"input_names": ["machine", "state", "symbol"]}),
         c("step", v("machine"), v("state"),
           choose(c("equal", v("symbol"), l("a")), l("b"), l("a")))),
        comb("sync", ("move_left", "move_right", "pair", "states", "symbol"),
             ("move_left", "move_right"), sync_body),
        op("combine", ("left", "right", "mode"), "automaton", combine_body()),
        op("reachable", ("machine",), "states", reachable_body()),
        obs("empty_language", empty_body(), ("start", "step", "final")),
        ("Trim", "object", trim, None),
        comb("refine", ("move", "machine"), ("move",), refine_body()),
        op("minimize", ("machine",), "automaton", minimize_body()),
        obs("equivalent", c("equal", c("minimize", v("left")), c("minimize", v("right")))),
        op("separate", ("left", "right"), "str", separate_body()),
        obs("included", choose(c("equivalent", v("left"), v("right")), l(boolean(True)),
                               c("empty_language", c("combine", v("left"), v("right"),
                                                           l("left_not_right"))))),
    ]
    generated = {"Pair.pair": 1, "Pair.left": 1, "Pair.right": 1,
                 "Trim.make": 2, "Trim.base": 2}
    layers = {}
    result = []
    for name, kind, spec, body in cards:
        definition = Definition(name, kind, "invented", 1, (), spec, body)
        references = all_dependencies(definition) if body is not None else set()
        if name == "Trim":
            references = set(n.references(spec.canon)) | set(n.references(spec.valid))
        references -= set(getattr(spec, "op_params", ()))
        dependencies = tuple(sorted(references if body is not None or name == "Trim" else ()))
        layer = compute_layer(references, lambda ref: layers.get(ref.split(".", 1)[0],
                                                                 generated.get(ref, 0)))
        result.append(Definition(name, kind, "invented", layer, dependencies, spec, body))
        layers[name] = layer
    return tuple(result)


def oracle_module():
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/automata.py"
    name = "opulse_automata_depth_oracle"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def to_reference(machine):
    reference = oracle_module()
    _, initial, finals, rows = hosts.from_card(machine)
    return reference.DFA(rows, initial, frozenset(finals))


def from_reference(machine):
    return hosts.to_card(len(machine.transitions), machine.initial, sorted(machine.finals), machine.transitions)


def oracle(name, *arguments):
    module = oracle_module()
    if name == "Pair":
        left, right = arguments
        return Card("Pair", "pair", (left, right,
                    hosts.make_row(hosts.start(left), hosts.start(right)),
                    hosts.count(left) * hosts.count(right)))
    if name == "sync":
        _, _, pair, states, symbol = arguments
        left, right = pair.fields
        def move(operation, machine, state):
            return hosts.step(machine, state, symbol if operation.name == "step" else
                              "b" if symbol == "a" else "a")
        return hosts.make_row(move(arguments[0], left, states.fields[0]),
                              move(arguments[1], right, states.fields[1]))
    if name in ("combine", "included", "equivalent", "separate"):
        left, right = (to_reference(machine) for machine in arguments[:2])
        answer = getattr(module, name)(left, right, *arguments[2:])
    elif name in ("Trim", "minimize", "reachable", "empty_language", "refine"):
        machine = to_reference(arguments[-1])
        answer = {"Trim": module.trim, "minimize": module.minimize,
                  "reachable": lambda item: module.reachable(item)[0],
                  "empty_language": module.empty,
                  "refine": lambda item: module.refine(
                      module.step if arguments[0].name == "step" else
                      lambda automaton, state, char: module.step(automaton, state,
                                                                "b" if char == "a" else "a"),
                      module.trim(item))}[name](machine)
    elif name == "reverse_move":
        machine, state, symbol = arguments
        return hosts.step(machine, state, "b" if symbol == "a" else "a")
    else:
        raise KeyError(name)
    if isinstance(answer, module.DFA):
        result = from_reference(answer)
        return Card("Trim", "val", (result,)) if name == "Trim" else result
    if isinstance(answer, bool):
        return boolean(answer)
    if answer is None:
        return "none"
    if isinstance(answer, (list, tuple)):
        return Card("states", "list", tuple(answer))
    return answer


def examples(library):
    machines = hosts.depth_examples()
    def machine(name):
        return machines[name]
    def combined(left, right, mode):
        return library.run("combine", (left, right, mode)).outcome.value
    pair = library.run("Pair.pair", (machine("mod7_a"), machine("no_bb"),
                       hosts.make_row(0, 0), 21)).outcome.value
    product = combined(machine("mod7_a"), machine("no_bb"), "and")
    large = combined(combined(machine("mod7_a"), machine("mod5_a"), "and"), machine("no_bb"), "and")
    target = combined(product, combined(machine("mod5_a"), machine("ends_a"), "or"), "left_not_right")
    return {
        "Pair": ("Pair.pair", (machine("mod7_a"), machine("no_bb"), hosts.make_row(0, 0), 21),
                 "Pair<Mod7A<>,NoBB<>>"),
        "sync": ("sync", (kernel.FnRef("step"), kernel.FnRef("step"), pair,
                          hosts.make_row(6, 0), "a"), "@sync[step,step](Pair<Mod7A<>,NoBB<>>,(6,0),'a')"),
        "combine": ("combine", (machine("mod7_a"), machine("no_bb"), "and"),
                    "?accept{combine(Mod7A<>,NoBB<>,'and'),'aaaaaaa'}"),
        "empty_language": ("empty_language", (combined(machine("mod7_a"),
                                                         machine("never_accept"), "and"),),
                           "?empty{combine(Mod7A<>,NeverAccept<>,'and')}"),
        "Trim": ("Trim.make", (product,), "?size{Trim<combine(Mod7A<>,NoBB<>,'and')>}"),
        "refine": ("refine", (kernel.FnRef("step"), product),
                   "distinct_count(@refine[step](Trim<combine(Mod7A<>,NoBB<>,'and')>))"),
        "minimize": ("minimize", (product,), "?size{minimize(combine(Mod7A<>,NoBB<>,'and'))}"),
        "equivalent": ("equivalent", (combined(machine("mod7_a"), machine("mod5_a"), "and"),
                                      machine("mod35_a")),
                       "?equivalent{combine(Mod7A<>,Mod5A<>,'and'),Mod35A<>}"),
        "separate": ("separate", (target, machine("never_accept")),
                     "separate(combine(combine(Mod7A<>,NoBB<>,'and'),combine(Mod5A<>,EndsA<>,'or'),'left_not_right'),NeverAccept<>)"),
        "included": ("included", (large, machine("mod35_a")),
                     "?included{combine(combine(Mod7A<>,Mod5A<>,'and'),NoBB<>,'and'),Mod35A<>}"),
    }


def small_machines():
    return tuple(hosts.to_card(2, start, finals,
                               ((first // 2, first % 2), (second // 2, second % 2)))
                 for start in (0, 1) for finals in ((), (0,), (1,), (0, 1))
                 for first in range(4) for second in range(4))[:50]


def build_library():
    library = new_library()
    fixtures = hosts.depth_examples()
    family = small_machines()
    ends, even = fixtures["ends_a"], fixtures["even_len"]
    for definition in definitions():
        name = definition.name
        library.write(definition)
        library.check(name)
        if name == "Pair":
            library.make_callable(name, ((ends, even, hosts.make_row(0, 0), 4),))
            request = bounded((family, (ends, even)), "bounded: 50 two-state DFAs x 2 partner DFAs")
        elif name == "Trim":
            library.make_callable(name, ((ends,),))
            request = bounded((family,), "bounded: 50 complete two-state DFAs")
        else:
            arguments = {
                "reverse_move": (ends, 0, "a"),
                "sync": (kernel.FnRef("step"), kernel.FnRef("step"),
                         library.run("Pair.pair", (ends, even, hosts.make_row(0, 0), 4)).outcome.value,
                         hosts.make_row(0, 0), "a"),
                "combine": (ends, even, "and"), "reachable": (ends,),
                "empty_language": (ends,), "refine": (kernel.FnRef("step"), ends),
                "minimize": (ends,), "equivalent": (ends, even),
                "separate": (ends, even), "included": (ends, even),
            }[name]
            library.make_callable(name, (arguments,))
            if name == "reverse_move":
                args = tuple((machine, state, char) for machine in family for state in range(2)
                             for char in "ab")
                request = replace(bounded((args,), "bounded: 200 states and alphabet letters in 50 two-state DFAs"),
                                  domain=args, reference=lambda machine, state, symbol: oracle(
                                      "reverse_move", machine, state, symbol))
            elif name == "sync":
                rows = tuple((library.run("Pair.pair", (machine, even,
                              hosts.make_row(hosts.start(machine), 0), 4)).outcome.value,
                              hosts.make_row(state, 0), char)
                             for machine in family[:25] for state in range(1) for char in "ab")
                request = bounded((rows,), "bounded: 50 paired states and letters; 4 slot assignments")
                request = replace(request, domain=rows,
                                  scope={**request.scope, "size": len(rows), "op_family": ["step", "reverse_move"],
                                         "fixed_ops": []},
                                  extra={"op_family": ("step", "reverse_move")},
                                  reference=lambda assignment, row: hosts.make_row(
                                      hosts.step(row[0].fields[0], row[1].fields[0],
                                                 row[2] if assignment["move_left"] == "step" else "b" if row[2] == "a" else "a"),
                                      hosts.step(row[0].fields[1], row[1].fields[1],
                                                 row[2] if assignment["move_right"] == "step" else "b" if row[2] == "a" else "a")))
            elif name == "combine":
                args = tuple((machine, partner, mode) for machine in family[:13]
                             for partner in (ends, even) for mode in ("and", "xor"))
                request = replace(bounded((args,), "bounded: 52 complete two-state DFA products, two modes"),
                                  domain=args, reference=lambda left, right, mode: oracle("combine", left, right, mode))
            elif name == "refine":
                request = bounded((family,), "bounded: 50 complete two-state DFAs; 2 move operations")
                request = replace(request, scope={**request.scope, "op_family": ["step", "reverse_move"],
                                                  "fixed_ops": []},
                                  extra={"op_family": ("step", "reverse_move")},
                                  reference=lambda assignment, args: oracle("refine", kernel.FnRef(assignment["move"]), args[0]))
            elif name in ("equivalent", "separate", "included"):
                args = tuple((machine, even) for machine in family)
                request = replace(bounded((args,), "bounded: 50 complete two-state DFAs against EvenLen"),
                                  domain=args, reference=lambda left, right, name=name: oracle(name, left, right))
            else:
                request = replace(bounded((family,), "bounded: 50 complete two-state DFAs"),
                                  reference=lambda machine, name=name: oracle(name, machine))
        library.verify(name, request)
        library.account(name)
        library.promote(name, Contract("Exact on the stated finite family; complete graph traversal for each input."))
    return library
