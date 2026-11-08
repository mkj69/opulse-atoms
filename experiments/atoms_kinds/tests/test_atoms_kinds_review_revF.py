"""Independent reproductions for the six-kind experiment review."""

import json
from pathlib import Path

from atoms_kinds.ascii import parse, render
from atoms_kinds.harness import analyze, save
from atoms_kinds.policies import frac_definition, observation_definition
from atoms_kinds.world import make_library
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms.values import Bottom, Card, Ok


def test_k5_public_value_observation_records_inputs_and_non_interference_na():
    library = make_library("K5")
    definition = observation_definition()
    assert save(library, (definition,), (1, 2))[0]["status"] == "promoted"
    stored = library.get(definition.name)
    assert stored.spec.extra["inputs"] == [["p", "Pair"]]
    assert stored.spec.reads == ()
    assert "Pair.num" in stored.depends_on and "pair_num_probe" not in stored.depends_on
    evidence = repr((stored.evidence.checks, stored.evidence.scope))
    assert "non_interference" in evidence and "n/a" in evidence


def test_k5_public_value_observation_cannot_read_a_probe():
    definitions, _ = parse(
        "obs ?leaky{p} = ?pair_num_probe{p}\n"
        "save ?leaky\n"
        "op solve(a: Int) -> Int = a"
    )
    status = save(make_library("K5"), definitions, (1, 2))[0]
    assert status["status"] == "refused"
    assert "public observation cannot read probes" in status["refusal"]


def test_k5_observation_accepts_invented_pure_operation_on_public_value():
    library = make_library("K5")
    operation, _ = parse(
        "op increment(a: Int) -> Int = add(a, 1)\n"
        "save increment\n"
        "op solve(a: Int) -> Int = increment(a)"
    )
    assert save(library, operation, (2,))[0]["status"] == "callable"
    observation, _ = parse(
        "obs ?next{p} = increment(Pair.num(p))\n"
        "save ?next\n"
        "op solve(a: Int) -> Int = a"
    )
    assert save(library, observation, (2,))[0]["status"] == "promoted"


def test_k6_partial_bridge_preserves_declared_domain():
    definition, _ = parse(
        "bridge ~limited: Pair -> Frac = Frac.make(x) "
        "where lt(Pair.num(x), 4) "
        "commutes (Pair.num -> Frac.num, Pair.den -> Frac.den)\n"
        "save ~limited\n"
        "op solve(a: Int) -> Int = a"
    )
    assert definition[0].spec.domain is not None
    library = make_library("K6")
    assert save(library, (frac_definition(),), (1, 2))[0]["status"] == "promoted"
    status = save(library, definition, (1, 2))[0]
    assert status["status"] == "promoted"
    assert 0 < status["scope"]["pairs_checked"] < status["scope"]["size"] * 2
    assert status["scope"]["skipped"] > 0
    assert library.run("~limited", (Card("Pair", "pair", (5, 1)),)).outcome == Bottom("outside_domain")
    assert isinstance(library.run("~limited", (Card("Pair", "pair", (2, 1)),)).outcome, Ok)
    assert parse(f"{render(definition[0])}\n"
                 "save ~limited\nop solve(a: Int) -> Int = a")[0][0].spec == definition[0].spec


@given(st.integers(min_value=4, max_value=20))
@settings(max_examples=8, deadline=None)
def test_k6_partial_bridge_never_maps_outside_domain(numerator):
    library = make_library("K6")
    assert save(library, (frac_definition(),), (1, 2))[0]["status"] == "promoted"
    definition, _ = parse(
        "bridge ~limited: Pair -> Frac = Frac.make(x) "
        "where lt(Pair.num(x), 4) "
        "commutes (Pair.num -> Frac.num, Pair.den -> Frac.den)\n"
        "save ~limited\nop solve(a: Int) -> Int = a"
    )
    assert save(library, definition, (1, 2))[0]["status"] == "promoted"
    assert library.run("~limited", (Card("Pair", "pair", (numerator, 1)),)).outcome == Bottom("outside_domain")


def test_kinds_decision_requires_registered_episode_indexes():
    root = Path(__file__).resolve().parents[1] / "tasks"
    task_ids = {stage: [task["id"] for task in json.loads(
        (root / f"stage{stage}.json").read_text(encoding="utf-8"))["tasks"]]
        for stage in (1, 2)}
    records = [
        {"group": group, "episode": episode, "stage": stage, "task_id": task_id,
         "correct": group == "K2", "api_error": False, "invented": [], "reused": [],
         "length": 1, "steps": 1, "boundary_steps": 1, "statuses": []}
        for group, start in (("K1", 0), ("K2", 40))
        for episode in range(start, start + 40)
        for stage in (1, 2) for task_id in task_ids[stage]
    ]
    assert analyze(records, resamples=2)["primary"]["decision"] == "diagnostic"


def test_k6_refuses_bridge_without_commuting_interface():
    library = make_library("K6")
    assert save(library, (frac_definition(),), (1, 2))[0]["status"] == "promoted"
    definition, _ = parse(
        "bridge ~empty: Pair -> Frac = Frac.make(x)\n"
        "save ~empty\n"
        "op solve(a: Int) -> Int = a"
    )
    status = save(library, definition, (1, 2))[0]
    assert status["status"] == "refused"


def test_k6_analysis_reports_its_observations_as_well_as_bridges():
    results = Path(__file__).resolve().parents[1] / "runs/dryrun_bridge/results.jsonl"
    records = [json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()]
    assert any(status["kind"] == "observation" and status["status"] == "promoted"
               for row in records for status in row["statuses"])
    observations = analyze(records, resamples=2)["groups"]["K6"]["observations"]
    assert observations["promoted"] == 1
    assert observations["scopes"][0]["size"] == 78
