"""Ten derived public observations promoted through the core pipeline."""

from fractions import Fraction

from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Contract, Definition, ObservationSpec

from . import reference as ref
from .world import new_library


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def test(expression):
    return n.Test(expression)


def branch(condition, yes, no):
    return n.Case(((test(condition), yes),), no)


def loop(name, end, initial, update):
    index, result = var(name + "_i"), var(name + "_result")
    return n.Rec(name, (name + "_i", name + "_result"),
                 branch(call("eq", index, end), result,
                        call(name, call("inc", index), update(index, result))),
                 (lit(0), initial), call("sub", end, index))


def normalize(expression):
    return n.Let("raw", expression,
                 n.Let("total", call("sum", var("raw")),
                       branch(call("eq", var("total"), lit(0)),
                              call("fail", lit("impossible_public_trace")),
                              loop("normalize_cells", lit(64), lit(()),
                                   lambda index, values: call("append", values,
                                                               call("div", call("at", var("raw"), index),
                                                                    var("total")))))))


def vector(trace, tick, config, normalize_frames=True):
    cells = lit(64)
    initial = loop("initial", cells, lit(()),
                   lambda index, values: call("append", values,
                                              call("mul", call("prior_mass", config, index),
                                                   call("weight", trace, lit(0), index, config))))

    def advance(index, weights, action, reading):
        predicted = loop("predict", cells, call("zeros", cells),
                         lambda cell, values: call("put_add", values, call("move", cell, action),
                                                   call("at", weights, cell)))
        return n.Let("predicted", predicted,
                     loop("update", cells, lit(()),
                          lambda cell, values: call("append", values,
                                                    call("mul", call("at", var("predicted"), cell),
                                                         call("protocol_mass", config, cell, reading)))))

    current, weights = var("filter_i"), var("filter_result")
    initial_weights = normalize(initial) if normalize_frames else initial
    next_weights = advance(current, weights, call("issued_at", trace, current),
                           call("frame_at", trace, call("inc", current)))
    if normalize_frames:
        next_weights = normalize(next_weights)
    return n.Let("base", initial_weights,
                 n.Rec("filter", ("filter_i", "filter_result"),
                       branch(call("eq", current, tick), weights,
                              call("filter", call("inc", current), next_weights)),
                       (lit(0), var("base")), call("sub", tick, current)))


def ranked_body(trace, tick, count, config):
    pairs = loop("pairs", lit(64), lit(()),
                 lambda cell, values: call("append", values,
                                            call("pair", cell, call("at", var("weights"), cell))))
    return n.Let("weights", vector(trace, tick, config),
                 n.Let("ordered", call("sort_pairs", pairs),
                       loop("rank", count, lit(()),
                            lambda index, values: call("append", values,
                                                       call("at", call("at", var("ordered"), index), lit(0))))))


def credible_body(trace, tick, quantile, config):
    indices = call("range_values", lit(64))
    weights = vector(trace, tick, config)
    position, picked, mass = var("pick_i"), var("pick_cells"), var("pick_mass")
    ranked = n.Rec("pick", ("pick_i", "pick_cells", "pick_mass"),
                   branch(call("le", quantile, mass), call("pair", picked, mass),
                          call("pick", call("inc", position),
                               call("append", picked, call("at", var("ordered"), position)),
                               call("add", mass,
                                    call("at", var("weights"), call("at", var("ordered"), position))))),
                   (lit(0), lit(()), lit(0)), call("sub", lit(65), position))
    window_list = var("window_list")
    windows = n.Rec("window", ("window_list",),
                    n.Let("bounds_pair", call("head", window_list),
                          n.Let("candidate_cells", call("slice_values", indices,
                                                              call("at", var("bounds_pair"), lit(0)),
                                                              call("at", var("bounds_pair"), lit(1))),
                                n.Let("candidate_mass", loop("interval_mass", call("len", var("candidate_cells")),
                                                              lit(0), lambda idx, total: call("add", total,
                                                                  call("at", var("weights"),
                                                                       call("at", var("candidate_cells"), idx)))),
                                      branch(call("le", quantile, var("candidate_mass")),
                                             call("pair", var("candidate_cells"), var("candidate_mass")),
                                             call("window", call("tail", window_list)))))),
                    (call("intervals", lit(64)),), call("len", window_list))
    return n.Case(((test(call("le", quantile, lit(0))), call("fail", lit("invalid_quantile"))),
                   (test(call("gt", quantile, lit(1))), call("fail", lit("invalid_quantile")))),
                  n.Let("weights", weights,
                        branch(call("eq", call("field", config, lit("credible_mode")), lit("window")),
                               windows, n.Let("ordered", call("ranked", trace, tick, lit(64), config), ranked))))


