"""Finite, exact reference semantics for the Opulse kitchen depth pass.

Run ``python3 out/kitchen.py`` to check every published example and task.
Time is integral; a job launched at t finishes at t + duration. Perishables
can be consumed iff t - born <= shelf_life, with FIFO consumption.
"""

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path
import json


ITEMS = ("flour", "water", "egg", "milk", "dough", "batter", "bread", "cake", "custard", "dessert")
SHELF = {"dough": 3, "batter": 2, "custard": 4}
# (station, duration, consumed, produced); a station holds at most one job.
RECIPES = {
    "mix": ("mixer", 2, (("flour", 2), ("water", 1)), "dough"),
    "whisk": ("mixer", 1, (("flour", 1), ("egg", 1), ("milk", 1)), "batter"),
    "bake_bread": ("oven", 3, (("dough", 1),), "bread"),
    "bake_cake": ("oven", 2, (("batter", 1),), "cake"),
    "simmer": ("hob", 2, (("egg", 1), ("milk", 1)), "custard"),
    "plate": ("bench", 1, (("cake", 1), ("custard", 1)), "dessert"),
}
RECIPE_NAMES = tuple(sorted(RECIPES))


@dataclass(frozen=True)
class Ok:
    value: object


@dataclass(frozen=True)
class Bottom:
    reason: str


@dataclass(frozen=True)
class State:
    time: int
    lots: tuple  # (item, born, quantity), canonical order
    jobs: tuple = ()  # (recipe, finish), canonical order

    def __post_init__(self):
        assert 0 <= self.time <= 24
        assert self.lots == tuple(sorted(self.lots))
        assert all(item in ITEMS and qty > 0 and 0 <= born <= self.time
                   and (item not in SHELF or self.time - born <= SHELF[item])
                   for item, born, qty in self.lots)
        assert self.jobs == tuple(sorted(self.jobs))
        assert all(recipe in RECIPES and finish > self.time for recipe, finish in self.jobs)
        assert len({RECIPES[recipe][0] for recipe, _ in self.jobs}) == len(self.jobs)


@dataclass(frozen=True)
class Plan:
    start: State
    slots: tuple  # each slot is a tuple of recipe names, in canonical order
    end: State


@dataclass(frozen=True)
class Order:
    bread: int
    cake: int
    dessert: int
    deadline: int

    def __post_init__(self):
        assert all(0 <= n <= 8 for n in (self.bread, self.cake, self.dessert))
        assert 0 <= self.deadline <= 12


@dataclass(frozen=True)
class Query:
    state: State
    order: Order


def state(flour, water, egg, milk):
    """Initial State at t=0; all four raw materials are nonperishable."""
    quantities = (flour, water, egg, milk)
    assert all(isinstance(qty, int) and 0 <= qty <= 8 for qty in quantities)
    return State(0, tuple(sorted((item, 0, qty) for item, qty in zip(ITEMS, quantities) if qty)))


def stock(s):
    return tuple(sum(qty for name, _, qty in s.lots if name == item) for item in ITEMS)


def busy(s):
    return tuple(sorted(RECIPES[recipe][0] for recipe, _ in s.jobs))


def start(s, recipe):
    station, duration, consumes, _ = RECIPES[recipe]
    if station in busy(s):
        return Bottom("station")
    remaining = list(s.lots)
    for item, amount in consumes:
        if sum(qty for name, _, qty in remaining if name == item) < amount:
            return Bottom("stock")
        for index, (name, born, qty) in sorted(enumerate(remaining), key=lambda x: (x[1][1], x[0])):
            if name != item or amount == 0:
                continue
            taken = min(qty, amount)
            remaining[index] = (name, born, qty - taken)
            amount -= taken
    return Ok(State(s.time, tuple(sorted(lot for lot in remaining if lot[2])),
                    tuple(sorted((*s.jobs, (recipe, s.time + duration))))))


def tick(s):
    now = s.time + 1
    lots = list(s.lots)
    for recipe, finish in s.jobs:
        if finish == now:
            item = RECIPES[recipe][3]
            lots.append((item, now, 1))
    kept = tuple(sorted(lot for lot in lots if lot[0] not in SHELF or now - lot[1] <= SHELF[lot[0]]))
    return Ok(State(now, kept, tuple((recipe, finish) for recipe, finish in s.jobs if finish > now)))


def seq(actions, s):
    for action in actions:
        result = start(s, action)
        if isinstance(result, Bottom):
            return result
        s = result.value
    return Ok(s)


