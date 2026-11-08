import gzip
import json

import pytest

from opulse.gen_v2 import batch, configs


def test_config_adapters_are_installed():
    available, missing = configs.available_adapters()
    assert set(configs.WORLDS) == set(available)
    assert "pixels" in missing or "pixels" in available
    assert all(config["adapter"] == available[name] for name, config in configs.WORLDS.items())


def test_quick_toy_publication(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(configs.WORLDS, "toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0, "layer_target": 0,
        "time_limit": 3, "seed": 3, "flagship": False})
    state = batch.run_world("toy", quick=True)
    assert len(state.entries) >= 4
    assert batch.meets_target("toy", state)
    summary = batch.publish("toy", state, tmp_path)
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["schema"] == batch.SCHEMA
    assert index["worlds"]["toy"] == summary
    assert summary["counts"] and summary["graph"] and summary["audit"]["checked"]
    assert summary["seed"] == 3 and summary["target_met"]
    assert len(json.loads((tmp_path / "toy.json").read_text())["entries"]) <= 100
    with gzip.open(tmp_path.parent / "dataset-exports/gen_v2/toy.jsonl.gz", "rt") as dataset:
        assert len(dataset.read().splitlines()) == len(state.entries)
    assert (tmp_path.parent / "dataset-exports/gen_v2/toy.jsonl.gz").read_bytes()[4:8] == b"\0" * 4
    assert not (tmp_path / "toy.jsonl").exists()
    assert (tmp_path / "toy.md").read_text().startswith("# toy")
    compact = json.loads((tmp_path / "toy.json").read_text())
    assert "showcase" in compact and "story" in compact
    assert "four_kinds_path" in compact
    assert summary["four_kinds_path"] == (compact["four_kinds_path"] is not None)
    assert summary["audit"]["sample"] is None
    assert summary["laws"] == len(json.loads((tmp_path / "toy.laws.json").read_text())["laws"])
    assert summary["bridges"] == len(json.loads((tmp_path / "toy.bridges.json").read_text())["bridges"])
    assert batch.main(["--report", "--out", str(tmp_path)]) == 0
    assert "toy |" in capsys.readouterr().out
    assert batch.main(["--worlds", "toy", "--quick", "--out", str(tmp_path)]) == 0


def test_review6_6_quick_unmet_target_is_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setitem(configs.WORLDS, "quick-toy", {
        "adapter": "toy", "target": 500, "per_kind_min": 50,
        "layer_target": 10, "time_limit": 3, "seed": 3})
    assert batch.main(["--worlds", "quick-toy", "--quick", "--out", str(tmp_path)]) == 0
    row = json.loads((tmp_path / "index.json").read_text())["worlds"]["quick-toy"]
    assert row["target_met"] is False and row["published"] is False and row["reason"] == "quick"


def test_unavailable_adapter_is_skipped(tmp_path, capsys):
    assert batch.main(["--worlds", "does-not-exist", "--quick", "--out", str(tmp_path)]) != 0
    assert "Skipping does-not-exist: unknown adapter" in capsys.readouterr().out
    assert not (tmp_path / "index.json").exists()


def test_depth_and_open_kind_quotas(monkeypatch):
    from opulse.gen_v2.base import Entry, GenState
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds.toy import gen_world

    world = gen_world(("operation", "observation"))
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    state.entries["f1"] = Entry("f1", "operation", 10, None, "test", (), (), 1, 1, 1)
    monkeypatch.setitem(configs.WORLDS, "quota-toy", {
        "target": 1, "per_kind_min": 0, "layer_target": 10})
    assert not batch.meets_target("quota-toy", state)
    state.entries["q2"] = Entry("q2", "observation", 10, None, "test", (), (), 1, 1, 1)
    assert batch.meets_target("quota-toy", state)


