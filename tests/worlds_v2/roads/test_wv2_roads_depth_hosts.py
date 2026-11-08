"""Depth-layer public graph access is lossless and agrees with its design oracle."""

import importlib.util
import sys
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.values import Bottom, Card, Ok, decode, encode
from opulse.worlds_v2.roads import depth_combinators, depth_hosts

SOURCE = Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/roads.py"


def reference():
    specification = importlib.util.spec_from_file_location("roads_depth_reference", SOURCE)
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_metro_is_the_complete_23_edge_design_graph():
    oracle = reference()
    assert depth_hosts.from_card(depth_hosts.METRO) == (oracle.G.nodes, oracle.G.edges)
    assert len(depth_hosts.METRO.fields[1].fields) == 23
    assert decode(encode(depth_hosts.METRO)) == depth_hosts.METRO
    for start in oracle.G.nodes:
        for end in oracle.G.nodes:
            actual = depth_hosts.edge(depth_hosts.METRO, start, end)
            expected = oracle.edge(oracle.G, start, end)
            assert (actual.reason if isinstance(actual, Bottom) else actual) == (
                expected.reason if isinstance(expected, oracle.Bottom) else expected)


def test_fifty_public_subgraphs_and_closed_road_interface():
    oracle = reference()
    for mask in range(50):
        removed = {index for index in range(6) if mask & (1 << index)}
        edges = tuple(edge for index, edge in enumerate(oracle.G.edges) if index not in removed)
        graph = depth_hosts.to_card((oracle.G.nodes, edges))
        assert depth_hosts.from_card(graph) == (oracle.G.nodes, edges)
        assert depth_hosts.map_view(graph) == graph
        for start, end, weight in edges:
            assert depth_hosts.edge(graph, start, end) == weight
            assert depth_hosts.edge(graph, end, start) == weight
    closed = Card("Edges", "set", (Card("List", "items", ("AB", "DF")),))
    closure = Card("Closure", "val", (Card("ClosureRaw", "closed", (depth_hosts.METRO, closed)),))
    assert depth_hosts.map_view(closure) == Bottom("invalid_graph")
    assert depth_hosts.edge(closure, "A", "B") == Bottom("invalid_terminals")
    assert depth_hosts.map_view(depth_hosts.METRO) == depth_hosts.METRO


def test_graph_rejects_invalid_or_noncanonical_inputs():
    for graph in (
        (("A", "B"), (("B", "A", 1),)),
        (("A", "B"), (("A", "B", 0),)),
        (("A", "B"), (("A", "B", 21),)),
        (("A", "B"), (("A", "B", 1), ("A", "B", 2))),
        (("B", "A"), (("A", "B", 1),)),
    ):
        try:
            depth_hosts.to_card(graph)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid graph was accepted")


def test_invalid_closures_do_not_remove_nonexistent_or_duplicate_edges():
    for identifiers in (("AA",), ("AB", "AB"), ("DF", "AB"), ("ZZ",)):
        closed = Card("Edges", "set", (Card("List", "items", identifiers),))
        closure = Card("Closure", "val", (Card("ClosureRaw", "closed", (depth_hosts.METRO, closed)),))
        assert depth_hosts.map_view(closure) == Bottom("invalid_graph")


def test_given_chain_unfolds_and_preserves_first_failure():
    spec = depth_combinators.chain_spec()
    scope = kernel.DictScope(
        (kernel.Atom("double", 1, lambda value: value * 2),
         kernel.Atom("next", 1, lambda value: value + 1),
         kernel.Atom("reject", 1, lambda value: Bottom("bad"))),
        (kernel.Defn("chain", spec.params, spec.body, "combinator", 0),),
    )
    assert kernel.call("chain", (kernel.FnRef("double"), kernel.FnRef("next"), 3), scope).outcome == Ok(7)
    failure = kernel.call("chain", (kernel.FnRef("reject"), kernel.FnRef("next"), 3), scope)
    assert failure.outcome == Bottom("bad") and failure.steps == 1


def test_public_edge_is_one_counted_given_step():
    scope = kernel.DictScope((kernel.Atom("edge", 3, depth_hosts.edge, cost=1),))
    assert kernel.call("edge", (depth_hosts.METRO, "A", "B"), scope).outcome == Ok(2)
    missing = kernel.call("edge", (depth_hosts.METRO, "A", "L"), scope, trace=True)
    assert missing.outcome == Bottom("no_edge")
    assert missing.steps == 1 and missing.trace.children[0].given
