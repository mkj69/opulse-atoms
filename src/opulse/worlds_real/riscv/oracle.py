"""Independent RV32I step model: decode by opcode tables and bit-string fields.

No machine.step/encoding.encode imports. This is a second implementation, not
an emulator substitute; compare against external tools when they are available.
"""

from .machine import Machine, Trap


def sext(value: int, size: int) -> int:
    return (value ^ (1 << (size - 1))) - (1 << (size - 1))


def _read(state: Machine, address: int, width: int, instruction: bool = False) -> int:
    _check_address(state, address, width, instruction)
    return sum(state.memory[address + index] * (256 ** index) for index in range(width))


def _check_address(state: Machine, address: int, width: int, instruction: bool = False) -> None:
    if address & (width - 1):
        raise Trap("instruction_address_misaligned" if instruction else "address_misaligned", state.pc)
    if address < 0 or address + width > len(state.memory):
        raise Trap("instruction_access_fault" if instruction else "access_fault", state.pc)


def oracle_step(state: Machine) -> Machine:
    pc = state.pc
    instruction = _read(state, pc, 4, True)
    bits = f"{instruction:032b}"
    opcode = int(bits[25:], 2)
    destination = int(bits[20:25], 2)
    func = int(bits[17:20], 2)
    source = int(bits[12:17], 2)
    other = int(bits[7:12], 2)
    extension = int(bits[:7], 2)
    lhs, rhs = state.regs[source], state.regs[other]
    s_lhs, s_rhs = sext(lhs, 32), sext(rhs, 32)
    next_pc = (pc + 4) % (1 << 32)
    value = None
    pending = None
    if opcode == 0x33:
        operations = {
            (0, 0): lambda: lhs + rhs, (0, 32): lambda: lhs - rhs,
            (1, 0): lambda: lhs * (1 << (rhs % 32)),
            (2, 0): lambda: int(s_lhs < s_rhs), (3, 0): lambda: int(lhs < rhs),
            (4, 0): lambda: lhs ^ rhs, (5, 0): lambda: lhs // (1 << (rhs % 32)),
            (5, 32): lambda: s_lhs // (1 << (rhs % 32)),
            (6, 0): lambda: lhs | rhs, (7, 0): lambda: lhs & rhs,
        }
        if (func, extension) not in operations:
            raise Trap("illegal_instruction", pc)
        value = operations[func, extension]()
    elif opcode == 0x13:
        immediate = sext(int(bits[:12], 2), 12)
        operations = {
            0: lambda: lhs + immediate, 2: lambda: int(s_lhs < immediate),
            3: lambda: int(lhs < (immediate % (1 << 32))),
            4: lambda: lhs ^ immediate, 6: lambda: lhs | immediate,
            7: lambda: lhs & immediate,
        }
        if func in operations:
            value = operations[func]()
        elif func == 1 and extension == 0:
            value = lhs * (1 << other)
        elif func == 5 and extension in (0, 32):
            value = (s_lhs if extension else lhs) // (1 << other)
        else:
            raise Trap("illegal_instruction", pc)
    elif opcode == 3:
        widths = {0: (1, True), 1: (2, True), 2: (4, False),
                  4: (1, False), 5: (2, False)}
        if func not in widths:
            raise Trap("illegal_instruction", pc)
        width, sign = widths[func]
        address = (lhs + sext(int(bits[:12], 2), 12)) % (1 << 32)
        raw = _read(state, address, width)
        value = sext(raw, width * 8) if sign else raw
    elif opcode == 0x23:
        widths = {0: 1, 1: 2, 2: 4}
        if func not in widths:
            raise Trap("illegal_instruction", pc)
        address = (lhs + sext(int(bits[:7] + bits[20:25], 2), 12)) % (1 << 32)
        _check_address(state, address, widths[func])
        pending = (address, (rhs % (1 << (widths[func] * 8))).to_bytes(widths[func], "little"))
    elif opcode == 0x63:
        conditions = {0: lhs == rhs, 1: lhs != rhs, 4: s_lhs < s_rhs,
                      5: s_lhs >= s_rhs, 6: lhs < rhs, 7: lhs >= rhs}
        if func not in conditions:
            raise Trap("illegal_instruction", pc)
        if conditions[func]:
            offset = sext(int(bits[0] + bits[24] + bits[1:7] + bits[20:24] + "0", 2), 13)
            next_pc = (pc + offset) % (1 << 32)
    elif opcode == 0x6f:
        offset = sext(int(bits[0] + bits[12:20] + bits[11] + bits[1:11] + "0", 2), 21)
        next_pc, value = (pc + offset) % (1 << 32), (pc + 4) % (1 << 32)
    elif opcode == 0x67:
        if func:
            raise Trap("illegal_instruction", pc)
        next_pc = ((lhs + sext(int(bits[:12], 2), 12)) % (1 << 32)) & ~1
        value = (pc + 4) % (1 << 32)
    elif opcode in (0x37, 0x17):
        value = (int(bits[:20], 2) << 12) + (pc if opcode == 0x17 else 0)
    else:
        raise Trap("illegal_instruction", pc)
    if next_pc % 4:
        raise Trap("instruction_address_misaligned", pc)
    if pending is not None:
        address, data = pending
        state.memory[address:address + len(data)] = data
    if value is not None and destination:
        state.regs[destination] = value % (1 << 32)
    state.pc = next_pc
    state.trace.append((pc, instruction, next_pc))
    return state
