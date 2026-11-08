"""Independent depth oracle, pipeline, sealing, and published fixture checks."""

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.library import PipelineError
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.shadows import deep_hosts as hosts
from opulse.worlds_v2.shadows.deep_export import (
    JUDGE_OUTPUT,
    OUTPUT,
    fresh_examples,
    render,
    run_expression,
)
from opulse.worlds_v2.shadows.deep_export import (
    examples as primary_examples,
)
from opulse.worlds_v2.shadows.deep_export import (
    expression as call_expression,
)
from opulse.worlds_v2.shadows.export import build_export
from opulse.worlds_v2.shadows.story import build_library, public_mask, request, source
from opulse.worlds_v2.shadows.world import DECL_PATH, decl

ROOT = Path(__file__).resolve().parents[3]
DESIGN = json.loads((ROOT / "worlds/catalogue/depth/shadows.json").read_text(encoding="utf-8"))
REFERENCE = ROOT / "worlds/catalogue/depth/shadows.py"


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def reference():
    spec = importlib.util.spec_from_file_location("shadows_depth_reference", REFERENCE)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_declaration_and_layer_zero(library):
    assert not validate(load(DECL_PATH))
    assert WorldDecl.from_dict(decl().to_dict()).to_dict() == decl().to_dict()
    assert decl().params == {"width": 8, "height": 8, "depth": 6, "candidate_limit": 200000}
    assert values.decode(decl().constants["M"]) == public_mask()
    assert "S" not in decl().constants
    assert not any(name.startswith("T") for name in decl().constants)
    assert {"enumerate_raw", "best_raw", "plan_raw"}.isdisjoint(op.name for op in decl().operations)
    assert hosts.to_card(hosts.from_card(source())) == source()
    assert hosts.put(hosts.volume(), 8, 0, 0) == Bottom("range")
    assert hosts.erase(hosts.volume(), 0, 0, 6) == Bottom("range")
    assert hosts.mask(*(hosts.cell(x, 0, z) for x in range(8) for z in range(6))) == Bottom("mask_limit")
    assert hosts.top(source()).sort == "Set" and hosts.side(source()).sort == "Set"
    from opulse.worlds_v2.shadows.world import new_library
    pipeline = new_library()
    assert pipeline.run("pipe", (kernel.FnRef("top"), kernel.FnRef("size"), source())).outcome == Ok(8)
    large_mask = hosts.mask(*(hosts.cell(x, row, z) for row in range(2)
                              for x in range(1, 5) for z in range(1, 5)))
    large_solid = hosts.volume(*(hosts.cell(x, row, x) for row in range(2)
                                 for x in range(1, 5)))
    large_views = Card("Views", "val", (hosts.views_record(
        hosts.top(large_solid), hosts.side(large_solid), 8),))
    assert library.run("enumerate_raw", (large_mask, large_views)).outcome == Bottom("candidate_limit")


def test_first_three_cards_build_fresh():
    fresh = build_library(upto=3)
    assert [fresh.get(name).status for name in ("ink", "Views", "capture")] == ["promoted"] * 3
    assert fresh.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), source())).outcome == Ok(
        Card("Views", "val", (hosts.views_record(hosts.top(source()), hosts.side(source()), 8),)))


def test_views_normalization_and_invalid_area(library):
    shadow = Card("Set", "items", (hosts.pair(2, 0), hosts.pair(1, 0)))
    empty = Card("Set", "items")
    result = library.run("Views.make", (hosts.views_record(shadow, empty, 2),))
    assert isinstance(result.outcome, Ok)
    assert result.outcome.value.fields[0].fields[0].fields == (hosts.pair(1, 0), hosts.pair(2, 0))
    assert library.run("Views.make", (hosts.views_record(shadow, empty, 1),)).outcome == Bottom("invalid")
    duplicates = Card("Set", "items", (hosts.pair(1, 0), hosts.pair(1, 0)))
    assert library.run("Views.make", (hosts.views_record(duplicates, empty, 2),)).outcome == Bottom("invalid")
    assert library.run("Views.make", (Card("ViewsRaw", "record", (empty, empty, True)),)).outcome == Bottom("invalid")
    assert library.run("Views.make", (Card("ViewsRaw", "record", (empty, empty, 0, 1)),)).outcome == Bottom("invalid")
    forged = Card("Views", "val", (Card("ViewsRaw", "record", (duplicates, empty, 2)),))
    assert library.run("Views.make", (forged.fields[0],)).outcome == Bottom("invalid")


