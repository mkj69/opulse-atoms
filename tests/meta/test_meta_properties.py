"""Reproducible invariant properties (atoms-meta section 9)."""

from dataclasses import replace

import pytest
import strategies as S
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.observations import judge
from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.meta import code, engine, identity, notation
from opulse.meta import gen_code as G
from opulse.meta.vn import machine, reference
from opulse.meta.vn.report import report

PROPERTIES = settings(max_examples=100, deadline=None, derandomize=True)
EXPENSIVE = settings(max_examples=100, deadline=None, derandomize=True)
WORLD = "small-int-world/1"


def evaluated(program, args, fuel=None, boundary=None):
    return engine.call("eval", (program, code.lst(args)), G.scope(),
                       kernel.Limits(fuel=fuel), trace=boundary is not None)


@given(S.definitions())
@PROPERTIES
def test_canonical_idempotence(program):
    first = code.canonicalize(program)
    assert first == program
    assert code.canonicalize(first) == first
    assert code.code_hash(first) == code.code_hash(program)


@given(S.small_ints, st.text(alphabet="abcdefghijkl", min_size=1, max_size=8))
@PROPERTIES
def test_all_binder_alpha_renaming(amount, suffix):
    def build(param, let_name, rec_name, counter, accumulator, block_var, entry, end):
        blocks = n.Blocks(((block_var, n.Var(accumulator)),), entry,
                          ((entry, n.Block((), n.Jump(end))),
                           (end, n.Block(((block_var, n.Call("add", (
                               n.Var(block_var), n.Lit(1)))),), n.Halt(n.Var(block_var))))))
        loop = n.Rec(rec_name, (counter, accumulator),
                     n.Case(((n.Test(n.Call("is_zero", (n.Var(counter),))), blocks),),
                            n.Call(rec_name, (n.Call("sub", (n.Var(counter), n.Lit(1))),
                                              n.Var(accumulator)))),
                     (n.Lit(2), n.Var(let_name)), "fuel")
        return code.make_code("operation", G.SIG, (param,),
                              n.Let(let_name, n.Call("add", (n.Var(param), n.Lit(amount))), loop),
                              S.resolve())

    first = build("input", "temporary", "loop", "counter", "acc", "register", "start", "stop")
    second = build("input_" + suffix, "temporary_" + suffix, "loop_" + suffix,
                   "counter_" + suffix, "acc_" + suffix, "register_" + suffix,
                   "start_" + suffix, "stop_" + suffix)
    assert first == second
    assert code.code_hash(first) == code.code_hash(second)


@given(S.small_ints, st.text(alphabet="abcdefgh", min_size=1, max_size=6))
@PROPERTIES
def test_dependency_and_definition_names_are_not_identity(amount, suffix):
    def build(name, dependency_name, parameter):
        dependency = code.make_code("operation", G.SIG, (parameter,),
                                    n.Call("add", (n.Var(parameter), n.Lit(amount))), S.resolve())
        result = code.make_code("operation", G.SIG, ("input",),
                                n.Call(dependency_name, (n.Var("input"),)),
                                S.resolve(((dependency_name, dependency),)))
        return name, result

    first_name, first = build("named", "helper", "value")
    other_name, other = build("named_" + suffix, "helper_" + suffix, "value_" + suffix)
    assert first_name != other_name
    assert first == other
    assert code.code_hash(first) == code.code_hash(other)


@given(S.edits())
@PROPERTIES
def test_single_subtree_edit_changes_hash(example):
    program, change = example
    assert change is not None
    path, replacement = change
    changed = identity.edit(program, path, replacement)
    assert code.code_hash(changed) != code.code_hash(program)


