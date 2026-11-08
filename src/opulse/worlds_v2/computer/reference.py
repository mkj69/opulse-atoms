"""Given reference variant computer_a (spec section 15).

The reference adds a given layer-0 operation. Its contract is intentionally
only compared to invented MUL on the task's r0 projection, never full state.
"""

from __future__ import annotations

from .machine import RULES, given_mul

COMPUTER_A = {
    "world": "computer_a", "extends": "computer@1",
    "operations": [{
        "kind": "operation", "name": "mul", "origin": "given", "layer": 0,
        "role": "act", "inputs": [{"name": "s", "sort": "machine_state", "enter": "bottom"}],
        "output": {"sort": "machine_state", "enter": "bottom"},
        "rule": RULES["mul"], "errors": ["invalid"], "cost": 1,
        "strict": True, "impl": "opulse.worlds_v2.computer.machine:given_mul",
    }],
}


def atoms() -> dict[str, tuple[int, object, int]]:
    from .runner import atoms as base_atoms

    return {**base_atoms(), "mul": (1, given_mul, 1)}
