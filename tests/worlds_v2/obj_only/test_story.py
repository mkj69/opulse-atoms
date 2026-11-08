"""Exact object constructor, permission and committed-export regressions."""

import ast
import json
from dataclasses import replace
from fractions import Fraction

import pytest

from opulse.atoms import nodes as n
from opulse.atoms.kernel import FnRef
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    Edge,
    LawSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.values import Bottom, Ok, Unknown, decode, encode_outcome
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.export_util import body_sha256, source_matches
from opulse.worlds_v2.obj_only import export, hosts, reference
from opulse.worlds_v2.obj_only.story import (
    NAMES,
    answer,
    build_library,
    definitions,
    design,
    example_raws,
    showcase_raw,
)
from opulse.worlds_v2.obj_only.world import DECL_PATH, decl, new_library


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def published():
    return json.loads(export.EXPORT_PATH.read_text(encoding="utf-8"))


def test_published_sources_match_stored_bodies(library, published):
    assert {row["name"] for row in published["story"] if "ascii" not in row} == {
        "Rat", "SparsePoly", "Span", "BernsteinPatch", "SignTile", "SignCover", "RootBracket", "RootAtlas",
    }
    for row, card in zip(published["story"], design()["tower"]):
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert row["design_decl"] == card["decl"]
        if "ascii" in row:
            assert row["decl"] == row["ascii"]
            assert source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row


def test_declaration_and_permission_boundary():
    assert validate(load(DECL_PATH)) == []
    assert WorldDecl.from_dict(decl().to_dict()).to_dict() == decl().to_dict()
    assert decl().open_kinds == ("object",)
    library = new_library()
    candidates = (
        Definition("forged_operation", "operation", "invented", 1, (),
                   OperationSpec("forged_operation", "transform", (Edge("int"),), Edge("int"), "copy"), n.Var("x")),
        Definition("forged_combinator", "combinator", "invented", 1, (),
                   CombinatorSpec("forged_combinator", ("x",), (), n.Var("x")), n.Var("x")),
        Definition("forged_observation", "observation", "invented", 1, (),
                   ObservationSpec("forged_observation", ("x",), n.Var("x")), n.Var("x")),
        Definition("forged_law", "law", "invented", 1, (),
                   LawSpec("forged_law", (("x", "int"),), n.Lit(True)), n.Lit(True)),
        Definition("forged_bridge", "bridge", "invented", 1, (),
                   BridgeSpec("forged_bridge", "int", "int", n.Var("x")), n.Var("x")),
        Definition("forged_template", "template", "invented", 1, (),
                   TemplateSpec("forged_template", (), "operation", {}), n.Lit(0)),
    )
    for candidate in candidates:
        with pytest.raises(PipelineError, match=f"kind {candidate.kind} is closed"):
            library.write(candidate)
        assert candidate.name not in library.records()


def test_given_combinators_and_sealed_public_read(library):
    assert {"map", "fold", "structural", "branch", "bounded"} <= {
        item["name"] for item in library.world.combinators["library"]
    }
    assert library.run("map", (FnRef("neg"), (1, 2, 3))).outcome == Ok((-1, -2, -3))
    assert library.run("fold", (FnRef("add"), 0, (1, 2, 3))).outcome == Ok(6)
    assert library.run("structural", (FnRef("add"), 0, (1, 2, 3))).outcome == Ok(6)
    assert library.run("branch", (FnRef("bounded_count"), FnRef("neg"),
                                  FnRef("bounded_count"), 2)).outcome == Ok(-2)
    assert library.run("bounded", (FnRef("neg"), 2, 3)).outcome == Ok(-2)
    assert library.run("bounded", (FnRef("neg"), 2, 21)).outcome == Bottom("depth_limit")
    assert library.run("binom", (5, 2)).outcome == Ok(10)
    assert library.run("div_exact", (6, 4)).outcome == Bottom("nonexact_division")
    assert library.run("sort", ((3, 1, 2),)).outcome == Ok((1, 2, 3))
    rat = library.run("Rat.make", (hosts.raw("Rat", 2, 4),)).outcome
    assert library.run("read", (rat.value, "num")).outcome == Ok(1)
    assert library.run("read", (rat.value, "den")).outcome == Ok(2)
    assert library.run("read", (rat.value, "private")).outcome == Bottom("sealed_field")
    assert library.run("value", (rat.value,)).outcome == Ok("Rat<1/2>")
    assert library.run("accepted", (rat.value,)).outcome == Ok(True)
    assert library.run("accepted", (Bottom("invalid"),)).outcome == Ok(False)
    assert library.run("Rat.make", (hosts.raw("Rat", 1, 0),)).outcome == Bottom("invalid")


