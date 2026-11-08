"""Layer-zero valence graph atoms and generic finite-value primitives."""

from itertools import combinations, permutations

from opulse.atoms.values import Bottom, Card, boolean

VALENCE = {"C": 4, "O": 2}


def list_make(*values):
    return Card("List", "items", values)


def pair_make(left, right):
    return Card("Pair", "pair", (left, right))


def to_card(labels, edges=(), hydrogen=None):
    labels = tuple(labels)
    return Card("Graph", "val", (list_make(*labels),
                                 list_make(*(pair_make(*edge) for edge in edges)),
                                 list_make(*(hydrogen if hydrogen is not None else (0,) * len(labels)))))


def from_card(graph):
    if not isinstance(graph, Card) or (graph.sort, graph.tag) != ("Graph", "val") or len(graph.fields) != 3:
        raise ValueError("invalid")
    labels, edges, hydrogen = graph.fields
    if any(not isinstance(item, Card) or (item.sort, item.tag) != ("List", "items")
           for item in (labels, edges, hydrogen)):
        raise ValueError("invalid")
    labels, hydrogen = labels.fields, hydrogen.fields
    if not 1 <= len(labels) <= 8 or len(hydrogen) != len(labels):
        raise ValueError("size")
    if any(type(label) is not str or label not in VALENCE for label in labels):
        raise ValueError("element")
    if any(type(count) is not int or count < 0 for count in hydrogen):
        raise ValueError("hydrogen")
    if len(labels) + sum(hydrogen) > 32:
        raise ValueError("size")
    pairs = []
    for edge in edges.fields:
        if not isinstance(edge, Card) or (edge.sort, edge.tag) != ("Pair", "pair") or len(edge.fields) != 2:
            raise ValueError("edge")
        left, right = edge.fields
        if type(left) is not int or type(right) is not int or not 0 <= left < right < len(labels):
            raise ValueError("edge")
        pairs.append((left, right))
    if pairs != sorted(set(pairs)):
        raise ValueError("edge")
    if any(count + sum(index in pair for pair in pairs) > VALENCE[label]
           for index, (label, count) in enumerate(zip(labels, hydrogen))):
        raise ValueError("valence")
    return labels, tuple(pairs), hydrogen


def graph_create(labels, edges, hydrogen):
    graph = Card("Graph", "val", (labels, edges, hydrogen))
    try:
        from_card(graph)
    except ValueError as error:
        return Bottom(str(error))
    return graph


def graph_raw(labels, edges, hydrogen):
    if any(not isinstance(item, Card) or (item.sort, item.tag) != ("List", "items")
           for item in (labels, edges, hydrogen)):
        return Bottom("invalid")
    return Card("Graph", "val", (labels, edges, hydrogen))


def graph_valid(graph):
    try:
        from_card(graph)
        return boolean(True)
    except ValueError:
        return boolean(False)


def graph_key(graph):
    try:
        labels, edges, hydrogen = from_card(graph)
        return ("".join(labels) + "/" + ",".join(map(str, hydrogen)) + "/" +
                ",".join(f"{left}-{right}" for left, right in edges))
    except ValueError as error:
        return Bottom(str(error))


def graph_labels(graph):
    return graph.fields[0] if isinstance(graph, Card) and graph.sort == "Graph" else Bottom("invalid")


def graph_edges(graph):
    return graph.fields[1] if isinstance(graph, Card) and graph.sort == "Graph" else Bottom("invalid")


def graph_hydrogen(graph):
    return graph.fields[2] if isinstance(graph, Card) and graph.sort == "Graph" else Bottom("invalid")


def attach(graph, atom, old):
    try:
        labels, edges, hydrogen = from_card(graph)
    except ValueError as error:
        return Bottom(str(error))
    if type(old) is not int or not 0 <= old < len(labels):
        return Bottom("index")
    if atom == "H":
        counts = list(hydrogen)
        counts[old] += 1
        candidate = to_card(labels, edges, counts)
    elif type(atom) is str and atom in VALENCE:
        candidate = to_card((*labels, atom), sorted((*edges, (old, len(labels)))), (*hydrogen, 0))
    else:
        return Bottom("element")
    try:
        from_card(candidate)
    except ValueError as error:
        return Bottom(str(error))
    return candidate


