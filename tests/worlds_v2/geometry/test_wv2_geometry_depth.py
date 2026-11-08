"""Independent depth oracle and core-pipeline regression checks."""

import importlib
import json
import os
import random
import re
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.export_util import body_sha256, source_matches
from opulse.worlds_v2.geometry import hosts
from opulse.worlds_v2.geometry.export import (
    build_export,
    constructor_text,
    fresh_examples,
    outcome_json,
    render,
)
from opulse.worlds_v2.geometry.story import (
    build_library,
    definitions,
    region_card,
    region_family,
    ring_card,
    small_region_family,
)
from opulse.worlds_v2.geometry.world import DECL_PATH, decl, new_library

ROOT = Path(__file__).resolve().parents[3]
DESIGN = json.loads((ROOT / "worlds/catalogue/depth/geometry.json").read_text(encoding="utf-8"))
EXPORTED = ROOT / "docs/assets/data/worlds_v2/geometry.json"


@pytest.fixture(scope="module")
def reference():
    return importlib.import_module("worlds.catalogue.depth.geometry")


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def exported():
    return json.loads(EXPORTED.read_text(encoding="utf-8"))


@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="fresh export takes over 60 s")
def test_fresh_export_matches_committed_file(exported):
    assert build_export() == exported


def test_design_standalone_oracle(reference):
    reference.verify()


def test_then_is_promoted_from_declaration():
    given = decl().combinators["library"][0]
    library = new_library()
    definition = library.get("then")
    assert definition.spec.to_dict() == given
    assert definition.origin == "given" and definition.status == "promoted"
    assert library.scope().defns["then"].body == definition.body


def test_first_three_cards_build_fresh():
    fresh = build_library(stop_after="translate")
    for name in ("Ring", "twice_area", "translate"):
        assert fresh.get(name).status == "promoted"
    sample = (hosts.point(0, 0), hosts.point(4, 0), hosts.point(0, 4))
    assert fresh.run("Ring.make", (sample,)).outcome == values.Ok(values.Card("Ring", "val", (sample,)))


@given(st.integers(min_value=1, max_value=7), st.integers(min_value=1, max_value=8))
@settings(max_examples=12, deadline=None)
def test_random_triangles_preserve_boundary_under_unfolding(library, reference, x_coord, y_coord):
    triangle = reference.Region(reference.Ring((x_coord, y_coord), (x_coord + 2, y_coord),
                                               (x_coord, y_coord + 2)))
    region = region_card(triangle)
    run = library.run("boundary_lattice", (region,), trace=True)
    assert run.outcome == values.Ok(reference.boundary_lattice(triangle))
    assert unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0), Boundary(depth=3))).ok


def test_canonical_region_template_family(library, exported, reference):
    family = library.get("Canon")
    assert family.status == "promoted" and family.evidence.scope["family"] == [
        {"T": "Region", "group": "_normalize"},
        {"T": "Region", "group": "_dihedral_normalize"},
    ]
    source = region_card(reference.Region(reference.Ring((4, 3), (6, 3), (4, 5))))
    for name in ("TranslationCanon", "DihedralCanon"):
        member = library.get(name)
        assert member.status == "promoted" and "Canon" in member.depends_on
        result = library.run(name + ".make", (source,), trace=True)
        assert isinstance(result.outcome, values.Ok)
        assert library.run(name + ".make", (result.outcome.value.fields[0],)).outcome == result.outcome
        assert unfold_equivalent(result.trace, (Boundary(), Boundary(depth=0))).ok
    assert [row["name"] for row in exported["templates"]] == ["Canon", "TranslationCanon", "DihedralCanon"]