def hit(start, route, config):
    index, position, visits = var("route_i"), var("route_position"), var("route_visits")
    region = call("field", config, lit("region"))
    end = branch(call("eq", call("field", config, lit("risk_mode")), lit("terminal")),
                 call("contains", region, position),
                 branch(call("eq", call("field", config, lit("risk_mode")), lit("ever")),
                        call("gt", visits, lit(0)), call("le", lit(2), visits)))
    next_position = call("move", position, call("at", route, index))
    return n.Rec("walk_route", ("route_i", "route_position", "route_visits"),
                 branch(call("eq", index, call("len", route)), end,
                        call("walk_route", call("inc", index), next_position,
                             call("add", visits, call("contains", region, next_position)))),
                 (lit(0), start, lit(0)), call("sub", call("len", route), index))


def risk_body(trace, tick, quantile, route, config):
    support = call("credible", trace, tick, quantile, config)
    cells, mass = call("at", var("support"), lit(0)), call("at", var("support"), lit(1))
    lower = loop("risk", call("len", cells), call("div", lit(0), lit(1)),
                 lambda index, total: n.Let("cell", call("at", cells, index),
                                             branch(hit(var("cell"), route, config),
                                                    call("add", total, call("at", var("weights"), var("cell"))),
                                                    total)))
    return n.Let("support", support,
                 n.Let("weights", vector(trace, tick, config),
                       n.Let("lower", lower,
                             call("pair", var("lower"), call("sub", call("add", var("lower"), lit(1)), mass)))))


def certified_body(trace, tick, quantile, route, cap, config):
    interval = call("risk_interval", trace, tick, quantile, route, config)
    return n.Let("interval", interval,
                 branch(call("le", call("at", var("interval"), lit(1)), cap), lit("SAFE"),
                        branch(call("gt", call("at", var("interval"), lit(0)), cap),
                               lit("UNSAFE"), lit("UNKNOWN"))))


def choice_body(trace, tick, quantile, cap, config):
    routes = call("field", config, lit("routes"))
    index = var("choice_i")
    return n.Rec("choose", ("choice_i",),
                 branch(call("eq", index, call("len", routes)), lit("NONE"),
                        n.Let("candidate", call("at", routes, index),
                              branch(call("eq", call("certified", trace, tick, quantile,
                                                     var("candidate"), cap, config), lit("SAFE")),
                                     var("candidate"), call("choose", call("inc", index))))),
                 (lit(0),), call("sub", call("len", routes), index))


def audit_body(trace, tick, quantile, cap, config):
    routes = call("field", config, lit("routes"))
    labels = loop("labels", call("len", routes), lit(()),
                  lambda index, values: n.Let("label_value", call("certified", trace, tick, quantile,
                                                                    call("at", routes, index), cap, config),
                                                call("append", values,
                                                     branch(call("eq", var("label_value"), lit("SAFE")), lit("S"),
                                                            branch(call("eq", var("label_value"), lit("UNSAFE")),
                                                                   lit("U"), lit("?"))))))
    bound = n.Let("interval", call("risk_interval", trace, tick, quantile,
                                         var("chosen"), config),
                  call("join", call("pair", call("fraction_text", call("at", var("interval"), lit(0))),
                                            call("fraction_text", call("at", var("interval"), lit(1)))), lit(",")))
    return n.Let("chosen", call("choice", trace, tick, quantile, cap, config),
                 n.Let("labels_text", call("join", labels, lit("")),
                       call("join", call("pair", call("join", call("pair", var("chosen"),
                                                                      var("labels_text")), lit("|")),
                                                branch(call("eq", var("chosen"), lit("NONE")), lit("NONE"),
                                                       call("join", call("pair", lit("["),
                                                                                      call("join", call("pair", bound,
                                                                                                              lit("]")), lit(""))), lit("")))), lit("|"))))


