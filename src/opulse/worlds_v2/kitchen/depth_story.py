"""Timed-kitchen invented cards, composed by the kernel."""

from itertools import combinations, product

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
from opulse.atoms.values import Bottom, Card

from . import depth_hosts as hosts
from .world import new_library


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def recipe_call(action, state):
    result = n.Lit(Bottom("invalid_recipe"))
    for name in reversed(tuple(hosts.RECIPES)):
        result = n.Case(((n.Test(call("eq", action, n.Lit(name))),
                          call(name, state)),), result)
    return result


def seq_spec():
    actions = var("actions")
    seq_body = n.Rec("start_fold", ("remaining", "current"),
                     n.Case(((n.Test(call("empty", var("remaining"))), var("current")),),
                            call("start_fold", call("tail", var("remaining")),
                                 recipe_call(call("head", var("remaining")), var("current")))),
                     (actions, var("state")), call("length", var("remaining")))
    return CombinatorSpec("seq", ("actions", "state"), (), seq_body)


CHOICES = tuple(actions for width in range(len(hosts.RECIPES) + 1)
                for actions in combinations(sorted(hosts.RECIPES), width)
                if len({hosts.RECIPES[action][0] for action in actions}) == len(actions))


def reach_nodes():
    current = var("frontier")
    existing = var("existing")
    candidate = var("candidate")
    old = call("head", existing)
    same = n.Test(call("eq", call("field", old, n.Lit(0)),
                       call("field", candidate, n.Lit(0))))
    better = n.Or(n.Test(call("lt", call("field", candidate, n.Lit(2)),
                             call("field", old, n.Lit(2)))),
                  n.And(n.Test(call("eq", call("field", candidate, n.Lit(2)),
                                    call("field", old, n.Lit(2)))),
                        n.Test(call("lt", call("field", candidate, n.Lit(1)),
                                     call("field", old, n.Lit(1))))))
    replace = n.Case(((better, call("cons", candidate, call("tail", existing))),), existing)
    insert = n.Rec("insert_state", ("existing", "candidate"),
                   n.Case(((n.Test(call("empty", existing)), call("cons", candidate, n.Lit(()))),
                           (same, replace)),
                          call("cons", old, call("insert_state", call("tail", existing), candidate))),
                   (var("next_frontier"), candidate), call("length", existing))
    row = var("row")
    action = call("head", var("remaining_actions"))
    possible = call("optional", call("slot", action, call("field", row, n.Lit(0))))
    make_row = call("seq_triple", call("head", var("possible")),
                    call("append", call("field", row, n.Lit(1)), action),
                    call("add", call("field", row, n.Lit(2)), call("length", action)))
    try_action = n.Let("possible", possible,
                       n.Case(((n.Test(call("empty", var("possible"))), var("next_frontier")),),
                              n.Let("candidate", make_row, insert)))
    expand = n.Rec("expand_actions", ("remaining_actions", "next_frontier", "row"),
                   n.Case(((n.Test(call("empty", var("remaining_actions"))),
                            var("next_frontier")),),
                          call("expand_actions", call("tail", var("remaining_actions")),
                               try_action, row)),
                   (n.Lit(CHOICES), var("next_frontier"), row),
                   call("length", var("remaining_actions")))
    advance = n.Rec("advance_rows", ("rows", "next_frontier"),
                    n.Case(((n.Test(call("empty", var("rows"))), var("next_frontier")),),
                           call("advance_rows", call("tail", var("rows")),
                                n.Let("row", call("head", var("rows")), expand))),
                    (current, n.Lit(())), call("length", var("rows")))
    output = n.Rec("pack_rows", ("rows",),
                   n.Case(((n.Test(call("empty", var("rows"))), n.Lit(())),),
                          call("cons", call("make_plan", var("start"),
                                            call("field", call("head", var("rows")), n.Lit(1))),
                               call("pack_rows", call("tail", var("rows"))))),
                   (current,), call("length", var("rows")))
    search = n.Rec("search_ticks", ("remaining", "frontier"),
                   n.Case(((n.Test(call("eq", var("remaining"), n.Lit(0))), output),),
                          call("search_ticks", call("sub", var("remaining"), n.Lit(1)), advance)),
                   (var("horizon"), call("cons", call("seq_triple", var("start"), n.Lit(()), n.Lit(0)),
                                                 n.Lit(()))), var("remaining"), memo=False)
    reachable = n.Case(((n.And(n.Test(call("le", n.Lit(0), var("horizon"))),
                                 n.Test(call("le", var("horizon"), n.Lit(12)))), search),),
                       n.Lit(Bottom("horizon")))
    return reachable, advance, output


