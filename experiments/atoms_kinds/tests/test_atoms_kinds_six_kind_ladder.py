"""Six-kind permission, evidence, and reproducibility checks."""

from dataclasses import replace

import pytest
from atoms_kinds.ascii import parse, render
from atoms_kinds.harness import analyze, run_episode, save
from atoms_kinds.policies import (
    ScriptedPolicy,
    bridge_definition,
    combinator_definition,
    frac_definition,
    law_definition,
    observation_definition,
    operation_definitions,
)
from atoms_kinds.tasks import generate
from atoms_kinds.world import GROUPS, make_library, pair_num_probe
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.library import PipelineError
from opulse.atoms.values import Bottom, Card, Ok


def candidates():
    return (frac_definition(), operation_definitions()[0], combinator_definition(),
            law_definition(), observation_definition(), bridge_definition())


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("definition", candidates(), ids=lambda definition: definition.kind)
def test_closed_kinds_are_refused_by_core_and_reported_as_feedback(group, definition):
    if definition.kind in GROUPS[group]:
        return
    library = make_library(group)
    with pytest.raises(PipelineError, match=f"kind {definition.kind} is closed"):
        library.write(replace(definition, layer=1))
    result = save(library, (definition,), (2, 4))[0]
    assert result["status"] == "refused"
    assert f"kind {definition.kind} is closed" in result["refusal"]


def test_public_pair_probe_never_reads_an_invalid_pair():
    assert pair_num_probe(Card("Pair", "pair", (3, 4))) == 3
    assert pair_num_probe(Card("Pair", "pair", (3,))) == Bottom("invalid")
    assert pair_num_probe(Card("Pair", "pair", (True, 2))) == Bottom("invalid")
    assert pair_num_probe(3) == Bottom("invalid")


def test_derived_observation_and_bridge_round_trip_through_ascii():
    for definition in (observation_definition(), bridge_definition()):
        source = render(definition)
        assert source.isascii()
        parsed, _ = parse(source + f"\nsave {definition.name}\nop solve(a: Int) -> Int = a")
        assert parsed[0].spec == definition.spec
        assert parsed[0].depends_on == definition.depends_on


def test_observation_and_bridge_have_scoped_pipeline_evidence():
    observations = make_library("K5")
    result = save(observations, (observation_definition(),), (1, 2))[0]
    assert result["status"] == "promoted" and result["scope"]["size"] == 78
    assert {"dependency", "facts_unchanged", "unfold_equivalence"} <= set(
        observations.get("?numerator").evidence.checks)
    assert observations.get("?numerator").evidence.scope["non_interference"] == "n/a"
    bridges = make_library("K6")
    assert save(bridges, (frac_definition(),), (1, 2))[0]["status"] == "promoted"
    result = save(bridges, (bridge_definition(),), (1, 2))[0]
    assert result["status"] == "promoted"
    assert result["scope"]["pairs_checked"] == result["scope"]["size"] * 2
    assert "commutes" in bridges.get("~to_frac").evidence.checks
    assert bridges.derived_world().scopes()["~to_frac"] == bridges.get("~to_frac").evidence.scope


@given(numerator=st.integers(-6, 6), denominator=st.integers(1, 6))
@settings(max_examples=12, deadline=None)
def test_derived_observation_only_reports_public_numerator(numerator, denominator):
    library = make_library("K5")
    save(library, (observation_definition(),), (1, 2))
    pair = Card("Pair", "pair", (numerator, denominator))
    assert library.run("?numerator", (pair,)).outcome == Ok(numerator)
    assert library.run("?numerator", (Card("Pair", "pair", (numerator, 1)),)).outcome == Ok(numerator)


def test_scripts_use_their_new_kinds_and_are_deterministic():
    stages = ([generate(1)[0]], [generate(2)[0]])
    for group, policy, kind in (("K5", "observation", "observation"),
                                ("K6", "bridge", "bridge")):
        first = run_episode(ScriptedPolicy(policy), group, 0, stages, max_attempts=1)
        assert first == run_episode(ScriptedPolicy(policy), group, 0, stages, max_attempts=1)
        records, prompts = first
        assert all(row["correct"] for row in records)
        assert kind in records[0]["reused"]
        assert any(item["kind"] == kind and item["status"] == "promoted"
                   for item in records[0]["statuses"])
        assert "Open kinds: " in prompts[0]["prompt"]
        result = analyze(records, resamples=2)
        assert result["descriptive_secondary"][f"{group}-{'K4' if group == 'K5' else 'K5'}"]["decision"] == "diagnostic"


def test_first_prompts_differ_only_in_open_kinds_sentence():
    stages = ([generate(1)[0]], [])
    prompts = [run_episode(ScriptedPolicy("operations"), group, 0, stages,
                           max_attempts=1)[1][0]["prompt"] for group in GROUPS]
    for group, prompt in zip(GROUPS, prompts):
        assert prompt.replace("Open kinds: " + ", ".join(GROUPS[group]), "Open kinds: SAME") == (
            prompts[0].replace("Open kinds: " + ", ".join(GROUPS["K1"]), "Open kinds: SAME"))


@pytest.mark.parametrize("group", ("K1", "K2", "K3", "K4"))
@pytest.mark.parametrize("policy,kind", (("refused_observation", "observation"),
                                          ("refused_bridge", "bridge")))
def test_closed_kind_script_receives_core_refusal_as_feedback(group, policy, kind):
    rows, prompts = run_episode(ScriptedPolicy(policy), group, 0,
                                ([generate(1)[0]], []), max_attempts=2)
    assert any(f"kind {kind} is closed" in status["refusal"]
               for status in rows[0]["statuses"] if "refusal" in status)
    assert f"kind {kind} is closed" in prompts[1]["prompt"]