def test_template_symmetry_groups_distinguish_rotation(library, reference):
    source = reference.Region(reference.Ring((4, 3), (7, 3), (4, 5)))
    rotated = reference.isometry(lambda point: reference.move(reference.turn(point, 1), -24, 0), source)
    first = region_card(source)
    second = region_card(rotated)
    translated_first = library.run("TranslationCanon.make", (first,)).outcome
    translated_second = library.run("TranslationCanon.make", (second,)).outcome
    dihedral_first = library.run("DihedralCanon.make", (first,)).outcome
    dihedral_second = library.run("DihedralCanon.make", (second,)).outcome
    assert isinstance(translated_first, values.Ok) and isinstance(translated_second, values.Ok)
    assert isinstance(dihedral_first, values.Ok) and isinstance(dihedral_second, values.Ok)
    assert translated_first != translated_second
    assert dihedral_first == dihedral_second
    outer, holes = reference.signature(source)
    canonical = region_card(reference.Region(reference.Ring(*outer),
                                             tuple(reference.Ring(*hole) for hole in holes)))
    assert dihedral_first.value.fields[0] == canonical


def test_canonical_objects_reject_forged_and_invalid_regions(library):
    valid = region_card(small_region_family()[0])
    forged = values.Card("Region", "val", (values.Card("RegionPair", "shape", (valid, ())),))
    bad = (forged, values.Card("Region", "val", ()), values.Card("Ring", "val", ()),
           values.Card("Region", "val", (values.Card("RegionPair", "shape", (valid, (valid,))),)))
    for name in ("TranslationCanon", "DihedralCanon"):
        for candidate in bad:
            assert isinstance(library.run(name + ".make", (candidate,)).outcome, values.Bottom)


def test_region_pair_rejects_wrong_field_sorts(library):
    ring = ring_card(small_region_family()[0].outer)
    cases = ((hosts.point(0, 0), ()), (ring, ring), (ring, (ring, hosts.point(1, 1))),
             (ring, (ring,) * 5))
    for fields in cases:
        assert isinstance(library.run("RegionPair.shape", fields).outcome, values.Bottom)


def test_region_and_signature_reject_multiple_invalid_inputs(library):
    ring = ring_card(small_region_family()[0].outer)
    reversed_ring = values.Card("Ring", "val", (tuple(reversed(ring.fields[0])),))
    for pair in (values.Card("RegionPair", "shape", (reversed_ring, ())),
                 values.Card("RegionPair", "shape", (ring, (ring,))),
                 values.Card("RegionPair", "shape", (ring, (ring,) * 5))):
        assert isinstance(library.run("Region.make", (pair,)).outcome, values.Bottom)
    for candidate in (ring, values.Card("Region", "other", ()), values.Card("Region", "val", ())):
        assert isinstance(library.run("Signature.make", (candidate,)).outcome, values.Bottom)


def test_constructor_example_text_replays_recorded_inputs(library, exported):
    def decode_input(item):
        if item["t"] == "List" and item["tag"] == "items":
            return tuple(decode_input(child) for child in item["f"])
        if "tag" in item:
            return values.Card(item["t"], item["tag"], tuple(decode_input(child) for child in item["f"]))
        return values.decode(item)

    for position, name in ((0, "Ring.make"), (4, "Region.make"), (9, "Signature.make")):
        for example in exported["story"][position]["examples"]:
            argument = decode_input(example["inputs"][0])
            assert example["text"] == constructor_text(name, argument)
            assert "ascii" not in example
            run = library.run(name, (argument,))
            assert outcome_json(run.outcome) == example["outcome"]
            assert run.steps == example["steps"]


def test_template_constructor_text_replays(library, exported, reference):
    scalene = region_card(reference.Region(reference.Ring((4, 3), (7, 3), (4, 5))))
    for row in exported["templates"][1:]:
        example = row["examples"][0]
        name = row["name"] + ".make"
        assert example["text"] == constructor_text(name, scalene)
        assert "ascii" not in example
        run = library.run(name, (scalene,))
        assert run.steps == example["steps"]
        assert outcome_json(run.outcome) == example["outcome"]


def test_isometry_example_is_inside_verified_family(library, reference):
    evidence = library.get("isometry").evidence.scope
    assert "flip_q1_shift" in evidence["op_family"]
    assert "two displayed holed regions" in evidence["domain"]
    assert library.run("isometry", (kernel.FnRef("flip_q1_shift"),
                                    region_card(reference.fixtures()[1]))).outcome == values.Ok(
        region_card(reference.fixtures()[2]))


def test_translate_examples_are_in_verified_family(library):
    evidence = library.get("translate").evidence.scope
    assert "two displayed triangles" in evidence["domain"]
    assert evidence["op_family"] == ["shift_x", "shift_y"]