def reach_body():
    return reach_nodes()[0]


def definitions():
    actions = var("actions")
    slot_body = n.Case(((n.Test(call("increasing", actions)),
                         call("tick", call("seq", actions, var("state")))),),
                       n.Lit(Bottom("duplicate_or_unsorted")))
    slot_spec = CombinatorSpec("slot", ("actions", "state"), (), slot_body)
    data_spec = ObjectSpec("PlanData", "compose", tags={"record": (("start", "State"),
                                                                ("slots", "List"),
                                                                ("end", "State"))})
    original, slots = var("start"), var("slots")
    replay = n.Rec("replay", ("remaining", "current"),
                   n.Case(((n.Test(call("empty", var("remaining"))), var("current")),),
                          call("replay", call("tail", var("remaining")),
                               call("slot", call("head", var("remaining")), var("current")))),
                   (slots, original), call("length", var("remaining")))
    plan_valid = n.Case(((n.Test(call("le", call("length", call("PlanData.slots", var("x"))), n.Lit(12))),
                         call("eq", call("PlanData.end", var("x")),
                              n.Rec("plan_replay", ("remaining", "current"),
                                    n.Case(((n.Test(call("empty", var("remaining"))),
                                             var("current")),),
                                           call("plan_replay", call("tail", var("remaining")),
                                                call("slot", call("head", var("remaining")), var("current")))),
                                    (call("PlanData.slots", var("x")),
                                     call("PlanData.start", var("x"))),
                                    call("length", var("remaining"))))),), n.Lit(False))
    plan_spec = ObjectSpec("Plan", "refine", base="PlanData", valid=plan_valid,
                           sealed=True, interface=("make_plan", "Plan.start", "Plan.slots",
                                                   "Plan.end", "peak", "yield", "meets",
                                                   "reach", "score", "best", "filter_plans",
                                                   "earliest", "min_flour"))
    make_body = n.Case(((n.Test(call("le", call("length", slots), n.Lit(12))),
                         call("Plan.make", call("PlanData.record", original, slots, replay))),),
                       n.Lit(Bottom("horizon")))
    make_spec = OperationSpec("make_plan", "combine", (Edge("State", name="start"),
                                                        Edge("List", name="slots")),
                              Edge("Plan"), "Replay all slots before constructing the plan.",
                              ("horizon", "station", "stock"),
                              extra={"input_names": ["start", "slots"]})
    plan = var("p")
    counts = call("stock", call("Plan.start", plan))
    public_start = call("state", *(call("item", counts, n.Lit(index)) for index in range(4)))
    actions_now = var("actions_now")
    maximum = var("maximum")
    concurrent = var("concurrent")
    next_peak = n.Case(((n.Test(call("lt", maximum, concurrent)), concurrent),), maximum)
    scan_body = n.Let("actions_now", call("head", var("remaining")),
                      n.Let("concurrent", call("length", call("busy",
                          call("seq", actions_now, var("current")))),
                            call("scan_peak", call("tail", var("remaining")),
                                 call("slot", actions_now, var("current")), next_peak)))
    peak_body = n.Rec("scan_peak", ("remaining", "current", "maximum"),
                      n.Case(((n.Test(call("empty", var("remaining"))), maximum),), scan_body),
                      (call("Plan.slots", plan), public_start,
                       call("length", call("busy", public_start))),
                      call("length", var("remaining")))
    peak_spec = ObservationSpec("peak", ("stock", "busy"), peak_body,
                                extra={"subject": "_hidden", "params": ["p"]})
    reachable, advance_frontier, pack_frontier = reach_nodes()
    reach_spec = OperationSpec("reach", "combine", (Edge("State", name="start"),
                                                   Edge("int", name="horizon")), Edge("List"),
                               "Enumerate each distinct complete dated state at an exact horizon.",
                               ("horizon",), extra={"input_names": ["start", "horizon"]})
    advance_spec = OperationSpec("advance_frontier", "combine",
                                 (Edge("List", name="frontier"),), Edge("List"),
                                 "Extend each complete-state witness by one legal concurrent slot.",
                                 extra={"input_names": ["frontier"]})
    pack_spec = OperationSpec("pack_frontier", "combine",
                              (Edge("State", name="start"), Edge("List", name="frontier")),
                              Edge("List"), "Validate and seal each frontier witness as a Plan.",
                              extra={"input_names": ["start", "frontier"]})
    yield_body = call("seq_triple", *(call("item", call("stock", call("Plan.end", plan)),
                                               n.Lit(index)) for index in (6, 7, 9)))
    yield_spec = ObservationSpec("yield", ("stock",), yield_body,
                                 extra={"subject": "_hidden", "params": ["p"]})
    order_data = ObjectSpec("OrderData", "compose",
                            tags={"order": (("bread", "int"), ("cake", "int"),
                                            ("dessert", "int"), ("deadline", "int"))})
    terms = tuple(call("OrderData." + name, var("x"))
                  for name in ("bread", "cake", "dessert", "deadline"))
    conditions = tuple(n.And(n.Test(call("le", n.Lit(0), item)),
                             n.Test(call("le", item, n.Lit(8 if index < 3 else 12))))
                       for index, item in enumerate(terms))
    order_condition = conditions[0]
    for item in conditions[1:]:
        order_condition = n.And(order_condition, item)
    order_spec = ObjectSpec("Order", "refine", base="OrderData",
                            valid=n.Case(((order_condition, n.Lit(True)),), n.Lit(False)),
                            sealed=True, interface=("make_order", "Order.bread", "Order.cake",
                                                    "Order.dessert", "Order.deadline", "meets",
                                                    "score", "filter_plans", "earliest", "best",
                                                    "min_flour"))
    make_order_body = call("Order.make", call("OrderData.order", *(var(name) for name in
                                  ("bread", "cake", "dessert", "deadline"))))
    make_order_spec = OperationSpec("make_order", "combine",
                                    tuple(Edge("int", name=name) for name in
                                          ("bread", "cake", "dessert", "deadline")),
                                    Edge("Order"), "Construct only a bounded valid order.",
                                    ("invalid",), extra={"input_names": ["bread", "cake",
                                                                      "dessert", "deadline"]})
    requested = var("o")
    produced = call("yield", plan)
    meets_body = n.Case(((n.And(n.Test(call("le", call("field", call("Plan.end", plan), n.Lit(0)),
                                               call("Order.deadline", requested))),
                               n.And(n.Test(call("le", call("Order.bread", requested),
                                                 call("item", produced, n.Lit(0)))),
                                     n.And(n.Test(call("le", call("Order.cake", requested),
                                                       call("item", produced, n.Lit(1)))),
                                           n.Test(call("le", call("Order.dessert", requested),
                                                       call("item", produced, n.Lit(2))))))),
                          n.Lit(True)),), n.Lit(False))
    meets_spec = OperationSpec("meets", "decide", (Edge("Plan", name="p"),
                                                  Edge("Order", name="o")), Edge("bool"),
                                "Compare three observed finished stocks and the absolute deadline.",
                                extra={"input_names": ["p", "o"]})
    remaining = var("remaining")
    filter_body = n.Rec("keep", ("remaining",),
                        n.Case(((n.Test(call("empty", remaining)), n.Lit(())),
                                (n.Test(call("pred", call("head", remaining), requested)),
                                 call("cons", call("head", remaining),
                                      call("keep", call("tail", remaining))))),
                               call("keep", call("tail", remaining))),
                        (var("plans"),), call("length", remaining))
    filter_spec = CombinatorSpec("filter_plans", ("pred", "plans", "o"),
                                 ("pred",), filter_body)
    starts_body = n.Rec("sum_starts", ("remaining",),
                        n.Case(((n.Test(call("empty", remaining)), n.Lit(0)),),
                               call("add", call("length", call("head", remaining)),
                                    call("sum_starts", call("tail", remaining)))),
                        (call("Plan.slots", plan),), call("length", remaining))
    score_body = n.Case(((n.Test(call("meets", plan, requested)),
                          call("seq_triple", call("field", call("Plan.end", plan), n.Lit(0)),
                               starts_body, call("Plan.slots", plan))),),
                        n.Lit(Bottom("not_met")))
    score_spec = OperationSpec("score", "combine", (Edge("Plan", name="p"),
                                                   Edge("Order", name="o")), Edge("List"),
                               "Compare deadline, starts, then the exact slot witness.",
                               ("not_met",), extra={"input_names": ["p", "o"]})
    alternate_spec = OperationSpec("score_alt", "combine", (Edge("Plan", name="p"),
                                                             Edge("Order", name="o")), Edge("List"),
                                    "Same deterministic key under a second metric slot.",
                                    ("not_met",), extra={"input_names": ["p", "o"]})
    query_value = var("q")
    query_state = call("field", query_value, n.Lit(0))
    query_order = call("field", query_value, n.Lit(1))
    raw_stock = call("stock", query_state)
    public_state = call("state", *(call("item", raw_stock, n.Lit(index)) for index in range(4)))
    now = var("now")
    remaining_ticks = var("remaining_ticks")
    oven_jobs = call("add", call("Order.cake", query_order),
                     call("Order.dessert", query_order))
    oven_work = call("add", call("mul", n.Lit(3), call("Order.bread", query_order)),
                     call("mul", n.Lit(2), oven_jobs))
    ready = n.Case(((n.Test(call("lt", n.Lit(0), oven_jobs)), n.Lit(1)),
                    (n.Test(call("lt", n.Lit(0), call("Order.bread", query_order))),
                     n.Lit(2))), n.Lit(0))
    dessert_bound = n.Case(((n.Test(call("lt", n.Lit(0),
                                          call("Order.dessert", query_order))), n.Lit(4)),),
                           n.Lit(0))
    oven_bound = call("add", oven_work, ready)
    lower_bound = n.Case(((n.Test(call("lt", oven_bound, dessert_bound)),
                           dessert_bound),), oven_bound)
    witnesses = call("filter_plans", n.Lit(kernel.FnRef("meets")),
                     call("pack_frontier", public_state, var("frontier")), query_order)
    initial_frontier = call("cons", call("seq_triple", public_state, n.Lit(()), n.Lit(0)),
                            n.Lit(()))
    warmed_frontier = n.Rec("warm_frontier", ("remaining", "frontier"),
                            n.Case(((n.Test(call("eq", var("remaining"), n.Lit(0))),
                                     var("frontier")),),
                                   call("warm_frontier", call("sub", var("remaining"), n.Lit(1)),
                                        call("advance_frontier", var("frontier")))),
                            (lower_bound, initial_frontier), var("remaining"))
    earliest_search = n.Rec("earliest_tick", ("now", "remaining_ticks", "frontier"),
                            n.Case(((n.Test(call("empty", witnesses)),
                                     n.Case(((n.Test(call("eq", remaining_ticks, n.Lit(0))),
                                              n.Lit(Bottom("no_plan"))),),
                                            call("earliest_tick", call("add", now, n.Lit(1)),
                                                 call("sub", remaining_ticks, n.Lit(1)),
                                                 call("advance_frontier", var("frontier"))))),),
                                   now),
                            (lower_bound, call("sub", call("Order.deadline", query_order),
                                                    lower_bound), warmed_frontier), remaining_ticks)
    earliest_body = n.Case(((n.Test(call("le", lower_bound,
                                          call("Order.deadline", query_order))),
                              earliest_search),),
                           n.Lit(Bottom("no_plan")))
    earliest_spec = ObservationSpec("earliest", ("stock",), earliest_body,
                                    extra={"subject": "_hidden", "params": ["q"]})
    best_row = var("best_row")
    challenger = call("head", remaining)
    best_body = n.Let("qualified", call("filter_plans", n.Lit(kernel.FnRef("meets")),
                                               var("plans"), requested),
                      n.Case(((n.Test(call("empty", var("qualified"))),
                               n.Lit(Bottom("no_plan"))),),
                             n.Rec("choose_best", ("remaining", "best_row"),
                                   n.Case(((n.Test(call("empty", remaining)), best_row),),
                                          call("choose_best", call("tail", remaining),
                                               n.Case(((n.Test(call("lt", call("metric", challenger, requested),
                                                                      call("metric", best_row, requested))),
                                                        challenger),), best_row))),
                                   (call("tail", var("qualified")),
                                    call("head", var("qualified"))),
                                   call("length", remaining))))
    best_spec = CombinatorSpec("best", ("metric", "plans", "o"), ("metric",), best_body)
    flour = var("flour")
    modified = call("state", flour, *(call("item", raw_stock, n.Lit(index)) for index in (1, 2, 3)))
    required_flour = call("add", call("mul", n.Lit(2),
                                            call("Order.bread", query_order)),
                          call("add", call("Order.cake", query_order),
                               call("Order.dessert", query_order)))
    tried = n.Case(((n.Test(call("lt", flour, required_flour)), n.Lit(())),),
                   call("filter_plans", n.Lit(kernel.FnRef("meets")),
                        call("reach", modified, call("Order.deadline", query_order)),
                        query_order))
    min_body = n.Rec("try_flour", ("flour", "remaining_flour"),
                     n.Case(((n.Test(call("empty", tried)),
                              n.Case(((n.Test(call("eq", var("remaining_flour"), n.Lit(0))),
                                       n.Lit(Bottom("no_plan"))),),
                                     call("try_flour", call("add", flour, n.Lit(1)),
                                          call("sub", var("remaining_flour"), n.Lit(1))))),),
                            flour),
                     (n.Lit(0), n.Lit(8)), var("remaining_flour"))
    min_spec = ObservationSpec("min_flour", ("stock",), min_body,
                               extra={"subject": "_hidden", "params": ["q"]})
    return (
        Definition("slot", "combinator", "invented", 1,
                   tuple(sorted(n.references(slot_body))), slot_spec, slot_body),
        Definition("PlanData", "object", "invented", 1, (), data_spec, None),
        Definition("Plan", "object", "invented", 2,
                   tuple(sorted(n.references(plan_valid))), plan_spec, None),
        Definition("make_plan", "operation", "invented", 3,
                   tuple(sorted(n.references(make_body))), make_spec, make_body),
        Definition("peak", "observation", "invented", 3,
                   tuple(sorted(n.references(peak_body))), peak_spec, peak_body),
        Definition("advance_frontier", "operation", "invented", 2,
                   tuple(sorted(n.references(advance_frontier))), advance_spec, advance_frontier),
        Definition("pack_frontier", "operation", "invented", 4,
                   tuple(sorted(n.references(pack_frontier))), pack_spec, pack_frontier),
        Definition("reach", "operation", "invented", 4,
                   tuple(sorted(n.references(reachable))), reach_spec, reachable),
        Definition("yield", "observation", "invented", 3,
                   tuple(sorted(n.references(yield_body))), yield_spec, yield_body),
        Definition("OrderData", "object", "invented", 1, (), order_data, None),
        Definition("Order", "object", "invented", 1,
                   tuple(sorted(n.references(order_spec.valid))), order_spec, None),
        Definition("make_order", "operation", "invented", 2,
                   tuple(sorted(n.references(make_order_body))), make_order_spec, make_order_body),
        Definition("meets", "operation", "invented", 4,
                   tuple(sorted(n.references(meets_body))), meets_spec, meets_body),
        Definition("filter_plans", "combinator", "invented", 1,
                   tuple(sorted(n.references(filter_body) - {"pred"})), filter_spec, filter_body),
        Definition("score", "operation", "invented", 5,
                   tuple(sorted(n.references(score_body))), score_spec, score_body),
        Definition("score_alt", "operation", "invented", 6, ("score",),
                   alternate_spec, call("score", plan, requested)),
        Definition("earliest", "observation", "invented", 5,
                   tuple(sorted(n.references(earliest_body))), earliest_spec, earliest_body),
        Definition("best", "combinator", "invented", 5,
                   tuple(sorted((n.references(best_body) - {"metric"}) | {"meets"})),
                   best_spec, best_body),
        Definition("min_flour", "observation", "invented", 5,
                   tuple(sorted(n.references(min_body))), min_spec, min_body),
    )


