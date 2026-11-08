"""Properties of generated libraries, exercised on their recorded verification domains."""

import copy
import os
from dataclasses import fields, is_dataclass, replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract
from opulse.atoms.values import FALSE, TRUE, Unknown, outcome_equal
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.gen_v2.audit import _domain, _object_call
from opulse.gen_v2.kinds import observations
from opulse.gen_v2.library import evidence_checked_scope
from opulse.gen_v2.notation import parse_term, print_node
from opulse.gen_v2.run import generate, load, save
from opulse.gen_v2.worlds import (
    action,
    circuits,
    dice,
    hidden,
    integer,
    lists,
    toy,
    toy_truth,
)


@pytest.fixture(scope="module")
def generated():
    worlds = (toy.gen_world(), toy_truth.gen_world(), lists.gen_world(),
              integer.gen_world(), action.gen_world(), dice.gen_world(),
              circuits.gen_world(), hidden.gen_world())
    targets = (24, 8, 10, 20, 4, 4, 2, 1)
    states = {world.name: generate(world, target, 7, per_kind_min=3 if world.name == "toy" else 0,
                                   layer_target=2)  # no time limit: the fixture must be deterministic
              for world, target in zip(worlds, targets)}
    assert {entry.kind for state in states.values() for entry in state.entries.values()} == {
        "object", "operation", "combinator", "observation"}
    return states


def _call(state, entry, args):
    record = state.library.get(entry.name)
    if entry.kind == "object":
        name, args = _object_call(record, args)
    else:
        name = entry.name
    return nodes.Call(name, tuple(nodes.Lit(arg) for arg in args))


def _assert_evidence_scope(state, entry, record, request):
    scope = dict(request.scope)
    scope["checked"] = {**evidence_checked_scope(request.domain), "by": (
        "library" if entry.name in state.library._library_checked else "generator")}
    fixed_ops = sorted(nodes.operation_literals(record.body)) if entry.kind == "combinator" else []
    if fixed_ops and entry.name in state.library._library_checked:
        scope["fixed_ops"] = fixed_ops
    attached = state.library._attached_hashes(record)
    if attached:
        scope["attached"] = attached
    assert record.evidence.scope == scope, entry.name


def _run(state, expression, trace=False):
    return kernel.evaluate(expression, scope=state.library.scope(),
                           limits=kernel.Limits(fuel=state.world.fuel),
                           dialect=state.library.dialect, trace=trace)


def _observed(state, entry, args, unfolded=False):
    record = state.library.get(entry.name)
    scope = observations._scope(state, record)
    history = observations._history(args, record.spec.memory)
    return observations._evaluate(state, record, history, scope, unfolded=unfolded)


@settings(max_examples=24, deadline=None)
@given(world_index=st.integers(min_value=0, max_value=7),
       entry_index=st.integers(min_value=0, max_value=1000),
       input_index=st.integers(min_value=0, max_value=10000))
def test_i1_named_calls_unfold_on_recorded_inputs(generated, world_index, entry_index, input_index):
    state = list(generated.values())[world_index]
    entry = list(state.entries.values())[entry_index % len(state.entries)]
    domain = _domain(state, entry, state.library.get(entry.name))
    assert domain
    args = domain[input_index % len(domain)]
    if entry.kind == "observation":
        actual = _observed(state, entry, args)
        expanded = _observed(state, entry, args, unfolded=True)
        assert outcome_equal(actual[0], expanded[0]) and actual[1] == expanded[1]
        return
    expression = _call(state, entry, args)
    actual = _run(state, expression, trace=True)
    expanded = _run(state, kernel.inline(expression, state.library.scope()))
    assert not isinstance(actual.outcome, Unknown)
    assert outcome_equal(actual.outcome, expanded.outcome)
    assert actual.steps == expanded.steps
    leaves = flatten_calls(actual.trace, Boundary.unfold_all())
    assert all(call.given for call in leaves)
    assert sum(call.steps for call in leaves) + actual.jumps == actual.work
    assert actual.work <= actual.steps


@settings(max_examples=20, deadline=None)
@given(world_index=st.sampled_from((0, 2, 4, 5, 6, 7)), first=st.integers(min_value=0, max_value=1000),
       count=st.integers(min_value=1, max_value=3), input_index=st.integers(min_value=0, max_value=1000),
       depth=st.one_of(st.none(), st.integers(min_value=0, max_value=8)),
       open_index=st.integers(min_value=0, max_value=1000),
       keep_index=st.integers(min_value=0, max_value=1000),
       kinds=st.sets(st.sampled_from(("object", "operation", "combinator", "observation"))))