def test_candidates_constructor_rejects_invalid_records(library):
    mask = hosts.mask(*public_mask().fields[:4])
    secret = hosts.volume(mask.fields[0])
    views = library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), secret)).outcome.value
    valid = hosts.enumerate_raw(mask, views)
    volume = hosts.pool_volumes(valid).fields[0]
    duplicate = Card("CandidatesRaw", "pool", (mask, views, Card("List", "items", (volume, volume))))
    outside = Card("CandidatesRaw", "pool", (mask, views, Card("List", "items", (source(),))))
    wrong_view = Card("CandidatesRaw", "pool", (mask, views, Card("List", "items", (hosts.volume(),))))
    forged_views = Card("Views", "val", (hosts.views_record(hosts.top(secret), hosts.side(secret), 0),))
    forged_view_pool = Card("CandidatesRaw", "pool", (mask, forged_views, Card("List", "items")))
    wrong_later = Card("CandidatesRaw", "pool", (mask, views, Card("List", "items", (
        volume, hosts.volume(mask.fields[-1])))))
    malformed = Card("CandidatesRaw", "pool", (mask, views, Card("List", "items"), 1))
    for record in (duplicate, outside, wrong_view, forged_view_pool, wrong_later, malformed):
        assert library.run("Candidates.make", (record,)).outcome == Bottom("invalid")
        forged = Card("Candidates", "val", (record,))
        assert library.run("Candidates.make", (forged.fields[0],)).outcome == Bottom("invalid")


def test_forged_invented_cards_cannot_enter_hosts_or_learner(library):
    secret = hosts.volume(hosts.cell(1, 0, 1))
    valid_views = Card("Views", "val", (hosts.views_record(hosts.top(secret), hosts.side(secret), 1),))
    invalid_views = (
        Card("Views", "val", (hosts.views_record(hosts.top(secret), hosts.side(secret), 0),)),
        Card("Views", "val", (hosts.views_record(Card("Set", "items", (hosts.pair(8, 0),)),
                                                  hosts.side(secret), 1),)),
        Card("Views", "val", ()),
    )
    for forged in invalid_views:
        assert hosts.unwrap_views(forged) == Bottom("invalid")
        assert library.run("matches", (secret, forged)).outcome == Bottom("invalid")
        assert library.run("size", (forged,)).outcome == Bottom("invalid")
    mask = hosts.mask(hosts.cell(1, 0, 1), hosts.cell(1, 0, 2))
    valid = Card("Candidates", "val", (hosts.enumerate_raw(mask, valid_views),))
    raw = valid.fields[0]
    forged_records = (
        Card("CandidatesRaw", "pool", (mask, invalid_views[0], raw.fields[2])),
        Card("CandidatesRaw", "pool", (mask, valid_views, Card("List", "items", (source(),)))),
        Card("CandidatesRaw", "pool", (mask, valid_views, Card("List", "items", (secret, secret)))),
        Card("CandidatesRaw", "pool", (mask, valid_views)),
    )
    for record in forged_records:
        forged = Card("Candidates", "val", (record,))
        assert hosts.pool_raw(forged) == Bottom("invalid")
        assert hosts.forced_cells(forged) == Bottom("invalid")
        assert library.run("forced", (forged,)).outcome == Bottom("invalid")
    assert library.run("forced", (valid,)).outcome == Ok(Card("Set", "items", (hosts.cell(1, 0, 1),)))


