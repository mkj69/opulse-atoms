"""Driver scheduling, deterministic generation, checkpoint and CLI tests."""

import importlib
import json
from dataclasses import replace

import pytest

from opulse.atoms import nodes
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.gen_v2 import run
from opulse.gen_v2.__main__ import main
from opulse.gen_v2.base import (
    Candidate,
    Entry,
    Signature,
    signature_data,
    signature_from_data,
)
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.registry import discover_moves
from opulse.gen_v2.worlds import toy


class OperationMove:
    kind = "operation"
    name = "test.operation"

    def __call__(self, state, rng):
        name = state.names.fresh(self.kind)
        factor = rng.randrange(2, 1_000_000)
        body = nodes.Call("add", (nodes.Call("mul", (nodes.Var("x"), nodes.Lit(factor))),
                                  nodes.Lit(factor + 1)))
        spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"), "multiply and shift",
                             extra={"input_names": ["x"]})
        defn = Definition(name, self.kind, "invented", 1, tuple(sorted(nodes.references(body))), spec, body)
        return Candidate(defn, Signature(("int",), "int"), self.name)


class FakeKindMove:
    def __init__(self, kind):
        self.kind = kind
        self.name = "test." + kind
        self.calls = 0

    def __call__(self, state, rng):
        self.calls += 1
        return (self.kind, rng.randrange(100000))


def test_signature_json_round_trip_with_operation_slots():
    signature = Signature(("int",), "bool", (Signature(("int",), "int"),))
    assert signature_from_data(signature_data(signature)) == signature
    assert signature_from_data(None) is None


def _fake_admit(state, candidate):
    kind, random_value = candidate
    name = state.names.fresh(kind)
    entry = Entry(name, kind, state.max_layer() + 1, None, "test." + kind,
                  (), (kind, random_value))
    state.entries[name] = entry
    return entry


def test_generated_operations_are_deterministic_and_stop_on_target():
    world = toy.gen_world(("operation",))
    first = run.generate(world, 30, 41, per_kind_min=0, layer_target=1, moves=[OperationMove()])
    second = run.generate(world, 30, 41, per_kind_min=0, layer_target=1, moves=[OperationMove()])
    assert len(first.entries) == len(second.entries) == 30
    assert [first.library.get(name).to_dict() for name in first.entries] == [
        second.library.get(name).to_dict() for name in second.entries]
    assert first.attempts == second.attempts


def test_kind_quotas_and_closed_kinds(monkeypatch):
    from opulse.gen_v2 import interest

    monkeypatch.setattr(run, "admit", _fake_admit)
    monkeypatch.setattr(interest, "score_entries", lambda state: None)  # fake entries have no results
    world = toy.gen_world(("object", "operation", "combinator"))
    moves = [FakeKindMove(kind) for kind in ("object", "operation", "combinator", "observation")]
    state = run.generate(world, 30, 3, per_kind_min=5, layer_target=10, moves=moves)
    assert len(state.entries) == 30
    assert all(sum(entry.kind == kind for entry in state.entries.values()) >= 5
               for kind in world.open_kinds)
    assert moves[-1].calls == 0
    assert state.max_layer() >= 10
    observed = replace(toy.gen_world(), probes=("see",), truth_states=(0, 1))
    all_kinds = run.generate(observed, 28, 5, per_kind_min=5, layer_target=10,
                             moves=[FakeKindMove(kind) for kind in observed.open_kinds])
    assert len(all_kinds.entries) == 28
    assert {kind for kind in observed.open_kinds
            if sum(entry.kind == kind for entry in all_kinds.entries.values()) < 5} == set()


def test_checkpoint_round_trip_and_resume(tmp_path):
    world = toy.gen_world(("operation",))
    state = run.generate(world, 30, 17, per_kind_min=0, layer_target=1, moves=[OperationMove()])
    path = tmp_path / "checkpoint.json"
    run.save(state, path)
    restored = run.load(world, path)
    assert len(restored.entries) == 30
    assert restored.attempts == state.attempts
    assert restored.move_attempts == state.move_attempts
    assert list(restored.entries) == list(state.entries)
    assert restored.fingerprints == state.fingerprints
    assert restored.library.get(next(iter(restored.entries))).to_dict() == state.library.get(next(iter(state.entries))).to_dict()
    resumed = run.generate(world, 32, 17, per_kind_min=0, layer_target=1,
                           moves=[OperationMove()], state=restored)
    uninterrupted = run.generate(world, 32, 17, per_kind_min=0, layer_target=1,
                                 moves=[OperationMove()])
    assert list(resumed.entries) == list(uninterrupted.entries)
    assert [resumed.library.get(name).body for name in resumed.entries] == [
        uninterrupted.library.get(name).body for name in uninterrupted.entries]


