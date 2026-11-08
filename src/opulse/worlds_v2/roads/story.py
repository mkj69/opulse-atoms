"""Twelve depth cards: every graph algorithm unfolds through counted kernel nodes."""

from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.check import all_dependencies
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
from opulse.atoms.values import boolean

from . import depth_hosts as hosts
from . import reference
from .world import new_library

TINY = hosts.to_card((("A", "B", "C", "D"), (("A", "B", 2), ("A", "C", 4),
                                             ("B", "D", 3), ("C", "D", 2))))


def v(name):
    return n.Var(name)


def c(name, *args):
    return n.Call(name, args)


def t(name, *args):
    return n.Test(c(name, *args))


EMPTY = n.Lit(hosts.items())


def let(bindings, body):
    for name, value in reversed(bindings):
        body = n.Let(name, value, body)
    return body


def choose(condition, yes, no):
    return n.Case(((condition, yes),), no)


def rec(name, params, body, args, measure):
    return n.Rec(name, params, body, args, measure)


def define(name, kind, spec, body, layers, extra=()):
    dependencies = tuple(sorted((all_dependencies(Definition(name, kind, "invented", 1, (), spec, body))
                                 - set(getattr(spec, "op_params", ()))) | set(extra))) if body else tuple(extra)
    layer = max((layers.get(item, layers.get(item.split(".")[0], 0)) for item in dependencies), default=0) + 1
    return Definition(name, kind, "invented", layer, dependencies, spec, body)


def op(name, inputs, output, body, layers):
    spec = OperationSpec(name, "transform", tuple(Edge(sort, name=param) for param, sort in inputs),
                         Edge(output), f"Derive {name} from public roads and earlier cards.",
                         extra={"input_names": [param for param, _ in inputs]})
    return define(name, "operation", spec, body, layers)


def comb(name, params, slots, body, layers):
    return define(name, "combinator", CombinatorSpec(name, params, slots, body), body, layers)


def obs(name, reads, body, layers):
    return define(name, "observation", ObservationSpec(name, reads, body), body, layers)


