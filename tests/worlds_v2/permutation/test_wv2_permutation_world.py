"""Kernel, oracle, export, and boundary checks for twelve-card permutations."""

import importlib.util
import json
import os
import random
import re
from dataclasses import replace
from itertools import permutations
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.observations import observe
from opulse.atoms.spec import Contract
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.permutation import hosts
from opulse.worlds_v2.permutation.export import (
    EXPORT_PATH,
    build_export,
    expression_text,
    fresh_nodes,
    render,
    sample_nodes,
)
from opulse.worlds_v2.permutation.story import build_library, cycle, definitions, seq
from opulse.worlds_v2.permutation.world import decl, new_library

ROOT = Path(__file__).resolve().parents[3]
DESIGN_PATH = ROOT / "worlds/catalogue/depth/permutation.py"
NOT_ASCII = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\u211a-\u2124\U0001d400-\U0001d7ff]")


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def oracle():
    spec = importlib.util.spec_from_file_location("permutation_depth_test_oracle", DESIGN_PATH)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    return reference


def test_declaration_round_trip_and_codec():
    world = decl()
    assert WorldDecl.from_dict(world.to_dict()).to_dict() == world.to_dict()
    assert validate(load(ROOT / "worlds/decl/v2/permutation@1.json")) == []
    assert hosts.to_card(hosts.from_card(hosts.R)) == hosts.R
    assert hosts.to_card(range(1, 12)) == values.Bottom("invalid")
    assert hosts.swap(0, 12, hosts.I) == values.Bottom("invalid")
    assert hosts.swap(1, 12, hosts.I) == hosts.to_card((12, *range(2, 12), 1))


def test_invented_object_interfaces_are_available_at_verification():
    objects = {entry.name: entry.spec for entry in definitions() if entry.kind == "object"}
    assert objects["Cycle"].sealed and objects["Cycle"].interface == ("Cycle.make", "Cycle.base")
    assert objects["Subgroup"].sealed and objects["Subgroup"].interface == ("Subgroup.make", "Subgroup.base")


def test_object_dependencies_include_validity_and_canonicalization():
    entries = {entry.name: entry for entry in definitions()}
    assert {"length", "all_between", "distinct", "smallest"} <= set(entries["Cycle"].depends_on)
    assert {"contains", "at_perm", "sorted_unique", "is_perm"} <= set(entries["Subgroup"].depends_on)


def test_first_three_tower_cards_build_fresh():
    library = new_library()
    samples = {"Cycle": (seq(1, 2),), "rotate": (cycle(1, 2), hosts.I),
               "rotate_quad": (hosts.I,), "rotate_pair": (hosts.I,),
               "power": (kernel.FnRef("rotate_quad"), 2, hosts.I)}
    for entry in definitions():
        if entry.name not in samples:
            continue
        library.write(entry)
        library.check(entry.name)
        library.make_callable(entry.name, (samples[entry.name],))
    assert library.run("power", samples["power"]).outcome == values.Ok(
        library.run("rotate_quad", (library.run("rotate_quad", (hosts.I,)).outcome.value,)).outcome.value)


def test_twelve_depth_examples_and_independent_reference(library, oracle):
    design = json.loads(DESIGN_PATH.with_suffix(".json").read_text(encoding="utf-8"))
    tower, showcase = oracle.examples()
    stored = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert len(stored["story"]) == len(tower) == 12
    for source, value, item, (name, expression, args) in zip(design["tower"], tower, stored["story"], sample_nodes(library)):
        run = kernel.evaluate(expression, scope=library.scope())
        assert run.outcome == values.Ok(run.outcome.value)
        assert render(run.outcome.value) == oracle.render(value) == source["value"]
        assert values.decode_outcome(item["examples"][0]["outcome"]) == run.outcome
        assert item["examples"][0]["steps"] == run.steps
        assert item["examples"][0]["steps"] == item["examples"][0]["trace"]["steps"]
        assert item["examples"][0]["text"] == expression_text(expression)
        assert item["kind"] == source["kind"]
        assert item["layer"] == (library.get(name).layer if name == "center" else source["layer"])
        assert item["def_layer"] == library.get(name).layer
        assert args
    assert [entry["answer"] for entry in stored["showcase"]] == [oracle.render(value) for value in showcase]
    assert all(entry["answer_checked"] for entry in stored["showcase"])
    for entry in stored["story"]:
        assert entry["examples"][0]["text"] != entry["examples"][1]["text"]
        fresh = kernel.evaluate(fresh_nodes()[entry["name"]], scope=library.scope())
        assert entry["examples"][1]["text"] == expression_text(fresh_nodes()[entry["name"]])
        assert fresh.outcome == values.decode_outcome(entry["examples"][1]["outcome"])
        assert fresh.steps == entry["examples"][1]["steps"]


