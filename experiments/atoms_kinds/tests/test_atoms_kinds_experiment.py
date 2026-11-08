"""Regression and property tests for the open-kinds experiment."""

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest
from atoms_kinds.ascii import (
    AsciiSyntaxError,
    display,
    expression,
    parse,
    render,
    signature,
)
from atoms_kinds.harness import (
    analyze,
    grade,
    run,
    run_episode,
    save,
    sealed_references,
)
from atoms_kinds.policies import (
    ScriptedPolicy,
    combinator_definition,
    expressions,
    frac_definition,
    fraction_helpers,
    normalize,
    operation_definitions,
)
from atoms_kinds.tasks import generate, reference
from atoms_kinds.tasks import main as tasks_main
from atoms_kinds.world import GROUPS, integer_atoms, make_library, make_world
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.atoms.boundary import Boundary
from opulse.atoms.kernel import FnRef
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok
from opulse.atoms.verify import unfold_equivalent


@pytest.fixture
def saved_object():
    library = make_library("K2")
    statuses = save(library, (frac_definition(),), (2, 4))
    assert statuses == [{"name": "Frac", "kind": "object", "status": "promoted"}]
    return library


def test_generators_are_frozen_and_disjoint():
    hashes = ("e935521cd8dd356616fbab510b25333e2e954b75a3b0e3299fb72f8a92de5d26",
              "b172cbe9be4eeb487c7cfa07bd1b8ac6b04ee8fa513a99252d2b0119e74906f7")
    for stage, expected in enumerate(hashes, 1):
        tasks = generate(stage)
        assert tasks == generate(stage)
        path = Path(__file__).resolve().parents[1] / "tasks" / f"stage{stage}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        assert json.loads(path.read_text(encoding="utf-8"))["tasks"] == tasks
        assert len(tasks) == (24 if stage == 1 else 16)
        assert all(task["statement"].endswith("= ... .") for task in tasks)
        assert all(len(task["public_examples"]) == 2 and len(task["hidden_cases"]) == 8 for task in tasks)
    assert not {task["id"] for task in generate(1)} & {task["id"] for task in generate(2)}


def test_generator_cli_writes_identical_files(tmp_path):
    tasks_main(["--out", str(tmp_path)])
    for stage in (1, 2):
        original = Path(__file__).resolve().parents[1] / "tasks" / f"stage{stage}.json"
        assert (tmp_path / original.name).read_bytes() == original.read_bytes()


@pytest.mark.parametrize("family,args,expected", [
    ("sum", [2, -4, 3, 6], [0, 1]),
    ("mixed", [-3, 2, -4], [-7, 2]),
    ("compare", [1, -2, 1, 3], [1]),
    ("dot", [1, 2, 2, 3, -1, 4, 4, -5], [8, 15]),
    ("average", [1, 2, 1, 3, 1, 4, 1, 6], [5, 16]),
])
def test_reference_examples(family, args, expected):
    assert reference(family, args) == expected


def test_world_same_atoms_and_different_open_kinds():
    assert set(GROUPS) == {"K1", "K2", "K3", "K4", "K5", "K6"}
    assert {atom.name for atom in integer_atoms()} == {"add", "sub", "mul", "div", "mod", "gcd", "eq", "lt"}
    worlds = [make_world(group) for group in GROUPS]
    assert all(world.operations == worlds[0].operations for world in worlds)
    assert [world.open_kinds for world in worlds] == [tuple(sorted(GROUPS[group])) for group in GROUPS]
    assert all(op.impl["host"].startswith("atoms_kinds.world:") and len(op.impl["digest"]) == 64
               for op in worlds[0].operations if op.name in {atom.name for atom in integer_atoms()})
    assert {op.name for op in worlds[0].operations if op.name.startswith("Pair.")} == {
        "Pair.pair", "Pair.num", "Pair.den"}
    with pytest.raises(ValueError, match="unknown group"):
        make_world("K7")


