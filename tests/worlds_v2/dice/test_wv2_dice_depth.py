"""Exact depth examples, pipeline guards, finite scopes and export fidelity."""

import importlib.util
import json
import os
import random
from copy import copy
from dataclasses import replace
from fractions import Fraction
from itertools import product

import pytest
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.library import PipelineError
from opulse.atoms.values import Bottom, Card, Ok, encode_outcome, outcome_equal
from opulse.atoms.verify import unfold_equivalent, unfold_equivalent_calls
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.dice import hosts
from opulse.worlds_v2.dice.export import (
    DESIGN_PATH,
    EXPORT_PATH,
    TOWER_NAMES,
    _card_text,
    _example_expr,
    _example_text,
    build_export,
)
from opulse.worlds_v2.dice.story import _wrap, build_library, definitions, example_args
from opulse.worlds_v2.dice.world import DECL_PATH, new_library
from opulse.worlds_v2.export_util import body_sha256, source_matches


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def design_module():
    path = DESIGN_PATH.with_suffix(".py")
    spec = importlib.util.spec_from_file_location("dice_depth_reference", path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_twelve_kernel_examples_and_independent_reference(library, design_module):
    assert design_module.as_text(design_module.POSTERIOR) == "Belief<6/25,19/25>"
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    args = example_args()
    for name, card, reference in zip(TOWER_NAMES, design["tower"], design_module.example_values()):
        result = kernel.evaluate(_example_expr(name, args[name]), scope=library.scope())
        assert isinstance(result.outcome, Ok), name
        assert _card_text(result.outcome.value) == card["value"] == design_module.as_text(reference), name
    for left, right in product((hosts.FAIR, hosts.TILT), repeat=2):
        result = library.run("independent", (kernel.FnRef("roll"), kernel.FnRef("roll"), left, right))
        assert isinstance(result.outcome, Ok)
        assert sum(Fraction(entry.fields[1], entry.fields[2]) for entry in result.outcome.value.fields) == 1
        assert len(result.outcome.value.fields) == 36


def test_null_evidence_and_unchanged_truth(library):
    truth = library.run("independent", (kernel.FnRef("roll"), kernel.FnRef("roll"), hosts.FAIR, hosts.FAIR)).outcome.value
    before = json.dumps(encode_outcome(Ok(truth)), sort_keys=True)
    assert library.run("mass", (truth, hosts.event(2, 2))).outcome == Ok(hosts.to_card(Fraction(1, 36)))
    assert library.run("conditional", (hosts.pure(hosts.pair(6, 6)), _wrap("Event", hosts.event(10, 12)), _wrap("Event", hosts.event(2, 2)))).outcome == Bottom("domain")
    assert json.dumps(encode_outcome(Ok(truth)), sort_keys=True) == before
    assert library.run("advance", (kernel.FnRef("roll"), kernel.FnRef("total"), kernel.FnRef("jump"),
                                   _wrap("Walk", hosts.walk(hosts.belief(hosts.to_card(Fraction(1, 2)), hosts.to_card(Fraction(1, 2))), 6)), -1)).outcome == Bottom("domain")


@given(st.lists(st.integers(min_value=-100, max_value=100), min_size=1, max_size=5, unique=True),
       st.lists(st.integers(min_value=1, max_value=10), min_size=5, max_size=5))
def test_mean_support_unfolds_for_arbitrary_integer_scores(library, scores, weights):
    dist = hosts.distribution((score, Fraction(weight, sum(weights[:len(scores)])))
                              for score, weight in zip(scores, weights))
    result = library.run("mean", (dist,), trace=True)
    expected = hosts.to_card(sum((score * Fraction(weight, sum(weights[:len(scores)]))
                                  for score, weight in zip(scores, weights)), Fraction()))
    assert result.outcome == Ok(expected)
    assert unfold_equivalent(result.trace, [Boundary(), Boundary(depth=0), Boundary.unfold_all()]).ok


@pytest.mark.parametrize("score", [-7, 13, 100])
def test_mean_point_masses_outside_die_score_range(library, score):
    assert library.run("mean", (hosts.pure(score),)).outcome == Ok(hosts.to_card(score))


def test_promotion_and_bounded_evidence(library):
    for name in (*TOWER_NAMES, "step"):
        definition = library.get(name)
        assert definition.status == "promoted" and definition.evidence.world_hash == library.world.world_hash()
        assert definition.evidence.scope["size"] >= (4 if name == "independent" else 10) and definition.evidence.checks
        assert definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
        assert definition.contract is not None and definition.cost is not None
        assert definition.evidence.method in ("bounded", "exhaustive")
    assert library.get("total").evidence.scope["size"] == 36
    assert library.get("independent").evidence.scope["size"] == 4
    assert library.get("Event").evidence.scope["size"] == 66
    assert library.get("conditional").evidence.scope["size"] == 396
    assert library.get("Belief").evidence.scope["size"] == 51
    assert library.get("update").evidence.scope["size"] == 103
    assert library.get("step").evidence.scope["size"] == 100
    assert library.get("score").evidence.scope["size"] == 80
    assert library.get("independent").evidence.scope["op_family"] == {"f": ["roll", "pure"], "g": ["roll", "pure"]}
    assert library.get("mean").evidence.scope["size"] == 54
    assert not library.get("mean").spec.reads
    assert "entries" in nodes.references(library.get("mean").body)
    truth_readers = {operation.name for operation in library.world.operations
                     if any(edge.sort == library.world.observation["truth"] for edge in operation.inputs)}
    for name in ("hit_prob", "hitting"):
        assert nodes.references(library.get(name).body) & truth_readers <= set(library.get(name).spec.reads)
    assert library.get("Walk").evidence.scope["size"] == 55
    assert library.get("advance").evidence.scope["size"] == 24
    assert library.get("hit_prob").evidence.scope["size"] == 21
    assert library.get("hitting").evidence.scope["size"] == 10
    for name in ("Event", "Belief", "Walk"):
        assert {"canon_total", "canon_idempotent", "canon_keeps_valid"} <= set(library.get(name).evidence.checks)
        assert library.run(name + ".make", example_args()[name]).outcome == Ok(_wrap(name, example_args()[name][0]))
    assert library.run("Event.make", (hosts.Card("event", "range", (1, 1)),)).outcome == Bottom("invalid")
    assert library.run("Belief.make", (hosts.Card("belief", "weights", (hosts.to_card(Fraction(-1)), hosts.to_card(Fraction(2)))),)).outcome == Bottom("invalid")
    assert library.run("Walk.make", (hosts.Card("walk", "goal", (example_args()["Belief"][0], 1)),)).outcome == Bottom("invalid")


def test_refined_object_families_against_reference(library, design_module):
    for lo in range(2, 13):
        for hi in range(lo, 13):
            base = hosts.event(lo, hi)
            assert library.run("Event.make", (base,)).outcome == Ok(_wrap("Event", base))
            assert _card_text(library.run("Event.make", (base,)).outcome.value) == design_module.as_text(design_module.Event(lo, hi))
    for index in range(51):
        fraction = Fraction(index, 50)
        base = hosts.belief(hosts.to_card(fraction), hosts.to_card(1 - fraction))
        assert _card_text(library.run("Belief.make", (base,)).outcome.value) == design_module.as_text(design_module.Belief(fraction, 1 - fraction))
        if index % 5 == 0:
            for goal in range(2, 7):
                walk = hosts.walk(base, goal)
                assert _card_text(library.run("Walk.make", (walk,)).outcome.value) == design_module.as_text(
                    design_module.Walk(design_module.Belief(fraction, 1 - fraction), goal))


def test_unfold_cost_and_boundary(library):
    randomizer = random.Random(37)
    for name in ("total", "update", "hitting"):
        args = example_args()[name]
        result = library.run(name, args, trace=True)
        inlined = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(item) for item in args)), library.scope()), scope=library.scope())
        assert outcome_equal(result.outcome, inlined.outcome) and result.steps == inlined.steps
        assert unfold_equivalent(result.trace, [Boundary(), Boundary(depth=0), Boundary.unfold_all()]).ok
        assert unfold_equivalent_calls(result.trace, [Boundary(), Boundary.unfold_all(),
            Boundary(depth=randomizer.randrange(1, 5)), Boundary(open_names=frozenset({name}))]).ok
        assert sum(frame.steps for frame in flatten_calls(result.trace, Boundary(depth=0))) == result.steps


