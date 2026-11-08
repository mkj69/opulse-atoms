"""Independent finite oracle for the first three timed-kitchen cards."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.values import Bottom, Card, Ok
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.kitchen import depth_hosts as hosts
from opulse.worlds_v2.kitchen.export import (
    EXPORT_PATH,
    arguments,
    ascii_declaration,
    example_expression,
    literal,
)

pytest_plugins = ("kitchen_fixture",)
SOURCE = Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/kitchen.py"
SPEC = importlib.util.spec_from_file_location("kitchen_depth_pipeline_oracle", SOURCE)
oracle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = oracle
SPEC.loader.exec_module(oracle)


def test_story_declarations_are_core_ascii_at_their_computed_layers(library):
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert {row["name"] for row in exported["story"] if "ascii" not in row} == {
        "Plan", "peak", "reach", "yield", "Order", "meets", "earliest", "score", "best", "min_flour",
    }
    for row in exported["story"]:
        definition = library.get(row["name"])
        digest = export_util.body_sha256(definition.body)
        assert row["body_sha256"] == digest
        assert row["def_layer"] == definition.layer
        if "ascii" in row:
            parsed = notation.parse_definition(row["decl"])
            assert row["decl"].endswith(f" L{row['def_layer']}")
            assert parsed.name == row["name"]
            assert parsed.layer == row["def_layer"]
            assert row["decl"] == row["ascii"] == ascii_declaration(definition)
            assert export_util.source_matches(row["ascii"], digest)
        else:
            assert not row.get("decl")
            assert ascii_declaration(definition) is None
        assert row["design_text"] == row["design_decl"]


def test_story_example_ascii_is_only_attached_to_core_parseable_expressions():
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    exceptions = {"filter_plans", "best"}
    for row in exported["story"]:
        for example in row["examples"]:
            if row["name"] in exceptions:
                assert "ascii" not in example
                with pytest.raises(notation.NotationError):
                    notation.parse_expr(example["text"])
            else:
                assert notation.parse_expr(example["text"])
                assert example["ascii"] == example["text"]


def test_slot_and_plan_through_pipeline(library):
    first = hosts.state(2, 1, 0, 0)
    record = library.run("PlanData.record", (first, ((),), hosts.tick(first)))
    assert isinstance(record.outcome, Ok)
    assert record.outcome.value.fields[1] == ((),)
    assert library.run("PlanData.record", (first, [], first)).outcome == Bottom("invalid")
    run = library.run("slot", (("mix",), first), trace=True)
    expected = oracle.slot(("mix",), oracle.state(2, 1, 0, 0))
    assert run.outcome == Ok(Card("State", "state", (expected.value.time,
                                                       expected.value.lots, expected.value.jobs)))
    slots = (("mix",), (), ("bake_bread",), (), ())
    result = library.run("make_plan", (first, slots), trace=True)
    independent = oracle.make_plan(oracle.state(2, 1, 0, 0), slots)
    assert result.outcome.value.fields[0].fields[2] == Card(
        "State", "state", (independent.value.end.time, independent.value.end.lots,
                            independent.value.end.jobs))
    assert library.run("slot", (("mix", "whisk"), first)).outcome == Bottom("station")
    assert library.run("make_plan", (first, (("bake_bread",),))).outcome == Bottom("stock")
    assert [library.get(name).status for name in ("slot", "Plan", "make_plan")] == ["promoted"] * 3
    assert library.get("Plan").evidence.scope["size"] == 50


def test_object_constructors_reject_invalid_records(library):
    initial = hosts.state(2, 1, 0, 0)
    malformed = Card("State", "state", (0, (("flour", -1, 1),), ()))
    for inputs in ((malformed, (), initial), (initial, (), malformed),
                   (initial, [], initial), (initial, (("missing",),), initial),
                   (initial, (([],),), initial),
                   (initial, ((),) * 13, initial)):
        assert library.run("PlanData.record", inputs).outcome == Bottom("invalid")
    for inputs in (("1", 0, 0, 1), (1, False, 0, 1),
                   (0, 0, 0, "1")):
        assert library.run("OrderData.order", inputs).outcome == Bottom("invalid")
    for inputs in ((-1, 0, 0, 1), (0, 0, 9, 1), (0, 0, 0, 13)):
        assert library.run("make_order", inputs).outcome == Bottom("invalid")


def test_forged_refinements_are_rechecked(library):
    initial = hosts.state(2, 1, 0, 0)
    invalid_plan = Card("Plan", "val", (Card("PlanData", "record",
                                             (initial, (), hosts.tick(initial))),))
    invalid_order = Card("Order", "val", (Card("OrderData", "order", (0, 0, 0, 13)),))
    assert isinstance(library.run("Plan.start", (invalid_plan,)).outcome, Bottom)
    assert isinstance(library.run("Order.deadline", (invalid_order,)).outcome, Bottom)


def test_forged_cards_never_pass_hosts_or_learner_runs(library):
    initial = hosts.state(2, 1, 0, 0)
    for forged in (
        Card("State", "state", (0, (("flour", "bad", 2),), ())),
        Card("State", "state", (0, (("flour", 0, 9),), ())),
        Card("State", "state", (1, (("bread", 1, 2),), ())),
        Card("State", "state", (1, (), (("mix", "bad"),))),
        Card("Plan", "val", (Card("PlanData", "record", (initial, ((),), initial)),)),
        Card("Order", "val", (Card("OrderData", "order", (0, 0, 0, 13)),)),
        Card("Plan", "val", ()),
        Card("OrderData", "order", (0, "bad", 0, 0)),
    ):
        assert not hosts.valid_input(forged)
        assert library.run("field", (forged, 0)).outcome == Bottom("invalid")
        assert library.run("eq", (forged, forged)).outcome == Bottom("invalid")
        assert hosts.eq(forged, forged) == Bottom("invalid")
        assert hosts.to_card(forged) == Bottom("invalid")
    assert hosts.stock(Card("State", "state", (0, (("flour", "bad", 2),), ()))) == Bottom("invalid")


def test_exported_plan_expression_replays_its_full_sealed_value(library):
    initial, slots = arguments("Plan", library)
    plan = library.run("make_plan", (initial, slots))
    assert isinstance(plan.outcome, Ok)
    text = literal(plan.outcome.value)
    assert text == f"make_plan({literal(initial)}, {literal(slots)})"
    assert "Plan<" not in text
    assert plan.outcome == library.run("make_plan", (initial, slots)).outcome
    assert library.run("peak", (plan.outcome.value,), expression=nodes.Call(
        "peak", (nodes.Lit(Card("Plan", "val", ())),))).outcome == Bottom("invalid")
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    for row in exported["story"]:
        if row["name"] not in ("peak", "yield", "meets", "score"):
            continue
        inputs = arguments(row["name"], library)
        assert literal(inputs[0]) in row["examples"][0]["text"]
        assert "Plan<" not in row["examples"][0]["text"]
        expression = nodes.Call(row["name"], tuple(example_expression(item) for item in inputs))
        run = library.run(row["name"], inputs, expression=expression)
        assert row["examples"][0]["steps"] == run.steps


def render(value):
    if isinstance(value, Bottom):
        return f"Bottom<{value.reason}>"
    if isinstance(value, Card) and value.sort == "State":
        if value.fields[0] or value.fields[2]:
            return "State<" + str(value.fields[0]) + ", " + render(value.fields[1]) + ", " + render(value.fields[2]) + ">"
        return "State<" + ", ".join(str(amount) for amount in hosts.stock(value)[:4]) + ">"
    if isinstance(value, Card) and value.sort == "Plan":
        start, slots, _ = value.fields[0].fields
        return "Plan<" + render(start) + ", " + render(slots) + ">"
    if isinstance(value, Card) and value.sort == "Order":
        return "Order<" + ", ".join(map(str, value.fields[0].fields)) + ">"
    if isinstance(value, tuple):
        return "List<" + ", ".join(render(item) for item in value) + ">"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def test_published_finite_examples(library):
    data = json.loads(SOURCE.with_suffix(".json").read_text(encoding="utf-8"))
    for name, row in zip(("slot", "Plan", "peak", "reach", "yield", "Order",
                          "meets", "filter_plans", "earliest", "score", "best", "min_flour"),
                         data["tower"]):
        if name in ("earliest", "min_flour"):
            continue
        inputs = arguments(name, library)
        call = {"Plan": "make_plan", "Order": "make_order"}.get(name, name)
        actual = library.run(call, inputs, fuel=500_000)
        assert isinstance(actual.outcome, Ok), (name, actual.outcome)
        assert render(actual.outcome.value) == row["value"], (name, render(actual.outcome.value), row["value"])
        assert oracle.render(oracle.evaluate(row["example"])) == row["value"]
        if name in ("filter_plans", "best"):
            assert isinstance(inputs[0], kernel.FnRef)


def test_deep_examples_and_three_showcases_match_independent_oracle():
    import json
    import re

    design = json.loads(SOURCE.with_suffix(".json").read_text(encoding="utf-8"))
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    query_texts = {
        8: ("earliest(query(state(2, 1, 0, 0), make_order(1, 0, 0, 4)))",
            "?earliest{Query<State<2,1,0,0>,Order<1,0,0,4>>}"),
        11: ("min_flour(query(state(4, 1, 2, 2), make_order(0, 0, 0, 0)))",
             "?min_flour{Query<State<4,1,2,2>,Order<0,0,0,0>>}"),
    }
    for position in (8, 11):
        row = design["tower"][position]
        expected = oracle.render(oracle.evaluate(row["example"]))
        example = exported["story"][position]["examples"][0]
        actual = example["outcome"]
        assert expected == row["value"]
        core_text, oracle_text = query_texts[position]
        assert example["text"] == core_text
        assert notation.parse_expr(core_text)
        assert oracle.render(oracle.evaluate(oracle_text)) == (
            "Bottom<no_plan>" if position == 8 else "0")
        if position == 8:
            assert actual == {"bottom": "no_plan"}
        else:
            assert actual == {"ok": {"t": "int", "v": 0}}
    for item in design["showcase"]:
        (expression,) = re.findall(r"`([^`]+)`", item["prompt"])
        assert oracle.render(oracle.evaluate(expression)) == item["answer"]


def test_learner_views_never_expose_private_lots():
    import json

    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    for card in exported["story"]:
        for example in card["examples"]:
            view = json.dumps(example["learner_view"], sort_keys=True)
            assert '"jobs"' not in view and '"lots"' not in view
            assert "learner_view" in example and "judge_view" not in example
