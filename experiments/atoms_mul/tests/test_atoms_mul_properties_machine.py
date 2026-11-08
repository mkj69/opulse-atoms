"""Random MASM source, persistent-library and independent-kernel checks."""

from copy import deepcopy
from dataclasses import replace

from atoms_mul.machine import env as machine_env
from atoms_mul.machine.check import check_program
from atoms_mul.machine.compile import compile_sub
from atoms_mul.machine.core_library import CoreMirror
from atoms_mul.machine.equiv import _fast_projection
from atoms_mul.machine.evaluate import run_blocks, run_sub
from atoms_mul.machine.lang import Instruction, Program, Sub
from atoms_mul.machine.library import Library
from hypothesis import example, given, settings
from hypothesis import strategies as st
from strategies_atoms_mul import machine_cases

from opulse.atoms import kernel as core
from opulse.atoms import nodes
from opulse.atoms.library import exhaustive
from opulse.atoms.spec import Contract
from opulse.worlds_v2.computer import reference, runner
from opulse.worlds_v2.computer.machine import State

BOUNDED = settings(max_examples=100, deadline=None, derandomize=True)


def reference_run(program, state, group, library, fuel):
    """Execute compiled blocks on the separate atoms-v2 interpreter."""
    specs = reference.atoms() if group == "A" else runner.atoms()
    atoms = [core.Atom(name, arity, function, cost=cost)
             for name, (arity, function, cost) in specs.items()]
    definitions = [core.Defn(entry.name, ("s",), nodes.from_json(entry.body))
                   for entry in library._entries.values()]
    definitions.extend(core.Defn(sub.name, ("s",), compile_sub(sub)) for sub in program.defs)
    return core.call("main", [state], core.DictScope(atoms, definitions),
                     core.Limits(fuel=fuel))


def instruction_oracle(program, state, group):
    """Interpret MASM instructions directly, without Blocks or the compiler."""
    definitions = {sub.name: sub for sub in program.defs}
    registers, memory = list(state.regs), bytearray(state.mem)
    zero, carry = state.zero, state.carry
    steps = 0

    def execute(name):
        nonlocal steps, zero, carry
        lines = definitions[name].lines
        labels = {line.args[0]: index for index, line in enumerate(lines) if line.op == "label"}
        position = 0
        while position < len(lines):
            line = lines[position]
            operation, args = line.op, line.args
            if operation == "label":
                position += 1
                continue
            if operation == "halt":
                return
            if operation in ("set", "add", "dec", "load", "store", "call", "mul"):
                steps += 1 if operation != "call" else 0
                if operation == "call":
                    execute(args[0])
                elif operation == "mul":
                    assert group == "A"
                    registers[0] = registers[1] * registers[2] & 255
                else:
                    destination = int(args[0][1:])
                    if operation == "set":
                        registers[destination] = int(args[1])
                    elif operation == "load":
                        registers[destination] = memory[int(args[1])]
                    elif operation == "store":
                        memory[int(args[1])] = registers[destination]
                    elif operation == "add":
                        total = registers[destination] + registers[int(args[1][1:])]
                        registers[destination] = total & 255
                        zero, carry = registers[destination] == 0, total > 255
                    else:
                        carry = registers[destination] == 0
                        registers[destination] = (registers[destination] - 1) & 255
                        zero = registers[destination] == 0
            elif operation in ("jz", "jnz"):
                steps += 1
                taken = (registers[int(args[0][1:])] == 0) == (operation == "jz")
                steps += 1
                position = labels[args[1]] if taken else position + 1
                continue
            else:
                steps += 1
                position = labels[args[0]]
                continue
            if position + 1 < len(lines) and lines[position + 1].op == "label":
                steps += 1
            position += 1

    execute("main")
    return State(tuple(registers), bytes(memory), zero, carry), steps


def test_instruction_oracle_counts_branch_and_memory_semantics():
    program = Program((Sub("main", (Instruction("set", ("r0", "2")),
                                    Instruction("store", ("r0", "9")),
                                    Instruction("dec", ("r0",)),
                                    Instruction("jz", ("r0", "done")),
                                    Instruction("load", ("r1", "9")),
                                    Instruction("label", ("done",)),
                                    Instruction("halt"))),), ())
    state, steps = instruction_oracle(program, State(), "B")
    assert (state.regs, state.mem[9], state.zero, state.carry, steps) == (
        (1, 2, 0, 0), 2, False, False, 7)