def test_recursive_object_hints_survive_resume(tmp_path):
    from opulse.gen_v2.moves.object import MOVES

    world = toy.gen_world(("object",))
    initial = run.generate(world, 10, 19, per_kind_min=0, layer_target=0, moves=MOVES)
    assert any(entry.move == "obj.recursive" for entry in initial.entries.values())
    path = tmp_path / "recursive.json"
    run.save(initial, path)
    restored = run.load(world, path)
    assert restored.world.measures == initial.world.measures
    assert restored.world.bases == initial.world.bases
    resumed = run.generate(world, 14, 19, per_kind_min=0, layer_target=0,
                           moves=MOVES, state=restored)
    uninterrupted = run.generate(world, 14, 19, per_kind_min=0, layer_target=0,
                                 moves=MOVES, state=initial)
    assert resumed.attempts == uninterrupted.attempts
    assert [(name, resumed.library.get(name).to_dict()) for name in resumed.entries] == [
        (name, uninterrupted.library.get(name).to_dict()) for name in uninterrupted.entries]


def test_discovery_reports_transitive_missing_module(monkeypatch):
    from opulse.gen_v2.moves import registry

    original_import = importlib.import_module

    def import_with_missing_dependency(name):
        if name == "opulse.gen_v2.moves.object":
            raise ModuleNotFoundError("No module named 'missing_dependency'", name="missing_dependency")
        return original_import(name)

    monkeypatch.setattr(registry.importlib, "import_module", import_with_missing_dependency)
    with pytest.raises(ModuleNotFoundError, match="missing_dependency"):
        registry.discover_moves()


def test_review4_17_observation_requests_replay_after_checkpoint(tmp_path):
    from opulse.gen_v2.audit import audit
    from opulse.gen_v2.worlds import toy_truth

    world = toy_truth.gen_world()
    state = run.generate(world, 12, 4, per_kind_min=0, layer_target=0, time_limit=8)
    path = tmp_path / "observation.json"
    run.save(state, path)
    restored = run.load(world, path)
    assert set(restored.requests) == set(state.entries)
    assert restored.requests.keys() == state.requests.keys()
    report = audit(restored)
    assert report.ok and not report.skipped


def test_review4_17_all_kinds_replay_after_checkpoint(tmp_path):
    from opulse.gen_v2.audit import audit
    from opulse.gen_v2.worlds import toy_truth

    world = toy_truth.gen_world(("object", "operation", "combinator", "observation"))
    state = run.generate(world, 12, 9, per_kind_min=2, layer_target=1, time_limit=12)
    path = tmp_path / "all_kinds.json"
    run.save(state, path)
    restored = run.load(world, path)
    assert {entry.kind for entry in restored.entries.values()} == set(world.open_kinds)
    assert set(restored.requests) == set(restored.entries)
    report = audit(restored)
    assert report.ok and not report.skipped


def test_registry_and_cli_smoke(monkeypatch, capsys, tmp_path):
    assert isinstance(discover_moves(), dict)
    assert main(["list"]) == 0
    assert "toy" in capsys.readouterr().out
    monkeypatch.setattr(run, "discover_moves", lambda: {"operation": [OperationMove()]})
    output = tmp_path / "export"
    assert main(["run", "--world", "toy", "--target", "3", "--seed", "9",
                 "--per-kind-min", "0", "--layer-target", "1", "--out", str(output)]) == 0
    data = json.loads((output / "toy.json").read_text())
    assert len(data["entries"]) == 3
    assert (output / "toy.compact.json").exists() and (output / "toy.jsonl").exists()
    assert (output / "toy.md").read_text().strip()
    assert "3 admitted" in capsys.readouterr().out


