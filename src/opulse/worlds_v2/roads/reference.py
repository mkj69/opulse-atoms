"""Independent depth-design oracle, used only by the bounded evidence verifier."""

import importlib.util
import sys
from pathlib import Path

from opulse.atoms.values import Bottom, Card, boolean

from . import depth_hosts as hosts


def design():
    name = "opulse_roads_depth_design"
    if name not in sys.modules:
        path = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/roads.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def graph(value):
    module = design()
    if isinstance(value, Card) and value.sort == "Closure":
        base, closed = value.fields[0].fields
        return module.Closure(graph(base), tuple((name[0], name[1]) for name in closed.fields[0].fields))
    nodes, edges = hosts.from_card(value)
    return module.Graph(nodes, edges)


def route(value):
    raw = value.fields[0]
    return design().Route(graph(raw.fields[0]), raw.fields[1].fields)


def encode_route(value):
    network = value.network
    if isinstance(network, design().Closure):
        network = Card("Closure", "val", (hosts.closure_raw(hosts.to_card((network.base.nodes, network.base.edges)),
                          hosts.edge_set(hosts.items(*(start + end for start, end in network.closed)))),))
    else:
        network = hosts.to_card((network.nodes, network.edges))
    return Card("Route", "val", (hosts.route_raw(network, hosts.items(*value.nodes)),))


def encode_closure(value):
    return Card("Closure", "val", (hosts.closure_raw(hosts.to_card((value.base.nodes, value.base.edges)),
                      hosts.edge_set(hosts.items(*(start + end for start, end in value.closed)))),))


def encode_edges(value):
    return hosts.edge_set(hosts.items(*(start + end for start, end in value)))


def expected(name, *args):
    module = design()
    if name == "Route":
        raw = args[0]
        try:
            return encode_route(module.Route(graph(raw.fields[0]), raw.fields[1].fields))
        except ValueError:
            return Bottom("invalid")
    if name == "Closure":
        raw = args[0]
        try:
            return encode_closure(module.Closure(graph(raw.fields[0]),
                tuple((identifier[0], identifier[1]) for identifier in raw.fields[1].fields[0].fields)))
        except ValueError:
            return Bottom("invalid")
    if name == "cost":
        return module.cost(route(args[0]))
    if name == "explore":
        _, network, start, end = args
        return hosts.items(*(encode_route(item) for item in module.explore(module.edge, graph(network), start, end)))
    if name == "best":
        return outcome_result(module.best(graph(args[0]), args[1], args[2]))
    if name == "optimal":
        return boolean(module.optimal(route(args[0])))
    if name == "close":
        network, blocked = args
        return encode_closure(module.close(graph(network),
                            tuple((name[0], name[1]) for name in blocked.fields[0].fields)))
    if name == "failures":
        _, network, budget = args
        return hosts.items(*(encode_closure(item) for item in module.failures(module.close, graph(network), budget)))
    if name == "survives":
        network, start, end, budget = args
        return boolean(module.survives(graph(network), start, end, budget))
    if name == "worst":
        network, start, end, budget = args
        record = module.worst(graph(network), start, end, budget)
        if isinstance(record, module.Bottom):
            return Bottom(record.reason)
        cost, blocked, vertices = record
        closure = module.close(graph(network), blocked)
        return hosts.worst_record(cost, encode_edges(blocked),
                                  encode_route(module.Route(closure, vertices)))
    if name == "mincut":
        return outcome_result(module.mincut(graph(args[0]), args[1], args[2]))
    if name == "cut_certificate":
        return boolean(module.cut_certificate(graph(args[0]), args[1], args[2]))
    raise ValueError(name)


def outcome_result(value):
    if isinstance(value, design().Bottom):
        return Bottom(value.reason)
    if isinstance(value, design().Route):
        return encode_route(value)
    return encode_edges(value)
