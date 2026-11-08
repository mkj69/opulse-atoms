"""Binding design cases executed by the Opulse kernel, not by the oracle parser."""

import ast
import json

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import (
    BridgeSpec,
    Definition,
    LawSpec,
    ObjectSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.values import Bottom, Ok
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.comb_obs import reference as ref
from opulse.worlds_v2.comb_obs.export import DESIGN, EXPORT_PATH, evaluate
from opulse.worlds_v2.comb_obs.story import NAMES, build_library
from opulse.worlds_v2.comb_obs.world import DECL_PATH, decl, new_library
from opulse.worlds_v2.export_util import body_sha256, source_matches


def test_layer_zero_has_no_story_answer_hosts():
    removed = {"frontier_at", "route_length", "reserve_value", "audit_value",
               "search_known", "route_plan", "dispatch_plan", "choose_frontier",
               "should_charge", "can_reach", "needs_scan", "known_empty",
               "capacity_exhausted", "order_target", "action_is", "action_arg"}
    assert {operation.name for operation in decl().operations}.isdisjoint(removed)
    source = (DECL_PATH.parents[3] / "src/opulse/worlds_v2/comb_obs/hosts.py").read_text(encoding="utf-8")
    imports = (node for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.Import, ast.ImportFrom)))
    assert all("reference" not in ast.unparse(node) for node in imports)


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def design():
    return json.loads(DESIGN.read_text(encoding="utf-8"))


def test_world_and_promoted_story(library, design):
    world = decl()
    assert WorldDecl.from_dict(world.to_dict()).to_dict() == world.to_dict()
    assert set(world.open_kinds) == set(design["open_kinds"]) == {"combinator", "observation"}
    assert validate(load(DECL_PATH)) == []
    assert {entry["name"] for entry in world.combinators["library"]} == {"seq", "repeat", "search"}
    assert [definition.name for definition in library.derived_world().promoted] == list(NAMES)
    assert [library.get(name).layer for name in NAMES] == list(range(1, 9))
    for name in NAMES:
        definition = library.get(name)
        assert definition.status == "promoted"
        assert definition.evidence.world_hash == world.world_hash()
        assert definition.evidence.scope["checked"]["size"] == 1
        assert definition.cost.steps["min"] > 0
    for name, actions in {"walk": {"probe", "step"},
                          "explore": {"probe", "step", "fill"},
                          "dispatch": {"probe", "step", "fill", "load", "handoff"}}.items():
        body = library.get(name).body
        assert any(isinstance(node, nodes.Rec) for node in nodes.walk(body))
        assert actions <= ({node.fn for node in nodes.walk(body) if isinstance(node, nodes.Call)}
                           | {node.name for node in nodes.walk(body) if isinstance(node, nodes.Var)})


@pytest.mark.parametrize("kind", ["object", "operation", "law", "bridge", "template"])
def test_closed_kinds_refused_before_storage(kind):
    library = new_library()
    body = nodes.Lit(1)
    specs = {
        "object": ObjectSpec("forbidden", "given"),
        "operation": OperationSpec("forbidden", "transform", (), None, "no"),
        "law": LawSpec("forbidden", (), body),
        "bridge": BridgeSpec("forbidden", "Run", "Run", body),
        "template": TemplateSpec("forbidden", (), "object", {}),
    }
    with pytest.raises(PipelineError, match="closed"):
        library.write(Definition("forbidden", kind, "invented", 1, (), specs[kind], body))
    assert "forbidden" not in library.records()


@pytest.mark.parametrize("index", range(8))
def test_every_design_example_exactly(library, design, index):
    row = design["tower"][index]
    actual, run = evaluate(row["example"], library)
    assert actual == row["value"]
    assert run.steps > 0


