"""Scoped laws in the optional plain-program K4 fraction arm."""

from dataclasses import replace
from pathlib import Path

import pytest
from atoms_kinds.ascii import AsciiSyntaxError, parse, render
from atoms_kinds.harness import analyze, run, run_episode, save
from atoms_kinds.policies import ScriptedPolicy, law_definition
from atoms_kinds.tasks import generate
from atoms_kinds.world import GROUPS, make_library
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.laws import (
    check_law,
    derivation_length,
    replay_rewrite,
    rewrite,
    verify_law,
)
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.spec import LawSpec
from opulse.atoms.values import TRUE, Ok

LAW_TEXT = ("law #add_comm: eq(add(a, b), add(b, a)) for a: Int, b: Int\n"
            "save #add_comm\nop solve(a: Int) -> Int = a")


def test_law_spec_binds_variables_and_round_trips_ascii():
    definition = law_definition()
    assert isinstance(definition.spec, LawSpec)
    assert tuple(name for name, _ in definition.spec.vars) == ("a", "b")
    parsed, _ = parse(LAW_TEXT)
    assert parsed == (replace(definition, layer=0),)
    assert render(definition).endswith("for a: Int, b: Int L1")
    assert parse(render(definition) + "\nsave #add_comm\nop solve(a: Int) -> Int = a")[0][0].body == definition.body
    with pytest.raises(AsciiSyntaxError):
        parse(LAW_TEXT.replace("eq(add(a, b), add(b, a))", "eq(a, b)").replace("a: Int, b: Int", "a: Nat"))
    with pytest.raises(AsciiSyntaxError):
        parse(LAW_TEXT + "\nby #add_comm")


def test_law_checker_refuses_unbound_variables():
    definition = law_definition()
    library = make_library("K4")
    assert check_law(definition, library) == []
    wrong = replace(definition, body=nodes.Call("eq", (nodes.Var("a"), nodes.Var("stray"))))
    assert "law body must equal its statement" in check_law(wrong, library)
    assert check_law(replace(definition, spec=replace(definition.spec, vars=(("a", "bool"), ("b", "int")))),
                     library)
    not_boolean = replace(definition, spec=replace(definition.spec, statement=nodes.Lit(1)),
                          body=nodes.Lit(1), depends_on=())
    assert "law statement must have boolean sort" in check_law(not_boolean, library)
    assert "law body must equal its statement" in check_law(replace(definition, body=nodes.Lit(TRUE)), library)


def test_law_library_rejects_invalid_binding_without_advancing_status():
    library = make_library("K4")
    definition = law_definition()
    invalid = replace(definition, spec=replace(definition.spec, vars=(("a", "bool"), ("b", "int"))))
    library.write(invalid)
    with pytest.raises(PipelineError):
        library.check(invalid.name)
    assert library.get(invalid.name).status == "written"


def test_scoped_verifier_rejects_counterexamples_and_invalid_domain():
    library = make_library("K4")
    bad, _ = parse("law #bad: eq(a, b) for a: Int, b: Int\nsave #bad\n"
                   "op solve(a: Int) -> Int = a")
    status = save(library, bad, (1, 2))[0]
    assert "law counterexample" in status["refusal"]
    definition = law_definition()
    request = VerifyRequest("bounded", ((1, 2, 3),), {"domain": "bad", "size": 1})
    assert "invalid law tuple" in verify_law(definition, make_library("K4"), request).problems[0]


def test_closed_laws_and_sampled_laws_cannot_promote():
    assert "law" not in GROUPS["K3"] and "law" in GROUPS["K4"]
    assert "kind law is closed" in save(make_library("K3"), (law_definition(),), (1, 2))[0]["refusal"]
    library = make_library("K4")
    definition = law_definition()
    library.write(definition)
    library.check(definition.name)
    library.make_callable(definition.name, ((2, 3),))
    verified = library.verify(definition.name, VerifyRequest("sampled", ((2, 3),),
                              {"domain": "one sampled pair", "size": 1}, seed=19))
    assert verified.evidence.method == "sampled"
    with pytest.raises(PipelineError, match="sampled evidence cannot be promoted"):
        library.promote(definition.name, verified.contract)


@given(left=st.integers(-6, 6), right=st.integers(-6, 6))
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_promoted_law_unfolds_with_same_truth_and_layer_zero_steps(left, right, promoted_law):
    library = promoted_law
    statement = law_definition().spec.statement
    opened = kernel.evaluate(statement, {"a": left, "b": right}, library.scope())
    assert opened.outcome == Ok(True)
    before = nodes.Call("add", (nodes.Lit(left), nodes.Lit(right)))
    after = rewrite(before, library.get("#add_comm"), library)
    replay = replay_rewrite(before, after, library.get("#add_comm"), library, {})
    assert derivation_length(replay) == 1
    assert kernel.evaluate(before, scope=library.scope()).outcome == kernel.evaluate(
        after, scope=library.scope()).outcome
    assert library.get("#add_comm").contract is not None


@pytest.fixture
def promoted_law():
    library = make_library("K4")
    status = save(library, (law_definition(),), (2, 3))[0]
    assert status["status"] == "promoted" and status["scope"]["size"] == 169
    return library


def test_scripted_k4_reports_law_without_rewrite_or_answer_change():
    stages = (generate(1), generate(2))
    k4, prompts = run_episode(ScriptedPolicy("object"), "K4", 0, stages, max_attempts=1)
    assert len(k4) == 40 and all(row["correct"] for row in k4)
    law = [status for status in k4[0]["statuses"] if status["kind"] == "law"]
    assert len(law) == 1 and law[0]["status"] == "promoted" and law[0]["scope"]["size"] == 169
    assert "Laws: law #NAME" in prompts[0]["prompt"]
    assert "by #NAME" in run_episode(ScriptedPolicy("object"), "K3", 0,
                                     stages, max_attempts=1)[1][0]["prompt"]
    analysis = analyze(k4, resamples=5)
    assert analysis["optional_secondary"]["decision"] == "diagnostic"
    assert analysis["groups"]["K4"]["laws"]["promoted"] == 1
    assert analysis["groups"]["K4"]["laws"]["rewrite_steps"] == 0


@pytest.mark.parametrize("policy,groups,episodes", [
    ("object", ("K1", "K2", "K3", "K4", "K5", "K6"), 2),
    ("operations", ("K1", "K2", "K3", "K4", "K5", "K6"), 2),
    ("refused", ("K1",), 1),
    ("observation", ("K5",), 1),
    ("bridge", ("K6",), 1),
])
def test_committed_kinds_dry_run_replays_byte_for_byte(tmp_path, policy, groups, episodes):
    name = f"dryrun_{policy}"
    replay = run(policy=policy, groups=groups, episodes=episodes, run_id=name, out=tmp_path)
    committed = Path(__file__).resolve().parents[1] / "runs" / name
    files = ("config.json", "results.jsonl", "prompts.jsonl", "summary.json",
             "analysis.json", "analysis.md", "cost_estimate.json")
    assert {path.name for path in committed.iterdir()} == set(files)
    for name in files:
        assert (replay / name).read_bytes() == (committed / name).read_bytes(), name