def definitions():
    result, layers = [], {}

    def add(definition):
        result.append(definition)
        layers[definition.name] = definition.layer

    raw = v("x")
    graph = c("RouteRaw.graph", raw)
    vertices = c("RouteRaw.vertices", raw)
    step = rec("route_steps", ("rest", "previous"),
               choose(t("empty", v("rest")), n.Lit(boolean(True)),
                      let((("next", c("head", v("rest"))),),
                          choose(t("defined", c("edge", graph, v("previous"), v("next"))),
                                 c("route_steps", c("tail", v("rest")), v("next")),
                                 n.Lit(boolean(False))))),
               (c("tail", vertices), c("head", vertices)), c("size", v("rest")))
    valid_route = choose(n.And(n.And(n.Not(t("empty", vertices)), t("distinct", vertices)),
                               t("subset", vertices, c("graph_nodes", graph))),
                         step, n.Lit(boolean(False)))
    route = ObjectSpec("Route", "refine", base="RouteRaw", valid=valid_route,
                       sealed=True, interface=("Route.make", "Route.graph", "Route.vertices"),
                       extra={"fields": ("graph", "vertices")})
    add(define("Route", "object", route, None, layers, tuple(sorted(n.references(valid_route)))))

    r = v("r")
    cost_step = let((("next", c("head", v("rest"))),),
                    c("sum_cost", c("tail", v("rest")), v("next"),
                      c("add", v("total"), c("edge", c("Route.graph", r), v("previous"), v("next")))))
    cost_body = let((("vertices", c("Route.vertices", r)),),
                    rec("sum_cost", ("rest", "previous", "total"),
                        choose(t("empty", v("rest")), v("total"), cost_step),
                        (c("tail", v("vertices")), c("head", v("vertices")), n.Lit(0)),
                        c("size", v("rest"))))
    add(op("cost", (("r", "Route"),), "Int", cost_body, layers))

    add(op("reverse_edge", (("g", "Roads"), ("u", "Text"), ("w", "Text")), "int",
           c("edge", v("g"), v("w"), v("u")), layers))

    g, s, target = v("g"), v("s"), v("target")
    path, candidates, found = v("path"), v("candidates"), v("found")
    expand_body = let((("candidate", c("head", candidates)),),
                      choose(n.Or(t("contains", v("candidate"), path),
                                  n.Not(t("defined", c("e", g, c("head", path), v("candidate"))))),
                             c("scan_neighbors", c("tail", candidates), found),
                             c("scan_neighbors", c("tail", candidates),
                               c("cons", c("cons", v("candidate"), path), found))))
    expand = rec("scan_neighbors", ("candidates", "found"),
                 choose(t("empty", candidates), found, expand_body),
                 (c("graph_nodes", g), EMPTY), c("size", candidates))
    dfs_body = let((("path", c("head", v("todo"))),),
                   choose(t("eq", c("head", path), target),
                          c("walk_paths", c("tail", v("todo")),
                            c("cons", c("Route.make", c("route_raw", g, c("reverse", path))), v("routes"))),
                          c("walk_paths", c("append", c("reverse", expand), c("tail", v("todo"))), v("routes"))))
    explore_body = choose(t("contains", s, c("graph_nodes", g)),
                          choose(t("contains", target, c("graph_nodes", g)),
                                 rec("walk_paths", ("todo", "routes"),
                                     choose(t("empty", v("todo")), c("reverse", v("routes")), dfs_body),
                                     (c("cons", c("cons", s, EMPTY), EMPTY), EMPTY), "fuel"), EMPTY), EMPTY)
    add(comb("explore", ("e", "g", "s", "target"), ("e",), explore_body, layers))

    state = v("state")
    state_cost = c("head", state)
    state_path = c("head", c("tail", state))
    scan_body = let((("candidate", c("head", v("candidates"))),),
                    choose(n.Or(t("contains", v("candidate"), v("path")),
                                n.Not(t("defined", c("edge", v("active"), c("head", c("reverse", v("path"))),
                                                          v("candidate"))))),
                           c("scan_frontier", c("tail", v("candidates")), v("frontier")),
                           c("scan_frontier", c("tail", v("candidates")),
                             c("cons", c("cons", c("add", v("price"),
                               c("edge", v("active"), c("head", c("reverse", v("path"))), v("candidate"))),
                               c("cons", c("append", v("path"), c("cons", v("candidate"), EMPTY)), EMPTY)),
                               v("frontier")))))
    scan = rec("scan_frontier", ("candidates", "frontier"),
               choose(t("empty", v("candidates")), v("frontier"), scan_body),
               (c("graph_nodes", v("active")), c("tail", v("pending"))), c("size", v("candidates")))
    current_node = c("head", c("reverse", v("path")))
    search_body = let((("state", c("head", v("pending"))),
                       ("price", state_cost), ("path", state_path)),
                      choose(t("contains", current_node, v("settled")),
                             c("search_frontier", c("tail", v("pending")), v("settled")),
                             choose(t("eq", current_node, target),
                                    let((("route", c("Route.make", c("route_raw", g, v("path")))),
                                         ("checked", c("cost", v("route")))), v("route")),
                                    c("search_frontier", c("sort_frontier", scan),
                                      c("cons", current_node, v("settled"))))))
    best_body = choose(n.And(t("contains", s, c("graph_nodes", v("active"))),
                             t("contains", target, c("graph_nodes", v("active")))),
                       rec("search_frontier", ("pending", "settled"),
                           choose(t("empty", v("pending")), c("no_route"), search_body),
                           (c("cons", c("cons", n.Lit(0),
                             c("cons", c("cons", s, EMPTY), EMPTY)), EMPTY), EMPTY), "fuel"), c("no_route"))
    add(op("best", (("g", "Roads"), ("s", "Text"), ("target", "Text")), "Route",
           let((("active", c("map_view", g)),), best_body), layers))

    route = v("r")
    optimal_body = let((("visible", c("map_view", c("Route.graph", route))),),
                       c("eq", c("cost", route),
                         c("cost", c("best", v("visible"), c("head", c("Route.vertices", route)),
                           c("head", c("reverse", c("Route.vertices", route)))))))
    add(obs("optimal", ("map_view",), optimal_body, layers))

    road_ids_body = rec("collect_ids", ("remaining", "acc"),
                        choose(t("empty", v("remaining")), c("reverse", v("acc")),
                               c("collect_ids", c("tail", v("remaining")),
                                 c("cons", c("edge_id", c("head", v("remaining"))), v("acc")))),
                        (v("roads"), EMPTY), c("size", v("remaining")))
    add(op("road_ids", (("roads", "List"),), "List", road_ids_body, layers))
    closed_raw = v("x")
    closed_ids = c("Edges.edge_ids", c("ClosureRaw.closed_edges", closed_raw))
    closure_canon = c("closure_raw", c("ClosureRaw.base", closed_raw),
                      c("edge_set", c("sort_texts", closed_ids)))
    closed = ObjectSpec("Closure", "refine", base="ClosureRaw",
                        valid=c("subset", closed_ids,
                                c("road_ids", c("graph_edges", c("ClosureRaw.base", closed_raw)))),
                        canon=closure_canon,
                        sealed=True, interface=("Closure.make", "Closure.base", "Closure.closed_edges"),
                        extra={"fields": ("closed_edges",)})
    add(define("Closure", "object", closed, None, layers,
               tuple(sorted(n.references(closed.valid) | n.references(closed.canon)))))

    add(op("close", (("g", "Roads"), ("blocked", "Edges")), "Closure",
           c("Closure.make", c("closure_raw", g, v("blocked"))), layers))
    add(op("close_same", (("g", "Roads"), ("blocked", "Edges")), "Closure",
           c("close", g, v("blocked")), layers))

    edges = v("edges")
    subset_body = let((("identifier", c("edge_id", c("head", edges))),
                       ("rest", c("tail", edges))),
                      c("append", c("generate_subsets", v("rest"), v("selected")),
                        choose(t("lt", c("size", v("selected")), v("b")),
                               c("generate_subsets", v("rest"), c("cons", v("identifier"), v("selected"))), EMPTY)))
    subsets_body = rec("generate_subsets", ("edges", "selected"),
                       choose(t("empty", edges), c("cons", c("edge_set", c("reverse", v("selected"))), EMPTY),
                              subset_body), (c("graph_edges", g), EMPTY), c("size", edges))
    failure_loop = let((("sets", c("sort_edge_sets", subsets_body)),),
                        rec("apply_closures", ("remaining", "closures"),
                            choose(t("empty", v("remaining")), c("reverse", v("closures")),
                                   c("apply_closures", c("tail", v("remaining")),
                                     c("cons", c("f", g, c("head", v("remaining"))), v("closures")))),
                            (v("sets"), EMPTY), c("size", v("remaining"))))
    failures_body = choose(n.And(n.Not(t("lt", v("b"), n.Lit(0))),
                                 n.Not(t("lt", c("size", c("graph_edges", g)), v("b")))),
                           failure_loop, c("invalid_budget"))
    add(comb("failures", ("f", "g", "b"), ("f",), failures_body, layers))

    seen = v("seen")
    road_fields = c("road_fields", v("road"))
    left = c("head", road_fields)
    right = c("head", c("tail", road_fields))
    step_body = let((("road", c("head", v("remaining"))),),
                    c("extend_reach", c("tail", v("remaining")),
                      choose(t("contains", left, seen), c("cons", right, seen),
                             choose(t("contains", right, seen), c("cons", left, seen), seen))))
    reach_step_body = let((("road_graph", c("reach_graph", v("state"))),
                           ("seen", c("reach_seen", v("state")))),
                          c("reach_state", v("road_graph"),
                            c("sort_texts", rec("extend_reach", ("remaining", "seen"),
                                choose(t("empty", v("remaining")), seen, step_body),
                                (c("graph_edges", v("road_graph")), seen),
                                c("size", v("remaining"))))))
    add(op("reach_step", (("state", "Reach"),), "Reach", reach_step_body, layers))
    reachable_body = choose(n.And(t("contains", s, c("graph_nodes", g)),
                                  t("contains", target, c("graph_nodes", g))),
                            c("contains", target, c("reach_seen", c("fix",
                              n.Lit(kernel.FnRef("reach_step")),
                              c("reach_state", g, c("cons", s, EMPTY)), c("size", c("graph_nodes", g))))),
                            n.Lit(boolean(False)))
    add(op("reachable", (("g", "Roads"), ("s", "Text"), ("target", "Text")), "bool",
           let((("g", c("map_view", g)),), reachable_body), layers))

    damaged = v("damaged")
    add(obs("survives", ("map_view", "size"),
            let((("public", c("map_view", g)),),
                rec("survival", ("remaining",),
                    choose(t("empty", v("remaining")), n.Lit(boolean(True)),
                           let((("damaged", c("head", v("remaining"))),),
                               choose(n.Not(t("reachable", damaged, s, target)),
                                      n.Lit(boolean(False)), c("survival", c("tail", v("remaining")))))),
                    (c("failures", n.Lit(kernel.FnRef("close")), v("public"), v("b")),),
                    c("size", v("remaining")))), layers))

    worst_candidate = let((("damaged", c("head", v("remaining"))),
                           ("attempt", c("capture", c("best", v("damaged"), s, target)))),
                          choose(t("is_value", v("attempt")),
                                 let((("route", c("unlift", v("attempt"))),
                                      ("price", c("cost", v("route"))),
                                       ("blocked", c("Closure.closed_edges", v("damaged")))),
                                     choose(n.Or(t("lt", v("maximum"), v("price")),
                                                 n.And(t("eq", v("maximum"), v("price")),
                                                       t("pair_before", c("Edges.edge_ids", c("Closure.closed_edges", v("damaged"))),
                                                         c("Edges.edge_ids", v("winner_set"))))),
                                            c("select_worst", c("tail", v("remaining")), v("price"),
                                              v("blocked"), v("route")),
                                            c("select_worst", c("tail", v("remaining")), v("maximum"),
                                              v("winner_set"), v("winner_route")))), c("disconnected")))
    worst_body = rec("select_worst", ("remaining", "maximum", "winner_set", "winner_route"),
                     choose(t("empty", v("remaining")), c("worst_record", v("maximum"), v("winner_set"), v("winner_route")),
                            worst_candidate),
                     (c("failures", n.Lit(kernel.FnRef("close")), g, v("b")), n.Lit(-1),
                      c("edge_set", EMPTY), n.Lit(0)),
                     c("size", v("remaining")))
    add(op("worst", (("g", "Roads"), ("s", "Text"), ("target", "Text"), ("b", "Int")),
           "Worst", worst_body, layers))

    boundary_body = rec("cut_edges", ("remaining", "crossing"),
                        choose(t("empty", v("remaining")), c("edge_set", c("reverse", v("crossing"))),
                               let((("road", c("head", v("remaining"))),
                                    ("start", c("head", c("road_fields", v("road")))),
                                    ("end", c("head", c("tail", c("road_fields", v("road")))))),
                                   c("cut_edges", c("tail", v("remaining")),
                                     choose(t("eq", c("contains", v("start"), v("side")),
                                               c("contains", v("end"), v("side"))),
                                            v("crossing"), c("cons", c("edge_id", v("road")), v("crossing")))))),
                        (c("graph_edges", g), EMPTY), c("size", v("remaining")))
    add(op("boundary", (("g", "Roads"), ("side", "List")), "Edges", boundary_body, layers))
    partition_body = let((("current", c("head", v("unseen"))),
                          ("rest", c("tail", v("unseen")))),
                         choose(t("eq", v("current"), target),
                                c("partition", v("rest"), v("side")),
                                choose(t("eq", v("current"), s),
                                       c("partition", v("rest"), c("cons", s, v("side"))),
                                       c("append", c("partition", v("rest"), v("side")),
                                         c("partition", v("rest"), c("cons", v("current"), v("side")))))))
    partitions = rec("partition", ("unseen", "side"),
                     choose(t("empty", v("unseen")), c("cons", c("reverse", v("side")), EMPTY),
                            partition_body), (c("graph_nodes", g), EMPTY), c("size", v("unseen")))
    cut_body = let((("vertices", c("graph_nodes", g)),),
               choose(n.And(n.And(t("contains", s, v("vertices")),
                                  t("contains", target, v("vertices"))),
                            n.Not(t("eq", s, target))),
                      let((("partitions", partitions),),
                          rec("pick_cut", ("remaining", "winner"),
                              choose(t("empty", v("remaining")), v("winner"),
                                     let((("side", c("head", v("remaining"))),
                                          ("candidate", c("boundary", g, v("side")))),
                                         c("pick_cut", c("tail", v("remaining")),
                                           choose(n.Or(t("lt", c("size", c("Edges.edge_ids", v("candidate"))),
                                                        c("size", c("Edges.edge_ids", v("winner")))),
                                                       n.And(t("eq", c("size", c("Edges.edge_ids", v("candidate"))),
                                                                 c("size", c("Edges.edge_ids", v("winner")))),
                                                             t("pair_before", c("Edges.edge_ids", v("candidate")),
                                                               c("Edges.edge_ids", v("winner"))))),
                                                  v("candidate"), v("winner"))))),
                              (v("partitions"), c("edge_set", c("road_ids", c("graph_edges", g)))),
                              c("size", v("remaining")))), c("invalid_terminals")))
    add(op("mincut", (("g", "Roads"), ("s", "Text"), ("target", "Text")), "Edges", cut_body, layers))

    certificate = let((("public", c("map_view", g)),
                       ("cut", c("mincut", v("public"), s, target))),
                      choose(t("survives", v("public"), s, target,
                               c("sub", c("size", c("Edges.edge_ids", v("cut"))), n.Lit(1))),
                             n.Case(((n.Not(t("reachable", c("close", v("public"), v("cut")), s, target)),
                                      n.Lit(boolean(True))),), n.Lit(boolean(False))), n.Lit(boolean(False))))
    add(obs("cut_certificate", ("map_view", "size"), certificate, layers))
    return tuple(result)


