"""Public weighted-road access for the twelve-junction depth design.

Algorithms over paths, failures and cuts do not belong in this layer: those
must unfold through invented definitions in the kernel.
"""

from opulse.atoms.values import Bottom, Card, Ok, boolean

METRO_NODES = tuple("ABCDEFGHIJKL")
METRO_EDGES = (
    ("A", "B", 2), ("A", "C", 4), ("A", "D", 3),
    ("B", "E", 3), ("B", "F", 6), ("C", "E", 1),
    ("C", "F", 2), ("D", "F", 2), ("D", "G", 2),
    ("E", "H", 3), ("E", "I", 4), ("F", "H", 2),
    ("F", "I", 3), ("F", "J", 4), ("G", "I", 2),
    ("G", "J", 3), ("H", "K", 3), ("H", "L", 8),
    ("I", "K", 2), ("I", "L", 5), ("J", "K", 4),
    ("J", "L", 3), ("K", "L", 2),
)


def to_card(graph):
    """Encode a sorted, undirected graph with only opulse.value/2 values."""
    if isinstance(graph, Card):
        if not valid_graph(graph):
            raise ValueError("invalid Roads card")
        return graph
    nodes, edges = graph
    result = Card("Roads", "graph", (
        Card("List", "items", tuple(nodes)),
        Card("List", "items", tuple(Card("Edge", "road", tuple(edge)) for edge in edges)),
    ))
    if not valid_graph(result):
        raise ValueError("invalid Roads graph")
    return result


def from_card(graph):
    graph = to_card(graph)
    return graph.fields[0].fields, tuple(edge.fields for edge in graph.fields[1].fields)


def valid_graph(graph):
    if not isinstance(graph, Card) or graph.sort != "Roads" or graph.tag != "graph" or len(graph.fields) != 2:
        return False
    nodes, edges = graph.fields
    if not (isinstance(nodes, Card) and isinstance(edges, Card)
            and nodes.sort == edges.sort == "List" and nodes.tag == edges.tag == "items"):
        return False
    names = nodes.fields
    if not (2 <= len(names) <= 20 and all(type(name) is str and name for name in names)
            and names == tuple(sorted(set(names)))):
        return False
    pairs = []
    for item in edges.fields:
        if not (isinstance(item, Card) and item.sort == "Edge" and item.tag == "road"
                and len(item.fields) == 3):
            return False
        start, end, weight = item.fields
        if not (type(start) is type(end) is str and start in names and end in names
                and start < end and type(weight) is int and 1 <= weight <= 20):
            return False
        pairs.append((start, end))
    return pairs == sorted(set(pairs))


METRO = to_card((METRO_NODES, METRO_EDGES))


def map_view(graph):
    """Public road maps only; invented closures are unfolded in the kernel."""
    return graph if valid_graph(graph) else Bottom("invalid_graph")


def roads_from_parts(nodes, edges):
    graph = Card("Roads", "graph", (nodes, edges))
    return graph if valid_graph(graph) else Bottom("invalid_graph")


def comb_positive(value):
    return type(value) is int and value > 0


def comb_dec(value):
    return value - 1 if type(value) is int else Bottom("invalid_int")


def fix_equal(left, right):
    return left == right


def edge(graph, start, end):
    graph = map_view(graph)
    if isinstance(graph, Bottom) or start not in graph.fields[0].fields or end not in graph.fields[0].fields:
        return Bottom("invalid_terminals")
    pair = tuple(sorted((start, end)))
    for item in graph.fields[1].fields:
        if item.fields[:2] == pair:
            return item.fields[2]
    return Bottom("no_edge")


def size(items):
    if isinstance(items, Card) and items.sort == "List" and items.tag == "items":
        return len(items.fields)
    return Bottom("invalid_list")


def empty(items):
    count = size(items)
    return count if isinstance(count, Bottom) else boolean(count == 0)


def head(items):
    return items.fields[0] if isinstance(items, Card) and items.sort == "List" and items.fields else Bottom("empty")


def tail(items):
    return Card("List", "items", items.fields[1:]) if isinstance(items, Card) and items.sort == "List" and items.fields else Bottom("empty")


def cons(item, items):
    return Card("List", "items", (item, *items.fields)) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid_list")


def append(left, right):
    if all(isinstance(items, Card) and items.sort == "List" for items in (left, right)):
        return Card("List", "items", (*left.fields, *right.fields))
    return Bottom("invalid_list")


def contains(item, items):
    return boolean(item in items.fields) if isinstance(items, Card) and items.sort == "List" else Bottom("invalid_list")


def eq(left, right):
    return boolean(left == right)


def lt(left, right):
    if type(left) is type(right) and type(left) in (int, str):
        return boolean(left < right)
    return Bottom("invalid_compare")


def add(left, right):
    return left + right if type(left) is type(right) is int else Bottom("invalid_int")


def sub(left, right):
    return left - right if type(left) is type(right) is int else Bottom("invalid_int")


def items(*values):
    return Card("List", "items", values)


def reverse(values):
    return items(*reversed(values.fields)) if isinstance(values, Card) and values.sort == "List" else Bottom("invalid_list")