def test_every_story_example_replays_exactly(library, published):
    assert len(published["story"]) == len(NAMES) == 8
    assert reference.example_checks() == {index: item["value"] for index, item in
                                           enumerate(design()["tower"], 1)}
    for name, raw, row, expected in zip(NAMES, example_raws(), published["story"], design()["tower"]):
        definition = library.get(name)
        assert definition.status == "promoted" and definition.evidence and definition.contract
        assert definition.kind == "object" and definition.layer == expected["layer"]
        assert definition.evidence.world_hash == library.world.world_hash()
        assert {"canon_total", "canon_idempotent", "canon_keeps_valid"} <= set(definition.evidence.checks)
        run = library.run(f"{name}.make", (raw,))
        example = row["examples"][0]
        assert example["text"] == expected["example"] and example["text"].isascii()
        assert export.display(name, run) == example["value"] == expected["value"]
        assert library.run("value", (run.outcome.value,)).outcome == Ok(example["value"])
        assert encode_outcome(run.outcome) == example["outcome"]
        assert run.steps == example["steps"]
        assert library.run(f"{name}.make", (decode(example["input"]),)).outcome == run.outcome


def test_all_showcases_replay_against_reference(library, published):
    tasks = design()["showcase"]
    assert reference.showcase_checks(tasks)[0] == [task["answer"] for task in tasks]
    for index, (task, record) in enumerate(zip(tasks, published["showcase"])):
        name = "SignCover" if index == 0 else "RootAtlas"
        raw = showcase_raw(task)
        run = library.run(f"{name}.make", (raw,))
        assert isinstance(run.outcome, Ok)
        assert record["prompt"] == task["prompt"] and record["prompt"].isascii()
        assert record["answer"] == task["answer"] == answer(run.outcome, task)
        assert record["answer_checked"] is True
        assert run.steps == record["steps"] and encode_outcome(run.outcome) == record["outcome"]
        assert library.run(f"{name}.make", (decode(record["input"]),)).outcome == run.outcome


def test_invalid_objects_and_forged_certificates_are_refused(library):
    for name, raw in (("Rat", hosts.raw("Rat", 1, 0)),
                      ("SparsePoly", hosts.polynomial(((-1, 1),))),
                      ("SparsePoly", hosts.polynomial(((257, 1),))),
                      ("Span", hosts.interval(1, 1)),
                      ("Span", hosts.raw("Span", 0.25, 1)),
                      ("SignTile", hosts.tile(hosts.polynomial(((1, 1),)), hosts.interval(-1, 1))),
                      ("BernsteinPatch", hosts.raw("BernsteinPatch", hosts.polynomial(((0, 1),)),
                                                   hosts.interval(0, 1), ("-1",))),
                      ("SignCover", hosts.cover(hosts.polynomial(((0, 1),)), hosts.interval(0, 1),
                                                (hosts.tile(hosts.polynomial(((0, 1),)),
                                                            hosts.interval(0, "1/3")),
                                                 hosts.tile(hosts.polynomial(((0, 1),)),
                                                            hosts.interval("1/2", 1))))),
                      ("RootBracket", hosts.bracket(hosts.polynomial(((2, 1),)), hosts.interval(-1, 1))),
                      ("RootAtlas", hosts.atlas(hosts.polynomial(((0, 1),)), hosts.interval(0, 1), ()))):
        assert isinstance(library.run(f"{name}.make", (raw,)).outcome, Bottom), name
    forged = showcase_raw(design()["showcase"][1])
    pieces = list(forged.fields[2])
    bracket = pieces[1]
    witness = list(bracket.fields[4])
    witness[0] = replace(witness[0], fields=(*witness[0].fields[:2], 1))
    pieces[1] = replace(bracket, fields=(*bracket.fields[:4], tuple(witness)))
    forged = replace(forged, fields=(*forged.fields[:2], tuple(pieces)))
    assert isinstance(library.run("RootAtlas.make", (forged,)).outcome, Bottom)
    incomplete = {**design()["showcase"][-1], "rational_root_candidates": ["1", "2"]}
    with pytest.raises(ValueError, match="incomplete"):
        answer(library.run("RootAtlas.make", (showcase_raw(incomplete),)).outcome, incomplete)