def build_library():
    lib = new_library()
    states = tuple(hosts.state(*amounts) for amounts in product(range(3), repeat=4))
    seq_domain = tuple((actions, state) for state in states
                       for actions in ((), ("mix",), ("whisk",), ("mix", "whisk")))
    for definition in definitions():
        lib.write(definition)
        lib.check(definition.name)
        name = definition.name
        if name in ("PlanData", "OrderData"):
            initial = states[0]
            domain = (tuple((state, slots, state)
                            for state in states[:25] for slots in ((), ((),)))
                      if name == "PlanData" else
                      tuple(product(range(4), range(4), range(4), (5,))))
            sample = [domain[0]]
            request = VerifyRequest("exhaustive", domain,
                                    {"domain": "25 states x 2 shapes" if name == "PlanData"
                                     else "all 4x4x4 target triples at deadline 5",
                                     "description": "25 states x 2 shapes" if name == "PlanData"
                                     else "all 4x4x4 target triples at deadline 5",
                                     "size": len(domain)})
        elif name == "Plan":
            initial = states[0]
            sample = [(Card("PlanData", "record", (initial, (), initial)),)]
            request = VerifyRequest("bounded", tuple((Card("PlanData", "record",
                                                           (state, ((),), hosts.tick(state))),)
                                                      for state in states[:50]),
                                    {"domain": "50 initial states and one legal idle slot",
                                     "description": "50 initial states and one legal idle slot",
                                     "size": 50})
        elif name == "peak":
            valid = tuple(_oracle_plan(state, ((), ("mix",)))
                          for state in states if state.fields[1] and
                          sum(qty for item, _, qty in state.fields[1] if item == "flour") >= 2 and
                          sum(qty for item, _, qty in state.fields[1] if item == "water") >= 1)
            plans = tuple(_oracle_plan(state, ((),)) for state in states[:50]) + valid
            sample = [(plans[0],)]
            request = VerifyRequest("bounded", tuple((entry,) for entry in plans),
                                    {"domain": "50 idle plans and all 0..2 raw states allowing delayed mix",
                                     "description": "50 idle plans and all 0..2 raw states allowing delayed mix",
                                     "size": len(plans)}, reference=_oracle_peak)
        elif name == "advance_frontier":
            domain = tuple((_frontier0(state),) for state in states[:50])
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "50 initial complete-state singleton frontiers",
                                     "description": "50 initial complete-state singleton frontiers",
                                     "size": 50}, reference=_oracle_advance)
        elif name == "pack_frontier":
            domain = tuple((state, _frontier0(state)) for state in states[:50])
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "50 initial singleton frontiers",
                                     "description": "50 initial singleton frontiers",
                                     "size": 50},
                                    reference=lambda state, frontier: tuple(_oracle_plan(state, row[1])
                                                                            for row in frontier))
        elif name == "reach":
            domain = tuple((state, horizon) for state in states[:25] for horizon in (0, 1, 2))
            sample = [(hosts.state(2, 1, 0, 0), 1)]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "25 initial states with horizons 0..2",
                                     "description": "25 initial states with horizons 0..2",
                                     "size": len(domain)}, reference=_oracle_reach)
        elif name == "yield":
            plans = tuple(_oracle_plan(state, ((),)) for state in states[:60])
            sample = [(plans[0],)]
            request = VerifyRequest("bounded", tuple((entry,) for entry in plans),
                                    {"domain": "60 initial states with one idle tick",
                                     "description": "60 initial states with one idle tick", "size": 60},
                                    reference=lambda plan: tuple(hosts.stock(plan.fields[0].fields[2])[index]
                                                                 for index in (6, 7, 9)))
        elif name == "Order":
            domain = tuple((Card("OrderData", "order", (bread, cake, dessert, deadline)),)
                           for bread, cake, dessert, deadline in
                           product(range(3), range(3), range(3), (5, 6)))
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "3x3x3 target triples at deadlines 5 and 6",
                                     "description": "3x3x3 target triples at deadlines 5 and 6",
                                     "size": len(domain)})
        elif name == "make_order":
            domain = tuple(product(range(3), range(3), range(3), (5, 6)))
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "3x3x3 target triples at deadlines 5 and 6",
                                     "description": "3x3x3 target triples at deadlines 5 and 6",
                                     "size": len(domain)},
                                    reference=lambda *parts: _oracle_order(*parts))
        elif name == "meets":
            plans = tuple(_oracle_plan(state, ((),)) for state in states[:25])
            orders = tuple(_oracle_order(*parts) for parts in ((0, 0, 0, 1),
                                                               (1, 0, 0, 1), (0, 0, 1, 1)))
            domain = tuple(product(plans, orders))
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "25 idle plans x 3 orders by tick 1",
                                     "description": "25 idle plans x 3 orders by tick 1",
                                     "size": len(domain)}, reference=_oracle_meets)
        elif name == "filter_plans":
            plans = tuple(_oracle_plan(state, ((),)) for state in states[:25])
            order = _oracle_order(0, 0, 0, 1)
            others = (_oracle_order(1, 0, 0, 1), _oracle_order(0, 0, 1, 1))
            domain = tuple((plans[:length], request) for length in range(1, 21)
                           for request in (order, *others))
            sample = [(kernel.FnRef("meets"), *domain[0])]
            family = ["meets", "eq"]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "20 plan prefixes of length 1..20 x 3 orders x meets/eq predicates",
                                     "description": "20 plan prefixes of length 1..20 x 3 orders x meets/eq predicates",
                                     "size": len(domain), "op_family": family},
                                    reference=lambda assignment, args: tuple(
                                        plan for plan in args[0] if
                                        (_oracle_meets(plan, args[1]) if assignment["pred"] == "meets"
                                         else plan == args[1])),
                                    extra={"op_family": family})
        elif name in ("score", "score_alt"):
            plans = tuple(_oracle_plan(state, ((),)) for state in states[:60])
            order = _oracle_order(0, 0, 0, 1)
            domain = tuple((plan, order) for plan in plans)
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "60 initial states with one idle tick and zero target order",
                                     "description": "60 initial states with one idle tick and zero target order",
                                     "size": len(domain)}, reference=_oracle_score)
        elif name == "earliest":
            domain = tuple((hosts.query(state, _oracle_order(bread, 0, 0, 1)),)
                           for state in states[:25] for bread in (0, 1))
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "25 initial states x bread target 0 or 1 by tick 1",
                                     "description": "25 initial states x bread target 0 or 1 by tick 1",
                                     "size": 50}, reference=_oracle_earliest)
        elif name == "best":
            plans = tuple(_oracle_plan(state, ((),)) for state in states[:25])
            orders = (_oracle_order(0, 0, 0, 1), _oracle_order(1, 0, 0, 1))
            domain = tuple((plans[:length], order)
                           for length in range(1, 26) for order in orders)
            sample = [(kernel.FnRef("score"), *domain[0])]
            family = ["score", "score_alt"]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "25 plan-prefix lengths x 2 orders x score/score_alt metrics",
                                     "description": "25 plan-prefix lengths x 2 orders x score/score_alt metrics",
                                     "size": 50, "op_family": family},
                                    reference=lambda assignment, args: _oracle_best(*args),
                                    extra={"op_family": family})
        elif name == "min_flour":
            domain = tuple((hosts.query(state, _oracle_order(bread, 0, 0, 0)),)
                           for state in states[:25] for bread in (0, 1))
            sample = [domain[0]]
            request = VerifyRequest("bounded", domain,
                                    {"domain": "25 initial states x bread target 0 or 1 by tick 0, search flour 0..8",
                                     "description": "25 initial states x bread target 0 or 1 by tick 0, search flour 0..8",
                                     "size": 50}, reference=_oracle_min_flour)
        elif name == "make_plan":
            sample = [(hosts.state(2, 1, 0, 0), (("mix",),))]
            request = VerifyRequest("bounded", tuple((state, slots) for state in states[:25]
                                                     for slots in ((), ((),), (("mix",),))),
                                    {"domain": "25 initial states, plans up to 1 tick",
                                     "description": "25 initial states and three plans of up to 1 tick",
                                     "size": 75},
                                    reference=lambda state, slots: _oracle_plan(state, slots))
        else:
            sample = [(('mix',), hosts.state(2, 1, 0, 0))]
            request = VerifyRequest("bounded", seq_domain,
                                    {"domain": "81 initial states and four action tuples of up to 2 starts",
                                     "description": "81 initial states and four action tuples of up to 2 starts",
                                     "size": len(seq_domain), "op_family": ["mix", "whisk"]},
                                    reference=lambda assignment, inputs:
                                    _oracle_slot(*inputs),
                                    extra={"op_family": ["mix", "whisk"]})
        lib.make_callable(name, sample)
        lib.verify(name, request)
        lib.account(name)
        lib.promote(name, Contract(f"Verified {name} on its declared finite family."))
        if name in ("PlanData", "OrderData"):
            tag = "record" if name == "PlanData" else "order"
            sorts = ("State", "List", "State") if name == "PlanData" else ("int",) * 4
            constructor = OperationSpec(name + "." + tag, "combine",
                                        tuple(Edge(sort) for sort in sorts), Edge(name),
                                        "Generated positional constructor.")
            lib._definitions[name + "." + tag] = Definition(name + "." + tag,
                "operation", "given", 0, (), constructor, {"generated": name}, status="promoted")
        if name == "Plan":
            maker = OperationSpec("Plan.make", "combine", (Edge("PlanData"),),
                                  Edge("Plan"), "Validated refinement constructor.")
            lib._definitions["Plan.make"] = Definition("Plan.make", "operation", "given", 0,
                                                         (), maker, {"generated": "Plan"},
                                                         status="promoted")
            for accessor, sort in (("start", "State"), ("slots", "List"), ("end", "State")):
                specification = OperationSpec("Plan." + accessor, "transform", (Edge("Plan"),),
                                              Edge(sort), "Generated validated accessor.")
                lib._definitions["Plan." + accessor] = Definition(
                    "Plan." + accessor, "operation", "given", 2, (), specification,
                    {"generated": "Plan"}, status="promoted")
        if name == "Order":
            maker = OperationSpec("Order.make", "combine", (Edge("OrderData"),),
                                  Edge("Order"), "Validated refinement constructor.")
            lib._definitions["Order.make"] = Definition("Order.make", "operation", "given",
                0, (), maker, {"generated": "Order"}, status="promoted")
            for accessor in ("bread", "cake", "dessert", "deadline"):
                specification = OperationSpec("Order." + accessor, "transform", (Edge("Order"),),
                                              Edge("int"), "Generated validated accessor.")
                lib._definitions["Order." + accessor] = Definition(
                    "Order." + accessor, "operation", "given", 1, (), specification,
                    {"generated": "Order"}, status="promoted")
    return lib


