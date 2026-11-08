"""Deep DFA tower: all cards, provenance, boundaries, exact design oracle."""

import json
import os
import random
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.library import PipelineError, bounded, checked_scope
from opulse.atoms.values import Bottom, Card, Ok, outcome_equal
from opulse.atoms.verify import unfold_equivalent
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.automata import hosts
from opulse.worlds_v2.automata.export import (
    build_export,
    example,
    expressions,
    extra_examples,
)
from opulse.worlds_v2.automata.story import build_library, oracle_module, small_machines
from opulse.worlds_v2.automata.world import DECL_PATH, atoms, decl

ROOT = Path(__file__).resolve().parents[3]
STORED = json.loads((ROOT / "docs/assets/data/worlds_v2/automata.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def library():
    return build_library()


def render(kind, value):
    if kind == "Pair":
        return f"Pair<{hosts.count(value.fields[0])},{hosts.count(value.fields[1])}>"
    if kind == "sync":
        return f"({value.fields[0]},{value.fields[1]})"
    return value.tag if isinstance(value, Card) and value.sort == "bool" else str(value)


def test_decl_roundtrip_and_given_atoms():
    assert not validate(load(DECL_PATH))
    assert decl().from_dict(decl().to_dict()).to_dict() == decl().to_dict()
    assert {key: value for key, value in decl().to_dict().items() if key != "open_kinds"} == json.loads(
        DECL_PATH.read_text(encoding="utf-8"))
    assert decl().to_dict()["lock"] == json.loads(DECL_PATH.read_text())["lock"]
    assert len(atoms()) == len(decl().operations) + len(decl().observation["probes"])
    assert decl().params["max_product_states"] == 20000


def test_all_primary_values_match_design(library):
    oracle = oracle_module()
    cases = expressions()
    assert len(STORED["story"]) == len(oracle.tower_results()) == 10
    for card, expected in zip(STORED["story"], oracle.tower_results()):
        run = kernel.evaluate(cases[card["name"]], scope=library.scope())
        assert isinstance(run.outcome, Ok), (card["name"], run.outcome)
        assert render(card["name"], run.outcome.value) == expected
        example = card["examples"][0]
        assert run.outcome == values.decode_outcome(example["outcome"])
        assert run.steps == example["steps"] > 0
        assert nodes.to_json(cases[card["name"]]) == example["expression"]
        assert example["trace"]["steps"] == run.steps
        assert card["status"] == "promoted"
        assert card["kind"] == library.get(card["name"]).kind
        assert card["def_layer"] == library.get(card["name"]).layer
        assert card["evidence"]["method"] == "bounded"
        assert card["evidence"]["scope"]["size"] >= 50
        assert card["cost"] == library.get(card["name"]).cost.to_dict()


def test_secondary_examples_against_independent_reference(library):
    oracle = oracle_module()
    expected = (
        "Pair<2,2>", "(1,1)", "true", "false",
        str(oracle.size(oracle.trim(oracle.combine(oracle.ends_a, oracle.no_bb, "and")))),
        str(oracle.distinct_count(oracle.refine(oracle.step,
            oracle.trim(oracle.combine(oracle.even_len, oracle.no_bb, "and"))))),
        str(oracle.size(oracle.minimize(oracle.combine(oracle.ends_a, oracle.even_len, "and")))),
        "true", "a", "true",
    )
    for card, answer in zip(STORED["story"], expected):
        run = kernel.evaluate(nodes.from_json(card["examples"][1]["expression"]), scope=library.scope())
        assert isinstance(run.outcome, Ok)
        assert render(card["name"], run.outcome.value) == answer


def test_failure_and_fresh_inputs(library):
    assert any("bottom" in item["outcome"] and item["outcome"]["bottom"] == "invalid"
               for card in STORED["story"] for item in card["examples"])
    for card in STORED["story"]:
        primary, fresh = card["examples"][:2]
        assert fresh["text"] != primary["text"]
        assert fresh["expression"] != primary["expression"]
        for item in card["examples"]:
            run = kernel.evaluate(nodes.from_json(item["expression"]), scope=library.scope())
            assert outcome_equal(run.outcome, values.decode_outcome(item["outcome"]))
            assert run.steps == item["steps"]


def test_pipeline_and_i1_i4(library):
    assert len(library.derived_world().promoted) == 12
    fixtures = hosts.depth_examples()
    pair_domain = bounded((small_machines(), (fixtures["ends_a"], fixtures["even_len"])),
                          "bounded: 50 two-state DFAs x 2 partner DFAs").domain
    assert library.get("Pair").evidence.scope["checked"] == checked_scope(pair_domain)
    assert all(definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
               for definition in library.derived_world().promoted)
    for card in STORED["story"]:
        definition = library.get(card["name"])
        assert definition.status == "promoted" and definition.evidence.checks
        assert definition.contract and definition.cost
    machines = hosts.depth_examples()
    cases = (("combine", (machines["ends_a"], machines["even_len"], "and")),
             ("empty_language", (machines["never_accept"],)),
             ("minimize", (machines["no_bb"],)),
             ("equivalent", (machines["mod7_a"], machines["mod7_a"])))
    rng = random.Random(7)
    for name, arguments in cases:
        run = library.run(name, arguments, trace=True)
        unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in arguments)),
                                                 library.scope()), scope=library.scope())
        assert outcome_equal(run.outcome, unfolded.outcome) and run.steps == unfolded.steps
        boundaries = [Boundary(), Boundary(depth=0), Boundary(depth=1),
                      Boundary(open_names=frozenset({name}))]
        if run.trace.children:
            boundaries.append(Boundary(open_paths=frozenset({(rng.randrange(len(run.trace.children)),)})))
        assertion = unfold_equivalent(run.trace, boundaries)
        assert assertion.ok, assertion.problems
        for boundary in boundaries:
            assert sum(node.steps for node in flatten_calls(run.trace, boundary)) <= run.steps
    before = machines["no_bb"]
    assert library.run("empty_language", (before,)).outcome == Ok(hosts.boolean(
        oracle_module().empty(oracle_module().no_bb)))
    assert before == machines["no_bb"]
    assert library.run("step", (before, 99, "a")).outcome == Bottom("invalid")
    assert library.run("combine", (before, machines["ends_a"], "bad")).outcome == Bottom("invalid")
    assert library.run("separate", (machines["mod7_a"], machines["mod7_a"])).outcome == Ok("none")
    assert library.run("separate", (machines["mod7_a"], machines["never_accept"])).outcome == Ok("")