@pytest.mark.parametrize("operation,left,right,expected", [
    ("add", -3, 7, 4), ("sub", -3, 7, -10), ("mul", -3, 7, -21),
    ("div", -7, 3, -2), ("div", 7, 0, Bottom("div_zero")),
    ("mod", -7, 3, 2), ("mod", 7, 0, Bottom("div_zero")),
    ("gcd", -6, 4, 2), ("eq", 4, 4, True),
    ("eq", 4, 3, False),
    ("lt", 3, 4, True), ("lt", 4, 3, False),
])
def test_integer_atoms_exact(operation, left, right, expected):
    assert make_library("K1").run(operation, (left, right)).outcome == (
        expected if isinstance(expected, Bottom) else Ok(expected))


def test_ascii_round_trip_and_reject_json():
    definitions = operation_definitions()
    payload = "\n".join([*(render(item) for item in definitions),
                         *(f"save {item.name}" for item in definitions),
                         "op solve(arg0: Int, arg1: Int) -> Int = norm_num(arg0, arg1)"])
    parsed, (_, output, answer) = parse(payload)
    assert [(item.name, item.kind, item.body, item.depends_on) for item in parsed] == [
        (item.name, item.kind, item.body, item.depends_on) for item in definitions]
    assert output == "Int" and display(answer) == "norm_num(arg0, arg1)"
    assert render(definitions[0]).startswith("op norm_num(arg0: Int, arg1: Int) -> Int = ")
    assert render(frac_definition()).startswith("obj Frac = <num: Int, den: Int> where")
    assert render(combinator_definition()).startswith("comb @combine[f: (Int, Int) -> Int]")
    with pytest.raises(AsciiSyntaxError):
        parse('{"definitions": {}, "answers": []}')


@pytest.fixture
def parsed_scripted_k3_program():
    actor = ScriptedPolicy("object")
    actor.reset(group="K3", episode=0, seed=1000)
    return parse(actor.act({"task": generate(1)[0]}))


def test_ascii_object_declaration_compiles(parsed_scripted_k3_program):
    definitions, _ = parsed_scripted_k3_program
    assert definitions[0].kind == "object"


def test_ascii_combinator_declaration_compiles(parsed_scripted_k3_program):
    definitions, _ = parsed_scripted_k3_program
    assert definitions[1].kind == "combinator"


def test_ascii_operation_declarations_compile(parsed_scripted_k3_program):
    definitions, _ = parsed_scripted_k3_program
    assert [item.kind for item in definitions[2:]] == ["operation", "operation"]


def test_ascii_solve_output_sort_compiles(parsed_scripted_k3_program):
    _, (_, output, _) = parsed_scripted_k3_program
    assert output == "Pair"


def test_ascii_solve_answer_compiles(parsed_scripted_k3_program):
    _, (_, _, answer) = parsed_scripted_k3_program
    assert isinstance(answer, nodes.Call)


def test_ascii_combinator_application_compiles():
    assert expression("@combine[add](2, 3)") == nodes.Call(
        "@combine", (nodes.Lit(FnRef("add")),
                     nodes.Lit(2), nodes.Lit(3)))


def test_ascii_let_compiles():
    assert expression("let x = 2 in add(x, 1)") == nodes.Let(
        "x", nodes.Lit(2), nodes.Call("add", (nodes.Var("x"), nodes.Lit(1))))


def test_ascii_conditional_compiles():
    assert expression("if lt(2, 3) then 4 else 5") == nodes.Case(
        ((nodes.Test(nodes.Call("lt", (nodes.Lit(2), nodes.Lit(3)))), nodes.Lit(4)),),
        nodes.Lit(5))


def test_ascii_pair_literal_compiles():
    assert expression("Pair<2, 4>") == nodes.Call("Pair.pair", (nodes.Lit(2), nodes.Lit(4)))


def test_ascii_signature_compiles():
    assert signature("a: Int, b: Int") == ("a", "b")


def test_ascii_save_requires_a_declaration():
    with pytest.raises(AsciiSyntaxError, match="save"):
        parse("save ghost\nop solve() -> Int = 0")


