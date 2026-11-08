"""Fixed, public relation constructors and operators (not learner inventions)."""

from opulse.atoms.values import Bottom, Card, Ok, boolean, truth

from . import algorithms as relations


def relation(value):
    if isinstance(value, Card) and value.sort == "Rel" and value.tag == "Rel":
        size, rows = value.fields
        if (type(size) is int and size > 0 and isinstance(rows, Card) and rows.sort == "Rows"
                and len(rows.fields) == size and all(type(row) is int and 0 <= row < 1 << size
                                                      for row in rows.fields)):
            return relations.Rel(size, rows.fields)
    raise ValueError("invalid relation")


def pack(value):
    return Card("Rel", "Rel", (value.size, Card("Rows", "Rows", value.rows)))


def profile_value(value):
    if isinstance(value, Card) and value.sort == "Profile":
        return relations.Profile(list(value.fields[0].fields), list(value.fields[1].fields))
    raise ValueError("invalid profile")


def pack_profile(value):
    return Card("Profile", "Profile", (Card("List", "items", tuple(value.depth)),
                                         Card("List", "items", tuple(value.ways))))


def braid(levels, lanes, cycle, gates):
    if not isinstance(gates, Card) or gates.sort != "Gates":
        return Bottom("invalid")
    indices = gates.fields
    if (type(levels) is not int or type(lanes) is not int or type(cycle) is not int or
            levels < 2 or lanes < 1 or cycle < 1 or
            any(type(gate) is not int or gate < 0 or gate >= levels - 1 for gate in indices) or
            tuple(sorted(set(indices))) != indices):
        return Bottom("invalid")
    return pack(relations.braid(levels, lanes, cycle, indices))


def switch_net(levels, width, seed):
    try:
        return pack(relations.switch_net(levels, width, seed))
    except ValueError:
        return Bottom("invalid")


def identity(value):
    return pack(relations.identity(relation(value).size))


def union(left, right):
    return pack(relations.union(relation(left), relation(right)))


def compose(left, right):
    return pack(relations.compose(relation(left), relation(right)))


def transpose(value):
    return pack(relations.transpose(relation(value)))


def intersect(left, right):
    first, second = relation(left), relation(right)
    return pack(relations.Rel(first.size, tuple(a & b for a, b in zip(first.rows, second.rows))))


def subtract(left, right):
    first, second = relation(left), relation(right)
    return pack(relations.Rel(first.size, tuple(a & ~b for a, b in zip(first.rows, second.rows))))


def quotient(value, equivalence):
    return pack(relations.collapse(relation(value), relation(equivalence)))


def fix2(context, function, seed, base):
    graph = relation(seed)
    relation(base)
    current = seed
    while True:
        outcome = context.call(function.name, (current, base))
        if not isinstance(outcome, Ok):
            return outcome
        next_graph = relation(outcome.value)
        if next_graph.size != graph.size or any(old & ~new for old, new in
                                                zip(graph.rows, next_graph.rows)):
            return Bottom("non_monotone")
        if next_graph.rows == graph.rows:
            return outcome.value
        current, graph = outcome.value, next_graph


def dag_fold(context, function, value):
    graph = relation(value)
    incoming = [0] * graph.size
    for _, target_vertex in graph.edges():
        incoming[target_vertex] += 1
    queue = [vertex for vertex, degree in enumerate(incoming) if degree == 0]
    profile = Card("Profile", "Profile", (Card("List", "items", (0,) * graph.size),
                                           Card("List", "items", (1,) * graph.size)))
    offset = 0
    while offset < len(queue):
        source_vertex = queue[offset]
        offset += 1
        row = graph.rows[source_vertex]
        while row:
            bit = row & -row
            target_vertex = bit.bit_length() - 1
            outcome = context.call(function.name, (profile, source_vertex, target_vertex))
            if not isinstance(outcome, Ok):
                return outcome
            profile = outcome.value
            incoming[target_vertex] -= 1
            if incoming[target_vertex] == 0:
                queue.append(target_vertex)
            row -= bit
    return profile if offset == graph.size else Bottom("cycle")


def set_profile(value, vertex, depth, ways):
    profile = profile_value(value)
    profile.depth[vertex] = depth
    profile.ways[vertex] = ways
    return pack_profile(profile)


def filter_edges(context, predicate, value, forward, backward):
    graph = relation(value)
    rows = [0] * graph.size
    for source, target in graph.edges():
        result = context.call(predicate.name, (Card("Edge", "Edge", (source, target)), forward, backward))
        if not isinstance(result, Ok):
            return result
        if truth(result.value):
            rows[source] |= 1 << target
    return pack(relations.Rel(graph.size, tuple(rows)))


def source(edge):
    return edge.fields[0]


def target(edge):
    return edge.fields[1]


def depth_at(profile, vertex):
    return profile_value(profile).depth[vertex]


def ways_at(profile, vertex):
    return profile_value(profile).ways[vertex]


def add(left, right):
    return left + right


def mul(left, right):
    return left * right


def eq(left, right):
    return boolean(left == right)


def lt(left, right):
    return boolean(left < right)


def has(value, edge):
    graph = relation(value)
    if not isinstance(edge, Card) or edge.sort != "Edge" or len(edge.fields) != 2:
        return Bottom("invalid_edge")
    source, target = edge.fields
    if (type(source) is not int or type(target) is not int or
            not 0 <= source < graph.size or not 0 <= target < graph.size):
        return Bottom("invalid_edge")
    return boolean(bool(graph.rows[source] & (1 << target)))


def count(value):
    return relations.count(relation(value))


def maxdepth(value):
    return max(profile_value(value).depth)


def longest_count(value):
    return relations.longest_count(profile_value(value))
