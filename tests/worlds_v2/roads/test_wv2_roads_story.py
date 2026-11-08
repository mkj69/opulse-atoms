"""Depth-road pipeline, independent design values and committed export."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, notation
from opulse.atoms.boundary import Boundary
from opulse.atoms.combinators import fix_spec
from opulse.atoms.library import PipelineError, atoms_digest
from opulse.atoms.spec import Contract
from opulse.atoms.values import Bottom, Ok, Unknown, boolean, decode, decode_outcome
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.roads import depth_combinators, export, reference
from opulse.worlds_v2.roads import depth_hosts as hosts
from opulse.worlds_v2.roads.story import TINY, build_library, definitions
from opulse.worlds_v2.roads.world import decl, new_library


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def exported():
    return json.loads(export.EXPORT_PATH.read_text(encoding="utf-8"))


def test_fresh_first_three_cards(library, exported):
    from opulse.worlds_v2.roads.export import _example

    graph = hosts.METRO
    route = library.run("Route.make", (hosts.route_raw(graph, hosts.items("A", "D", "F", "H", "K", "L")),)).outcome.value
    inputs = ((hosts.route_raw(graph, hosts.items("A", "D", "F", "H", "K", "L")),),
              (route,), (kernel.FnRef("edge"), graph, "A", "L"))
    for card, args in zip(exported["story"][:3], inputs):
        fresh = _example(library, card["name"], args)
        assert fresh == {key: value for key, value in card["examples"][0].items() if key != "ascii"}


@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="full traced fresh export exceeds 60 seconds")
def test_full_fresh_export_matches_committed(exported):
    assert export.build_export() == exported


def test_declaration_round_trip_and_public_graph():
    world = decl()
    assert WorldDecl.from_dict(world.to_dict()).to_dict() == world.to_dict()
    assert world.combinators["library"] == [depth_combinators.chain_spec().to_dict(), fix_spec().to_dict()]
    path = Path(__file__).resolve().parents[3] / "worlds/decl/v2/roads@1.json"
    assert validate(load(path)) == []
    assert set(world.open_kinds) == {"object", "operation", "combinator", "observation"}
    assert len(hosts.from_card(hosts.METRO)[1]) == 23
    assert hosts.from_card(hosts.to_card(hosts.from_card(hosts.METRO))) == hosts.from_card(hosts.METRO)
    assert hosts.map_view(hosts.METRO) == hosts.METRO
    assert hosts.edge(hosts.METRO, "A", "L") == Bottom("no_edge")
    assert "Edge" in {obj.name for obj in world.objects}


def test_host_digest_ignores_runtime_bookkeeping():
    library = new_library()
    digest = atoms_digest(library.atoms)
    library._steps["sample"] = [1]
    assert atoms_digest(library.atoms) == digest


def test_every_tower_card_is_promoted_with_honest_family(library):
    tower = [library.get(name) for name in export.TOWER_NAMES]
    assert library.get("Route").spec.interface == ("Route.make", "Route.graph", "Route.vertices")
    assert library.get("Closure").spec.interface == ("Closure.make", "Closure.base", "Closure.closed_edges")
    assert [item.kind for item in tower] == ["object", "operation", "combinator", "operation",
        "observation", "object", "operation", "combinator", "observation", "operation",
        "operation", "observation"]
    for definition in tower:
        assert definition.status == "promoted"
        assert definition.evidence.method == "bounded"
        assert definition.evidence.scope["size"] == 256  # every weighting 1..4 of the four roads
        assert definition.evidence.scope["checked"]["size"] == 256
        assert "all 256 weightings" in definition.evidence.scope["description"]
        assert len(definition.evidence.scope["checked"]["sha256"]) == 64
        assert definition.evidence.world_hash == library.world.world_hash()
        assert definition.contract and definition.cost.steps
        assert definition.origin == "invented"
    assert {definition.name for definition in library.derived_world().promoted} >= set(export.TOWER_NAMES)
    assert library.get("survives").layer == 4
    assert library.get("cut_certificate").layer == 5
    assert "close" in library.get("survives").depends_on
    assert "close" in library.get("worst").depends_on
    assert {"canon_total", "canon_idempotent", "canon_keeps_valid"} <= set(
        library.get("Closure").evidence.checks)
    for name in ("explore", "failures"):
        assert len(next(iter(library.get(name).evidence.scope["op_family"].values()))) == 2
        assert "fixed_ops" not in library.get(name).evidence.scope


def test_design_oracle_and_twelve_exact_kernel_examples(exported):
    design = json.loads(export.DESIGN.read_text(encoding="utf-8"))
    assert len(exported["story"]) == 12
    assert [item["layer"] for item in exported["story"]] == list(range(1, 13))
    assert [item["name"] for item in exported["story"]] == list(export.TOWER_NAMES)
    assert all(item["status"] == "promoted" for item in exported["story"])
    assert all(item["examples"][0]["steps"] > 0 for item in exported["story"])
    assert all(item["examples"][0]["trace"] for item in exported["story"])
    assert exported["story"][2]["examples"][0]["outcome"] == {"ok": {"t": "int", "v": 419}}
    assert exported["story"][7]["examples"][0]["outcome"] == {"ok": {"t": "int", "v": 277}}
    assert exported["story"][2]["examples"][0]["inputs"][0] == {"t": "fn", "v": "edge"}
    assert exported["story"][7]["examples"][0]["inputs"][0] == {"t": "fn", "v": "close"}
    for card in exported["story"]:
        assert card["layer"] <= 12
        assert card["evidence"]["scope"]["size"] >= 50
        assert card["title"] and card["definition"]
    assert [item["answer_checked"] for item in exported["showcase"]] == [True, True, True]
    assert [item["answer"] for item in exported["showcase"]] == [item["answer"] for item in design["showcase"]]
    for card in exported["story"]:
        case = card["examples"][0]
        args = tuple(kernel.FnRef(value["v"]) if value["t"] == "fn" else decode(value)
                     for value in case["inputs"])
        oracle = reference.expected(card["name"], *args)
        if card["name"] in ("explore", "failures"):
            oracle = len(oracle.fields)
        assert decode_outcome(case["outcome"]) == (oracle if isinstance(oracle, Bottom) else Ok(oracle))
    reference.design().verify()


def test_bounded_inputs_include_disconnected_and_closure_canon(library, exported):
    failed = exported["story"][3]["examples"][-1]
    assert failed["outcome"] == {"bottom": "no_route"}
    assert library.run("best", (hosts.METRO, "A", "Z")).outcome == Bottom("no_route")
    assert library.run("worst", (TINY, "A", "D", 2)).outcome == Bottom("disconnected")
    assert library.run("worst", (TINY, "Z", "D", 0)).outcome == Bottom("disconnected")
    assert library.run("mincut", (TINY, "A", "A")).outcome == Bottom("invalid_terminals")
    assert library.run("failures", (kernel.FnRef("close"), TINY, 5)).outcome == Bottom("invalid_budget")
    assert library.run("best", (hosts.METRO, "A", "L"), fuel=5).outcome == Unknown("fuel")
    raw = hosts.closure_raw(TINY, hosts.edge_set(hosts.items("AC", "AB", "AB")))
    made = library.run("Closure.make", (raw,)).outcome
    assert made == Ok(reference.expected("Closure", hosts.closure_raw(
        TINY, hosts.edge_set(hosts.items("AB", "AC")))))
    view = library.run("map_view", (made.value,)).outcome.value
    assert library.run("edge", (view, "A", "B")).outcome == Bottom("no_edge")
    assert library.run("map_view", (hosts.Card("Closure", "val", made.value.fields),)).outcome == Bottom("invalid_closure")
    assert library.run("map_view", (hosts.Card("Closure", "val", (hosts.closure_raw(TINY,
        hosts.edge_set(hosts.items("ZZ"))),)),)).outcome == Bottom("invalid_closure")
    assert library.run("Route.make", (hosts.route_raw(TINY, hosts.items("A", "B", "A")),)).outcome == Bottom("invalid")


def test_invented_objects_reject_invalid_and_forged_values(library):
    for path in ((), ("A", "D"), ("A", "B", "A"), ("A", "Z")):
        assert library.run("Route.make", (hosts.route_raw(TINY, hosts.items(*path)),)).outcome == Bottom("invalid")
    for malformed in (hosts.Card("RouteRaw", "wrong", (TINY, hosts.items("A", "B"))),
                      hosts.Card("RouteRaw", "route", (TINY,)),
                      hosts.Card("RouteRaw", "route", (TINY, hosts.items(1, 2)))):
        assert isinstance(library.run("Route.make", (malformed,)).outcome, Bottom)
    valid_route = library.run("Route.make", (hosts.route_raw(TINY, hosts.items("A", "B", "D")),)).outcome.value
    forged_route = hosts.Card("Route", "val", valid_route.fields)
    assert library.run("Route.graph", (forged_route,)).outcome == Bottom("invalid")
    assert kernel.call("Route.graph", (forged_route,), library.scope()).outcome == Bottom("invalid")
    assert library.run("cost", (forged_route,)).outcome == Bottom("invalid")
    for blocked in (("ZZ",), ("AB", "ZZ"), ("AB", "AA")):
        invalid = hosts.closure_raw(TINY, hosts.edge_set(hosts.items(*blocked)))
        assert library.run("Closure.make", (invalid,)).outcome == Bottom("invalid")
    for malformed in (hosts.Card("ClosureRaw", "wrong", (TINY, hosts.edge_set(hosts.items()))),
                      hosts.Card("ClosureRaw", "closed", (TINY,)),
                      hosts.closure_raw(TINY, hosts.Card("Edges", "set", (hosts.items(123),)))):
        assert isinstance(library.run("Closure.make", (malformed,)).outcome, Bottom)
    valid_closure = library.run("close", (TINY, hosts.edge_set(hosts.items("AB")))).outcome.value
    forged_closure = hosts.Card("Closure", "val", valid_closure.fields)
    assert library.run("Closure.closed_edges", (forged_closure,)).outcome == Bottom("invalid")
    assert kernel.call("Closure.closed_edges", (forged_closure,), library.scope()).outcome == Bottom("invalid")
    assert library.run("map_view", (forged_closure,)).outcome == Bottom("invalid_closure")


def test_i1_i4_small_trace_boundary_and_immutability(library):
    original = hosts.from_card(TINY)
    trace = library.run("best", (TINY, "A", "D"), trace=True)
    assert trace.outcome == Ok(reference.expected("best", TINY, "A", "D"))
    assert trace.steps == sum(leaf.steps for leaf in _given_leaves(trace.trace))
    assert unfold_equivalent_calls(trace.trace, [Boundary(), Boundary(depth=0),
        Boundary(depth=2, keep_names=frozenset({"cost"}))]).ok
    assert hosts.from_card(TINY) == original
    denied = library.run("Route.make", (hosts.route_raw(TINY, hosts.items("A", "D")),))
    assert denied.outcome == Bottom("invalid")
    assert library.run("reachable", (TINY, "A", "D")).outcome == Ok(boolean(True))
    initial = hosts.reach_state(TINY, hosts.items("A"))
    closure = library.run("fix", (kernel.FnRef("reach_step"), initial, 4), trace=True)
    assert closure.outcome == Ok(hosts.reach_state(TINY, hosts.items("A", "B", "C", "D")))
    assert closure.steps == sum(leaf.steps for leaf in _given_leaves(closure.trace))
    assert library.run("fix", (kernel.FnRef("reach_step"), initial, 0)).outcome == Bottom("not_stable")
    failures = library.run("failures", (kernel.FnRef("close"), TINY, 1)).outcome.value.fields
    assert [item.fields[0].fields[1].fields[0].fields for item in failures] == [
        (), ("AB",), ("AC",), ("BD",), ("CD",)]


@settings(max_examples=8, deadline=None)
@given(st.tuples(*(st.integers(min_value=1, max_value=4) for _ in range(4))),
       st.lists(st.sampled_from(("AB", "AC", "BD", "CD")), unique=True, max_size=2))
def test_random_closure_boundary_and_unfold(library, weights, removed):
    graph = hosts.to_card((("A", "B", "C", "D"),
        tuple((start, end, weight) for (start, end), weight in zip(
            (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")), weights))))
    closure = library.run("close", (graph, hosts.edge_set(hosts.items(*sorted(removed))))).outcome.value
    trace = library.run("map_view", (closure,), trace=True)
    visible = trace.outcome.value
    assert hosts.from_card(visible)[1] == tuple(edge.fields for edge in graph.fields[1].fields
                                                  if edge.fields[0] + edge.fields[1] not in removed)
    assert unfold_equivalent_calls(trace.trace, [Boundary(), Boundary(depth=0)]).ok
    assert library.run("boundary", (visible, hosts.items("A", "B"))).outcome == Ok(
        hosts.edge_set(hosts.items(*(start + end for start, end, _ in hosts.from_card(visible)[1]
                                     if (start in ("A", "B")) != (end in ("A", "B"))))))


def _given_leaves(trace):
    if trace.given:
        yield trace
    else:
        for child in trace.children:
            yield from _given_leaves(child)


def test_promotion_requires_evidence_and_invalidates_after_world_change():
    lib = new_library()
    item = definitions()[0]
    lib.write(item)
    lib.check(item.name)
    lib.make_callable(item.name, [(hosts.route_raw(TINY, hosts.items("A", "B", "D")),)])
    with pytest.raises(PipelineError, match="requires verified"):
        lib.promote(item.name, Contract("valid checked route"))
    lib.world = replace(lib.world, constants={"changed": 1})
    assert lib.get(item.name).status == "callable"


def test_committed_export_and_ascii_notation(exported):
    stored = json.loads(export.EXPORT_PATH.read_text(encoding="utf-8"))
    assert stored == exported
    assert stored["decl"] == json.loads((Path(__file__).resolve().parents[3] /
        "worlds/decl/v2/roads@1.json").read_text(encoding="utf-8"))
    assert export.EXPORT_PATH.stat().st_size < 12_000_000
    assert stored["tower_source"] == "depth" and len(stored["ladder"]) == 5
    assert len({row["knobs"] for row in stored["ladder"]}) == 5
    assert stored["helpers"][0]["decl"] == "op boundary(g:Roads,X:List<Text>) -> Edges"
    assert stored["helpers"][0]["status"] == "promoted"
    assert stored["tags"]["visibility"] == "full"
    for item in stored["story"]:
        assert item["symbol"].isascii()
        if "decl" in item:
            assert item["decl"].isascii()
        assert all(example["text"].isascii() for example in item["examples"])


def test_story_sources_and_evaluated_expressions(library, exported):
    unsupported = {"Route", "Closure", "explore", "failures"}
    for card in exported["story"]:
        digest = export_util.body_sha256(library.get(card["name"]).body)
        assert card["body_sha256"] == digest
        if "ascii" in card:
            parsed = notation.parse_definition(card["ascii"])
            assert parsed.name == card["name"]
            assert parsed.layer == card["def_layer"]
            assert card["decl"].endswith(f" L{card['def_layer']}")
            assert card["ascii"] == card["decl"]
            assert export_util.source_matches(card["ascii"], digest)
        else:
            assert "decl" not in card
        assert card["design_text"] == card["design_decl"]
        for example in card["examples"]:
            if card["name"] in unsupported:
                assert "ascii" not in example
            else:
                assert notation.parse_expr(example["text"])
                assert example["ascii"] == example["text"]
