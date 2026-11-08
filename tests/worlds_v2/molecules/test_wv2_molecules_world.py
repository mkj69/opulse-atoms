"""Depth reference, twelve pipeline cards, finite probes and committed export."""

import json
import os
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract, Definition, ObservationSpec
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.molecules import hosts
from opulse.worlds_v2.molecules.export import EXPORT_PATH, build_export, display
from opulse.worlds_v2.molecules.reference import canonical_card, design
from opulse.worlds_v2.molecules.story import (
    TOWER,
    build_library,
    definitions,
    verification_graphs,
)
from opulse.worlds_v2.molecules.world import (
    DECL_PATH,
    atoms,
    chain_spec,
    decl,
    new_library,
)


@pytest.fixture(scope="module")
def lib():
    return build_library()


@pytest.fixture(scope="module")
def exported():
    return json.loads(EXPORT_PATH.read_text(encoding="utf-8"))


@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1",
                    reason="fresh six-heavy export takes over 60 seconds")
def test_fresh_export_matches_committed_file(exported):
    assert build_export() == exported


def test_decl_roundtrip_and_given_graphs():
    data = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    assert {key: value for key, value in WorldDecl.from_dict(data).to_dict().items()
            if key != "open_kinds"} == data
    assert not validate(load(DECL_PATH))
    assert len(atoms()) == len(decl().operations)
    assert chain_spec().to_dict() == decl().combinators["given_rules"]["chain"]
    assert chain_spec().to_dict() == decl().combinators["library"][0]
    assert decl().params["max_heavy"] == 8 and decl().params["max_total"] == 32
    assert hosts.from_card(hosts.to_card(("C", "O"), ((0, 1),), (2, 1))) == (
        ("C", "O"), ((0, 1),), (2, 1))
    for count in (8,):
        graph = hosts.to_card(("C",) * count)
        assert len(hosts.from_card(graph)[0]) == count
        assert hosts.attach(graph, "C", 0) == values.Bottom("size")
    assert hosts.attach(hosts.to_card(("O",), hydrogen=(2,)), "H", 0) == values.Bottom("valence")
    assert hosts.link(hosts.to_card(("C", "C"), ((0, 1),)), 0, 1) == values.Bottom("edge")


def test_given_chain_unfolds_and_propagates_failure(lib):
    graph = hosts.to_card(("C",))
    combined = lib.run("chain", (kernel.FnRef("identity"), kernel.FnRef("identity"), graph))
    assert combined.outcome == values.Ok(graph) and combined.steps == 2
    full_oxygen = hosts.to_card(("O",), hydrogen=(2,))
    bad = lib.run("chain", (kernel.FnRef("identity"), kernel.FnRef("identity"), full_oxygen))
    assert bad.outcome == values.Ok(full_oxygen)
    disconnected = hosts.to_card(("C", "C"))
    failed = lib.run("chain", (kernel.FnRef("identity"), kernel.FnRef("saturate"), disconnected))
    assert failed.outcome == values.Bottom("invalid")


def test_pipeline_and_scope(lib):
    assert [lib.get(name).kind for name in TOWER] == [
        "object", "operation", "combinator", "observation", "observation", "operation",
        "observation", "combinator", "object", "operation", "combinator", "observation"]
    assert len(lib.derived_world().promoted) == len(definitions())
    for name in TOWER:
        definition = lib.get(name)
        assert definition.status == "promoted"
        assert definition.evidence.method in ("bounded", "exhaustive")
        assert definition.evidence.scope["size"] >= 50
        assert definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
        assert len(definition.evidence.scope["checked"]["sha256"]) == 64
        assert definition.contract and definition.cost.to_dict()
        if definition.kind == "observation":
            assert {"dependency", "facts_unchanged", "non_interference"} <= set(definition.evidence.checks)
        if definition.kind == "object" and name == "Molecule":
            assert {"canon_total", "canon_idempotent", "canon_keeps_valid"} <= set(definition.evidence.checks)
        if name == "Profile":
            assert "finite_values" in definition.evidence.checks
        if definition.kind in ("operation", "combinator"):
            assert "unfold_equivalence" in definition.evidence.checks
        if definition.kind == "combinator":
            assert definition.evidence.scope["fixed_ops"] == []
    assert lib.get("finish").layer == 5 and lib.get("candidates").layer == 6
    assert lib.get("Profile").layer == 1 and lib.get("ambiguity").layer == 2
    assert len(verification_graphs()) >= 65


def test_fresh_first_three_cards():
    fresh = build_library(first_three=True)
    assert [fresh.get(name).status for name in TOWER[:3]] == ["promoted"] * 3
    graph = hosts.to_card(("C", "O"), ((0, 1),))
    assert fresh.run("finish", (kernel.FnRef("identity"), graph)).outcome == fresh.run(
        "saturate", (graph,)).outcome


