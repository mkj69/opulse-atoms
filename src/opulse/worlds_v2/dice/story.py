"""Kernel-unfolded exact dice, Bayesian updates and finite absorbing walks."""

from fractions import Fraction
from itertools import product

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

from . import adapter, hosts
from .world import new_library


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def index(value, number):
    return call("field", value, lit(number))


ONE = lit(hosts.to_card(Fraction(1)))
ZERO = lit(hosts.to_card(Fraction(0)))
FAIR = lit(hosts.FAIR)
TILT = lit(hosts.TILT)


def _fold(name, items, initial, operation):
    remaining, accumulated = var("remaining"), var("accumulated")
    body = n.Case(((n.Test(call("is_empty", remaining)), accumulated),),
                  n.Let("current", call("head", remaining),
                        call(name, call("tail", remaining), operation(var("current"), accumulated))))
    return n.Rec(name, ("remaining", "accumulated"), body,
                 (items, initial), call("length", remaining))


def bind_spec():
    def inner(entry, accumulated):
        return call("cons", call("make_entry", call("item", entry),
                                  call("multiply", call("weight", var("outer")), call("weight", entry))), accumulated)

    def outer(entry, accumulated):
        return n.Let("outer", entry,
                     _fold("inner_bind", call("entries", call("k", call("item", entry), var("context"))),
                           accumulated, inner))

    body = call("make_dist", _fold("outer_bind", call("entries", var("dist")), lit(()), outer))
    return CombinatorSpec("bind", ("dist", "k", "context"), ("k",), body)


def continuation_defns():
    first = var("first")
    second = var("second")
    point = call("pure", call("pair", first, second))
    pair_with = call("bind", var("second_dist"), lit(kernel.FnRef("pair_one")), first)
    score_one = call("pure", call("f", var("value")))
    return (kernel.Defn("first_score", ("value",), index(var("value"), 0), "operation", 0),
            kernel.Defn("pair_one", ("second", "first"), point, "combinator", 0),
            kernel.Defn("pair_with", ("first", "second_dist"), pair_with, "combinator", 0),
            kernel.Defn("score_one", ("value", "f"), score_one, "combinator", 0),
            kernel.Defn("step_with", ("arg0", "arg1", "roll_slot", "total_slot", "jump_slot"),
                        _step_body(var("roll_slot"), var("total_slot"), "jump_slot"), "combinator", 0),
            kernel.Defn("roll_alias", ("value",), call("roll", var("value")), "operation", 0),
            kernel.Defn("total_alias", ("value",), call("total", var("value")), "operation", 0),
            kernel.Defn("jump_alias", ("position", "points", "goal"),
                        call("jump", var("position"), var("points"), var("goal")), "operation", 0))


def _definition(name, kind, spec, body, dependencies, layer=None):
    if body is not None:
        references = n.references(body) - set(getattr(spec, "op_params", ()))
        if kind == "combinator":
            references |= n.operation_literals(body)
        dependencies = tuple(sorted(references))
    elif kind == "object" and spec.valid is not None:
        references = n.references(spec.valid)
        dependencies = tuple(sorted(references | {reference.split(".", 1)[0] for reference in references
                                                if reference.startswith(("Event.", "Belief.", "Walk."))}))
    return Definition(name, kind, "invented", layer if layer is not None else 1,
                      tuple(dict.fromkeys(dependencies)), spec, body)


def _operation(name, body, inputs, output, dependencies, layer):
    spec = OperationSpec(name, "transform", tuple(Edge(sort, name=f"arg{index}") for index, sort in enumerate(inputs)),
                         Edge(output), f"Exact {name} from preceding definitions.", ("invalid", "domain"),
                         {"body": body}, extra={"input_names": tuple(f"arg{index}" for index in range(len(inputs)))})
    return _definition(name, "operation", spec, body, dependencies, layer)