@given(S.definitions(), S.arguments)
@EXPENSIVE
def test_quote_eval_unfold_steps(program, args):
    decoded = code.decode(program)
    scope = kernel.DictScope((*G.ATOMS, engine.eval_atom(G.ATOMS, G.DIGESTS),
                              engine.run_atom(G.ATOMS, G.DIGESTS)),
                             (decoded.main, *decoded.deps))
    direct = engine.call(decoded.main.name, args, scope, trace=True)
    reflected = evaluated(program, args, boundary=Boundary())
    literal = n.Call("eval", (n.Lit(program), n.Lit(code.lst(args))))
    unfolded = engine.evaluate(engine.inline(literal, G.scope()), scope=G.scope(), trace=True)
    assert (reflected.outcome, reflected.steps) == (direct.outcome, direct.steps)
    assert (unfolded.outcome, unfolded.steps) == (direct.outcome, direct.steps)

    def given_steps(frame):
        if frame.given and not frame.children and frame.steps:
            return [(frame.name, frame.inputs, frame.outcome, frame.steps)]
        return [step for child in frame.children for step in given_steps(child)]

    assert given_steps(reflected.trace) == given_steps(direct.trace) == given_steps(unfolded.trace)


@given(S.code_argument_cases())
@PROPERTIES
def test_code_valued_arguments_quote_eval_unfold_steps(case):
    program, args = case
    decoded = code.decode(program)
    scope = kernel.DictScope((*G.ATOMS, engine.eval_atom(G.ATOMS, G.DIGESTS),
                              engine.run_atom(G.ATOMS, G.DIGESTS)),
                             (decoded.main, *decoded.deps))
    direct = engine.call(decoded.main.name, args, scope)
    reflected = evaluated(program, args)
    literal = n.Call("eval", (n.Lit(program), n.Lit(code.lst(args))))
    unfolded = engine.evaluate(engine.inline(literal, G.scope()), scope=G.scope())
    assert (reflected.outcome, reflected.steps) == (direct.outcome, direct.steps)
    assert (unfolded.outcome, unfolded.steps) == (direct.outcome, direct.steps)


@given(S.definitions(), S.arguments, st.integers(0, 6))
@EXPENSIVE
def test_fuel_monotonicity_and_exactness(program, args, extra):
    result = evaluated(program, args)
    assert not isinstance(result.outcome, Unknown)
    at_or_above = evaluated(program, args, result.steps + extra)
    assert (at_or_above.outcome, at_or_above.steps) == (result.outcome, result.steps)
    if result.steps:
        below = evaluated(program, args, result.steps - 1)
        assert (below.outcome, below.steps) == (Unknown("fuel"), result.steps - 1)


@given(S.definitions(), S.arguments, st.integers(0, 8))
@EXPENSIVE
def test_run_budget_exact(program, args, budget):
    assert_run_budget_exact(program, args, budget)


@given(S.definitions(allow_nested_run=False), S.arguments, st.integers(0, 8))
@EXPENSIVE
def test_run_budget_exact_without_nested_run(program, args, budget):
    assert_run_budget_exact(program, args, budget)


def assert_run_budget_exact(program, args, budget):
    needed = evaluated(program, args)
    assert not isinstance(needed.outcome, Unknown)
    result = engine.call("run", (program, code.lst(args), budget), G.scope())
    expected = (Card("result", "out", (budget,)) if budget < needed.steps else
                Card("result", "ok", (needed.outcome.value,)) if isinstance(needed.outcome, Ok) else
                Card("result", "err", (needed.outcome.reason,)))
    assert result.outcome == Ok(expected)
    assert result.steps == min(needed.steps, budget)
    if budget >= needed.steps:
        larger = engine.call("run", (program, code.lst(args), needed.steps + 2), G.scope())
        assert (larger.outcome, larger.steps) == (result.outcome, result.steps)


def test_nested_run_zero_budget_regression():
    nested = code.make_code("operation", G.SIG, ("item",),
                            n.Call("add", (n.Var("item"), n.Lit(0))), S.resolve())
    program = code.make_code("operation", G.SIG, ("input",),
                             n.Let("marker", n.Call("run", (n.Lit(nested),
                                                             n.Lit(code.lst((0,))), n.Lit(0))),
                                   n.Var("input")), S.resolve())
    needed = evaluated(program, (0,))
    actual = engine.call("run", (program, code.lst((0,)), 0), G.scope())
    assert (needed.outcome, needed.steps) == (Ok(0), 0)
    assert (actual.outcome, actual.steps) == (Ok(Card("result", "ok", (0,))), 0)