def test_observation_rejects_truth_read_outside_probes():
    library = build_library(upto=1)
    body = nodes.Call("size", (nodes.Call("volume_cells", (nodes.Var("v"),)),))
    original = library.get("ink")
    library._definitions["ink"] = replace(original, status="callable", body=body,
                                           spec=replace(original.spec, body=body),
                                           depends_on=("volume_cells", "size"))
    first = hosts.volume(hosts.cell(1, 0, 1), hosts.cell(2, 0, 2))
    second = hosts.volume(hosts.cell(1, 0, 1), hosts.cell(2, 0, 2), hosts.cell(1, 0, 2))
    assert hosts.top(first) == hosts.top(second) and hosts.side(first) == hosts.side(second)
    evidence = request("bounded", ((first,), (second,)), "two equally projected states",
                       lambda volume: len(hosts._cells(volume)))
    with pytest.raises(PipelineError, match="subject v may only be passed to probes"):
        library.verify("ink", evidence)


def test_export_rejects_invert_showcase_mismatch():
    from opulse.worlds_v2.shadows.deep_export import seal_showcases

    tasks = [{"angle": "Invert", "answer": "unsealed", "answer_checked": False}]
    with pytest.raises(ValueError, match="showcase answer differs"):
        seal_showcases(tasks)
    assert tasks[0]["answer"] == "unsealed" and not tasks[0]["answer_checked"]
    tasks[0]["answer_checked"] = True
    seal_showcases(tasks)
    assert tasks[0]["answer"] == "sealed" and tasks[0]["answer_checked"]


@given(st.integers(min_value=0, max_value=15))
@settings(max_examples=12, deadline=None)
def test_random_small_unfold_and_projection_boundary(library, bits):
    cells = public_mask().fields[:4]
    secret = hosts.volume(*(item for index, item in enumerate(cells) if bits & (1 << index)))
    views = library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), secret))
    assert isinstance(views.outcome, Ok)
    scope = library.scope()
    unfolded = kernel.evaluate(kernel.inline(nodes.Call("capture", (
        nodes.Lit(kernel.FnRef("top")), nodes.Lit(kernel.FnRef("side")), nodes.Lit(secret))), scope), scope=scope)
    assert outcome_equal(views.outcome, unfolded.outcome)
    assert views.steps == unfolded.steps
    original_agent = library.agent
    library.agent = "learner"
    try:
        assert library.run("front", (secret,)).outcome == Bottom("permission")
    finally:
        library.agent = original_agent


def test_depth_reference_all_cards(library, reference):
    reference_mask, reference_secret = reference.sample()
    assert {item.fields for item in hosts._cells(source())} == reference_secret.cells
    assert {item.fields for item in public_mask().fields} == reference_mask.cells
    mask, secret = public_mask(), source()
    reference_views = reference.capture(reference_secret)
    views = library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), secret)).outcome.value
    pool = library.run("candidates", (mask, views)).outcome.value
    reference_pool = reference.candidates(reference_mask, reference_views)
    assert len(reference_pool.volumes) == 2401
    assert {tuple(part.fields for part in hosts._cells(volume))
            for volume in hosts.pool_volumes(hosts.pool_raw(pool)).fields} == {tuple(sorted(volume.cells)) for volume in reference_pool.volumes}
    expected = (reference.ink(reference_secret), reference_views, reference_views, True,
                reference_pool, reference_pool, reference.forced(reference_pool),
                reference.least(reference_pool), reference.ambiguity(reference_pool),
                reference.ambiguity(reference.add_view("diag", reference_pool, reference.diag(reference_secret),
                                                       ("diag",))),
                reference.best_probe(reference_pool), reference.plan(reference_pool))
    results = (library.run("ink", (secret,)).outcome,
               library.run("Views.make", (hosts.views_record(hosts.top(secret), hosts.side(secret), 8),)).outcome,
               library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), secret)).outcome,
               library.run("matches", (secret, views)).outcome,
               Ok(pool),
               library.run("retain", (kernel.FnRef("top"), pool, hosts.top(secret))).outcome,
               library.run("forced", (pool,)).outcome, library.run("least", (pool,)).outcome,
               library.run("ambiguity", (pool,)).outcome,
               library.run("ambiguity", (library.run("add_view",
                   (kernel.FnRef("diag"), pool, hosts.diag(secret))).outcome.value,)).outcome,
               library.run("best_probe", (pool,)).outcome,
               library.run("plan", (kernel.FnRef("front"), kernel.FnRef("diag"),
                                    kernel.FnRef("anti"), pool)).outcome)
    for layer, (result, oracle, card) in enumerate(zip(results, expected, DESIGN["tower"]), 1):
        assert isinstance(result, Ok), layer
        if layer in (5, 6):
            assert len(hosts.pool_volumes(hosts.pool_raw(result.value)).fields) == len(oracle.volumes)
        elif layer == 7:
            assert {item.fields for item in result.value.fields} == oracle
        elif layer == 8:
            assert tuple(result.value.fields) == (oracle.mass, oracle.count)
        elif layer == 11:
            assert tuple(result.value.fields) == (oracle.probe, oracle.worst, oracle.groups)
        elif layer == 12:
            assert tuple(result.value.fields) == (oracle.depth, oracle.first, oracle.worst_after_first)
        elif layer in (2, 3):
            assert render(result.value) == card["value"]
        else:
            assert render(result.value) == card["value"], layer
    assert len(library.derived_world().promoted) == 14