def test_forged_geometry_cards_fail_without_raising(library, reference):
    valid_ring = ring_card(reference.fixtures()[0])
    valid_region = region_card(reference.fixtures()[1])
    bad_ring = values.Card("Ring", "val", ((hosts.point(0, 0), hosts.point(1, 1), hosts.point(2, 2)),))
    bad_region = values.Card("Region", "val", (values.Card("RegionPair", "shape", (bad_ring, ())),))
    bad_signature = values.Card("Signature", "val", (bad_region,))
    candidates = (
        ("twice_area", (bad_ring,)),
        ("Ring.base", (bad_ring,)),
        ("RegionPair.shape", (bad_ring, ())),
        ("Region.make", (bad_region.fields[0],)),
        ("boundary_lattice", (bad_region,)),
        ("Signature.base", (bad_signature,)),
        ("congruent", (bad_region, valid_region)),
        ("twice_area", (values.Card("Ring", "val", (tuple(reversed(valid_ring.fields[0])),)),)),
        ("inside", ((valid_region, values.Card("Point", "xy", (33, 1))),)),
        ("twice_area", (values.Card("FictionalRing", "val", (valid_ring.fields[0],)),)),
    )
    for name, args in candidates:
        assert library.run(name, args).outcome == values.Bottom("invalid")
    assert hosts.points(bad_ring) == values.Bottom("size")


def test_twelve_cards_match_the_independent_oracle(reference, library, exported):
    first, region, reflected, _, shifted = reference.fixtures()
    cases = (first, reference.twice_area(first),
             reference.translate(lambda point: reference.move(point, 1, 0),
                                 lambda point: reference.move(point, 0, 1), first),
             reference.orientation(first), region, reference.boundary_lattice(region),
             reference.interior_lattice(region), reflected,
             reference.inside(region, (8, 6)),
             reference.signature(reference.Region(reference.Ring((2, 2), (6, 2), (6, 6), (2, 6)))),
             reference.congruent(region, reflected), reference.overlap_lattice(region, shifted))
    assert len(exported["story"]) == 12
    for card, oracle, expected in zip(exported["story"], cases, DESIGN["tower"]):
        assert card["layer"] == expected["layer"]
        assert card["kind"] == expected["kind"]
        assert reference.render(oracle) == expected["value"]
        assert card["examples"][0]["outcome"]["ok"]
        assert card["status"] == "promoted"
        assert card["evidence"]["scope"]["size"] >= 50
        assert card["def_layer"] == library.get(card["name"]).layer
    example = exported["story"][7]["examples"][0]
    assert example["inputs"][0] == {"t": "fn", "v": "flip_q1_shift"}


def test_ring_boundaries_and_failure(library, exported, reference):
    invalid = (hosts.point(0, 0), hosts.point(2, 2), hosts.point(0, 2), hosts.point(2, 0))
    result = library.run("Ring.make", (invalid,), trace=True)
    assert isinstance(result.outcome, values.Bottom)
    assert exported["story"][0]["examples"][1]["outcome"] == {"bottom": "invalid"}
    assert isinstance(library.run("Ring.make", (invalid,), fuel=0).outcome, values.Unknown)
    valid = ring_card(reference.fixtures()[0])
    for name, args in (("twice_area", (valid,)),
                       ("translate", (kernel.FnRef("shift_x"), kernel.FnRef("shift_y"), valid))):
        run = library.run(name, args, trace=True)
        assert unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0), Boundary(depth=2))).ok


