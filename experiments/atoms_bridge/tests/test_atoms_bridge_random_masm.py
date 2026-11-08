"""Random program checks against a separate straight-line MASM interpreter."""

import json
from pathlib import Path

import pytest
from atoms_bridge.env import LibraryView, _check, _results
from atoms_bridge.machine import parse_program, run_sub, runtime_names
from atoms_bridge.summary import FROZEN_TASK_IDS, analyze, bootstrap_length_ratio
from atoms_mul.analysis.analyze import bootstrap_median_ratio
from atoms_mul.machine.lang import NAME, MasmSyntaxError
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.values import Bottom, Ok
from opulse.worlds_v2.computer.machine import State

TASK_FILE = Path(__file__).resolve().parents[2] / "atoms_mul/tasks/machine_stage2.json"
INSTRUCTIONS = ("add r0, r1", "add r0, r3", "dec r0", "load r1, 16",
                "load r2, 32", "store r0, 17", "call helper", "jz r3, done",
                "jnz r0, done", "set r0, 19", "xcall mul r1, r2 -> r0")


@st.composite
def masm_cases(draw):
    """Draw variable-length programs with branches, helper calls and optional xcall."""
    commands = draw(st.lists(st.sampled_from(INSTRUCTIONS[:-1]), min_size=1, max_size=12))
    if draw(st.booleans()):
        commands.insert(draw(st.integers(min_value=0, max_value=len(commands))),
                        "xcall mul r1, r2 -> r0")
    registers = (draw(st.integers(0, 255)), draw(st.integers(0, 255)),
                 draw(st.integers(0, 20)), draw(st.integers(0, 255)))
    memory = bytearray(256)
    memory[16] = draw(st.integers(0, 255))
    memory[32] = draw(st.integers(0, 20))
    program = "sub helper:\n  add r0, r1\nend\nsub main:\n" + "\n".join(
        f"  {command}" for command in commands) + "\n  done:\n  halt\nend"
    return program, State(registers, bytes(memory)), commands


def direct_masm(state, commands):
    """Independently evaluate generated programs over byte registers and memory."""
    registers = list(state.regs)
    memory = bytearray(state.mem)
    zero, carry = state.zero, state.carry
    for command in commands:
        if command == "jz r3, done" and registers[3] == 0:
            break
        if command == "jnz r0, done" and registers[0] != 0:
            break
        if command.startswith("add") or command == "call helper":
            source = 3 if command == "add r0, r3" else 1
            total = registers[0] + registers[source]
            registers[0] = total % 256
            zero, carry = registers[0] == 0, total > 255
        elif command == "dec r0":
            carry = registers[0] == 0
            registers[0] = (registers[0] - 1) % 256
            zero = registers[0] == 0
        elif command == "load r1, 16":
            registers[1] = memory[16]
        elif command == "load r2, 32":
            registers[2] = memory[32]
        elif command == "store r0, 17":
            memory[17] = registers[0]
        elif command == "set r0, 19":
            registers[0] = 19
        elif command.startswith("set r2, "):
            registers[2] = int(command.removeprefix("set r2, "))
        elif command == "xcall mul r1, r2 -> r0":
            registers[0] = registers[1] * registers[2] % 256
    return State(tuple(registers), bytes(memory), zero, carry)


@given(masm_cases())
@settings(max_examples=35, deadline=None)
def test_random_programs_unfold_and_boundary_do_not_change_full_state(case):
    source, state, commands = case
    program = parse_program(source)
    oracle = direct_masm(state, commands)
    for group in ("B", "C"):
        library = LibraryView()
        library.group = group
        assert _check(program, {}, group, library) == []
        result = run_sub(program, state, group)
        assert result.outcome == Ok(oracle)
        assert result.final_state == oracle
        assert result.boundary_steps <= result.steps
    invented = run_sub(program, state, "B")
    given = run_sub(program, state, "C")
    assert invented.outcome == given.outcome
    assert invented.boundary_steps == given.boundary_steps
    assert invented.calls["xcall"] == given.calls["xcall"]


@given(st.sampled_from(sorted(name for name in runtime_names("B") if NAME.fullmatch(name))),
       st.sampled_from(("add r0, r1", "xcall mul r1, r2 -> r0", "halt")))
