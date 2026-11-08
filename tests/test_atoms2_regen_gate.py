"""Publication must reject stale generated UI artifacts without rewriting them."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import (
    atoms2_grammar_export,
    atoms2_parse_status,
    atoms2_roads_export,
    atoms2_tower_export,
)
from tools.site_gates import regen_check


def test_regeneration_gate_runs_every_exporter_in_check_mode(monkeypatch, capsys):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert regen_check.main() == 0
    assert [Path(command[1]).name for command, _ in calls] == list(regen_check.EXPORTERS)
    assert all(command[2:] == ["--check"] and kwargs["cwd"] == regen_check.ROOT
               for command, kwargs in calls)
    assert "passed" in capsys.readouterr().out


def test_regeneration_gate_reports_stale_filename_and_stops(monkeypatch, capsys):
    stale = "docs/assets/data/atoms2/roads_core.json"
    calls = []

    def run(command, **kwargs):
        calls.append(Path(command[1]).name)
        return SimpleNamespace(returncode=1 if calls[-1] == "atoms2_roads_export.py" else 0,
                               stdout="", stderr=f"stale generated data: {stale}")

    monkeypatch.setattr(subprocess, "run", run)
    assert regen_check.main() == 1
    assert calls == list(regen_check.EXPORTERS[:regen_check.EXPORTERS.index('atoms2_roads_export.py') + 1])
    assert stale in capsys.readouterr().err


def test_parse_status_check_rejects_stale_file_without_writing(tmp_path, monkeypatch, capsys):
    output = tmp_path / atoms2_parse_status.OUTPUT
    output.parent.mkdir(parents=True)
    output.write_text("stale fixture\n")
    monkeypatch.setattr(atoms2_parse_status, "ROOT", tmp_path)
    monkeypatch.setattr(atoms2_parse_status, "generate", lambda: {"entries": {}})
    monkeypatch.setattr("sys.argv", ["atoms2_parse_status.py", "--check"])
    try:
        atoms2_parse_status.main()
    except SystemExit as error:
        assert error.code == 1
    else:
        raise AssertionError("stale export passed the check")
    assert str(output) in capsys.readouterr().err
    assert output.read_text() == "stale fixture\n"


def test_regeneration_gate_rejects_real_stale_export(tmp_path, monkeypatch, capsys):
    tool = tmp_path / "tools/atoms2_parse_status.py"
    tool.parent.mkdir()
    shutil.copyfile(regen_check.ROOT / "tools/atoms2_parse_status.py", tool)
    for name, data in (
        ("docs/assets/data/worlds_v2/index.json", {"worlds": []}),
        ("docs/assets/data/challenge/v2.json", {"ladders": {}, "paths": {}}),
        ("docs/worlds/designs.json", {"worlds": {}}),
    ):
        source = tmp_path / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(data))
    output = tmp_path / atoms2_parse_status.OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("stale fixture\n")
    monkeypatch.setenv("PYTHONPATH", str(regen_check.ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setattr(regen_check, "ROOT", tmp_path)
    monkeypatch.setattr(regen_check, "EXPORTERS", ("atoms2_parse_status.py",))
    assert regen_check.main() == 1
    assert str(output) in capsys.readouterr().err
    assert output.read_text() == "stale fixture\n"


def test_grammar_input_digest_tracks_design_source(monkeypatch):
    first = atoms2_grammar_export.input_digest()
    assert atoms2_grammar_export.input_digest() == first
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: b"changed design" if path ==
                        atoms2_grammar_export.DESIGN else original(path))
    assert atoms2_grammar_export.input_digest() != first


def test_grammar_check_reuses_only_matching_source_pinned_export(tmp_path, monkeypatch):
    output = tmp_path / "grammar_core.json"
    monkeypatch.setattr(atoms2_grammar_export, "OUTPUT", output)
    monkeypatch.setattr(atoms2_grammar_export, "input_digest", lambda: "source")
    artifact = {"schema": "opulse.atoms2_grammar_core/1", "inputs_sha256": "source",
                "rows": {kind: {} for kind in ("object", "operation", "combinator", "observation")}}
    checksum = hashlib.sha256(json.dumps(artifact, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=True).encode("ascii")).hexdigest()
    artifact["digest"] = checksum
    output.write_text(json.dumps(artifact))
    calls = []
    monkeypatch.setattr(atoms2_grammar_export, "export", lambda: calls.append(True) or artifact)
    monkeypatch.setattr(sys, "argv", ["atoms2_grammar_export.py", "--check"])
    atoms2_grammar_export.main()
    assert not calls
    artifact["digest"] = "tampered"
    output.write_text(json.dumps(artifact))
    with pytest.raises(SystemExit, match="1"):
        atoms2_grammar_export.main()
    assert calls == [True]


@pytest.mark.parametrize("exporter,entrypoint", [
    (atoms2_roads_export, "build_library"),
    (atoms2_grammar_export.story, "build_library"),
    (atoms2_tower_export, "build_export"),
])
def test_world_build_failures_are_not_reported_as_stale(monkeypatch, exporter, entrypoint):
    def fail(**kwargs):
        raise RuntimeError("world constructor broke")

    monkeypatch.setattr(exporter, entrypoint, fail)
    if exporter is atoms2_roads_export:
        call = exporter.build_export
        world = "roads"
    elif exporter is atoms2_tower_export:
        monkeypatch.setattr(sys, "argv", ["atoms2_tower_export.py", "--check"])
        call = exporter.main
        world = "integer"
    else:
        call = atoms2_grammar_export.export
        world = "grammar"
    with pytest.raises(RuntimeError, match=f"{world} world code failed") as error:
        call()
    assert isinstance(error.value.__cause__, RuntimeError)
    assert "stale UI data" in str(error.value)
