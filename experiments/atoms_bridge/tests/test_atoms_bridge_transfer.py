"""Independent checks of scope, costs, replay and the preloaded source library."""

import json
from pathlib import Path

import pytest
from atoms_bridge.bridge import (
    MUL_DOMAIN,
    byte_add,
    mul_scope,
    nat_add,
    worlds,
    wrap_byte,
)
from atoms_bridge.env import LibraryView, Transfer, _check, _grade, run_episode
from atoms_bridge.machine import parse_program, run_sub
from atoms_bridge.run import main as run_main
from atoms_bridge.run import run
from atoms_bridge.summary import analyze, summarize
from atoms_bridge.summary import main as analyze_main
from atoms_mul.machine.env import state_for
from atoms_mul.machine.evaluate import run_sub as native_run
from atoms_mul.machine.lang import MasmSyntaxError
from atoms_mul.machine.lang import parse_program as parse_masm
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms.bridges import BridgeContext, bridge_defn, verify_bridge
from opulse.atoms.library import bounded
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.worlds_v2.computer.machine import State

TASKS = Path(__file__).resolve().parents[2] / "atoms_mul" / "tasks" / "machine_stage2.json"
PROGRAM = "sub main:\n  xcall mul r1, r2 -> r0\nend"


def test_scripted_source_promotion_and_checked_commuting_scope():
    integer, machine = worlds("B")
    assert integer.get("mul").status == "promoted"
    assert integer.get("mul").evidence.scope["domain"] == MUL_DOMAIN
    assert integer.get("mul").evidence.scope["size"] == 256 * 21
    bridge = integer.get("to_byte")
    assert bridge.status == "promoted"
    assert bridge.evidence.scope["pairs_checked"] == 256
    assert machine.get("to_nat").status == "promoted"
    for left, right in ((0, 15), (8, 7), (15, 15)):
        mapped = tuple(integer.run("to_byte", (Card("nat", "val", (value,)),)).outcome.value
                       for value in (left, right))
        output = integer.run("to_byte", (Card("nat", "val", (left + right,)),)).outcome
        assert output == machine.run("byte_add", mapped).outcome


def test_overflowing_add_does_not_commute_and_cannot_expand_evidence():
    integer, machine = worlds("B")
    request = bounded((tuple(Card("nat", "val", (value,)) for value in range(256)),),
                      "bound <= 255")
    request.extra["pairs"] = ((Card("nat", "val", (255,)), Card("nat", "val", (1,))),)
    request.extra["bridge_context"] = BridgeContext(integer, machine)
    result = verify_bridge(integer.get("to_byte"), integer, request)
    assert not result.ok
    assert any("no checked pairs" in problem for problem in result.problems)


@given(st.integers(min_value=0, max_value=255))
def test_partial_byte_domain_and_roundtrip(number):
    integer, machine = worlds("B")
    mapped = integer.run("to_byte", (Card("nat", "val", (number,)),)).outcome
    assert mapped == Ok(Card("byte", "val", (number,)))
    assert machine.run("to_nat", (mapped.value,)).outcome == Ok(Card("nat", "val", (number,)))


@pytest.mark.parametrize(("number", "reason"),
                         ((-2, "nan_condition"), (-1, "nan_condition"),
                          (256, "outside_domain"), (10**9, "outside_domain")))
def test_outside_domain_returns_explicit_bottom(number, reason):
    integer, _ = worlds("B")
    source = Card("nat", "val", (number,))
    assert integer.run("to_byte", (source,)).outcome == Bottom(reason)
    definition = integer.get("to_byte")
    inline = kernel.call("to_byte", (source,), integer.scope().extend((bridge_defn(definition.spec),)))
    assert inline.outcome == Bottom(reason)


def test_wrap_is_separate_from_partial_bridge():
    integer, _ = worlds("B")
    assert wrap_byte(286) == 30
    assert wrap_byte(-1) == Bottom("invalid")
    assert integer.run("to_byte", (Card("nat", "val", (286,)),)).outcome == Bottom("outside_domain")


