"""Randomized syntax-tree checks of experiment kernel invariants."""

from copy import deepcopy
from dataclasses import replace

from atoms_mul.harness.env import TRACK
from atoms_mul.kernel import (
    Library,
    Ok,
    Unknown,
    check_program,
    evaluate,
    is_mul_equivalent,
    load_world,
)
from atoms_mul.kernel.core_backend import core_evaluate
from atoms_mul.kernel.core_library import CoreMirror
from atoms_mul.kernel.nodes import Call, Def, If, Lit, Program, Var
from hypothesis import event, example, given, settings
from hypothesis import strategies as st
from strategies_atoms_mul import aml_cases, nat_expressions

from opulse.atoms.library import exhaustive
from opulse.atoms.spec import Contract

BOUNDED = settings(max_examples=150, deadline=None, derandomize=True)


def split_program(program, names):
    """Store a dependency-closed subset and leave the rest local."""
    library = Library()
    if names:
        library.add_from_program(program, names, "previous-task")
    return Program(tuple(definition for definition in program.defs
                         if definition.name not in names), ()), library


@given(case=aml_cases(), args=st.tuples(st.integers(0, 20), st.integers(0, 20)),
       fuel=st.one_of(st.integers(0, 8), st.just(2000)))
@BOUNDED
def test_unfold_saved_pasted_and_core(case, args, fuel):
    program, names, group = case
    world = load_world(group)
    assert not check_program(program, world, Library())
    pasted, library = split_program(program, names)
    assert not check_program(pasted, world, library)
    original = evaluate("solve", args, world=world, program=program, fuel=fuel)
    saved = evaluate("solve", args, world=world, program=pasted, library=library, fuel=fuel)
    event(type(original.outcome).__name__)
    assert (saved.outcome, saved.steps) == (original.outcome, original.steps)


def test_failed_condition_is_nan_condition_in_both_kernels():
    program = Program((Def("solve", ("a", "b"),
                           If(Call("is_zero", (Call("sub", (Var("b"), Var("a"))),)),
                              Lit(1), Lit(2))),), ())
    world = load_world("B")
    run = evaluate("solve", (1, 0), world=world, program=program)
    assert core_evaluate("solve", (1, 0), world=world, program=program) == (
        run.outcome, run.steps)


@given(case=aml_cases(), args=st.tuples(st.integers(0, 20), st.integers(0, 20)),
       fuel=st.one_of(st.integers(0, 8), st.just(2000)))
@BOUNDED
@example(case=(Program((Def("solve", ("a", "b"),
                            If(Call("is_zero", (Call("sub", (Var("b"), Var("a"))),)),
                               Lit(1), Lit(2))),), ()), (), "B"), args=(1, 0), fuel=2000)
def test_random_aml_core_unfold_equivalence(case, args, fuel):
    program, names, group = case
    pasted, library = split_program(program, names)
    world = load_world(group)
    original = evaluate("solve", args, world=world, program=program, fuel=fuel)
    saved = evaluate("solve", args, world=world, program=pasted, library=library, fuel=fuel)
    assert core_evaluate("solve", args, world=world, program=program, fuel=fuel) == (
        original.outcome, original.steps)
    assert core_evaluate("solve", args, world=world, program=pasted,
                         library=library, fuel=fuel) == (saved.outcome, saved.steps)


@given(case=aml_cases(), args=st.tuples(st.integers(0, 20), st.integers(0, 20)),
       mask=st.integers(0, 15))
@BOUNDED
def test_random_boundaries_change_only_visible_cost(case, args, mask):
    program, names, group = case
    pasted, library = split_program(program, names)
    world = load_world(group)
    boundary = frozenset(definition.name for index, definition in enumerate(program.defs)
                         if mask & (1 << index))
    baseline = evaluate("solve", args, world=world, program=pasted, library=library,
                        fuel=1500)
    bounded = evaluate("solve", args, world=world, program=pasted, library=library,
                       boundary=boundary, fuel=1500)
    assert (bounded.outcome, bounded.steps, bounded.calls) == (
        baseline.outcome, baseline.steps, baseline.calls)
    if not boundary:
        assert bounded.boundary_steps == bounded.steps