def link(graph, left, right):
    try:
        labels, edges, hydrogen = from_card(graph)
    except ValueError as error:
        return Bottom(str(error))
    if type(left) is not int or type(right) is not int or left == right or not (
            0 <= left < len(labels) and 0 <= right < len(labels)):
        return Bottom("index")
    candidate = to_card(labels, sorted((*edges, tuple(sorted((left, right))))), hydrogen)
    try:
        from_card(candidate)
    except ValueError as error:
        return Bottom(str(error))
    return candidate


def identity(graph):
    try:
        from_card(graph)
    except ValueError as error:
        return Bottom(str(error))
    return graph


def atoms(graph):
    try:
        labels, edges, hydrogen = from_card(graph)
    except ValueError as error:
        return Bottom(str(error))
    return Card("AtomsView", "view", (list_make(*(Card("Triple", "triple", (
        label, hydrogen[index], VALENCE[label] - hydrogen[index] - sum(index in edge for edge in edges)))
        for index, label in enumerate(labels))), graph.fields[1]))


def count(values):
    return len(values.fields) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")


def group_sizes(groups):
    if not isinstance(groups, Card) or groups.tag != "items":
        return Bottom("invalid")
    return list_make(*(pair_make(pair_left(item), count(pair_right(item))) for item in groups.fields))


def list_get(values, index):
    if not isinstance(values, Card) or values.tag != "items" or type(index) is not int or not 0 <= index < len(values.fields):
        return Bottom("index")
    return values.fields[index]


def list_append(values, value):
    return list_make(*values.fields, value) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")


def list_prepend(values, value):
    return list_make(value, *values.fields) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")


def list_sort(values):
    if not isinstance(values, Card) or values.tag != "items":
        return Bottom("invalid")
    try:
        return list_make(*sorted(values.fields, key=lambda item: item.fields if isinstance(item, Card) else item))
    except TypeError:
        return Bottom("invalid")


def list_unique(values):
    return list_make(*dict.fromkeys(values.fields)) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")


def list_permutations(values):
    return list_make(*(list_make(*item) for item in permutations(values.fields))) if isinstance(values, Card) and values.tag == "items" and len(values.fields) <= 8 else Bottom("size")


def list_label_permutations(values, auxiliary):
    if (not isinstance(values, Card) or values.tag != "items" or
            not isinstance(auxiliary, Card) or auxiliary.tag != "items" or
            len(values.fields) != len(auxiliary.fields) or len(values.fields) > 8):
        return Bottom("size")
    keys = tuple(zip(values.fields, auxiliary.fields))
    groups = [tuple(index for index, item in enumerate(keys) if item == key)
              for key in sorted(set(keys))]
    from itertools import product

    return list_make(*(list_make(*(index for group in ordering for index in group))
                       for ordering in product(*(permutations(group) for group in groups))))


def list_permute(values, order):
    if not isinstance(values, Card) or values.tag != "items" or not isinstance(order, Card) or order.tag != "items":
        return Bottom("invalid")
    if any(type(index) is not int for index in order.fields) or sorted(order.fields) != list(range(len(values.fields))):
        return Bottom("invalid")
    return list_make(*(values.fields[index] for index in order.fields))


def list_reindex_pairs(pairs, order):
    if not isinstance(pairs, Card) or pairs.tag != "items" or not isinstance(order, Card) or order.tag != "items":
        return Bottom("invalid")
    if any(type(index) is not int for index in order.fields) or sorted(order.fields) != list(range(len(order.fields))) or any(
            not isinstance(pair, Card) or pair.tag != "pair" or len(pair.fields) != 2
            or any(type(index) is not int or not 0 <= index < len(order.fields) for index in pair.fields)
            for pair in pairs.fields):
        return Bottom("invalid")
    inverse = {old: new for new, old in enumerate(order.fields)}
    return list_make(*(pair_make(*sorted((inverse[left], inverse[right])))
                       for left, right in sorted((pair.fields for pair in pairs.fields),
                                                 key=lambda value: tuple(sorted(inverse[item] for item in value)))))


def list_combinations(values, size):
    return list_make(*(list_make(*item) for item in combinations(values.fields, size))) if isinstance(values, Card) and values.tag == "items" and len(values.fields) <= 15 and type(size) is int and 0 <= size <= min(len(values.fields), 6) else Bottom("size")


def list_range(size):
    return list_make(*range(size)) if type(size) is int and 0 <= size <= 32 else Bottom("size")


def list_repeat(value, size):
    return list_make(*([value] * size)) if type(size) is int and 0 <= size <= 32 else Bottom("size")