def test_saved_fraction_helpers_match_independent_fraction_reference():
    library = make_library("K2")
    assert save(library, (frac_definition(),), (2, 4))[0]["status"] == "promoted"
    helpers = fraction_helpers()
    statuses = save(library, helpers, (2, 4))
    assert [row["status"] for row in statuses] == ["callable", "callable"]
    assert all(any(name.startswith("Frac.") for name in library.get(item.name).depends_on)
               for item in helpers)
    for numerator, denominator in ((2, 4), (-3, 6), (8, -12), (0, -2), (-6, -4)):
        expected = Fraction(numerator, denominator)
        assert library.run("fraction_num", (numerator, denominator)).outcome == Ok(expected.numerator)
        assert library.run("fraction_den", (numerator, denominator)).outcome == Ok(expected.denominator)


def test_ascii_solve_parameter_binding_and_let_scope():
    definitions, (names, sort, answer) = parse(
        "op solve(a: Int, b: Int) -> Pair = let a = add(a, 1) in Pair<a, b>")
    assert not definitions and names == ("a", "b") and sort == "Pair"
    assert answer == nodes.Let("a", nodes.Call("add", (nodes.Var("arg0"), nodes.Lit(1))),
                               nodes.Call("Pair.pair", (nodes.Var("a"), nodes.Var("arg1"))))


def test_ascii_operation_pair_sort():
    definitions, _ = parse("op make_pair(a: Int, b: Int) -> Pair = Pair<a, b>\n"
                           "save make_pair\nop solve(a: Int, b: Int) -> Pair = make_pair(a, b)")
    assert definitions[0].spec.output.sort == "Pair"


def test_ascii_open_kinds_refusal_reaches_core():
    actor = ScriptedPolicy("refused")
    actor.reset(group="K1", episode=0, seed=1000)
    definitions, _ = parse(actor.act({"task": generate(1)[0]}))
    statuses = save(make_library("K1"), definitions, (2, 4))
    assert statuses[0]["refusal"].startswith("kind object is closed")


@given(text=st.text(max_size=150))
@settings(max_examples=120, deadline=None)
def test_ascii_parser_only_raises_own_syntax_error(text):
    try:
        parse(text)
    except AsciiSyntaxError:
        pass


def test_core_refuses_closed_kinds_before_checking():
    with pytest.raises(PipelineError, match="kind object is closed"):
        make_library("K1").write(frac_definition())
    with pytest.raises(PipelineError, match="kind combinator is closed"):
        make_library("K2").write(combinator_definition())


def test_mirror_statuses_and_scope(saved_object):
    library = saved_object
    assert library.get("Frac").evidence.scope["size"] == 156
    assert "respects_canon" in library.get("Frac").evidence.checks
    assert library.derived_world().scopes()["Frac"]["size"] == 156
    assert library.run("Frac.num", (Card("Frac", "val", (Card("Pair", "pair", (2, 4)),)),)).outcome == Ok(1)
    assert library.run("Frac.num", (Card("Frac", "val", (Card("Pair", "pair", (2, 0)),)),)).outcome == Bottom("invalid")
    canonical = library.run("Frac.make", (Card("Pair", "pair", (2, 4)),)).outcome
    assert isinstance(canonical, Ok)
    assert library.run("Frac.num", (canonical.value,)).outcome == Ok(1)
    operations = make_library("K1")
    assert [row["status"] for row in save(operations, operation_definitions(), (1, 2))] == ["callable"] * 2
    comb = make_library("K3")
    assert save(comb, (combinator_definition(),), (1, 2))[0]["status"] == "promoted"


def test_fraction_refine_rejects_zero_and_seals_representation(saved_object):
    assert saved_object.run("Frac.make", (Card("Pair", "pair", (1, 0)),)).outcome == Bottom("invalid")
    body = nodes.Call("Frac.base", (nodes.Var("arg0"),))
    peek = Definition("peek", "operation", "invented", 2, ("Frac.base",),
                      OperationSpec("peek", "transform", (Edge("Frac"),), Edge("Pair"),
                                    "read sealed representation", extra={"input_names": ["arg0"]}), body)
    assert sealed_references(saved_object, {"Frac.base", "Frac.num"}) == ["Frac.base"]
    with pytest.raises(ValueError, match="private sealed operation"):
        grade(generate(1)[0], (nodes.Call("Frac.base", (nodes.Var("arg0"),)), nodes.Lit(1)),
              saved_object, 200_000)
    assert "private sealed operation" in save(saved_object, (peek,), (1, 2))[0]["refusal"]


