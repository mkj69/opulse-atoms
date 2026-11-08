"""Executable form of the ``vn/1`` instruction set (docs/spec/atoms-meta.md, section 4.1).

Plain Python on plain data. The machine world, the kernel-node interpreter and the compiler are
all checked against this file; it must stay a literal transcription of the spec table.
"""

from __future__ import annotations

from dataclasses import dataclass

SIZES = (16, 32, 64, 256)
OPCODES = {"HALT": 0, "LDI": 1, "LD": 2, "ST": 3, "ADD": 4, "SUB": 5, "JMP": 6, "JZ": 7, "ADDI": 8}
NAMES = {code: name for name, code in OPCODES.items()}


@dataclass(frozen=True)
class State:
    pc: int
    a: int
    mem: tuple[int, ...]
    halted: bool = False

    def __post_init__(self) -> None:
        if len(self.mem) not in SIZES:
            raise ValueError(f"memory size must be one of {SIZES}")
        if (not all(type(b) is int and 0 <= b < 256 for b in self.mem)
                or type(self.a) is not int or not 0 <= self.a < 256):
            raise ValueError("bytes must be 0..255")
        if type(self.pc) is not int or not 0 <= self.pc < len(self.mem):
            raise ValueError("pc out of range")
        if type(self.halted) is not bool:
            raise ValueError("halted must be bool")


class Illegal(Exception):
    """Opcode 9..255: the step is Bottom(illegal)."""


def step(s: State) -> State:
    if s.halted:
        return s
    size = len(s.mem)
    op, k = s.mem[s.pc], s.mem[(s.pc + 1) % size]
    nxt = (s.pc + 2) % size
    a, mem = s.a, s.mem
    if op == 0:
        return State(s.pc, a, mem, True)
    if op == 1:
        a = k
    elif op == 2:
        a = mem[k % size]
    elif op == 3:
        mem = mem[:k % size] + (a,) + mem[k % size + 1:]
    elif op == 4:
        a = (a + mem[k % size]) % 256
    elif op == 5:
        a = (a - mem[k % size]) % 256
    elif op == 6:
        nxt = k % size
    elif op == 7:
        if a == 0:
            nxt = k % size
    elif op == 8:
        a = (a + k) % 256
    else:
        raise Illegal(op)
    return State(nxt, a, mem, False)


def run(s: State, fuel: int) -> tuple[str, State | None, int]:
    """``("ok", final, steps)``, ``("illegal", None, steps)`` or ``("fuel", None, fuel)``.

    Steps count executed instructions, HALT included; a halted start state takes 0 steps.
    """
    steps = 0
    while not s.halted:
        if steps >= fuel:
            return "fuel", None, fuel
        steps += 1
        try:
            s = step(s)
        except Illegal:
            return "illegal", None, steps
    return "ok", s, steps


def load(code: list[int] | tuple[int, ...], size: int = 16, data: dict[int, int] | None = None,
         a: int = 0, pc: int = 0) -> State:
    """A state with ``code`` at address 0 and ``data`` cells set; everything else 0."""
    mem = [0] * size
    for i, byte in enumerate(code):
        mem[i] = byte
    for addr, byte in (data or {}).items():
        mem[addr % size] = byte
    return State(pc, a, tuple(mem))
