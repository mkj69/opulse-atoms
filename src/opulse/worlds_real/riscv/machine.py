"""RV32I subset. Unified little-endian RAM, strict alignment, no privileged traps."""

from dataclasses import dataclass, field

MASK = 0xffffffff


def signed(value: int, bits: int = 32) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class Trap(Exception):
    """Fatal EEI trap; no instruction side effects have committed."""

    def __init__(self, reason: str, pc: int):
        self.reason, self.pc = reason, pc
        super().__init__(f"{reason} at pc={pc:#x}")


@dataclass
class Machine:
    memory: bytearray = field(default_factory=lambda: bytearray(65536))
    regs: list[int] = field(default_factory=lambda: [0] * 32)
    pc: int = 0
    trace: list[tuple[int, int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.memory, bytearray) or len(self.memory) != 65536:
            raise ValueError("memory must be exactly 65536 bytes")
        if len(self.regs) != 32 or self.regs[0] != 0 or any(type(v) is not int or not 0 <= v <= MASK for v in self.regs):
            raise ValueError("expected 32 unsigned registers with x0=0")
        if type(self.pc) is not int or not 0 <= self.pc <= MASK:
            raise ValueError("PC must be a 32-bit address")

    def clone(self) -> "Machine":
        return Machine(bytearray(self.memory), self.regs.copy(), self.pc, self.trace.copy())

    def access(self, addr: int, width: int, instruction: bool = False) -> None:
        if addr % width:
            raise Trap("instruction_address_misaligned" if instruction else "address_misaligned", self.pc)
        if addr < 0 or addr + width > len(self.memory):
            raise Trap("instruction_access_fault" if instruction else "access_fault", self.pc)

    def read(self, addr: int, width: int, instruction: bool = False) -> int:
        self.access(addr, width, instruction)
        return int.from_bytes(self.memory[addr:addr + width], "little")

    def load_program(self, words: list[int] | tuple[int, ...], addr: int = 0) -> None:
        self.access(addr, 4, True)
        if addr + len(words) * 4 > len(self.memory):
            raise ValueError("program does not fit in RAM")
        if any(type(word) is not int or not 0 <= word <= MASK for word in words):
            raise ValueError("each instruction must be a 32-bit word")
        for index, word in enumerate(words):
            self.memory[addr + 4 * index:addr + 4 * index + 4] = word.to_bytes(4, "little")


def step(machine: Machine) -> Machine:
    """Decode and execute one word; reject unimplemented/reserved encodings."""
    pc = machine.pc
    word = machine.read(pc, 4, True)
    opcode, rd = word & 127, (word >> 7) & 31
    f3, rs1, rs2, f7 = (word >> 12) & 7, (word >> 15) & 31, (word >> 20) & 31, word >> 25
    left, right = machine.regs[rs1], machine.regs[rs2]
    next_pc, result, write, store = (pc + 4) & MASK, 0, False, None
    immediate = signed(word >> 20, 12)
    if opcode == 0x33:
        if (f3, f7) == (0, 0): result = left + right
        elif (f3, f7) == (0, 32): result = left - right
        elif (f3, f7) == (1, 0): result = left << (right & 31)
        elif (f3, f7) == (2, 0): result = int(signed(left) < signed(right))
        elif (f3, f7) == (3, 0): result = int(left < right)
        elif (f3, f7) == (4, 0): result = left ^ right
        elif (f3, f7) == (5, 0): result = left >> (right & 31)
        elif (f3, f7) == (5, 32): result = signed(left) >> (right & 31)
        elif (f3, f7) == (6, 0): result = left | right
        elif (f3, f7) == (7, 0): result = left & right
        else: raise Trap("illegal_instruction", pc)
        write = True
    elif opcode == 0x13:
        if f3 == 0: result = left + immediate
        elif f3 == 2: result = int(signed(left) < immediate)
        elif f3 == 3: result = int(left < (immediate & MASK))
        elif f3 == 4: result = left ^ immediate
        elif f3 == 6: result = left | immediate
        elif f3 == 7: result = left & immediate
        elif f3 in (1, 5):
            if f3 == 1 and f7 == 0: result = left << rs2
            elif f3 == 5 and f7 == 0: result = left >> rs2
            elif f3 == 5 and f7 == 32: result = signed(left) >> rs2
            else: raise Trap("illegal_instruction", pc)
        else: raise Trap("illegal_instruction", pc)
        write = True
    elif opcode == 3:
        if f3 not in (0, 1, 2, 4, 5): raise Trap("illegal_instruction", pc)
        width = (1, 2, 4, 1, 2)[(0, 1, 2, 4, 5).index(f3)]
        addr = (left + immediate) & MASK
        result = machine.read(addr, width)
        if f3 in (0, 1): result = signed(result, width * 8)
        write = True
    elif opcode == 0x23:
        if f3 not in (0, 1, 2): raise Trap("illegal_instruction", pc)
        width = 1 << f3
        addr = (left + signed(((word >> 25) << 5) | rd, 12)) & MASK
        machine.access(addr, width)
        store = (addr, right.to_bytes(4, "little")[:width])
    elif opcode == 0x63:
        if f3 not in (0, 1, 4, 5, 6, 7): raise Trap("illegal_instruction", pc)
        conditions = {0: left == right, 1: left != right,
                      4: signed(left) < signed(right), 5: signed(left) >= signed(right),
                      6: left < right, 7: left >= right}
        if conditions[f3]:
            offset = signed(((word >> 31) << 12) | (((word >> 7) & 1) << 11) |
                            (((word >> 25) & 63) << 5) | (((word >> 8) & 15) << 1), 13)
            next_pc = (pc + offset) & MASK
            if next_pc % 4: raise Trap("instruction_address_misaligned", pc)
    elif opcode == 0x6f:
        offset = signed(((word >> 31) << 20) | (((word >> 12) & 255) << 12) |
                        (((word >> 20) & 1) << 11) | (((word >> 21) & 1023) << 1), 21)
        next_pc, result, write = (pc + offset) & MASK, (pc + 4) & MASK, True
        if next_pc % 4: raise Trap("instruction_address_misaligned", pc)
    elif opcode == 0x67:
        if f3 != 0: raise Trap("illegal_instruction", pc)
        next_pc, result, write = ((left + immediate) & MASK) & ~1, (pc + 4) & MASK, True
        if next_pc % 4: raise Trap("instruction_address_misaligned", pc)
    elif opcode in (0x37, 0x17):
        result, write = (word & 0xfffff000) + (pc if opcode == 0x17 else 0), True
    else:
        raise Trap("illegal_instruction", pc)
    if store is not None:
        addr, data = store
        machine.memory[addr:addr + len(data)] = data
    if write and rd:
        machine.regs[rd] = result & MASK
    machine.pc = next_pc
    machine.trace.append((pc, word, next_pc))
    return machine


def run_with_step(machine: Machine, stop_pc: int, fuel: int, step_fn) -> Machine:
    """Run a supplied decoder until stop_pc or until fuel is exhausted."""
    if fuel < 0 or not 0 <= stop_pc <= MASK:
        raise ValueError("invalid stop PC or fuel")
    for _ in range(fuel):
        if machine.pc == stop_pc:
            return machine
        step_fn(machine)
    if machine.pc == stop_pc:
        return machine
    raise Trap("fuel_exhausted", machine.pc)


def run(machine: Machine, stop_pc: int, fuel: int = 10000) -> Machine:
    """Stop BEFORE executing stop_pc; exhausted fuel raises, never implies success."""
    return run_with_step(machine, stop_pc, fuel, step)
