"""Finite, exact road-network reference semantics; run with Python 3."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import json
from pathlib import Path


@dataclass(frozen=True)
class Bottom:
    reason: str


@dataclass(frozen=True)
class Graph:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str, int], ...]

    def __post_init__(self):
        if not 2 <= len(self.nodes) <= 20 or tuple(sorted(set(self.nodes))) != self.nodes:
            raise ValueError("nodes must be distinct sorted names, size 2..20")
        if not all(isinstance(node, str) and node for node in self.nodes):
            raise ValueError("invalid node")
        keys = []
        for start, end, weight in self.edges:
            if not (start in self.nodes and end in self.nodes and start < end
                    and type(weight) is int and 1 <= weight <= 20):
                raise ValueError("invalid undirected edge or weight")
            keys.append((start, end))
        if keys != sorted(set(keys)):
            raise ValueError("edges must be unique and sorted")


@dataclass(frozen=True)
class Closure:
    base: Graph
    closed: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if self.closed != tuple(sorted(set(self.closed))):
            raise ValueError("closure must be canonical")
        if not set(self.closed) <= {(start, end) for start, end, _ in self.base.edges}:
            raise ValueError("closure contains nonexistent edge")


Network = Graph | Closure


def map_view(network: Network):
    """Layer-0 ?map: reveal every active vertex and weighted edge."""
    if isinstance(network, Graph):
        return network.nodes, network.edges
    return network.base.nodes, tuple(
        item for item in network.base.edges if item[:2] not in network.closed
    )


def edge(network: Network, start: str, end: str):
    """Layer-0 edge: an absent edge gives an explicit failure."""
    pair = tuple(sorted((start, end)))
    if start == end:
        return Bottom("no_edge")
    for left, right, weight in map_view(network)[1]:
        if pair == (left, right):
            return weight
    return Bottom("no_edge")


def chain(first, second, value):
    """Layer-0 @chain[f,g](x), strictly propagating Bottom."""
    result = first(value)
    return result if isinstance(result, Bottom) else second(result)


@dataclass(frozen=True)
class Route:
    network: Network
    nodes: tuple[str, ...]

    def __post_init__(self):
        visible, _ = map_view(self.network)
        if not self.nodes or len(set(self.nodes)) != len(self.nodes):
            raise ValueError("route must be nonempty and simple")
        if any(node not in visible for node in self.nodes):
            raise ValueError("route contains unknown vertex")
        if any(isinstance(edge(self.network, left, right), Bottom)
               for left, right in zip(self.nodes, self.nodes[1:])):
            raise ValueError("route traverses an absent edge")


def cost(route: Route) -> int:
    total = 0
    for start, end in zip(route.nodes, route.nodes[1:]):
        weight = edge(route.network, start, end)
        assert isinstance(weight, int)
        total += weight
    return total


def explore(edge_op, network: Network, start: str, end: str) -> tuple[Route, ...]:
    """@explore[edge]: enumerate all simple routes in lexical node order."""
    nodes, _ = map_view(network)
    if start not in nodes or end not in nodes:
        return ()
    routes = []

    def visit(path):
        if path[-1] == end:
            routes.append(Route(network, path))
            return
        for neighbor in nodes:
            if neighbor not in path and not isinstance(edge_op(network, path[-1], neighbor), Bottom):
                visit(path + (neighbor,))

    visit((start,))
    return tuple(routes)


def best(network: Network, start: str, end: str):
    """Minimize (cost, node sequence) over @explore[edge], pruning positive-cost prefixes."""
    nodes, _ = map_view(network)
    if start not in nodes or end not in nodes:
        return Bottom("unknown_node")
    winner = None

    def visit(path, length):
        nonlocal winner
        if winner is not None and length > winner[0]:
            return
        if path[-1] == end:
            candidate = (length, path)
            if winner is None or candidate < winner:
                winner = candidate
            return
        for neighbor in nodes:
            if neighbor not in path:
                weight = edge(network, path[-1], neighbor)
                if not isinstance(weight, Bottom):
                    visit(path + (neighbor,), length + weight)

    visit((start,), 0)
    return Route(network, winner[1]) if winner is not None else Bottom("no_route")


def optimal(route: Route) -> bool:
    candidate = best(route.network, route.nodes[0], route.nodes[-1])
    return not isinstance(candidate, Bottom) and cost(route) == cost(candidate)


def close(network: Graph, blocked) -> Closure:
    return Closure(network, tuple(sorted(set(tuple(sorted(pair)) for pair in blocked))))


def failures(close_op, network: Graph, budget: int) -> tuple[Closure, ...]:
    """@failures[close] includes all subsets of size at most budget, including empty."""
    if type(budget) is not int or not 0 <= budget <= len(network.edges):
        raise ValueError("invalid failure budget")
    edges = tuple(item[:2] for item in map_view(network)[1])
    return tuple(close_op(network, subset)
                 for count in range(budget + 1)
                 for subset in combinations(edges, count))


def survives(network: Graph, start: str, end: str, budget: int) -> bool:
    """?survives derives only from the public map and closures; no private probe."""
    for damaged in failures(close, network, budget):
        if not explore_first(damaged, start, end):
            return False
    return True


def explore_first(network: Network, start: str, end: str) -> bool:
    """Early-exit existential @explore[edge] for connectivity, with the same semantics."""
    nodes, _ = map_view(network)
    if start not in nodes or end not in nodes:
        return False
    frontier = [(start,)]
    while frontier:
        path = frontier.pop()
        if path[-1] == end:
            return True
        for neighbor in nodes:
            if neighbor not in path and not isinstance(edge(network, path[-1], neighbor), Bottom):
                frontier.append(path + (neighbor,))
    return False


def worst(network: Graph, start: str, end: str, budget: int):
    """Worst cheapest surviving route; tie-break by lexical closed-edge tuple."""
    record = None
    for damaged in failures(close, network, budget):
        route = best(damaged, start, end)
        if isinstance(route, Bottom):
            return Bottom("disconnected")
        candidate = (cost(route), damaged.closed, route.nodes)
        if record is None or candidate[0] > record[0] or (
                candidate[0] == record[0] and candidate[1] < record[1]):
            record = candidate
    return record


def mincut(network: Graph, start: str, end: str):
    """Enumerate all s/t vertex partitions; choose smallest crossing cut, lexical ties."""
    nodes, entries = map_view(network)
    if start not in nodes or end not in nodes or start == end:
        return Bottom("invalid_terminals")
    middle = tuple(node for node in nodes if node not in (start, end))
    answer = None
    for mask in range(1 << len(middle)):
        left = {start} | {node for index, node in enumerate(middle) if mask & (1 << index)}
        cut = tuple((first, second) for first, second, _ in entries
                    if (first in left) != (second in left))
        if answer is None or (len(cut), cut) < (len(answer), answer):
            answer = cut
    return answer


def cut_certificate(network: Graph, start: str, end: str) -> bool:
    """?cut_certificate: independently check failure lower bound and cut witness."""
    cut = mincut(network, start, end)
    if isinstance(cut, Bottom):
        return False
    return (not cut or survives(network, start, end, len(cut) - 1)) and not explore_first(
        close(network, cut), start, end
    )


G = Graph(
    tuple("ABCDEFGHIJKL"),
    (
        ("A", "B", 2), ("A", "C", 4), ("A", "D", 3),
        ("B", "E", 3), ("B", "F", 6),
        ("C", "E", 1), ("C", "F", 2),
        ("D", "F", 2), ("D", "G", 2),
        ("E", "H", 3), ("E", "I", 4),
        ("F", "H", 2), ("F", "I", 3), ("F", "J", 4),
        ("G", "I", 2), ("G", "J", 3),
        ("H", "K", 3), ("H", "L", 8),
        ("I", "K", 2), ("I", "L", 5),
        ("J", "K", 4), ("J", "L", 3), ("K", "L", 2),
    ),
)


def route_value(route: Route) -> str:
    return "Route<" + ",".join(route.nodes) + ">"


def edge_set_value(edges) -> str:
    return "Edges<" + ",".join(left + right for left, right in edges) + ">"


def closure_value(closure: Closure) -> str:
    return "Closure<" + ",".join(left + right for left, right in closure.closed) + ">"


def worst_value(record) -> str:
    if isinstance(record, Bottom):
        return "Bottom<" + record.reason + ">"
    length, blocked, path = record
    return f"Worst<{length},{edge_set_value(blocked)}," + "Route<" + ",".join(path) + ">>"


def truth(value: bool) -> str:
    return "true" if value else "false"


def verify():
    seed_route = Route(G, ("A", "D", "F", "H", "K", "L"))
    sample_damage = close(G, (("A", "B"), ("D", "F")))
    sample_route = best(G, "A", "L")
    assert not isinstance(sample_route, Bottom)
    tower_values = (
        route_value(seed_route),
        str(cost(seed_route)),
        str(len(explore(edge, G, "A", "L"))),
        route_value(sample_route),
        truth(optimal(seed_route)),
        closure_value(sample_damage),
        closure_value(close(G, (("A", "C"), ("D", "G")))),
        str(len(failures(close, G, 2))),
        truth(survives(G, "A", "L", 2)),
        worst_value(worst(G, "A", "L", 2)),
        edge_set_value(mincut(G, "A", "L")),
        truth(cut_certificate(G, "A", "L")),
    )
    record = worst(G, "A", "L", 2)
    assert not isinstance(record, Bottom)
    worst_pairs = [damaged.closed for damaged in failures(close, G, 2)
                   if len(damaged.closed) == 2
                   and cost(best(damaged, "A", "L")) == record[0]]
    showcase_values = (
        worst_value(record),
        edge_set_value(min(worst_pairs)),
        edge_set_value(mincut(G, "A", "L")) + ";" + truth(cut_certificate(G, "A", "L")),
    )
    assert chain(lambda number: number + 1, lambda number: number * 2, 3) == 8
    assert chain(lambda _: Bottom("bad"), lambda _: 0, 3) == Bottom("bad")
    assert edge(G, "A", "L") == Bottom("no_edge")
    assert len(map_view(G)[1]) >= 20
    assert best(G, "L", "A").nodes == tuple(reversed(best(G, "A", "L").nodes)) or cost(
        best(G, "L", "A")) == cost(best(G, "A", "L"))
    assert not explore_first(close(G, mincut(G, "A", "L")), "A", "L")
    assert record[0] == max(cost(best(damaged, "A", "L"))
                            for damaged in failures(close, G, 2))
    document = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert document["id"] == "roads"
    assert [item["layer"] for item in document["tower"]] == list(range(1, 13))
    assert [item["value"] for item in document["tower"]] == list(tower_values), (
        tower_values, [item["value"] for item in document["tower"]]
    )
    assert [item["answer"] for item in document["showcase"]] == list(showcase_values), (
        showcase_values, [item["answer"] for item in document["showcase"]]
    )
    print("OK")


if __name__ == "__main__":
    verify()
