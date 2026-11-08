"""Pure, timestamped kitchen layer-zero operations."""

from itertools import pairwise

from opulse.atoms.values import Bottom, Card, Ok, Unknown

ITEMS = ("flour", "water", "egg", "milk", "dough", "batter", "bread", "cake", "custard", "dessert")
SHELF = {"dough": 3, "batter": 2, "custard": 4}
RECIPES = {
    "mix": ("mixer", 2, (("flour", 2), ("water", 1)), "dough"),
    "whisk": ("mixer", 1, (("flour", 1), ("egg", 1), ("milk", 1)), "batter"),
    "bake_bread": ("oven", 3, (("dough", 1),), "bread"),
    "bake_cake": ("oven", 2, (("batter", 1),), "cake"),
    "simmer": ("hob", 2, (("egg", 1), ("milk", 1)), "custard"),
    "plate": ("bench", 1, (("cake", 1), ("custard", 1)), "dessert"),
}
PRODUCED_AFTER = {output: duration for _, duration, _, output in RECIPES.values()}


def state(flour, water, egg, milk):
    amounts = (flour, water, egg, milk)
    if any(type(amount) is not int or not 0 <= amount <= 8 for amount in amounts):
        return Bottom("invalid")
    return Card("State", "state", (0, tuple(sorted((item, 0, amount) for item, amount in
                                                  zip(ITEMS, amounts) if amount)), ()))


def valid_state(value):
    if not isinstance(value, Card) or value.sort != "State" or value.tag != "state" or len(value.fields) != 3:
        return False
    time, lots, jobs = value.fields
    if type(time) is not int or not 0 <= time <= 24 or not isinstance(lots, tuple) or not isinstance(jobs, tuple):
        return False
    if not all(isinstance(lot, tuple) and len(lot) == 3 and
               type(lot[0]) is str and lot[0] in ITEMS and
               type(lot[1]) is int and 0 <= lot[1] <= time and
               type(lot[2]) is int and
               (lot[1] == 0 and lot[2] <= 8 if lot[0] in ITEMS[:4]
                else lot[1] >= PRODUCED_AFTER[lot[0]] and lot[2] == 1) and
               lot[2] > 0 and
               (lot[0] not in SHELF or time - lot[1] <= SHELF[lot[0]]) for lot in lots):
        return False
    if not all(isinstance(job, tuple) and len(job) == 2 and
               type(job[0]) is str and job[0] in RECIPES and
               type(job[1]) is int and RECIPES[job[0]][1] <= job[1] and
               time < job[1] <= time + RECIPES[job[0]][1]
               for job in jobs):
        return False
    return (lots == tuple(sorted(lots)) and jobs == tuple(sorted(jobs)) and
            len({RECIPES[recipe][0] for recipe, _ in jobs}) == len(jobs) and
            len({(item, born) for item, born, _ in lots}) == len(lots))


def valid_order(value):
    if not isinstance(value, Card) or value.sort != "Order" or value.tag != "val" or len(value.fields) != 1:
        return False
    record = value.fields[0]
    return (isinstance(record, Card) and record.sort == "OrderData" and
            record.tag == "order" and len(record.fields) == 4 and
            all(type(part) is int and 0 <= part <= (12 if index == 3 else 8)
                for index, part in enumerate(record.fields)))


def valid_plan(value):
    if not isinstance(value, Card) or value.sort != "Plan" or value.tag != "val" or len(value.fields) != 1:
        return False
    record = value.fields[0]
    if not isinstance(record, Card) or record.sort != "PlanData" or record.tag != "record" or len(record.fields) != 3:
        return False
    start, slots, end = record.fields
    if not valid_state(start) or not valid_state(end) or not isinstance(slots, tuple) or len(slots) > 12:
        return False
    current = start
    for actions in slots:
        if (not isinstance(actions, tuple) or not all(type(recipe) is str and recipe in RECIPES
                                                      for recipe in actions) or
                actions != tuple(sorted(set(actions))) or
                len({RECIPES[recipe][0] for recipe in actions}) != len(actions)):
            return False
        for recipe in actions:
            current = _start(current, recipe)
            if isinstance(current, Bottom):
                return False
        current = tick(current)
        if isinstance(current, Bottom):
            return False
    return current == end