def test_work_is_charged_and_exhaustion_is_not_a_negative_certificate(library):
    small = hosts.polynomial(((0, 1),))
    large = hosts.polynomial(((0, 1), (36, 1)))
    small_steps = library.run("BernsteinPatch.make", (hosts.raw("BernsteinPatch", small,
                                                              hosts.interval(0, 1)),)).steps
    large_steps = library.run("BernsteinPatch.make", (hosts.raw("BernsteinPatch", large,
                                                              hosts.interval(0, 1)),)).steps
    assert large_steps > small_steps
    source = hosts.polynomial(((2, Fraction(1, 9) + Fraction(1, 2**100)),
                               (3, Fraction(-2, 3)), (4, 1)))
    narrow = hosts.bracket(source, hosts.interval(-1, 1), "0", 2)
    assert library.run("RootBracket.make", (narrow,)).outcome == Unknown("resource")
    assert library.run("RootBracket.make", (narrow,), fuel=1).outcome == Unknown("fuel")


def test_certificate_arithmetic_unfolds_to_counted_kernel_primitives(library):
    def atoms(frame):
        for child in frame.children:
            if child.given:
                yield child
            yield from atoms(child)

    run = library.run("Rat.make", (hosts.raw("Rat", 6, -8),), trace=True)
    assert run.outcome == Ok(library.run("Rat.make", (hosts.raw("Rat", -3, 4),)).outcome.value)
    rat_atoms = list(atoms(run.trace))
    assert {"lt", "neg", "gcd", "div_exact"} <= {child.name for child in rat_atoms}
    assert run.steps == sum(child.steps for child in rat_atoms) + run.jumps

    polynomial = hosts.polynomial(((0, 1), (2, 3)))
    patch = library.run("BernsteinPatch.make", (hosts.raw("BernsteinPatch", polynomial,
                                                               hosts.interval(0, 1)),), trace=True)
    expected = reference.patch(reference.poly(((0, 1), (2, 3))), reference.span(0, 1))
    assert patch.outcome.value.fields[0].fields[2] == tuple(map(reference.show, expected.values))
    patch_atoms = list(atoms(patch.trace))
    assert {"binom", "head", "tail", "is_empty"} <= {child.name for child in patch_atoms}
    assert patch.steps == sum(child.steps for child in patch_atoms) + patch.jumps


def test_object_bodies_only_use_generic_layer_zero_and_earlier_objects():
    operations = {operation.name for operation in decl().operations}
    assert not {"card_valid", "card_canon"} & operations
    tree = ast.parse((export.EXPORT_PATH.parents[4] / "src/opulse/worlds_v2/obj_only/hosts.py")
                     .read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "reference"
                   or isinstance(node, ast.Import) and any(alias.name.endswith("reference")
                                                           for alias in node.names) for node in ast.walk(tree))
    for index, definition in enumerate(definitions()):
        for body in (definition.spec.valid, definition.spec.canon):
            assert n.references(body) <= operations | {f"{name}.make" for name in NAMES[:index]}


def test_export_tags_and_fresh_build(published):
    assert published["tags"] == design()["tags"]
    assert published["open_kinds"] == design()["open_kinds"]
    assert export.build_export() == published
