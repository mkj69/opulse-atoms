"""Bounded public primitives for idealized second-resolution schedules."""

from math import gcd

from opulse.atoms.values import Bottom, Card, Ok, Unknown

LIMIT = 10**120 - 1


def bounded(value):
    return value if type(value) is int and abs(value) <= LIMIT else Bottom("range")


def bounded_pair(left, right):
    return not isinstance(bounded(left), Bottom) and not isinstance(bounded(right), Bottom)


def add(left, right):
    return bounded(left + right) if bounded_pair(left, right) else Bottom("range")


def sub(left, right):
    return add(left, -right) if type(right) is int else Bottom("range")


def mul(left, right):
    return bounded(left * right) if bounded_pair(left, right) else Bottom("range")


def mul_mod(left, right, modulus):
    if not bounded_pair(left, right) or isinstance(bounded(modulus), Bottom):
        return Bottom("range")
    return left * right % modulus if modulus > 0 else Bottom("period")


def mod(left, right):
    if not bounded_pair(left, right):
        return Bottom("range")
    return left % right if right > 0 else Bottom("period")


def mod_sub(left, right, modulus):
    if not bounded_pair(left, right) or isinstance(bounded(modulus), Bottom):
        return Bottom("range")
    return (left - right) % modulus if modulus > 0 else Bottom("period")


def offset_fits(lo, offset, hi):
    if not bounded_pair(lo, offset) or isinstance(bounded(hi), Bottom):
        return Bottom("range")
    return lo + offset <= hi


def div_floor(left, right):
    if not bounded_pair(left, right):
        return Bottom("range")
    return left // right if right > 0 else Bottom("period")


def egcd(left, right):
    if not bounded_pair(left, right):
        return Bottom("range")
    old_remainder, remainder = left, right
    old_x, x, old_y, y = 1, 0, 0, 1
    while remainder:
        quotient = old_remainder // remainder
        old_remainder, remainder = remainder, old_remainder - quotient * remainder
        old_x, x = x, old_x - quotient * x
        old_y, y = y, old_y - quotient * y
    if old_remainder < 0:
        old_remainder, old_x, old_y = -old_remainder, -old_x, -old_y
    return (old_remainder, old_x, old_y)


def le(left, right):
    return left <= right if bounded_pair(left, right) else Bottom("range")


def lt(left, right):
    return left < right if bounded_pair(left, right) else Bottom("range")


def eq(left, right):
    return type(left) is type(right) and left == right


def list_length(items):
    return len(items) if isinstance(items, tuple) and len(items) <= 4096 else Bottom("range")


def is_empty(items):
    return not items if isinstance(items, tuple) else Bottom("type")


def cons(item, items):
    return (item, *items) if isinstance(items, tuple) and len(items) < 4096 else Bottom("range")


def head(items):
    return items[0] if isinstance(items, tuple) and items else Bottom("empty")


def tail(items):
    return items[1:] if isinstance(items, tuple) and items else Bottom("empty")


def list_of(*items):
    return tuple(items)


def cycle_raw(residue, period):
    if isinstance(check := bounded(residue), Bottom):
        return check
    if isinstance(check := bounded(period), Bottom):
        return check
    return Card("CycleRaw", "val", (residue, period))


def plan_raw(cycles):
    return Card("PlanRaw", "val", (cycles,)) if isinstance(cycles, tuple) else Bottom("type")


def window_raw(plan, lo, hi, compiled):
    if any(isinstance(bounded(value), Bottom) for value in (lo, hi)):
        return Bottom("range")
    return Card("WindowRaw", "val", (plan, lo, hi, compiled))


def band(lo, hi):
    if any(isinstance(bounded(value), Bottom) for value in (lo, hi)):
        return Bottom("range")
    return Card("Band", "val", (lo, hi)) if lo <= hi else Bottom("band_order")


def blackout_raw(window, bands):
    return Card("BlackoutRaw", "val", (window, bands)) if isinstance(bands, tuple) else Bottom("type")


def record_field(value, sort, arity, index):
    if (not isinstance(value, Card) or value.sort != sort or value.tag != "val"
            or len(value.fields) != arity or not 0 <= index < arity):
        return Bottom("type")
    return value.fields[index]


def band_lo(value):
    return value.fields[0]


def band_hi(value):
    return value.fields[1]


def no_hit():
    return Bottom("no_hit")


def incompatible():
    return Bottom("incompatible")


def resource_unknown():
    return Unknown("resource")


def is_defined(outcome):
    return isinstance(outcome, Ok)


def cycle_residue(value):
    return value.fields[0].fields[0]


def cycle_period(value):
    return value.fields[0].fields[1]


def plan_cycles(value):
    return value.fields[0].fields[0]


def window_plan(value):
    return value.fields[0].fields[0]


def window_lo(value):
    return value.fields[0].fields[1]


def window_hi(value):
    return value.fields[0].fields[2]


def window_compiled(value):
    return value.fields[0].fields[3]


def blackout_window(value):
    return value.fields[0].fields[0]


def blackout_bands(value):
    return value.fields[0].fields[1]


def reference_join(left, right):
    left_residue, left_period = left.fields[0].fields
    right_residue, right_period = right.fields[0].fields
    factor = gcd(left_period, right_period)
    if (right_residue - left_residue) % factor:
        return Bottom("incompatible")
    inverse = pow(left_period // factor, -1, right_period // factor) if right_period // factor > 1 else 0
    period = left_period * (right_period // factor)
    if period > LIMIT:
        return Bottom("range")
    residue = (left_residue + left_period * ((right_residue - left_residue) // factor * inverse
                                             % (right_period // factor))) % period
    return Card("Cycle", "val", (cycle_raw(residue, period),))


def value(item):
    from .expressions import display

    text = display(item)
    return text if len(text.encode("utf-8")) <= 4096 else Bottom("range")


def status(item):
    if isinstance(item, Ok):
        return "Ok"
    if isinstance(item, Bottom):
        return f"Bottom({item.reason})"
    if isinstance(item, Unknown):
        return f"Unknown({item.resource})"
    return "Ok"


def range_probe(item):
    return item.fields if isinstance(item, Card) and item.sort == "Band" else Bottom("type")