def test_showcase_answers_exactly(library, design):
    for item in design["showcase"]:
        check = item["check"]
        if item["angle"] == "Invert":
            actual = [seed for seed in check["candidates"]
                      if evaluate(check["template"].replace("SEED", str(seed)), library)[0] == check["expected"]]
        elif item["angle"] == "Decide":
            actual = evaluate(check["left"], library)[0] == evaluate(check["right"], library)[0]
        else:
            actual = evaluate(check["expression"], library)[0]
        assert actual == item["answer"]


def test_unknown_cells_never_used_as_known_routes(library):
    state = ref.Run(17, (45, 44))
    assert ref.route(state, state.goal) is None
    assert ref.frontier(state) is False
    assert ref.route_len(state) is None
    assert library.run("walk", (kernel.FnRef("scan"), kernel.FnRef("move"),
                                state, state.goal)).outcome.reason == "unknown_route"


def test_layer_zero_combinators_and_known_only_search(library):
    state = ref.Run(17, (5, 4))
    composed = library.run("seq", (kernel.FnRef("scan"), kernel.FnRef("charge"), state)).outcome
    assert isinstance(composed, Ok)
    assert composed.value.scans == composed.value.charges == 1
    repeated = library.run("repeat", (kernel.FnRef("scan"), 2, state)).outcome
    assert isinstance(repeated, Ok)
    assert repeated.value.energy == 596 and repeated.value.scans == 2
    assert state.energy == 600 and not state.known
    callbacks = (kernel.FnRef("pos"), kernel.FnRef("known"))
    assert library.run("search", (*callbacks, state.pos, state.goal, state.known)).outcome == Ok(None)
    assert library.run("search", (*callbacks, state.pos, state.goal,
                                  {state.goal: True})).outcome == Ok(None)
    charted = library.run("chart", (kernel.FnRef("scan"), state)).outcome.value
    assert library.run("search", (*callbacks, charted.pos, charted.goal, charted.known)).outcome == Ok(
        tuple(ref.route(charted, charted.goal)))


def test_actions_and_audit_cannot_retroactively_invent_observations(library):
    state = ref.Run(17, (3, 2))
    assert library.run("move", (state, (2, 0))).outcome == Bottom("direction")
    assert state.pos == ref.HOME and not state.known
    moved = library.run("move", (state, (1, 0))).outcome
    assert isinstance(moved, Ok)
    assert moved.value.known == {}
    assert moved.value.log[0][3] is False
    assert library.run("audit", (moved.value,)).outcome.value[0] is False
    assert library.run("pick", (state, "A")).outcome.value.payload == 2
    assert library.run("deliver", (state, "A")).outcome == Bottom("not_delivery_site")


def test_export_bound_to_core_and_tags(library, design):
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert exported["world_hash"] == library.world.world_hash()
    assert exported["open_kinds"] == exported["tags"]["open_kinds"] == design["open_kinds"]
    assert [row["examples"][0]["value"] for row in exported["story"]] == [
        row["value"] for row in design["tower"]]
    assert [item["answer"] for item in exported["showcase"]] == [
        item["answer"] for item in design["showcase"]]
    assert all(item["answer_checked"] for item in exported["showcase"])


def test_published_source_matches_stored_body(library, design):
    rows = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    assert {row["name"] for row in rows if "ascii" not in row} == {
        "walk", "route_len", "explore", "reserve", "dispatch",
    }
    for row, entry in zip(rows, design["tower"], strict=True):
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert row["design_decl"] == entry["decl"]
        assert ("ascii" in row) == ("decl" in row)
        if "ascii" in row:
            assert row["ascii"] == row["decl"]
            assert source_matches(row["ascii"], digest)


def test_export_and_declaration_are_ascii_outside_zh():
    def check(value, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                check(item, name)
        elif isinstance(value, list):
            for item in value:
                check(item, key)
        elif isinstance(value, str) and not key.endswith("_zh"):
            assert value.isascii(), (key, value)

    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    declaration = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    check({key: value for key, value in exported.items() if key != 'notation3'})
    check(declaration)
    assert exported["tags"]["agents"] == 1
    assert type(exported["tags"]["agents"]) is int
