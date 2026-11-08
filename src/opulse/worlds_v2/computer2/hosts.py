"""Pure layer-zero byte-machine instructions and generic structure primitives."""

from opulse.atoms.values import Bottom, Card

REGISTERS = ("A", "B", "C", "D")
MEMORY_GRANTS = frozenset((*range(16, 48), *range(64, 96), *range(120, 132)))


def mem(current, addr):
    if type(addr) is not int or addr not in MEMORY_GRANTS:
        return Bottom("permission")
    return fields(current)[1][addr]


def reg_name(value):
    if isinstance(value, Card) and value.sort == "Reg" and not value.fields:
        return value.tag
    return value


def byte(value):
    return type(value) is int and 0 <= value < 256


def machine(regs=(0, 0, 0, 0), mem=None, pc=0, z=0):
    memory = (0,) * 256 if mem is None else tuple(mem)
    registers = tuple(regs)
    if (len(registers) != 4 or len(memory) != 256 or
            not all(map(byte, registers + memory)) or not byte(pc) or z not in (0, 1)):
        return Bottom("invalid")
    return Card("Machine", "machine", (registers, memory, pc, z))


def state(regs=(0, 0, 0, 0), changes=None, pc=0, z=0, fill=0):
    memory = [fill] * 256
    for index, value in (changes or {}).items():
        memory[index] = value
    return machine(regs, memory, pc, z)


def fields(current):
    if not isinstance(current, Card) or current.sort != "Machine":
        raise ValueError("invalid machine")
    return current.fields


def replace_state(current, *, regs=None, mem=None, pc=None, z=None):
    old_regs, old_mem, old_pc, old_z = fields(current)
    if mem is not None:
        return machine(old_regs if regs is None else regs, mem,
                       old_pc if pc is None else pc, old_z if z is None else z)
    if ((regs is not None and (len(regs) != 4 or not all(map(byte, regs)))) or
            (pc is not None and not byte(pc)) or
            (z is not None and z not in (0, 1))):
        return Bottom("invalid")
    return Card("Machine", "machine", (old_regs if regs is None else tuple(regs), old_mem,
                                       old_pc if pc is None else pc, old_z if z is None else z))


def register(current, reg):
    reg = reg_name(reg)
    if reg not in REGISTERS:
        return Bottom("invalid_reg")
    return fields(current)[0][REGISTERS.index(reg)]


def put(current, reg, value):
    reg = reg_name(reg)
    if reg not in REGISTERS:
        return Bottom("invalid_reg")
    if not byte(value):
        return Bottom("invalid_byte")
    regs, _, pc, _ = fields(current)
    updated = list(regs)
    updated[REGISTERS.index(reg)] = value
    return replace_state(current, regs=updated, pc=(pc + 1) % 256, z=int(value == 0))


def add(current, dst, src):
    dst, src = reg_name(dst), reg_name(src)
    if dst not in REGISTERS or src not in REGISTERS:
        return Bottom("invalid_reg")
    return put(current, dst, (register(current, dst) + register(current, src)) % 256)


def dec(current, reg):
    reg = reg_name(reg)
    if reg not in REGISTERS:
        return Bottom("invalid_reg")
    return put(current, reg, (register(current, reg) - 1) % 256)


def load(current, reg, addr):
    reg = reg_name(reg)
    if not byte(addr):
        return Bottom("invalid_addr")
    return put(current, reg, fields(current)[1][addr])


def store(current, addr, reg):
    reg = reg_name(reg)
    if not byte(addr):
        return Bottom("invalid_addr")
    if reg not in REGISTERS:
        return Bottom("invalid_reg")
    regs, mem, pc, _ = fields(current)
    updated = list(mem)
    updated[addr] = regs[REGISTERS.index(reg)]
    return replace_state(current, mem=updated, pc=(pc + 1) % 256)


def branch(current, predicate, target):
    if not byte(target):
        return Bottom("invalid_addr")
    if type(predicate) is not bool:
        return Bottom("invalid_condition")
    return replace_state(current, pc=target if predicate else (fields(current)[2] + 1) % 256)


def snapshot(current):
    regs, mem, pc, z = fields(current)
    return machine(regs, mem, pc, z)


def out(current):
    return register(current, "A")


def regs(current):
    return fields(current)[0]


def b(current):
    return register(current, "B")


def c(current):
    return register(current, "C")


def d(current):
    return register(current, "D")


def pc(current):
    return fields(current)[2]


def z(current):
    return fields(current)[3]


def inc(value):
    return value + 1


def sub(left, right):
    return left - right


def lt(left, right):
    return left < right


def le(left, right):
    return left <= right


def eq(left, right):
    return left == right


def byte_add(left, right):
    if not byte(left) or not byte(right):
        return Bottom("invalid_byte")
    return (left + right) % 256


def address(start, offset):
    return start + offset


def pair(first, second):
    return Card("pair", "pair", (first, second))


def first(value):
    return value.fields[0]


def second(value):
    return value.fields[1]


def vec(start, length):
    return Card("vec_base", "vec", (start, length))


def wide(lo, mid, hi):
    return Card("wide_base", "wide", (lo, mid, hi))


def vec_start(value):
    return value.fields[0]


def vec_len(value):
    return value.fields[1]


def wide_lo(value):
    return value.fields[0]


def wide_mid(value):
    return value.fields[1]


def wide_hi(value):
    return value.fields[2]


def is_vec_base(value):
    return (isinstance(value, Card) and value.sort == "vec_base" and value.tag == "vec"
            and len(value.fields) == 2 and all(type(item) is int for item in value.fields))


def is_wide_base(value):
    return (isinstance(value, Card) and value.sort == "wide_base" and value.tag == "wide"
            and len(value.fields) == 3 and all(type(item) is int for item in value.fields))


def machine_new(a, b_value, c_value, d_value):
    if not all(byte(item) for item in (a, b_value, c_value, d_value)):
        return Bottom("invalid_byte")
    return machine((a, b_value, c_value, d_value))


def to_card(value):
    if isinstance(value, tuple):
        return Card("List", "list", tuple(to_card(item) for item in value))
    if isinstance(value, Card):
        return Card(value.sort, value.tag, tuple(to_card(item) for item in value.fields))
    return value


def from_card(value):
    if isinstance(value, Card) and value.sort == "List" and value.tag == "list":
        return tuple(from_card(item) for item in value.fields)
    if isinstance(value, Card):
        return Card(value.sort, value.tag, tuple(from_card(item) for item in value.fields))
    return value


def zip_error():
    return Bottom("zip_length_mismatch")
