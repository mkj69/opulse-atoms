"""Reference semantics and executable certificates for the observation-only world."""

import json
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from .model import DEFAULT, SIZE, PublicConfig, State, Trace


def config_of(spec):
    fields = dict(spec.get("config", {}))
    for name in ("region", "routes"):
        if name in fields:
            fields[name] = tuple(fields[name])
    return PublicConfig(**fields)


def prior_mass(index, config=DEFAULT):
    if config.prior == "uniform":
        return Fraction(1, SIZE)
    if config.prior == "edge":
        return Fraction(SIZE - index, SIZE * (SIZE + 1) // 2)
    return Fraction(1, SIZE // 2) if index % 2 == 0 else Fraction(0)


def protocol_mass(position_now, reading, config=DEFAULT):
    if config.protocol == "parity":
        return Fraction(7 if reading == position_now % 2 else 3, 10) if reading in (0, 1) else Fraction(0)
    offset = (reading - beacon(position_now)) % 8
    if config.protocol == "sharp":
        return Fraction({0: 75, 1: 13, 7: 12}.get(offset, 0), 100)
    return Fraction({0: 63, 1: 17, 7: 10}.get(offset, 2), 100)


def trace_of(spec):
    return Trace(spec["actions"], spec["readings"])


def position(position_before, action):
    return max(0, min(63, position_before + {"L": -1, "R": 1, "S": 0}[action]))


def beacon(position_now):
    return (position_now ^ (position_now >> 3)) % 8


def emit(position_now, draw, config=DEFAULT):
    if not 0 <= draw < 100:
        raise ValueError("draw out of range")
    if config.protocol == "parity":
        return str(position_now % 2 if draw < 70 else 1 - position_now % 2)
    if config.protocol == "sharp":
        offset = 0 if draw < 75 else 1 if draw < 88 else 7
        return str((beacon(position_now) + offset) % 8)
    offset = (0 if draw < 63 else 1 if draw < 80 else 7 if draw < 90
              else 2 + (draw - 90) // 2)
    return str((beacon(position_now) + offset) % 8)


def step(state, action, config=DEFAULT):
    if not state.private_draws:
        raise ValueError("exhausted_draws")
    destination = position(state.position, action)
    history = Trace(state.history.actions + action,
                    state.history.readings + emit(destination, state.private_draws[0], config))
    return State(destination, history, state.private_draws[1:])


def likelihood(trace, tick, position_now, config=DEFAULT):
    if not 0 <= tick < len(trace.readings) or not 0 <= position_now < SIZE:
        raise ValueError("index out of range")
    reading = int(trace.readings[tick])
    return protocol_mass(position_now, reading, config)


@lru_cache(maxsize=2048)
def belief(trace, tick, config=DEFAULT):
    if not 0 <= tick < len(trace.readings):
        raise ValueError("tick out of range")
    weights = [prior_mass(index, config) for index in range(SIZE)]
    for current in range(tick + 1):
        if current:
            moved = [Fraction(0)] * SIZE
            for index, weight in enumerate(weights):
                moved[position(index, trace.actions[current - 1])] += weight
            weights = moved
        weights = [weight * likelihood(trace, current, index, config)
                   for index, weight in enumerate(weights)]
        total = sum(weights)
        if not total:
            raise ValueError("impossible public trace")
        weights = [weight / total for weight in weights]
    return tuple(weights)


@lru_cache(maxsize=2048)
def ranked(trace, tick, config=DEFAULT):
    weights = belief(trace, tick, config)
    return tuple(sorted(range(SIZE), key=lambda index: (-weights[index], index)))


@lru_cache(maxsize=2048)
def credible(trace, tick, quantile, config=DEFAULT):
    if not 0 < quantile <= 1:
        raise ValueError("quantile out of range")
    weights = belief(trace, tick, config)
    if config.credible_mode == "window":
        prefix = [Fraction(0)]
        for weight in weights:
            prefix.append(prefix[-1] + weight)
        length, left, mass = min(
            (right - start, start, prefix[right] - prefix[start])
            for start in range(SIZE) for right in range(start + 1, SIZE + 1)
            if prefix[right] - prefix[start] >= quantile
        )
        return tuple(range(left, left + length)), mass
    picked = []
    mass = Fraction(0)
    for index in ranked(trace, tick, config):
        picked.append(index)
        mass += weights[index]
        if mass >= quantile:
            break
    return tuple(picked), mass


def hits_hazard(start, route, config=DEFAULT):
    hits = 0
    for action in route:
        start = position(start, action)
        hits += start in config.region
        if config.risk_mode == "ever" and hits:
            return True
    if config.risk_mode == "terminal":
        return start in config.region
    return hits >= 2


@lru_cache(maxsize=2048)
def risk_interval(trace, tick, quantile, route, config=DEFAULT):
    if not route or len(route) > 4 or any(action not in "LRS" for action in route):
        raise ValueError("route out of range")
    support, mass = credible(trace, tick, quantile, config)
    weights = belief(trace, tick, config)
    lower = sum((weights[index] for index in support if hits_hazard(index, route, config)),
                Fraction(0))
    return lower, lower + 1 - mass


@lru_cache(maxsize=2048)
def certified(trace, tick, quantile, route, cap, config=DEFAULT):
    if not 0 <= cap <= 1:
        raise ValueError("cap out of range")
    lower, upper = risk_interval(trace, tick, quantile, route, config)
    return "SAFE" if upper <= cap else "UNSAFE" if lower > cap else "UNKNOWN"


def choice(trace, tick, quantile, cap, config=DEFAULT):
    return next((route for route in config.routes
                 if certified(trace, tick, quantile, route, cap, config) == "SAFE"), "NONE")


def audit(trace, tick, quantile, cap, config=DEFAULT):
    route = choice(trace, tick, quantile, cap, config)
    labels = "".join("S" if certified(trace, tick, quantile, item, cap, config) == "SAFE"
                     else "U" if certified(trace, tick, quantile, item, cap, config) == "UNSAFE"
                     else "?" for item in config.routes)
    bound = "NONE" if route == "NONE" else format_interval(risk_interval(trace, tick, quantile, route, config))
    return f"{route}|{labels}|{bound}"


def status(trace, tick, config=DEFAULT):
    try:
        belief(trace, tick, config)
    except ValueError as error:
        if str(error) != "impossible public trace":
            raise
        return "IMPOSSIBLE"
    return "POSSIBLE"


def exact_risk(trace, tick, route, config=DEFAULT):
    if not route or len(route) > 4 or any(action not in "LRS" for action in route):
        raise ValueError("route out of range")
    return sum((mass for index, mass in enumerate(belief(trace, tick, config))
                if hits_hazard(index, route, config)), Fraction(0))


def partition(trace, tick, quantile, cap, config=DEFAULT):
    if status(trace, tick, config) == "IMPOSSIBLE":
        return "IMPOSSIBLE"
    return "".join("S" if certified(trace, tick, quantile, item, cap, config) == "SAFE"
                   else "U" if certified(trace, tick, quantile, item, cap, config) == "UNSAFE"
                   else "?" for item in config.routes)


def format_fraction(value):
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def format_interval(interval):
    return "[" + ",".join(map(format_fraction, interval)) + "]"


def evaluate(case):
    trace = trace_of(case["trace"])
    tick = case["tick"]
    kind = case["query"]
    quantile = Fraction(case.get("q", "9/10"))
    cap = Fraction(case.get("cap", "1/5"))
    config = config_of(case)
    if kind == "weight":
        return format_fraction(likelihood(trace, tick, case["position"], config))
    if kind == "belief":
        return format_fraction(belief(trace, tick, config)[case["position"]])
    if kind == "ranked":
        return ",".join(map(str, ranked(trace, tick, config)[:case["count"]]))
    if kind == "credible":
        picked, mass = credible(trace, tick, quantile, config)
        return f"{','.join(map(str, picked))}|{format_fraction(mass)}"
    if kind == "risk_interval":
        return format_interval(risk_interval(trace, tick, quantile, case["route"], config))
    if kind == "certified":
        return certified(trace, tick, quantile, case["route"], cap, config)
    if kind == "choice":
        return choice(trace, tick, quantile, cap, config)
    if kind == "audit":
        return audit(trace, tick, quantile, cap, config)
    if kind == "status":
        return status(trace, tick, config)
    if kind == "exact_risk":
        return format_fraction(exact_risk(trace, tick, case["route"], config))
    if kind == "partition":
        return partition(trace, tick, quantile, cap, config)
    if kind == "invert_choice":
        return ",".join(str(reading) for reading in range(8)
                        if status(Trace(trace.actions, trace.readings[:-1] + str(reading)), tick, config) == "POSSIBLE"
                        and choice(Trace(trace.actions, trace.readings[:-1] + str(reading)),
                                   tick, quantile, cap, config) == case["target"])
    if kind == "decide_safe":
        return "true" if choice(trace, tick, quantile, cap, config) != "NONE" else "false"
    raise ValueError(kind)


def independent_forward(trace, tick, config=DEFAULT):
    """Independent unnormalized forward recurrence, cross-checking the normalized filter."""
    masses = []
    for initial in range(SIZE):
        path = prior_mass(initial, config)
        location = initial
        for current in range(tick + 1):
            if current:
                location = position(location, trace.actions[current - 1])
            path *= protocol_mass(location, int(trace.readings[current]), config)
        masses.append((location, path))
    collected = [sum((value for location, value in masses if location == index), Fraction(0))
                 for index in range(SIZE)]
    total = sum(collected)
    return None if not total else tuple(mass / total for mass in collected)


def independent_hit(start, route, config):
    path = []
    for action in route:
        start += {"L": -1, "R": 1, "S": 0}[action]
        start = min(SIZE - 1, max(0, start))
        path.append(start in config.region)
    if config.risk_mode == "terminal":
        return path[-1]
    if config.risk_mode == "at_least_two":
        return sum(path) >= 2
    return any(path)


def run_checks():
    card = json.loads((Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/obs_only.json")
                      .read_text(encoding="utf-8"))
    assert card["id"] == "obs_only"
    assert card["open_kinds"] == ["observation"]
    assert len(card["tower"]) == 10 and all(layer["kind"] == "observation"
                                             for layer in card["tower"])
    assert [layer["layer"] for layer in card["tower"]] == list(range(1, 11))
    assert len(card["ladder"]) == 5 and len(card["showcase"]) == 5
    assert card["rejected_fixes"] == []
    for layer in card["tower"]:
        assert evaluate(layer["check"]) == layer["value"], layer["layer"]
    for task in card["showcase"]:
        assert evaluate(task["check"]) == task["answer"], task["angle"]
    for task in card["generated_cases"]:
        assert evaluate(task["check"]) == task["value"], task["example"]
    for layer in card["tower"]:
        public_trace = trace_of(layer["check"]["trace"])
        config = config_of(layer["check"])
        for hidden_start in (0, 63):
            hidden_position = hidden_start
            probability = Fraction(1)
            for current, reading in enumerate(public_trace.readings):
                if current:
                    hidden_position = position(hidden_position, public_trace.actions[current - 1])
                probability *= likelihood(public_trace, current, hidden_position, config)
            assert probability >= 0
    for task in card["showcase"]:
        case = task["check"]
        trace = trace_of(case["trace"])
        config = config_of(case)
        assert belief(trace, case["tick"], config) == independent_forward(trace, case["tick"], config)
        if case["query"] == "audit":
            for route in config.routes:
                actual = exact_risk(trace, case["tick"], route, config)
                lower, upper = risk_interval(trace, case["tick"], Fraction(case["q"]), route, config)
                assert lower <= actual <= upper
        if case["query"] == "invert_choice":
            witnesses = evaluate(case).split(",") if evaluate(case) else []
            assert all(choice(Trace(trace.actions, trace.readings[:-1] + str(index)),
                              case["tick"], Fraction(case["q"]), Fraction(case["cap"]), config)
                       == case["target"] for index in map(int, witnesses))
            assert all(choice(Trace(trace.actions, trace.readings[:-1] + str(index)),
                              case["tick"], Fraction(case["q"]), Fraction(case["cap"]), config)
                       != case["target"] for index in range(8) if str(index) not in witnesses)
    assert all(sum(belief(Trace("", str(reading)), 0)) == 1 for reading in range(8))
    assert all(sum((likelihood(Trace("", str(reading)), 0, position_now)
                    for reading in range(8)), Fraction(0)) == 1
               for position_now in range(64))
    for position_now in range(64):
        assert all(sum(emit(position_now, draw) == str(reading) for draw in range(100))
                   == 100 * likelihood(Trace("", str(reading)), 0, position_now)
                   for reading in range(8))
    configs = (DEFAULT,
               PublicConfig("edge", "sharp", tuple(range(20, 29)), ("LL", "R", "SS"), "at_least_two", "ranked"),
               PublicConfig("edge", "sharp", tuple(range(20, 29)), ("LL", "R", "SS"), "terminal", "window"),
               PublicConfig("even", "parity", (0, 1, 2, 8, 9, 10), ("LL", "R", "SS"), "at_least_two", "ranked"))
    signatures = set()
    history_partitions = []
    for config in configs:
        history_partitions.append(tuple(partition(Trace("LR", readings), 2, Fraction(3, 4), Fraction(1, 5), config)
                                        for readings in ("010", "607", "717", "633")))
        assert sum((prior_mass(index, config) for index in range(SIZE)), Fraction(0)) == 1
        for index in range(SIZE):
            assert sum((protocol_mass(index, reading, config) for reading in range(8)), Fraction(0)) == 1
            assert all(sum(emit(index, draw, config) == str(reading) for draw in range(100))
                       == 100 * protocol_mass(index, reading, config) for reading in range(8))
        for readings in ("010", "607", "717", "633"):
            trace = Trace("LR", readings)
            oracle = independent_forward(trace, 2, config)
            assert (oracle is None) == (status(trace, 2, config) == "IMPOSSIBLE")
            if oracle is None:
                continue
            posterior = belief(trace, 2, config)
            assert posterior == oracle and sum(posterior) == 1
            for quantile in (Fraction(3, 4), Fraction(1)):
                support, mass = credible(trace, 2, quantile, config)
                assert sum((posterior[index] for index in support), Fraction(0)) == mass
                for route in config.routes:
                    lower, upper = risk_interval(trace, 2, quantile, route, config)
                    oracle_risk = sum((weight for index, weight in enumerate(oracle)
                                       if independent_hit(index, route, config)), Fraction(0))
                    tail = 1 - mass
                    assert lower <= oracle_risk <= upper
                    assert oracle_risk == exact_risk(trace, 2, route, config)
                    assert upper - lower == tail
                    for cap in (Fraction(0), Fraction(1, 5), Fraction(1)):
                        label = certified(trace, 2, quantile, route, cap, config)
                        assert label == ("SAFE" if upper <= cap else "UNSAFE" if lower > cap else "UNKNOWN")
                        assert (label != "SAFE" or oracle_risk <= cap)
                        assert (label != "UNSAFE" or oracle_risk > cap)
                signature = partition(trace, 2, quantile, Fraction(0), config)
                assert signature == partition(Trace(trace.actions, trace.readings), 2, quantile, Fraction(0), config)
                signatures.add(signature)
    assert len(signatures) >= 3 and status(Trace("", "7"), 0, configs[-1]) == "IMPOSSIBLE"
    assert len(set(history_partitions)) == len(configs)
    initial = State(0, Trace("", emit(0, 0)), (63, 80))
    assert step(step(initial, "L"), "R").history == Trace("LR", "010")
    print("OK")


if __name__ == "__main__":
    run_checks()