def _oracle_seq(actions, state):
    for action in actions:
        state = getattr(hosts, action)(state)
        if isinstance(state, Bottom):
            return state
    return state


def _oracle_slot(actions, state):
    if not hosts.increasing(actions):
        return Bottom("duplicate_or_unsorted")
    result = _oracle_seq(actions, state)
    return result if isinstance(result, Bottom) else hosts.tick(result)


def _oracle_plan(state, slots):
    if len(slots) > 12:
        return Bottom("horizon")
    end = state
    for actions in slots:
        end = _oracle_slot(actions, end)
        if isinstance(end, Bottom):
            return end
    return Card("Plan", "val", (Card("PlanData", "record", (state, slots, end)),))


def _oracle_peak(plan):
    start, slots, _ = plan.fields[0].fields
    current = start
    maximum = len(current.fields[2])
    for actions in slots:
        launched = _oracle_seq(actions, current)
        maximum = max(maximum, len(launched.fields[2]))
        current = _oracle_slot(actions, current)
    return maximum


def _oracle_reach(start, horizon):
    frontier = {start: ((), 0)}
    for _ in range(horizon):
        next_frontier = {}
        for current, (slots, starts) in frontier.items():
            for actions in CHOICES:
                result = _oracle_slot(actions, current)
                if isinstance(result, Bottom):
                    continue
                candidate = (slots + (actions,), starts + len(actions))
                previous = next_frontier.get(result)
                if previous is None or candidate[1] < previous[1]:
                    next_frontier[result] = candidate
        frontier = next_frontier
    return tuple(Card("Plan", "val", (Card("PlanData", "record", (start, slots, end)),))
                 for end, (slots, _) in frontier.items())