def test_probe_truth_and_judge_views(library):
    truth = library.run("independent", (kernel.FnRef("roll"), kernel.FnRef("roll"), hosts.FAIR, hosts.TILT)).outcome.value
    original = encode_outcome(Ok(truth))
    event = hosts.event(10, 12)
    expected = hosts.mass(truth, event)
    for learner_view in ({"result": "opaque"}, {"result": "different"}):
        observed = library.run("mass", (truth, event)).outcome
        assert observed == Ok(expected)
        judge_view = {"truth": original, "result": encode_outcome(observed)}
        assert judge_view["truth"] == original and learner_view != judge_view
    assert encode_outcome(Ok(truth)) == original


def test_invented_objects_reject_invalid_values(library):
    invalid = {
        "Event": (Card("event", "range", (1, 3)), Card("event", "range", (12, 13)),
                  Card("event", "range", (5, 4)), Card("event", "other", (2, 3))),
        "Belief": (Card("belief", "weights", (hosts.to_card(-1), hosts.to_card(2))),
                   Card("belief", "weights", (hosts.to_card(Fraction(1, 2)), hosts.to_card(Fraction(1, 3)))),
                   Card("belief", "wrong", (hosts.to_card(0), hosts.to_card(1)))),
        "Walk": (Card("walk", "goal", (hosts.belief(hosts.to_card(1), hosts.to_card(0)), 1)),
                 Card("walk", "goal", (hosts.belief(hosts.to_card(0), hosts.to_card(1)), 33)),
                 Card("walk", "goal", (Card("belief", "weights", (hosts.to_card(1), hosts.to_card(1))), 4))),
    }
    for name, values in invalid.items():
        for value in values:
            assert isinstance(library.run(f"{name}.make", (value,)).outcome, Bottom)