def test_blocker_report_does_not_publish(tmp_path, monkeypatch):
    from opulse.gen_v2.audit import AuditFailure, AuditReport
    from opulse.gen_v2.base import Rejection

    monkeypatch.setitem(configs.WORLDS, "blocked-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 50,
        "layer_target": 10, "time_limit": 1, "seed": 3})
    state = batch.run_world("blocked-toy", quick=True)
    configs.WORLDS["blocked-toy"]["target"] = 500
    state.rejections.append(Rejection("obj.compose", "object", "verify", "KeyError: 'B1'"))
    report = AuditReport(failures=[AuditFailure("B1", "I1", "missing")])
    summary = batch.blocker("blocked-toy", state, report, tmp_path)
    assert summary["top_rejection_per_kind"]["object"]["move"] == "obj.compose"
    assert summary["audit"]["failures"][0]["name"] == "B1"
    assert "blocked-toy |" in batch.report_table(json.loads((tmp_path / "index.json").read_text()))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["index.json"]


def test_blocker_index_is_independent_of_wall_clock(tmp_path, monkeypatch):
    from opulse.gen_v2.audit import AuditReport

    monkeypatch.setitem(configs.WORLDS, "blocked-clock", {
        "adapter": "toy", "target": 500, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 1, "seed": 3})
    state = batch.run_world("blocked-clock", quick=True)
    state.elapsed_seconds = 1.0
    report = AuditReport()
    report.timings["total_seconds"] = 3.0
    batch.blocker("blocked-clock", state, report, tmp_path)
    first = (tmp_path / "index.json").read_bytes()
    state.elapsed_seconds = 99.0
    report.timings["total_seconds"] = 42.0
    batch.blocker("blocked-clock", state, report, tmp_path)
    assert (tmp_path / "index.json").read_bytes() == first