def test_invalid_definition_allows_correcting_the_same_name():
    from dataclasses import replace

    library = make_library("K1")
    original = operation_definitions()[0]
    invalid = replace(original, body=nodes.Call("ghost", (nodes.Var("arg0"), nodes.Var("arg1"))),
                      depends_on=("ghost",))
    assert "unresolved call" in save(library, (invalid,), (1, 2))[0]["refusal"]
    assert original.name not in library.definitions
    assert save(library, (original,), (1, 2))[0]["status"] == "callable"
    assert "definition already exists" in save(library, (original,), (1, 2))[0]["refusal"]
    renamed = replace(original, name="norm_num_new", spec=replace(original.spec, name="norm_num_new"))
    assert save(library, (renamed,), (1, 2))[0]["status"] == "callable"


def test_exact_kernel_grader_rejects_wrong_or_unresolved(saved_object):
    task = generate(1)[0]
    correct = expressions(task["family"], use_object=True)
    assert grade(task, correct, saved_object, 200_000)[0]
    assert not grade(task, (nodes.Lit(0), nodes.Lit(1)), saved_object, 200_000)[0]
    with pytest.raises(ValueError, match="unknown operation"):
        grade(task, (nodes.Call("ghost"), nodes.Lit(1)), saved_object, 200_000)
    assert not grade(task, (nodes.Lit(1),), saved_object, 200_000)[0]
    with pytest.raises(ValueError, match="arity"):
        grade(task, (), saved_object, 200_000)


def test_observation_changes_no_judgment(saved_object):
    from dataclasses import replace

    task = generate(1)[0]
    answer = expressions(task["family"], use_object=True)
    correct = grade(task, answer, saved_object, 200_000)
    saved_object.world = replace(saved_object.world,
                                 observation={"truth": None, "show": {"input": "hidden", "result": "hidden"},
                                              "judge_view": "full_state"})
    assert grade(task, answer, saved_object, 200_000) == correct
    assert "observation" not in saved_object.world.open_kinds


def test_scripted_refusal_and_reuse():
    stages = (generate(1), generate(2))
    refused, prompts = run_episode(ScriptedPolicy("refused"), "K1", 0, stages, max_attempts=2)
    assert any("kind object is closed" in status["refusal"] for status in refused[0]["statuses"])
    assert "kind object is closed" in prompts[1]["prompt"]
    for group, policy in (("K1", "operations"), ("K2", "object"), ("K3", "object")):
        rows, _ = run_episode(ScriptedPolicy(policy), group, 0, stages, max_attempts=1)
        assert len(rows) == 40 and all(row["correct"] for row in rows)
        assert any(row["reused"] for row in rows if row["stage"] == 2)
        assert all(row["status"] == ("callable" if row["kind"] == "operation" else "promoted")
                   for row in rows[0]["statuses"])
        if group != "K1":
            assert {row["name"] for row in rows[0]["statuses"] if row["kind"] == "operation"} == {
                "fraction_num", "fraction_den"}
            assert any("fraction_num" in row["prompt"] for row in _ if row["stage"] == 2)
            assert all("object" in row["reused"] and "operation" in row["reused"]
                       for row in rows if row["stage"] == 2)


def test_task_statements_are_visible_and_identical_across_arms():
    stages = (generate(1), generate(2))
    first = {}
    for group in GROUPS:
        _, prompts = run_episode(ScriptedPolicy("operations"), group, 0, stages, max_attempts=1)
        first[group] = {row["task_id"]: row["prompt"] for row in prompts}
    for task in (*stages[0], *stages[1]):
        assert all(task["statement"] in first[group][task["id"]] for group in GROUPS)
        assert "Open kinds: " in first["K1"][task["id"]]