def slot(actions, s):
    if tuple(actions) != tuple(sorted(set(actions))):
        return Bottom("duplicate_or_unsorted")
    result = seq(actions, s)
    return result if isinstance(result, Bottom) else tick(result.value)


def make_plan(s, slots):
    if len(slots) > 12:
        return Bottom("horizon")
    end = s
    for actions in slots:
        result = slot(actions, end)
        if isinstance(result, Bottom):
            return result
        end = result.value
    return Ok(Plan(s, tuple(tuple(actions) for actions in slots), end))


def peak(plan):
    current = plan.start
    maximum = len(current.jobs)
    for actions in plan.slots:
        result = seq(actions, current)
        assert isinstance(result, Ok)
        maximum = max(maximum, len(result.value.jobs))
        current = tick(result.value).value
    return maximum


def choices():
    for width in range(len(RECIPE_NAMES) + 1):
        for actions in combinations(RECIPE_NAMES, width):
            if len({RECIPES[name][0] for name in actions}) == len(actions):
                yield actions


CHOICES = tuple(choices())


@lru_cache(maxsize=16)
def reach(s, horizon):
    """One fewest-starts, then lexical witness per full state at exact horizon.

    Only equal full states (time, birth-dated lots and in-flight jobs) merge;
    they have identical possible futures. The list is finite, not sampled.
    """
    if not 0 <= horizon <= 12 or s.time + horizon > 24:
        return Bottom("horizon")
    frontier = {s: ()}
    for _ in range(horizon):
        following = {}
        for current, slots in frontier.items():
            for actions in CHOICES:
                result = slot(actions, current)
                if isinstance(result, Ok):
                    candidate = slots + (actions,)
                    previous = following.get(result.value)
                    candidate_key = (sum(map(len, candidate)), candidate)
                    if previous is None or candidate_key < (sum(map(len, previous)), previous):
                        following[result.value] = candidate
        frontier = following
    return tuple(Plan(s, slots, final) for final, slots in
                 sorted(frontier.items(), key=lambda entry: entry[1]))


def yield_of(plan):
    counts = dict(zip(ITEMS, stock(plan.end)))
    return (counts["bread"], counts["cake"], counts["dessert"])


def meets(plan, order):
    return (plan.end.time <= order.deadline and
            all(actual >= needed for actual, needed in zip(yield_of(plan),
                (order.bread, order.cake, order.dessert))))


def filter_plans(predicate, plans, order):
    return tuple(plan for plan in plans if predicate(plan, order))


def earliest(query):
    for horizon in range(max(0, query.order.deadline - query.state.time + 1)):
        if filter_plans(meets, reach(query.state, horizon), query.order):
            return horizon + query.state.time
    return Bottom("no_plan")


def score(plan, order):
    assert meets(plan, order)
    return (plan.end.time, sum(len(actions) for actions in plan.slots), plan.slots)


def best(metric, plans, order):
    if not plans:
        return Bottom("no_plan")
    return min(plans, key=lambda plan: metric(plan, order))


def solve(s, order):
    when = earliest(Query(s, order))
    if isinstance(when, Bottom):
        return when
    return best(score, filter_plans(meets, reach(s, when - s.time), order), order)


def min_flour(query):
    baseline = stock(query.state)
    if query.state.time != 0 or query.state.jobs or any(item in SHELF for item, _, _ in query.state.lots):
        return Bottom("not_raw_initial_state")
    for flour in range(9):
        candidate = state(flour, baseline[1], baseline[2], baseline[3])
        if candidate.time <= query.order.deadline and filter_plans(
                meets, reach(candidate, query.order.deadline - candidate.time), query.order):
            return flour
    return Bottom("no_plan")


def render(value):
    if isinstance(value, Ok):
        return render(value.value)
    if isinstance(value, Bottom):
        return f"Bottom<{value.reason}>"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, State):
        if value.jobs or value.time or any(item in SHELF for item, _, _ in value.lots):
            return (f"State<{value.time}, List<{', '.join(render(lot) for lot in value.lots)}>, "
                    f"List<{', '.join(render(job) for job in value.jobs)}> >").replace('> >', '>>')
        counts = stock(value)
        return f"State<{', '.join(str(counts[index]) for index in range(4))}>"
    if isinstance(value, Plan):
        return f"Plan<{render(value.start)}, {render(value.slots)}>"
    if isinstance(value, Order):
        return f"Order<{value.bread}, {value.cake}, {value.dessert}, {value.deadline}>"
    if isinstance(value, Query):
        return f"Query<{render(value.state)}, {render(value.order)}>"
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return f"List<{', '.join(render(entry) for entry in value)}>"
    return str(value)