def test_i2_boundaries_only_change_visibility(generated, world_index, first, count, input_index,
                                               depth, open_index, keep_index, kinds):
    state = list(generated.values())[world_index]
    eligible = [entry for entry in state.entries.values() if entry.kind != "observation"]
    calls = []
    for offset in range(count):
        entry = eligible[(first + offset) % len(eligible)]
        domain = _domain(state, entry, state.library.get(entry.name))
        calls.append(_call(state, entry, domain[(input_index + offset) % len(domain)]))
    expression = calls[-1]
    for index, call in reversed(list(enumerate(calls[:-1]))):
        expression = nodes.Let(f"unused_{index}", call, expression)
    run = _run(state, expression, trace=True)
    unfolded = _run(state, kernel.inline(expression, state.library.scope()))
    assert outcome_equal(run.outcome, unfolded.outcome)
    assert run.steps == unfolded.steps
    names = list(state.entries)
    boundary = Boundary(depth=depth, open_names=frozenset({names[open_index % len(names)]}),
                        keep_names=frozenset({names[keep_index % len(names)]}),
                        kinds=frozenset(kinds))
    check = unfold_equivalent_calls(run.trace, [Boundary(), boundary, Boundary.unfold_all()])
    assert check.ok, check.problems


@settings(max_examples=16, deadline=None)
@given(entry_index=st.integers(min_value=0, max_value=1000),
       truth_index=st.integers(min_value=0, max_value=1000))
