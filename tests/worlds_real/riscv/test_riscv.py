"""RV32I encoding fixtures and independently executed instruction cross-checks."""

import random

import pytest

from opulse.worlds_real.riscv import Machine, Trap, encode, run, step
from opulse.worlds_real.riscv.declaration import LADDER, STORY, WORLD
from opulse.worlds_real.riscv.encoding import BRANCH, LOAD, SHIFT, STORE, I, R
from opulse.worlds_real.riscv.oracle import oracle_step
from opulse.worlds_real.riscv.showcase import (
    FIBONACCI,
    SIGNED_SUM,
    execute,
    grade,
    showcases,
)


def cross_check(machine: Machine, count: int) -> None:
    """Compare full states, traces, and traps after each executed instruction."""
    expected = machine.clone()
    actual = machine.clone()
    for _ in range(count):
        failures = []
        for implementation, state in ((step, actual), (oracle_step, expected)):
            try:
                implementation(state)
                failures.append(None)
            except Trap as error:
                failures.append((error.reason, error.pc))
        assert failures[0] == failures[1], (failures, actual.pc, expected.pc)
        assert (actual.pc, actual.regs, actual.memory, actual.trace) == (
            expected.pc, expected.regs, expected.memory, expected.trace)
        if failures[0] is not None:
            return


@pytest.mark.parametrize("name,fields,word", [
    ("addi", {"rd": 1, "imm": 1}, 0x00100093),
    ("add", {"rd": 3, "rs1": 1, "rs2": 2}, 0x002081b3),
    ("sub", {"rd": 3, "rs1": 1, "rs2": 2}, 0x402081b3),
    ("lw", {"rd": 1, "rs1": 2, "imm": 8}, 0x00812083),
    ("sw", {"rs1": 2, "rs2": 1, "imm": 8}, 0x00112423),
    ("beq", {"rs1": 1, "rs2": 2, "imm": 8}, 0x00208463),
    ("jal", {"rd": 1, "imm": 8}, 0x008000ef),
    ("jalr", {"rs1": 1}, 0x00008067),
    ("lui", {"rd": 1, "imm": 0x12345}, 0x123450b7),
    ("auipc", {"rd": 1, "imm": 0x12345}, 0x12345097),
])
def test_published_format_encodings(name, fields, word):
    assert encode(name, **fields) == word


def test_cross_check_3000_seeded_cases():
    rng = random.Random(0x32_1)
    names = tuple(R) + tuple(I) + tuple(SHIFT) + tuple(LOAD) + tuple(STORE) + tuple(BRANCH) + ("jal", "jalr", "lui", "auipc")
    covered = set()
    for _ in range(3000):
        name = rng.choice(names)
        covered.add(name)
        machine = Machine()
        machine.pc = 0x100
        machine.regs[1:] = [rng.getrandbits(32) for _ in range(31)]
        rd, rs1, rs2 = (rng.randrange(32) for _ in range(3))
        if name in LOAD or name in STORE:
            rs1 = 5
            machine.regs[5] = 0x400
            imm = rng.choice((-16, -8, -4, 0, 4, 8, 16))
        elif name in BRANCH:
            imm = rng.choice((-4096, -2048, -4, -2, 2, 4, 2048, 4094))
        elif name == "jal":
            imm = rng.choice((-1048576, -8, -2, 2, 8, 1048574))
        elif name in SHIFT:
            imm = rng.randrange(32)
        elif name in ("lui", "auipc"):
            imm = rng.randrange(1 << 20)
        elif name == "jalr":
            rs1 = 5
            machine.regs[5] = rng.choice((0x200, 0x201, 0xffffffff))
            imm = rng.choice((-2048, -1, 0, 1, 2047))
        else:
            imm = rng.randrange(-2048, 2048)
        word = encode(name, rd, rs1, rs2, imm)
        machine.load_program([word], machine.pc)
        machine.memory[0x3f0:0x420] = rng.randbytes(48)
        cross_check(machine, 1)
    assert covered == set(names)