def test_cli_refuses_exports_when_full_audit_fails(monkeypatch, tmp_path):
    from opulse.gen_v2 import __main__ as cli
    from opulse.gen_v2.audit import AuditFailure, AuditReport

    monkeypatch.setattr(cli, "generate", lambda *args: object())
    monkeypatch.setattr(cli, "audit", lambda state: AuditReport(failures=[AuditFailure("A1", "I1", "invalid")]))
    output = tmp_path / "not-published"
    assert main(["run", "--world", "toy", "--out", str(output)]) == 1
    assert not output.exists()


def test_review6_3_cli_world_slugs_do_not_collide(monkeypatch, tmp_path):
    from opulse.gen_v2 import __main__ as cli
    from opulse.gen_v2.worlds import classic

    monkeypatch.setattr(classic, "gen_world", lambda name: toy.gen_world(("operation",)))
    monkeypatch.setattr(cli, "generate", lambda world, *args: run.generate(
        toy.gen_world(("operation",)), 3, 9, per_kind_min=0, layer_target=1,
        moves=[OperationMove()]))
    output = ["run", "--target", "1", "--out", str(tmp_path)]
    assert main([*output, "--world", "toy"]) == 0
    assert main([*output, "--world", "classic:toy"]) == 0
    assert (tmp_path / "toy.json").exists() and (tmp_path / "classic-toy.json").exists()


def test_review6_5_cli_compact_curates_deep_showcase(monkeypatch, tmp_path):
    from opulse.gen_v2 import __main__ as cli

    monkeypatch.setattr(cli, "generate", lambda world, *args: run.generate(
        toy.gen_world(("operation",)), 12, 9, per_kind_min=0, layer_target=1,
        moves=[OperationMove()]))
    assert main(["run", "--world", "toy", "--target", "12", "--out", str(tmp_path)]) == 0
    compact = json.loads((tmp_path / "toy.compact.json").read_text())
    assert compact["showcase"] and compact["story"]
    assert {row["name"] for row in compact["showcase"]} == {row["name"] for row in compact["story"]}


def test_time_limit_and_missing_moves():
    world = toy.gen_world(("operation",))
    assert run.generate(world, 10, 1, time_limit=0, moves=[OperationMove()]).attempts == 0
    assert run.generate(world, 10, 1, moves={}).attempts == 0


def test_progress_reports_counts_layers_and_rejection_stages():
    updates = []
    state = run.generate(toy.gen_world(("operation",)), 30, 2, per_kind_min=0,
                         layer_target=1, moves=[OperationMove()], log=updates.append)
    assert len(updates) == 2
    assert updates[-1]["admitted"] == len(state.entries) == 30
    assert updates[-1]["counts"] == {"operation": 30}
    assert updates[-1]["max_layer"] == 1
    assert updates[-1]["rejections"] == {}


def test_checkpoint_round_trip_keeps_object_witnesses_and_operations(tmp_path):
    from opulse.atoms import kernel

    world = toy.gen_world()
    state = run.generate(world, 40, 5, per_kind_min=8, layer_target=2, time_limit=60)
    path = tmp_path / "checkpoint.json"
    run.save(state, path)
    restored = run.load(world, path)
    objects = [entry.name for entry in state.entries.values() if entry.kind == "object"]
    assert objects
    for name in objects:
        assert (kernel.call(name, (), restored.library.scope()).outcome ==
                kernel.call(name, (), state.library.scope()).outcome)
    for entry in state.entries.values():
        if entry.kind == "operation":
            args = tuple(state.sorts[sort].values[0] for sort in entry.signature.inputs)
            assert (kernel.call(entry.name, args, restored.library.scope()).outcome ==
                    kernel.call(entry.name, args, state.library.scope()).outcome)


def test_checkpoint_keeps_the_template_catalogue(tmp_path):
    from opulse.gen_v2 import templates

    world = toy.gen_world()
    state = run.generate(world, 60, 2, per_kind_min=5, layer_target=2, time_limit=60)
    before = templates.templates_to_json(state)
    path = tmp_path / "checkpoint.json"
    run.save(state, path)
    restored = run.load(world, path)
    assert templates.templates_to_json(restored) == before