def test_molecule_constructor_rejects_invalid_graphs(lib):
    forged = values.Card("Graph", "val", hosts.to_card(("O",), hydrogen=(3,)).fields)
    for graph in (hosts.to_card(("C", "C")), forged,
                  hosts.to_card(("C", "C"), ((0, 1), (0, 1)))):
        assert lib.run("Molecule.make", (graph,)).outcome == values.Bottom("invalid")


def test_forged_molecule_cannot_reach_refined_base(lib):
    disconnected = hosts.to_card(("C", "C"))
    for forged in (values.Card("Molecule", "val", (disconnected,)),
                   values.Card("Molecule", "fake", (disconnected,)),
                   values.Card("Molecule", "val", (1,))):
        assert lib.run("Molecule.base", (forged,)).outcome == values.Bottom("invalid")


def test_profile_constructor_rejects_invalid_fields(lib):
    for fields in ((1, 0, 0, 0), ("C1H4O0", "0", 0, 0),
                   ("C1H4O0", 0, values.Card("Profile", "profile", ()), 0)):
        assert lib.run("Profile.profile", fields).outcome == values.Bottom("invalid")


def test_ambiguity_rejects_forged_profile_key(lib):
    forged = values.Card("Profile", "profile", (1, 0, 0, 0))
    group = hosts.list_make(hosts.pair_make(forged, hosts.list_make("C/4/")))
    assert lib.run("ambiguity", (group,)).outcome == values.Bottom("invalid")


@settings(max_examples=12, deadline=None)
@given(st.lists(st.sampled_from(("C", "O")), min_size=1, max_size=2),
       st.lists(st.integers(min_value=0, max_value=1), min_size=2, max_size=2))
def test_random_saturation_unfolds_with_same_boundary(lib, labels, hydrogen):
    graph = hosts.to_card(labels, ((0, 1),) if len(labels) == 2 else (), hydrogen[:len(labels)])
    run = lib.run("saturate", (graph,), trace=True)
    expected = design().saturate(design().Graph(*hosts.from_card(graph))).code
    assert display(run.outcome.value) == expected
    result = unfold_equivalent(run.trace, [Boundary.unfold_all(), Boundary.unfold_none(),
                                           Boundary(depth=2)])
    assert result.ok, result.problems


def test_depth_reference_and_every_export_example(lib, exported):
    oracle = design()
    oracle.tests()
    reference = json.loads((DECL_PATH.parents[3] / "worlds/catalogue/depth/molecules.json").read_text(
        encoding="utf-8"))
    assert [row["layer"] for row in exported["story"]] == list(range(1, 13))
    assert [row["name"] for row in exported["story"]] == list(TOWER)
    for row, design_row, independent in zip(exported["story"], reference["tower"], oracle.evaluate()):
        assert oracle.display(independent) == design_row["value"]
        if row["name"] in ("candidates", "screen", "partition"):
            assert row["design_value"] == design_row["value"]
            assert row["examples"][0]["steps"] > 1
        else:
            assert display(values.decode_outcome(row["examples"][0]["outcome"]).value) == design_row["value"]
        assert row["kind"] == design_row["kind"] and row["def_layer"] == lib.get(row["name"]).layer
        for entry in row["examples"]:
            arguments = tuple(values.decode(value) for value in entry["inputs"])
            run_name = row["name"]
            if run_name in ("Molecule", "Profile"):
                run_name += ".make" if run_name == "Molecule" else ".profile"
            run = lib.run(run_name, arguments)
            assert values.outcome_equal(run.outcome, values.decode_outcome(entry["outcome"]))
            assert run.steps == entry["steps"]
            assert entry["trace"] is not None
    assert exported["story"][1]["examples"][1]["outcome"] == {"bottom": "invalid"}
    assert [task["answer"] for task in exported["showcase"]] == oracle.showcase()
    assert all(task["answer_checked"] for task in exported["showcase"])


def test_ambiguity_witnesses_are_real_canonical_molecules(lib, exported):
    entry = exported["story"][11]["examples"][0]
    groups = values.decode(entry["inputs"][0])
    for group in groups.fields:
        profile, codes = group.fields
        assert len(set(codes.fields)) == len(codes.fields)
        for code in codes.fields:
            graph = canonical_card(code)
            molecule = lib.run("Molecule.make", (graph,)).outcome.value
            assert display(molecule) == code
            assert lib.run("profile", (molecule,)).outcome == values.Ok(profile)