@given(case=machine_cases(), registers=st.tuples(*[st.integers(0, 255)] * 4),
       address=st.integers(0, 255), value=st.integers(0, 255), mask=st.integers(0, 7))
@BOUNDED
def test_machine_unfold_boundary_and_core_final_state(case, registers, address, value, mask):
    program, names, group = case
    assert not check_program(program, group, Library())
    saved = Library()
    if names:
        saved.add_from_program(program, names, "previous-task")
    pasted = Program(tuple(sub for sub in program.defs if sub.name not in names), ())
    assert not check_program(pasted, group, saved)
    memory = bytearray(256)
    memory[address] = value
    state = State(registers, bytes(memory))
    boundary = frozenset(sub.name for index, sub in enumerate(program.defs)
                         if mask & (1 << index))
    local = run_sub("main", state, group=group, program=program, fuel=1000)
    reused = run_sub("main", state, group=group, program=pasted, library=saved, fuel=1000)
    bounded = run_sub("main", state, group=group, program=pasted, library=saved,
                      boundary=boundary, fuel=1000)
    independent = reference_run(pasted, state, group, saved, 1000)
    direct_state, direct_steps = instruction_oracle(program, state, group)
    assert (local.outcome, local.steps, local.final_state) == (
        reused.outcome, reused.steps, reused.final_state)
    assert (bounded.outcome, bounded.steps, bounded.final_state, bounded.calls) == (
        reused.outcome, reused.steps, reused.final_state, reused.calls)
    assert (reused.outcome, reused.steps) == (independent.outcome, independent.steps)
    assert (reused.final_state, reused.steps) == (direct_state, direct_steps)
    if isinstance(independent.outcome, core.Ok):
        assert reused.final_state == independent.outcome.value
    assert bounded == run_sub("main", state, group=group, program=pasted,
                              library=saved, boundary=boundary, fuel=1000)


def test_empty_helper_is_one_visible_step():
    program = Program((Sub("empty", (Instruction("halt"),)),
                       Sub("main", (Instruction("call", ("empty",)), Instruction("halt")))), ())
    state = State((0, 0, 0, 0), bytes(256))
    run = run_sub("main", state, group="A", program=program, boundary=frozenset({"empty"}))
    assert run.boundary_steps == run.steps + 1  # spec 10: a kept call shows as one step


@given(case=machine_cases(), registers=st.tuples(*[st.integers(0, 255)] * 4),
       mask=st.integers(0, 7), fuel=st.sampled_from((0, 1, 1000)))
@BOUNDED
@example(case=(Program((Sub("empty", (Instruction("halt"),)),
                        Sub("main", (Instruction("call", ("empty",)), Instruction("halt")))), ()),
               (), "A"), registers=(0, 0, 0, 0), mask=1, fuel=0)
def test_random_machine_boundary_cost_bound(case, registers, mask, fuel):
    program, names, group = case
    saved = Library()
    if names:
        saved.add_from_program(program, names, "previous-task")
    pasted = Program(tuple(sub for sub in program.defs if sub.name not in names), ())
    boundary = frozenset(sub.name for index, sub in enumerate(program.defs)
                         if mask & (1 << index))
    run = run_sub("main", State(registers, bytes(256)), group=group, program=pasted,
                  library=saved, boundary=boundary, fuel=fuel)
    kept_calls = sum(run.calls.get(name, 0) for name in boundary)
    assert 0 <= run.boundary_steps <= run.steps + kept_calls + ("main" in boundary)
    if not boundary:
        assert run.boundary_steps == run.steps


@given(case=machine_cases(), registers=st.tuples(*[st.integers(0, 255)] * 4),
       delta=st.integers(-2, 2))
