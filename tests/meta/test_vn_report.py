"""vn/1 execution report tests (meta spec section 4.3)."""

import hashlib
import itertools
import json

from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.meta.vn import reference
from opulse.meta.vn.asm import assemble
from opulse.meta.vn.machine import to_card
from opulse.meta.vn.report import report, routine_id


def test_array_sum_rewrites_add_operand():
    source = """
        LDI 0
    loop: ADD 26
        ST 30
        LD @loop+1
        ADDI 1
        ST @loop+1
        LD 30
        SUB 31
        JZ @done
        LD 30
        JMP @loop
    done: LD 30
        HALT
    """
    code = assemble(source, 32)
    state = reference.load(code, 32, {26: 3, 27: 5, 28: 7, 31: 15})
    result = report(state, 50)
    assert result.outcome == Ok(to_card(reference.run(state, 50)[1]))
    assert result.outcome.value.fields[1] == 15
    assert result.self_modifying and result.writes_ahead and result.writes_behind
    assert len(result.versions) == 4


def test_data_only_and_equal_code_byte():
    data = report(reference.load([1, 9, 3, 12, 0, 0]), 3)
    assert data.stores == ((2, 12, 0, 9),)
    assert not data.self_modifying and len(data.versions) == 1
    equal = report(reference.load([1, 1, 3, 1, 0, 0]), 3)
    assert equal.stores == ((2, 1, 1, 1),)
    assert not equal.self_modifying


def test_ahead_behind_and_outcomes():
    behind_state = reference.load([1, 5, 3, 0, 0, 0])
    behind = report(behind_state, 3)
    assert behind.self_modifying and behind.writes_behind and not behind.writes_ahead
    ahead = report(reference.load([1, 8, 3, 6, 6, 6, 0, 0]), 5)
    assert ahead.self_modifying and ahead.writes_ahead and not ahead.writes_behind
    assert report(reference.load([6, 0]), 3).outcome == Unknown("fuel")
    assert report(reference.load([9, 0]), 1).outcome == Bottom("illegal")
    assert len({image.identity for image in behind.versions}) == 2
    initial = behind.versions[0]
    payload = [[address, behind_state.mem[address]] for address in sorted(behind.fetched)]
    assert initial.identity == hashlib.sha256(
        f"opulse.vn/1\n16\n{json.dumps(payload, separators=(',', ':'))}".encode("ascii")
    ).hexdigest()
    assert routine_id(16, 0, [1, 5]) != routine_id(16, 0, [1, 6])
    assert routine_id(16, 0, [1, 5]) != routine_id(16, 1, [1, 5])


def _brute_self_modifying(state, fuel):
    snapshots = []
    stores = []
    for _ in range(fuel):
        if state.halted:
            break
        pc = state.pc
        snapshots.append((pc, (pc + 1) % len(state.mem)))
        opcode, operand = state.mem[pc], state.mem[(pc + 1) % len(state.mem)]
        if opcode == 3:
            address = operand % len(state.mem)
            stores.append((address, state.mem[address], state.a))
        try:
            state = reference.step(state)
        except reference.Illegal:
            break
    fetched = set(itertools.chain.from_iterable(snapshots))
    return any(address in fetched and old != new for address, old, new in stores)


def test_exhaustive_two_instruction_self_modification():
    for code in itertools.product(range(10), range(16), range(10), range(16)):
        state = reference.load(code)
        assert report(state, 20).self_modifying == _brute_self_modifying(state, 20)