def test_export_shape_and_answer_checks():
    assert len(json.dumps(STORED, ensure_ascii=False).encode("utf-8")) < 3_000_000
    assert STORED["tower_source"] == "depth"
    assert len(STORED["ladder"]) == 5 and len(STORED["showcase"]) == 3
    assert all(task["answer_checked"] for task in STORED["showcase"])
    assert [task["answer"] for task in STORED["showcase"]] == oracle_module().showcase_results()


def test_first_three_cards_build_fresh(library):
    primary = expressions()
    secondary = extra_examples()
    for card in STORED["story"][:3]:
        name = card["name"]
        for recorded, expression, text in ((card["examples"][0], primary[name], card["examples"][0]["text"]),
                                           (card["examples"][1], *secondary[name])):
            expected = example(expression, text, library)
            if "ascii" in recorded:
                expected["ascii"] = recorded["text"]
            assert recorded == expected


def test_story_ascii_matches_stored_bodies(library):
    for row in STORED["story"]:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)


def test_story_notation_is_parseable_and_tracks_computed_layers(library):
    # Round 6: an observation printed with subject {s} whose body reads another variable is not published.
    assert [card["name"] for card in STORED["story"] if "ascii" in card] == []
    assert "ascii" not in next(card for card in STORED["story"] if card["name"] == "equivalent")
    for card in STORED["story"]:
        digest = export_util.body_sha256(library.get(card["name"]).body)
        assert card["body_sha256"] == digest
        if "ascii" in card:
            parsed = notation.parse_definition(card["ascii"])
            assert parsed.name == card["name"]
            assert parsed.kind == card["kind"]
            assert parsed.layer == card["def_layer"]
            assert card["decl"].endswith(f" L{card['def_layer']}")
            assert card["ascii"] == card["decl"]
            assert export_util.source_matches(card["ascii"], digest)
        else:
            assert "decl" not in card
        assert card["design_text"] == card["design_decl"]


def test_parseable_examples_are_exact_evaluated_expressions():
    unrepresentable = {"Pair", "sync", "Trim", "refine"}
    for card in STORED["story"]:
        for item in card["examples"]:
            if card["name"] in unrepresentable:
                assert "ascii" not in item
                continue
            assert notation.parse_expr(item["text"]) == nodes.from_json(item["expression"])
            assert item["ascii"] == item["text"]


