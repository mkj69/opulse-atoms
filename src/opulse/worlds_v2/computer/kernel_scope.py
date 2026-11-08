"""Computer host-State bridge to the atoms kernel (spec sections 6.4, 6.5 and 15).

The kernel permits opaque host values; State is passed unchanged to the machine
operations. The Card codec remains the boundary for serialized machine states.
"""

from __future__ import annotations

from dataclasses import dataclass

from opulse.atoms.kernel import Atom, Defn, DictScope, Limits, evaluate
from opulse.atoms.nodes import Block, Blocks, CondJump, Test
from opulse.atoms.values import Ok

from .machine import State
from .runner import atoms as local_atoms


def scope(defs: dict[str, Blocks] | None = None) -> DictScope:
    """Resolve the seven layer-0 instructions and single-State definitions."""
    return DictScope(
        [Atom(name, arity, function, cost) for name, (arity, function, cost) in local_atoms().items()],
        [Defn(name, ("s",), _conditions(body)) for name, body in (defs or {}).items()],
    )


def _conditions(program: Blocks) -> Blocks:
    """Bridge pre-kernel computer programs whose conditional held a raw expression."""
    return Blocks(program.vars, program.entry, tuple(
        (label, Block(block.assigns, CondJump(Test(block.end.cond), block.end.then, block.end.else_)
                      if isinstance(block.end, CondJump) and not isinstance(block.end.cond, Test)
                      else block.end)) for label, block in program.blocks))


@dataclass(frozen=True)
class ComputerRun:
    outcome: object
    steps: int
    jumps: int
    final_state: State
    trace: object


def run_kernel(program: Blocks, state: State, fuel: int | None = None,
               defs: dict[str, Blocks] | None = None, *, trace: bool = False) -> ComputerRun:
    """Execute Blocks with the same fuel and jump accounting as the local runner.

    A non-Ok run reports the last state-producing operation; programs whose
    nested expression discards that state should inspect the returned trace.
    """
    result = evaluate(_conditions(program), {"s": state}, scope(defs), Limits(fuel=fuel), trace=trace)
    if not trace and (not isinstance(result.outcome, Ok) or
                      not isinstance(result.outcome.value, State)):
        result = evaluate(_conditions(program), {"s": state}, scope(defs), Limits(fuel=fuel), trace=True)
    last_state = state
    if result.trace is not None:
        def visit(node):
            nonlocal last_state
            if node.given and isinstance(node.outcome, Ok) and isinstance(node.outcome.value, State):
                last_state = node.outcome.value
            for child in node.children:
                visit(child)

        visit(result.trace)
    if isinstance(result.outcome, Ok) and isinstance(result.outcome.value, State):
        last_state = result.outcome.value
    return ComputerRun(result.outcome, result.steps, result.jumps, last_state, result.trace)
