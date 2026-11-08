"""The Learn/Checks walkthrough is a reproducible kernel artifact."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import PipelineError
from opulse.atoms.notation import parse_definition
from opulse.atoms.spec import Contract
from tools import atoms2_walk_export
from tools.atoms2_walk_export import (
    build_library,
    definitions,
    export,
    law_and_bridge,
    outcome_text,
    requests,
    trace_nodes,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/assets/data/atoms2/walk.json"


def test_fresh_export_equals_committed_bytes():
    from opulse.notation3.export import add_notation3

    expected = json.dumps(add_notation3(export(), 'atoms2', source='atoms2/walk.json'),
                          indent=2, ensure_ascii=True) + "\n"
    assert FIXTURE.read_text(encoding="utf-8") == expected
    from tools.export_digest import inputs_sha256

    assert json.loads(expected)["core_digest"] == inputs_sha256(
        ROOT, (ROOT / "src/opulse/atoms").glob("*.py"))


def test_command_line_check_uses_the_same_atom_hash_as_imported_export():
    subprocess.run([sys.executable, "tools/atoms2_walk_export.py", "--check"], cwd=ROOT, check=True)


def test_check_mode_fails_for_stale_fixture(tmp_path, monkeypatch):
    target = tmp_path / "walk.json"
    target.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(atoms2_walk_export, "OUTPUT", target)
    monkeypatch.setattr(sys, "argv", ["atoms2_walk_export.py", "--check"])
    assert atoms2_walk_export.main() == 0
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        atoms2_walk_export.main()
    assert error.value.code == 2
    monkeypatch.setattr(sys, "argv", ["atoms2_walk_export.py"])
    assert atoms2_walk_export.main() == 0
    monkeypatch.setattr(sys, "argv", ["atoms2_walk_export.py", "--check"])
    assert atoms2_walk_export.main() == 0


def test_broken_object_reaches_canon_verification_not_dependency_rejection():
    failure = export()["definitions"][0]["failure"]
    assert failure["attempt"] == "Broken canon add(x, 2)"
    assert "depends_on" not in failure["error"]
    assert "canon" in failure["error"]


def test_scoped_law_replays_a_real_kernel_rewrite():
    law = law_and_bridge()["law"]
    assert law["method"] == "bounded"
    assert law["scope"] == "all 64 ordered pairs with each operand 0..7"
    assert law["evidence"]["scope"]["size"] == 64
    assert law["evidence"]["scope"]["checked"]["by"] == "library"
    assert law["evidence"]["checker"] == "opulse.atoms.library.Library.verify"
    assert law["evidence"]["content_hash"] == law["content_hash"]
    assert law["before_outcome"] == law["after_outcome"] == "Ok(70)"
    assert (law["rewrite_steps"], law["charged_steps"]) == (1, 3)
    assert parse_definition(law["declaration"]).kind == "law"


def test_bridge_verifies_all_recorded_interface_pairs():
    bridge = law_and_bridge()["bridge"]
    assert bridge["method"] == "bounded"
    assert (bridge["domain_size"], bridge["pairs_checked"]) == (16, 256)
    assert bridge["evidence"]["scope"]["size"] == 16
    assert bridge["evidence"]["scope"]["checked"]["by"] == "bridge verifier"
    assert bridge["evidence"]["checker"] == "opulse.atoms.bridges.verify_bridge"
    assert len(bridge["evidence"]["scope"]["checked"]["sha256"]) == 64
    assert bridge["checks"] == ["commutes", "total_on_domain"]
    assert (bridge["outcome"], bridge["layer0_steps"]) == ("Ok(2)", 1)
    assert parse_definition(bridge["declaration"]).kind == "bridge"


def test_all_four_kinds_go_through_five_stations_with_real_evidence():
    fixture = json.loads(FIXTURE.read_text())
    assert [item["kind"] for item in fixture["definitions"]] == [
        "object", "operation", "combinator", "observation"]
    for row in fixture["definitions"]:
        assert row["declaration"].isascii() and parse_definition(row["declaration"]).kind == row["kind"]
        stages = row["stages"]
        assert [stage["status"] for stage in stages] == [
            "written", "checked", "callable", "verified", "promoted"]
        assert len({stage["content_hash"] for stage in stages}) == 1
        assert all(stage["evidence"] is None for stage in stages[:3])
        assert stages[3]["evidence"] == stages[4]["evidence"]
        evidence = stages[4]["evidence"]
        assert evidence["method"] in ("bounded", "exhaustive")
        assert evidence["scope"]["size"] > 0
        assert evidence["content_hash"] == stages[4]["content_hash"]
        assert stages[4]["contract"] is not None
        example = row["example"]
        assert example["layer0_steps"] == sum(item["steps"] for item in example["trace"]
                                                if item["layer"] == 0 and item["leaf"] and item["call"] != "root")
        assert example["trace"][0]["steps"] == example["layer0_steps"]
    assert fixture["definitions"][2]["stages"][4]["evidence"]["scope"]["op_family"] == ["bump_even"]
    assert fixture["link_limit"]["error"] == (
        "operation bump_even may read or change truth; operation advance may read or change truth"
    )
    assert "bump_even and advance take the truth sort Even" in fixture["link_limit"]["meaning"]
    assert "not on the truth sort" in fixture["link_limit"]["meaning"]


def test_spec_05_learn_copy_keeps_truth_sort_rejection() -> None:
    source = (ROOT / "docs/assets/js/atoms2/learn-checks.js").read_text()
    assert "Spec 0.5 still rejects this call: bump_even and advance take the truth sort Even" in source
    assert "This historical error does not describe spec 0.5" not in source


def test_editing_verified_definition_changes_hash_and_drops_evidence():
    library = build_library()
    obj, operation, _, _ = definitions()
    for definition in (obj, operation):
        library.write(definition)
        library.check(definition.name)
        sample = (0,) if definition.kind == "object" else (kernel.Card("Even", "val", (0,)),)
        library.make_callable(definition.name, [sample])
        library.verify(definition.name, requests(definition.kind))
    original_hash = library.content_hash(operation.name)
    assert library.get(operation.name).evidence.content_hash == original_hash
    changed = replace(operation, body=n.Call("advance", (n.Call("advance", (n.Var("arg0"),)),)))
    library.replace(operation.name, changed)
    assert library.get(operation.name).evidence is None
    assert library.get(operation.name).status == "written"
    assert library.content_hash(operation.name) != original_hash
    assert library.get(operation.name).contract is None


def test_promoted_definition_is_immutable():
    library = build_library()
    definition = definitions()[0]
    library.write(definition)
    library.check(definition.name)
    library.make_callable(definition.name, [(18,)])
    library.verify(definition.name, requests(definition.kind))
    library.promote(definition.name, Contract("Only in the checked finite domain"))
    with pytest.raises(PipelineError, match="promoted definitions are immutable"):
        library.replace(definition.name, replace(definition, body=n.Lit(True)))
    assert library.get(definition.name).evidence is not None
    assert library.run("Even.make", (19,)).outcome == kernel.Bottom("invalid")


def test_seeded_sample_cannot_promote():
    fixture = json.loads(FIXTURE.read_text())
    failed = fixture["definitions"][1]["failure"]
    assert failed["error"] == "sampled evidence cannot be promoted"
    assert failed["evidence"]["method"] == "sampled"
    assert failed["evidence"]["seed"] == 17
    assert failed["evidence"]["scope"]["size"] == 2
    assert all(row["stages"][-1]["evidence"]["method"] != "sampled"
               for row in fixture["definitions"])


def test_failure_outcomes_and_trace_flattening():
    fixture = json.loads(FIXTURE.read_text())
    failures = {row["kind"]: row["failure"]["error"] for row in fixture["definitions"]}
    assert "canon_idempotent" in failures["object"]
    assert failures["combinator"] == "Unknown(fuel)"
    assert "not granted" in failures["observation"]
    assert outcome_text(kernel.Ok(12)) == "Ok(12)"
    assert outcome_text(kernel.Bottom("invalid")) == "Bottom(invalid)"
    assert outcome_text(kernel.Unknown("fuel")) == "Unknown(fuel)"
    assert trace_nodes(None) == []


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_badges_distinguish_pre_run_and_verified_stations():
    script = r"""
const assert = require('node:assert/strict');
const walk = require(process.argv[1]);
require(process.argv[2]);
const checks = globalThis.A2.learnChecks;
for (const item of walk.definitions) {
  assert.deepEqual(item.stages.map(checks.walkBadge),
    ['design', 'design', 'executable', item.stages[3].evidence.method,
     item.stages[4].evidence.method]);
}
"""
    result = subprocess.run(["node", "-e", script, str(FIXTURE),
                             str(ROOT / "docs/assets/js/atoms2/learn-checks.js")],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
