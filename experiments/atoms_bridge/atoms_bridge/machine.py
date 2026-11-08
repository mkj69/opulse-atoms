"""MASM's single cross-world instruction, lowered into core kernel nodes."""

import re
from dataclasses import dataclass
from functools import lru_cache

from atoms_mul.machine.compile import compile_sub
from atoms_mul.machine.lang import MasmSyntaxError
from atoms_mul.machine.lang import parse_program as parse_masm

from opulse.atoms import kernel, nodes
from opulse.atoms.values import Bottom, Ok
from opulse.worlds_v2.computer.machine import REGISTERS, State

from .bridge import mul_scope, worlds, wrap_byte

XCALL = re.compile(r"(?m)^([ \t]*)xcall mul r1, r2 -> r0[ \t]*(?=#|$)")
SENTINEL = "__xcall_mul"


def parse_program(text):
    """Recognize the exact new instruction, leaving all other MASM unchanged."""
    if not isinstance(text, str):
        return parse_masm(text)
    source = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    if re.search(rf"\bcall\s+{SENTINEL}\b|\bsub\s+{SENTINEL}\s*:", source):
        raise MasmSyntaxError("reserved cross-world instruction", 1, 1)
    return parse_masm(XCALL.sub(lambda match: f"{match[1]}call {SENTINEL}", text))


def _xcall_body(group):
    def nat(register):
        read = nodes.Call("read", (nodes.Var("s"), nodes.Lit(REGISTERS[register])))
        byte = nodes.Call("byte.make", (read,))
        return nodes.Call("nat.base", (nodes.Call("to_nat", (byte,)),))

    arguments = (nodes.Var("left"), nodes.Var("right"))
    product = nodes.Call("mul", arguments)
    if group == "B":
        product = nodes.Case(((nodes.Test(nodes.Call("mul_scope", arguments)), product),),
                             nodes.Lit(Bottom("outside_domain")))
    result = nodes.Call("byte.base", (nodes.Call("to_byte", (
        nodes.Call("nat.make", (nodes.Call("wrap_byte", (product,)),)),)),))
    return nodes.Let("left", nat(1), nodes.Let("right", nat(2),
                     nodes.Call("write", (nodes.Var("s"), nodes.Lit(REGISTERS[0]), result))))


@dataclass(frozen=True)
class Run:
    outcome: object
    steps: int
    boundary_steps: int
    calls: dict[str, int]
    final_state: State


@lru_cache(maxsize=2)
def _runtime(group):
    integer, machine = worlds(group)
    scope = integer.scope()
    machine_scope = machine.local_scope()
    atoms = {**scope.atoms,
             "wrap_byte": kernel.Atom("wrap_byte", 1, wrap_byte),
             "mul_scope": kernel.Atom("mul_scope", 2, mul_scope, cost=0)}
    atoms["machine_add"] = machine_scope.atoms["add"]
    atoms["machine_is_zero"] = machine_scope.atoms["is_zero"]
    definitions = dict(scope.defns)
    definitions[SENTINEL] = kernel.Defn(SENTINEL, ("s",), _xcall_body(group))
    return atoms, definitions


def runtime_names(group):
    """Names occupied by the cross-world kernel, including hidden helpers."""
    atoms, definitions = _runtime(group)
    return frozenset(atoms) | definitions.keys()


def run_sub(program, state, group, fuel=200_000):
    """Run native MASM and transferred integer calls in one kernel fuel counter."""
    atoms, base_definitions = _runtime(group)
    definitions = dict(base_definitions)

    def alias(node):
        if isinstance(node, nodes.Call) and node.fn in ("add", "is_zero"):
            return nodes.Call(f"machine_{node.fn}", node.args)
        return node

    definitions.update({sub.name: kernel.Defn(sub.name, ("s",), nodes.map_nodes(compile_sub(sub), alias))
                        for sub in program.defs})
    result = kernel.call("main", (state,), kernel.DictScope(atoms, definitions),
                         kernel.Limits(fuel=fuel), trace=True)
    final_state = result.outcome.value if isinstance(result.outcome, Ok) else state
    calls = {"xcall": 0, "mul": 0}

    def visit(node):
        nonlocal final_state
        if node.name == SENTINEL:
            calls["xcall"] += 1
        if node.name == "mul":
            calls["mul"] += 1
        if node.given and isinstance(node.outcome, Ok) and isinstance(node.outcome.value, State):
            final_state = node.outcome.value
        for child in node.children:
            visit(child)

    visit(result.trace)

    def visible(frame):
        if group == "B" and frame.name == "mul":
            return 1
        return frame.steps - sum(child.steps for child in frame.children) + sum(
            visible(child) for child in frame.children)

    return Run(result.outcome, result.steps, visible(result.trace), calls, final_state)