def test_fresh_dependent_examples_match_oracle(reference, library, exported):
    regions = region_family()
    triangles = small_region_family()
    assert isinstance(regions[0], reference.Region)
    assert isinstance(triangles[5], reference.Region)
    ring = reference.Ring((2, 2), (6, 2), (2, 6))
    expected = (reference.twice_area(reference.Ring((1, 1), (5, 1), (1, 5))),
                reference.translate(lambda point: reference.move(point, 0, 1),
                                    lambda point: reference.move(point, 1, 0), ring),
                reference.orientation(reference.Ring((2, 2), (2, 6), (6, 2))),
                regions[0], reference.boundary_lattice(regions[1]),
                reference.interior_lattice(regions[2]),
                reference.isometry(lambda point: reference.move(point, 1, 0), regions[3]),
                reference.inside(regions[4], (4, 5)), reference.signature(triangles[5]),
                reference.congruent(regions[6], regions[7]),
                reference.overlap_lattice(regions[8], regions[9]))
    for card, oracle, (name, args, text) in zip(exported["story"][1:], expected, fresh_examples(library)):
        assert card["examples"][1]["text"] == text
        assert card["examples"][0]["inputs"] != card["examples"][1]["inputs"]
        result = library.run(name, args).outcome
        assert isinstance(result, values.Ok)
        assert render(result.value) == reference.render(oracle)
        assert card["examples"][1]["steps"] > 0


def test_point_truth_and_core_costs(reference, library):
    assert hosts.point(-1, 4) == values.Bottom("range")
    assert hosts.point(33, 4) == values.Bottom("range")
    assert hosts.segments_meet(hosts.point(0, 0), hosts.point(2, 2),
                               hosts.point(0, 2), hosts.point(2, 0)) is True
    region = region_card(reference.fixtures()[1])
    for coordinate in ((5, 5), (6, 6), (8, 6)):
        result = library.run("inside", ((region, hosts.point(*coordinate)),))
        assert result.outcome == values.Ok(reference.inside(reference.fixtures()[1], coordinate))
    assert library.run("boundary_lattice", (region,)).outcome == values.Ok(88)
    assert library.run("interior_lattice", (region,)).outcome == values.Ok(155)


def test_strict_interior_on_the_complete_public_lattice(reference, library):
    reference_region = reference.fixtures()[1]
    region = region_card(reference_region)
    for x_coord in range(33):
        for y_coord in range(33):
            observed = library.run("inside", ((region, hosts.point(x_coord, y_coord)),)).outcome
            assert observed == values.Ok(reference.inside(reference_region, (x_coord, y_coord)))


def test_maximum_ring_and_four_disjoint_holes(reference, library):
    boundary = (tuple((1 + 3 * index, 1) for index in range(7)) +
                tuple((19, 1 + 3 * index) for index in range(1, 7)) +
                tuple((19 - 3 * index, 19) for index in range(1, 7)) +
                tuple((1, 19 - 3 * index) for index in range(1, 6)))
    assert len(boundary) == 24
    outer = reference.Ring(*boundary)
    holes = tuple(reference.Ring((x_coord, y_coord), (x_coord, y_coord + 2),
                                 (x_coord + 2, y_coord + 2), (x_coord + 2, y_coord))
                  for x_coord, y_coord in ((4, 4), (10, 4), (4, 10), (10, 10)))
    source = reference.Region(outer, holes)
    card = region_card(source)
    assert library.run("Ring.make", (ring_card(outer).fields[0],)).outcome == values.Ok(ring_card(outer))
    assert library.run("Region.make", (card.fields[0],)).outcome == values.Ok(card)
    assert library.run("boundary_lattice", (card,)).outcome == values.Ok(reference.boundary_lattice(source))
    assert library.run("interior_lattice", (card,)).outcome == values.Ok(reference.interior_lattice(source))
    assert hosts.from_card(hosts.to_card(ring_card(outer).fields[0])) == ring_card(outer).fields[0]
    assert hosts.from_card(hosts.to_card(hosts.point(3, 7))) == hosts.point(3, 7)
    assert library.run("path", (ring_card(outer).fields[0],)).outcome == values.Ok(ring_card(outer).fields[0])
    assert library.run("path", (ring_card(outer).fields[0] + (hosts.point(3, 7),),)).outcome == values.Bottom("size")


def test_given_segments_match_exact_oracle(reference):
    randomizer = random.Random(41)
    for _ in range(1200):
        raw = tuple((randomizer.randrange(33), randomizer.randrange(33)) for _ in range(4))
        assert hosts.segments_meet(*(hosts.point(*item) for item in raw)) == reference.segments_meet(*raw)