def test_export_error_records_blocker(tmp_path, monkeypatch, capsys):
    from opulse.gen_v2.audit import AuditReport

    monkeypatch.setitem(configs.WORLDS, "error-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 2, "seed": 3})
    monkeypatch.setattr(batch, "audit", lambda *args, **kwargs: AuditReport())

    def fail_publish(*args, **kwargs):
        raise TypeError("unsupported export value")

    monkeypatch.setattr(batch, "publish", fail_publish)
    assert batch.main(["--worlds", "error-toy", "--out", str(tmp_path)]) != 0
    assert "unsupported export value" in capsys.readouterr().out
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["worlds"]["error-toy"]["export_error"] == "TypeError: unsupported export value"


def test_move_crash_records_blocker(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(configs.WORLDS, "crash-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 2, "seed": 3})

    def crash(*args, **kwargs):
        raise KeyError("witness")

    monkeypatch.setattr(batch, "run_world", crash)
    assert batch.main(["--worlds", "crash-toy", "--out", str(tmp_path)]) != 0
    assert "KeyError" in capsys.readouterr().out
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["worlds"]["crash-toy"]["run_error"] == "KeyError: 'witness'"


def test_publish_repeat_is_byte_identical(tmp_path, monkeypatch):
    from opulse.gen_v2.worlds import toy

    monkeypatch.setitem(configs.WORLDS, "toy-ops", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 4, "seed": 3})
    monkeypatch.setattr(batch, "_world", lambda adapter: toy.gen_world(("operation",)))
    state = batch.run_world("toy-ops")
    first = batch.publish("toy-ops", state, tmp_path)
    files = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    compressed = (tmp_path.parent / "dataset-exports/gen_v2/toy-ops.jsonl.gz").read_bytes()
    assert not first["audit"]["failures"]
    assert batch.publish("toy-ops", state, tmp_path) == first
    assert files == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert compressed == (tmp_path.parent / "dataset-exports/gen_v2/toy-ops.jsonl.gz").read_bytes()
    second_dir = tmp_path / "second"
    second = batch.run_world("toy-ops")
    batch.publish("toy-ops", second, second_dir)
    for filename in ("toy-ops.json", "toy-ops.md",
                     "toy-ops.laws.json", "toy-ops.bridges.json", "index.json"):
        assert (tmp_path / filename).read_bytes() == (second_dir / filename).read_bytes()
    assert compressed == (second_dir.parent / "dataset-exports/gen_v2/toy-ops.jsonl.gz").read_bytes()


def test_classic_slug_and_dataset_layout(tmp_path, monkeypatch):
    from opulse.gen_v2.worlds import toy

    monkeypatch.setitem(configs.WORLDS, "classic:toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 3, "seed": 3})
    monkeypatch.setattr(batch, "_world", lambda adapter: toy.gen_world(("operation",)))
    state = batch.run_world("classic:toy")
    summary = batch.publish("classic:toy", state, tmp_path)
    assert (tmp_path / "classic-toy.json").exists()
    assert (tmp_path.parent / "dataset-exports/gen_v2/classic-toy.jsonl.gz").exists()
    assert json.loads((tmp_path / "index.json").read_text())["worlds"]["classic-toy"] == summary
    batch.blocker("classic:toy", state, batch._audit_once(state), tmp_path)
    assert not (tmp_path / "classic-toy.json").exists()
    assert not (tmp_path.parent / "dataset-exports/gen_v2/classic-toy.jsonl.gz").exists()


def test_slug_rejects_unsafe_path_components():
    assert batch._slug("classic:bits") == "classic-bits"
    assert batch._slug("../A B") == "a-b"


def test_requested_missing_adapter_fails(tmp_path, capsys):
    assert batch.main(["--worlds", "unknown-world", "--out", str(tmp_path)]) != 0
    assert "unknown adapter" in capsys.readouterr().out


def test_requested_unmet_target_fails(tmp_path, monkeypatch):
    monkeypatch.setitem(configs.WORLDS, "unmet-toy", {
        "adapter": "toy", "target": 500, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 1, "seed": 3})
    assert batch.main(["--worlds", "unmet-toy", "--out", str(tmp_path)]) != 0
    assert not (tmp_path / "unmet-toy.json").exists()


def test_review6_7_story_error_has_explicit_fallback_and_reason(tmp_path, monkeypatch):
    monkeypatch.setitem(configs.WORLDS, "story-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 3, "seed": 3})
    state = batch.run_world("story-toy")
    monkeypatch.setattr(batch, "showcase", lambda state: [
        {"name": "bad"}, {"name": "good"}])

    def story(state, names):
        if names == ["bad"]:
            raise TypeError("unencodable trace")
        return [{"name": "good"}]

    monkeypatch.setattr(batch, "export_story", story)
    summary = batch.publish("story-toy", state, tmp_path)
    compact = json.loads((tmp_path / "story-toy.json").read_text())
    assert compact["story"] == [
        {"name": "bad", "error": "unencodable trace", "fallback": True, "examples": []},
        {"name": "good"}]
    assert summary["story_errors"] == compact["story_errors"] == [
        {"name": "bad", "error": "unencodable trace"}]


def test_story_bottom_is_encoded(tmp_path, monkeypatch):
    from opulse.atoms.values import Bottom

    monkeypatch.setitem(configs.WORLDS, "bottom-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 3, "seed": 3})
    state = batch.run_world("bottom-toy")
    monkeypatch.setattr(batch, "export_story", lambda state, names: [
        {"name": names[0], "outcome": Bottom("miss")}])
    batch.publish("bottom-toy", state, tmp_path)
    story = json.loads((tmp_path / "bottom-toy.json").read_text())["story"]
    assert story[0]["outcome"] == {"t": "bottom", "v": "miss"}


def test_run_continues_when_one_kind_lacks_depth(monkeypatch):
    from opulse.gen_v2.base import Entry
    from opulse.gen_v2.worlds import toy

    monkeypatch.setitem(configs.WORLDS, "depth-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 10, "time_limit": 10, "seed": 3})
    calls = []
    monkeypatch.setattr(batch, "_world", lambda adapter: toy.gen_world(("object", "operation")))

    def generate(world, target, seed, *, state, **kwargs):
        calls.append(target)
        for number in range(len(state.entries), target):
            kind = "operation" if number % 2 else "object"
            layer = 10 if kind == "operation" or len(calls) > 1 else 1
            state.entries[f"f{number}"] = Entry(f"f{number}", kind, layer, None,
                                                 "test", (), (), 1, 1, 1)
        state.attempts += 1
        return state

    monkeypatch.setattr(batch, "generate", generate)
    state = batch.run_world("depth-toy")
    assert calls == [4, 12]
    assert batch.meets_target("depth-toy", state)


def test_attempt_budget_continues_after_initial_target_is_missed(monkeypatch):
    from opulse.gen_v2.worlds import toy

    monkeypatch.setitem(configs.WORLDS, "budget-toy", {
        "adapter": "toy", "target": 4, "max_attempts": 800,
        "per_kind_min": 0, "layer_target": 10, "time_limit": 30, "seed": 3})
    monkeypatch.setattr(batch, "_world", lambda adapter: toy.gen_world(("operation",)))
    calls = []

    def generate(world, target, seed, *, state, **kwargs):
        calls.append(target)
        state.attempts = 100 * target
        return state

    monkeypatch.setattr(batch, "generate", generate)
    state = batch.run_world("budget-toy")
    assert calls == [4, 8]
    assert state.attempts == 800
    assert not state.time_limit_hit


def test_attempt_budget_progresses_past_overshot_target(monkeypatch):
    from opulse.gen_v2.base import Entry
    from opulse.gen_v2.worlds import toy

    monkeypatch.setitem(configs.WORLDS, "overshot-toy", {
        "adapter": "toy", "target": 4, "max_attempts": 1000,
        "per_kind_min": 0, "layer_target": 10, "time_limit": 30, "seed": 3})
    monkeypatch.setattr(batch, "_world", lambda adapter: toy.gen_world(("operation",)))
    calls = []

    def generate(world, target, seed, *, state, **kwargs):
        calls.append(target)
        for index in range(len(state.entries), target + 2):
            state.entries[f"f{index}"] = Entry(f"f{index}", "operation", 1, None,
                                                 "test", (), (), 1, 1, 1)
        state.attempts += 1
        return state

    monkeypatch.setattr(batch, "generate", generate)
    state = batch.run_world("overshot-toy")
    assert calls == [4, 10]
    assert len(state.entries) == 12


def test_flagship_requires_full_target_and_refuses_timeout(tmp_path, monkeypatch):
    from opulse.gen_v2.base import Entry, GenState
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds.toy import gen_world

    monkeypatch.setitem(configs.WORLDS, "flag-toy", {
        "target": 1000, "per_kind_min": 50, "layer_target": 10,
        "flagship": True, "seed": 1})
    world = gen_world(("operation",))
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    for index in range(300):
        state.entries[f"f{index}"] = Entry(f"f{index}", "operation", 10, None,
                                            "test", (), (), 1, 1, 1)
    assert not batch.meets_target("flag-toy", state)
    assert not batch.meets_target("flag-toy", state, publication=True)
    state.time_limit_hit = True
    with pytest.raises(ValueError, match="safety time limit"):
        batch.publish("flag-toy", state, tmp_path)
    assert not list(tmp_path.glob("*.json"))


def test_audit_is_full_even_after_mutation(monkeypatch):
    from opulse.gen_v2.audit import AuditReport

    calls = []
    monkeypatch.setattr(batch, "audit", lambda state, *, sample, seed: (
        calls.append((sample, seed)) or AuditReport()))
    state = type("State", (), {"entries": dict.fromkeys(range(1000)), "seed": 17})()
    batch._audit_once(state)
    assert calls == [(None, 17)]
    state.entries[1000] = None
    batch._audit_once(state)
    assert calls == [(None, 17), (None, 17)]


def test_publish_rejects_incomplete_or_skipped_audit(tmp_path, monkeypatch):
    from opulse.gen_v2.audit import AuditFailure, AuditReport

    monkeypatch.setitem(configs.WORLDS, "audit-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 3, "seed": 3})
    state = batch.run_world("audit-toy")
    partial = AuditReport(checked={"operation": 1})
    with pytest.raises(ValueError, match="incomplete audit"):
        batch.publish("audit-toy", state, tmp_path, audit_result=partial)
    full = AuditReport(checked={kind: sum(entry.kind == kind for entry in state.entries.values())
                                for kind in batch.KINDS},
                       skipped=[AuditFailure("f1", "I2", "boundary not replayed")])
    with pytest.raises(ValueError, match="incomplete audit"):
        batch.publish("audit-toy", state, tmp_path, audit_result=full)
    assert not list(tmp_path.iterdir())


def test_large_template_catalogue_is_separate_from_compact(tmp_path, monkeypatch):
    monkeypatch.setitem(configs.WORLDS, "template-toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0,
        "layer_target": 0, "time_limit": 3, "seed": 3})
    state = batch.run_world("template-toy", quick=True)
    original = batch.export_compact

    def with_templates(state, path, **kwargs):
        data = original(state, path, **kwargs)
        data["templates"] = [{"name": "T1", "payload": "a" * 2_100_000}]
        data["template_instance_links"] = {}
        data["template_counts"] = {"total": 1, "per_kind": {}}
        return data

    monkeypatch.setattr(batch, "export_compact", with_templates)
    summary = batch.publish("template-toy", state, tmp_path,
                            dataset_dir=tmp_path / "datasets")
    compact = json.loads((tmp_path / "template-toy.json").read_text())
    catalogue = json.loads((tmp_path / "template-toy.templates.json").read_text())
    assert summary["templates"] == 1
    assert compact["templates_file"] == "template-toy.templates.json"
    assert catalogue["templates"][0]["payload"] == "a" * 2_100_000
    assert summary["sizes_bytes"]["json"] <= 2_000_000


def test_review11_tag_order_featured_and_checkpoint(tmp_path, monkeypatch):
    from opulse.gen_v2 import run

    monkeypatch.setitem(configs.WORLDS, "toy", {
        "adapter": "toy", "target": 30, "per_kind_min": 0, "layer_target": 0,
        "time_limit": 60, "seed": 3, "flagship": False})
    assert batch.main(["--worlds", "toy", "--out", str(tmp_path / "site"),
                       "--datasets", str(tmp_path / "data"),
                       "--checkpoints", str(tmp_path / "ckpt")]) == 0
    with gzip.open(tmp_path / "data/toy.jsonl.gz", "rt") as dataset:
        rows = [json.loads(line) for line in dataset]
    restored = run.load(batch._world("toy"), tmp_path / "ckpt/toy.json")
    assert sorted(row["name"] for row in rows) == sorted(restored.entries)
    tagged = [row for row in rows if row["kind"] == "object" and row["spec"].get("tags")]
    assert tagged
    for row in tagged:
        # sorted JSON keys lose the declared order; tag_order keeps it (fold handler order)
        assert row["spec"]["tag_order"] == list(restored.library.get(row["name"]).spec.tags)
        assert sorted(row["spec"]["tag_order"]) == sorted(row["spec"]["tags"])
    compact = json.loads((tmp_path / "site/toy.json").read_text())
    featured = [item for item in compact["entries"] if item["featured"]]
    assert featured and all(item["interest"]["featured_why"] for item in featured)
    assert "## Featured" in (tmp_path / "site/toy.md").read_text()


def test_checkpoint_failure_does_not_stop_publication(tmp_path, monkeypatch, capsys):
    from opulse.gen_v2 import run

    monkeypatch.setitem(configs.WORLDS, "toy", {
        "adapter": "toy", "target": 4, "per_kind_min": 0, "layer_target": 0,
        "time_limit": 30, "seed": 3, "flagship": False})

    def refuse(state, path):
        path.write_text("partial")
        raise ValueError("checkpoint contains display-only host value; cannot restore")

    monkeypatch.setattr(run, "save", refuse)
    assert batch.main(["--worlds", "toy", "--out", str(tmp_path / "site"),
                       "--datasets", str(tmp_path / "data"),
                       "--checkpoints", str(tmp_path / "ckpt")]) == 0
    assert "checkpoint skipped" in capsys.readouterr().out
    assert not (tmp_path / "ckpt/toy.json").exists()
    assert (tmp_path / "data/toy.jsonl.gz").exists()


def test_open_law_kind_has_no_entry_quota(monkeypatch):
    # integer, circuits and versions declare law as an open kind; laws are separate records
    # discovered after generation, so the quota must not wait for law entries.
    from dataclasses import replace

    from opulse.gen_v2.base import Entry, GenState
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds.toy import gen_world

    world = gen_world(("operation",))
    world = replace(world, open_kinds=frozenset({"operation", "law", "bridge"}))
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    state.entries["f1"] = Entry("f1", "operation", 10, None, "test", (), (), 1, 1, 1)
    monkeypatch.setitem(configs.WORLDS, "law-toy", {
        "target": 1, "per_kind_min": 1, "layer_target": 10})
    assert batch.meets_target("law-toy", state)
    monkeypatch.setitem(configs.WORLDS, "law-toy", {
        "target": 1, "per_kind_min": 2, "layer_target": 10})
    assert not batch.meets_target("law-toy", state)