def test_checkpoint_replays_bool_card_literals_identically(tmp_path):
    """Admission stores the core-codec form, so a reloaded library gives the same outcomes."""
    from opulse.atoms import kernel
    from opulse.atoms.values import outcome_equal
    from opulse.gen_v2.worlds import action

    world = action.gen_world()
    state = run.generate(world, 50, 1, per_kind_min=0, layer_target=0, time_limit=60)
    path = tmp_path / "checkpoint.json"
    run.save(state, path)
    restored = run.load(world, path)
    for name, entry in state.entries.items():
        if entry.kind != "operation":  # objects, combinators and observations replay through hooks
            continue
        for args in state.requests[name].domain[:4]:
            left = kernel.call(name, args, state.library.scope(), kernel.Limits(fuel=world.fuel))
            right = kernel.call(name, args, restored.library.scope(), kernel.Limits(fuel=world.fuel))
            assert outcome_equal(left.outcome, right.outcome) and left.steps == right.steps, (name, args)


def test_all_catalogue_adapters_construct_frozen_library():
    from importlib import import_module

    for name in ("action", "automata", "calendar", "circuits", "dice", "geometry", "grammar",
                 "hidden", "integer", "kitchen", "lists", "melody", "molecules", "permutation",
                 "pixels", "rhythm", "roads", "shadows", "text", "versions"):
        world = import_module(f"opulse.gen_v2.worlds.{name}").gen_world()
        library = GenLibrary(world.decl, world.atoms, world.dialect, world.extra_scope,
                             world.signatures)
        assert library.world.world_hash() == world.decl.world_hash(), name


def test_hidden_frozen_world_checkpoint_round_trip(tmp_path):
    from opulse.gen_v2.base import GenState
    from opulse.gen_v2.worlds import hidden

    world = hidden.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                       world.extra_scope, world.signatures), dict(world.sorts))
    path = tmp_path / "hidden.json"
    run.save(state, path)
    restored = run.load(world, path)
    assert restored.library.world.world_hash() == world.decl.world_hash()


def test_a_move_error_is_a_recorded_refusal_not_a_crash():
    class Broken:
        kind = "operation"
        name = "test.broken"

        def __call__(self, state, rng):
            raise TypeError("'<' not supported between instances of 'Card' and 'Card'")

    state = run.generate(toy.gen_world(("operation",)), 3, 1, per_kind_min=0, layer_target=0,
                         moves=[Broken(), OperationMove()])
    assert len(state.entries) == 3
    assert any(item.stage == "move_error" and item.move == "test.broken" for item in state.rejections)


def test_given_atom_host_error_in_duplicate_filter_is_not_a_crash():
    # roads' sort_frontier host raises AttributeError on some declared-sort values; the
    # "same as given atom" filter must treat that atom as different instead of crashing.
    from opulse.gen_v2.worlds import roads

    state = run.generate(roads.gen_world(), 12, 1, time_limit=15)
    assert state.entries


def test_open_law_kind_has_no_generation_quota():
    # integer, circuits and versions open the law kind and have a law move; in versions every law
    # conjecture failed its check, and generation ran to the safety limit waiting for law entries.
    from opulse.gen_v2.moves.registry import discover_moves
    from opulse.gen_v2.worlds import integer

    class NoLaw:
        kind, name = "law", "law.none"

        def __call__(self, state, rng):
            return None

    moves = [move for kind, options in discover_moves().items() if kind != "law" for move in options]
    moves.append(NoLaw())
    import time

    start = time.monotonic()
    state = run.generate(integer.gen_world(), 20, 1, per_kind_min=3, layer_target=0,
                         time_limit=60, moves=moves)
    assert time.monotonic() - start < 50  # stopped by the quotas, not by the time limit
    counts = {kind: sum(entry.kind == kind for entry in state.entries.values())
              for kind in ("object", "operation", "combinator", "observation", "law")}
    assert "law" in integer.gen_world().open_kinds and counts["law"] == 0
    assert all(counts[kind] >= 3 for kind in ("object", "operation", "combinator", "observation"))
    assert state.attempts < 100 * 20  # stopped by the quotas, not by the attempt cap