def test_kept_definition_is_one_visible_step_even_when_it_costs_nothing():
    # Spec 10: a kept definition is shown as one step, so boundary_steps may exceed the
    # layer-0 steps when the definition itself performs no operation.
    program = Program((Def("solve", ("a", "b"), Var("a")),), ())
    run = evaluate("solve", (0, 0), world=load_world("B"), program=program,
                   boundary=frozenset({"solve"}))
    assert (run.steps, run.boundary_steps) == (0, 1)


@given(case=aml_cases(), args=st.tuples(st.integers(0, 20), st.integers(0, 20)),
       mask=st.integers(0, 15))
@BOUNDED
@example(case=(Program((Def("solve", ("a", "b"), Var("a")),), ()), (), "B"),
         args=(0, 0), mask=1)
def test_random_aml_boundary_cost_bound(case, args, mask):
    program, names, group = case
    pasted, library = split_program(program, names)
    boundary = frozenset(definition.name for index, definition in enumerate(program.defs)
                         if mask & (1 << index))
    run = evaluate("solve", args, world=load_world(group), program=pasted, library=library,
                   boundary=boundary, fuel=1500)
    kept_calls = sum(run.calls.get(name, 0) for name in boundary)
    assert 0 <= run.boundary_steps <= run.steps + kept_calls
    if not boundary:
        assert run.boundary_steps == run.steps


@given(case=aml_cases(), args=st.tuples(st.integers(0, 20), st.integers(0, 20)),
       fuel=st.integers(0, 30))
@BOUNDED
def test_fuel_monotonicity_and_determinism(case, args, fuel):
    program, _, group = case
    world = load_world(group)
    low = evaluate("solve", args, world=world, program=program, fuel=fuel)
    high = evaluate("solve", args, world=world, program=program, fuel=fuel + 30)
    assert low == evaluate("solve", args, world=world, program=program, fuel=fuel)
    assert low.steps <= fuel and high.steps <= fuel + 30
    if isinstance(low.outcome, Ok):
        assert (high.outcome, high.steps) == (low.outcome, low.steps)
    if low.outcome == Unknown("fuel"):
        event("fuel exhausted: next operation requires steps > fuel")
        assert low.steps == fuel
        assert high.outcome != Unknown("fuel") or high.steps > fuel


def test_zero_fuel_exhaustion_is_observed():
    program = Program((Def("solve", ("a", "b"), Call("add", (Var("a"), Var("b")))),), ())
    run = evaluate("solve", (1, 2), world=load_world("B"), program=program, fuel=0)
    assert run.outcome == Unknown("fuel") and run.steps == 0


def test_boundary_of_direct_calls_counts_top_level_operations():
    helper = Def("helper0", ("a", "b"), Call("succ", (Var("a"),)))
    solve = Def("solve", ("a", "b"), Call("add", (
        Call("helper0", (Var("a"), Var("b"))),
        Call("helper0", (Var("b"), Var("a"))))))
    run = evaluate("solve", (3, 4), world=load_world("B"),
                   program=Program((helper, solve), ()), boundary=frozenset({"helper0"}))
    assert run.boundary_steps == 3
    assert run.steps == 3


@given(case=aml_cases(), args=st.tuples(st.integers(0, 20), st.integers(0, 20)),
       delta=st.integers(-2, 2))
@BOUNDED
def test_observation_does_not_change_hidden_grading(case, args, delta):
    program, names, group = case
    pasted, library = split_program(program, names)
    world = load_world(group)
    outcome = evaluate("solve", args, world=world, program=pasted, library=library).outcome
    expected = outcome.value + delta if isinstance(outcome, Ok) else delta
    task = {"id": "hidden", "statement": "Compute the result.", "params": ["a", "b"],
            "public_examples": [{"args": [0, 0], "expected": 0}],
            "hidden_tests": [{"args": list(args), "expected": expected}]}
    before = deepcopy(task), deepcopy(library.to_json())

    full_runs, full_verdict = TRACK.grade(pasted, task, group, library, 200_000)
    assert full_verdict == (outcome == Ok(expected))
    for change in ("statement", "public_examples"):
        altered = deepcopy(task)
        altered[change] = "A different prompt" if change == "statement" else [
            {"args": [1, 1], "expected": -1}]
        visible = {key: altered[key] for key in TRACK.visible_fields}
        feedback = TRACK.feedback(pasted, visible, group, library, 200_000)
        prompt = TRACK.render_prompt(group, library, visible, [feedback, "changed feedback"], 200_000)
        assert "hidden_tests" not in prompt
        assert TRACK.grade(pasted, altered, group, library, 200_000) == (full_runs, full_verdict)
    assert (task, library.to_json()) == before


