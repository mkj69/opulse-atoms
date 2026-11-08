"""Fixed, local layer-zero graph operations and structural data access."""

from dataclasses import dataclass

from opulse.atoms.values import Bottom, Card, Unknown, encode


@dataclass(frozen=True)
class Plan:
    seed: int
    blocks: int
    width: int
    override_vertex: int = -1
    override_weight: int = -1
    bridges: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        size = self.blocks * self.width
        if (type(self.seed) is not int or self.seed < 0 or type(self.blocks) is not int
                or type(self.width) is not int or not 1 <= self.blocks <= 12
                or not 3 <= self.width <= 16 or type(self.override_vertex) is not int
                or type(self.override_weight) is not int
                or not ((self.override_vertex, self.override_weight) == (-1, -1)
                        or 0 <= self.override_vertex < size and 0 <= self.override_weight <= 40)
                or any(not (0 <= left < right < size and left // self.width != right // self.width)
                       for left, right in self.bridges)):
            raise ValueError("Bottom(range)")


@dataclass(frozen=True)
class State:
    plan: Plan
    available: int
    chosen: int = 0
    earned: int = 0


def vertices(mask):
    return tuple(index for index in range(mask.bit_length()) if mask & (1 << index))


def weight(plan, vertex):
    if not 0 <= vertex < plan.blocks * plan.width:
        return Bottom("range")
    if vertex == plan.override_vertex:
        return plan.override_weight
    return (11 * plan.seed + 17 * vertex + 3 * vertex * vertex) % 29 + 1


def adjacent(plan, vertex):
    if not 0 <= vertex < plan.blocks * plan.width:
        return Bottom("range")
    block, local = divmod(vertex, plan.width)
    mask = 0
    for peer in range(plan.width):
        if peer == local:
            continue
        left, right = sorted((local, peer))
        if (peer - local) % plan.width in (1, plan.width - 1) or (7 * left + 11 * right + 3 * block + plan.seed) % 5 <= 1:
            mask |= 1 << (block * plan.width + peer)
    for left, right in plan.bridges:
        if vertex == left:
            mask |= 1 << right
        if vertex == right:
            mask |= 1 << left
    return mask


def start(plan):
    return State(plan, (1 << (plan.blocks * plan.width)) - 1)


def take(state, vertex):
    if not state.available & (1 << vertex):
        return Bottom("unavailable")
    return State(state.plan, state.available & ~((1 << vertex) | adjacent(state.plan, vertex)),
                 state.chosen | (1 << vertex), state.earned + weight(state.plan, vertex))


def ban(state, vertex):
    if not state.available & (1 << vertex):
        return Bottom("unavailable")
    return State(state.plan, state.available & ~(1 << vertex), state.chosen, state.earned)


def priority(plan, available, vertex):
    return ((adjacent(plan, vertex) & available).bit_count(), weight(plan, vertex), -vertex)


def degree(plan, vertex, available):
    return (adjacent(plan, vertex) & available).bit_count()


def drop_lowest(mask):
    return mask & (mask - 1)


def lowest(mask):
    return (mask & -mask).bit_length() - 1 if mask else Bottom("empty")


def singleton(vertex):
    return 1 << vertex


def split_mid(items):
    midpoint = len(items) // 2
    return items[:midpoint], items[midpoint:]


def head(items):
    return items[0] if items else Bottom("empty")


def tail(items):
    return items[1:] if items else Bottom("empty")


def state_group(state, group):
    return State(state.plan, group)


def join_state(state, part):
    return State(state.plan, 0, state.chosen | part.chosen, state.earned + part.earned)


def done(state):
    return State(state.plan, 0, state.chosen, state.earned)


def legal(state):
    return (all(not adjacent(state.plan, vertex) & state.chosen for vertex in vertices(state.chosen))
            and sum(weight(state.plan, vertex) for vertex in vertices(state.chosen)) == state.earned)


def non_decreasing():
    return Bottom("non_decreasing_measure")


def empty_frontier():
    return Bottom("empty_frontier")


def outside_universe():
    return Bottom("outside_universe")


def first(pair):
    return pair[0]


def second(pair):
    return pair[1]


def pair(left, right):
    return left, right


def append(items, value):
    return (*items, value)


def concat(left, right):
    return (*left, *right)


def member(value, items):
    return value in items


def bound(state):
    return state.earned


def score(state):
    return state.earned


def chosen(state):
    return vertices(state.chosen)


def available(state):
    return state.available


def plan(state):
    return state.plan


def identity(value):
    return value


def union(left, right):
    return left | right


def intersect(left, right):
    return left & right


def difference(left, right):
    return left & ~right


def ascending(mask):
    return vertices(mask)


def length(items):
    return len(items)


def empty(items):
    return not items


def singleton_list(items):
    return len(items) == 1


def all_vertices(plan):
    return (1 << (plan.blocks * plan.width)) - 1


def popcount(mask):
    return mask.bit_count()


def add(left, right):
    return left + right


def le(left, right):
    return left <= right


def lt(left, right):
    return left < right


def eq(left, right):
    return left == right


def decrement(value):
    return value - 1 if value > 0 else Bottom("range")


def resource():
    return Unknown("resource")


def nonzero(mask):
    return mask != 0


def encode_value(value):
    if isinstance(value, Plan):
        return {"t": "Plan", "tag": "given", "f": [encode_value(item) for item in
                (value.seed, value.blocks, value.width, value.override_vertex,
                 value.override_weight, value.bridges)]}
    if isinstance(value, State):
        return {"t": "State", "tag": "given", "f": [encode_value(item) for item in
                (value.plan, value.available, value.chosen, value.earned)]}
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [encode_value(item) for item in value]}
    return encode(value)


def from_notation(value):
    if isinstance(value, tuple):
        return tuple(from_notation(item) for item in value)
    if not isinstance(value, Card):
        return value
    if value.sort == "Set":
        mask = 0
        for vertex in value.fields:
            if type(vertex) is not int or not 0 <= vertex < 192:
                raise ValueError("Bottom(range)")
            mask |= 1 << vertex
        return mask
    if value.sort == "Pair":
        return tuple(from_notation(item) for item in value.fields)
    if value.sort == "Plan":
        fields = tuple(from_notation(item) for item in value.fields)
        return Plan(*fields)
    if value.sort == "State":
        return State(*(from_notation(item) for item in value.fields))
    return value