def test_forged_invented_cards_cannot_be_refined(library):
    for name in ("Event", "Belief", "Walk"):
        forged = Card(name, "val", (example_args()[name][0],))
        assert isinstance(library.run(f"{name}.make", (forged,)).outcome, Bottom)


@pytest.mark.parametrize("forged", (Card("Event", "fake", (hosts.event(2, 2),)),
                                     Card("Belief", "val", (hosts.belief(hosts.to_card(1), hosts.to_card(1)),)),
                                     Card("Walk", "val", (hosts.walk(hosts.belief(hosts.to_card(1), hosts.to_card(0)), 1),)),
                                     Card("Walk", "fake", ())))
def test_forged_cards_fail_invented_object_accessors(library, forged):
    assert isinstance(library.run(f"{forged.sort}.base", (forged,)).outcome, Bottom)


def test_generic_host_does_not_enforce_invented_event_shape():
    library = build_library(limit=3)
    forged = Card("Event", "fake", (hosts.event(2, 2),))
    assert hosts.field(forged, 0) == hosts.event(2, 2)
    assert isinstance(library.run("Event.base", (forged,)).outcome, Bottom)


def test_given_raw_cards_do_not_enforce_invented_refinements():
    invalid_prior = hosts.belief(hosts.to_card(-1), hosts.to_card(2))
    assert hosts.valid_world_value(hosts.event(1, 13))
    assert hosts.mass(hosts.pure(hosts.pair(1, 1)), hosts.event(1, 13)) == hosts.to_card(1)
    assert hosts.valid_world_value(invalid_prior)
    assert hosts.valid_world_value(hosts.walk(invalid_prior, 33))


def test_advance_slots_are_real_and_verified(library):
    definition = library.get("advance")
    assert definition.spec.op_params == ("roll_slot", "total_slot", "jump_slot")
    assert definition.evidence.scope["size"] == 24
    args = (kernel.FnRef("roll"), kernel.FnRef("total"), kernel.FnRef("jump"),
            _wrap("Walk", hosts.walk(hosts.belief(hosts.to_card(1), hosts.to_card(0)), 2)), 1)
    baseline = library.run("advance", args)
    for index, alias in enumerate(("roll_alias", "total_alias", "jump_alias")):
        aliased = list(args)
        aliased[index] = kernel.FnRef(alias)
        result = library.run("advance", aliased, trace=True)
        assert result.outcome == baseline.outcome
        def trace_names(node):
            return [node.name, *(name for child in node.children for name in trace_names(child))]

        assert alias in trace_names(result.trace)
    assert _example_text("advance", example_args()["advance"]).startswith("?mass{@advance[roll,total,jump](")


def test_builds_do_not_share_mutable_state():
    first = build_library(limit=3)
    first._definitions.clear()
    assert build_library(limit=3).get("total").status == "promoted"


@pytest.mark.skipif(not os.environ.get("OPULSE_RUN_SLOW"), reason="two independent full exports take more than 60 seconds")
def test_exports_do_not_share_mutable_state():
    exported = build_export()
    exported["story"].clear()
    assert len(build_export()["story"]) == 12


def test_fast_fresh_first_three_cards():
    fresh = build_library(limit=3)
    assert [fresh.get(name).status for name in TOWER_NAMES[:3]] == ["promoted"] * 3


def test_guarded_nested_example_keeps_kernel_steps_and_trace(library):
    expression = _example_expr("independent", example_args()["independent"])
    actual = library.run_example(expression)
    unfolded = kernel.evaluate(expression, scope=library.scope(), trace=True)
    assert actual.outcome == unfolded.outcome and actual.steps == unfolded.steps
    assert [child.name for child in actual.trace.children] == ["independent", "mass"]
    assert actual.trace.steps == actual.steps


