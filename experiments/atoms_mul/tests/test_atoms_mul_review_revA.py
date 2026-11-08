"""Independent reproductions of saved-definition and checkpoint failures."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from atoms_mul.harness import run as runner
from atoms_mul.harness.env import run_episode
from atoms_mul.kernel import core_library as aml_core
from atoms_mul.kernel import parse_program as parse_aml
from atoms_mul.kernel.core_library import CoreMirror as AmlMirror
from atoms_mul.kernel.library import Library as AmlLibrary
from atoms_mul.machine import core_library as machine_core
from atoms_mul.machine import env as machine_env
from atoms_mul.machine.core_library import CoreMirror as MachineMirror
from atoms_mul.machine.lang import parse_program as parse_machine
from atoms_mul.machine.library import Library as MachineLibrary
from atoms_mul.mirror_order import dependency_order
from hypothesis import given
from hypothesis import strategies as st


@given(st.permutations(("outer", "inner", "root")))
def test_joint_save_dependency_order_is_stable_under_permutation(names):
    class Saved:
        def __init__(self, name, depends_on):
            self.name = name
            self.depends_on = depends_on

    definitions = [Saved(name, {"outer": ("inner",), "inner": (),
                                "root": ("outer",)}[name]) for name in names]
    assert [definitions[index].name for index in dependency_order(definitions)] == [
        "inner", "outer", "root"]


def test_aml_mirror_accepts_reverse_ordered_saved_dependencies():
    program = parse_aml(
        "op outer(x: Nat) -> Nat = inner(x)\n"
        "op inner(x: Nat) -> Nat = add(x, 1)\n"
        "op solve(x: Nat) -> Nat = outer(x)\n"
        "save outer\nsave inner"
    )
    entries = AmlLibrary().add_from_program(program, program.saves, "stage1")
    mirror = AmlMirror("B")
    reports = mirror.mirror(entries)
    assert all(report["core_status"] == "callable" and not report["problems"]
               for report in reports)
    assert mirror.library.run("outer", (3,)).outcome.value == 4


def test_machine_mirror_accepts_reverse_ordered_saved_dependencies():
    program = parse_machine(
        "sub outer:\n  call inner\nend\n"
        "sub inner:\n  set r0, 7\nend\n"
        "sub main:\n  call outer\nend\n"
        "save outer\nsave inner"
    )
    entries = MachineLibrary().add_from_program(program, program.saves, "stage1")
    mirror = MachineMirror("B")
    reports = mirror.mirror(entries)
    assert all(report["core_status"] == "callable" and not report["problems"]
               for report in reports)


def test_promoted_episode_record_preserves_core_evidence_and_cost():
    class SavesMul:
        def reset(self, **kwargs):
            pass

        def act(self, observation):
            return ("op rep(n: Nat, x: Nat) -> Nat = if is_zero(n) then 0 else "
                    "add(x, rep(pred(n), x))\n"
                    "op solve(a: Nat, b: Nat) -> Nat = rep(a, b)\nsave rep")

    task = {"id": "s1_t09", "family": "variable_scale", "statement": "Repeat addition.",
            "params": ["a", "b"], "solve_signature": "solve(a, b)",
            "public_examples": [{"args": [3, 4], "expected": 12}],
            "hidden_tests": [{"args": [3, 4], "expected": 12}]}
    record, = run_episode(SavesMul(), "B", 0, [task], [], max_attempts=1)
    promoted, = record["core_library"]
    assert promoted["status"] == "promoted"
    assert promoted["problems"] == []
    assert promoted["evidence"]["method"] == "exhaustive"
    assert promoted["evidence"]["scope"]["size"] == 256
    assert promoted["evidence"]["checks"]
    assert promoted["cost"]["length"] > 0
    assert promoted["cost"]["steps"] is not None
    assert promoted["contract"]["keeps"] == ["full_state"]


def test_resume_recovers_completed_episode_after_torn_checkpoint(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    calls = []

    def offline_episode(*args, **kwargs):
        calls.append(1)
        return []

    monkeypatch.setattr(runner, "run_episode", offline_episode)
    options = {"policy": "inventor", "groups": ["B"], "episodes": 1,
               "run_id": "recover", "out": tmp_path}
    destination = runner.run(**options)
    config = json.loads((destination / "config.json").read_text())
    records = [json.loads(line) for line in
               (root / "runs/dryrun_inventor/results.jsonl").read_text().splitlines()]
    prompts = [json.loads(line) for line in
               (root / "runs/dryrun_inventor/prompts.jsonl").read_text().splitlines()]
    completed = {"group": "B", "episode": 0, "records": [
        record for record in records if record["group"] == "B" and record["episode"] == 0],
        "prompts": [prompt for prompt in prompts if prompt["group"] == "B" and prompt["episode"] == 0]}
    (destination / "episodes.jsonl").write_text(
        json.dumps({"config": config}) + "\n" + json.dumps(completed) + "\n" +
        '{"group":"B","episode":1,"records":')
    runner.run(**{**options, "episodes": 2}, resume=True)
    assert len(calls) == 2


def test_resume_rejects_torn_checkpoint_line_in_middle(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "run_episode", lambda *args, **kwargs: [])
    options = {"policy": "inventor", "groups": ["B"], "episodes": 1,
               "run_id": "middle", "out": tmp_path}
    destination = runner.run(**options)
    config = json.loads((destination / "config.json").read_text())
    checkpoint = destination / "episodes.jsonl"
    checkpoint.write_text(json.dumps({"config": config}) + "\n" +
                          '{"group":"B","episode":0,"records":\n' +
                          json.dumps({"group": "B", "episode": 0, "records": [], "prompts": []}) + "\n")
    with pytest.raises(json.JSONDecodeError):
        runner.run(**options, resume=True)


def test_resume_discards_unterminated_valid_json_episode(monkeypatch, tmp_path):
    calls = []

    def offline_episode(*args, **kwargs):
        calls.append(1)
        return []

    monkeypatch.setattr(runner, "run_episode", offline_episode)
    options = {"policy": "inventor", "groups": ["B"], "episodes": 1,
               "run_id": "unterminated", "out": tmp_path}
    destination = runner.run(**options)
    config = json.loads((destination / "config.json").read_text())
    (destination / "episodes.jsonl").write_text(
        json.dumps({"config": config}) + "\n" +
        json.dumps({"group": "B", "episode": 0, "records": [], "prompts": []}))
    runner.run(**options, resume=True)
    assert len(calls) == 2


def test_aml_resume_rejects_changed_decl(monkeypatch, tmp_path):
    declarations = tmp_path / "decl"
    declarations.mkdir()
    for group in "ABC":
        (declarations / f"atoms_mul_{group}.json").write_bytes(
            (aml_core.DECLARATIONS / f"atoms_mul_{group}.json").read_bytes())
    monkeypatch.setattr(aml_core, "DECLARATIONS", declarations)
    monkeypatch.setattr(runner, "run_episode", lambda *args, **kwargs: [])
    options = {"policy": "inventor", "groups": ["B"], "episodes": 1,
               "run_id": "aml_changed", "out": tmp_path}
    runner.run(**options)
    declaration = declarations / "atoms_mul_A.json"
    changed = json.loads(declaration.read_text())
    changed["world"] = "changed_a"
    declaration.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="resume config mismatch: hashes"):
        runner.run(**options, resume=True)


def test_machine_resume_rejects_changed_world_declaration(monkeypatch, tmp_path):
    declaration = tmp_path / "computer.json"
    declaration.write_bytes(machine_core.DECLARATION.read_bytes())
    monkeypatch.setattr(machine_core, "DECLARATION", declaration)
    monkeypatch.setattr(machine_env, "run_episode", lambda *args, **kwargs: [])
    options = {"policy": "inventor", "groups": ["B"], "episodes": 1,
               "run_id": "world_changed", "out": tmp_path, "track": "machine"}
    runner.run(**options)
    altered = json.loads(declaration.read_text())
    altered["world"] = "computer_modified"
    declaration.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="resume config mismatch:.*(world|hashes)"):
        runner.run(**options, resume=True)


def test_machine_resume_rejects_changed_derived_a_declaration(monkeypatch, tmp_path):
    monkeypatch.setattr(machine_env, "run_episode", lambda *args, **kwargs: [])
    options = {"policy": "inventor", "groups": ["A"], "episodes": 1,
               "run_id": "derived_changed", "out": tmp_path, "track": "machine"}
    runner.run(**options)
    original_load = machine_core.load_decl

    def changed_load(group):
        world = original_load(group)
        return replace(world, world="computer_a_changed") if group == "A" else world

    monkeypatch.setattr(machine_core, "load_decl", changed_load)
    with pytest.raises(ValueError, match="resume config mismatch: hashes"):
        runner.run(**options, resume=True)


@pytest.mark.parametrize("run_id", (
    "dryrun_inventor", "dryrun_nosave", "dryrun_unroll", "dryrun_flaky",
    "dryrun_machine_inventor", "dryrun_machine_nosave", "dryrun_machine_unroll",
    "dryrun_machine_flaky",
))
def test_regenerated_dry_run_byte_replay(run_id, tmp_path):
    root = Path(__file__).resolve().parents[1]
    committed = root / "runs" / run_id
    config = json.loads((committed / "config.json").read_text())
    replay = runner.run(policy=config["policy"], groups=config["groups"],
                        episodes=config["episodes"], run_id=run_id, out=tmp_path,
                        max_attempts=config["max_attempts"], fuel=config["fuel"],
                        track=config["track"])
    for name in ("config.json", "results.jsonl", "prompts.jsonl", "summary.json"):
        assert (replay / name).read_bytes() == (committed / name).read_bytes()