def test_verification_witness_rejects_forged_values():
    assert byte_add(Card("byte", "val", (255,)), Card("byte", "val", (2,))) == Card("byte", "val", (1,))
    assert byte_add(Card("byte", "val", (999,)), Card("byte", "val", (2,))) == Bottom("invalid")


def test_refined_add_preserves_integer_host_and_rejects_forged_cards():
    assert nat_add(7, 8) == Ok(15)
    assert nat_add(Card("nat", "val", (7,)), Card("nat", "val", (8,))) == Card(
        "nat", "val", (15,))
    assert nat_add(Card("nat", "val", (-1,)), Card("nat", "val", (8,))) == Bottom("invalid")


@given(st.integers(min_value=-1, max_value=256), st.integers(min_value=-1, max_value=22))
def test_saved_mul_scope_matches_exact_evidence(first, second):
    assert mul_scope(first, second) == (0 <= first <= 255 and 0 <= second <= 20)


def test_out_of_scope_xcall_is_refused():
    for group in ("B", "C"):
        result = run_sub(parse_program(PROGRAM), State((0, 5, 21, 0)), group)
        if group == "B":
            assert result.outcome == Bottom("outside_domain")
        else:
            assert result.outcome == Ok(result.final_state)


def test_frozen_xcall_inputs_within_saved_mul_scope():
    tasks = json.loads(TASKS.read_text())["tasks"]
    assert len(tasks) == 16
    for task in tasks:
        lines = parse_masm(task["reference_masm"]).defs[0].lines
        first_address = second_address = None
        pairs = []
        for line in lines:
            if line.op == "load" and line.args[0] == "r1":
                first_address = line.args[1]
            if line.op == "load" and line.args[0] == "r2":
                second_address = line.args[1]
            if line.op == "mul":
                assert first_address is not None and second_address is not None
                pairs.append((first_address, second_address))
        assert pairs
        for test in (*task["public_examples"], *task["hidden_tests"]):
            assert all(mul_scope(test["memory"][left], test["memory"][right])
                       for left, right in pairs)


def test_core_cross_world_scope_routes_source_add():
    integer, machine = worlds("B")
    assert integer.local_scope().resolve("add").arity == 2
    assert machine.scope().resolve("add").arity == 3
    assert kernel.call("mul", (9, 6), machine.scope()).outcome == Ok(54)


def test_parser_accepts_only_one_new_instruction_form():
    assert parse_program(PROGRAM).defs[0].lines[0].args == ("__xcall_mul",)
    assert parse_program(PROGRAM.replace(" -> r0", " -> r0 # explains transfer")).defs
    for bad in ("xcall mul r2, r1 -> r0", "xcall mul r1, r2 -> r3", "call __xcall_mul"):
        with pytest.raises(MasmSyntaxError):
            parse_program(f"sub main:\n  {bad}\nend")


def test_access_control_and_saved_source_view():
    program = parse_program(PROGRAM)
    library = LibraryView()
    assert _check(program, {}, "A", library) == ["bridge is unavailable in G1"]
    library.group = "B"
    assert _check(program, {}, "B", library) == []
    assert "L1" in library.listing()
    library.group = "C"
    assert "given" in library.listing()


@given(st.integers(min_value=0, max_value=255), st.integers(min_value=0, max_value=20))
@settings(max_examples=12, deadline=None)
def test_cross_world_costs_and_byte_result(first, second):
    state = State((7, first, second, 19))
    program = parse_program(PROGRAM)
    invented = run_sub(program, state, "B")
    given = run_sub(program, state, "C")
    assert invented.outcome == given.outcome
    assert isinstance(invented.outcome, Ok)
    assert invented.final_state.regs == (first * second % 256, first, second, 19)
    integer, _ = worlds("B")
    assert invented.steps == integer.run("mul", (first, second)).steps + 17
    assert given.steps == 18
    assert invented.boundary_steps == given.boundary_steps == 18
    assert invented.calls["xcall"] == given.calls["xcall"] == 1
    assert run_sub(program, state, "B") == invented
    assert isinstance(run_sub(program, state, "B", fuel=5).outcome, Unknown)