def test_pipeline_evidence_and_failure(library):
    cards = ["ink", "Views", "capture", "matches", "Candidates", "retain", "forced",
             "least", "ambiguity", "add_view", "best_probe", "plan"]
    for item in cards:
        definition = library.get(item)
        assert definition.kind == DESIGN["tower"][cards.index(item)]["kind"]
        assert definition.status == "promoted" and definition.contract and definition.evidence
        assert definition.evidence.scope["size"] >= 50
        assert definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
        assert len(definition.evidence.scope["checked"]["sha256"]) == 64
        assert definition.evidence.method in ("bounded", "exhaustive")
    assert library.get("enumerate_raw").status == "promoted"
    assert library.get("plan").spec.op_params == ("front_probe", "diag_probe", "anti_probe")
    secret = source()
    views = library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), secret)).outcome.value
    pool = library.run("candidates", (public_mask(), views)).outcome.value
    empty = Card("Candidates", "val", (hosts.retain_raw(pool, "front",
              Card("Set", "items", (hosts.pair(7, 7),))),))
    assert library.run("least", (empty,)).outcome == Bottom("empty_candidates")
    library.agent = "extra"
    assert library.run("plan", (kernel.FnRef("front"), kernel.FnRef("diag"),
                                kernel.FnRef("anti"), empty)).outcome == Bottom("empty_candidates")
    library.agent = "learner"
    assert library.run("diag", (secret,)).outcome == Bottom("permission")
    assert library.run("add_view", (kernel.FnRef("diag"), pool, hosts.diag(secret))).outcome == Bottom("permission")


def test_example_calls_respect_learner_probe_capabilities(library):
    previous = library.agent
    try:
        library.agent = "learner"
        denied, steps, _ = run_expression(library, call_expression("front", source()))
        assert denied == Bottom("permission") and steps == 0
        library.agent = "learner_all"
        granted, steps, _ = run_expression(library, call_expression("front", source()))
        assert granted == hosts.front(source()) and steps == 1
    finally:
        library.agent = previous


def test_canonical_plan_fast_path_is_scoped_and_exact(library):
    previous = library.agent
    library.agent = "learner_all"
    try:
        views = library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), source())).outcome.value
        pool = library.run("candidates", (public_mask(), views)).outcome.value
        slots = tuple(kernel.FnRef(name) for name in ("front", "diag", "anti"))
        path = library.scope().fast_paths["plan"]
        assert path.scope_predicate(*slots, pool)
        assert not path.scope_predicate(*slots, Card("Candidates", "val", (hosts.enumerate_raw(
            hosts.mask(*public_mask().fields[:4]), views),)))
        actual = library.run("plan", (*slots, pool), trace=True)
        assert any(child.fast for child in actual.trace.children)
        assert actual.steps == path.steps_fn(*slots, pool)
        assert actual.outcome == Ok(path.fn(*slots, pool))
    finally:
        library.agent = previous