def build_library():
    lib = new_library()
    graphs = tuple(hosts.to_card((("A", "B", "C", "D"),
                   (("A", "B", weights[0]), ("A", "C", weights[1]),
                    ("B", "D", weights[2]), ("C", "D", weights[3]))))
                   for weights in product((1, 2, 3, 4), repeat=4))
    closures = tuple(hosts.closure_raw(graph, hosts.edge_set(hosts.items("AB", "AC")))
                     for graph in graphs)

    def evidence(name):
        if name == "Route":
            domain = tuple((hosts.route_raw(graph, hosts.items("A", "B", "D")),) for graph in graphs)
        elif name == "Closure":
            domain = tuple((raw,) for raw in closures)
        elif name in ("cost", "optimal"):
            domain = tuple((lib.run("Route.make", (hosts.route_raw(graph, hosts.items("A", "B", "D")),)).outcome.value,)
                           for graph in graphs)
        elif name in ("reverse_edge",):
            domain = tuple((graph, "A", "B") for graph in graphs)
        elif name in ("road_ids",):
            domain = tuple((hosts.graph_edges(graph),) for graph in graphs)
        elif name == "boundary":
            domain = tuple((graph, hosts.items("A", "B")) for graph in graphs)
        elif name == "close" or name == "close_same":
            domain = tuple((graph, hosts.edge_set(hosts.items("AB"))) for graph in graphs)
        elif name == "explore":
            domain = tuple((graph, "A", "D") for graph in graphs)
        elif name == "failures":
            domain = tuple((graph, 1) for graph in graphs)
        elif name == "reach_step":
            domain = tuple((hosts.reach_state(graph, hosts.items("A")),) for graph in graphs)
        elif name == "reachable":
            domain = tuple((graph, "A", "D") for graph in graphs)
        elif name == "survives" or name == "worst":
            domain = tuple((graph, "A", "D", 1) for graph in graphs)
        elif name == "cut_certificate":
            domain = tuple((graph, "A", "D") for graph in graphs)
        else:
            domain = tuple((graph, "A", "D") for graph in graphs)
        signatures = {
            "Route": "RouteRaw(graph, List<Text> route)",
            "Closure": "ClosureRaw(graph, Edges<AB,AC>)",
            "cost": "minted Route(graph, List<Text> route)",
            "optimal": "minted Route(graph, List<Text> route)",
            "road_ids": "List<Edge> from the graph",
            "reach_step": "Reach(graph, List<Text> containing A)",
            "boundary": "graph and List<Text> side A,B",
            "close": "graph and Edges<AB>",
            "close_same": "graph and Edges<AB>",
            "reverse_edge": "graph, A, B",
            "explore": "graph, A, D with slot e",
            "failures": "graph, budget 1 with slot f",
            "reachable": "graph, A, D",
            "best": "graph, A, D",
            "survives": "graph, A, D, budget 1",
            "worst": "graph, A, D, budget 1",
            "mincut": "graph, A, D",
            "cut_certificate": "graph, A, D",
        }
        count = len(graphs)
        graph_family = (f"all {count} weightings (each road weight 1..4) of the fixed connected 4-node, 4-road"
                        " graph A-B, A-C, B-D, C-D")
        scope = {"domain": f"{graph_family}; {count} {signatures[name]} inputs",
                 "size": len(domain), "description": (f"Exactly {count} bounded {signatures[name]} inputs from {graph_family}, each checked against"
                                 " the independent reference; complete for this topology and weight bound, no other graphs claimed.")}
        if name in ("optimal", "survives", "cut_certificate"):
            scope["description"] = (f"{count} bounded {signatures[name]} inputs from {graph_family},"
                                    f" {count} oracle comparisons and {count} identical-public-map non-interference reruns.")
        if name == "explore":
            scope["description"] = (f"{2 * count} complete search evaluations: {graph_family}, times two undirected edge"
                                    " operations.")
            scope["op_family"] = {"e": ["edge", "reverse_edge"]}
            return VerifyRequest("bounded", domain, scope,
                                 reference=lambda slots, args: reference.expected(
                                     "explore", kernel.FnRef(slots["e"]), *args),
                                 extra={"op_family": {"e": ("edge", "reverse_edge")}})
        if name == "failures":
            scope["description"] = (f"{2 * count} complete failure enumerations: {graph_family}, times two closure operations,"
                                    " budget one.")
            scope["op_family"] = {"f": ["close", "close_same"]}
            return VerifyRequest("bounded", domain, scope,
                                 reference=lambda slots, args: reference.expected(
                                     "failures", kernel.FnRef(slots["f"]), *args),
                                 extra={"op_family": {"f": ("close", "close_same")}})

        def oracle(*args):
            if name == "reverse_edge":
                return reference.design().edge(reference.graph(args[0]), args[2], args[1])
            if name == "close_same":
                return reference.expected("close", *args)
            if name == "road_ids":
                return hosts.items(*(road.fields[0] + road.fields[1] for road in args[0].fields))
            if name == "boundary":
                graph, side = args
                selected = set(side.fields)
                return hosts.edge_set(hosts.items(*(start + end for start, end, _ in reference.graph(graph).edges
                       if (start in selected) != (end in selected))))
            if name == "reach_step":
                graph, seen = args[0].fields
                reached = set(seen.fields)
                for start, end, _ in reference.graph(graph).edges:
                    if start in reached:
                        reached.add(end)
                    elif end in reached:
                        reached.add(start)
                return hosts.reach_state(graph, hosts.items(*sorted(reached)))
            if name == "reachable":
                return boolean(reference.design().explore_first(reference.graph(args[0]), args[1], args[2]))
            return reference.expected(name, *args)

        return VerifyRequest("bounded", domain, scope, reference=oracle,
                             extra={"interface_ops": {}} if name in ("Route", "Closure") else {})

    for definition in definitions():
        lib.write(definition)
        lib.check(definition.name)
        lib.make_callable(definition.name, [(TINY, "A", "D", 0)] if definition.name == "survives" else
                          [(TINY, "A", "D")] if definition.name == "cut_certificate" else
                          [(hosts.route_raw(TINY, hosts.items("A", "B", "D")),)]
                          if definition.name == "Route" else
                          [(hosts.closure_raw(TINY, hosts.edge_set(hosts.items())),)]
                          if definition.name == "Closure" else
                          [(kernel.FnRef("edge"), TINY, "A", "D")]
                          if definition.name == "explore" else
                          [(kernel.FnRef("close"), TINY, 0)]
                          if definition.name == "failures" else
                          [(TINY, "A", "D", 0)]
                          if definition.name in ("worst",) else
                          [(TINY, "A", "D")]
                          if definition.name in ("best", "mincut") else
                          [(hosts.reach_state(TINY, hosts.items("A")),)]
                          if definition.name == "reach_step" else
                          [(hosts.graph_edges(TINY),)]
                          if definition.name == "road_ids" else
                          [(TINY, hosts.items("A"))]
                          if definition.name == "boundary" else
                          [(TINY, "A", "D")]
                          if definition.name == "reachable" else
                          [(TINY, "A", "B")]
                          if definition.name == "reverse_edge" else
                          [(TINY, hosts.edge_set(hosts.items()))]
                          if definition.name == "close_same" else
                          [(TINY, hosts.edge_set(hosts.items()))]
                          if definition.name == "close" else
                          [(lib.run("Route.make", (hosts.route_raw(TINY, hosts.items("A", "B", "D")),)).outcome.value,)])
        lib.verify(definition.name, evidence(definition.name))
        lib.account(definition.name)
        lib.promote(definition.name, Contract(f"Bounded public-graph semantics for {definition.name}."))
    return lib