def _hitting_body():
    goal = index(call("Walk.base", var("arg0")), 1)
    current = var("position")
    die_index = var("hidden")
    column = var("column")
    row_probability = call("mass", var("distribution"), call("cons", call("state", column, die_index), lit(())))
    diagonal = n.Case(((n.Test(call("equal", current, column)), ONE),), ZERO)
    columns = n.Rec("columns", ("column", "collected"),
                    n.Case(((n.Test(call("equal", column, lit(-1))), var("collected")),),
                           call("columns", call("int_sub", column, lit(1)),
                                call("cons", call("subtract", diagonal, row_probability), var("collected")))),
                    (call("int_sub", goal, lit(1)), call("cons", ONE, lit(()))),
                    call("int_add", column, lit(1)))
    rows = n.Rec("rows", ("position", "matrix"),
                 n.Case(((n.Test(call("equal", current, lit(-1))), var("matrix")),),
                        n.Let("distribution", call("step", var("arg0"), call("state", current, die_index)),
                              call("rows", call("int_sub", current, lit(1)),
                                   call("cons", columns, var("matrix"))))),
                 (call("int_sub", goal, lit(1)), lit(())), call("int_add", current, lit(1)))

    index_value = var("pivot")
    current_matrix = var("matrix")
    pivot_row = call("nth", current_matrix, index_value)
    pivot_value = call("nth", pivot_row, index_value)
    normalize = n.Rec("normalize", ("left",),
                      n.Case(((n.Test(call("is_empty", var("left"))), lit(())),),
                             call("cons", call("divide", call("head", var("left")), var("diagonal")),
                                  call("normalize", call("tail", var("left"))))),
                      (pivot_row,), call("length", var("left")))
    elimination_row = n.Rec("eliminate_elements", ("left", "right"),
                            n.Case(((n.Test(call("is_empty", var("left"))), lit(())),),
                                   call("cons", call("subtract", call("head", var("left")),
                                                         call("multiply", var("factor"), call("head", var("right")))),
                                        call("eliminate_elements", call("tail", var("left")), call("tail", var("right"))))),
                            (var("old_row"), var("unit_row")), call("length", var("left")))
    eliminate = n.Rec("eliminate", ("row_index", "updated"),
                      n.Case(((n.Test(call("equal", var("row_index"), goal)), var("updated")),),
                             call("eliminate", call("int_add", var("row_index"), lit(1)),
                                  n.Case(((n.Test(call("equal", var("row_index"), index_value)), var("updated")),),
                                         n.Let("old_row", call("nth", var("updated"), var("row_index")),
                                               n.Let("factor", call("nth", var("old_row"), index_value),
                                                     call("replace_at", var("updated"), var("row_index"), elimination_row)))))),
                      (lit(0), call("replace_at", current_matrix, index_value, var("unit_row"))),
                      call("int_sub", goal, var("row_index")))
    elimination = n.Rec("pivots", ("pivot", "matrix"),
                        n.Case(((n.Test(call("equal", index_value, goal)),
                                 call("nth", call("nth", current_matrix, lit(0)), goal)),),
                               n.Let("diagonal", pivot_value,
                                     n.Let("unit_row", normalize,
                                           call("pivots", call("int_add", index_value, lit(1)), eliminate)))),
                        (lit(0), rows), call("int_sub", goal, index_value))
    fair_solution = n.Let("hidden", lit(0), elimination)
    tilt_solution = n.Let("hidden", lit(1), elimination)
    return call("add", call("multiply", index(index(call("Walk.base", var("arg0")), 0), 0), fair_solution),
                call("multiply", index(index(call("Walk.base", var("arg0")), 0), 1), tilt_solution))


def _step_body(roll_slot, total_slot, jump_name):
    current = var("arg1")
    die = n.Case(((n.Test(call("equal", index(current, 1), lit(0))), FAIR),), TILT)
    pair_roll = call("independent", roll_slot, roll_slot, die, die)
    return n.Case(((n.Test(call("equal", index(current, 0), index(call("Walk.base", var("arg0")), 1))), call("pure", current)),),
                  call("make_dist", _fold("step_scores", call("entries", call("score", total_slot, pair_roll)), lit(()),
                                           lambda entry, accumulated: call("cons", call("make_entry",
                                               call("state", call(jump_name, index(current, 0), call("item", entry), index(call("Walk.base", var("arg0")), 1)),
                                                    index(current, 1)), call("weight", entry)), accumulated))))