def test_i3_observing_never_changes_truth_or_hidden_facts(generated, entry_index, truth_index):
    state = generated["toy_truth"]
    entry = list(state.entries.values())[entry_index % len(state.entries)]
    record = state.library.get(entry.name)
    scope = observations._scope(state, record)
    arguments = observations._read_arguments(state, record, scope)
    truth = state.world.truth_states[(truth_index % (len(state.world.truth_states) // 2)) * 2]
    hidden_twin = state.world.truth_states[state.world.truth_states.index(truth) + 1]
    left_reads = observations._probe_values(state, record.spec.reads, truth, scope, arguments)
    right_reads = observations._probe_values(state, record.spec.reads, hidden_twin, scope, arguments)
    assert left_reads[2] is None and right_reads[2] is None
    assert left_reads[0] == right_reads[0]
    before_states = copy.deepcopy(state.world.truth_states)
    before_truth, before_twin = copy.deepcopy((truth, hidden_twin))
    left = _observed(state, entry, (truth,))
    right = _observed(state, entry, (hidden_twin,))
    assert outcome_equal(left[0], right[0])
    assert truth == before_truth and hidden_twin == before_twin
    assert state.world.truth_states == before_states


def test_catalogue_observation_does_not_mutate_truth(generated):
    catalogue = [state for name, state in generated.items() if not name.startswith("toy")]
    state, entry = next((state, entry) for state in catalogue for entry in state.entries.values()
                        if entry.kind == "observation")
    truth = copy.deepcopy(state.world.truth_states)
    arguments = state.requests[entry.name].domain[0]
    first = _observed(state, entry, arguments)
    second = _observed(state, entry, arguments)
    assert outcome_equal(first[0], second[0]) and first[1] == second[1]
    assert state.world.truth_states == truth


@settings(max_examples=20, deadline=None)
@given(world_index=st.integers(min_value=0, max_value=7),
       entry_index=st.integers(min_value=0, max_value=1000))
def test_i4_promotion_keeps_exact_evidence_and_contract(generated, world_index, entry_index):
    state = list(generated.values())[world_index]
    entry = list(state.entries.values())[entry_index % len(state.entries)]
    record = state.library.get(entry.name)
    request = state.requests[entry.name]
    assert record.status == "promoted"
    assert record.evidence.method in ("exhaustive", "bounded")
    _assert_evidence_scope(state, entry, record, request)
    assert record.evidence.scope["size"] == len(request.domain)
    assert record.contract is not None and record.contract.guarantees
    assert record.evidence.world_hash == state.library.world.world_hash()
    assert record.evidence.deps_hash == state.library._deps_hash(entry.name)
    probe = copy.copy(state.library)
    probe._definitions = dict(state.library.definitions)
    probe._definitions[entry.name] = replace(record, status="verified", contract=None,
                                              evidence=replace(record.evidence, method="sampled", seed=7))
    with pytest.raises(PipelineError, match="sampled"):
        probe.promote(entry.name, Contract("must be refused"))



def test_i4_promoted_content_identity(generated):
    record = generated["toy"].library.get("B1")
    assert record.evidence.content_hash == generated["toy"].library.content_hash("B1")


def test_i4_every_promoted_record_has_current_scope(generated):
    for state in generated.values():
        for entry in state.entries.values():
            record = state.library.get(entry.name)
            request = state.requests[entry.name]
            assert record.status == "promoted", entry.name
            assert record.evidence.method in ("exhaustive", "bounded"), entry.name
            _assert_evidence_scope(state, entry, record, request)
            assert record.evidence.scope["size"] == len(request.domain), entry.name
            assert record.contract is not None and record.contract.guarantees, entry.name
            assert record.evidence.world_hash == state.library.world.world_hash(), entry.name
            assert record.evidence.deps_hash == state.library._deps_hash(entry.name), entry.name


def test_deterministic_seed_and_bodies(generated):
    adapters = {module.__name__.rsplit(".", 1)[-1]: module.gen_world
                for module in (toy, toy_truth, lists, integer, action, dice, circuits, hidden)}
    for name, state in generated.items():
        first, second = (generate(adapters[name](), len(state.entries), 7,
                                  per_kind_min=3 if name == "toy" else 0, layer_target=2)
                         for _ in range(2))
        assert [(entry.name, first.library.get(entry.name).body) for entry in first.entries.values()] == [
            (entry.name, second.library.get(entry.name).body) for entry in second.entries.values()]


def test_i1_memoized_recursion_preserves_charged_steps():
    state = generate(toy.gen_world(), 22, 3, per_kind_min=0, layer_target=2, time_limit=8)
    memo = next(entry for entry in state.entries.values() if entry.move == "mode.memo")
    assert (5,) in state.requests[memo.name].domain
    expression = _call(state, memo, (5,))
    named = _run(state, expression, trace=True)
    unfolded = _run(state, kernel.inline(expression, state.library.scope()))
    assert outcome_equal(named.outcome, unfolded.outcome)
    assert named.steps == unfolded.steps
    assert named.work < named.steps
    assert sum(call.steps for call in flatten_calls(named.trace, Boundary.unfold_all())) + named.jumps == named.steps


def test_checkpoint_preserves_behaviour_on_recorded_domains(generated, tmp_path):
    for state in generated.values():
        path = tmp_path / f"{state.world.name}.json"
        save(state, path)
        restored = load(state.world, path)
        assert list(restored.entries) == list(state.entries)
        for entry in state.entries.values():
            record = state.library.get(entry.name)
            for args in _domain(state, entry, record):
                if entry.kind == "observation":
                    original = _observed(state, entry, args)
                    replayed = _observed(restored, entry, args)
                    assert outcome_equal(original[0], replayed[0]) and original[1] == replayed[1]
                else:
                    expression = _call(state, entry, args)
                    original = _run(state, expression)
                    replayed = _run(restored, expression)
                    assert outcome_equal(original.outcome, replayed.outcome)
                    assert original.steps == replayed.steps


def _bools(node):
    """The core node codec reads bool cards back as Python bools (the kernel treats both as the
    same truth value); compare bodies modulo that canonical form."""
    if node == TRUE:
        return True
    if node == FALSE:
        return False
    if isinstance(node, tuple):
        return tuple(_bools(item) for item in node)
    if is_dataclass(node):
        return replace(node, **{field.name: _bools(getattr(node, field.name))
                                for field in fields(node)})
    return node


def test_generated_bodies_json_round_trip(generated):
    for state in generated.values():
        for entry in state.entries.values():
            body = state.library.get(entry.name).body
            once = nodes.from_json(nodes.to_json(body))
            assert nodes.from_json(nodes.to_json(once)) == once
            assert once == _bools(body)


def test_generated_bodies_notation_round_trip(generated):
    for state in generated.values():
        for entry in state.entries.values():
            body = state.library.get(entry.name).body
            printed = print_node(body, state)
            assert printed.isascii()
            assert _bools(parse_term(printed, state)) == _bools(body), (state.world.name, entry.name, printed)


def test_notation_zero_argument_observation_call(generated):
    state = generated["toy_truth"]
    observation = next(name for name, entry in state.entries.items() if entry.kind == "observation")
    call = nodes.Call(observation, ())
    printed = print_node(call, state)
    assert printed == f"?{observation}{{}}"
    assert parse_term(printed, state) == call


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_larger_generated_library_invariants():
    state = generate(toy.gen_world(), 120, 7, per_kind_min=15, layer_target=8, time_limit=90)
    assert len(state.entries) >= 120
    from opulse.gen_v2.audit import audit

    report = audit(state, sample=20, seed=7)
    assert report.ok, report.failures
