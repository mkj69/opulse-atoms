"""Local Blocks interpreter (spec sections 6.4-6.5); swap here for the core kernel.

Definitions execute in their own frames; trace groups their unfolded events as one
definition-call node without changing the underlying layer-0 costs.
"""

from __future__ import annotations

from dataclasses import dataclass

from opulse.atoms.nodes import (
    Always,
    And,
    Block,
    Blocks,
    Call,
    CondJump,
    Halt,
    Jump,
    Let,
    Lit,
    Not,
    Or,
    Test,
    Var,
)
from opulse.atoms.values import Bottom, Ok, Unknown, truth

from . import machine


@dataclass(frozen=True)
class TraceNode:
    name: str
    children: tuple[TraceNode, ...] = ()


@dataclass(frozen=True)
class Run:
    outcome: Ok | Bottom | Unknown
    steps: int
    jumps: int
    final_state: machine.State | None
    trace: tuple[TraceNode, ...]


def atoms() -> dict[str, tuple[int, object, int]]:
    return {
        "read": (2, machine.read, 1), "write": (3, machine.write, 1),
        "load": (3, machine.load, 1), "store": (3, machine.store, 1),
        "add": (3, machine.add, 1), "dec": (2, machine.dec, 1),
        "is_zero": (2, machine.is_zero, 1),
    }


class _Stop(Exception):
    def __init__(self, outcome: Bottom | Unknown):
        self.outcome = outcome


def run(program: Blocks, inputs: dict, fuel: int | None = None,
        defs: dict[str, Blocks] | None = None, *, record_trace: bool = True) -> Run:
    """Run a program; ``inputs`` binds parameters (usually ``s``).

    ``final_state`` is the last successfully assigned state, even when a later
    call fails; it is never inferred from a read-only result.
    """
    operations = atoms()
    definitions = defs or {}
    steps = 0
    jumps = 0
    last_state = inputs.get("s") if isinstance(inputs.get("s"), machine.State) else None
    trace: list[TraceNode] = []
    active: set[str] = set()

    def expression(node: object, env: dict, events: list[TraceNode]):
        nonlocal steps
        if isinstance(node, Var):
            value = env[node.name]
            if isinstance(value, (Bottom, Unknown)):
                raise _Stop(value)
            return value
        if isinstance(node, Lit):
            if isinstance(node.value, (Bottom, Unknown)):
                raise _Stop(node.value)
            return node.value
        if isinstance(node, Let):
            value = expression(node.value, env, events)
            local = dict(env)
            local[node.name] = value
            return expression(node.body, local, events)
        if isinstance(node, Call):
            args = tuple(expression(arg, env, events) for arg in node.args)
            for arg in args:
                if isinstance(arg, (Bottom, Unknown)):
                    raise _Stop(arg)
            if node.fn in operations:
                arity, function, cost = operations[node.fn]
                if len(args) != arity:
                    raise _Stop(Bottom("invalid"))
                if fuel is not None and steps + cost > fuel:
                    raise _Stop(Unknown("fuel"))
                steps += cost
                result = function(*args)
                if record_trace:
                    events.append(TraceNode(node.fn))
                if isinstance(result, (Bottom, Unknown)):
                    raise _Stop(result)
                return result
            if node.fn in definitions and len(args) == 1:
                if node.fn in active:
                    raise _Stop(Bottom("invalid"))
                children: list[TraceNode] = []
                active.add(node.fn)
                try:
                    return execute(definitions[node.fn], {"s": args[0]}, children)
                finally:
                    active.remove(node.fn)
                    if record_trace:
                        events.append(TraceNode(node.fn, tuple(children)))
            raise _Stop(Bottom("invalid"))
        if isinstance(node, Blocks):
            return execute(node, env, events)
        raise _Stop(Bottom("invalid"))

    def condition(cond: object, env: dict, events: list[TraceNode]) -> bool:
        """Spec 6.1 conditions, left to right with short-circuit; a bare node is a Test."""
        if isinstance(cond, Always):
            return True
        if isinstance(cond, Not):
            return not condition(cond.operand, env, events)
        if isinstance(cond, And):
            return condition(cond.left, env, events) and condition(cond.right, env, events)
        if isinstance(cond, Or):
            return condition(cond.left, env, events) or condition(cond.right, env, events)
        value = expression(cond.expr if isinstance(cond, Test) else cond, env, events)
        try:
            return truth(value)
        except TypeError:
            raise _Stop(Bottom("invalid")) from None

    def execute(body: Blocks, inputs_: dict, events: list[TraceNode]):
        nonlocal steps, jumps, last_state
        env = dict(inputs_)
        for name, init in body.vars:
            env[name] = expression(init, env, events)
            if isinstance(env[name], machine.State):
                last_state = env[name]
        blocks = dict(body.blocks)
        label = body.entry
        while True:
            block: Block = blocks[label]
            for name, value in block.assigns:
                env[name] = expression(value, env, events)
                if isinstance(env[name], machine.State):
                    last_state = env[name]
            end = block.end
            if isinstance(end, Halt):
                return expression(end.value, env, events)
            if isinstance(end, CondJump):
                try:
                    label = end.then if condition(end.cond, env, events) else end.else_
                except _Stop as stop:
                    if isinstance(stop.outcome, Bottom):
                        raise _Stop(Bottom("nan_condition")) from None
                    raise
            elif isinstance(end, Jump):
                label = end.target
            else:
                raise _Stop(Bottom("invalid"))
            if fuel is not None and steps + 1 > fuel:
                raise _Stop(Unknown("fuel"))
            steps += 1
            jumps += 1
            if record_trace:
                events.append(TraceNode("jump"))

    try:
        result = execute(program, inputs, trace)
        return Run(Ok(result), steps, jumps, result if isinstance(result, machine.State) else last_state, tuple(trace))
    except _Stop as stop:
        return Run(stop.outcome, steps, jumps, last_state, tuple(trace))