def definitions():
    independent = call("bind", call("f", var("a")), lit(kernel.FnRef("pair_with")), call("g", var("b")))
    total = call("int_add", index(var("arg0"), 0), index(var("arg0"), 1))
    event_low = call("total", call("pair", index(var("x"), 0), lit(0)))
    event_high = index(var("x"), 1)
    event_valid = n.Case(((n.And(n.Test(call("less_equal", lit(2), event_low)),
                                  n.And(n.Test(call("less_equal", event_low, event_high)),
                                        n.Test(call("less_equal", event_high, lit(12))))),
                           call("equal", call("event", event_low, event_high), var("x"))),), lit(False))
    conditional = call("divide", call("mass", var("arg0"), call("intersect", call("Event.base", var("arg1")), call("Event.base", var("arg2")))),
                       call("mass", var("arg0"), call("Event.base", var("arg2"))))
    score = call("bind", var("dist"), lit(kernel.FnRef("score_one")), var("f"))
    mean = _fold("mean_entries", call("entries", var("dist")), ZERO,
                 lambda entry, accumulated: call("add", accumulated,
                                                 call("int_mul_fraction", call("item", entry), call("weight", entry))))
    fair_weight, tilt_weight = index(var("x"), 0), index(var("x"), 1)
    belief_valid = n.Case(((n.And(n.Test(call("less_equal", lit(0), index(fair_weight, 0))),
                                   n.And(n.Test(call("less_equal", lit(0), index(tilt_weight, 0))),
                                         n.Test(call("equal", call("add", fair_weight, tilt_weight), ONE)))),
                            call("equal", call("belief", fair_weight, tilt_weight), var("x"))),), lit(False))
    event_fair = call("mass", call("independent", lit(kernel.FnRef("roll")), lit(kernel.FnRef("roll")), FAIR, FAIR), call("Event.base", var("arg1")))
    event_tilt = call("mass", call("independent", lit(kernel.FnRef("roll")), lit(kernel.FnRef("roll")), TILT, TILT), call("Event.base", var("arg1")))
    update = n.Let("fair", call("multiply", index(call("Belief.base", var("arg0")), 0), event_fair),
                   n.Let("tilt", call("multiply", index(call("Belief.base", var("arg0")), 1), event_tilt),
                         n.Let("norm", call("add", var("fair"), var("tilt")),
                               call("Belief.make", call("belief", call("divide", var("fair"), var("norm")),
                                    call("divide", var("tilt"), var("norm")))))))
    walk_goal = index(var("x"), 1)
    walk_prior = index(var("x"), 0)
    walk_valid = n.Case(((n.And(n.Test(call("less_equal", lit(2), walk_goal)),
                                 n.And(n.Test(call("less_equal", walk_goal, lit(32))),
                                       n.Test(call("equal", call("Belief.base", call("Belief.make", walk_prior)), walk_prior)))),
                         call("equal", call("walk", walk_prior, walk_goal), var("x"))),), lit(False))
    step = _step_body(lit(kernel.FnRef("roll")), lit(kernel.FnRef("total")), "jump")
    start = call("make_dist", call("cons", call("make_entry", call("state", lit(0), lit(0)), index(index(call("Walk.base", var("arg0")), 0), 0)),
                          call("cons", call("make_entry", call("state", lit(0), lit(1)), index(index(call("Walk.base", var("arg0")), 0), 1)), lit(()))))
    def expand(entry, accumulated):
        return n.Let("outer_entry", entry,
                     _fold("expand_inner", call("entries", call("step_with", var("arg0"), call("item", var("outer_entry")),
                                                              var("roll_slot"), var("total_slot"), var("jump_slot"))), accumulated,
                           lambda inner, result: call("cons", call("make_entry", call("item", inner),
                                                 call("multiply", call("weight", var("outer_entry")), call("weight", inner))), result)))

    advance_step = call("make_dist", _fold("expand_outer", call("entries", var("distribution")), lit(()), expand))
    rounds = n.Rec("advance_round", ("round", "distribution"),
                   n.Case(((n.Test(call("equal", var("round"), var("arg1"))), var("distribution")),),
                          call("advance_round", call("int_add", var("round"), lit(1)),
                               advance_step)),
                   (lit(0), start), call("int_sub", var("arg1"), var("round")))
    advance = n.Case(((n.Test(call("less_equal", lit(0), var("arg1"))), rounds),), call("jump_slot", lit(-1), lit(2), lit(2)))
    targets = call("cons", call("state", index(call("Walk.base", var("arg0")), 1), lit(0)),
                   call("cons", call("state", index(call("Walk.base", var("arg0")), 1), lit(1)), lit(())))
    hit = call("mass", call("advance", lit(kernel.FnRef("roll")), lit(kernel.FnRef("total")),
                              lit(kernel.FnRef("jump")), var("arg0"), var("arg1")), targets)
    return (
        _definition("independent", "combinator", CombinatorSpec("independent", ("f", "g", "a", "b"), ("f", "g"), independent), independent, ("bind",), 1),
        _operation("total", total, ("value",), "int", ("int_add", "field"), 1),
        _definition("Event", "object", ObjectSpec("Event", "refine", base="event", valid=event_valid, canon=var("x")), None, (), 2),
        _operation("conditional", conditional, ("dist", "value", "value"), "fraction", ("mass", "intersect", "divide", "Event"), 3),
        _definition("score", "combinator", CombinatorSpec("score", ("f", "dist"), ("f",), score), score, ("bind",), 1),
        _definition("mean", "observation", ObservationSpec("mean", (), mean), mean,
                    ("mass", "cons", "int_sub", "int_add", "equal", "add", "int_mul_fraction"), 1),
        _definition("Belief", "object", ObjectSpec("Belief", "refine", base="belief", valid=belief_valid, canon=var("x")), None, (), 1),
        _operation("update", update, ("value", "value"), "value", ("multiply", "field", "mass", "independent", "add", "belief", "divide", "Belief", "Event"), 3),
        _definition("Walk", "object", ObjectSpec("Walk", "refine", base="walk", valid=walk_valid, canon=var("x")), None, (), 2),
        _operation("step", step, ("value", "state"), "dist", ("equal", "field", "pure", "independent", "score", "make_dist", "entries", "is_empty", "head", "tail", "length", "cons", "make_entry", "state", "jump", "item", "weight", "Walk"), 3),
        _definition("advance", "combinator", CombinatorSpec("advance", ("roll_slot", "total_slot", "jump_slot", "arg0", "arg1"),
                                                            ("roll_slot", "total_slot", "jump_slot"), advance), advance,
                    ("less_equal", "equal", "int_add", "int_sub", "step_with", "make_dist", "make_entry", "state", "field", "cons", "entries", "is_empty", "head", "tail", "length", "item", "weight", "multiply", "Walk"), 3),
        _definition("hit_prob", "observation", ObservationSpec("hit_prob", ("mass",), hit), hit, ("mass", "advance", "cons", "state", "field", "Walk"), 4),
        _definition("hitting", "observation", ObservationSpec("hitting", ("mass",), _hitting_body()), _hitting_body(),
                    ("field", "mass", "step", "state", "cons", "int_sub", "int_add", "equal", "subtract", "Walk",
                     "nth", "replace_at", "is_empty", "head", "tail", "length", "divide", "multiply", "add"), 4),
    )


