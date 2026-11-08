"""Eight-bit Harvard machine and a ten-layer, fully checkable definition tower.

Copied from atoms/depth/out/computer.py as an independent design reference.
All arithmetic on machine bytes goes through the given atomic instructions.
Static Vec addresses are compile-time operands of an unrolled program. Address
255 is reserved as the dot-product accumulator, never as vector input.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


def byte(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 256:
        raise ValueError("byte outside 0..255")
    return value


def address(value):
    return byte(value)


REGS = ("A", "B", "C", "D")


@dataclass
class Machine:
    regs: list = field(default_factory=lambda: [0] * 4)
    memory: list = field(default_factory=lambda: [0] * 256)
    pc: int = 0
    z: int = 0

    def __post_init__(self):
        if len(self.regs) != 4 or len(self.memory) != 256:
            raise ValueError("invalid machine dimensions")
        for value in self.regs + self.memory:
            byte(value)
        address(self.pc)
        if self.z not in (0, 1):
            raise ValueError("invalid zero flag")

    def copy(self):
        return Machine(self.regs.copy(), self.memory.copy(), self.pc, self.z)


def index(reg):
    if reg not in REGS:
        raise ValueError("invalid register")
    return REGS.index(reg)


def put(state, reg, value):
    state.regs[index(reg)] = byte(value)
    state.z = int(value == 0)
    state.pc = (state.pc + 1) % 256
    return state


def add(state, dst, src):
    destination, source = index(dst), index(src)
    state.regs[destination] = (state.regs[destination] + state.regs[source]) % 256
    state.z = int(state.regs[destination] == 0)
    state.pc = (state.pc + 1) % 256
    return state


def dec(state, reg):
    destination = index(reg)
    state.regs[destination] = (state.regs[destination] - 1) % 256
    state.z = int(state.regs[destination] == 0)
    state.pc = (state.pc + 1) % 256
    return state


def load(state, reg, addr):
    state.regs[index(reg)] = state.memory[address(addr)]
    state.z = int(state.regs[index(reg)] == 0)
    state.pc = (state.pc + 1) % 256
    return state


def store(state, addr, reg):
    state.memory[address(addr)] = state.regs[index(reg)]
    state.pc = (state.pc + 1) % 256
    return state


def b_nonzero(state):
    return state.regs[1] != 0


def always(state):
    return True


def branch(state, predicate, target):
    state.pc = address(target) if predicate(state) else (state.pc + 1) % 256
    return state


def seq(first, second, state):
    return second(first(state))


def out(state):
    return state.regs[0]


def regs(state):
    return tuple(state.regs)


def at(state, addr):
    scratch = snapshot(state)
    load(scratch, "C", addr)
    return scratch.regs[2]


def snapshot(state):
    return state.copy()


def b(state):
    return state.regs[1]


def c(state):
    return state.regs[2]


def d(state):
    return state.regs[3]


def pc(state):
    return state.pc


def z(state):
    return state.z


def while_b(body, state):
    """External code block: test at pc=0, body at pc=2, exit at pc=1.

    Fuel bound is 256 tests (B decreases in the admissible body contract).
    The caller supplies a body that decrements B exactly once per iteration.
    """
    state.pc = 0
    for _ in range(256):
        branch(state, b_nonzero, 2)
        if state.pc == 1:
            return state
        body(state)
        branch(state, always, 0)
    raise RuntimeError("Unknown(resource): loop fuel exhausted")


def mul_into(state):
    """A := A + B*C mod 256; B := 0; C,D,memory untouched.

    Output pc=1. z=1 for positive B, otherwise the incoming z is kept.
    """
    def body(current):
        add(current, "A", "C")
        dec(current, "B")

    return while_b(body, state)


@dataclass(frozen=True)
class Vec:
    start: int
    length: int

    def __post_init__(self):
        address(self.start)
        if not isinstance(self.length, int) or isinstance(self.length, bool):
            raise TypeError("invalid vector length")
        if not 0 <= self.length <= 32 or self.start + self.length > 255:
            raise ValueError("vector includes reserved 255 or exceeds 32 cells")


def dot_step(state, xaddr, yaddr):
    load(state, "C", xaddr)
    load(state, "B", yaddr)
    put(state, "A", 0)
    mul_into(state)
    load(state, "D", 255)
    add(state, "D", "A")
    store(state, 255, "D")
    return state


def zip_fold(step, state, left, right):
    if left.length != right.length:
        raise ValueError("zip length mismatch")
    for offset in range(left.length):
        state = step(state, left.start + offset, right.start + offset)
    return state


def dot(state, left, right):
    put(state, "D", 0)
    store(state, 255, "D")
    return zip_fold(dot_step, state, left, right)


def mul_carry(left, right):
    """High byte of an unsigned 8x8 product, from carry events, not * ."""
    state = Machine(regs=[0, right, left, 0])
    carries = 0

    def carry_step(current):
        nonlocal carries
        before = out(current)
        add(current, "A", "C")
        if current.regs[0] < before:
            carries += 1
        dec(current, "B")

    while_b(carry_step, state)
    check = Machine(regs=[0, right, left, 0])
    assert state.regs[0] == mul_into(check).regs[0]
    return byte(carries)


@dataclass(frozen=True)
class Wide:
    lo: int
    mid: int
    hi: int

    def __post_init__(self):
        for value in (self.lo, self.mid, self.hi):
            byte(value)


def byte_sum(left, right):
    """Use the base add instruction; compare the output to detect carry."""
    state = Machine(regs=[left, 0, right, 0])
    add(state, "A", "C")
    return state.regs[0], int(state.regs[0] < left)


def wide_add(left, right):
    low, carry_low = byte_sum(left.lo, right.lo)
    middle, carry_middle = byte_sum(left.mid, right.mid)
    middle, extra_middle = byte_sum(middle, carry_low)
    high, carry_high = byte_sum(left.hi, right.hi)
    high, extra_high = byte_sum(high, carry_middle + extra_middle)
    if carry_high or extra_high:
        raise ValueError("24-bit sum overflow")
    return Wide(low, middle, high)


def wide_dot(state, left, right):
    if left.length != right.length:
        raise ValueError("zip length mismatch")
    modular = dot(state.copy(), left, right)
    total = zip_fold(lambda total, xaddr, yaddr: wide_step(state, total, xaddr, yaddr),
                     Wide(0, 0, 0), left, right)
    assert total.lo == modular.regs[3] == modular.memory[255]
    return total


def wide_step(state, total, xaddr, yaddr):
    first = at(state, xaddr)
    second = at(state, yaddr)
    product = Machine(regs=[0, second, first, 0])
    mul_into(product)
    return wide_add(total, Wide(out(product), mul_carry(first, second), 0))


def dot_wrap(state, left, right):
    result = wide_dot(state, left, right)
    return result.mid != 0 or result.hi != 0


def machine_with(left_start, left_values, right_start, right_values):
    state = Machine()
    state.memory[left_start:left_start + len(left_values)] = left_values
    state.memory[right_start:right_start + len(right_values)] = right_values
    return state


def full_state_mul_check():
    """All B,C pairs in deterministic varied contexts; compare full resulting state."""
    memory = [(position * 37 + 11) % 256 for position in range(256)]
    for left in range(256):
        for right in range(256):
            start = Machine([((left * 13 + right * 7) % 256), right, left,
                             (left ^ right) % 256], memory.copy(),
                            (left + right) % 256, (left ^ right) & 1)
            slow = mul_into(start.copy())
            fast = start.copy()
            fast.regs[0] = (start.regs[0] + left * right) % 256
            fast.regs[1] = 0
            fast.pc = 1
            if right:
                fast.z = 1
            assert slow == fast


def examples():
    first = machine_with(16, [17, 29, 43, 61, 79, 101, 127, 149],
                         64, [13, 23, 37, 41, 53, 67, 71, 83])
    left, right = Vec(16, 8), Vec(64, 8)
    shifted = Machine(regs=[5, 3, 4, 91], memory=[7] * 256, pc=77, z=0)
    loop = while_b(lambda current: seq(lambda state: add(state, "A", "C"),
                                        lambda state: dec(state, "B"), current), shifted)
    multiplied = mul_into(Machine(regs=[5, 13, 20, 91], pc=77, z=0))
    single = first.copy()
    single.memory[255] = 9
    dot_step(single, 16, 64)
    folded = first.copy()
    folded.memory[255] = 9
    zip_fold(dot_step, folded, left, right)
    dotted = dot(first.copy(), left, right)
    wide = wide_dot(first, left, right)
    return {
        "loop": [out(loop), loop.regs[1], loop.pc, loop.z],
        "multiply": [out(multiplied), multiplied.regs[1], multiplied.pc, multiplied.z],
        "vec": [left.start, left.length],
        "read": at(first, 18),
        "step": [single.regs[3], single.memory[255], single.pc],
        "fold": [folded.regs[3], folded.memory[255], folded.pc],
        "dot": [dotted.regs[3], dotted.memory[255], dotted.pc],
        "carry": mul_carry(201, 173),
        "wide_type": [wide.lo, wide.mid, wide.hi],
        "wide": [wide.lo, wide.mid, wide.hi],
        "wrap": dot_wrap(first, left, right),
    }


def showcases():
    left = Vec(16, 16)
    right = Vec(64, 16)
    first = [17, 29, 43, 61, 79, 101, 127, 149, 163, 181, 197, 211, 223, 229, 241, 253]
    second = [13, 23, 37, 41, 53, 67, 71, 83, 97, 103, 109, 113, 131, 137, 139, 151]
    state = machine_with(16, first, 64, second)
    wide = wide_dot(state, left, right)
    computed = {"wide": [wide.lo, wide.mid, wide.hi],
                "dot": dot(state.copy(), left, right).regs[3],
                "wrap": dot_wrap(state, left, right)}

    first = [4, 0, 13, 7, 19, 23, 5, 11]
    second = [17, 29, 9, 0, 6, 12, 27, 3]
    left, right = Vec(32, 8), Vec(40, 8)
    base = machine_with(32, first, 40, second)
    base.memory[33] = 17
    base.memory[43] = 19
    reference = wide_dot(base, left, right)
    target = reference.lo + 256 * reference.mid + 65536 * reference.hi
    matches = []
    for candidate_x in range(32):
        for candidate_y in range(32):
            base.memory[33] = candidate_x
            base.memory[43] = candidate_y
            result = wide_dot(base, left, right)
            if result.lo + 256 * result.mid + 65536 * result.hi == target:
                matches.append([candidate_x, candidate_y])
    computed["inverse_target"] = target
    computed["inverse"] = matches

    left, right = Vec(80, 12), Vec(120, 12)
    state = machine_with(80, [21, 33, 47, 58, 69, 72, 85, 96, 107, 118, 129, 140],
                         120, [119, 108, 97, 86, 75, 64, 53, 42, 31, 20, 9, 254])
    other = state.copy()
    other.memory[91] = (other.memory[91] + 128) % 256
    modular = [dot(state.copy(), left, right).regs[3],
               dot(other.copy(), left, right).regs[3]]
    exact = [wide_dot(state, left, right), wide_dot(other, left, right)]
    computed["decide"] = {
        "same_modular": modular[0] == modular[1],
        "same_wide": exact[0] == exact[1],
        "modular": modular,
        "wide": [[value.lo, value.mid, value.hi] for value in exact],
    }
    return computed


if __name__ == "__main__":
    expected_examples = {
        "loop": [17, 0, 1, 1], "multiply": [9, 0, 1, 1], "vec": [16, 8],
        "read": 43, "step": [230, 230, 4], "fold": [207, 207, 4],
        "dot": [198, 198, 4], "carry": 135, "wide_type": [198, 145, 0],
        "wide": [198, 145, 0], "wrap": True,
    }
    expected_showcases = {
        "wide": [32, 206, 3], "dot": 32, "wrap": True,
        "inverse_target": 1369, "inverse": [[17, 19]],
        "decide": {"same_modular": True, "same_wide": False,
                   "modular": [40, 40], "wide": [[40, 42, 1], [40, 171, 0]]},
    }
    assert examples() == expected_examples
    assert showcases() == expected_showcases
    full_state_mul_check()
    assert len(Vec(223, 32).__dict__) == 2
    for bad_start, bad_length in [(224, 32), (254, 2), (0, 33)]:
        try:
            Vec(bad_start, bad_length)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid Vec accepted")
    for first in range(8):
        for second in range(8):
            for third in range(8):
                for fourth in range(8):
                    state = machine_with(0, [first, second], 2, [third, fourth])
                    result = wide_dot(state, Vec(0, 2), Vec(2, 2))
                    exact = first * third + second * fourth
                    assert result == Wide(exact % 256, exact // 256, 0)
                    assert dot(state.copy(), Vec(0, 2), Vec(2, 2)).regs[3] == exact % 256
    catalog = json.loads(Path(__file__).with_suffix(".json").read_text())
    assert [item["value"] for item in catalog["tower"]] == list(expected_examples.values())
    assert [item["answer"] for item in catalog["showcase"]] == [
        {key: expected_showcases[key] for key in ("wide", "dot", "wrap")},
        expected_showcases["inverse"], expected_showcases["decide"]]
    print("OK")
