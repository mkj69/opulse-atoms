"""Execute MASM using the computer world and account for trace boundaries."""

from collections import Counter
from dataclasses import dataclass

from opulse.atoms import kernel, nodes
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.worlds_v2.computer import machine, runner
from opulse.worlds_v2.computer.kernel_scope import scope

from .compile import compile_sub


@dataclass(frozen=True)
class Run:
    outcome: Ok | Bottom | Unknown
    steps: int
    boundary_steps: int
    calls: dict
    final_state: machine.State | None


def run_blocks(body, state, definitions, fuel, group, *, record_trace=True):
    """Use the world runner, or its kernel scope with computer_a's given mul."""
    if group != "A":
        return runner.run(body, {"s": state}, fuel=fuel, defs=definitions,
                          record_trace=record_trace)
    machine_scope = scope(definitions)
    machine_scope.atoms["mul"] = kernel.Atom("mul", 1, machine.given_mul)
    result = kernel.evaluate(body, {"s": state}, machine_scope, kernel.Limits(fuel=fuel), trace=True)
    last_state = state

    def visit(node):
        nonlocal last_state
        if node.given and isinstance(node.outcome, Ok) and isinstance(node.outcome.value, machine.State):
            last_state = node.outcome.value
        for child in node.children:
            visit(child)

    visit(result.trace)
    if isinstance(result.outcome, Ok) and isinstance(result.outcome.value, machine.State):
        last_state = result.outcome.value

    def events(node):
        children = tuple(event for child in node.children for event in events(child))
        own_steps = node.steps - sum(child.steps for child in node.children)
        if node.given:
            return (runner.TraceNode(node.name),) if own_steps > 0 else children
        unfolded = children + (runner.TraceNode("jump"),) * own_steps
        return (runner.TraceNode(node.name, unfolded),) if node.name else unfolded

    return runner.Run(result.outcome, result.steps, result.jumps, last_state,
                      events(result.trace) if record_trace else ())


def run_sub(name, state, *, group, program, library=None, fuel=200_000, boundary=frozenset()):
    definitions = {sub.name: compile_sub(sub) for sub in program.defs}
    if library:
        definitions.update({entry.name: nodes.from_json(entry.body)
                            for entry in library._entries.values()})
    if name not in definitions:
        return Run(Bottom(f"no such name {name}"), 0, 0, {}, state)
    outcome = run_blocks(definitions[name], state, definitions, fuel, group)
    counts = Counter()

    def count_only(events):
        for event in events:
            if event.name in definitions:
                counts[event.name] += 1
                count_only(event.children)

    def cost(events):
        total = 0
        for event in events:
            if event.name in definitions:
                counts[event.name] += 1
                if event.name in boundary:
                    total += 1
                    count_only(event.children)
                else:
                    total += cost(event.children)
            else:
                total += 1
        return total

    if name in boundary:
        count_only(outcome.trace)
        visible = 1
    else:
        visible = cost(outcome.trace)
    return Run(outcome.outcome, outcome.steps, visible, dict(counts), outcome.final_state)