def definitions():
    trace, tick, cell, config = map(var, ("v", "t", "p", "c"))
    quantile, route, cap = map(var, ("q", "route", "cap"))
    weights = vector(trace, tick, config)
    belief = call("at", weights, cell)
    status = n.Let("raw_weights", vector(trace, tick, config, normalize_frames=False),
                   branch(call("eq", call("sum", var("raw_weights")), lit(0)),
                          lit("IMPOSSIBLE"), lit("POSSIBLE")))
    exact = n.Let("weights", vector(trace, tick, config),
                  loop("exact", lit(64), call("div", lit(0), lit(1)),
                       lambda index, total: branch(hit(index, route, config),
                                                   call("add", total, call("at", var("weights"), index)), total)))
    bodies = (
        ("weight", ("v", "t", "p", "c"), call("protocol_mass", config, cell, call("frame_at", trace, tick))),
        ("belief", ("v", "t", "p", "c"), belief),
        ("ranked", ("v", "t", "n", "c"), ranked_body(trace, tick, var("n"), config)),
        ("credible", ("v", "t", "q", "c"), credible_body(trace, tick, quantile, config)),
        ("risk_interval", ("v", "t", "q", "route", "c"), risk_body(trace, tick, quantile, route, config)),
        ("certified", ("v", "t", "q", "route", "cap", "c"),
         certified_body(trace, tick, quantile, route, cap, config)),
        ("choice", ("v", "t", "q", "cap", "c"), choice_body(trace, tick, quantile, cap, config)),
        ("audit", ("v", "t", "q", "cap", "c"), audit_body(trace, tick, quantile, cap, config)),
        ("status", ("v", "t", "c"), status),
        ("exact_risk", ("v", "t", "route", "c"), exact),
    )
    sorts = {"v": "Trace", "t": "Fin80", "p": "Fin64", "n": "int", "c": "PublicConfig",
             "q": "Rational", "route": "Text", "cap": "Rational"}
    for layer, (name, params, body) in enumerate(bodies, 1):
        dependencies = tuple(sorted(n.all_dependencies(body)))
        spec = ObservationSpec(name, (), body, extra={"inputs": [[param, sorts[param]] for param in params]})
        yield Definition(name, "observation", "invented", layer, dependencies, spec, body)


def inputs_for(case):
    trace = ref.trace_of(case["trace"])
    config = ref.config_of(case)
    values = {"v": trace, "t": case["tick"], "p": case.get("position"),
              "n": case.get("count"), "q": Fraction(case.get("q", "9/10")),
              "route": case.get("route"), "cap": Fraction(case.get("cap", "1/5")), "c": config}
    return values


def args_for(definition, case):
    values = inputs_for(case)
    return tuple(values[name] for name, _ in definition.spec.extra["inputs"])


def references():
    return {
        "weight": lambda trace, tick, cell, config: ref.likelihood(trace, tick, cell, config),
        "belief": lambda trace, tick, cell, config: ref.independent_forward(trace, tick, config)[cell],
        "ranked": lambda trace, tick, count, config: ref.ranked(trace, tick, config)[:count],
        "credible": ref.credible,
        "risk_interval": ref.risk_interval,
        "certified": ref.certified,
        "choice": ref.choice,
        "audit": ref.audit,
        "status": ref.status,
        "exact_risk": ref.exact_risk,
    }


def build_library():
    from .export import design

    source = design()
    library = new_library()
    for definition, entry in zip(definitions(), source["tower"]):
        assert entry["layer"] == definition.layer and entry["check"]["query"] == definition.name
        library.write(definition)
        library.check(definition.name)
        domain = tuple(dict.fromkeys(args_for(definition, row["check"]) for row in
                       (entry, *source["showcase"], *source["generated_cases"])
                       if row["check"]["query"] == definition.name))
        library.make_callable(definition.name, domain[:1])
        request = VerifyRequest("bounded", domain, {"domain": "design tower and public tasks", "size": len(domain)},
                                reference=references()[definition.name])
        library.verify(definition.name, request)
        library.account(definition.name)
        library.promote(definition.name, Contract("Exact on the checked public finite scope"))
    return library
