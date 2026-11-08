"""Eight invented control structures, all unfolded through the core kernel."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import CombinatorSpec, Contract, Definition

from . import hosts
from .reference import independent_oracle
from .world import new_library


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def call(name, *args):
    return n.Call(name, args)


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def bind(name, expression, body):
    return n.Let(name, expression, body)


def recursive(name, params, body, args, measure):
    return n.Rec(name, params, body, args, measure)


def fixed(name):
    return lit(kernel.FnRef(name))


def definitions():
    mapped = recursive("walk", ("remaining", "output"),
                       choose(call("empty", var("remaining")), var("output"),
                              call("walk", call("tail", var("remaining")),
                                   call("append", var("output"), call("f", var("p"), call("head", var("remaining")))))),
                       (var("xs"), lit(())), call("length", var("remaining")))
    folded = recursive("walk", ("remaining", "output"),
                       choose(call("empty", var("remaining")), var("output"),
                              call("walk", call("tail", var("remaining")),
                                   call("f", var("output"), call("head", var("remaining"))))),
                       (var("xs"), var("zero")), call("length", var("remaining")))
    until = recursive("loop", ("current",), bind("next", call("step", var("current")),
                      choose(call("eq", var("next"), var("current")), var("current"),
                             choose(call("lt", call("measure", var("next")),
                                         call("measure", var("current"))),
                                    call("loop", var("next")), call("non_decreasing")))),
                      (var("initial"),), call("measure", var("current")))
    def close_in(plan, seeds, universe, neighbors, prefix):
        spread = prefix + "_spread"
        visit = prefix + "_visit"
        return choose(call("eq", call("difference", seeds, universe), lit(0)),
                      recursive(spread, ("seen",),
                                bind("next", recursive(visit, ("rest", "found"),
                                      choose(call("empty", var("rest")), var("found"),
                                             call(visit, call("tail", var("rest")),
                                                  call("union", var("found"),
                                                       call(neighbors, plan, call("head", var("rest")))))),
                                      (call("ascending", var("seen")), var("seen")), call("length", var("rest"))),
                                     bind("inside", call("intersect", var("next"), universe),
                                          choose(call("eq", var("seen"), var("inside")), var("seen"),
                                                 call(spread, var("inside"))))),
                                (seeds,), call("popcount", call("difference", universe, var("seen")))),
                      call("outside_universe"))

    closure = bind("universe", call("all_vertices", var("p")),
                   close_in(var("p"), var("seeds"), var("universe"), "neighbors", "public"))
    divide = recursive("split", ("items",),
                       choose(call("empty", var("items")), var("zero"),
                              choose(call("singleton_list", var("items")), call("leaf", call("head", var("items"))),
                                     bind("halves", call("split_mid", var("items")),
                                          call("merge", call("split", call("first", var("halves"))),
                                               call("split", call("second", var("halves"))))))),
                       (var("xs"),), call("length", var("items")))
    components = recursive("collect", ("remaining", "groups"),
                           choose(call("eq", var("remaining"), lit(0)), var("groups"),
                                  bind("group", call("closure", var("neighbors"), var("p"),
                                                     call("singleton", call("lowest", var("remaining")))),
                                       call("collect", call("difference", var("remaining"), var("group")),
                                            call("append", var("groups"), var("group"))))),
                           (call("all_vertices", var("p")), lit(())), call("popcount", var("remaining")))
    branch = choose(call("eq", call("available", var("s")), lit(0)), call("empty_frontier"),
                    bind("picked", recursive("pick", ("rest", "best"),
                           choose(call("empty", var("rest")), var("best"),
                                  bind("candidate", call("head", var("rest")),
                                       call("pick", call("tail", var("rest")),
                                            choose(call("lt", call("rank", call("plan", var("s")),
                                                                    call("available", var("s")), var("best")),
                                                        call("rank", call("plan", var("s")),
                                                             call("available", var("s")), var("candidate"))),
                                                   var("candidate"), var("best"))))),
                           (call("tail", call("ascending", call("available", var("s")))),
                            call("head", call("ascending", call("available", var("s"))))),
                           call("length", var("rest"))),
                         call("pair", call("take", var("s"), var("picked")),
                              call("ban", var("s"), var("picked")))))

    def better(left, right):
        return choose(call("lt", call("score", left), call("score", right)), right,
                      choose(call("eq", call("score", left), call("score", right)),
                             choose(call("lt", call("chosen", right), call("chosen", left)), right, left), left))

    def upper(state):
        return call("add", call("score", state),
                    call("fold", fixed("add"), lit(0),
                         call("map", fixed("weight"), call("plan", state),
                              call("ascending", call("available", state)))))

    def consider(candidate, best):
        return choose(call("lt", upper(candidate), call("score", best)), best,
                      better(best, call("solve", candidate)))

    available = call("available", var("current"))
    current_plan = call("plan", var("current"))
    induced = recursive("collect_induced", ("remaining", "groups"),
                        choose(call("eq", var("remaining"), lit(0)), var("groups"),
                               bind("group", close_in(current_plan,
                                    call("singleton", call("lowest", var("remaining"))),
                                    available, "adjacent", "induced"),
                                    call("collect_induced", call("difference", var("remaining"), var("group")),
                                         call("append", var("groups"), var("group"))))),
                        (available, lit(())), call("popcount", var("remaining")))
    opt = recursive("solve", ("current",),
                    choose(call("eq", available, lit(0)), var("current"),
                           bind("groups", choose(call("eq", available, call("all_vertices", current_plan)),
                                                 call("components", fixed("adjacent"), current_plan), induced),
                                choose(call("singleton_list", var("groups")),
                                       bind("branches", call("branch", var("rank"), var("current")),
                                            bind("best", consider(call("first", var("branches")),
                                                                  call("done", var("current"))),
                                                 consider(call("second", var("branches")), var("best")))),
                                       recursive("join", ("rest", "result"),
                                                 choose(call("empty", var("rest")), var("result"),
                                                        call("join", call("tail", var("rest")),
                                                             call("join_state", var("result"),
                                                                  call("solve", call("state_group", var("current"),
                                                                                     call("head", var("rest"))))))),
                                                 (var("groups"), call("done", var("current"))),
                                                 call("length", var("rest")))))),
                    (var("s"),), call("popcount", call("available", var("current"))))
    bodies = (mapped, folded, until, closure, divide, components, branch, opt)
    names = ("map", "fold", "until", "closure", "divide", "components", "branch", "opt")
    params = (("f", "p", "xs"), ("f", "zero", "xs"), ("step", "measure", "initial"),
              ("neighbors", "p", "seeds"), ("leaf", "merge", "xs", "zero"),
              ("neighbors", "p"), ("rank", "s"), ("rank", "s"))
    operation_params = (("f",), ("f",), ("step", "measure"), ("neighbors",),
                        ("leaf", "merge"), ("neighbors",), ("rank",), ("rank",))
    return tuple(Definition(name, "combinator", "invented", index,
                            tuple(sorted(n.references(body) - set(ops) | n.operation_literals(body))),
                            CombinatorSpec(name, arguments, ops, body), body)
                 for index, (name, arguments, ops, body) in enumerate(
                     zip(names, params, operation_params, bodies, strict=True), 1))


def build_library():
    library = new_library()
    small = hosts.Plan(23, 1, 3)
    medium = hosts.Plan(23, 2, 4)
    samples = ((kernel.FnRef("weight"), small, (0, 1, 2)),
               (kernel.FnRef("add"), 0, (4, 7, 9)),
               (kernel.FnRef("drop_lowest"), kernel.FnRef("popcount"), 15),
               (kernel.FnRef("adjacent"), small, 1),
               (kernel.FnRef("identity"), kernel.FnRef("add"), (1, 2, 3), 0),
               (kernel.FnRef("adjacent"), medium),
               (kernel.FnRef("priority"), hosts.start(small)),
               (kernel.FnRef("priority"), hosts.start(small)))
    families = (("weight",), ("add",), ("drop_lowest", "popcount"), ("adjacent",),
                ("identity", "add"), ("adjacent",), ("priority",), ("priority",))
    domains = (((small, (0, 1, 2)), (small, (1,)), (small, ())),
               ((0, (4, 7, 9)), (5, ()), (2, (3,))),
               ((15,), (1,), (0,)),
               ((small, 1), (small, 2), (small, 0)),
               (((1, 2, 3), 0), ((), 9), ((8,), 0)),
               ((medium,), (small,), (hosts.Plan(23, 2, 3),)),
               ((hosts.start(small),), (hosts.start(medium),),
                (hosts.start(hosts.Plan(23, 1, 4)),)),
               ((hosts.start(small),), (hosts.start(medium),),
                (hosts.start(hosts.Plan(23, 2, 3, bridges=((0, 3),))),)))

    def expected(name, inputs):
        if name == "map":
            plan, items = inputs
            return tuple(hosts.weight(plan, vertex) for vertex in items)
        if name == "fold":
            initial, items = inputs
            return initial + sum(items)
        if name == "until":
            return 0
        if name == "closure":
            plan, seeds = inputs
            universe = hosts.all_vertices(plan)
            reached = seeds
            while True:
                expanded = reached
                for vertex in hosts.vertices(reached):
                    expanded |= hosts.adjacent(plan, vertex) & universe
                if expanded == reached:
                    return reached
                reached = expanded
        if name == "divide":
            items, initial = inputs
            return initial if not items else sum(items)
        if name == "components":
            (plan,) = inputs
            universe = hosts.all_vertices(plan)
            remaining = universe
            groups = []
            while remaining:
                group = expected("closure", (plan, 1 << hosts.lowest(remaining)))
                groups.append(group)
                remaining &= ~group
            return tuple(groups)
        if name == "branch":
            (state,) = inputs
            vertex = max(hosts.vertices(state.available),
                         key=lambda item: hosts.priority(state.plan, state.available, item))
            return hosts.take(state, vertex), hosts.ban(state, vertex)
        (state,) = inputs
        score, selected = independent_oracle(state.plan)
        return hosts.State(state.plan, 0, sum(1 << vertex for vertex in selected), score)

    for definition, sample, family, domain in zip(definitions(), samples, families, domains, strict=True):
        library.write(definition)
        library.check(definition.name)
        library.make_callable(definition.name, (sample,))
        operation_family = ({param: [name] for param, name in zip(definition.spec.op_params, family, strict=True)}
                            if family else ["adjacent"])
        scope = {"size": len(domain), "domain": "three finite public cases", "op_family": operation_family}
        library.verify(definition.name, VerifyRequest("bounded", domain, scope,
                                                       reference=lambda assignment, inputs, name=definition.name:
                                                       expected(name, inputs),
                                                       extra={"op_family": operation_family}))
        library.account(definition.name)
        library.promote(definition.name, Contract("Finite, unfolded public operations and exact kernel costs."))
    return library
