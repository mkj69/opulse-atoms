"""Depth melody: independent oracle, exact kernels and the promotion invariants."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import ObservationSpec
from opulse.atoms.values import Bottom, Card, Ok, outcome_equal
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.melody import adapter, hosts
from opulse.worlds_v2.melody.export import (
    _examples,
    _fresh_examples,
    build_export,
    render,
)
from opulse.worlds_v2.melody.story import (
    NAMES,
    build_library,
    kernel_value,
    op,
    oracle,
    reference_for,
    score,
)
from opulse.worlds_v2.melody.world import decl, new_library

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def library():
    if not os.environ.get("OPULSE_RUN_SLOW"):
        pytest.skip("full 12-card verification and showcase export take over 60 s; set OPULSE_RUN_SLOW=1")
    return build_library()


@pytest.fixture(scope="module")
def first_three():
    return build_library(limit=3)


@settings(max_examples=12, deadline=None)
@given(st.lists(st.tuples(st.integers(54, 78), st.integers(1, 4)), min_size=2, max_size=5),
       st.integers(-3, 3))
def test_fast_fresh_scan_unfold(first_three, events, offset):
    source = hosts.melody(*events)
    pattern = kernel_value(oracle().motif((0, events[0][1]), (offset, events[1][1])))
    arguments = (kernel.FnRef("occurs"), source, pattern)
    result = first_three.run("scan", arguments, trace=True)
    assert outcome_equal(result.outcome, Ok(reference_for("scan")(*arguments)))
    assert unfold_equivalent(result.trace, [Boundary(), Boundary(depth=0)]).ok
    assert all(first_three.get(name).evidence.scope["checked"]["size"] >= 50
               for name in ("Motif", "occurs", "scan"))


def test_tuple_backed_refined_accessor(first_three):
    valid = Card("Motif", "val", (((0, 1), (-3, 1)),))
    invalid = Card("Motif", "val", (((1, 1), (-3, 1)),))
    assert first_three.run("Motif.base", (valid,)).outcome == Ok(valid.fields[0])
    assert first_three.run("Motif.base", (invalid,)).outcome == Bottom("invalid")


def test_declaration_lock_round_trip():
    path = ROOT / "worlds/decl/v2/melody@1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["combinators"]["library"][0]["name"] == "map_notes"
    assert data["combinators"]["library"][0]["body"]["node"] == "Call"
    assert WorldDecl.from_dict(data).to_dict() == decl().to_dict()
    assert {key: value for key, value in decl().to_dict().items() if key != "open_kinds"} == data
    assert validate(load(path)) == []
    assert {"note_shift", "transpose", "slice_events", "concat"} <= {
        operation.name for operation in decl().operations}
    assert {"events", "beats"} <= {item["name"] for item in decl().observation["probes"]}


def test_every_tower_example_matches_depth_oracle(library):
    reference = oracle()
    templates = json.loads((ROOT / "worlds/catalogue/depth/melody.json").read_text(encoding="utf-8"))
    args, _ = _examples(reference)
    fresh = _fresh_examples(library, reference)
    for name, arguments, other, template in zip(NAMES, args, fresh, templates["tower"]):
        for inputs in (arguments, other):
            if name in ("Motif", "Score"):
                run = library.run(name + ".make", inputs)
            elif name in ("intervals", "cover_count", "cover_report"):
                run = adapter.run_observation(library, name, inputs[0])
            else:
                run = library.run(name, inputs)
            assert isinstance(run.outcome, Ok), (name, run.outcome)
            if inputs is arguments:
                assert render(run.outcome.value) == template["value"], name
            expected = reference_for(name)(*inputs)
            assert outcome_equal(run.outcome, expected if isinstance(expected, Bottom) else Ok(expected)), name


def test_failure_and_sparse_certificate(library):
    reference = oracle()
    *_, full, sparse = reference.cases()
    full = kernel_value(full)
    sparse = kernel_value(sparse)
    assert library.run("perform", (kernel.FnRef("realize"), full, ((0, 60),))).outcome == Bottom("mismatch")
    assert library.run("best_cover", (score(hosts.melody((60, 1), (65, 1)),
                                            (kernel_value(reference.cases()[0]),)),)).outcome == Bottom("no_cover")
    assert adapter.run_observation(library, "cover_report", sparse).outcome == Ok(kernel_value(reference.cover_report(reference.cases()[-1])))


def test_promoted_observation_uses_learner_probe_runs(library):
    source = hosts.melody((60, 1), (62, 2), (65, 1))
    result = adapter.run_observation(library, "intervals", source, trace=True)
    assert result == library.run("intervals", (hosts.events(source),), trace=True)


def test_layer_zero_boundaries_and_given_map(library):
    assert library.get("map_notes").status == "promoted"
    long_source = hosts.melody(*((60 + index % 5, 1 + index % 4) for index in range(64)))
    assert len(hosts.events(long_source)) == 64
    assert hosts.beats(long_source) == 160
    assert hosts.transpose(long_source, 13) == Bottom("range")
    assert hosts.transpose(long_source, -13) == Bottom("range")
    assert hosts.slice_events(long_source, 63, 2) == Bottom("slice")
    assert hosts.concat(long_source, hosts.melody((60, 1))) == Bottom("capacity")
    assert hosts.note_shift((84, 2), 1) == Bottom("pitch")
    assert hosts.note_shift(("bad", 1), 1) == Bottom("event")
    assert hosts.melody((85, 1)) == Bottom("invalid")
    assert library.run("Motif.make", (((1, 1), (2, 1)),)).outcome == Bottom("invalid")
    assert library.run("Motif.make", (((0, 1), (37, 1)),)).outcome == Bottom("invalid")
    source = hosts.melody((60, 1), (62, 2))
    assert library.run("map_notes", (kernel.FnRef("note_shift"), source)).outcome == Ok(
        hosts.melody((60, 1), (63, 2)))


def test_event_dependent_atom_costs(library):
    source = hosts.melody((60, 1), (63, 2), (66, 3), (69, 4))
    for count in (1, 2, 4):
        assert library.run("transpose", (hosts.melody(*source.fields[:count]), 1)).steps == count
        assert library.run("slice_events", (source, 0, count)).steps == count
    assert library.run("slice_events", (source, 3, 2)).steps == 1
    assert library.run("transpose", (source, 13)).steps == 1
    assert {name: library.scope().resolve(name).cost_rule for name in ("transpose", "slice_events")} == decl().extra["atom_cost_rules"]


def test_refined_constructors_reject_invalid_values(library):
    source = hosts.melody((60, 1), (62, 2))
    pattern = library.run("Motif.make", (((0, 1), (2, 2)),)).outcome.value
    for candidate in ((), ((1, 1), (2, 1)), ((0, 1), (37, 1)), ((0, 1), (1, 5)),
                      ((0, 1), (1, 1), (2, "bad")), Card("Motif", "val", ((),))):
        assert not isinstance(library.run("Motif.make", (candidate,)).outcome, Ok)
    for candidate in ((source, ()), (source, (pattern, pattern)), (source, ("not a motif",)),
                      (source, (["unhashable"],)),
                      (Card("Melody", "events", ((85, 1),)), (pattern,)),
                      Card("Score", "val", ((source, (pattern,)),))):
        assert not isinstance(library.run("Score.make", (candidate,)).outcome, Ok)


def test_malformed_cards_never_pass_hosts_or_learner(library):
    source = hosts.melody((60, 1), (62, 2))
    motif = Card("Motif", "val", (((0, 1), (2, 2)),))
    valid = Card("Score", "val", ((source, (motif,)),))
    assert hosts.score_view(valid) == valid
    assert hosts.beats(valid) == 3
    forged = (Card("Score", "val", ()), Card("Score", "wrong", ((source, (motif,)),)),
              Card("Score", "val", ((source, ()),)),
              Card("Score", "val", ((source, (motif, motif)),)),
              Card("Score", "val", ((source, (Card("Motif", "val", (((1, 1), (2, 2)),)),)),)),
              Card("Score", "val", ((Card("Melody", "events", ((85, 1),)), (motif,)),)),
              Card("Invented", "val", ()))
    for value in forged:
        assert hosts.score_view(value) == Bottom("invalid")
        assert hosts.beats(value) == Bottom("invalid")
        assert hosts.eq(value, value) == Bottom("invalid")
        assert library.run("score_view", (value,)).outcome == Bottom("invalid")
        assert library.run("beats", (value,)).outcome == Bottom("invalid")
        assert library.run("Score.base", (value,)).outcome == Bottom("invalid")
        assert library.run("list_cons", (value, ())).outcome == Bottom("invalid")
    assert library.run("Motif.base", (Card("Motif", "val", (((0, 5), (2, 1)),)),)).outcome == Bottom("invalid")
    assert library.run("eq", ({"nested": Card("Invented", "val", ())},
                              {"nested": Card("Invented", "val", ())})).outcome == Bottom("invalid")


def test_checker_rejects_unrelated_argument_type_errors():
    library = new_library()
    broken = replace(op("bad_add", (), nodes.Call("add", (nodes.Lit("not-an-int"), nodes.Lit(1)))),
                     depends_on=("add",))
    library.write(broken)
    with pytest.raises(PipelineError, match="add argument 1: expected int, got str"):
        library.check("bad_add")


def test_checker_rejects_forged_card_literals():
    library = new_library()
    forged = Card("Invented", "val", ())
    body = nodes.Call("eq", (nodes.Lit(forged), nodes.Lit(forged)))
    broken = replace(op("bad_literal", (), body), depends_on=("eq",))
    library.write(broken)
    with pytest.raises(PipelineError, match="invalid card literal"):
        library.check("bad_literal")


def test_observation_allows_transitive_public_probe_but_not_direct_undeclared_read():
    library = new_library()
    derived = replace(op("derived_events", ("s",), nodes.Call("events", (nodes.Var("s"),))),
                      depends_on=("events",))
    library.write(derived)
    library.check(derived.name)
    body = nodes.Call("derived_events", (nodes.Var("score_view"),))
    allowed = nodes.Var("score_view")
    for name, expression in (("transitive_events", body), ("direct_events", nodes.Call("events", (allowed,)))):
        definition = replace(op(name, (), expression), kind="observation", layer=2,
                             spec=ObservationSpec(name, ("score_view",), expression),
                             depends_on=tuple(nodes.references(expression)))
        library.write(definition)
        if name == "direct_events":
            with pytest.raises(PipelineError, match="probe events"):
                library.check(name)
        else:
            library.check(name)


@settings(max_examples=12, deadline=None)
@given(st.lists(st.tuples(st.integers(54, 78), st.integers(1, 4)), min_size=1, max_size=7),
       st.integers(-3, 3))
def test_random_transposition_unfold_and_cost(library, events, shift):
    source = hosts.melody(*events)
    result = library.run("transpose", (source, shift), trace=True)
    assert result.outcome == Ok(hosts.transpose(source, shift))
    assert result.steps == len(events)
    assert unfold_equivalent(result.trace, [Boundary(), Boundary(depth=0)]).ok


def test_promoted_scope_and_invariants(library):
    for name in NAMES:
        definition = library.get(name)
        assert definition.status == "promoted"
        assert definition.evidence.method in ("bounded", "exhaustive")
        assert definition.evidence.scope["size"] >= 50
        assert definition.contract and definition.cost.steps["max"] >= 0
        assert definition.evidence.world_hash == library.world.world_hash()
    assert library.get("count_covers").spec.body == library.get("count_covers").body
    assert library.get("scan").spec.body == library.get("scan").body
    source = hosts.melody((60, 1), (62, 1), (64, 2))
    motif = kernel_value(oracle().cases()[0])
    for name, arguments in (("occurs", (source, motif, 0)),
                            ("scan", (kernel.FnRef("occurs"), source, motif)),
                            ("realize", (motif, 61))):
        run = library.run(name, arguments, trace=True)
        assert unfold_equivalent(run.trace, [Boundary(), Boundary(depth=0), Boundary(depth=1)]).ok
    for item in NAMES:
        assert library.by_hash(library.content_hash(item)) == library.get(item)
    assert library.world.observation["capabilities"]["learner"]["probes"] == ["events", "beats", "score_view"]
    assert library.world.observation["judge_view"] == "full_state"
    assert hosts.events(source) != hosts.events(hosts.melody((60, 2), (62, 1), (64, 2)))


def test_committed_export_and_ascii(library):
    data = json.loads((ROOT / "docs/assets/data/worlds_v2/melody.json").read_text(encoding="utf-8"))
    assert data == build_export()
    assert len(data["story"]) == 12 and len(data["showcase"]) == 3
    assert all(item["answer_checked"] for item in data["showcase"])
    assert any("bottom" in example["outcome"] for item in data["story"]
               for example in item["examples"])
    assert all(item["examples"][0]["steps"] > 0 for item in data["story"])
    assert {item["name"] for item in data["story"] if "ascii" not in item} == {
        "Motif", "occurs", "scan", "realize", "motif_at", "Score", "count_covers",
        "cover_count", "best_cover", "perform", "cover_report",
        "intervals",  # round 6: printed subject {s} does not bind the body's events
    }
    for item in data["story"]:
        assert item["body_sha256"] == export_util.body_sha256(library.get(item["name"]).body)
        if "ascii" in item:
            assert item["decl"].isascii()
            assert notation.parse_definition(item["decl"]).layer == item["def_layer"]
            assert item["decl"].endswith(f" L{item['def_layer']}")
            assert item["ascii"] == item["decl"]
            assert export_util.source_matches(item["ascii"], item["body_sha256"])
        else:
            assert not item.get("decl")
        assert item["design_text"] == item["design_decl"]
        for example in item["examples"]:
            if item["kind"] != "object":
                assert isinstance(notation.parse_expr(example["text"], library), nodes.Call)
        assert item["examples"][0]["text"].isascii()
        assert item["cost"]["steps"]["over"] == "verification family"
        assert item["example_steps"] == {"min": min(example["steps"] for example in item["examples"]),
                                          "max": max(example["steps"] for example in item["examples"])}
        assert item["symbol"].startswith({"combinator": "@", "observation": "?", "object": item["name"],
                                           "operation": item["name"]}[item["kind"]])
    assert len((ROOT / "docs/assets/data/worlds_v2/melody.json").read_bytes()) < 3_000_000


def test_story_notation_round_trips_without_full_build():
    data = json.loads((ROOT / "docs/assets/data/worlds_v2/melody.json").read_text(encoding="utf-8"))
    kinds = {item["name"]: item["kind"] for item in data["story"]}
    context = {"kinds": kinds, "op_arity": {"scan": 1, "count_covers": 1, "perform": 1}}
    for item in data["story"]:
        if "ascii" in item:
            parsed = notation.parse_definition(item["decl"])
            assert (parsed.name, parsed.kind, parsed.layer) == (item["name"], item["kind"], item["def_layer"])
            assert item["decl"].endswith(f" L{item['def_layer']}")
            assert item["ascii"] == item["decl"]
            assert export_util.source_matches(item["ascii"], item["body_sha256"])
        else:
            assert not item.get("decl")
        assert item["design_text"] == item["design_decl"]
        for example in item["examples"]:
            if item["kind"] != "object":
                assert isinstance(notation.parse_expr(example["text"], context), nodes.Call)