def test_symbols_text_and_example_cost_labels():
    for card in STORED["story"]:
        prefix = {"combinator": "@", "observation": "?"}.get(card["kind"], "")
        assert card["symbol"].startswith(prefix + card["name"])
        assert card["symbol"] != prefix + card["name"]
        assert card["cost_scope"].startswith("verified finite family")
        assert card["example_steps"]["max"] == max(item["steps"] for item in card["examples"])
        for item in card["examples"]:
            assert not item["text"].startswith("L" + str(card["layer"]) + " ")
            if "ascii" in item:
                assert item["ascii"] == item["text"]


def test_pair_constructor_rejects_invalid_fields(library):
    fixtures = hosts.depth_examples()
    left, right = fixtures["ends_a"], fixtures["even_len"]
    initial = hosts.make_row(hosts.start(left), hosts.start(right))
    valid = library.run("Pair.pair", (left, right, initial, 4)).outcome.value
    assert library.run("Pair.left", (valid,)).outcome == Ok(left)
    forged = Card("Pair", "pair", (left, right, initial, 4))
    assert library.run("Pair.left", (forged,)).outcome == Bottom("invalid")
    assert library.run("Pair.capacity", (forged,)).outcome == Bottom("invalid")
    assert library.run("Pair.size", (forged,)).outcome == Bottom("invalid")
    assert library.run("Pair.is_pair", (forged,)).outcome == Ok(False)
    invalid = ((left, right, initial, 3), (left, right, hosts.make_row(1, 0), 4),
               (left, right, hosts.make_row(0, 9), 4), (left, right, initial, True),
               (Card("automaton", "dfa", ()), right, initial, 4))
    for fields in invalid:
        assert library.run("Pair.pair", fields).outcome == Bottom("invalid")
        assert library.run("Pair.left", (Card("Pair", "pair", fields),)).outcome == Bottom("invalid")
    assert library.run("Pair.right", (Card("Pair", "pair", (left, right)),)).outcome == Bottom("invalid")


def test_trim_rejects_forged_and_invalid_base(library):
    machine = hosts.depth_examples()["ends_a"]
    trimmed = library.run("Trim.make", (machine,)).outcome.value
    assert library.run("Trim.base", (trimmed,)).outcome == Ok(machine)
    assert library.run("Trim.base", (Card("Trim", "val", (machine,)),)).outcome == Bottom("invalid")
    assert library.run("Trim.base", (Card("Trim", "val", ()),)).outcome == Bottom("invalid")
    for invalid in (Card("automaton", "dfa", ()), Card("automaton", "dfa", (0,)),
                    Card("automaton", "dfa", (1, 9, machine.fields[2], machine.fields[3]))):
        assert library.run("Trim.make", (invalid,)).outcome == Bottom("invalid")
    with pytest.raises(PipelineError, match="private object constructor"):
        library.run("Trim._pack", (machine,))


def test_observation_uses_only_granted_probes(library):
    definition = library.get("empty_language")
    assert set(definition.spec.reads) == {"start", "step", "final"}
    from opulse.atoms import nodes as n
    calls = {node.fn for node in n.walk(definition.body) if isinstance(node, n.Call)}
    probes = {probe["name"] for probe in library.world.observation["probes"]}
    assert calls & probes <= set(definition.spec.reads)


@settings(max_examples=12, deadline=None)
@given(start=st.integers(0, 1), finals=st.sets(st.integers(0, 1)),
       transitions=st.lists(st.integers(0, 1), min_size=4, max_size=4))
def test_random_small_dfa_unfold_and_boundaries(library, start, finals, transitions):
    machine = hosts.to_card(2, start, tuple(sorted(finals)),
                            ((transitions[0], transitions[1]), (transitions[2], transitions[3])))
    call = nodes.Call("empty_language", (nodes.Lit(machine),))
    run = library.run("empty_language", (machine,), trace=True)
    unfolded = kernel.evaluate(kernel.inline(call, library.scope()), scope=library.scope())
    assert outcome_equal(run.outcome, unfolded.outcome)
    assert run.steps == unfolded.steps
    assertion = unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0), Boundary(depth=1)))
    assert assertion.ok, assertion.problems


def test_export_strings_use_ascii_outside_chinese_fields():
    def check(item, path=(), chinese=False):
        if isinstance(item, dict):
            for key, value in item.items():
                check(value, path + (key,), chinese or key.endswith("_zh"))
        elif isinstance(item, list):
            for index, value in enumerate(item):
                check(value, path + (str(index),), chinese)
        elif isinstance(item, str) and not chinese:
            assert item.isascii(), path
    check({key: value for key, value in STORED.items() if key != 'notation3'})


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="set OPULSE_RUN_SLOW=1 to regenerate the full export")
def test_committed_export_equals_kernel_rebuild():
    assert STORED == build_export()
