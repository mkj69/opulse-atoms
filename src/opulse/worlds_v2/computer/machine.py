"""Machine state, host codec and layer-0 operations (spec sections 2.3 and 15).

The immutable host State is bijective with a machine_state Card on valid states.
The two arrays are Card('array[4,byte]'/'array[256,byte]', 'array', items).
Only the program runner owns a program; state and memory contain bytes only.
"""

from __future__ import annotations

from dataclasses import dataclass

from opulse.atoms.values import Bottom, Card, boolean, truth

REGISTERS = tuple(Card("reg", f"r{index}") for index in range(4))


@dataclass(frozen=True)
class State:
    regs: tuple[int, int, int, int] = (0, 0, 0, 0)
    mem: bytes = bytes(256)
    zero: bool = False
    carry: bool = False

    def __post_init__(self) -> None:
        if (type(self.regs) is not tuple or len(self.regs) != 4
                or any(not byte_ok(item) for item in self.regs)
                or type(self.mem) is not bytes or len(self.mem) != 256
                or type(self.zero) is not bool or type(self.carry) is not bool):
            raise ValueError("invalid machine state")


def byte_ok(value: object) -> bool:
    return type(value) is int and 0 <= value < 256


def reg_index(value: object) -> int | None:
    if isinstance(value, Card) and value in REGISTERS:
        return REGISTERS.index(value)
    return None


def to_card(state: State) -> Card:
    if not isinstance(state, State):
        raise TypeError("invalid machine state")
    return Card("machine_state", "machine", (
        Card("array[4,byte]", "array", state.regs),
        Card("array[256,byte]", "array", tuple(state.mem)),
        boolean(state.zero), boolean(state.carry),
    ))


def from_card(value: Card) -> State:
    if not isinstance(value, Card) or value.sort != "machine_state" or value.tag != "machine" or len(value.fields) != 4:
        raise ValueError("invalid machine state card")
    regs, mem, zero, carry = value.fields
    if (not isinstance(regs, Card) or (regs.sort, regs.tag) != ("array[4,byte]", "array")
            or not isinstance(mem, Card) or (mem.sort, mem.tag) != ("array[256,byte]", "array")
            or len(regs.fields) != 4 or len(mem.fields) != 256
            or any(not byte_ok(item) for item in (*regs.fields, *mem.fields))):
        raise ValueError("invalid machine state arrays")
    if not all(isinstance(flag, Card) and flag.sort == "bool" and flag.tag in ("true", "false") and not flag.fields
               for flag in (zero, carry)):
        raise ValueError("invalid machine state flags")
    try:
        flags = (truth(zero), truth(carry))
    except TypeError as exc:
        raise ValueError("invalid machine state flags") from exc
    return State(tuple(regs.fields), bytes(mem.fields), *flags)


def _args(state: object, register: object, address: object = None) -> tuple[State, int] | None:
    index = reg_index(register)
    if not isinstance(state, State) or index is None or (address is not None and not byte_ok(address)):
        return None
    return state, index


def read(state: State, register: Card) -> int | Bottom:
    args = _args(state, register)
    return args[0].regs[args[1]] if args is not None else Bottom("invalid")


def write(state: State, register: Card, byte: int) -> State | Bottom:
    args = _args(state, register)
    if args is None or not byte_ok(byte):
        return Bottom("invalid")
    state, index = args
    regs = list(state.regs)
    regs[index] = byte
    return State(tuple(regs), state.mem, state.zero, state.carry)


def load(state: State, register: Card, address: int) -> State | Bottom:
    args = _args(state, register, address)
    return write(state, register, state.mem[address]) if args is not None and byte_ok(address) else Bottom("invalid")


def store(state: State, register: Card, address: int) -> State | Bottom:
    args = _args(state, register, address)
    if args is None or not byte_ok(address):
        return Bottom("invalid")
    memory = bytearray(state.mem)
    memory[address] = state.regs[args[1]]
    return State(state.regs, bytes(memory), state.zero, state.carry)


def add(state: State, destination: Card, source: Card) -> State | Bottom:
    args = _args(state, destination)
    source_index = reg_index(source)
    if args is None or source_index is None:
        return Bottom("invalid")
    index = args[1]
    total = state.regs[index] + state.regs[source_index]
    regs = list(state.regs)
    regs[index] = total & 255
    return State(tuple(regs), state.mem, regs[index] == 0, total > 255)


def dec(state: State, register: Card) -> State | Bottom:
    args = _args(state, register)
    if args is None:
        return Bottom("invalid")
    index = args[1]
    regs = list(state.regs)
    regs[index] = (regs[index] - 1) & 255
    return State(tuple(regs), state.mem, regs[index] == 0, state.regs[index] == 0)


def is_zero(state: State, register: Card) -> Card | Bottom:
    args = _args(state, register)
    return boolean(args[0].regs[args[1]] == 0) if args is not None else Bottom("invalid")


def flags(state: State) -> Card | Bottom:
    if not isinstance(state, State):
        return Bottom("invalid")
    return Card("flags", "flags", (boolean(state.zero), boolean(state.carry)))


def view(state: State, name: str = "io") -> tuple[int, ...]:
    """Learner view only; a task's judge always receives the original state."""
    if name == "io":
        return (state.regs[1], state.regs[2], state.regs[0])
    if name == "all_registers":
        return state.regs
    raise ValueError("unknown learner view")


def contract_projection(state: State, fields: tuple[str, ...] = ("r0",)) -> tuple:
    """Project for a particular task, never for unfold-equivalence checking."""
    available = {"r0": state.regs[0], "r1": state.regs[1],
                 "r2": state.regs[2], "r3": state.regs[3],
                 "mem": state.mem, "zero": state.zero, "carry": state.carry}
    return tuple(available[name] for name in fields)


def given_mul(state: State) -> State | Bottom:
    """Reference computer_a: r0 := r1*r2 mod 256; preserve all other fields."""
    if not isinstance(state, State):
        return Bottom("invalid")
    regs = (state.regs[1] * state.regs[2] & 255, *state.regs[1:])
    return State(regs, state.mem, state.zero, state.carry)


RULES = {
    "read": "Return the byte in the selected register; state and flags are unchanged.",
    "write": "Set the selected register to the byte; preserve all other registers, memory, zero and carry.",
    "load": "Set the selected register to mem[address]; preserve memory and both flags.",
    "store": "Set mem[address] to the selected register's byte; preserve registers and both flags.",
    "add": "Set rd to (rd + rs) mod 256; carry is true iff the sum exceeds 255; zero is true iff the result equals 0; other registers and memory are unchanged.",
    "dec": "Set r to (r - 1) mod 256; zero is true iff the result equals 0; carry is true iff the old r was 0 (borrow); other registers and memory are unchanged.",
    "is_zero": "Return true iff the selected register is 0; state and flags are unchanged.",
    "mul": "Set r0 to (r1 * r2) mod 256; preserve r1, r2, r3, memory, zero and carry.",
}