def graph_nodes(graph):
    graph = map_view(graph)
    return graph if isinstance(graph, Bottom) else graph.fields[0]


def graph_edges(graph):
    graph = map_view(graph)
    return graph if isinstance(graph, Bottom) else graph.fields[1]


def edge_id(road):
    return road.fields[0] + road.fields[1] if isinstance(road, Card) and road.sort == "Edge" else Bottom("invalid_edge")


def is_ok(result):
    return boolean(not isinstance(result, Bottom))


def distinct(values):
    return boolean(isinstance(values, Card) and values.sort == "List"
                   and len(values.fields) == len(set(values.fields)))


def subset(values, universe):
    return boolean(isinstance(values, Card) and isinstance(universe, Card)
                   and values.sort == universe.sort == "List" and set(values.fields) <= set(universe.fields))


def pair_before(left, right):
    return boolean(left.fields < right.fields) if isinstance(left, Card) and isinstance(right, Card) else Bottom("invalid_compare")


def edge_set(identifiers):
    return Card("Edges", "set", (identifiers,)) if isinstance(identifiers, Card) and identifiers.sort == "List" else Bottom("invalid_list")


def route_raw(graph, vertices):
    return Card("RouteRaw", "route", (graph, vertices))


def closure_raw(graph, closed):
    return Card("ClosureRaw", "closed", (graph, closed))


def worst_record(cost, closures, route):
    return Card("Worst", "record", (cost, closures, route))


def no_route():
    return Bottom("no_route")


def disconnected():
    return Bottom("disconnected")


def invalid_terminals():
    return Bottom("invalid_terminals")


def invalid_budget():
    return Bottom("invalid_budget")


def road_fields(road):
    return items(*road.fields) if isinstance(road, Card) and road.sort == "Edge" else Bottom("invalid_edge")


def edge_set_ids(closed):
    if (isinstance(closed, Card) and closed.sort == "Edges" and closed.tag == "set"
            and len(closed.fields) == 1 and isinstance(closed.fields[0], Card)
            and closed.fields[0].sort == "List" and closed.fields[0].tag == "items"
            and all(type(identifier) is str for identifier in closed.fields[0].fields)):
        return closed.fields[0]
    return Bottom("invalid_edges")


def valid_route_raw(raw):
    return (isinstance(raw, Card) and raw.sort == "RouteRaw" and raw.tag == "route"
            and len(raw.fields) == 2 and (valid_graph(raw.fields[0])
                or (isinstance(raw.fields[0], Card) and raw.fields[0].sort == "Closure"
                    and raw.fields[0].tag == "val" and len(raw.fields[0].fields) == 1))
            and isinstance(raw.fields[1], Card) and raw.fields[1].sort == "List"
            and raw.fields[1].tag == "items"
            and all(type(vertex) is str for vertex in raw.fields[1].fields))


def valid_closure_raw(raw):
    return (isinstance(raw, Card) and raw.sort == "ClosureRaw" and raw.tag == "closed"
            and len(raw.fields) == 2 and valid_graph(raw.fields[0])
            and not isinstance(edge_set_ids(raw.fields[1]), Bottom))


def raw_graph(raw):
    return raw.fields[0] if valid_route_raw(raw) else Bottom("invalid_route")


def raw_vertices(raw):
    return raw.fields[1] if valid_route_raw(raw) else Bottom("invalid_route")


def raw_base(raw):
    return raw.fields[0] if valid_closure_raw(raw) else Bottom("invalid_closure")


def raw_closed(raw):
    return raw.fields[1] if valid_closure_raw(raw) else Bottom("invalid_closure")


def sort_frontier(states):
    if not isinstance(states, Card) or states.sort != "List":
        return Bottom("invalid_list")
    return items(*sorted(states.fields, key=lambda state: (state.fields[0], state.fields[1].fields)))


def sort_texts(values):
    return items(*sorted(set(values.fields))) if isinstance(values, Card) and values.sort == "List" else Bottom("invalid_list")


def reach_state(graph, reached):
    return Card("Reach", "state", (graph, reached))


def reach_graph(state):
    return state.fields[0] if isinstance(state, Card) and state.sort == "Reach" else Bottom("invalid_reach")


def reach_seen(state):
    return state.fields[1] if isinstance(state, Card) and state.sort == "Reach" else Bottom("invalid_reach")


def sort_edge_sets(sets):
    return items(*sorted(sets.fields, key=lambda item: (len(item.fields[0].fields), item.fields[0].fields))) if isinstance(sets, Card) and sets.sort == "List" else Bottom("invalid_list")


def defined(value):
    return boolean(isinstance(value, Ok))


def capture(value):
    if isinstance(value, Bottom):
        return Card("Lift", "bot", (value.reason,))
    if isinstance(value, Ok):
        return Card("Lift", "val", (value.value,))
    return value


def is_value(value):
    return boolean(isinstance(value, Card) and value.sort == "Lift" and value.tag == "val")


def unlift(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "Lift" and value.tag == "val" else Bottom("invalid_lift")
