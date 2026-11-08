"""Projection-only exhaustive multiplication checks."""

from opulse.atoms import nodes
from opulse.atoms.nodes import from_json
from opulse.atoms.values import Ok
from opulse.worlds_v2.computer import machine
from opulse.worlds_v2.computer.machine import State

from .check import calls
from .compile import compile_sub
from .evaluate import run_blocks


def is_mul_equivalent(name, *, group, program, library=None, fuel=200_000):
    return _check(name, group=group, program=program, library=library, fuel=fuel, domain=16)


def exhaustive_mul_check(name, *, group, program, library=None, fuel=200_000):
    return _check(name, group=group, program=program, library=library, fuel=fuel, domain=256)


def _fast_projection(body, fuel):
    """Compile instruction-only Blocks to a no-trace byte-state projection runner."""
    blocks = {}
    for label, block in body.blocks:
        operations = []
        for _, assign in block.assigns:
            if not isinstance(assign, nodes.Call) or assign.fn not in (
                    "write", "add", "dec", "load", "store"):
                return None
            if not all(isinstance(arg, nodes.Lit) for arg in assign.args[1:]):
                return None
            operands = tuple(machine.reg_index(arg.value) if machine.reg_index(arg.value) is not None
                             else arg.value for arg in assign.args[1:])
            operations.append((assign.fn, operands))
        end = block.end
        if isinstance(end, nodes.CondJump):
            test = end.cond
            if not isinstance(test, nodes.Test) or not isinstance(test.expr, nodes.Call) or (
                    test.expr.fn != "is_zero"):
                return None
            register = machine.reg_index(test.expr.args[1].value)
            if register is None:
                return None
            terminal = ("cond", register, end.then, end.else_)
        elif isinstance(end, nodes.Jump):
            terminal = ("jump", end.target)
        elif isinstance(end, nodes.Halt):
            terminal = ("halt",)
        else:
            return None
        blocks[label] = (operations, terminal)

    def evaluate(state):
        registers = list(state.regs)
        memory = bytearray(state.mem)
        zero, carry = state.zero, state.carry
        steps = 0
        label = body.entry
        while True:
            operations, terminal = blocks[label]
            for operation, operands in operations:
                if steps >= fuel:
                    return None
                steps += 1
                if operation == "write":
                    registers[operands[0]] = operands[1]
                elif operation == "add":
                    destination, source = operands
                    total = registers[destination] + registers[source]
                    registers[destination] = total & 255
                    zero, carry = registers[destination] == 0, total > 255
                elif operation == "dec":
                    destination = operands[0]
                    carry = registers[destination] == 0
                    registers[destination] = (registers[destination] - 1) & 255
                    zero = registers[destination] == 0
                elif operation == "load":
                    registers[operands[0]] = memory[operands[1]]
                else:
                    memory[operands[1]] = registers[operands[0]]
            if terminal[0] == "halt":
                return Ok(State(tuple(registers), bytes(memory), zero, carry))
            if terminal[0] == "cond":
                if steps >= fuel:
                    return None
                steps += 1
                destination = terminal[2] if registers[terminal[1]] == 0 else terminal[3]
            else:
                destination = terminal[1]
            if steps >= fuel:
                return None
            steps += 1
            label = destination

    return evaluate


def _check(name, *, group, program, library, fuel, domain):
    graph = {sub.name: calls(sub) + (["mul"] if any(line.op == "mul" for line in sub.lines) else [])
             for sub in program.defs}
    if library:
        graph.update({entry.name: entry.depends_on for entry in library._entries.values()})
    pending, seen = [name], set()
    while pending:
        current = pending.pop()
        if current == "mul":
            return {"equivalent": False, "method": "exhaustive",
                    "scope": f"r1,r2 in [0,{domain - 1}], projection r0", "counterexample": None}
        if current not in seen:
            seen.add(current)
            pending.extend(graph.get(current, ()))
    definitions = {sub.name: compile_sub(sub) for sub in program.defs}
    if library:
        definitions.update({entry.name: from_json(entry.body) for entry in library._entries.values()})
    if name not in definitions:
        return {"equivalent": False, "method": "exhaustive",
                "scope": f"r1,r2 in [0,{domain - 1}], projection r0", "counterexample": None}
    fast = _fast_projection(definitions[name], fuel) if domain == 256 and isinstance(fuel, int) else None
    for left in range(domain):
        for right in range(domain):
            state = State((0, left, right, 0))
            outcome = fast(state) if fast else None
            if outcome is None:
                outcome = run_blocks(definitions[name], state, definitions, fuel,
                                     group, record_trace=False).outcome
            if not isinstance(outcome, Ok) or outcome.value.regs[0] != (left * right & 255):
                return {"equivalent": False, "method": "exhaustive",
                        "scope": f"r1,r2 in [0,{domain - 1}], projection r0",
                        "counterexample": [left, right]}
    return {"equivalent": True, "method": "exhaustive",
            "scope": f"r1,r2 in [0,{domain - 1}], projection r0", "counterexample": None}
