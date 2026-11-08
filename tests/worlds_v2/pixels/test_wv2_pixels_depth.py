"""Independent depth-oracle and atoms-v2 invariants for the 32x32 pixel world."""

import json
import os
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError, atoms_digest, checked_scope, sampled
from opulse.atoms.observations import judge
from opulse.atoms.spec import Contract, Cost, Evidence
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.pixels import hosts, story
from opulse.worlds_v2.pixels.adapter import PixelsLibrary
from opulse.worlds_v2.pixels.export import build_export, trace_json
from opulse.worlds_v2.pixels.world import decl, new_library

# The full 3x3 audits take minutes; run them with OPULSE_RUN_SLOW=1.
RUN_SLOW = pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1",
                              reason="set OPULSE_RUN_SLOW=1 for the exhaustive pixel audits")


ROOT = Path(__file__).resolve().parents[3]
DESIGN = json.loads((ROOT / "worlds/catalogue/depth/pixels.json").read_text(encoding="utf-8"))
EXPORTED = json.loads((ROOT / "docs/assets/data/worlds_v2/pixels.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def library():
    loaded = new_library()
    for definition in story.definitions():
        loaded.write(definition)
        saved = EXPORTED["evidence_fixture"][definition.name]
        evidence = Evidence.from_dict(saved["evidence"])
        assert evidence.content_hash == loaded.content_hash(definition.name)
        assert evidence.atoms_hash == atoms_digest(loaded.atoms)
        checked = evidence.scope["checked"]
        assert {key: value for key, value in checked.items() if key != "by"} == checked_scope(
            story.verification_inputs()[definition.name])
        assert checked.get("by") == ("library" if definition.kind in ("object", "operation") else None)
        loaded._definitions[definition.name] = replace(
            loaded.get(definition.name), evidence=evidence, cost=Cost.from_dict(saved["cost"]),
            contract=Contract(f"{definition.name} agrees with the bounded reference"), status="promoted")
    assert all(loaded.get(definition.name).status == "promoted" for definition in story.definitions())
    return loaded


@pytest.mark.parametrize("rows", [("##", 3), ("#", "##"), ("#", "x"), ("#", ""),
                                        ("#",) * 33])
def test_forged_grid_rows_fail_without_host_exceptions(rows):
    forged = values.Card("grid", "rows", (hosts.list_of(*rows),))
    assert hosts.from_card(forged) == values.Bottom("invalid")
    assert hosts.cell(forged, hosts.point(0, 1)) == values.Bottom("invalid")
    assert hosts.light(forged, hosts.point(0, 1)) == values.Bottom("invalid")


def test_fixture_cannot_skip_fresh_verification(monkeypatch):
    def reject_verification(self, name, request):
        raise PipelineError("fresh verification required")

    monkeypatch.setattr(PixelsLibrary, "verify", reject_verification)
    with pytest.raises(PipelineError, match="fresh verification required"):
        story.build_library(EXPORTED["evidence_fixture"], limit=1)


@pytest.mark.parametrize("sort,base", [("Island", hosts.to_card(("#.#",))),
                                          ("Island", hosts.to_card(("...",))),
                                          ("Shape", values.Card("Island", "val", (hosts.to_card(("...", ".#.")),))),
                                          ("Shape", hosts.to_card(("#",)))])
def test_forged_invented_cards_fail_at_host_and_learner(library, sort, base):
    forged = values.Card(sort, "val", (base,))
    assert hosts.from_card(forged) == values.Bottom("invalid")
    assert hosts.identity(forged) == values.Bottom("invalid")
    assert library.run("identity", (forged,)).outcome == values.Bottom("invalid")
    assert library.run(f"{sort}.base", (forged,)).outcome == values.Bottom("invalid")


def test_first_three_cards_are_freshly_verified():
    fresh = story.build_library(limit=3)
    assert {name for name, definition in fresh.definitions.items()
            if definition.origin == "invented"} == {"islands", "Island", "flood"}
    assert all(fresh.get(name).status == "promoted" for name in ("islands", "Island", "flood"))
    for name in ("islands", "Island", "flood"):
        assert fresh.get(name).evidence.to_dict() == EXPORTED["evidence_fixture"][name]["evidence"]
        assert fresh.get(name).cost.to_dict() == EXPORTED["evidence_fixture"][name]["cost"]


@pytest.mark.slow
@RUN_SLOW
def test_full_three_by_three_promotion_evidence():
    verified = story.build_library()
    assert {name: {"evidence": definition.evidence.to_dict(), "cost": definition.cost.to_dict()}
            for name, definition in verified.definitions.items() if definition.origin == "invented"} == EXPORTED["evidence_fixture"]


@pytest.mark.slow
@RUN_SLOW
def test_all_three_by_three_object_constructors(library):
    reference = story.oracle()
    for (image,) in story.verification_inputs()["Island"]:
        rows = hosts.from_card(image)
        grid = reference.Grid(rows)
        actual = library.run("Island.make", (image,)).outcome
        if reference.islands(grid) != 1:
            assert actual == values.Bottom("invalid")
        else:
            assert actual == values.Ok(story.convert(reference.Island(grid)))
    for (island,) in story.verification_inputs()["Shape"]:
        actual = library.run("Shape.make", (island,)).outcome
        grid = reference.Grid(story.object_rows(island))
        assert actual == values.Ok(story.convert(reference.Shape.make(reference.Island(grid))))


def test_depth_reference_is_independent_and_validated():
    story.oracle().main()
    assert len(DESIGN["tower"]) == 12
    assert story.oracle().encode(story.oracle().scan_add(story.oracle().euler, story.oracle().A0, 3)) == DESIGN["tower"][-1]["value"]


def test_evidence_scope_is_three_by_three(library):
    sizes = {name: len(domain) for name, domain in story.verification_inputs().items()}
    assert sizes == {"islands": 512, "Island": 512, "flood": 2304, "grow": 218,
                     "map_components": 512, "holes": 512, "Shape": 218,
                     "turn": 151, "mirror": 151, "dihedral": 151,
                     "signature": 151, "euler": 512, "equivalent": 64, "scan_add": 100}
    for name, size in sizes.items():
        evidence = library.get(name).evidence
        assert evidence.scope["size"] == size
        checked = evidence.scope["checked"]
        assert {key: value for key, value in checked.items() if key != "by"} == checked_scope(
            story.verification_inputs()[name])
        assert checked.get("by") == ("library" if library.get(name).kind in ("object", "operation") else None)
        assert evidence.method in ("bounded", "exhaustive")
        if library.get(name).kind == "combinator":
            assert len(evidence.scope["op_family"]) >= 2
        if name == "Shape":
            assert {"canon_total", "canon_idempotent", "canon_keeps_valid"} <= set(evidence.checks)


def test_declaration_and_host_round_trip():
    path = ROOT / "worlds/decl/v2/pixels@1.json"
    declaration = json.loads(path.read_text(encoding="utf-8"))
    assert not validate(load(path))
    assert WorldDecl.from_dict(declaration).to_dict() == decl().to_dict()
    assert {key: value for key, value in decl().to_dict().items() if key != "open_kinds"} == declaration
    assert hosts.grid(hosts.list_of("..", ".#")) == hosts.to_card(("..", ".#"))
    assert hosts.from_card(hosts.to_card(("..", ".#"))) == ("..", ".#")
    assert hosts.light(hosts.to_card(("..", "..")), hosts.point(2, 0)) == values.Bottom("range")
    assert hosts.erase(hosts.to_card(("..", "..")), hosts.point(0, -1)) == values.Bottom("range")
    assert hosts.grid(hosts.list_of("..", ".")) == values.Bottom("grid")
    assert hosts.grid(hosts.list_of("." * 33)) == values.Bottom("range")
    large = hosts.to_card(("." * 32,) * 32)
    assert hosts.width(large) == hosts.height(large) == 32
    assert hosts.cell(hosts.light(large, hosts.point(31, 31)), hosts.point(31, 31)) == values.TRUE
    assert hosts.x_coord(values.Card("point", "xy")) == values.Bottom("invalid")
    assert hosts.cell(large, values.Card("point", "xy")) == values.Bottom("invalid")


def test_given_combinator_is_promoted_by_core():
    from opulse.worlds_v2.pixels.world import new_library

    library = new_library()
    given = library.get("then")
    assert given.origin == "given" and given.status == "promoted"
    assert library.scope().resolve("then").body == given.body
    assert library.world.combinators["library"][0] == library.world.combinators["given"][0]


def test_layers_include_literal_handles_without_padding_slots():
    definitions = {definition.name: definition for definition in story.definitions()}
    assert definitions["signature"].layer == 6
    assert "identity" in definitions["signature"].depends_on
    assert definitions["holes"].layer == 1
    assert "map_components" not in definitions["holes"].depends_on
    assert definitions["scan_add"].layer == 1
    assert "euler" not in definitions["scan_add"].depends_on


@pytest.mark.parametrize("index", range(10))
def test_design_example_exact_with_kernel_and_oracle(library, index):
    card = DESIGN["tower"][index]
    entry = EXPORTED["story"][index]
    assert card["layer"] == entry["layer"] and card["kind"] == entry["kind"]
    example = entry["examples"][0]
    expression = nodes.from_json(example["expression"])
    if "ascii" in example and entry["name"] not in ("Island", "grow", "Shape"):
        assert notation.parse_expr(example["text"]) == expression
    if entry["name"] in ("Island", "grow", "Shape", "map_components", "dihedral", "signature"):
        assert example["text"] == card["example"]
    result = kernel.evaluate(expression, scope=library.scope(), limits=kernel.Limits(fuel=4_000_000))
    assert isinstance(result.outcome, values.Ok)
    assert story.depth_encode(result.outcome.value) == card["value"]
    assert example["outcome"] == values.encode_outcome(result.outcome)
    assert example["steps"] == result.steps > 0
    assert entry["def_layer"] == library.get(entry["name"]).layer
    assert entry["status"] == "promoted"
    assert entry["evidence"]["scope"]["size"] > 0
    assert entry["evidence"]["method"] in ("bounded", "exhaustive")
    assert entry["contract"]["guarantees"]


@pytest.mark.slow
@RUN_SLOW
@pytest.mark.parametrize("index", (10, 11))
def test_large_design_examples_exact(library, index):
    example = EXPORTED["story"][index]["examples"][0]
    result = kernel.evaluate(nodes.from_json(example["expression"]), scope=library.scope(),
                             limits=kernel.Limits(fuel=4_000_000))
    assert values.encode_outcome(result.outcome) == example["outcome"]
    assert result.steps == example["steps"]
    assert story.depth_encode(result.outcome.value) == DESIGN["tower"][index]["value"]


@pytest.mark.parametrize("index", range(12))
def test_fresh_example_matches_independent_reference(index):
    entry = EXPORTED["story"][index]
    example = entry["examples"][-1]
    arguments = tuple(kernel.FnRef(item["v"]) if item["t"] == "fn" else values.decode(item)
                      for item in example["inputs"])
    if entry["kind"] == "combinator":
        expected = story.combinator_reference(entry["name"], {"f": arguments[0].name}, arguments[1:])
    else:
        expected = story.reference_result(entry["name"], *arguments)
    assert values.decode_outcome(example["outcome"]) == values.Ok(expected)


def test_failure_example_from_invented_flood(library):
    entry = EXPORTED["story"][2]
    failure = entry["examples"][1]
    expression = nodes.from_json(failure["expression"])
    result = kernel.evaluate(expression, scope=library.scope(), trace=True)
    assert result.outcome == values.Bottom("empty")
    assert failure["outcome"] == values.encode_outcome(result.outcome)
    assert failure["steps"] == result.steps
    assert failure["trace"] == trace_json(result.trace)
    assert library.run("Island.make", (hosts.to_card(("#.#",)),)).outcome == values.Bottom("invalid")
    assert library.run("flood", (hosts.to_card(("#",)), hosts.point(-1, 0))).outcome == values.Bottom("range")


def test_all_2x2_grids_and_small_exhaustive_crosscheck(library):
    reference = story.oracle()
    for mask in range(16):
        image = reference.grid(2, 2, {(index % 2, index // 2) for index in range(4) if mask & (1 << index)})
        card = hosts.to_card(image.rows)
        for name, answer in (("islands", reference.islands(image)), ("holes", reference.holes(image)),
                             ("euler", reference.euler(image))):
            run = library.run(name, (card,), trace=mask in (0, 5, 15))
            assert run.outcome == values.Ok(answer)
            if run.trace:
                assert unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0))).ok
        for y_coord in range(2):
            for x_coord in range(2):
                position = hosts.point(x_coord, y_coord)
                try:
                    expected = values.Ok(story.convert(reference.flood(image, (x_coord, y_coord))))
                except reference.Bottom as error:
                    expected = values.Bottom(str(error))
                assert library.run("flood", (card, position)).outcome == expected


def test_showcase_answers_are_kernel_checked(library):
    reference = story.oracle()
    a0, b0 = hosts.to_card(reference.A0.rows), hosts.to_card(reference.B0.rows)
    image = library.run("map_components", (kernel.FnRef("grow"), a0)).outcome.value
    cases = (("euler", (image,)), ("scan_add", (kernel.FnRef("euler"), a0, 3)),
             ("equivalent", (a0, b0)))
    for index, (card, (name, args)) in enumerate(zip(EXPORTED["showcase"], cases)):
        assert card["answer_checked"] is True
        outcome = (library.run(name, args, fuel=4_000_000).outcome if index == 0 else
                   values.decode_outcome(EXPORTED["story"][11 if index == 1 else 10]["examples"][0]["outcome"]))
        assert story.depth_encode(outcome.value) == card["answer"]


def test_i1_i2_i3_i4_and_promotion(library):
    image = hosts.to_card(("##.", ".#.", "..."))
    snapshot = values.encode(image)
    for name, args in (("islands", (image,)), ("holes", (image,)),
                       ("grow", (library.run("Island.make", (image,)).outcome.value,))):
        call = nodes.Call(name, tuple(nodes.Lit(item) for item in args))
        run = kernel.evaluate(call, scope=library.scope(), trace=True)
        inline = kernel.evaluate(kernel.inline(call, library.scope()), scope=library.scope())
        assert values.outcome_equal(run.outcome, inline.outcome) and run.steps == inline.steps
        assert unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0))).ok
    assert values.encode(image) == snapshot
    before = library.run("pixels", (image,)).outcome
    after = library.run("pixels", (image,)).outcome
    assert before == after == values.Ok(hosts.rows(image))
    other = hosts.to_card(("#..", ".#.", "..."))
    assert judge(library.world.observation["judge_view"], image, image)
    assert not judge(library.world.observation["judge_view"], image, other)
    missing = deepcopy(library)
    from dataclasses import replace
    missing._definitions["islands"] = replace(missing.get("islands"), status="callable", evidence=None, contract=None)
    with pytest.raises(PipelineError):
        missing.promote("islands", story.Contract("unsupported"))
    request = sampled(lambda randomizer: (image,), 2, 7, "2 sampled 3x3 grids")
    missing.verify("islands", replace(request, reference=lambda grid: 1))
    with pytest.raises(PipelineError, match="sampled"):
        missing.promote("islands", story.Contract("sampled"))
    changed = deepcopy(library)
    changed.world = replace(changed.world, params={**changed.world.params, "changed": 1})
    assert changed.get("islands").status == "callable" and changed.get("islands").evidence is None
    with pytest.raises(PipelineError, match="requires verified"):
        changed.promote("islands", story.Contract("stale"))