def test_export_and_ascii(library):
    stored = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert stored["tower_source"] == "depth"
    assert len(stored["ladder"]) == 5 and len(stored["showcase"]) == 3
    assert EXPORT_PATH.stat().st_size < 3_000_000

    def strings(item, name=""):
        if isinstance(item, dict):
            for key, value in item.items():
                if key == "notation3":  # Notation v3: the generated display block is not machine notation
                    continue
                yield from strings(value, key)
        elif isinstance(item, list):
            for value in item:
                yield from strings(value, name)
        elif isinstance(item, str) and not name.endswith("_zh"):
            yield item

    assert not [text for text in strings(stored) if NOT_ASCII.search(text)]
    for entry in stored["story"]:
        assert entry["status"] == "promoted"
        assert entry["symbol"].startswith({"object": entry["name"] + "<", "operation": entry["name"] + "(",
                                           "combinator": "@", "observation": "?"}[entry["kind"]])
        assert entry["evidence"]["scope"]["size"] >= 27
        assert entry["evidence"]["scope"]["checked"]["size"] == entry["evidence"]["scope"]["size"]
        assert entry["evidence"]["method"] == "bounded"
        assert entry["examples"][0]["text"]
        assert entry["title"] and entry["definition"]


def test_story_ascii_matches_stored_bodies(library):
    stored = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    for row in stored["story"]:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)


def test_story_declarations_are_core_source(library):
    stored = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert [entry["name"] for entry in stored["story"] if "ascii" in entry] == [
        "power", "cycles", "sign", "closure", "order", "center",
    ]
    for entry in stored["story"]:
        digest = export_util.body_sha256(library.get(entry["name"]).body)
        assert entry["body_sha256"] == digest
        if "ascii" in entry:
            declaration = notation.parse_definition(entry["ascii"])
            assert declaration.name == entry["name"]
            assert declaration.kind == entry["kind"]
            assert declaration.layer == entry["def_layer"]
            assert entry["decl"].endswith(f" L{entry['def_layer']}")
            assert entry["ascii"] == entry["decl"]
            assert export_util.source_matches(entry["ascii"], digest)
        else:
            assert "decl" not in entry
        assert entry["design_decl"] == entry["design_text"]


def test_parseable_examples_match_evaluated_expressions():
    stored = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    examples = {entry["name"]: entry["examples"] for entry in stored["story"]}
    expressions = {name: expression for name, expression, _ in sample_nodes(None)}
    fresh = fresh_nodes()
    for name, rows in examples.items():
        for row, expression in zip(rows, (expressions[name], fresh[name])):
            if "ascii" in row:
                assert row["ascii"] == row["text"]
                assert notation.parse_expr(row["text"]) == expression
    assert sum("ascii" in example for rows in examples.values() for example in rows) == 11


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="Set OPULSE_RUN_SLOW=1 for fresh full export")
def test_fresh_export_matches_committed():
    assert json.loads(EXPORT_PATH.read_text(encoding="utf-8")) == build_export()


def test_finite_group_laws_and_failure(library, oracle):
    states = [hosts.to_card((*items, *range(5, 13))) for items in permutations(range(1, 5))]
    for state in states:
        assert library.run("inverse", (state,)).outcome == values.Ok(hosts.to_card(oracle.inverse(state.fields)))
        assert library.run("compose", (state, hosts.I)).outcome == values.Ok(state)
        assert library.run("order", (state,)).outcome == values.Ok(oracle.order(state.fields))
    group = library.run("closure", (kernel.FnRef("compose_r"), kernel.FnRef("compose_s"), hosts.I)).outcome
    assert isinstance(group, values.Ok) and len(group.value.fields) == 24
    assert library.run("closure", (kernel.FnRef("reset"), kernel.FnRef("rotate_pair"), hosts.I)).outcome == values.Bottom("not_bijective")
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert exported["story"][7]["examples"][-1]["outcome"] == {"bottom": "not_bijective"}
    assert library.run("Cycle.make", (seq(2, 1),)).outcome == values.Bottom("invalid")


def test_subgroup_rejects_nonmembers_and_nonclosure(library):
    forged = values.Card("permutation", "cards", (1,) * 12)
    invalid = (seq(hosts.I, hosts.R), seq(1, 2), seq(hosts.I, forged),
               seq(hosts.S), seq(hosts.I, hosts.R, hosts.S), seq(),
               seq(*([hosts.I] * 4097)))
    for members in invalid:
        assert library.run("Subgroup.make", (members,)).outcome == values.Bottom("invalid")
    assert library.run("Subgroup.make", (seq(hosts.S, hosts.I),)).outcome == values.Ok(
        values.Card("Subgroup", "val", (seq(hosts.I, hosts.S),)))