def example_args():
    prior = _wrap("Belief", hosts.belief(hosts.to_card(Fraction(1, 2)), hosts.to_card(Fraction(1, 2))))
    posterior = _wrap("Belief", hosts.belief(hosts.to_card(Fraction(6, 25)), hosts.to_card(Fraction(19, 25))))
    high = _wrap("Event", hosts.event(10, 12))
    joint = hosts.distribution((hosts.pair(left, right), Fraction(1, 36)) for left, right in product(range(1, 7), repeat=2))
    tilted = hosts.distribution((hosts.pair(left, right), Fraction(hosts.TILT.fields[left-1] * hosts.TILT.fields[right-1], 144)) for left, right in product(range(1, 7), repeat=2))
    score = hosts.distribution((left + right, Fraction(hosts.TILT.fields[left-1] * hosts.TILT.fields[right-1], 144)) for left, right in product(range(1, 7), repeat=2))
    return {"independent": (kernel.FnRef("roll"), kernel.FnRef("roll"), hosts.FAIR, hosts.FAIR),
            "total": (hosts.pair(4, 5),), "Event": (hosts.event(10, 12),), "conditional": (joint, high, _wrap("Event", hosts.event(7, 12))),
            "score": (kernel.FnRef("total"), tilted), "mean": (score,), "Belief": (prior.fields[0],),
            "update": (prior, high), "Walk": (hosts.walk(posterior.fields[0], 6),),
            "step": (_wrap("Walk", hosts.walk(posterior.fields[0], 6)), hosts.state(0, 1)),
            "advance": (kernel.FnRef("roll"), kernel.FnRef("total"), kernel.FnRef("jump"),
                        _wrap("Walk", hosts.walk(posterior.fields[0], 6)), 3),
            "hit_prob": (_wrap("Walk", hosts.walk(posterior.fields[0], 6)), 8),
            "hitting": (_wrap("Walk", hosts.walk(posterior.fields[0], 6)),)}