@pytest.mark.slow
@RUN_SLOW
def test_export_matches_builder():
    assert EXPORTED == build_export()


def test_public_grid_fixtures_are_runnable(library):
    for name, fixture in EXPORTED["fixtures"].items():
        assert name in ("A0", "A1", "B0")
        assert fixture["ascii"] == name
        expected = hosts.to_card(fixture["rows"])
        assert fixture["grid"] == story.depth_encode(expected)
        assert fixture["value"] == values.encode(expected)
        expression = nodes.from_json(fixture["expression"])
        assert kernel.evaluate(expression, scope=library.scope()).outcome == values.Ok(expected)


@pytest.mark.parametrize("image", [hosts.to_card(("...",)), hosts.to_card(("#.#",)),
                                        hosts.to_card(("#..", "...", "..#")),
                                        values.Card("grid", "rows", (hosts.list_of("broken"),))])
def test_island_constructor_rejects_invalid_grids(library, image):
    assert not isinstance(library.run("Island.make", (image,)).outcome, values.Ok)


@pytest.mark.parametrize("island", [values.Card("Island", "val", (hosts.to_card(("#.#",)),)),
                                         values.Card("Island", "val", (hosts.to_card(("...",)),)),
                                         values.Card("Island", "wrong", (hosts.to_card(("#",)),))])
