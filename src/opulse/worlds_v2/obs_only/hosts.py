"""Fixed public probes and generic exact finite-structure operations."""

import builtins
from fractions import Fraction

from opulse.atoms.values import Bottom

from .model import DEFAULT, PublicConfig, State, Trace


def guarded(function):
    def invoke(*args):
        try:
            return function(*args)
        except (ValueError, IndexError, KeyError, TypeError, ZeroDivisionError) as error:
            return Bottom(str(error).replace(" ", "_"))
    return invoke


def frame(trace, tick):
    return int(trace.readings[tick]) if 0 <= tick < builtins.len(trace.readings) else Bottom("out_of_range")


def issued(trace, tick):
    return trace.actions[tick] if 0 <= tick < builtins.len(trace.actions) else Bottom("out_of_range")


def public_config(trace):
    return DEFAULT


def prior(config, position):
    if config.prior == "uniform":
        return Fraction(1, 64)
    if config.prior == "edge":
        return Fraction(64 - position, 2080)
    return Fraction(1, 32) if position % 2 == 0 else Fraction(0)


def protocol(config, position, reading):
    if config.protocol == "parity":
        return Fraction(7 if reading == position % 2 else 3, 10) if reading in (0, 1) else Fraction(0)
    offset = (reading - ((position ^ (position >> 3)) % 8)) % 8
    if config.protocol == "sharp":
        return Fraction({0: 75, 1: 13, 7: 12}.get(offset, 0), 100)
    return Fraction({0: 63, 1: 17, 7: 10}.get(offset, 2), 100)


def move(position, action):
    return max(0, min(63, position + {"L": -1, "R": 1, "S": 0}[action]))


def emit(position, draw, config):
    if not 0 <= draw < 100:
        raise ValueError("draw_out_of_range")
    if config.protocol == "parity":
        return position % 2 if draw < 70 else 1 - position % 2
    beacon = (position ^ (position >> 3)) % 8
    if config.protocol == "sharp":
        offset = 0 if draw < 75 else 1 if draw < 88 else 7
    else:
        offset = 0 if draw < 63 else 1 if draw < 80 else 7 if draw < 90 else 2 + (draw - 90) // 2
    return (beacon + offset) % 8


def step(state, action, config):
    if not state.private_draws:
        return Bottom("exhausted_draws")
    destination = move(state.position, action)
    history = Trace(state.history.actions + action,
                    state.history.readings + str(emit(destination, state.private_draws[0], config)))
    return State(destination, history, state.private_draws[1:])


def add(left, right):
    return left + right


def mul(left, right):
    return left * right


def div(left, right):
    return Fraction(left) / Fraction(right)


def le(left, right):
    return left <= right


def eq(left, right):
    return left == right


def at(items, index_value):
    return items[index_value]


def sum(items):
    return builtins.sum(items)


def sort_pairs(pairs):
    return tuple(sorted(pairs, key=lambda item: (-item[1], item[0])))


def first(items, count):
    return items[:count]


def len(items):
    return builtins.len(items)


def inc(value):
    return value + 1


def dec(value):
    return value - 1


def empty(items):
    return not items


def head(items):
    return items[0]


def tail(items):
    return items[1:]


def trace_sum(total, action, reading):
    return total + reading


def remaining(tick, current):
    return tick - current


def index(items, position):
    return items[position]


def sub(left, right):
    return left - right


def pair(left, right):
    return left, right


def append(items, value):
    return (*items, value)


def put_add(items, position, value):
    result = list(items)
    result[position] += value
    return tuple(result)


def zeros(count):
    return (Fraction(0),) * count


def range_values(count):
    return tuple(range(count))


def intervals(count):
    return tuple((left, left + width) for width in range(1, count + 1)
                 for left in range(count - width + 1))


def slice_values(items, left, right):
    return items[left:right]


def field(value, name):
    if not isinstance(value, PublicConfig) or name not in (
        "prior", "protocol", "region", "routes", "risk_mode", "credible_mode"
    ):
        raise ValueError("not_a_public_config_field")
    return getattr(value, name)


def contains(items, value):
    return value in items


def gt(left, right):
    return left > right


def join(items, separator):
    return separator.join(items)


def text(value):
    return str(value)


def fraction_text(value):
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def fail(reason):
    return Bottom(reason)


def frame_at(trace, tick):
    return frame(trace, tick)


def issued_at(trace, tick):
    return issued(trace, tick)


def prior_mass(config, position):
    return prior(config, position)


def protocol_mass(config, position, reading):
    return protocol(config, position, reading)


def config_of(trace):
    return public_config(trace)
