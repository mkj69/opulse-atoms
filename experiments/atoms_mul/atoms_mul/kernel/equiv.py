from .evaluate import Ok, evaluate

MUL_DOMAIN = 16


def is_mul_equivalent(name, *, world, program=None, library=None):
    for first in range(MUL_DOMAIN):
        for second in range(MUL_DOMAIN):
            outcome = evaluate(name, (first, second), world=world, program=program,
                               library=library).outcome
            if not isinstance(outcome, Ok) or type(outcome.value) is not int or outcome.value != first * second:
                return {"equivalent": False, "method": "exhaustive", "scope": "a,b in [0,15]",
                        "counterexample": [first, second]}
    return {"equivalent": True, "method": "exhaustive", "scope": "a,b in [0,15]",
            "counterexample": None}


def constant_multiplier(name, *, world, program=None, library=None):
    candidates = set(range(2, 21))
    for value in range(64):
        outcome = evaluate(name, (value,), world=world, program=program, library=library).outcome
        if not isinstance(outcome, Ok) or type(outcome.value) is not int:
            return None
        candidates = {factor for factor in candidates if outcome.value == factor * value}
        if not candidates:
            return None
    return min(candidates) if candidates else None