def test_shape_constructor_rejects_forged_islands(library, island):
    assert not isinstance(library.run("Shape.make", (island,)).outcome, values.Ok)


def test_island_constructor_rejects_nested_forgery(library):
    forged = values.Card("Island", "val", (hosts.to_card(("#",)),))
    assert not isinstance(library.run("Island.make", (forged,)).outcome, values.Ok)


@settings(max_examples=18, deadline=None)
@given(st.integers(min_value=1, max_value=3), st.integers(min_value=1, max_value=3),
       st.integers(min_value=0, max_value=511))
def test_random_grid_unfold_and_boundary_invariance(library, width, height, mask):
    reference = story.oracle()
    image = reference.grid(width, height, {(index % width, index // width)
                                           for index in range(width * height) if mask & (1 << index)})
    card = hosts.to_card(image.rows)
    for name, expected in (("islands", reference.islands(image)),
                           ("holes", reference.holes(image)), ("euler", reference.euler(image))):
        call = nodes.Call(name, (nodes.Lit(card),))
        run = kernel.evaluate(call, scope=library.scope(), trace=True)
        inline = kernel.evaluate(kernel.inline(call, library.scope()), scope=library.scope())
        assert run.outcome == inline.outcome == values.Ok(expected)
        assert run.steps == inline.steps
        assert unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0))).ok


