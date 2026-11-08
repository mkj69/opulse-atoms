"""Pipeline and frozen-run checks for saved machine definitions."""

import json

import pytest
from atoms_mul.machine.core_library import (
    CoreMirror,
    compile_definition,
    full_state_problem,
    load_decl,
)
from atoms_mul.machine.env import run_episode, state_for
from atoms_mul.machine.evaluate import run_blocks, run_sub
from atoms_mul.machine.lang import parse_program
from atoms_mul.machine.library import Library
from atoms_mul.machine.policies import HELPER, Inventor
from atoms_mul.machine.tasks import ROOT
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.atoms.library import Library as CoreLibrary
from opulse.atoms.values import Ok
from opulse.worlds_v2.computer import machine, runner


def saved_entry(text=HELPER):
    program = parse_program(text + "\nsub main:\n call MUL\nend\nsave MUL")
    return Library().add_from_program(program, ["MUL"], "sample")[0]


def test_machine_core_declarations_and_compilation():
    assert load_decl("A").world == "computer_a"
    assert "mul" in {op.name for op in load_decl("A").operations}
    assert "mul" not in {op.name for op in load_decl("B").operations}
    with pytest.raises(ValueError, match="unknown group"):
        load_decl("X")
    entry = saved_entry()
    definition = compile_definition(entry)
    assert isinstance(definition.body, nodes.Blocks)
    assert definition.layer == entry.layer
    assert set(definition.depends_on) == nodes.references(definition.body)


def test_machine_core_status_and_full_state_obligation():
    entry = saved_entry()
    mirror = CoreMirror("B")
    report, = mirror.mirror([{"definition": entry, "mul_equivalent": True}])
    assert report["core_status"] == "callable"
    assert report["evidence"] is None
    assert report["cost"]["length"] > 0
    assert report["cost"]["steps"]["max"] > 0
    assert "full-state reference counterexample r1=0, r2=1" in report["problems"][0]
    assert "r2, zero" in report["problems"][0]
    assert not mirror.derived_world().promoted
    assert CoreMirror("B").mirror([entry])[0]["core_status"] == "callable"
    assert CoreMirror("C").mirror([entry])[0]["core_status"] is None


def test_machine_mirror_uses_native_scope_for_record_objects():
    mirror = CoreMirror("B")
    assert type(mirror.library) is CoreLibrary
    assert mirror.library.scope().resolve("add") is not None


def test_machine_core_reference_problem_is_compact_and_deterministic():
    entry = saved_entry()
    mirror = CoreMirror("B")
    mirror.mirror([entry])
    states = [machine.State((0, 0, right, 0)) for right in (0, 1)]
    problem = full_state_problem(mirror.library, entry.name, states)
    assert problem == full_state_problem(mirror.library, entry.name, states)
    assert len(problem) < 150
    assert "r2=1" in problem
    assert full_state_problem(mirror.library, entry.name, [machine.State()]) == (
        "full-state reference check failed")


def test_machine_core_dependency_order_and_repeated_mirroring():
    program = parse_program("sub main:\n halt\nend\nsub low:\n set r0, 1\nend\n"
                            "sub high:\n call low\nend\nsave low\nsave high")
    entries = Library().add_from_program(program, ["low", "high"], "sample")
    reports = CoreMirror("B").mirror(entries)
    assert [report["core_status"] for report in reports] == ["callable", "callable"]
    assert reports == CoreMirror("B").mirror(entries)


@settings(max_examples=30)
@given(left=st.integers(min_value=0, max_value=255),
       right=st.integers(min_value=0, max_value=20),
       fuel=st.integers(min_value=0, max_value=250))
def test_machine_boundary_preserves_outcome_full_state_and_steps(left, right, fuel):
    saved = parse_program(HELPER + "\nsub main:\n call MUL\nend\nsave MUL")
    library = Library()
    library.add_from_program(saved, ["MUL"], "sample")
    program = parse_program("sub main:\n call MUL\nend")
    state = machine.State((0, left, right, 0))
    opened = run_sub("main", state, group="B", program=program, library=library, fuel=fuel)
    closed = run_sub("main", state, group="B", program=program, library=library,
                     fuel=fuel, boundary=frozenset({"MUL"}))
    assert (opened.outcome, opened.final_state, opened.steps) == (
        closed.outcome, closed.final_state, closed.steps)
    if isinstance(opened.outcome, Ok):
        assert closed.boundary_steps <= opened.boundary_steps
    assert closed.calls == opened.calls


def test_run_blocks_dispatches_to_world_runner():
    program = parse_program("sub main:\n set r0, 1\nNEXT:\n jz r0, NEXT\n halt\nend")
    body = compile_definition(saved_entry()).body
    assert run_blocks(body, machine.State(), {}, 10, "B") == runner.run(
        body, {"s": machine.State()}, fuel=10)
    actual = run_sub("main", machine.State(), group="B", program=program)
    assert isinstance(actual.outcome, Ok) and actual.steps == 4


def test_run_blocks_computer_a_uses_the_given_mul():
    from atoms_mul.machine.compile import compile_sub

    program = parse_program("sub main:\n mul\nend")
    body = compile_sub(program.defs[0])
    state = machine.State((0, 4, 7, 0))
    world = run_blocks(body, state, {}, 1, "A", record_trace=False)
    traced = run_blocks(body, state, {}, 1, "A")
    assert world.outcome == Ok(machine.given_mul(state))
    assert (world.outcome, world.steps, world.final_state) == (
        traced.outcome, traced.steps, traced.final_state)
    assert world.steps == 1 and world.final_state == machine.given_mul(state)
    assert world.trace == ()


def test_machine_episode_records_real_core_status_deterministically():
    task = next(task for task in json.loads((ROOT / "tasks" / "machine_stage1.json").read_text())["tasks"]
                if task["family"] == "variable_scale")
    def episode(group):
        return run_episode(Inventor([task]), group, 0, [task], [], max_attempts=1)

    first = episode("B")
    assert first == episode("B")
    assert first[0]["saved"] == ["MUL"]
    assert first[0]["mul_equivalent"] == ["MUL"]
    assert first[0]["core_library"][0]["status"] == "callable"
    assert "full-state reference counterexample" in first[0]["core_library"][0]["problems"][0]
    assert episode("C")[0]["core_library"] == []


def test_all_committed_machine_programs_match_frozen_results():
    tasks = {task["id"]: task for stage in (1, 2) for task in json.loads(
        (ROOT / "tasks" / f"machine_stage{stage}.json").read_text())["tasks"]}
    for results in sorted((ROOT / "runs").glob("dryrun_machine_*/results.jsonl")):
        libraries = {}
        for line in results.read_text().splitlines():
            row = json.loads(line)
            library = libraries.setdefault((row["group"], row["episode"]), Library())
            program = parse_program(row["final_program"])
            hidden = [run_sub("main", state_for(test), group=row["group"], program=program,
                              library=library, boundary=frozenset(library.names()))
                      for test in tasks[row["task_id"]]["hidden_tests"]]
            all_ok = all(isinstance(result.outcome, Ok) for result in hidden)
            assert (sum(result.steps for result in hidden) if all_ok else None) == row["steps"]
            assert (sum(result.boundary_steps for result in hidden) if all_ok else None) == row["boundary_steps"]
            assert all(isinstance(result.outcome, Ok) and
                       result.final_state.regs[0] == test["expected_r0"]
                       for result, test in zip(hidden, tasks[row["task_id"]]["hidden_tests"])) == row["correct"]
            if row["saved"]:
                library.add_from_program(program, row["saved"], row["task_id"])