def test_given_dist_has_no_generated_private_operations(library):
    assert not library.sealed_names()
    expression = nodes.Call("mass", (nodes.Lit(hosts.pure(1)), nodes.Lit((1,))))
    assert library.run_example(expression).outcome == Ok(hosts.to_card(1))


def test_evidence_is_required_finite_and_current(library):
    missing = new_library()
    missing.write(definitions()[0])
    with pytest.raises(PipelineError, match="verified"):
        missing.promote("independent", library.get("independent").contract)
    checked = library.get("independent")
    missing._definitions["independent"] = replace(checked, status="verified",
        evidence=replace(checked.evidence, method="sampled", seed=3))
    with pytest.raises(PipelineError, match="sampled"):
        missing.promote("independent", checked.contract)
    wrong = {**checked.evidence.scope["checked"], "sha256": "not-a-digest"}
    missing._definitions["independent"] = replace(checked, status="verified",
        evidence=replace(checked.evidence, scope={**checked.evidence.scope, "checked": wrong}))
    assert missing.get("independent").evidence is None  # a malformed checked record invalidates the evidence
    with pytest.raises(PipelineError, match="verified"):
        missing.promote("independent", checked.contract)
    changed = copy(library)
    changed._definitions = dict(library.definitions)
    changed._steps = dict(library._steps)
    changed._scope_key = None
    changed.world = replace(library.world, constants={**library.world.constants, "changed": True})
    assert changed.get("independent").status == "callable"
    with pytest.raises(PipelineError):
        changed.promote("independent", checked.contract)


def test_declaration_export_and_ascii(library, design_module):
    data = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    assert {key: value for key, value in WorldDecl.from_dict(data).to_dict().items()
            if key != "open_kinds"} == data
    assert not validate(load(DECL_PATH))
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert exported["tower_source"] == "depth" and len(exported["story"]) == 12
    assert len(exported["ladder"]) == 5 and len(exported["showcase"]) == 3
    assert [entry["answer"] for entry in exported["showcase"]] == list(map(design_module.as_text, design_module.showcase_values()))
    assert all(task["answer_checked"] for task in exported["showcase"])
    assert any("bottom" in example["outcome"] for entry in exported["story"] for example in entry["examples"])
    assert all(entry["title"] and entry["definition"] for entry in exported["story"])
    assert all(entry["title"] and entry["definition"] for section in ("objects", "operations")
               for entry in exported["layer0"][section])
    assert exported["story"][0]["examples"][0]["inputs"][0] == {"t": "fn", "v": "roll"}
    assert all("judge_view" not in example and "inputs" not in example["learner_view"]
               for entry in exported["story"] for example in entry["examples"])
    assert nodes.to_json(nodes.Lit(kernel.FnRef("roll")))["value"] == {"t": "fn", "v": "roll"}
    assert EXPORT_PATH.stat().st_size < 3_000_000

    def check_ascii(value, path=""):
        if isinstance(value, str):
            if not path.endswith("_zh") and not path.startswith("modalities_zh."):
                assert value.isascii(), path
        elif isinstance(value, dict):
            for key, item in value.items():
                if key == "notation3":  # Notation v3: the generated display block is not machine notation
                    continue
                check_ascii(item, key if not path else path + "." + key)
        elif isinstance(value, list):
            for item in value:
                check_ascii(item, path)

    check_ascii(exported)


def test_story_declarations_are_core_source(library):
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    for row in exported["story"]:
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            parsed = notation.parse_definition(row["ascii"])
            assert parsed.name == row["name"] and parsed.kind == row["kind"]
            assert parsed.layer == row["def_layer"] == library.get(row["name"]).layer
            assert row["decl"].endswith(f" L{row['def_layer']}")
            assert row["ascii"] == row["decl"]
            assert source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row
        assert row["design_decl"] and row["design_text"] == row["design_decl"]


def test_parseable_examples_are_exact_evaluated_expressions():
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    args = example_args()
    parseable_names = {"total", "update", "hit_prob", "hitting"}
    for row in exported["story"]:
        for example in row["examples"]:
            if row["name"] in parseable_names:
                assert notation.parse_expr(example["text"]) == _example_expr(row["name"], args[row["name"]])
                assert example["ascii"] == example["text"]
            else:
                with pytest.raises(notation.NotationError):
                    notation.parse_expr(example["text"])
                assert "ascii" not in example


@pytest.mark.skipif(not os.environ.get("OPULSE_RUN_SLOW"), reason="fresh full export takes more than 60 seconds")
def test_fresh_full_library_and_export_match_committed():
    assert json.loads(EXPORT_PATH.read_text(encoding="utf-8")) == build_export()