def test_full_graph_and_probe_invariants(lib):
    graph = hosts.to_card(("C", "C", "O"), ((0, 1), (1, 2)))
    before = graph
    molecule = lib.run("finish", (kernel.FnRef("identity"), graph)).outcome.value
    assert graph == before
    assert lib.run("formula", (molecule,)).outcome == values.Ok("C2H6O1")
    assert lib.run("oh_count", (molecule,)).outcome == values.Ok(1)
    assert lib.run("cycle_rank", (molecule,)).outcome == values.Ok(0)
    renamed = hosts.to_card(("O", "C", "C"), ((0, 1), (1, 2)))
    assert lib.run("saturate", (renamed,)).outcome == values.Ok(molecule)
    visible = hosts.atoms(graph)
    assert visible.fields[0].fields[2].fields == ("O", 0, 1)
    assert lib.run("saturate", (hosts.to_card(("C", "C")),)).outcome == values.Bottom("invalid")
    with pytest.raises(PipelineError):
        lib.promote("formula", Contract("promoting twice is not allowed"))


def test_unfold_boundaries_and_observation_access(lib):
    graph = hosts.to_card(("C", "O"), ((0, 1),))
    traced = lib.run("saturate", (graph,), trace=True)
    inlined = kernel.evaluate(kernel.inline(nodes.Call("saturate", (nodes.Lit(graph),)), lib.scope()),
                              scope=lib.scope())
    assert inlined.outcome == traced.outcome and inlined.steps == traced.steps
    result = unfold_equivalent(traced.trace,
                               [Boundary.unfold_all(), Boundary.unfold_none(),
                                Boundary(depth=2), Boundary(open_names=frozenset({"Molecule.make"}))])
    assert result.ok, result.problems
    assert lib.derived_world().extends == "molecules@1"
    assert all(definition.evidence.world_hash == lib.world.world_hash()
               for definition in lib.derived_world().promoted)

    unauthorized = new_library()
    body = nodes.Call("graph_edges", (nodes.Var("m"),))
    unauthorized.write(Definition("raw_edges", "observation", "invented", 1,
                                  ("graph_edges",), ObservationSpec("raw_edges", ("atoms",), body), body))
    with pytest.raises(PipelineError, match="truth"):
        unauthorized.check("raw_edges")


def test_committed_export_and_ascii(exported):
    assert json.loads(EXPORT_PATH.read_text(encoding="utf-8")) == exported
    assert EXPORT_PATH.stat().st_size < 3_000_000
    assert exported["tower_source"] == "depth" and len(exported["ladder"]) == 5
    assert len(exported["showcase"]) == 3
    assert set(exported["open_kinds"]) == {"object", "operation", "combinator", "observation"}
    forbidden = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\u211a-\u2124\U0001d400-\U0001d7ff]")

    def strings(value, field=""):
        if isinstance(value, dict):
            for name, member in value.items():
                if name == "notation3":  # Notation v3: the generated display block is not machine notation
                    continue
                yield from strings(member, name)
        elif isinstance(value, list):
            for member in value:
                yield from strings(member, field)
        elif isinstance(value, str) and not field.endswith("_zh"):
            yield value

    assert not [item for item in strings(exported) if forbidden.search(item)]


def test_export_symbols_and_traces(exported):
    assert exported["layer0"]["combinators"]["given"]["symbol"].startswith("@chain[")
    suffix = {"object": "<", "operation": "(", "combinator": "[", "observation": "{"}
    prefix = {"object": "", "operation": "", "combinator": "@", "observation": "?"}
    for row in exported["story"]:
        assert row["symbol"].startswith(prefix[row["kind"]] + row["name"] + suffix[row["kind"]])
        assert all(entry["trace"] for entry in row["examples"])


def test_story_notation_matches_evaluated_calls(exported, lib):
    from opulse.worlds_v2 import export_util

    assert {row["name"] for row in exported["story"] if "ascii" not in row} == {
        "Molecule", "saturate", "formula", "cycle_rank", "candidates", "oh_count",
        "Profile", "profile", "partition", "ambiguity",
    }
    for row in exported["story"]:
        digest = export_util.body_sha256(lib.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            parsed = notation.parse_definition(row["decl"])
            assert parsed.name == row["name"] and parsed.kind == row["kind"]
            assert parsed.layer == row["def_layer"]
            assert row["ascii"] == row["decl"]
            assert export_util.source_matches(row["ascii"], digest)
        else:
            assert not row.get("decl")
        assert row["design_text"] == row["design_decl"]
        for entry in row["examples"]:
            if row["kind"] in ("object", "combinator"):
                assert "ascii" not in entry
                continue
            expression = notation.parse_expr(entry["text"])
            assert expression.fn == row["name"]
            assert tuple(argument.value for argument in expression.args) == tuple(
                values.decode(argument) for argument in entry["inputs"])
            assert entry["ascii"] == entry["text"]