@given(candidate=st.one_of(
    st.tuples(st.just("B"), nat_expressions(())),
    st.tuples(st.just("A"), nat_expressions((), mul=True)),
    st.just(("A", Call("mul", (Var("a"), Var("b")))))))
@BOUNDED
def test_mul_equivalence_exactly_matches_independent_exhaustion(candidate):
    group, body = candidate
    world = load_world(group)
    program = Program((Def("candidate", ("a", "b"), body),), ())
    assert not check_program(program, world, Library())
    agrees = all(evaluate("candidate", (first, second), world=world,
                          program=program).outcome == Ok(first * second)
                 for first in range(16) for second in range(16))
    assert is_mul_equivalent("candidate", world=world, program=program)["equivalent"] is agrees


def test_promotion_evidence_is_scoped_not_global():
    """Agreement on 0..15 never claims agreement beyond that checked scope."""
    world = load_world("B")
    name = "invented_mul"
    product = If(Call("is_zero", (Var("b"),)), Lit(0),
                 Call("add", (Var("a"), Call(name, (Var("a"), Call("pred", (Var("b"),)))))))
    definition = Def(name, ("a", "b"), If(Call("lt", (Var("a"), Lit(16))), product,
                                            Lit(0)))
    program = Program((definition,), ())
    assert not check_program(program, world, Library())
    assert is_mul_equivalent(name, world=world, program=program) == {
        "equivalent": True, "method": "exhaustive", "scope": "a,b in [0,15]",
        "counterexample": None}
    assert evaluate(name, (16, 1), world=world, program=program).outcome != Ok(16)
    library = Library()
    entry, = library.add_from_program(program, [name], "scope-task")
    mirror = CoreMirror("B")
    report, = mirror.mirror([{"definition": entry, "mul_equivalent": True}])
    assert report["core_status"] == "promoted" and not report["problems"]
    evidence = report["evidence"]
    assert evidence["method"] == "exhaustive"
    assert evidence["scope"]["description"] == "a, b in 0..15"
    assert evidence["scope"]["size"] == 256
    promoted, = mirror.derived_world().promoted
    assert promoted.evidence.scope == mirror.derived_world().scopes()[name]
    assert "a, b in 0..15" in promoted.contract.guarantees
    assert "no state" in promoted.contract.guarantees


@given(limit=st.integers(1, 6), value=st.integers(0, 30))
@settings(max_examples=20, deadline=None, derandomize=True)
def test_random_aml_promotion_preserves_exact_checked_domain(limit, value):
    definition = Def("candidate", ("a", "b"), If(
        Call("lt", (Var("a"), Lit(limit))), Lit(value), Lit(value + 1)))
    program = Program((definition,), ())
    library = Library()
    entry, = library.add_from_program(program, ["candidate"], "scope-property")
    mirror = CoreMirror("B")
    report, = mirror.mirror([entry])
    assert report["core_status"] == "callable"
    request = exhaustive((range(limit), range(2)), f"a in 0..{limit - 1}, b in 0..1")
    mirror.library.verify("candidate", replace(request, reference=lambda a, b: value))
    mirror.library.account("candidate")
    mirror.library.promote("candidate", Contract("result on checked a and b only"))
    promoted, = mirror.derived_world().promoted
    assert promoted.evidence.scope == mirror.derived_world().scopes()["candidate"]
    assert mirror.library.get("candidate").cost.steps["over"] == promoted.evidence.scope
    assert "checked" not in request.scope
    assert promoted.evidence.scope["checked"]["size"] == len(request.domain)
    assert promoted.evidence.scope["checked"]["bounds"] == {
        "0": {"min": 0, "max": limit - 1}, "1": {"min": 0, "max": 1}}
    assert evaluate("candidate", (limit, 0), world=load_world("B"), program=program).outcome != Ok(value)