def test_ring_validity_matches_oracle_on_random_paths(reference):
    randomizer = random.Random(58)
    fresh = new_library()
    fresh.write(definitions()[0])
    fresh.check("Ring")
    sample = (hosts.point(0, 0), hosts.point(4, 0), hosts.point(0, 4))
    fresh.make_callable("Ring", ((sample,),))
    for _ in range(200):
        raw = tuple((randomizer.randrange(9), randomizer.randrange(9))
                    for _ in range(randomizer.randrange(3, 7)))
        result = fresh.run("Ring.make", (tuple(hosts.point(*item) for item in raw),)).outcome
        try:
            oracle = reference.Ring(*raw)
        except reference.Bottom:
            assert isinstance(result, values.Bottom), raw
        else:
            assert result == values.Ok(ring_card(oracle)), raw


def test_declaration_pipeline_and_export(library, exported):
    assert WorldDecl.from_dict(decl().to_dict()).to_dict() == decl().to_dict()
    assert all(card["origin"] == "given" for card in (definition.to_dict() for definition in library.definitions.values())
               if card["name"] in {"cross", "move", "turn", "flip", "segments_meet"})
    for definition in library.definitions.values():
        if definition.origin == "invented":
            assert definition.status == "promoted"
            assert definition.evidence.method == "bounded"
            assert definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
            assert re.fullmatch(r"[0-9a-f]{64}", definition.evidence.scope["checked"]["sha256"])
            assert definition.contract is not None
            assert not any(isinstance(node, dict) and "host" in node for node in nodes.walk(definition.body)
                           if definition.body)
    assert exported["tower_source"] == "depth"
    assert exported["decl"] == json.loads(DECL_PATH.read_text(encoding="utf-8"))
    assert json.loads(EXPORTED.read_text(encoding="utf-8")) == exported
    assert EXPORTED.stat().st_size < 3_000_000
    assert all(ord(letter) < 128 for item in exported["story"]
               for letter in (item.get("decl", "") + item["symbol"] + item["examples"][0]["text"]))


def test_stale_world_resets_evidence_and_showcase_checks(library, exported):
    fresh = new_library()
    fresh._definitions["Ring"] = library.get("Ring")
    assert fresh.get("Ring").status == "promoted"
    fresh.world = replace(fresh.world, params={**fresh.world.params, "max_coord": 31})
    assert fresh.get("Ring").status == "callable"
    assert all(task["answer_checked"] for task in exported["showcase"])


def test_ascii_strings_and_five_level_ladder(exported):
    forbidden = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986♠♦○◉ℚ𝔹]")
    def strings(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                yield from strings(item, name)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item, key)
        elif isinstance(value, str) and not key.endswith("_zh"):
            yield value
    plain_strings = tuple(strings({key: value for key, value in exported.items()
                                   if key != 'notation3'}))
    assert not any(forbidden.search(text) or not text.isascii() for text in plain_strings)
    assert [item["level"] for item in exported["ladder"]] == [1, 2, 3, 4, 5]
    assert len(exported["showcase"]) == 3


def test_story_declarations_and_examples_use_core_notation(library, exported):
    for row in (*exported["story"], *exported["templates"]):
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            definition = notation.parse_definition(row["ascii"])
            assert definition.name == row["name"]
            assert definition.layer == row["def_layer"]
            assert row["decl"].endswith(f" L{row['def_layer']}")
            assert row["ascii"] == row["decl"]
            assert source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row
        assert row["design_text"] == row["design_decl"]
        for example in row["examples"]:
            if "ascii" in example:
                assert example["ascii"] == example["text"]
                notation.parse_expr(example["text"])
            else:
                with pytest.raises(notation.NotationError):
                    notation.parse_expr(example["text"])


def test_parseable_example_literals_match_evaluated_inputs(exported):
    def decode_input(item):
        if item["t"] == "List" and item.get("tag") == "items":
            return tuple(decode_input(child) for child in item["f"])
        if "tag" in item:
            return values.Card(item["t"], item["tag"], tuple(decode_input(child) for child in item["f"]))
        return values.decode(item)

    for row in exported["story"]:
        for example in row["examples"]:
            if "ascii" not in example:
                continue
            expression = notation.parse_expr(example["text"])
            assert expression == nodes.Call(row["name"], tuple(
                nodes.Lit(decode_input(item)) for item in example["inputs"]
            ))