@settings(max_examples=20, deadline=None)
def test_random_reserved_subs_cannot_shadow_runtime(name, instruction):
    library = LibraryView()
    library.group = "B"
    source = f"sub {name}:\n  halt\nend\nsub main:\n  {instruction}\nend"
    if name == "__xcall_mul":
        with pytest.raises(MasmSyntaxError):
            parse_program(source)
        return
    program = parse_program(source)
    assert any("reserved runtime name" in error for error in _check(program, {}, "B", library))


@given(st.lists(st.sampled_from(INSTRUCTIONS), min_size=0, max_size=8),
       st.integers(min_value=21, max_value=255), st.integers(min_value=0, max_value=255))
@settings(max_examples=20, deadline=None)
def test_random_programs_enforce_saved_source_scope(commands, multiplier, first):
    source = ("sub helper:\n  add r0, r1\nend\nsub main:\n"
              f"  set r2, {multiplier}\n"
              "  xcall mul r1, r2 -> r0\n" +
              "\n".join(f"  {command}" for command in commands) + "\n  done:\n  halt\nend")
    program = parse_program(source)
    state = State((0, first, 0, 0))
    library = LibraryView()
    library.group = "B"
    assert _check(program, {}, "B", library) == []
    assert run_sub(program, state, "B").outcome == Bottom("outside_domain")
    assert run_sub(program, state, "C").outcome == Ok(
        direct_masm(state, [f"set r2, {multiplier}", "xcall mul r1, r2 -> r0", *commands]))


def test_length_bootstrap_matches_shared_seeded_ci95():
    left, right = [3, 4, 5, 8], [10, 12, 15, 20]
    result = bootstrap_length_ratio(left, right, 100)
    shared = bootstrap_median_ratio(left, right, 100)
    assert result["ratio"] == shared["ratio"]
    assert result["ci95"] == shared["ci95"]
    assert result["ci90"][0] >= result["ci95"][0]
    assert result["ci90"][1] <= result["ci95"][1]
    assert bootstrap_length_ratio([2], [0], 10)["ci95"] is None
    assert bootstrap_length_ratio([2], [0, 0, 3], 10)["ci95"] is None


def test_written_length_counts_in_task_helper_and_main():
    program = parse_program("sub helper:\n  set r0, 4\n  halt\nend\n"
                            "sub main:\n  call helper\n  halt\nend")
    result = _results(program, True, [run_sub(program, State(), "B")], {}, "B", LibraryView(), 200_000)
    assert result["length"] == 4
    assert {entry["name"] for entry in result["defs_written"]} == {"main", "helper"}


def _rows(length_a, length_b, correct_a=True, correct_b=True):
    return [{"group": group, "stage": 2, "episode": episode, "task_id": task_id,
             "length": length, "correct": correct, "uses_library": group == "B", "steps": 10}
            for group, length, correct in (("A", length_a, correct_a),
                                           ("B", length_b, correct_b))
            for episode in range(40) for task_id in FROZEN_TASK_IDS]


def test_length_decisions_and_secondary_noninferiority():
    saves = analyze(_rows(10, 5), resamples=20)
    assert saves["decision"] == "transfer saves effort"
    assert saves["secondary_accuracy_noninferior"] is True
    assert saves["secondary_bridge_use_rate"] == {"A": 0, "B": 1}
    assert saves["secondary_layer0_steps"] == {"A": 10, "B": 10}
    assert analyze(_rows(10, 10), resamples=20)["decision"] == "no saving"
    uncertain = analyze(_rows(10, 12, correct_b=False), resamples=20)
    assert uncertain["decision"] == "inconclusive"
    assert uncertain["secondary_accuracy_noninferior"] is False
    assert analyze(_rows(0, 5), resamples=20)["decision"] == "inconclusive"


def test_analysis_rejects_missing_or_repeated_frozen_task_and_incomplete_arms():
    frozen = json.loads(TASK_FILE.read_text())["tasks"]
    rows = _rows(10, 5)
    assert len(frozen) == len(FROZEN_TASK_IDS)
    for modified in (rows[:-1], [*rows[:-1], rows[-2]]):
        assert analyze(modified, resamples=10)["decision"] == "diagnostic"
    assert analyze([row for row in rows if row["episode"] < 39], resamples=10)["decision"] == "diagnostic"
    errors = [dict(row) for row in rows]
    for row in [item for item in errors if item["group"] == "B" and item["episode"] == 0][:3]:
        row["api_error"] = True
    assert analyze(errors, resamples=10)["decision"] == "diagnostic"