def evaluate(expression):
    """Parse the ASCII subset actually used in the published examples."""
    import re
    tokens = re.findall(r"@[a-z_]+|\?[a-z_]+|[A-Za-z_][A-Za-z_0-9]*|\d+|[<>()\[\]{},]", expression)
    assert ''.join(tokens) == re.sub(r'\s+', '', expression), expression
    position = 0

    def accept(token):
        nonlocal position
        if position < len(tokens) and tokens[position] == token:
            position += 1
            return True
        return False

    def group(opening, closing, recipe_names=False):
        assert accept(opening)
        entries = []
        if not accept(closing):
            entries.append(take_recipe() if recipe_names else parse())
            while accept(','):
                entries.append(take_recipe() if recipe_names else parse())
            assert accept(closing)
        return entries

    def take_recipe():
        nonlocal position
        name = tokens[position]
        assert name in RECIPES
        position += 1
        return name

    operations = {**{name: (lambda current, recipe=name: start(current, recipe)) for name in RECIPES},
                  'tick': tick, 'reach': reach, 'meets': meets,
                  'solve': solve, 'score': score}
    observations = {'stock': stock, 'busy': busy, 'peak': peak, 'yield': yield_of,
                    'earliest': earliest, 'min_flour': min_flour}
    combinators = {'seq': seq, 'slot': slot, 'filter': filter_plans, 'best': best}

    def parse():
        nonlocal position
        token = tokens[position]
        position += 1
        if token.isdigit():
            return int(token)
        if token == 'List':
            return tuple(group('<', '>'))
        if token == 'State':
            parts = group('<', '>')
            return state(*parts) if len(parts) == 4 else State(parts[0], parts[1], parts[2])
        if token == 'Order':
            return Order(*group('<', '>'))
        if token == 'Query':
            return Query(*group('<', '>'))
        if token == 'Plan':
            result = make_plan(*group('<', '>'))
            return result if isinstance(result, Bottom) else result.value
        if token.startswith('@'):
            name = token[1:]
            names = group('[', ']', recipe_names=name in ('seq', 'slot'))
            arguments = group('(', ')')
            if name in ('seq', 'slot'):
                return combinators[name](names, *arguments)
            assert len(names) == 1
            return combinators[name](names[0], *arguments)
        if token.startswith('?'):
            return observations[token[1:]](*group('{', '}'))
        if token in operations and accept('('):
            position -= 1
            return operations[token](*group('(', ')'))
        if token in operations:
            return token if token in RECIPES else operations[token]
        if token in ITEMS:
            return token
        raise ValueError(f'Unknown token: {token}')

    result = parse()
    assert position == len(tokens), (expression, tokens[position:])
    return result


def check():
    data = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    assert data['id'] == 'kitchen' and len(data['tower']) == 12 and len(data['showcase']) == 3
    assert {row['kind'] for row in data['tower']} == {'object', 'operation', 'combinator', 'observation'}
    for number, row in enumerate(data['tower'], 1):
        assert row['layer'] == number and row['decl'].endswith(f'L{number}')
        actual = render(evaluate(row['example']))
        assert actual == row['value'], (number, actual, row['value'])
    for row in data['showcase']:
        import re
        expressions = re.findall(r'`([^`]+)`', row['prompt'])
        assert len(expressions) == 1
        actual = render(evaluate(expressions[0]))
        assert actual == row['answer'], (row['angle'], actual, row['answer'])
    assert render(slot(('mix', 'whisk'), state(4, 2, 2, 2))) == 'Bottom<station>'
    assert render(slot(('bake_bread',), state(4, 2, 2, 2))) == 'Bottom<stock>'
    assert render(make_plan(state(2, 1, 0, 0), (('bake_bread',),))) == 'Bottom<stock>'
    expired = make_plan(state(2, 1, 0, 0), (('mix',),) + ((),) * 6)
    assert isinstance(expired, Ok) and stock(expired.value.end)[4] == 0
    intermediate = slot(('mix',), state(2, 1, 0, 0)).value
    assert evaluate(render(intermediate)) == intermediate
    assert render(evaluate('?stock{State<2,1,0,0>}')) == 'List<2, 1, 0, 0, 0, 0, 0, 0, 0, 0>'
    assert render(evaluate('?busy{State<2,1,0,0>}')) == 'List<>'
    print('OK')


if __name__ == '__main__':
    check()
