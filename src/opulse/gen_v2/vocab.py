"""World-generic roles: find the operations that play a familiar part in any world.

Moves must not hard-code the names of one world (``lt``, ``is_zero``, ``add``...). They ask
this module instead. A role is recognised by its signature and by its behaviour on the probe
values of the sort, never by its name:

* ``less(state, sort)``        binary decide ``(s, s) -> bool`` that is a strict order on the
                               probe values (irreflexive, transitive, total on distinct values);
* ``equal(state, sort)``       binary decide that agrees with value equality;
* ``zero_test(state, sort)``   unary decide true on exactly one probe value (int: on 0);
* ``deciders(state, sort)``    every unary decide ``s -> bool`` that is true and false on the
                               probe values (useful conditions);
* ``steps(state, sort)``       unary ``s -> s`` operations that are not the identity;
* ``combiners(state, sort)``   binary ``(s, s) -> s`` operations;
* ``int_measures(state, sort)`` unary ``s -> int`` operations that are non-negative on every
                               probe value.

Roles cover given atoms, object operations and invented entries. Each (role, sort, name) is
tested once per state (a name's behaviour never changes once admitted).
"""

from __future__ import annotations

import itertools

from opulse.atoms.values import Ok, truth, value_equal
from opulse.gen_v2 import fast
from opulse.gen_v2.base import GenState
from opulse.gen_v2.codec import value_key

_CACHE_ATTR = "_vocab_cache"


def _cache(state: GenState) -> dict:
    cache = getattr(state, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        object.__setattr__(state, _CACHE_ATTR, cache)
    return cache


def _run(state: GenState, name: str, args):
    try:
        outcome = fast.call(name, args, state.library.scope(), state.world.fuel, state.world.dialect).outcome
    except (ValueError, TypeError, KeyError, RecursionError, IndexError, AttributeError):
        return None
    return outcome.value if isinstance(outcome, Ok) else None


def _bool(value):
    try:
        return truth(value)
    except TypeError:
        return None


def _values(state: GenState, sort: str, limit: int = 8) -> tuple:
    entry = state.sorts.get(sort)
    return tuple(entry.values[:limit]) if entry else ()


def _role(state: GenState, role: str, sort: str, inputs: tuple, output: str, test) -> list[str]:
    """Every callable with the signature for which ``test(name)`` holds. A name's behaviour
    never changes once admitted, so each (role, sort, name) is tested once per state."""
    cache = _cache(state)
    found = []
    for name in state.callables("operation", output=output, inputs=inputs):
        try:
            probes = tuple((part, tuple(value_key(value) for value in _values(state, part)))
                           for part in dict.fromkeys((*inputs, output)))
        except TypeError:
            matched = bool(test(name))
        else:
            key = (role, sort, name, probes, state.world.dialect,
                   state.world.fuel, id(state.library.scope()))
            if key not in cache:
                cache[key] = bool(test(name))
            matched = cache[key]
        if matched:
            found.append(name)
    return found


def less(state: GenState, sort: str) -> list[str]:
    values = _values(state, sort)

    def test(name):
        table = {}
        for a, b in itertools.product(values, repeat=2):
            result = _bool(_run(state, name, (a, b)))
            if result is None:
                return False
            table[a, b] = result
        return (values and all(not table[a, a] for a in values)
                and all(table[a, b] != table[b, a] for a, b in itertools.combinations(values, 2))
                and all(not (table[a, b] and table[b, c]) or table[a, c]
                        for a, b, c in itertools.product(values, repeat=3)))
    return _role(state, "less", sort, (sort, sort), "bool", test)


def equal(state: GenState, sort: str) -> list[str]:
    values = _values(state, sort)
    return _role(state, "equal", sort, (sort, sort), "bool",
                 lambda name: values and all(_bool(_run(state, name, (a, b))) == value_equal(a, b)
                                             for a, b in itertools.product(values, repeat=2)))


def deciders(state: GenState, sort: str) -> list[str]:
    values = _values(state, sort, 16)
    return _role(state, "deciders", sort, (sort,), "bool",
                 lambda name: {_bool(_run(state, name, (value,))) for value in values} == {True, False})


def zero_test(state: GenState, sort: str) -> list[str]:
    values = _values(state, sort, 16)

    def test(name):
        hits = [value for value in values if _bool(_run(state, name, (value,)))]
        return len(hits) == 1 and (sort != "int" or hits[0] == 0)
    zero = set(_role(state, "zero", sort, (sort,), "bool", test))
    return [name for name in deciders(state, sort) if name in zero]


def steps(state: GenState, sort: str) -> list[str]:
    values = _values(state, sort)
    return _role(state, "steps", sort, (sort,), sort,
                 lambda name: any(not value_equal(_run(state, name, (value,)), value) for value in values))


def combiners(state: GenState, sort: str) -> list[str]:
    return _role(state, "combiners", sort, (sort, sort), sort, lambda name: True)


def int_measures(state: GenState, sort: str) -> list[str]:
    values = _values(state, sort, 16)

    def test(name):
        results = [_run(state, name, (value,)) for value in values]
        return values and all(type(result) is int and result >= 0 for result in results)
    return _role(state, "measures", sort, (sort,), "int", test)