def test_core_trace_steps_charge_cross_world_work_exactly():
    integer, machine = worlds("B")
    state = State((0, 9, 6, 11))
    run_result = run_sub(parse_program(PROGRAM), state, "B")
    source_steps = integer.run("mul", (9, 6)).steps
    given_steps = run_sub(parse_program(PROGRAM), state, "C").steps
    machine_and_bridges_steps = given_steps - 1
    assert run_result.steps == source_steps + machine_and_bridges_steps
    assert run_result.steps == run_sub(parse_program(PROGRAM), state, "B").steps
    assert isinstance(run_sub(parse_program(PROGRAM), state, "B", fuel=run_result.steps - 1).outcome,
                      Unknown)
    assert run_sub(parse_program(PROGRAM), state, "B", fuel=run_result.steps).outcome == run_result.outcome
    assert machine.get("to_nat").evidence.scope["domain_size"] == 256


def test_native_masm_replay_on_frozen_dot_tasks():
    tasks = json.loads(TASKS.read_text())["tasks"]
    for task in tasks:
        bridge = parse_program(task["reference_masm"].replace("  mul", "  xcall mul r1, r2 -> r0"))
        native = parse_masm(task["reference_masm"])
        for test in task["hidden_tests"]:
            state = state_for(test)
            given = native_run("main", state, group="A", program=native)
            for group in ("B", "C"):
                result = run_sub(bridge, state, group)
                assert result.outcome == Ok(result.final_state)
                assert result.final_state.regs[0] == test["expected_r0"]
                assert result.final_state == given.final_state


def test_shared_episode_and_summary_use_stage2_only():
    tasks = json.loads(TASKS.read_text())["tasks"]
    actor = Transfer((), tasks)
    rows = run_episode(actor, "B", 0, (), tasks)
    assert len(rows) == 16
    assert all(row["correct"] and row["uses_library"] for row in rows)
    summary = summarize(rows, {"groups": ["B"]})
    assert summary["groups"]["B"]["2"]["bridge_use_rate"] == 1
    assert summary["groups"]["B"]["2"]["fixed_source_aml_length"] == 13
    assert analyze(rows, resamples=10)["decision"] == "diagnostic"


def test_shared_run_checkpoint_and_cost_input(tmp_path):
    run(policy="unroll", groups=["A", "B"], episodes=1, run_id="offline", out=tmp_path)
    result = tmp_path / "offline"
    assert (result / "prompts.jsonl").exists()
    assert len((result / "results.jsonl").read_text().splitlines()) == 32
    assert analyze_main(["--run", str(result), "--resamples", "10"])["decision"] == "diagnostic"
    assert (result / "analysis.json").exists()


def test_cli_offline_unroll_uses_shared_runner(tmp_path):
    run_main(["--policy", "unroll", "--groups", "A", "--episodes", "1",
              "--run-id", "cli", "--out", str(tmp_path)])
    assert (tmp_path / "cli" / "summary.json").exists()


def test_exact_grader_on_frozen_examples():
    task = json.loads(TASKS.read_text())["tasks"][0]
    library = LibraryView()
    library.group = "B"
    hidden, correct = _grade(parse_program(task["reference_masm"].replace(
        "  mul", "  xcall mul r1, r2 -> r0")), task, "B", library, 200_000)
    assert correct and len(hidden) == 12


def test_transferred_outcome_does_not_depend_on_boundary():
    program = parse_program(PROGRAM)
    state = State((0, 4, 6, 2))
    result = run_sub(program, state, "B")
    assert result.outcome == Ok(result.final_state)
    assert result.steps > result.boundary_steps
    assert result.boundary_steps == 18
