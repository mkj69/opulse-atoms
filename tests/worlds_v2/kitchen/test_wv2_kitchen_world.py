"""Locked depth declaration, pipeline status, replay, and export contracts."""

import json
import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, values
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.kitchen import depth_hosts as hosts
from opulse.worlds_v2.kitchen.depth_adapter import _observable
from opulse.worlds_v2.kitchen.export import EXPORT_PATH, JUDGE_PATH, build_export
from opulse.worlds_v2.kitchen.world import atoms, decl

pytest_plugins = ("kitchen_fixture",)


def test_declaration_and_host_digests():
    declaration = decl()
    assert [entry["name"] for entry in declaration.combinators["library"]] == ["seq"]
    assert declaration.combinators["library"][0]["body"]["node"] == "Rec"
    assert WorldDecl.from_dict(declaration.to_dict()).to_dict() == declaration.to_dict()
    assert not validate(load("worlds/decl/v2/kitchen@1.json"))
    assert {atom.name for atom in atoms()} == (
        {operation.name for operation in declaration.operations} | {"stock", "busy"})
    assert len(declaration.observation["probes"]) == 2
    assert declaration.params["raw_max"] == 8


def test_pipeline_and_actual_scopes(library):
    names = ("slot", "Plan", "peak", "reach", "yield", "Order",
             "meets", "filter_plans", "earliest", "score", "best", "min_flour")
    assert [library.get(name).kind for name in names] == [
        "combinator", "object", "observation", "operation", "observation",
        "object", "operation", "combinator", "observation", "operation",
        "combinator", "observation"]
    assert all(library.get(name).status == "promoted" for name in names)
    assert all(library.get(name).evidence.scope["size"] >= 50 for name in names)
    assert all(library.get(name).evidence.world_hash == library.world.world_hash()
               for name in names)
    assert library.get("Plan").evidence.checks >= ("canon_total",)
    assert all("non_interference" in library.get(name).evidence.checks
               for name in ("peak", "yield", "earliest", "min_flour"))
    assert len(library.derived_world().promoted) >= len(names)
    assert library.get("seq").status == "promoted"
    assert [library.get(name).layer for name in (
        "make_plan", "pack_frontier", "reach", "make_order", "earliest", "min_flour"
    )] == [3, 4, 4, 2, 5, 5]
    assert "seq" in library.scope().defns
    record = values.Card("OrderData", "order", (0, 0, 0, 0))
    assert library.run("Order.make", (record,)).outcome == values.Ok(
        values.Card("Order", "val", (record,)))
    invalid = values.Card("OrderData", "order", (0, 0, 0, 13))
    assert library.run("Order.make", (invalid,)).outcome == values.Bottom("invalid")


def test_verified_object_scopes_roundtrip_through_json(library):
    for name in ("Plan", "Order"):
        definition = library.get(name)
        assert definition.evidence.scope == json.loads(json.dumps(definition.evidence.scope))
        assert definition.cost.to_dict() == json.loads(json.dumps(definition.cost.to_dict()))


def test_observation_equivalence_uses_public_probes_not_card_identity():
    initial = hosts.state(2, 1, 0, 0)
    later = values.Card("State", "state", (1, initial.fields[1], ()))
    assert initial != later
    assert _observable(initial) == _observable(later)


def test_error_and_fuel_are_distinct(library):
    state = hosts.state(2, 1, 0, 0)
    assert library.run("slot", (("bake_bread",), state)).outcome == values.Bottom("stock")
    assert library.run("slot", (("mix", "whisk"), state)).outcome == values.Bottom("station")
    assert library.run("slot", (("whisk", "mix"), state)).outcome == values.Bottom(
        "duplicate_or_unsorted")
    assert library.run("slot", (("mix",), state), fuel=1).outcome == values.Unknown("fuel")


def test_kernel_unfold_and_boundary(library):
    from opulse.atoms.boundary import Boundary
    from opulse.atoms.verify import unfold_equivalent

    state = hosts.state(2, 1, 0, 0)
    expression = nodes.Call("slot", (nodes.Lit(("mix",)), nodes.Lit(state)))
    direct = kernel.evaluate(expression, scope=library.scope(), trace=True)
    unfolded = kernel.evaluate(kernel.inline(expression, library.scope()),
                               scope=library.scope(), trace=True)
    assert direct.outcome == unfolded.outcome and direct.steps == unfolded.steps
    assert unfold_equivalent(direct.trace, [Boundary(), Boundary(depth=0)]).ok


@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1",
                    reason="full fresh export; set OPULSE_RUN_SLOW=1")
def test_export_matches_generator():
    generated = build_export()
    assert json.loads(EXPORT_PATH.read_text(encoding="utf-8")) == generated
    assert EXPORT_PATH.read_text(encoding="utf-8") == json.dumps(
        generated, sort_keys=True, ensure_ascii=False, indent=1) + "\n"
    assert len(generated["story"]) == 12
    assert len(generated["ladder"]) == 5 and len(generated["showcase"]) == 3
    assert all("learner_view" in row["examples"][0] and
               "judge_view" not in row["examples"][0] for row in generated["story"])
    assert generated["story"][0]["examples"][1]["outcome"] == {"bottom": "stock"}


def test_committed_export_has_real_traces_and_private_judge():
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    judge = json.loads(JUDGE_PATH.read_text(encoding="utf-8"))
    for row in exported["story"]:
        assert row["symbol"].startswith({"combinator": "@", "observation": "?"}.get(
            row["kind"], ""))
        for index, example in enumerate(row["examples"]):
            assert example["trace"] and example["trace"]["steps"] == example["steps"]
            assert "inputs" not in example and "judge_view" not in example
            assert f"{row['name']}:{index}" in judge["examples"]
            assert '"lots"' not in json.dumps(example)
            assert all("inputs" in node and "outcome" in node
                       for node in trace_nodes(example["trace"]))
            assert '"t": "tuple"' not in json.dumps(example["trace"])


def trace_nodes(root):
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(node["children"])


@given(flour=st.integers(0, 2), water=st.integers(0, 2),
       egg=st.integers(0, 2), milk=st.integers(0, 2),
       action=st.sampled_from(((), ("mix",), ("whisk",), ("mix", "whisk"))))
@settings(max_examples=15, deadline=None)
def test_slot_unfolds_on_random_small_stocks(library, flour, water, egg, milk, action):
    state = hosts.state(flour, water, egg, milk)
    expression = nodes.Call("slot", (nodes.Lit(action), nodes.Lit(state)))
    direct = kernel.evaluate(expression, scope=library.scope())
    expanded = kernel.evaluate(kernel.inline(expression, library.scope()),
                               scope=library.scope())
    assert direct.outcome == expanded.outcome
    assert direct.steps == expanded.steps