def valid_card(value):
    if value.sort == "State":
        return valid_state(value)
    if value.sort == "Plan":
        return valid_plan(value)
    if value.sort == "Order":
        return valid_order(value)
    if value.sort == "PlanData":
        return (value.tag == "record" and len(value.fields) == 3 and
                valid_state(value.fields[0]) and isinstance(value.fields[1], tuple) and
                len(value.fields[1]) <= 12 and
                all(isinstance(slot, tuple) and
                    all(type(recipe) is str and recipe in RECIPES for recipe in slot)
                    for slot in value.fields[1]) and valid_state(value.fields[2]))
    if value.sort == "OrderData":
        return (value.tag == "order" and len(value.fields) == 4 and
                all(type(part) is int for part in value.fields))
    if value.sort == "Query":
        return (value.tag == "query" and len(value.fields) == 2 and
                valid_state(value.fields[0]) and valid_order(value.fields[1]))
    return value.sort == "bool" and value.tag in ("true", "false") and not value.fields


def valid_input(value):
    if isinstance(value, Card):
        return valid_card(value)
    if isinstance(value, (tuple, list, frozenset, set)):
        return all(valid_input(item) for item in value)
    if isinstance(value, dict):
        return all(valid_input(item) for pair in value.items() for item in pair)
    return True


def to_card(value):
    if not valid_state(value):
        return Bottom("invalid")
    return value


def from_card(value):
    return to_card(value)


def stock(value):
    if not valid_state(value):
        return Bottom("invalid")
    return tuple(sum(qty for name, _, qty in value.fields[1] if name == item) for item in ITEMS)


def busy(value):
    if not valid_state(value):
        return Bottom("invalid")
    return tuple(sorted(RECIPES[recipe][0] for recipe, _ in value.fields[2]))


def _start(value, recipe):
    if not valid_state(value):
        return Bottom("invalid")
    station, duration, consumed, _ = RECIPES[recipe]
    if station in busy(value):
        return Bottom("station")
    time, lots, jobs = value.fields
    remaining = list(lots)
    for item, amount in consumed:
        if sum(qty for name, _, qty in remaining if name == item) < amount:
            return Bottom("stock")
        for index, (name, born, qty) in sorted(enumerate(remaining), key=lambda entry: (entry[1][1], entry[0])):
            if name != item or not amount:
                continue
            taken = min(qty, amount)
            remaining[index] = (name, born, qty - taken)
            amount -= taken
    return Card("State", "state", (time, tuple(sorted(lot for lot in remaining if lot[2])),
                                    tuple(sorted((*jobs, (recipe, time + duration))))))


def mix(value):
    return _start(value, "mix")


def whisk(value):
    return _start(value, "whisk")


def bake_bread(value):
    return _start(value, "bake_bread")


def bake_cake(value):
    return _start(value, "bake_cake")


def simmer(value):
    return _start(value, "simmer")


def plate(value):
    return _start(value, "plate")


def tick(value):
    if not valid_state(value):
        return Bottom("invalid")
    time, lots, jobs = value.fields
    if time == 24:
        return Bottom("horizon")
    now = time + 1
    remaining = list(lots)
    for recipe, finish in jobs:
        if finish == now:
            remaining.append((RECIPES[recipe][3], now, 1))
    return Card("State", "state", (now,
        tuple(sorted(lot for lot in remaining if lot[0] not in SHELF or now - lot[1] <= SHELF[lot[0]])),
        tuple((recipe, finish) for recipe, finish in jobs if finish > now)))


def empty(items):
    return not items


def head(items):
    return items[0] if items else Bottom("invalid")


def tail(items):
    return items[1:] if items else Bottom("invalid")


def cons(value, items):
    return (value, *items)


def append(items, value):
    return (*items, value)


def length(items):
    return len(items)


def item(items, index):
    return items[index] if isinstance(items, tuple) and type(index) is int and 0 <= index < len(items) else Bottom("invalid")


def field(value, index):
    if isinstance(value, Card) and not valid_card(value):
        return Bottom("invalid")
    fields = value.fields if isinstance(value, Card) else value
    return item(fields, index)


def eq(left, right):
    if not valid_input(left) or not valid_input(right):
        return Bottom("invalid")
    return left == right


def lt(left, right):
    if not valid_input(left) or not valid_input(right):
        return Bottom("invalid")
    return left < right


def le(left, right):
    if not valid_input(left) or not valid_input(right):
        return Bottom("invalid")
    return left <= right


def add(left, right):
    return left + right


def sub(left, right):
    return left - right


def mul(left, right):
    return left * right


def seq_pair(left, right):
    return left, right


def seq_triple(first, second, third):
    return first, second, third


def query(value, order):
    if not valid_state(value) or not valid_order(order):
        return Bottom("invalid")
    return Card("Query", "query", (value, order))


def increasing(items):
    return isinstance(items, tuple) and all(first < second for first, second in pairwise(items))


def optional(outcome):
    if isinstance(outcome, Unknown):
        return outcome
    return (outcome.value,) if isinstance(outcome, Ok) else ()