@given(S.definitions(), S.arguments, st.integers(0, 4))
@EXPENSIVE
def test_run_outer_fuel_or_budget_tie(program, args, budget):
    needed = evaluated(program, args)
    if needed.steps <= budget:
        return
    tied = engine.call("run", (program, code.lst(args), budget), G.scope(),
                       kernel.Limits(fuel=budget))
    assert (tied.outcome, tied.steps) == (Ok(Card("result", "out", (budget,))), budget)
    if budget:
        outer_first = engine.call("run", (program, code.lst(args), budget), G.scope(),
                                  kernel.Limits(fuel=budget - 1))
        assert (outer_first.outcome, outer_first.steps) == (Unknown("fuel"), budget - 1)


@given(S.definitions(), S.arguments, S.boundaries)
@EXPENSIVE
def test_random_boundary_preserves_outcome_and_steps(program, args, boundary):
    plain = evaluated(program, args)
    traced = evaluated(program, args, boundary=boundary)
    decoded = code.decode(program)
    scope = kernel.DictScope((*G.ATOMS, engine.eval_atom(G.ATOMS, G.DIGESTS),
                              engine.run_atom(G.ATOMS, G.DIGESTS)),
                             (decoded.main, *decoded.deps))
    direct = engine.call(decoded.main.name, args, scope, trace=True)
    visible = flatten_calls(direct.trace, boundary)
    assert (plain.outcome, plain.steps) == (traced.outcome, traced.steps)
    assert (traced.trace.outcome, traced.trace.steps) == (plain.outcome, plain.steps)
    assert (direct.outcome, direct.steps) == (plain.outcome, plain.steps)
    assert Boundary.from_dict(boundary.to_dict()) == boundary
    assert visible == flatten_calls(direct.trace, Boundary.from_dict(boundary.to_dict()))
    assert all(not boundary.opens(frame, frame.path) for frame in visible)


@given(S.generated_codes())
@EXPENSIVE
def test_code_notation_round_trip(program):
    printed = notation.show_code(program, signature=True, deps=True, exact=True)
    assert notation.parse_code(printed) == program


@given(S.vn_states())
@PROPERTIES
def test_vn_notation_round_trip(state):
    card = machine.to_card(state)
    assert notation.parse_vn(notation.show_vn(card)) == card


@given(S.vn_states(), st.integers(0, 12))
@PROPERTIES
def test_vn_machine_matches_reference(state, fuel):
    status, final, steps = reference.run(state, fuel)
    actual = machine.run(machine.to_card(state), fuel)
    outcome = (Ok(machine.to_card(final)) if status == "ok" else
               Bottom("illegal") if status == "illegal" else Unknown("fuel"))
    assert (actual.outcome, actual.steps) == (outcome, steps)


def brute_self_modifying(state, fuel):
    current = state
    fetched = set()
    stores = []
    for _ in range(fuel):
        if current.halted:
            break
        addresses = (current.pc, (current.pc + 1) % len(current.mem))
        fetched.update(addresses)
        if current.mem[current.pc] == 3:
            address = current.mem[addresses[1]] % len(current.mem)
            stores.append((address, current.mem[address], current.a))
        try:
            current = reference.step(current)
        except reference.Illegal:
            break
    return any(address in fetched and before != after for address, before, after in stores)


@given(S.vn_states(), st.integers(0, 12))
@PROPERTIES
def test_vn_report_deterministic_and_self_modifying(state, fuel):
    first = report(state, fuel)
    assert first == report(state, fuel)
    assert first.self_modifying == brute_self_modifying(state, fuel)
    assert first.outcome == machine.run(machine.to_card(state), fuel).outcome


