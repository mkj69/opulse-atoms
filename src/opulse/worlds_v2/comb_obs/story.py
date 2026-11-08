"""Eight warehouse inventions passed through the core library pipeline."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import all_dependencies
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import CombinatorSpec, Contract, Definition, ObservationSpec
from opulse.atoms.values import Bottom

from . import reference as ref
from .world import new_library

NAMES = ("chart", "frontier", "walk", "route_len", "explore", "reserve", "dispatch", "audit")
SLOTS = {
    "chart": ("scan",), "walk": ("scan", "move"),
    "explore": ("scan", "move", "charge"),
    "dispatch": ("scan", "move", "charge", "pick", "deliver"),
}


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def let(name, value, body):
    return n.Let(name, value, body)


def choose(test, yes, no):
    return n.Case(((n.Test(test), yes),), no)


def both(first, second):
    return choose(first, second, lit(False))


def negate(value):
    return choose(value, lit(False), lit(True))


def route(start, target, known):
    return call("search", lit(kernel.FnRef("neighbors")), lit(kernel.FnRef("map_get")),
                start, target, known)


def target(orders, order_id):
    return call("field", call("item", orders, order_id), lit(0))


def distance(parents, start, end):
    return call("parent_distance", parents, start, end)


def graph(known, start):
    frontier, parents = var("frontier"), var("parents")
    return n.Rec("graph_loop", ("frontier", "parents"),
                 choose(call("empty", frontier), parents,
                        let("expanded", call("graph_expand", frontier, parents, known),
                            choose(call("empty", call("graph_frontier", var("expanded"))),
                                   call("graph_parents", var("expanded")),
                                   call("graph_loop", call("graph_frontier", var("expanded")),
                                        call("graph_parents", var("expanded")))))),
                 (call("prepend", start, lit(())), call("singleton", start)),
                 call("sub", lit(4097), call("size", parents)))


def frontier_body():
    state = var("s")
    return let("known_map", call("known", state),
               let("position", call("pos", state),
                   choose(call("map_get", var("known_map"), var("position")),
                          call("map_missing_any", var("known_map"),
                               call("square", var("position"), lit(3))), lit(False))))


def walk_body():
    state, path = var("state"), var("path")
    execute = n.Rec("walk_loop", ("state", "path"),
                    choose(call("empty", path), state,
                           call("walk_loop", call("step", state,
                                                  call("cell_delta", call("head", path),
                                                       call("pos", state))),
                                call("tail", path))),
                    (var("start"), var("route")), call("size", path))
    return let("start", choose(call("frontier", var("s")), var("s"),
                               choose(call("empty", call("known", var("s"))),
                                      call("probe", var("s")), var("s"))),
               let("route", route(call("pos", var("start")), var("target"),
                                  call("known", var("start"))),
                   choose(call("is_none", var("route")), lit(Bottom("unknown_route")), execute)))


def route_length_body():
    return let("route", route(call("pos", var("s")), call("goal", var("s")),
                              call("known", var("s"))),
               choose(call("is_none", var("route")), call("none"), call("size", var("route"))))


def candidates_body():
    cells, best, cell = var("cells"), var("best"), var("cell")
    known, parents, position, target_cell = (var(name) for name in
                                             ("known_map", "parents_map", "position", "target"))
    rank = call("pack", call("tuple4",
                              call("add", call("mul", lit(2), distance(parents, position, cell)),
                                   call("manhattan", cell, target_cell)),
                              distance(parents, position, cell), call("field", cell, lit(1)),
                              call("field", cell, lit(0))), cell)
    candidate_frontier = choose(call("equal", cell, position),
                                call("frontier", var("state")),
                                call("map_missing_any", known, call("square", cell, lit(3))))
    acceptable = n.And(n.Test(call("map_get", known, cell)),
                       n.And(n.Test(call("map_has", parents, cell)), n.Test(candidate_frontier)))
    body = let("cell", call("head", cells),
               call("choose_loop", call("tail", cells),
                    n.Case(((acceptable, call("select_min", best, rank)),), best)))
    return n.Rec("choose_loop", ("cells", "best"),
                 choose(call("empty", cells), best, body),
                 (call("keys", known), call("none")), call("size", cells))


def explore_body():
    state, remaining = var("state"), var("remaining")
    position = call("pos", state)
    known = call("known", state)
    home = lit((2, 2))
    plan = let("known_map", known,
               let("position", position,
                   let("parents_map", graph(var("known_map"), var("position")),
                       let("candidate", candidates_body(),
                           choose(call("is_none", var("candidate")),
                                  lit(Bottom("unreachable")),
                                  let("cell", call("pair_second", var("candidate")),
                                      choose(call("less", call("energy", state),
                                                  call("add", call("add", call("mul", lit(2),
                                                      distance(var("parents_map"), var("position"), var("cell"))),
                                                      distance(var("parents_map"), var("position"), home)),
                                                       lit(21))),
                                             choose(both(call("equal", position, home),
                                                         call("equal", call("energy", state), lit(600))),
                                                    lit(Bottom("capacity")),
                                                    call("fill", call("walk", var("probe"), var("step"),
                                                                      state, home))),
                                             call("probe", call("walk", var("probe"), var("step"),
                                                                state, var("cell"))))))))))
    known_route = choose(call("equal", var("target"), call("goal", state)),
                         negate(call("is_none", call("route_len", state))),
                         negate(call("is_none", route(position, var("target"), known))))
    body = choose(negate(known_route),
                  choose(call("budget_empty", remaining), lit(Bottom("exploration_limit")),
                         call("explore_loop", plan, call("decrement", remaining))), state)
    start = choose(call("map_get", call("known", var("s")), call("pos", var("s"))),
                   var("s"), call("probe", var("s")))
    return n.Rec("explore_loop", ("state", "remaining"), body,
                 (start, lit(400)), remaining)


def reserve_body():
    return let("path", route(call("pos", var("s")), lit((2, 2)), call("known", var("s"))),
               choose(call("is_none", var("path")), call("none"),
                      call("sub", call("sub", call("energy", var("s")),
                                             call("size", var("path"))), lit(2))))


def trip_length(batch, orders, known):
    remaining, last, moves = var("remaining"), var("last"), var("moves")
    return n.Rec("trip_length_loop", ("remaining", "last", "moves"),
                 choose(call("empty", remaining),
                        call("add", moves, call("size", route(last, lit((2, 2)), known))),
                        let("destination", target(orders, call("head", remaining)),
                            call("trip_length_loop", call("tail", remaining), var("destination"),
                                 call("add", moves, call("size", route(last, var("destination"), known)))))),
                 (batch, lit((2, 2)), lit(0)), call("size", remaining))


def batch_weight(batch, orders):
    remaining = var("remaining")
    return n.Rec("weight_loop", ("remaining", "weight"),
                 choose(call("empty", remaining), var("weight"),
                        call("weight_loop", call("tail", remaining),
                             call("add", var("weight"),
                                  call("field", call("item", orders, call("head", remaining)), lit(1))))),
                 (batch, lit(0)), call("size", remaining))


def schedule_body(orders, known, initial_energy):
    remaining, energy, choices, best, batch = (var(name) for name in
                                               ("remaining", "energy_left", "choices", "best", "batch"))
    charge_needed = call("less", energy, call("add", var("moves"), lit(2)))
    next_energy = call("sub", choose(charge_needed, lit(600), energy), var("moves"))
    suffix = call("solve", call("difference", remaining, batch), next_energy)
    score = call("tuple4", call("add", call("field", call("pair_first", var("suffix")), lit(0)),
                                           call("add", var("moves"),
                                                choose(charge_needed, lit(30), lit(0)))),
                 call("add", call("field", call("pair_first", var("suffix")), lit(1)), var("moves")),
                 call("add", call("field", call("pair_first", var("suffix")), lit(2)),
                      choose(charge_needed, lit(1), lit(0))),
                 call("prepend", batch, call("pair_second", var("suffix"))))
    candidate = let("moves", trip_length(batch, orders, known),
                    choose(call("less", lit(600), call("add", var("moves"), lit(2))), best,
                           let("suffix", suffix,
                               choose(call("is_none", var("suffix")), best,
                                      let("score", score,
                                          call("select_min", best,
                                               call("pack", var("score"),
                                                    call("field", var("score"), lit(3)))))))))
    fold = n.Rec("batch_loop", ("choices", "best"),
                 choose(call("empty", choices), best,
                        let("batch", call("head", choices),
                            call("batch_loop", call("tail", choices),
                                 choose(call("less", lit(3), batch_weight(batch, orders)),
                                        best, candidate)))),
                 (call("batches", remaining), call("none")), call("size", choices))
    return n.Rec("solve", ("remaining", "energy_left"),
                 choose(call("empty", remaining),
                        call("pack", call("tuple4", lit(0), lit(0), lit(0), lit(())), lit(())), fold),
                 (call("sort", call("keys", orders)), initial_energy),
                 call("size", remaining))


def dispatch_body():
    survey = var("s")
    for order_id in ("A", "B", "C"):
        saved = "surveyed_" + order_id
        survey = let(saved, survey,
                     call("explore", var("probe"), var("step"), var("fill"), var(saved),
                          target(call("orders", var(saved)), lit(order_id))))
    batch, state, remaining = var("batch"), var("state"), var("remaining")
    load = n.Rec("load_loop", ("remaining", "state"),
                 choose(call("empty", remaining), state,
                        call("load_loop", call("tail", remaining),
                             call("load", state, call("head", remaining)))),
                 (batch, state), call("size", remaining))
    deliver = n.Rec("deliver_loop", ("remaining", "state"),
                    choose(call("empty", remaining), state,
                           let("order_id", call("head", remaining),
                               call("deliver_loop", call("tail", remaining),
                                    call("handoff", call("walk", var("probe"), var("step"),
                                                         state, target(call("orders", state),
                                                                       var("order_id"))),
                                         var("order_id"))))),
                    (batch, var("loaded")), call("size", remaining))
    run_batch = let("batch", call("head", var("pending")),
                    let("moves", trip_length(batch, call("orders", state), call("known", state)),
                        let("charged", choose(call("less", call("reserve", state), var("moves")),
                                              call("fill", state), state),
                            let("loaded", n.Rec("load_loop", ("remaining", "state"),
                                                load.body, (batch, var("charged")),
                                                call("size", remaining)),
                                call("dispatch_loop", call("walk", var("probe"), var("step"),
                                                            deliver, lit((2, 2))),
                                     call("tail", var("pending")))))))
    return let("survey", survey,
               let("ready", call("walk", var("probe"), var("step"), var("survey"), lit((2, 2))),
                   let("solution", schedule_body(call("orders", var("ready")),
                                                 call("known", var("ready")), call("energy", var("ready"))),
                       n.Rec("dispatch_loop", ("state", "pending"),
                             choose(call("empty", var("pending")), state, run_batch),
                             (var("ready"), call("pair_second", var("solution"))),
                             call("size", var("pending"))))))


def audit_transition(accumulator, event, orders):
    energy, position, payload, onboard, delivered, returns, trip, valid = (
        call("field", accumulator, lit(index)) for index in range(8))
    action, cell, logged_energy, known_before, order_id, logged_payload = (
        call("field", event, lit(index)) for index in range(6))

    def result(new_energy, new_position, new_payload, new_onboard, new_delivered,
               new_returns, new_trip, condition):
        legal = both(valid, condition)
        legal = both(legal, both(call("less", lit(-1), new_energy),
                                 both(call("less", lit(-1), new_payload),
                                      call("less", new_payload, lit(4)))))
        legal = both(legal, call("equal", call("pack", new_energy, new_payload),
                                 call("pack", logged_energy, logged_payload)))
        return call("tuple8", new_energy, new_position, new_payload, new_onboard,
                    new_delivered, new_returns, new_trip, legal)

    scan = result(call("sub", energy, lit(2)), position, payload, onboard,
                  delivered, returns, trip, lit(True))
    moving = let("next_energy", call("sub", energy, lit(1)),
                 let("returning", both(trip, both(call("equal", cell, lit((2, 2))),
                                                   call("empty", onboard))),
                     result(var("next_energy"), cell, payload, onboard, delivered,
                            choose(var("returning"),
                                   call("append", returns, call("sub", var("next_energy"), lit(2))),
                                   returns),
                            choose(var("returning"), lit(False), trip),
                            both(call("equal", call("manhattan", cell, position), lit(1)),
                                 both(known_before,
                                      choose(var("returning"),
                                             call("less", lit(1), var("next_energy")), lit(True)))))))
    charge = result(lit(600), position, payload, onboard, delivered, returns, trip,
                    both(call("equal", position, lit((2, 2))), call("empty", onboard)))
    available = both(call("map_has", orders, order_id),
                     both(negate(call("member", order_id, onboard)),
                          negate(call("member", order_id, delivered))))
    pickup = choose(available,
                    result(energy, position,
                           call("add", payload, call("field", call("item", orders, order_id), lit(1))),
                           call("set_add", onboard, order_id), delivered, returns, lit(True),
                           call("equal", position, lit((2, 2)))),
                    result(energy, position, payload, onboard, delivered, returns, trip, lit(False)))
    drop = choose(call("map_has", orders, order_id),
                  result(energy, position,
                         call("sub", payload, call("field", call("item", orders, order_id), lit(1))),
                         call("set_remove", onboard, order_id), call("set_add", delivered, order_id),
                         returns, trip, both(call("member", order_id, onboard),
                                             call("equal", position, target(orders, order_id)))),
                  result(energy, position, payload, onboard, delivered, returns, trip, lit(False)))
    return choose(call("equal", action, lit("scan")), scan,
                  choose(call("equal", action, lit("move")), moving,
                         choose(call("equal", action, lit("charge")), charge,
                                choose(call("equal", action, lit("pick")), pickup,
                                       choose(call("equal", action, lit("deliver")), drop,
                                              result(energy, position, payload, onboard, delivered,
                                                     returns, trip, lit(False)))))))


def count_events(events, action):
    remaining, count = var("remaining"), var("count")
    return n.Rec("count_loop", ("remaining", "count"),
                 choose(call("empty", remaining), count,
                        call("count_loop", call("tail", remaining),
                             call("add", count, choose(call("equal", call("field", call("head", remaining),
                                                                         lit(0)), action), lit(1), lit(0))))),
                 (events, lit(0)), call("size", remaining))


def audit_body():
    events = var("events")
    remaining, accumulator = var("remaining"), var("accumulator")
    fold_events = n.Rec("event_loop", ("remaining", "accumulator"),
                        choose(call("empty", remaining), accumulator,
                               call("event_loop", call("tail", remaining),
                                    audit_transition(accumulator, call("head", remaining), var("orders_map")))),
                        (events, call("tuple8", lit(600), lit((2, 2)), lit(0), call("empty_set"),
                                      call("empty_set"), lit(()), lit(False), lit(True))),
                        call("size", remaining))
    entries = var("entries")
    entry = call("head", entries)
    cell = call("field", entry, lit(0))
    hashed = call("mod", call("add", call("add", call("mul", var("checksum"), lit(257)),
                                               call("mul", call("field", cell, lit(0)), lit(67))),
                                   call("add", call("mul", call("field", cell, lit(1)), lit(71)),
                                        choose(call("field", entry, lit(1)), lit(1), lit(0)))),
                  lit(1000003))
    fold_checksum = n.Rec("checksum_loop", ("entries", "checksum"),
                          choose(call("empty", entries), var("checksum"),
                                 call("checksum_loop", call("tail", entries), hashed)),
                          (call("sorted_items", call("known", var("s"))), lit(0)),
                          call("size", entries))
    actual = var("s")
    valid = both(call("field", accumulator, lit(7)),
                 both(call("equal", call("field", accumulator, lit(0)), call("energy", actual)),
                      both(call("equal", call("field", accumulator, lit(1)), call("pos", actual)),
                           both(call("equal", call("field", accumulator, lit(3)),
                                            call("field", call("cargo", actual), lit(0))),
                                both(call("equal", call("field", accumulator, lit(4)),
                                                 call("field", call("cargo", actual), lit(1))),
                                     negate(call("field", accumulator, lit(6))))))))
    completion = both(var("valid_trace"),
                      both(call("equal", call("pos", actual), lit((2, 2))),
                           both(call("all_in", call("field", call("cargo", actual), lit(1)),
                                               call("keys", var("orders_map"))),
                                both(call("empty", call("field", call("cargo", actual), lit(0))),
                                     both(call("equal", call("field", call("cargo", actual), lit(2)), lit(0)),
                                          call("equal", count_events(events, lit("deliver")),
                                               call("size", call("keys", var("orders_map")))))))))
    results = call("list9", completion,
                   call("to_list", call("sort", call("field", call("cargo", actual), lit(1)))),
                   call("field", call("cargo", actual), lit(2)),
                   choose(var("valid_trace"), call("size", call("field", accumulator, lit(5))), call("none")),
                   choose(both(var("valid_trace"),
                               negate(call("empty", call("field", accumulator, lit(5))))),
                          call("min_list", call("field", accumulator, lit(5))), call("none")),
                   fold_checksum, count_events(events, lit("scan")),
                   count_events(events, lit("move")), count_events(events, lit("charge")))
    return let("events", call("log", actual),
               let("orders_map", call("orders", actual),
                   let("accumulator", fold_events,
                       let("valid_trace", valid, results))))


def definitions():
    bodies = (call("probe", var("s")), frontier_body(), walk_body(), route_length_body(),
              explore_body(), reserve_body(), dispatch_body(), audit_body())
    result = []
    for index, (name, body) in enumerate(zip(NAMES, bodies), 1):
        if name in SLOTS:
            slots = ("probe", "step", "fill", "load", "handoff")[:len(SLOTS[name])]
            params = (*slots, "s", "target") if name in ("walk", "explore") else (*slots, "s")
            spec = CombinatorSpec(name, params, slots, body)
            kind = "combinator"
        else:
            reads = tuple(sorted({node.fn for node in n.walk(body) if isinstance(node, n.Call)}
                                 & {"pos", "energy", "known", "goal", "orders", "cargo", "log"}))
            spec = ObservationSpec(name, reads, body)
            kind = "observation"
        definition = Definition(name, kind, "invented", index, (), spec, body)
        result.append(Definition(name, kind, "invented", index,
                                 tuple(sorted(all_dependencies(definition) - set(getattr(spec, "op_params", ())))),
                                 spec, body))
    return result


def inputs(name):
    state = ref.Run(17, (5, 4))
    if name in ("frontier", "route_len", "reserve", "audit"):
        ref.chart(state)
    if name == "dispatch":
        for order_id in sorted(state.orders):
            ref.explore(state, state.orders[order_id][0])
        ref.walk(state, (2, 2))
    return (state, (5, 4)) if name in ("walk", "explore") else (state,)


def build_library():
    library = new_library()
    for definition in definitions():
        name = definition.name
        domain = (inputs(name),)
        library.write(definition)
        library.check(name)
        if definition.kind == "combinator":
            family = dict(zip(definition.spec.op_params, ((slot,) for slot in SLOTS[name])))
            sample = tuple(kernel.FnRef(slot) for slot in SLOTS[name]) + domain[0]
            request = VerifyRequest("bounded", domain, {"domain": "one finite warehouse state",
                "size": len(domain), "op_family": family}, extra={"op_family": family})
        else:
            sample = domain[0]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "one finite authorized warehouse state", "size": len(domain)},
                                    reference={"frontier": ref.frontier, "route_len": ref.route_len,
                                               "reserve": ref.reserve, "audit": ref.audit}[name])
        library.make_callable(name, (sample,))
        library.verify(name, request)
        library.account(name)
        library.promote(name, Contract(f"{name}: exact on the stated bounded scope"))
    return library
