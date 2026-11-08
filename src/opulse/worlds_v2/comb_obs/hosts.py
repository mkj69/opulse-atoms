"""Physical warehouse actions and generic operations on authorized values."""

from copy import deepcopy
from itertools import permutations

from opulse.atoms.values import Bottom

SIZE = 64
CAPACITY = 600
HOME = (2, 2)
DIRECTIONS = ((0, -1), (-1, 0), (1, 0), (0, 1))


def _free(seed, cell):
    x_coord, y_coord = cell
    if not (0 <= x_coord < SIZE and 0 <= y_coord < SIZE):
        return False
    if x_coord and x_coord % 8 == 0:
        return y_coord % 8 == 2 + ((7 * seed + 11 * x_coord + 13 * (y_coord // 8)) % 5)
    if y_coord and y_coord % 8 == 0:
        return x_coord % 8 == 2 + ((3 * seed + 17 * y_coord + 19 * (x_coord // 8)) % 5)
    return True


def _record(state, action, known_before=True, order_id=None):
    state.log.append((action, state.pos, state.energy, known_before, order_id, state.payload))


def scan(state):
    if state.energy < 2:
        return Bottom("energy")
    state = deepcopy(state)
    state.energy -= 2
    state.tick += 1
    state.scans += 1
    for x_coord in range(max(0, state.pos[0] - 3), min(SIZE, state.pos[0] + 4)):
        for y_coord in range(max(0, state.pos[1] - 3), min(SIZE, state.pos[1] + 4)):
            state.known[(x_coord, y_coord)] = _free(state.seed, (x_coord, y_coord))
    _record(state, "scan")
    return state


def move(state, direction):
    if direction not in DIRECTIONS:
        return Bottom("direction")
    destination = (state.pos[0] + direction[0], state.pos[1] + direction[1])
    if state.energy < 1:
        return Bottom("energy")
    if not _free(state.seed, destination):
        return Bottom("blocked")
    state = deepcopy(state)
    known_before = state.known.get(destination) is True
    state.energy -= 1
    state.tick += 1
    state.moves += 1
    state.pos = destination
    _record(state, "move", known_before)
    return state


def charge(state):
    if state.pos != HOME or state.onboard:
        return Bottom("not_depot")
    state = deepcopy(state)
    state.energy = CAPACITY
    state.tick += 30
    state.charges += 1
    _record(state, "charge")
    return state


def pick(state, order_id):
    if (order_id not in state.orders or state.pos != HOME or
            order_id in state.onboard or order_id in state.delivered or
            state.payload + state.orders[order_id][1] > 3):
        return Bottom("pickup")
    state = deepcopy(state)
    state.onboard.add(order_id)
    state.tick += 1
    _record(state, "pick", order_id=order_id)
    return state


def deliver(state, order_id):
    if order_id not in state.onboard or state.pos != state.orders[order_id][0]:
        return Bottom("not_delivery_site")
    state = deepcopy(state)
    state.onboard.remove(order_id)
    state.delivered.add(order_id)
    state.deliveries += 1
    state.tick += 1
    _record(state, "deliver", order_id=order_id)
    return state


def probe_pos(state):
    return state.pos


def probe_energy(state):
    return state.energy


def probe_known(state):
    return dict(state.known)


def probe_goal(state):
    return state.goal


def probe_orders(state):
    return dict(state.orders)


def probe_cargo(state):
    return set(state.onboard), set(state.delivered), state.payload


def probe_log(state):
    return list(state.log)


def neighbors(cell):
    return tuple((cell[0] + dx, cell[1] + dy) for dx, dy in DIRECTIONS)


def square(cell, radius):
    return tuple((x_coord, y_coord)
                 for x_coord in range(max(0, cell[0] - radius), min(SIZE, cell[0] + radius + 1))
                 for y_coord in range(max(0, cell[1] - radius), min(SIZE, cell[1] + radius + 1)))


def map_get(mapping, key):
    return mapping.get(key) is True


def map_has(mapping, key):
    return key in mapping


def map_missing_any(mapping, keys):
    return any(key not in mapping for key in keys)


def keys(mapping):
    return tuple(mapping)


def singleton(key):
    return {key: None}


def graph_expand(frontier, parents, known):
    expanded = dict(parents)
    following = []
    for cell in frontier:
        for adjacent in neighbors(cell):
            if known.get(adjacent) is True and adjacent not in expanded:
                expanded[adjacent] = cell
                following.append(adjacent)
    return tuple(following), expanded


def graph_frontier(graph):
    return graph[0]


def graph_parents(graph):
    return graph[1]


def graph_path(parents, start, target):
    if target not in parents:
        return None
    result = []
    cursor = target
    while cursor != start:
        result.append(cursor)
        cursor = parents[cursor]
    return tuple(reversed(result))


def parent_distance(parents, start, target):
    if target not in parents:
        return None
    distance = 0
    while target != start:
        distance += 1
        target = parents[target]
    return distance


def empty(value):
    return not value


def head(value):
    return value[0]


def tail(value):
    return value[1:]


def size(value):
    return len(value)


def item(value, key):
    return value[key]


def field(value, index):
    return value[index]


def pack(first, second):
    return first, second


def prepend(value, sequence):
    return (value, *sequence)


def difference(first, second):
    return tuple(value for value in first if value not in second)


def batches(remaining):
    return tuple(batch for length in range(1, len(remaining) + 1)
                 for batch in permutations(remaining, length))


def less(first, second):
    return first < second


def equal(first, second):
    return first == second


def add(first, second):
    return first + second


def sub(first, second):
    return first - second


def mul(first, second):
    return first * second


def mod(first, second):
    return first % second


def cell_delta(first, second):
    return first[0] - second[0], first[1] - second[1]


def manhattan(first, second):
    return abs(first[0] - second[0]) + abs(first[1] - second[1])


def sorted_items(mapping):
    return tuple(sorted(mapping.items()))


def sort(value):
    return tuple(sorted(value))


def to_list(value):
    return list(value)


def select_min(best, candidate):
    return candidate if best is None or candidate[0] < best[0] else best


def pair_first(value):
    return value[0]


def pair_second(value):
    return value[1]


def tuple4(first, second, third, fourth):
    return first, second, third, fourth


def is_none(value):
    return value is None


def none():
    return None


def empty_set():
    return frozenset()


def tuple8(first, second, third, fourth, fifth, sixth, seventh, eighth):
    return first, second, third, fourth, fifth, sixth, seventh, eighth


def decrement(value):
    return value - 1


def budget_empty(value):
    return value == 0


def all_in(first, second):
    return set(first) == set(second)


def member(value, collection):
    return value in collection


def set_add(collection, value):
    return frozenset((*collection, value))


def set_remove(collection, value):
    return frozenset(item for item in collection if item != value)


def append(sequence, value):
    return (*sequence, value)


def logical_and(first, second):
    return bool(first and second)


def logical_not(value):
    return not value


def list9(*values):
    return list(values)


def min_list(values):
    return min(values)
