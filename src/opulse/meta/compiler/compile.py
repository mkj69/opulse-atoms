"""Untrusted tiny/1 to vn/1 reference compiler (atoms-meta, section 5)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from opulse.atoms import nodes
from opulse.atoms.values import Card
from opulse.meta.code import lst
from opulse.meta.compiler.tiny import check_tiny, definition
from opulse.meta.vn import reference as machine


class CompileError(ValueError):
    """A source body cannot be represented by a program of this size."""


@dataclass(frozen=True)
class Prog:
    n: int
    code: tuple[int, ...]
    args: tuple[int, ...]
    out: str = "a"
    params: tuple[str, ...] = field(default=(), compare=False, repr=False)
    defs: Mapping = field(default_factory=dict, compare=False, repr=False)

    @property
    def card(self) -> Card:
        return Card("prog", "prog", (self.n, lst(self.code), lst(self.args), self.out))

    def _check_interface(self):
        if self.out != "a":
            raise ValueError("unsupported output mode")
        if any(type(address) is not int or not 0 <= address < self.n for address in self.args):
            raise ValueError("invalid argument address")

    def run(self, inputs, fuel=10000):
        self._check_interface()
        if len(inputs) != len(self.args) or any(type(value) is not int or not 0 <= value < 256
                                                for value in inputs):
            raise ValueError("program inputs must be bytes, one per parameter")
        return machine.run(machine.load(self.code, self.n, dict(zip(self.args, inputs))), fuel)


class _Assembler:
    def __init__(self):
        self.code = []
        self.slots = 0
        self.patches = []
        self.labels = {}

    def slot(self):
        slot = self.slots
        self.slots += 1
        return slot

    def emit(self, opcode, operand=0):
        self.code.extend((machine.OPCODES[opcode] if isinstance(opcode, str) else opcode, operand))

    def reference(self, opcode, target, kind="label"):
        self.emit(opcode)
        self.patches.append((len(self.code) - 1, kind, target))

    def label(self):
        return object()

    def mark(self, label):
        self.labels[label] = len(self.code)

    def finish(self, size):
        if len(self.code) + self.slots > size:
            raise CompileError(f"program needs {len(self.code) + self.slots} bytes; n={size}")
        for position, kind, target in self.patches:
            address = self.labels[target] if kind == "label" else len(self.code) + target
            self.code[position] = address
        return tuple(self.code)


def compile_tiny(body, params, defs=None, n=64) -> Prog:
    """Emit code at zero and reserve disjoint data cells after the instructions."""
    defs = dict(defs or {})
    params = tuple(params)
    errors = check_tiny(body, params, defs)
    if errors:
        raise CompileError("; ".join(errors))
    if n not in machine.SIZES:
        raise CompileError(f"n must be one of {machine.SIZES}")
    asm = _Assembler()
    inputs = tuple(asm.slot() for _ in params)

    def save(slot):
        asm.reference("ST", slot, "slot")

    def load(slot):
        asm.reference("LD", slot, "slot")

    def jump(label):
        asm.reference("JMP", label)

    def cond(node, env, loops, yes, no):
        if isinstance(node, nodes.Always):
            jump(yes)
        elif isinstance(node, nodes.Not):
            cond(node.operand, env, loops, no, yes)
        elif isinstance(node, nodes.And):
            middle = asm.label()
            cond(node.left, env, loops, middle, no)
            asm.mark(middle)
            cond(node.right, env, loops, yes, no)
        elif isinstance(node, nodes.Or):
            middle = asm.label()
            cond(node.left, env, loops, yes, middle)
            asm.mark(middle)
            cond(node.right, env, loops, yes, no)
        else:
            expression(node.expr.args[0], env, loops)
            asm.reference("JZ", yes)
            jump(no)

    def expression(node, env, loops):
        if isinstance(node, nodes.Var):
            load(env[node.name])
        elif isinstance(node, nodes.Lit):
            asm.emit("LDI", node.value)
        elif isinstance(node, nodes.Let):
            expression(node.value, env, loops)
            slot = asm.slot()
            save(slot)
            expression(node.body, {**env, node.name: slot}, loops)
        elif isinstance(node, nodes.Case):
            if node.default is None:
                raise CompileError("case without default cannot preserve Bottom(no_branch)")
            end = asm.label()
            for test, arm in node.arms:
                yes, no = asm.label(), asm.label()
                cond(test, env, loops, yes, no)
                asm.mark(yes)
                expression(arm, env, loops)
                jump(end)
                asm.mark(no)
            expression(node.default, env, loops)
            asm.mark(end)
        elif isinstance(node, nodes.Rec):
            slots = tuple(asm.slot() for _ in node.params)
            for arg, slot in zip(node.args, slots):
                expression(arg, env, loops)
                save(slot)
            start, exit_label = asm.label(), asm.label()
            asm.mark(start)
            expression(node.body, {**env, **dict(zip(node.params, slots))},
                       {**loops, node.fn: (slots, start, exit_label)})
            asm.mark(exit_label)
        elif isinstance(node, nodes.Call):
            if node.fn in loops:
                slots, start, _ = loops[node.fn]
                staged = []
                for arg in node.args:
                    expression(arg, env, loops)
                    slot = asm.slot()
                    save(slot)
                    staged.append(slot)
                for source, target in zip(staged, slots):
                    load(source)
                    save(target)
                jump(start)
            elif node.fn in defs:
                dep_body, dep_params = definition(defs[node.fn])
                staged = []
                for arg in node.args:
                    expression(arg, env, loops)
                    slot = asm.slot()
                    save(slot)
                    staged.append(slot)
                expression(dep_body, dict(zip(dep_params, staged)), {})
            else:
                if isinstance(node.args[1], nodes.Lit):
                    expression(node.args[0], env, loops)
                    asm.emit("ADDI", (node.args[1].value if node.fn == "add"
                                      else -node.args[1].value) % 256)
                    return
                expression(node.args[0], env, loops)
                left = asm.slot()
                save(left)
                expression(node.args[1], env, loops)
                if node.fn == "add":
                    asm.reference("ADD", left, "slot")
                else:
                    right = asm.slot()
                    save(right)
                    load(left)
                    asm.reference("SUB", right, "slot")

    expression(body, dict(zip(params, inputs)), {})
    asm.emit("HALT")
    return Prog(n, asm.finish(n), tuple(len(asm.code) + index for index in inputs),
                params=params, defs=defs)
