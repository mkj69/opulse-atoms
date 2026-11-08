"""Exact public channels, sealed truth, and generic finite primitives."""

from fractions import Fraction
from functools import wraps

from opulse.atoms.values import Bottom, Card, boolean

CARDS = ("R", "B")
LAMPS = ("red", "blue")
MODES = ("A", "B")


def rational(value):
    try:
        number = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return Bottom("invalid")
    return Card("Rational", "fraction", (number.numerator, number.denominator))


def _fraction(value):
    if type(value) is int:
        return Fraction(value)
    if (isinstance(value, Card) and value.sort == "Rational" and value.tag == "fraction"
            and len(value.fields) == 2 and all(type(part) is int for part in value.fields)
            and value.fields[1] > 0):
        return Fraction(*value.fields)
    raise ValueError("not a rational")


def fraction(value):
    try:
        return _fraction(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return Bottom("invalid")


def valid(value):
    if not isinstance(value, Card):
        return False
    fields = value.fields
    if value.sort == "Rational":
        return isinstance(fraction(value), Fraction)
    if value.sort == "BeliefPair":
        return value.tag == "pair" and len(fields) == 2 and all(valid(item) and item.sort == "Rational" for item in fields)
    if value.sort == "Belief":
        return (value.tag == "val" and len(fields) == 1 and valid(fields[0])
                and fields[0].sort == "BeliefPair" and all(
                    0 <= fraction(item) <= 1 and item == rational(fraction(item)) for item in fields[0].fields)
                and sum((fraction(item) for item in fields[0].fields), Fraction(0)) == 1)
    if value.sort == "PolicyNode":
        return (value.tag == "Leaf" and len(fields) == 1 and type(fields[0]) is str and fields[0] in CARDS
                or value.tag == "Ask" and len(fields) == 3 and type(fields[0]) is str and fields[0] in MODES
                and all(valid(child) and child.sort == "PolicyNode" for child in fields[1:]))
    if value.sort == "Policy":
        return value.tag == "val" and len(fields) == 1 and valid(fields[0]) and fields[0].sort == "PolicyNode"
    if value.sort == "Step":
        return (value.tag == "step" and len(fields) == 2 and type(fields[0]) is str
                and fields[0] in MODES and type(fields[1]) is str and fields[1] in LAMPS)
    if value.sort in ("History", "Actions", "Modes", "Lamps", "Branches"):
        return (value.tag == "list" and all(
            valid(item) and item.sort == ("Step" if value.sort == "History" else "Branch")
            if value.sort in ("History", "Branches") else type(item) is str
            and item in (CARDS if value.sort == "Actions" else MODES if value.sort == "Modes" else LAMPS)
            for item in fields))
    if value.sort == "Truth":
        return (value.tag == "sealed" and len(fields) == 3 and type(fields[0]) is str and fields[0] in CARDS
                and valid(fields[1]) and fields[1].sort == "History" and valid(fields[2]) and fields[2].sort == "Actions")
    if value.sort == "ReceiverView":
        return (value.tag == "view" and len(fields) == 2 and valid(fields[0]) and fields[0].sort == "History"
                and valid(fields[1]) and fields[1].sort == "Actions")
    if value.sort == "DistLamp":
        return (value.tag == "dist" and len(fields) == 2 and all(valid(item) and item.sort == "Rational" for item in fields)
                and all(0 <= fraction(item) <= 1 for item in fields)
                and sum((fraction(item) for item in fields), Fraction(0)) == 1)
    if value.sort == "Branch":
        return (value.tag == "branch" and len(fields) == 2 and valid(fields[0]) and fields[0].sort == "Truth"
                and valid(fields[1]) and fields[1].sort == "Rational" and 0 <= fraction(fields[1]) <= 1)
    if value.sort == "DistTruth":
        return value.tag == "dist" and all(valid(item) and item.sort == "Branch" for item in fields)
    if value.sort == "bool":
        return value.tag in ("true", "false") and not fields
    return False


def pair(red, blue):
    if not all(isinstance(item, Card) and item.sort == "Rational" and valid(item) for item in (red, blue)):
        return Bottom("invalid")
    return Card("BeliefPair", "pair", (red, blue))


def pair_r(value):
    return value.fields[0] if isinstance(value, Card) and value.sort == "BeliefPair" else Bottom("invalid")


def pair_b(value):
    return value.fields[1] if isinstance(value, Card) and value.sort == "BeliefPair" else Bottom("invalid")


def ratio(numerator, denominator):
    if type(numerator) is not int or type(denominator) is not int or denominator == 0:
        return Bottom("invalid")
    return rational(Fraction(numerator, denominator))


def add(left, right):
    try:
        return rational(fraction(left) + fraction(right))
    except (ValueError, TypeError, ZeroDivisionError):
        return Bottom("invalid")


def sub(left, right):
    try:
        return rational(fraction(left) - fraction(right))
    except (ValueError, TypeError, ZeroDivisionError):
        return Bottom("invalid")


def mul(left, right):
    try:
        return rational(fraction(left) * fraction(right))
    except (ValueError, TypeError, ZeroDivisionError):
        return Bottom("invalid")


def div(left, right):
    try:
        return rational(fraction(left) / fraction(right))
    except (ValueError, TypeError, ZeroDivisionError):
        return Bottom("impossible")


def lt(left, right):
    try:
        return boolean(fraction(left) < fraction(right))
    except (ValueError, TypeError):
        return Bottom("invalid")


def le(left, right):
    try:
        return boolean(fraction(left) <= fraction(right))
    except (ValueError, TypeError):
        return Bottom("invalid")


def eq(left, right):
    if (isinstance(left, Card) and isinstance(right, Card)
            and left.sort == right.sort == "Rational"):
        try:
            return boolean(fraction(left) == fraction(right))
        except ValueError:
            return Bottom("invalid")
    return boolean(left == right)


def less_int(left, right):
    return boolean(type(left) is int and type(right) is int and left < right)


def decrease(value, amount):
    if type(value) is not int or type(amount) is not int or value < amount:
        return Bottom("budget")
    return value - amount


def fail(reason):
    return Bottom(reason) if reason in ("unpaired", "budget", "invalid") else Bottom("invalid")


def channel(mode, card):
    if mode not in MODES or card not in CARDS:
        return Bottom("invalid")
    red = {("A", "R"): Fraction(1), ("A", "B"): Fraction(1, 2),
           ("B", "R"): Fraction(1, 4), ("B", "B"): Fraction(3, 4)}[mode, card]
    return Card("DistLamp", "dist", (rational(red), rational(1 - red)))


def weight(distribution, lamp):
    if not isinstance(distribution, Card) or distribution.sort != "DistLamp" or lamp not in LAMPS:
        return Bottom("invalid")
    return distribution.fields[LAMPS.index(lamp)]


def mode_cost(mode):
    return {"A": 3, "B": 1}.get(mode, Bottom("invalid")) if type(mode) is str else Bottom("invalid")


def state(card, history=(), actions=()):
    result = Card("Truth", "sealed", (card, Card("History", "list", tuple(
        Card("Step", "step", (mode, lamp)) for mode, lamp in history)), Card("Actions", "list", tuple(actions))))
    return result if valid(result) else Bottom("invalid")


def receiver(truth):
    if not isinstance(truth, Card) or truth.sort != "Truth":
        return Bottom("invalid")
    return Card("ReceiverView", "view", truth.fields[1:])


def judge(truth, choice):
    if not isinstance(truth, Card) or truth.sort != "Truth" or choice not in CARDS:
        return Bottom("invalid")
    return boolean(truth.fields[0] == choice)


def signal(truth, mode):
    if not isinstance(truth, Card) or truth.sort != "Truth" or mode not in MODES:
        return Bottom("invalid")
    distribution = channel(mode, truth.fields[0])
    return Card("DistTruth", "dist", tuple(Card("Branch", "branch", (
        state(truth.fields[0], tuple(step.fields for step in truth.fields[1].fields) + ((mode, lamp),),
              truth.fields[2].fields), weight(distribution, lamp))) for lamp in LAMPS
        if fraction(weight(distribution, lamp))))


def guess(view, choice):
    if not isinstance(view, Card) or view.sort != "ReceiverView" or choice not in CARDS:
        return Bottom("invalid")
    return Card("ReceiverView", "view", (view.fields[0], Card("Actions", "list", (*view.fields[1].fields, choice))))


def history(view):
    return view.fields[0] if isinstance(view, Card) and view.sort == "ReceiverView" else Bottom("invalid")


def step_lamp(step):
    return step.fields[1] if isinstance(step, Card) and step.sort == "Step" else Bottom("invalid")


def empty(items):
    return boolean(not items.fields) if isinstance(items, Card) and items.tag == "list" else Bottom("invalid")


def head(items):
    return items.fields[0] if isinstance(items, Card) and items.tag == "list" and items.fields else Bottom("empty")


def tail(items):
    return Card(items.sort, "list", items.fields[1:]) if isinstance(items, Card) and items.tag == "list" and items.fields else Bottom("empty")


def prepend(item, items):
    return Card(items.sort, "list", (item, *items.fields)) if isinstance(items, Card) and items.tag == "list" else Bottom("invalid")


def reverse(items):
    return Card(items.sort, "list", tuple(reversed(items.fields))) if isinstance(items, Card) and items.tag == "list" else Bottom("invalid")


def size(items):
    return len(items.fields) if isinstance(items, Card) and items.tag == "list" else Bottom("invalid")


def dist_items(distribution):
    return Card("Branches", "list", distribution.fields) if isinstance(distribution, Card) and distribution.tag == "dist" else Bottom("invalid")


def dist_make(items):
    return Card("DistTruth", "dist", items.fields) if isinstance(items, Card) and items.sort == "Branches" else Bottom("invalid")


def branch(value, probability):
    if not valid(value) or value.sort != "Truth":
        return Bottom("invalid")
    if not isinstance(probability, Card) or probability.sort != "Rational" or not valid(probability):
        return Bottom("invalid")
    if not 0 <= fraction(probability) <= 1:
        return Bottom("invalid")
    return Card("Branch", "branch", (value, probability))


def branch_value(item):
    return item.fields[0] if isinstance(item, Card) and item.sort == "Branch" else Bottom("invalid")


def branch_weight(item):
    return item.fields[1] if isinstance(item, Card) and item.sort == "Branch" else Bottom("invalid")


def singleton(value):
    return Card("DistTruth", "dist", (branch(value, rational(1)),))


def duplicate(value):
    return Card("DistTruth", "dist", (branch(value, rational(Fraction(1, 2))),
                                      branch(value, rational(Fraction(1, 2)))))


def node_leaf(choice):
    return Card("PolicyNode", "Leaf", (choice,)) if choice in CARDS else Bottom("invalid")


def node_ask(mode, red, blue):
    if mode not in MODES or any(not isinstance(child, Card) or child.sort != "PolicyNode"
                                for child in (red, blue)):
        return Bottom("invalid")
    return Card("PolicyNode", "Ask", (mode, red, blue))


def node_is_ask(node):
    return boolean(isinstance(node, Card) and node.sort == "PolicyNode" and node.tag == "Ask")


def node_valid(node):
    if not isinstance(node, Card) or node.sort != "PolicyNode":
        return boolean(False)
    if node.tag == "Leaf":
        return boolean(len(node.fields) == 1 and node.fields[0] in CARDS)
    return boolean(node.tag == "Ask" and len(node.fields) == 3 and node.fields[0] in MODES
                   and all(node_valid(child) == boolean(True) for child in node.fields[1:]))


def node_choice(node):
    return node.fields[0] if isinstance(node, Card) and node.sort == "PolicyNode" and node.tag == "Leaf" else Bottom("invalid")


def node_mode(node):
    return node.fields[0] if isinstance(node, Card) and node.sort == "PolicyNode" and node.tag == "Ask" else Bottom("invalid")


def node_red(node):
    return node.fields[1] if isinstance(node, Card) and node.sort == "PolicyNode" and node.tag == "Ask" else Bottom("invalid")


def node_blue(node):
    return node.fields[2] if isinstance(node, Card) and node.sort == "PolicyNode" and node.tag == "Ask" else Bottom("invalid")


_ORIGINALS = {}


def _guard(name):
    @wraps(_ORIGINALS[name])
    def checked(*args, **kwargs):
        def invalid(item):
            if isinstance(item, Card):
                return not valid(item)
            if isinstance(item, (tuple, list)):
                return any(invalid(child) for child in item)
            return False

        if any(invalid(item) for item in (*args, *kwargs.values())):
            return Bottom("invalid")
        return _ORIGINALS[name](*args, **kwargs)

    return checked


for _name, _function in tuple(globals().items()):
    if (_name not in ("valid", "fraction") and not _name.startswith("_")
            and callable(_function) and getattr(_function, "__module__", None) == __name__):
        _ORIGINALS[_name] = _function
        globals()[_name] = _guard(_name)