def test_i1_i4_on_public_bounded_inputs(library):
    secret = source()
    before = secret
    authorized = library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), secret))
    assert secret is before and isinstance(authorized.outcome, Ok)
    public = Card("Mask", "cells", public_mask().fields[:4])
    views = library.run("capture", (kernel.FnRef("top"), kernel.FnRef("side"), hosts.volume(
        hosts.cell(1, 0, 1), hosts.cell(1, 0, 2)))).outcome.value
    pool = library.run("candidates", (public, views)).outcome.value
    scope = library.scope()
    for name, args in (("ink", (secret,)), ("matches", (secret, authorized.outcome.value)),
                       ("retain", (kernel.FnRef("top"), pool, hosts.top(secret))),
                       ("forced", (pool,)), ("least", (pool,))):
        actual = library.run(name, args)
        unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),
                                                 scope), scope=scope)
        assert outcome_equal(actual.outcome, unfolded.outcome) and actual.steps == unfolded.steps
    library.agent = "learner"
    assert library.run("front", (secret,)).outcome == Bottom("permission")
    assert library.run("best_probe", (pool,)).outcome == Bottom("permission")
    assert library.run("plan", (kernel.FnRef("front"), kernel.FnRef("diag"),
                                kernel.FnRef("anti"), pool)).outcome == Bottom("permission")
    assert library.run("plan", (kernel.FnRef("top"), kernel.FnRef("diag"),
                                kernel.FnRef("anti"), pool)).outcome == Bottom("probe_domain")
    assert library.run("least", (pool,), fuel=1).outcome == Unknown("fuel")


def test_every_fresh_card_against_depth_reference(library, reference):
    public, examples, fixtures = fresh_examples()
    assert len({secret for _, secret in fixtures}) == 11
    reference_mask = reference.Mask(frozenset(item.fields for item in public.fields))
    library.agent = "extra"
    for name, expression, _, _, secret in examples:
        actual = kernel.evaluate(expression, scope=library.scope()).outcome
        assert isinstance(actual, Ok), (name, actual)
        reference_secret = reference.Volume(frozenset(item.fields for item in hosts._cells(secret)))
        reference_views = reference.capture(reference_secret)
        reference_pool = reference.candidates(reference_mask, reference_views)
        if name in ("Views", "capture"):
            assert render(actual.value) == render(Card("Views", "val", (hosts.views_record(
                hosts.top(secret), hosts.side(secret), 4),)))
        elif name == "matches":
            assert actual.value == values.boolean(reference.matches(reference_secret, reference_views))
        elif name in ("Candidates", "retain"):
            assert len(hosts.pool_volumes(hosts.pool_raw(actual.value)).fields) == len(reference_pool.volumes)
        elif name == "forced":
            assert {item.fields for item in actual.value.fields} == reference.forced(reference_pool)
        elif name == "least":
            expected = reference.least(reference_pool)
            assert actual.value.fields == (expected.mass, expected.count)
        elif name == "ambiguity":
            assert actual.value == reference.ambiguity(reference_pool)
        elif name == "add_view":
            assert actual.value == reference.ambiguity(reference.add_view(
                "anti", reference_pool, reference.anti(reference_secret), ("anti",)))
        elif name == "best_probe":
            expected = reference.best_probe(reference_pool)
            assert actual.value.fields == (expected.probe, expected.worst, expected.groups)
        elif name == "plan":
            expected = reference.plan(reference_pool)
            assert actual.value.fields == (expected.depth, expected.first, expected.worst_after_first)