def _wrap(name, value):
    return Card(name, "val", (value,))


def _reference(name):
    from worlds.catalogue.depth import dice as oracle

    def convert(value):
        if isinstance(value, Card):
            if value.tag == "val" and value.sort in ("Event", "Belief", "Walk"):
                return convert(value.fields[0])
            if value.sort == "die":
                return oracle.Die(value.fields)
            if value.sort == "pair":
                return tuple(value.fields)
            if value.sort == "state":
                return tuple(value.fields)
            if value.sort == "event":
                return oracle.Event(*value.fields)
            if value.sort == "belief":
                return oracle.Belief(*(hosts.from_card(part) for part in value.fields))
            if value.sort == "walk":
                return oracle.Walk(convert(value.fields[0]), value.fields[1])
            if value.sort == "dist":
                return oracle.Dist((convert(entry.fields[0]), Fraction(*entry.fields[1:])) for entry in value.fields)
        return value

    def from_oracle(value):
        if isinstance(value, oracle.Dist):
            return hosts.distribution((from_oracle(item), weight) for item, weight in value.weights.items())
        if isinstance(value, oracle.Die):
            return hosts.die(*value.weights)
        if isinstance(value, oracle.Event):
            return _wrap("Event", hosts.event(value.lo, value.hi))
        if isinstance(value, oracle.Belief):
            return _wrap("Belief", hosts.belief(hosts.to_card(value.fair), hosts.to_card(value.tilt)))
        if isinstance(value, oracle.Walk):
            return _wrap("Walk", hosts.walk(from_oracle(value.belief).fields[0], value.goal))
        if isinstance(value, Fraction):
            return hosts.to_card(value)
        if isinstance(value, tuple):
            return (hosts.pair(*(from_oracle(item) for item in value)) if name == "independent" else hosts.state(*value))
        return value

    def reference(*args):
        slots = tuple(arg.name for arg in args if isinstance(arg, kernel.FnRef))
        args = tuple(convert(arg) for arg in args if not isinstance(arg, kernel.FnRef))
        if name == "independent":
            operations = {"roll": oracle.roll, "pure": oracle.pure}
            return from_oracle(oracle.bind(operations[slots[0]](args[0]), lambda first:
                oracle.bind(operations[slots[1]](args[1]), lambda second: oracle.pure((first, second)))))
        if name == "step":
            return from_oracle(oracle.step(*args))
        if name == "score":
            return from_oracle(oracle.score(args[0], oracle.total if slots[0] == "total" else lambda pair: pair[0]))
        if name == "advance" and slots not in (("roll", "total", "jump"), ("roll_alias", "total", "jump"),
                                                ("roll", "total_alias", "jump"), ("roll", "total", "jump_alias")):
            raise ValueError("unverified advance slot family")
        return from_oracle(getattr(oracle, name)(*args))
    return reference