def test_multi_step_oracle_and_call_convention():
    machine = Machine()
    machine.load_program(FIBONACCI)
    machine.regs[1], machine.regs[10] = 0x1000, 24
    cross_check(machine, 170)
    result = execute(FIBONACCI, (24,))
    oracle = execute(FIBONACCI, (24,), oracle=True)
    assert result.regs == oracle.regs and result.pc == oracle.pc == 0x1000
    assert result.regs[10] == 46368 and result.regs[0] == 0
    assert result.trace == oracle.trace
    data = bytes([0, 127, 128, 255] * 16)
    state = execute(SIGNED_SUM, (0x400, 64), data)
    assert state.regs[10] == (0 + 127 - 128 - 1) * 16 & 0xffffffff
    assert state.regs[1] == 0x1000 and state.regs[2] == 0x2000


def test_misaligned_load_is_atomic():
    machine = Machine()
    machine.load_program((encode("lw", rd=5, rs1=0, imm=3),))
    before = machine.clone()
    with pytest.raises(Trap, match="address_misaligned"):
        step(machine)
    assert (machine.pc, machine.regs, machine.memory, machine.trace) == (
        before.pc, before.regs, before.memory, before.trace)
    cross_check(machine, 1)


def test_illegal_instruction_traps():
    machine = Machine()
    machine.load_program((0xffffffff,))
    with pytest.raises(Trap, match="illegal_instruction"):
        step(machine)
    cross_check(machine, 1)


def test_fuel_exhaustion_is_a_trap():
    machine = Machine()
    machine.load_program((encode("jal", imm=0),))
    with pytest.raises(Trap, match="fuel_exhausted"):
        run(machine, 0x1000, 9)
    assert machine.pc == 0 and len(machine.trace) == 9


def test_store_modifies_future_instruction():
    machine = Machine()
    replacement = encode("addi", rd=7, imm=17)
    machine.regs[5] = replacement
    machine.load_program((encode("sw", rs1=0, rs2=5, imm=4), encode("addi", rd=7, imm=1)))
    run(machine, 8)
    assert machine.regs[7] == 17
    assert machine.read(4, 4, True) == replacement


def test_jalr_clears_low_bit_and_preserves_x0():
    machine = Machine()
    machine.load_program((encode("jalr", rd=0, rs1=5),))
    machine.regs[5] = 9
    cross_check(machine, 1)
    step(machine)
    assert machine.pc == 8 and machine.regs[0] == 0


def test_misaligned_jump_is_atomic():
    machine = Machine()
    machine.load_program((encode("jal", rd=1, imm=2),))
    cross_check(machine, 1)
    with pytest.raises(Trap, match="instruction_address_misaligned"):
        step(machine)
    assert machine.regs[1] == 0 and not machine.trace


def test_showcase_oracle_grades():
    tasks = showcases()
    assert [task.angle for task in tasks] == ["compute", "invert", "decide", "induce", "create"]
    assert tasks[2].answer is False
    for task in tasks:
        answer = task.answer["words"] if task.angle == "create" else task.answer
        assert grade(task, answer), task.angle
    assert not grade(tasks[4], (encode("jalr", rs1=1),))
    assert not grade(tasks[0], -1)


def test_declaration_four_kinds_and_layers():
    assert all(WORLD["layer0"][key] for key in ("objects", "operations", "combinators", "observations"))
    assert len(STORY) == 11 and {row["kind"] for row in STORY} == set(WORLD["open_kinds"])
    assert [level["level"] for level in LADDER] == [1, 2, 3, 4, 5]


def test_create_rejects_unrelated_memory_write():
    task = showcases()[-1]
    candidate = SIGNED_SUM[:-1] + (encode("sw", rs1=0, rs2=1, imm=0x500), SIGNED_SUM[-1])
    assert not grade(task, candidate)


def test_create_rejects_code_mutation():
    task = showcases()[-1]
    candidate = SIGNED_SUM[:-1] + (encode("sw", rs1=0, rs2=1, imm=0), SIGNED_SUM[-1])
    assert not grade(task, candidate)


def test_create_rejects_clobbered_caller_saved_register():
    task = showcases()[-1]
    candidate = SIGNED_SUM[:-1] + (encode("addi", rd=5, imm=42), SIGNED_SUM[-1])
    assert not grade(task, candidate)