def _frontier0(state):
    return ((state, (), 0),)


def _oracle_advance(frontier):
    next_frontier = {}
    for current, slots, count in frontier:
        for actions in CHOICES:
            outcome = _oracle_slot(actions, current)
            if isinstance(outcome, Bottom):
                continue
            candidate = outcome, slots + (actions,), count + len(actions)
            previous = next_frontier.get(outcome)
            if previous is None or candidate[2:] < previous[2:] or (
                    candidate[2] == previous[2] and candidate[1] < previous[1]):
                next_frontier[outcome] = candidate
    return tuple(next_frontier.values())


def _oracle_order(bread, cake, dessert, deadline):
    if any(not 0 <= amount <= 8 for amount in (bread, cake, dessert)) or not 0 <= deadline <= 12:
        return Bottom("invalid")
    return Card("Order", "val", (Card("OrderData", "order", (bread, cake, dessert, deadline)),))


def _oracle_meets(plan, order):
    end = plan.fields[0].fields[2]
    bread, cake, dessert, deadline = order.fields[0].fields
    amounts = hosts.stock(end)
    return end.fields[0] <= deadline and all(have >= required for have, required in
                                            zip((amounts[6], amounts[7], amounts[9]),
                                                (bread, cake, dessert)))


def _oracle_score(plan, order):
    if not _oracle_meets(plan, order):
        return Bottom("not_met")
    _, slots, end = plan.fields[0].fields
    return end.fields[0], sum(len(actions) for actions in slots), slots


def _oracle_best(plans, order):
    valid = [plan for plan in plans if _oracle_meets(plan, order)]
    return min(valid, key=lambda plan: _oracle_score(plan, order)) if valid else Bottom("no_plan")


def _oracle_earliest(query):
    start, order = query.fields
    deadline = order.fields[0].fields[3]
    for horizon in range(deadline + 1):
        if any(_oracle_meets(plan, order) for plan in _oracle_reach(start, horizon)):
            return horizon
    return Bottom("no_plan")


def _oracle_min_flour(query):
    start, order = query.fields
    amounts = hosts.stock(start)
    for flour in range(9):
        result = _oracle_earliest(hosts.query(hosts.state(flour, *amounts[1:4]), order))
        if not isinstance(result, Bottom):
            return flour
    return Bottom("no_plan")