def list_replace(values, index, value):
    if not isinstance(values, Card) or values.tag != "items" or type(index) is not int or not 0 <= index < len(values.fields):
        return Bottom("index")
    result = list(values.fields)
    result[index] = value
    return list_make(*result)


def list_index(values, value):
    return values.fields.index(value) if isinstance(values, Card) and values.tag == "items" and value in values.fields else Bottom("missing")


def pair_left(pair):
    return pair.fields[0] if isinstance(pair, Card) and pair.tag == "pair" else Bottom("invalid")


def pair_right(pair):
    return pair.fields[1] if isinstance(pair, Card) and pair.tag == "pair" else Bottom("invalid")


def triple_get(value, index):
    return value.fields[index] if isinstance(value, Card) and value.tag == "triple" and type(index) is int and 0 <= index < 3 else Bottom("index")


def view_vertices(view):
    return view.fields[0] if isinstance(view, Card) and view.tag == "view" else Bottom("invalid")


def view_edges(view):
    return view.fields[1] if isinstance(view, Card) and view.tag == "view" else Bottom("invalid")


def plus(left, right):
    return left + right if type(left) is int and type(right) is int else Bottom("invalid")


def minus(left, right):
    return left - right if type(left) is int and type(right) is int else Bottom("invalid")


def small_half(value):
    return value // 2 if type(value) is int and 0 <= value <= 40320 else Bottom("invalid")


def equal(left, right):
    return boolean(left == right)


def less(left, right):
    try:
        return boolean(left < right)
    except TypeError:
        return Bottom("invalid")


def text_join(values, separator):
    return separator.join(values.fields) if isinstance(values, Card) and values.tag == "items" and isinstance(separator, str) and all(isinstance(item, str) for item in values.fields) else Bottom("invalid")


def text_concat(left, right):
    return left + right if isinstance(left, str) and isinstance(right, str) else Bottom("invalid")


def text_of_int(value):
    return str(value) if type(value) is int else Bottom("invalid")


def list_contains(values, value):
    return boolean(isinstance(values, Card) and values.tag == "items" and value in values.fields)


def list_add_unique(values, value):
    return list_make(*values.fields, value) if isinstance(values, Card) and values.tag == "items" and value not in values.fields else values


def list_take(values, size):
    return list_make(*values.fields[:size]) if isinstance(values, Card) and values.tag == "items" and type(size) is int and size >= 0 else Bottom("invalid")


def record_make(profile, number, witness):
    return Card("Record", "ambiguity", (profile, number, witness))


def value_less(left, right):
    try:
        first = left.fields if isinstance(left, Card) else left
        second = right.fields if isinstance(right, Card) else right
        return boolean(first < second)
    except TypeError:
        return Bottom("invalid")


def list_insert_pair(values, item):
    if not isinstance(values, Card) or values.tag != "items" or not isinstance(item, Card) or item.tag != "pair":
        return Bottom("invalid")
    existing = {pair_left(pair): pair for pair in values.fields}
    existing.setdefault(pair_left(item), item)
    try:
        return list_make(*(existing[key] for key in sorted(existing, key=lambda key: key.fields if isinstance(key, Card) else key)))
    except TypeError:
        return Bottom("invalid")


def list_rights(values):
    return list_make(*(pair_right(pair) for pair in values.fields)) if isinstance(values, Card) and values.tag == "items" else Bottom("invalid")


def list_groups_insert(groups, key, value):
    if not isinstance(groups, Card) or groups.tag != "items":
        return Bottom("invalid")
    entries = [(pair_left(pair), pair_right(pair)) for pair in groups.fields]
    if any(old == key for old, _ in entries):
        return list_make(*(pair_make(old, list_append(members, value) if old == key else members)
                           for old, members in entries))
    return list_append(groups, pair_make(key, list_make(value)))


def list_sort_groups(groups):
    if not isinstance(groups, Card) or groups.tag != "items":
        return Bottom("invalid")
    try:
        def key(item):
            value = pair_left(item)
            return value.fields if isinstance(value, Card) else value
        return list_make(*(pair_make(pair_left(pair), list_sort(pair_right(pair)))
                           for pair in sorted(groups.fields, key=key)))
    except TypeError:
        return Bottom("invalid")


def always_fail(reason):
    return Bottom(reason) if isinstance(reason, str) else Bottom("invalid")