@given(S.vn_states(), st.integers(0, 12), st.booleans())
@PROPERTIES
def test_vn_grading_ignores_learner_probe_selection(state, fuel, answer):
    before = machine.to_card(state)
    full_report = report(state, fuel)
    full_view, full_verdict = S.vn_self_modifying_grade(
        state, fuel, ("pc", "a", "cell", "halted"), answer)
    partial_view, partial_verdict = S.vn_self_modifying_grade(
        state, fuel, ("pc", "halted"), answer)
    assert full_view != partial_view
    assert full_verdict == partial_verdict == judge(
        "full_state", full_report.self_modifying, answer)
    assert machine.to_card(state) == before


@given(st.lists(S.edits(), min_size=1, max_size=4),
       st.lists(st.sampled_from(("sampled", "bounded", "exhaustive")), min_size=1, max_size=4))
@EXPENSIVE
def test_ledger_evidence_is_hash_scoped_and_round_trips(examples, methods):
    ledger = identity.Ledger()
    contract = Contract("exact full-state equality", keeps=("inputs",))
    domain = tuple(range(5))
    for index, (program, _) in enumerate(examples):
        digest = ledger.add(program, WORLD, f"program{index}")
        method = methods[index % len(methods)]
        scope = {"size": len(domain), "domain": list(domain)}
        evidence = Evidence(method, scope,
                            seed=0 if method == "sampled" else None, world_hash=WORLD)
        if ledger.status(digest, WORLD) != "promoted":
            ledger.attach_evidence(digest, WORLD, evidence)
            if method == "sampled" and not any(
                    item.method in ("bounded", "exhaustive")
                    for item in ledger.record(digest, WORLD).evidence):
                with pytest.raises(identity.LedgerError, match="promotion needs exhaustive or bounded evidence"):
                    ledger.promote(digest, WORLD, contract)
                assert ledger.status(digest, WORLD) == "verified"
            assert replace(evidence, deps_hash=identity.dependency_hash(program)) in (
                ledger.record(digest, WORLD).evidence)
            if method == "sampled":
                evidence = Evidence("bounded", scope, world_hash=WORLD)
                ledger.attach_evidence(digest, WORLD, evidence)
            ledger.promote(digest, WORLD, contract)
        promoted = ledger.record(digest, WORLD)
        strongest, stored_contract = ledger.promoted(digest, WORLD)
        assert promoted.status == "promoted"
        assert strongest == promoted.evidence[-1]
        assert strongest.method in ("exhaustive", "bounded")
        assert strongest.scope == scope
        assert strongest.scope["size"] == len(strongest.scope["domain"]) == len(domain)
        assert promoted.contract == stored_contract == contract
    restored = identity.Ledger.from_dict(ledger.to_dict())
    assert restored.to_dict() == ledger.to_dict()
    for item in ledger.to_dict()["records"]:
        if item["status"] == "promoted":
            assert restored.record(item["hash"], item["world_hash"]) == ledger.record(
                item["hash"], item["world_hash"])
    original, change = examples[0]
    path, _ = change
    changed = identity.edit(original, path, 999)
    old_hash = code.code_hash(original)
    new_hash = ledger.add(changed, WORLD)
    assert new_hash != old_hash
    assert ledger.record(new_hash, WORLD).evidence == ()
    with pytest.raises(identity.LedgerError, match="promotion needs exhaustive or bounded evidence"):
        ledger.promote(new_hash, WORLD, contract)
    ledger.attach_evidence(new_hash, WORLD, Evidence("sampled", {"domain": list(domain),
                                                         "size": len(domain)}, seed=0,
                                                    world_hash=WORLD))
    with pytest.raises(identity.LedgerError, match="promotion needs exhaustive or bounded evidence"):
        ledger.promote(new_hash, WORLD, contract)
    with pytest.raises(ValueError, match="invalid evidence method or scope"):
        Evidence("bounded", {}, world_hash=WORLD)
    with pytest.raises(identity.LedgerError, match="evidence must match the record's world hash"):
        ledger.attach_evidence(new_hash, WORLD, Evidence("bounded", {"domain": list(domain),
                                                              "size": len(domain)}, world_hash="other-world"))
    assert ledger.record(new_hash, WORLD).status == "verified"
    assert ledger.record(new_hash, WORLD).contract is None
