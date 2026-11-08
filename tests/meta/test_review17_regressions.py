"""Reproducible evidence commitments and routine sources (atoms-meta 8-9)."""

import copy
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.library import atoms_digest
from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import decode
from opulse.meta import cards, code
from opulse.meta.builder import world_value
from opulse.meta.builder.instantiate import instantiate
from opulse.meta.check import export_problems
from opulse.meta.export_util import outcome_json, parse_meta_definition
from opulse.meta.identity import Ledger
from opulse.meta.vn.asm import assemble
from opulse.meta.vn.report import routine_id
from opulse.meta.worlds.builder.story import promoted_mul5, promoted_power5
from opulse.meta.worlds.code.world import library as code_library
from opulse.meta.worlds.compiler.world import make_library as compiler_library
from opulse.meta.worlds.vonneumann.story import creation_story

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "docs/assets/data/meta"


def test_builder_evidence_matches_two_independent_processes():
    command = (sys.executable, "-c", ("import json; "
               "from opulse.meta.worlds.builder.story import creation; "
               "library, _ = creation(); "
               "print(json.dumps({name: definition.evidence.to_dict() "
               "for name, definition in library.definitions.items() "
               "if definition.origin == 'invented'}, sort_keys=True))"))
    snapshots = [json.loads(subprocess.check_output(command, cwd=ROOT, text=True))
                 for _ in range(2)]
    assert snapshots[0] == snapshots[1]
    published = json.loads((EXPORTS / "builder.json").read_text())
    assert len(snapshots[0]) == len(published["story"]) - 6
    for entry in published["story"]:
        if entry["name"] in snapshots[0]:
            evidence = snapshots[0][entry["name"]]
            assert entry["status"] == "promoted"
            assert entry["evidence"]["atoms_hash"] == evidence["atoms_hash"]
            assert entry["evidence"]["deps_hash"] == evidence["deps_hash"]


def test_ledger_outputs_commit_code_and_current_atoms():
    for name in ("code", "compiler"):
        published = json.loads((EXPORTS / f"{name}.json").read_text())
        current_atoms_hash = atoms_digest((code_library if name == "code" else compiler_library)().atoms)
        if name == "code":
            records = [row for row in published["generated"] if row["status"] == "promoted"]
            assert len(records) == 2
            for row in records:
                assert row["evidence"][-1]["content_hash"] == row["hash"]
                assert row["evidence"][-1]["atoms_hash"] == current_atoms_hash
        else:
            records = [row for row in published["story"] if row["name"] in (
                "SourceCode", "CompiledProgram", "LearnerSource", "LearnerProgram")]
            assert len(records) == 4
            for row in records:
                assert row["evidence"]["content_hash"] == row["examples"][0]["code_hash"]
                assert row["evidence"]["atoms_hash"] == current_atoms_hash
    for make in (promoted_mul5, promoted_power5):
        result = make()
        value, program, ledger = result[:3]
        digest = code.code_hash(program)
        evidence = ledger.record(digest, world_value.world_hash(value)).evidence[-1]
        _, entries = instantiate(value)
        from opulse.atoms.kernel import Atom

        assert evidence.content_hash == digest
        assert evidence.atoms_hash == atoms_digest(tuple(
            entry for entry in entries if isinstance(entry, Atom)))


def test_output_promotion_rejects_missing_or_wrong_commitments():
    value, program, _, _ = promoted_mul5()
    world_hash = world_value.world_hash(value)
    _, entries = instantiate(value)
    from opulse.atoms.kernel import Atom

    atoms = tuple(entry for entry in entries if isinstance(entry, Atom))
    digest = code.code_hash(program)
    contract = Contract("verified z5 product")
    ledger = Ledger()
    ledger.add(program, world_hash)
    with pytest.raises(ValueError, match="commit current code and atoms"):
        cards.promote_output(ledger, digest, world_hash, atoms, contract)
    evidence = Evidence("exhaustive", {"domain": "all 25 pairs of z5", "size": 25},
                        world_hash=world_hash)
    ledger.attach_evidence(digest, world_hash, evidence)
    with pytest.raises(ValueError, match="commit current code and atoms"):
        cards.promote_output(ledger, digest, world_hash, atoms, contract)
    ledger.attach_evidence(digest, world_hash, replace(
        evidence, content_hash=digest, atoms_hash="0" * 64))
    with pytest.raises(ValueError, match="commit current code and atoms"):
        cards.promote_output(ledger, digest, world_hash, atoms, contract)
    ledger.attach_evidence(digest, world_hash, replace(
        evidence, content_hash=digest, atoms_hash=atoms_digest(atoms)))
    cards.promote_output(ledger, digest, world_hash, atoms, contract)
    assert ledger.status(digest, world_hash) == "promoted"


def test_routine_ascii_commits_specific_bytes_base_and_dependencies():
    path = EXPORTS / "vonneumann.json"
    published = json.loads(path.read_text())
    routines = [entry for entry in published["story"] if "routine_id" in entry]
    assert len(routines) == 4
    assert len({parse_meta_definition(row["ascii"]).body for row in routines}) == 4
    library, _ = creation_story()
    for row in routines:
        body = parse_meta_definition(row["ascii"]).body
        assert isinstance(body, nodes.Let) and body.name == "routine_base"
        base = body.value.value
        assert isinstance(body.body, nodes.Let) and body.body.name == "routine_bytes"
        assert bytes.fromhex(body.body.value.value) == bytes(assemble(row["body"], 32))
        assert row["routine_id"] == routine_id(32, base, assemble(row["body"], 32))
        assert row["depends_on"] == sorted(nodes.references(body))
        example = row["examples"][0]
        run = kernel.evaluate(body, {"s": decode(example["inputs"][0])}, library.scope(),
                              kernel.Limits(fuel=100))
        assert run.steps == example["steps"] == row["cost"]["steps"]
        assert outcome_json(run.outcome) == example["outcome"]
    changed = copy.deepcopy(published)
    changed["story"][0]["ascii"] = routines[1]["ascii"].replace(
        routines[1]["name"], routines[0]["name"])
    assert any("routine bytes/base" in problem for problem in export_problems(
        changed, path, strict=True))