def build_library(limit=None):
    library = new_library()
    examples = example_args()
    events = tuple(_wrap("Event", hosts.event(lo, hi)) for lo in range(2, 13) for hi in range(lo, 13))
    priors = tuple(_wrap("Belief", hosts.belief(hosts.to_card(Fraction(index, 50)),
                                                 hosts.to_card(Fraction(50 - index, 50)))) for index in range(51))
    selected_priors = tuple(priors[index] for index in (0, 12, 25, 38, 50))
    endpoint_priors = (selected_priors[0], selected_priors[-1])
    walks = lambda beliefs, goals: tuple((_wrap("Walk", hosts.walk(belief.fields[0], goal)),)
                                        for belief, goal in product(beliefs, goals))
    joint = tuple(hosts.distribution((hosts.pair(left, right),
                   Fraction(first.fields[left - 1] * second.fields[right - 1], sum(first.fields) * sum(second.fields)))
                   for left, right in product(range(1, 7), repeat=2))
                  for first, second in product((hosts.FAIR, hosts.TILT), repeat=2))
    for definition in definitions()[:limit]:
        library.write(definition)
        if definition.kind == "object":
            adapter.check_generic(library, definition.name)
        elif definition.name == "conditional":
            library.check(definition.name)
        elif definition.kind == "observation":
            adapter.check_local(library, definition.name)
        elif any(isinstance(node, n.Lit) and isinstance(node.value, kernel.FnRef) for node in n.walk(definition.body)):
            adapter.check_refs(library, definition.name)
        else:
            adapter.check_generic(library, definition.name)
        args = examples[definition.name]
        if definition.kind == "observation":
            adapter.make_callable_local(library, definition.name, (args,))
        else:
            library.make_callable(definition.name, (args,))
        cases = (args,)
        if definition.name == "total":
            cases = tuple((hosts.pair(left, right),) for left, right in product(range(1, 7), repeat=2))
        elif definition.name == "Event":
            cases = tuple((event.fields[0],) for event in events)
        elif definition.name == "independent":
            cases = tuple((kernel.FnRef(first_slot), kernel.FnRef(second_slot), left, right)
                          for first_slot, second_slot, left, right in product(("roll", "pure"), ("roll", "pure"),
                                                                             (hosts.FAIR, hosts.TILT), (hosts.FAIR, hosts.TILT)))
        elif definition.name == "conditional":
            given_intervals = (events[0], _wrap("Event", hosts.event(7, 12)), events[-1])
            cases = tuple((dist, event, given) for dist, event, given in product((joint[0], joint[3]), events, given_intervals))
        elif definition.name == "score":
            cases = tuple((kernel.FnRef(slot), hosts.pure(hosts.pair(left, right)))
                          for slot, left, right in product(("total", "first_score"), range(1, 7), range(1, 7)))
            cases += tuple((kernel.FnRef(slot), distribution)
                           for slot, distribution in product(("total", "first_score"), joint))
        elif definition.name == "mean":
            cases = tuple((hosts.distribution(((value, Fraction(part, 5)),
                                               (value + 1, Fraction(5 - part, 5)))),)
                          for value, part in product(range(2, 12), range(1, 6)))
            cases += (args, (hosts.pure(13),), (hosts.pure(100),), (hosts.pure(-7),))
        elif definition.name == "Belief":
            cases = tuple((prior.fields[0],) for prior in priors)
        elif definition.name == "update":
            cases = tuple(product(priors, (events[0], events[-1]))) + (args,)
        elif definition.name == "Walk":
            cases = tuple((walk[0].fields[0],) for walk in walks(priors[::5], range(2, 7)))
        elif definition.name == "step":
            cases = tuple((walk[0], hosts.state(position, hidden)) for walk in walks(selected_priors[:2], range(2, 7))
                          for hidden in (0, 1) for position in range(walk[0].fields[0].fields[1] + 1))
        elif definition.name == "advance":
            cases = tuple((kernel.FnRef("roll"), kernel.FnRef("total"), kernel.FnRef("jump"), walk[0], turns)
                          for walk in walks(endpoint_priors, range(2, 7)) for turns in (0, 1)) + (args,)
            cases += tuple((kernel.FnRef(roll_slot), kernel.FnRef(total_slot), kernel.FnRef(jump_slot),
                            walks(selected_priors[:1], (2,))[0][0], 1)
                           for roll_slot, total_slot, jump_slot in (("roll_alias", "total", "jump"),
                                                                     ("roll", "total_alias", "jump"),
                                                                     ("roll", "total", "jump_alias")))
        elif definition.name == "hit_prob":
            cases = tuple((walk[0], turns) for walk in walks(endpoint_priors, range(2, 7)) for turns in (0, 1)) + (args,)
        elif definition.name == "hitting":
            cases = walks(selected_priors[:2], range(2, 7))
        method = "exhaustive" if definition.name in ("total", "Event") else "bounded"
        descriptions = {
            "independent": "bound: 2x2 operation slots roll/pure and 2x2 Fair/Tilt dice",
            "total": "all 36 ordered face pairs in 1..6",
            "Event": "all 66 event intervals 2 <= lo <= hi <= 12",
            "conditional": "bound: all 66 event intervals x evidence intervals [2,2], [7,12], [12,12] on Fair/Fair and Tilt/Tilt distributions",
            "score": "bound: total/first_score on all 36 point-pair distributions and four die-pair distributions",
            "mean": "bound: all 10 adjacent score pairs in 2..12 x 5 fifth-weight splits, tilted scores, and point masses at -7, 13, 100",
            "Belief": "bound: 51 rational priors index/50 for index 0..50",
            "update": "bound: 51 priors x the intervals [2,2] and [12,12], plus the half/half prior with [10,12]",
            "Walk": "bound: 11 prior-grid beliefs x goals 2..6",
            "step": "bound: two prior-grid beliefs x goals 2..6 x both hidden dice x all positions 0..goal",
            "advance": "bound: roll/total/jump slots on the prior-grid endpoints 0 and 1 x goals 2..6 x turns 0..1, plus posterior 6/25 at goal 6 for turn 3; one roll_alias, total_alias, jump_alias slot substitution each at prior 0, goal 2, turn 1",
            "hit_prob": "bound: prior-grid endpoints 0 and 1 x goals 2..6 x turns 0..1, plus posterior 6/25 at goal 6 for turn 8",
            "hitting": "bound: two prior-grid beliefs x goals 2..6 (exact rational elimination)",
        }
        description = descriptions[definition.name]
        if definition.name == "independent":
            params = definition.spec.params
            op_params = definition.spec.op_params
            op_indices = {param: params.index(param) for param in op_params}
            family = {param: list(dict.fromkeys(row[index].name for row in cases))
                      for param, index in op_indices.items()}
            value_indices = tuple(index for index, param in enumerate(params) if param not in op_params)
            cases = tuple(dict.fromkeys(tuple(row[index] for index in value_indices) for row in cases))
            oracle = _reference(definition.name)

            def reference(assignment, values, *, params=params, oracle=oracle):
                values = iter(values)
                return oracle(*(kernel.FnRef(assignment[param]) if param in assignment else next(values)
                                for param in params))

            request = VerifyRequest(method, cases, {"domain": description, "description": description,
                                                    "size": len(cases), "op_family": family},
                                    reference=reference, extra={"op_family": family})
        else:
            request = VerifyRequest(method, cases, {"domain": description, "description": description, "size": len(cases)},
                                    reference=_reference(definition.name))
        if definition.kind in ("operation", "object") or definition.name == "independent":
            library.verify(definition.name, request)
        else:
            adapter.verify_general(library, definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract("Exact on the stated bounded reference domain."))
    return library