def test_data_cannot_extend_fixed_ram():
    with pytest.raises(ValueError, match="data does not fit"):
        execute(SIGNED_SUM, (0x400, 0), bytes(65536))


@pytest.mark.parametrize("size", (65535, 65537))
def test_machine_requires_fixed_ram(size):
    with pytest.raises(ValueError, match="65536"):
        Machine(memory=bytearray(size))


def test_oracle_run_fuel_exhaustion_is_a_trap():
    with pytest.raises(Trap, match="fuel_exhausted"):
        execute((encode("jal", imm=0),), oracle=True, limit=3)


def test_core_world_and_definition_records_load():
    pytest.importorskip("opulse.atoms.world", reason="core WorldDecl is supplied by atoms-v2 integration")
    from opulse.atoms.check import check_definition
    from opulse.atoms.spec import Definition
    from opulse.atoms.world import WorldDecl

    world = WorldDecl.from_dict(WORLD)
    assert world.world == "riscv-rv32i"
    for row in WORLD["story"]:
        definition = Definition.from_dict(row["definition"])
        assert not definition.validate(), definition.name
        assert not check_definition(definition, world, lambda name: None), definition.name


def test_core_definition_check_verify_and_promote():
    pytest.importorskip("opulse.atoms.world", reason="core WorldDecl is supplied by atoms-v2 integration")
    from dataclasses import replace

    from opulse.atoms.check import check_definition
    from opulse.atoms.spec import Contract, Definition, Evidence, advance
    from opulse.atoms.world import DerivedWorld, WorldDecl
    world = WorldDecl.from_dict(WORLD)
    definition = Definition.from_dict(WORLD["story"][3]["definition"])
    assert not check_definition(definition, world, lambda name: None)
    checked = replace(definition, status=advance(definition.status, "checked"))
    callable_definition = replace(checked, status=advance(checked.status, "callable"))
    words = (encode("addi", rd=10, imm=7), encode("jalr", rs1=1),
             encode("sw", rs1=0, rs2=1, imm=0x500), encode("lw", rd=10, imm=3))
    for word in words:
        machine = Machine()
        machine.load_program((word,))
        machine.regs[1] = 0x1000
        cross_check(machine, 1)
    evidence = Evidence("bounded", {"domain": "these four single-step RV32I words", "size": len(words)},
                        world_hash=world.world_hash())
    verified = replace(callable_definition, status=advance(callable_definition.status, "verified"),
                       evidence=evidence)
    promoted = replace(verified, status=advance(verified.status, "promoted"),
                       contract=Contract("matches independent step oracle on the four recorded words"))
    assert not promoted.validate()
    assert DerivedWorld.build(world, (promoted,)).scopes()[definition.name] == evidence.scope


def test_core_library_verifies_and_promotes_riscv_word_definition():
    pytest.importorskip("opulse.atoms.world", reason="core WorldDecl is supplied by atoms-v2 integration")
    from dataclasses import replace

    from opulse.atoms.library import Library, exhaustive
    from opulse.atoms.spec import Contract, Definition, Edge, OperationSpec
    from opulse.atoms.world import WorldDecl

    from opulse.atoms import kernel, nodes

    world = WorldDecl.from_dict(WORLD)
    library = Library(world, [kernel.Atom("identity_word", 1, lambda value: value)])
    spec = OperationSpec("restate_word", "transform", (Edge("Word"),), Edge("Word"),
                         "Keep the supplied register word", extra={"input_names": ["value"]})
    definition = Definition("restate_word", "operation", "invented", 1, ("identity_word",),
                            spec, nodes.Call("identity_word", (nodes.Var("value"),)))
    library.write(definition)
    library.check(definition.name)
    library.make_callable(definition.name, ((7,),))
    request = replace(exhaustive(((0, 1, 0xffffffff),), "three RV32I register words"),
                      reference=lambda value: value)
    assert library.verify(definition.name, request).status == "verified"
    library.promote(definition.name, Contract("preserves these three 32-bit words"))
    assert library.derived_world().scopes()[definition.name]["size"] == 3