def test_cards_and_learner_reject_forged_subgroups(library):
    forged_permutation = values.Card("permutation", "cards", (1,) * 12)
    malformed = (
        values.Card("Subgroup", "val"),
        values.Card("Subgroup", "val", (1,)),
        values.Card("Subgroup", "val", (seq(1),)),
        values.Card("Subgroup", "val", (seq(hosts.I, forged_permutation),)),
        values.Card("Subgroup", "val", (seq(hosts.I, hosts.R),)),
        values.Card("Subgroup", "val", (seq(hosts.S, hosts.I),)),
        values.Card("Subgroup", "val", (seq(hosts.I, hosts.I),)),
        values.Card("Subgroup", "val", (seq(hosts.I, hosts.S), seq(hosts.I, hosts.S))),
    )
    for group in malformed:
        assert hosts.cards(group) == values.Bottom("invalid")
        assert library.run("center", (group,)).outcome == values.Bottom("invalid")
        assert library.run("Subgroup.base", (group,)).outcome == values.Bottom("invalid")
    valid = values.Card("Subgroup", "val", (seq(hosts.I, hosts.S),))
    assert hosts.cards(valid) == seq(seq(*hosts.I.fields), seq(*hosts.S.fields))
    assert library.run("Subgroup.base", (valid,)).outcome == values.Ok(seq(hosts.I, hosts.S))


def test_cycle_rejects_invalid_positions_and_forged_cards(library):
    invalid = (seq(1), seq(1, 1), seq(13, 14), seq(2, 1),
               values.Card("Cycle", "val", (seq(1, 2),)))
    for positions in invalid:
        assert isinstance(library.run("Cycle.make", (positions,)).outcome, values.Bottom)


def test_forged_cycles_cannot_be_unboxed_or_rotated(library):
    for positions in (seq(1), seq(1, 1), seq(2, 1), seq(0, 13)):
        forged = values.Card("Cycle", "val", (positions,))
        assert library.run("Cycle.base", (forged,)).outcome == values.Bottom("invalid")
        assert library.run("rotate", (forged, hosts.I)).outcome == values.Bottom("invalid")
    assert library.run("Cycle.base", (cycle(1, 2),)).outcome == values.Ok(seq(1, 2))


@settings(max_examples=12, deadline=None)
@given(st.integers(min_value=1, max_value=4), st.integers(min_value=1, max_value=4))
def test_subgroup_boundary_invariance(library, first, second):
    if first == second:
        return
    generator = hosts.swap(first, second, hosts.I)
    arguments = (seq(generator, hosts.I),)
    run = library.run("Subgroup.make", arguments, trace=True)
    assert run.outcome == values.Ok(values.Card("Subgroup", "val", (seq(hosts.I, generator),)))
    check = unfold_equivalent_calls(run.trace, [Boundary.unfold_none(), Boundary.unfold_all()])
    assert check.ok, check.problems


def test_pipeline_boundaries_and_sealed_observations(library):
    randomizer = random.Random(81)
    for name in ("rotate", "compose", "closure", "conjugate"):
        definition = library.get(name)
        assert definition.status == "promoted"
        assert definition.evidence.world_hash == library.world.world_hash()
        assert definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
        if name == "closure":
            args = (kernel.FnRef("rotate_pair"), kernel.FnRef("swap34"), hosts.I)
        elif name == "rotate":
            args = (cycle(1, 2, 3), hosts.I)
        elif name == "compose":
            args = (hosts.R, hosts.S)
        else:
            args = (hosts.R, hosts.S)
        run = library.run(name, args, trace=True)
        check = unfold_equivalent_calls(run.trace, [Boundary.unfold_none(), Boundary.unfold_all(),
                                                    Boundary(depth=randomizer.randrange(1, 5))])
        assert check.ok, check.problems
        unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),
                                                   library.scope()), scope=library.scope())
        assert values.outcome_equal(run.outcome, unfolded.outcome) and run.steps == unfolded.steps
    for name in ("cycles", "sign", "order"):
        definition = library.get(name)
        state = hosts.S
        before = state
        observation = observe(definition, library, [state])[0]
        assert observation == library.run(name, (state,)).outcome
        assert state == before
        assert {"facts_unchanged", "non_interference", "dependency"} <= set(definition.evidence.checks)


def test_promotion_requires_real_evidence():
    library = new_library()
    entry = next(definition for definition in definitions() if definition.name == "Cycle")
    library.write(entry)
    library.check("Cycle")
    library.make_callable("Cycle", ((seq(1, 2),),))
    with pytest.raises(PipelineError):
        library.promote("Cycle", Contract("No verification."))
    assert library.get("Cycle").evidence is None
    assert replace(library.world, params={"positions": 11}).world_hash() != library.world.world_hash()
    domain = tuple((seq(first, second),) for first in range(1, 7) for second in range(first + 1, 8))
    library.verify("Cycle", VerifyRequest("bounded", domain, {"domain": "all 21 pairs in 1..7", "size": len(domain)}))
    library.account("Cycle")
    library.promote("Cycle", Contract("Canonical for checked pair inputs."))
    library.world = replace(library.world, params={"positions": 11})
    assert library.get("Cycle").evidence is None and library.get("Cycle").status == "callable"