def test_export_uses_ascii_notation(library):
    assert EXPORTED["decl"] == decl().to_dict()
    assert len(EXPORTED["ladder"]) == 5 and len(EXPORTED["showcase"]) == 3
    assert len(EXPORTED["story"]) == 12 and EXPORTED["tower_source"] == "depth"
    assert sum("ascii" in example for entry in EXPORTED["story"] for example in entry["examples"]) == 18
    assert (ROOT / "docs/assets/data/worlds_v2/pixels.json").stat().st_size < 3_000_000
    for category in ("objects", "operations"):
        assert all(entry["title"].isascii() and entry["definition"].isascii()
                   for entry in EXPORTED["layer0"][category])
    for entry in EXPORTED["layer0"]["combinators"]["given"] + EXPORTED["layer0"]["observation"]["probes"]:
        assert entry["title"].isascii() and entry["definition"].isascii()
    for entry in EXPORTED["story"]:
        assert entry["design_text"] == DESIGN["tower"][entry["layer"] - 1]["decl"]
        definition = library.get(entry["name"])
        digest = export_util.body_sha256(definition.body)
        assert entry["body_sha256"] == digest
        assert ("ascii" in entry) == ("decl" in entry)
        if "ascii" in entry:
            assert entry["ascii"] == entry["decl"]
            assert notation.parse_definition(entry["decl"]).layer == entry["def_layer"]
            assert export_util.source_matches(entry["ascii"], digest)
        assert entry["title"].isascii() and entry["definition"].isascii()
        for example in entry["examples"]:
            assert example["text"].isascii()
            if "ascii" in example:
                assert example["ascii"] == example["text"]
                parsed = notation.parse_expr(example["text"])
                if parsed != nodes.from_json(example["expression"]):
                    assert entry["name"] in ("Island", "grow", "Shape")
            if entry["kind"] == "combinator":
                assert example["inputs"][0] == {"t": "fn", "v": example["inputs"][0]["v"]}
    forbidden = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\u211a\U0001d400-\U0001d7ff]")

    def strings(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                yield from strings(item, name)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item, key)
        elif isinstance(value, str) and not key.endswith("_zh"):
            yield value

    assert not [text for text in strings({key: value for key, value in EXPORTED.items()
                                        if key != 'notation3'}) if forbidden.search(text)]


def test_published_ascii_matches_stored_bodies(library):
    assert {row["name"] for row in EXPORTED["story"] if "ascii" not in row} == {
        "islands", "Island", "flood", "grow", "map_components", "holes", "Shape", "signature",
        "euler", "equivalent",
    }
    for row in EXPORTED["story"]:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert ("ascii" in row) == ("decl" in row)
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)
