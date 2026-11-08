"""Layer-0 computer operations and reversible host codec (spec section 15)."""

import pytest

from opulse.atoms.values import FALSE, TRUE, Bottom, Card
from opulse.worlds_v2.computer import machine


def test_codec_and_operations():
    state = machine.State((255, 1, 0, 9), bytes([7]) + bytes(255), True, True)
    assert machine.from_card(machine.to_card(state)) == state
    assert machine.to_card(machine.from_card(machine.to_card(state))) == machine.to_card(state)
    assert machine.read(state, machine.REGISTERS[0]) == 255
    assert machine.is_zero(state, machine.REGISTERS[2]) == TRUE
    assert machine.is_zero(state, machine.REGISTERS[0]) == FALSE
    assert machine.flags(state) == Card("flags", "flags", (TRUE, TRUE))
    assert machine.view(state) == (1, 0, 255)
    assert machine.view(state, "all_registers") == state.regs
    assert machine.contract_projection(state, ("r0", "mem")) == (255, state.mem)
    assert machine.write(state, machine.REGISTERS[0], 0).zero is True
    assert machine.load(state, machine.REGISTERS[1], 0).regs[1] == 7
    stored = machine.store(state, machine.REGISTERS[0], 255)
    assert stored.mem[255] == 255 and stored.regs == state.regs
    added = machine.add(state, machine.REGISTERS[0], machine.REGISTERS[1])
    assert added.regs[0] == 0 and added.zero and added.carry
    decremented = machine.dec(state, machine.REGISTERS[2])
    assert decremented.regs[2] == 255 and not decremented.zero and decremented.carry
    decremented = machine.dec(machine.State((0, 0, 1, 0)), machine.REGISTERS[2])
    assert decremented.zero and not decremented.carry
    assert machine.given_mul(state).regs == (0, 1, 0, 9)
    with pytest.raises(ValueError):
        machine.from_card(Card("machine_state", "machine", ()))
    with pytest.raises(TypeError):
        machine.to_card(None)


@pytest.mark.parametrize("operation,args", [
    (machine.read, (Card("reg", "bad"),)),
    (machine.write, (machine.REGISTERS[0], 256)),
    (machine.load, (machine.REGISTERS[0], -1)),
    (machine.load, (machine.REGISTERS[0], None)),
    (machine.store, (machine.REGISTERS[0], True)),
    (machine.store, (machine.REGISTERS[0], None)),
    (machine.add, (machine.REGISTERS[0], Card("reg", "bad"))),
    (machine.dec, (Card("reg", "bad"),)),
    (machine.is_zero, (Card("reg", "bad"),)),
])
def test_invalid_input_is_bottom(operation, args):
    assert operation(machine.State(), *args) == Bottom("invalid")