def test_publication_and_ascii(library):
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    library.agent = "extra"
    assert data == build_export(library)
    assert OUTPUT.stat().st_size < 3_000_000
    assert data["tower_source"] == "depth" and len(data["story"]) == 12
    assert [task["answer_checked"] for task in data["showcase"]] == [True, True, True]
    assert data["story"][7]["examples"][-1]["outcome"] == {"bottom": "empty_candidates"}
    for card in data["story"]:
        for example in card["examples"]:
            assert "learner_view" in example and "judge_view" not in example
            assert example["steps"] >= 0 and example["trace"]
            assert "Volume<" not in example["text"]
    def strings(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                yield from strings(item, name)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item, key)
        elif isinstance(value, str) and not key.endswith("_zh"):
            yield value
    forbidden = "⟨⟩⟦⟧⦅⦆♠♦○◉ℚ𝔹"
    assert not any(character in text for text in strings({key: value for key, value in data.items()
                                                          if key != 'notation3'}) for character in forbidden)
    assert str(source().fields[0]) not in OUTPUT.read_text(encoding="utf-8")
    assert render(source()) not in OUTPUT.read_text(encoding="utf-8")
    assert data["showcase"][1]["answer"] == "sealed"
    judge = json.loads(JUDGE_OUTPUT.read_text(encoding="utf-8"))
    assert len(judge["examples"]) == sum(len(card["examples"]) for card in data["story"])
    assert judge["showcase"][1]["answer"] == DESIGN["showcase"][1]["answer"]
    public_ids = {example["id"] for card in data["story"] for example in card["examples"]}
    assert public_ids == {example["id"] for example in judge["examples"]}


def test_story_declarations_and_example_notation(library):
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    judge = json.loads(JUDGE_OUTPUT.read_text(encoding="utf-8"))
    fresh_mask, fresh_rows, _ = fresh_examples()
    expected = {f"{name}:0": (expr, source(), public_mask())
                for name, expr, _, _ in primary_examples()}
    expected.update({f"{name}:1": (expr, secret, fresh_mask)
                     for name, expr, _, _, secret in fresh_rows})
    failure = next(entry for entry in judge["examples"] if entry["id"] == "least:2")
    impossible = values.decode(failure["inputs"][1])
    expected["least:2"] = (call_expression("least", call_expression("candidates", public_mask(),
                                                                     impossible)), source(), public_mask())

    def bind(node, bindings):
        if isinstance(node, nodes.Var):
            return nodes.Lit(bindings[node.name])
        if isinstance(node, nodes.Call):
            return nodes.Call(node.fn, tuple(bind(arg, bindings) for arg in node.args))
        return node

    assert len(data["story"]) == 12
    examples = [example for card in data["story"] for example in card["examples"]]
    assert len(examples) == 24
    for card in data["story"]:
        assert card["body_sha256"] == export_util.body_sha256(library.get(card["name"]).body)
        if "ascii" in card:
            parsed = notation.parse_definition(card["ascii"])
            assert parsed.name == card["name"]
            assert parsed.kind == card["kind"]
            assert parsed.layer == card["def_layer"]
            assert card["ascii"] == card["decl"]
            assert export_util.source_matches(card["ascii"], card["body_sha256"])
        else:
            assert "decl" not in card
        assert card["design_text"] == card["design_decl"]
        for example in card["examples"]:
            if card["name"] == "Views":
                assert "ascii" not in example
            else:
                original, secret, _mask = expected[example["id"]]
                bindings = {"s": secret, "m": public_mask(), "n": fresh_mask,
                            **{name: kernel.FnRef(name) for name in
                               ("top", "side", "front", "diag", "anti")}}
                assert bind(notation.parse_expr(example["text"]), bindings) == original
                assert example["ascii"] == example["text"]
    assert sum("ascii" in example for example in examples) == 22


def test_published_ascii_matches_stored_body(library):
    rows = json.loads(OUTPUT.read_text(encoding="utf-8"))["story"]
    assert [row["name"] for row in rows if "ascii" not in row] == [
        "ink", "Views", "capture", "matches", "Candidates", "retain", "forced", "least",
        "ambiguity", "add_view", "best_probe", "plan"]
    for row in rows:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row