def test_run_resume_and_analysis(tmp_path):
    path = run(policy="operations", groups=("K1",), episodes=1, run_id="offline", out=tmp_path, max_attempts=1)
    original = (path / "results.jsonl").read_bytes()
    assert len(original.splitlines()) == 40
    assert run(policy="operations", groups=("K1",), episodes=1, run_id="offline",
               out=tmp_path, max_attempts=1, resume=True) == path
    assert (path / "results.jsonl").read_bytes() == original
    with pytest.raises(ValueError, match="resume config mismatch"):
        run(policy="object", groups=("K1",), episodes=1, run_id="offline",
            out=tmp_path, max_attempts=1, resume=True)
    summary = analyze([json.loads(line) for line in original.splitlines()], 20)
    assert summary["primary"]["decision"] == "diagnostic"
    checkpoint = path / "episodes.jsonl"
    config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    old_prompts = [json.loads(line) for line in (path / "prompts.jsonl").read_text(encoding="utf-8").splitlines()]
    checkpoint.write_text(json.dumps({"config": config}) + "\n" + json.dumps({
        "group": "K1", "episode": 0,
        "records": [json.loads(line) for line in original.splitlines()], "prompts": old_prompts}) + "\n",
                          encoding="utf-8")
    run(policy="operations", groups=("K1", "K2"), episodes=1, run_id="offline",
        out=tmp_path, max_attempts=1, resume=True)
    assert (path / "results.jsonl").read_bytes().splitlines()[:40] == original.splitlines()
    assert len((path / "results.jsonl").read_bytes().splitlines()) == 80


@given(numerator=st.integers(-500, 500), denominator=st.integers(-500, 500).filter(bool))
@settings(max_examples=35, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_normalization_and_unfold(saved_object, numerator, denominator):
    library = saved_object
    fraction = Fraction(numerator, denominator)
    outcome = library.run("Frac.make", (Card("Pair", "pair", (numerator, denominator)),), trace=True)
    assert outcome.outcome == Ok(Card("Frac", "val", (Card("Pair", "pair", (fraction.numerator, fraction.denominator)),)))
    assert unfold_equivalent(outcome.trace, [Boundary.unfold_all(), Boundary.unfold_none()]).ok


@given(numerator=st.integers(-100, 100), denominator=st.integers(-100, 100).filter(bool))
@settings(max_examples=30, deadline=None)
def test_property_operation_normalization(numerator, denominator):
    library = make_library("K1")
    save(library, operation_definitions(), (1, 2))
    fraction = Fraction(numerator, denominator)
    assert library.run("norm_num", (numerator, denominator)).outcome == Ok(fraction.numerator)
    assert library.run("norm_den", (numerator, denominator)).outcome == Ok(fraction.denominator)
    assert library.run("div", (5, 0)).outcome == Bottom("div_zero")
    assert len(normalize(nodes.Var("arg0"), nodes.Var("arg1"))) == 2


@given(left=st.integers(-12, 12), left_den=st.integers(-9, 9).filter(bool),
       right=st.integers(-12, 12), right_den=st.integers(-9, 9).filter(bool))
@settings(max_examples=12, deadline=None)
def test_property_observation_independence_and_scope(left, left_den, right, right_den):
    from dataclasses import replace

    library = make_library("K2")
    save(library, (frac_definition(),), (2, 4))
    fraction = Fraction(left, left_den) + Fraction(right, right_den)
    task = {"family": "sum", "hidden_cases": [{"args": [left, left_den, right, right_den],
                                                "expected": [fraction.numerator, fraction.denominator]}]}
    answer = expressions("sum", use_object=True)
    assert grade(task, answer, library, 200_000)[0]
    promoted = library.derived_world()
    assert promoted.scopes()["Frac"] == library.get("Frac").evidence.scope
    assert promoted.promoted[0].contract == library.get("Frac").contract
    library.world = replace(library.world, observation={"truth": None, "show": {"input": "none"},
                                                         "judge_view": "full_state"})
    assert grade(task, answer, library, 200_000)[0]