@settings(max_examples=50, deadline=None, derandomize=True)
def test_machine_visible_observation_cannot_change_hidden_grade(case, registers, delta):
    program, _, group = case
    state = State(registers)
    final = run_sub("main", state, group=group, program=program, fuel=1000).final_state
    task = {"statement": "Original prompt", "public_examples": [
        {"registers": list(registers), "memory": {}, "expected_r0": 0}],
        "hidden_tests": [{"registers": list(registers), "memory": {},
                          "expected_r0": (final.regs[0] + delta) & 255}]}
    library = Library()
    before = deepcopy(task)
    result = machine_env.TRACK.grade(program, task, group, library, 1000)
    assert result[1] == (delta == 0)
    for key in ("statement", "public_examples"):
        altered = deepcopy(task)
        altered[key] = "Changed prompt" if key == "statement" else [
            {"registers": [0, 0, 0, 0], "memory": {}, "expected_r0": -1}]
        visible = {field: altered[field] for field in machine_env.TRACK.visible_fields}
        feedback = machine_env.TRACK.feedback(program, visible, group, library, 1000)
        prompt = machine_env.TRACK.render_prompt(group, library, visible,
                                                  [feedback, "changed feedback"], 1000)
        assert "hidden_tests" not in prompt
        assert machine_env.TRACK.grade(program, altered, group, library, 1000) == result
    assert task == before


@given(value=st.integers(0, 254), other=st.integers(0, 255))
@settings(max_examples=20, deadline=None, derandomize=True)
def test_random_machine_promotion_preserves_exact_checked_domain(value, other):
    outside_value = other if other != value else (value + 1) & 255
    program = Program((Sub("candidate", (Instruction("set", ("r0", str(outside_value))),
                                         Instruction("jz", ("r1", "within")),
                                         Instruction("halt"), Instruction("label", ("within",)),
                                         Instruction("set", ("r0", str(value))),
                                         Instruction("halt"))),), ())
    library = Library()
    entry, = library.add_from_program(program, ["candidate"], "scope-property")
    mirror = CoreMirror("B")
    report, = mirror.mirror([entry])
    assert report["core_status"] == "callable"
    states = (State((0, 0, 0, 0)), State((0, 0, 1, 0)))
    request = exhaustive((states,), "r1=0, r2 in 0..1, other fields zero")
    def expected(state):
        return State((value, *state.regs[1:]), state.mem, state.zero, state.carry)
    mirror.library.verify("candidate", replace(request, reference=expected))
    mirror.library.account("candidate")
    mirror.library.promote("candidate", Contract("full state on checked states only"))
    promoted, = mirror.derived_world().promoted
    assert promoted.evidence.scope == mirror.derived_world().scopes()["candidate"]
    assert mirror.library.get("candidate").cost.steps["over"] == promoted.evidence.scope
    assert "checked" not in request.scope
    assert promoted.evidence.scope["checked"]["size"] == len(request.domain)
    assert promoted.evidence.scope["checked"]["sha256"]
    outside = State((0, 1, 0, 0))
    assert run_sub("candidate", outside, group="B", program=program).final_state != expected(outside)


@given(operations=st.lists(st.one_of(
    st.tuples(st.just("set"), st.integers(0, 3), st.integers(0, 255)),
    st.tuples(st.just("add"), st.integers(0, 3), st.integers(0, 3)),
    st.tuples(st.just("dec"), st.integers(0, 3), st.just(0)),
    st.tuples(st.just("load"), st.integers(0, 3), st.integers(0, 255)),
    st.tuples(st.just("store"), st.integers(0, 3), st.integers(0, 255))),
    max_size=8), registers=st.tuples(*[st.integers(0, 255)] * 4),
       address=st.integers(0, 255), byte=st.integers(0, 255))
@settings(max_examples=60, deadline=None, derandomize=True)
def test_random_fast_blocks_match_original_runner(operations, registers, address, byte):
    lines = []
    for operation, destination, operand in operations:
        args = (f"r{destination}",)
        if operation != "dec":
            args += (f"r{operand}" if operation == "add" else str(operand),)
        lines.append(Instruction(operation, args))
    body = compile_sub(Sub("main", (*lines, Instruction("halt"))))
    memory = bytearray(256)
    memory[address] = byte
    state = State(registers, bytes(memory))
    fast = _fast_projection(body, 100)
    original = run_blocks(body, state, {"main": body}, 100, "B", record_trace=False)
    assert fast is not None and fast(state) == original.outcome
