"""Generic observations over sealed truth and state histories."""

import os
import random
from collections import Counter
from dataclasses import replace
from itertools import product
from time import monotonic

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Definition, Edge, ObservationSpec, OperationSpec
from opulse.atoms.values import Bottom, Ok, outcome_equal
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import admit, hook_for
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature
from opulse.gen_v2.kinds.observations import _evaluate, _probe_args
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.object import MOVES as OBJECT_MOVES
from opulse.gen_v2.moves.observation import (
    MOVES,
    _candidate,
    _join,
    _source_partition,
    _sources,
)
from opulse.gen_v2.moves.registry import discover_moves
from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import (
    action,
    automata,
    calendar,
    circuits,
    dice,
    geometry,
    grammar,
    hidden,
    integer,
    kitchen,
    lists,
    melody,
    molecules,
    permutation,
    pixels,
    rhythm,
    roads,
    shadows,
    text,
    toy,
    toy_truth,
    versions,
)
from opulse.gen_v2.worlds.classic import gen_world as classic_world


def state():
    world = toy_truth.gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))


def candidate(name, reads, body, memory=None, layer=1):
    definition = Definition(name, "observation", "invented", layer,
                            tuple(sorted(n.references(body))),
                            ObservationSpec(name, tuple(reads), body, memory), body)
    return Candidate(definition, Signature(("truth",), "int"), "obs.test")


def test_join_refines_two_independent_observations():
    current = state()
    first = candidate("q401", ("read_x",),
                      n.Call("lt", (n.Var("read_x"), n.Lit(2))))
    first.signature = Signature(("truth",), "bool")
    second = candidate("q402", ("read_y",),
                       n.Call("lt", (n.Var("read_y"), n.Lit(2))))
    second.signature = Signature(("truth",), "bool")
    assert isinstance(admit(current, first), Entry)
    assert isinstance(admit(current, second), Entry)
    first_source = ("q401", "bool", n.Call("q401"), ("read_x",))
    second_source = ("q402", "bool", n.Call("q402"), ("read_y",))
    partitions = (_source_partition(current, first_source),
                  _source_partition(current, second_source))
    assert len(set(zip(*partitions))) > max(len(set(partition)) for partition in partitions)
    joined = _join(current, random.Random(19))
    assert joined is not None
    assert joined.defn.spec.reads == ("read_x", "read_y")
    assert isinstance(admit(current, joined), Entry)
    assert current.entries[joined.defn.name].layer == 2
    joined_values = _source_partition(current, (joined.defn.name, "int",
                                                 n.Call(joined.defn.name), joined.defn.spec.reads))
    assert len(set(joined_values)) == len(set(zip(*partitions)))


def test_grant_act_hidden_truth_and_init_are_rejected():
    current = state()
    denied = candidate("q101", ("read_x", "no_such_probe"), n.Var("read_x"))
    assert admit(current, denied).stage == "check"
    act = candidate("q102", ("read_x",), n.Call("act", (n.Lit(current.world.truth_states[0]),)))
    assert admit(current, act).stage == "check"
    hidden = candidate("q103", ("read_x",), n.Call("hidden", (n.Lit(current.world.truth_states[0]),)))
    assert admit(current, hidden).stage == "check"
    bad_init = candidate("q104", ("read_x",), n.Var("memory"),
                         {"init": n.Call("read_x"), "step": n.Var("read_x")})
    assert admit(current, bad_init).stage == "check"
    hidden_reference = candidate("q107", ("read_x",),
                                 n.Let("operation", n.Lit(kernel.FnRef("hidden")), n.Var("read_x")))
    assert admit(current, hidden_reference).stage == "check"


def test_identical_truth_partitions_are_rejected():
    current = state()
    body = n.Call("lt", (n.Var("read_x"), n.Lit(2)))
    first = candidate("q105", ("read_x",), body)
    first.signature = Signature(("truth",), "bool")
    assert isinstance(admit(current, first), Entry)
    inverted = n.Case(((n.Test(body), n.Lit(False)),), n.Lit(True))
    second = candidate("q106", ("read_x",), inverted)
    second.signature = Signature(("truth",), "bool")
    rejected = admit(current, second)
    assert rejected.stage == "verify" and "same truth partition" in rejected.reason


def test_truth_unchanged_and_non_interference_obligations_really_run():
    current = state()
    first = current.world.truth_states[0]
    second = current.world.truth_states[1]
    honest = candidate("q111", ("read_x", "read_y"),
                       n.Call("add", (n.Var("read_x"), n.Var("read_y"))))
    assert isinstance(admit(current, honest), Entry)
    assert set(current.library.get("q111").evidence.checks) == {
        "dependency", "facts_unchanged", "non_interference", "unfold_equivalence"}
    assert current.requests["q111"].scope["reference"] == "none"
    assert first != second and first.fields[:3] == second.fields[:3]
    current = state()
    hidden = {"value": 0}

    def deceptive_probe(truth):
        hidden["value"] = truth.fields[3]
        return 0

    current.world.atoms = tuple(kernel.Atom("read_x", 1, deceptive_probe, kind="observation")
                                if atom.name == "read_x" else atom for atom in current.world.atoms)
    current.world.decl = replace(current.world.decl, operations=current.world.decl.operations +
                                 (OperationSpec("covert", "decide", (), Edge("int"), "covert"),))
    current.world.atoms += (kernel.Atom("covert", 0, lambda: hidden["value"]),)
    current.library = GenLibrary(current.world.decl, current.world.atoms)
    rejection = admit(current, candidate("q112", ("read_x",), n.Call("covert")))
    assert rejection.stage == "verify" and "non_interference" in rejection.reason

    current = state()

    class MutableTruth:
        def __init__(self, value):
            self.fields = [value, 0, 0, 0]

        def __eq__(self, other):
            return isinstance(other, MutableTruth) and self.fields == other.fields

    def mutating_probe(truth):
        truth.fields[0] += 1
        return truth.fields[0]

    current.world.sorts["truth"].values = tuple(MutableTruth(value) for value in range(4))
    current.world.atoms = tuple(kernel.Atom("read_x", 1, mutating_probe, kind="observation")
                                if atom.name == "read_x" else atom for atom in current.world.atoms)
    current.library = GenLibrary(current.world.decl, current.world.atoms)
    rejection = admit(current, candidate("q113", ("read_x",), n.Var("read_x")))
    assert rejection.stage in ("callable", "verify") and "facts_unchanged" in rejection.reason


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_memory_history_and_reproducible_moves():
    def generate(seed):
        def grow():
            current = state()
            rng = random.Random(seed)
            for index in range(320 if os.environ.get("OPULSE_GEN_SLOW") == "1" else 200):
                move = MOVES[index % len(MOVES)]
                proposal = move(current, rng)
                if proposal:
                    admit(current, proposal)
            return current
        return fast.deep(grow)

    first = generate(76)
    second = generate(76)
    assert [(entry.move, entry.layer, entry.fingerprint) for entry in first.entries.values()] == [
        (entry.move, entry.layer, entry.fingerprint) for entry in second.entries.values()]
    assert len(first.entries) >= (65 if os.environ.get("OPULSE_GEN_SLOW") == "1" else 45)
    assert first.max_layer("observation") >= (7 if os.environ.get("OPULSE_GEN_SLOW") == "1" else 6)
    assert {entry.move for entry in first.entries.values()} == {move.name for move in MOVES}
    memory = next(entry for entry in first.entries.values() if entry.move == "obs.memory")
    assert first.library.get(memory.name).spec.memory is not None
    assert isinstance(memory.examples[0][1], dict) and "ok" in memory.examples[0][1]
    assert memory.name in first.requests
    assert first.requests[memory.name].scope["history_length"] == 3
    assert first.requests[memory.name].scope["size"] == 84


def test_small_observation_moves_are_reproducible():
    def grow():
        current = state()
        rng = random.Random(76)
        for index in range(12):
            proposal = MOVES[index % len(MOVES)](current, rng)
            if proposal is not None:
                admit(current, proposal)
        return [(entry.name, entry.move, entry.depends_on) for entry in current.entries.values()]

    first = fast.deep(grow)
    assert first
    assert fast.deep(grow) == first


def test_finding_5_memory_histories_match_bounded_domain():
    current = state()
    step = n.Call("add", (n.Var("memory"), n.Var("read_x")))
    proposal = _candidate(current, "obs.memory", step, ("read_x",), "int",
                          {"init": n.Lit(0), "step": step})
    request = proposal.request
    indices = request.scope["history_state_indices"]
    selected = tuple(current.world.truth_states[index] for index in indices)
    assert request.method == "bounded" and request.seed is None
    assert request.domain == tuple(history for length in range(1, 4)
                                   for history in product(selected, repeat=length))
    hook = hook_for("observation")
    truncated = replace(request, domain=request.domain[:-1],
                        scope={**request.scope, "size": len(request.domain) - 1})
    with pytest.raises(ValueError, match="cover every enumerated state history"):
        hook.run(current, proposal, truncated)
    with pytest.raises(ValueError, match="bounded enumerated scope"):
        hook.run(current, proposal, replace(request, method="exhaustive"))
    with pytest.raises(ValueError, match="require a seed"):
        hook.run(current, proposal, replace(request, method="sampled"))
    assert isinstance(admit(current, proposal), Entry)
    sampled_state = state()
    sampled = _candidate(sampled_state, "obs.memory", step, ("read_x",), "int",
                         {"init": n.Lit(0), "step": step})
    sampled.request = replace(sampled.request, method="sampled", seed=17)
    rejected = admit(sampled_state, sampled)
    assert rejected.stage == "verify" and "sampled evidence cannot be promoted" in rejected.reason


def test_finding_6_memory_step_dependencies_count_in_layer():
    world = toy_truth.gen_world(("operation", "observation"))
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    from opulse.gen_v2.moves.operation import _candidate as operation_candidate

    previous = "add"
    for layer in range(1, 4):
        body = n.Call("add", (n.Var("x0"), n.Lit(5))) if layer == 1 else n.Call(
            "add", (n.Call(previous, (n.Var("x0"),)), n.Lit(2)))
        operation = operation_candidate(current, "test.deep", ("int",), "int", body)
        assert isinstance(admit(current, operation), Entry)
        previous = operation.defn.name
    deep = current.entries[previous]
    step = n.Call(deep.name, (n.Var("read_x"),))
    proposal = _candidate(current, "obs.memory", step, ("read_x",), "int",
                          {"init": n.Lit(0), "step": step})
    assert deep.name in proposal.defn.depends_on
    assert deep.name in n.references(proposal.defn.body)
    assert proposal.defn.layer == deep.layer + 1
    assert not hook_for("observation").check(proposal.defn, current.library)
    step_only = _candidate(current, "obs.memory", n.Var("memory"), ("read_x",), "int",
                           {"init": n.Lit(0), "step": step})
    assert deep.name in step_only.defn.depends_on
    assert step_only.defn.layer == deep.layer + 1
    assert isinstance(step_only.defn.body, n.Case)
    assert step_only.defn.body.arms == ((n.Always(), n.Var("memory")),)
    assert step_only.defn.body.default == step
    assert not hook_for("observation").check(step_only.defn, current.library)
    untracked = candidate("q599", ("read_x",), n.Var("memory"), proposal.defn.spec.memory)
    assert "memory.step dependencies must occur in the body" in hook_for("observation").check(
        untracked.defn, current.library)


def test_memory_dependency_arm_preserves_outcome_and_layer_zero_cost_on_entire_scope():
    current = state()
    body = n.Case(((n.Test(n.Call("is_pos", (n.Var("read_x"),))), n.Var("memory")),))
    step = n.Call("add", (n.Var("memory"), n.Var("read_x")))
    proposal = _candidate(current, "obs.memory", body, ("read_x",), "int",
                          {"init": n.Lit(0), "step": step})
    original = replace(proposal.defn, body=body, spec=replace(proposal.defn.spec, body=body))
    assert isinstance(proposal.defn.body, n.Case)
    assert proposal.defn.body.arms == ((n.Always(), body),)
    assert proposal.defn.body.default == step
    assert n.references(proposal.defn.body) == set(proposal.defn.depends_on)
    assert not hook_for("observation").check(proposal.defn, current.library)

    def compare():
        scope = current.library.scope()
        observed = set()
        for history in proposal.request.domain:
            for unfolded in (False, True):
                expected, expected_steps = _evaluate(current, original, history, scope, unfolded=unfolded)
                actual, actual_steps = _evaluate(current, proposal.defn, history, scope, unfolded=unfolded)
                assert outcome_equal(actual, expected)
                assert actual_steps == expected_steps
                observed.add(type(actual))
        return observed

    assert compare() == {Ok, Bottom}
    assert isinstance(admit(current, proposal), Entry)
    from opulse.gen_v2.audit import audit
    assert audit(current).ok


def test_observation_hook_refuses_other_unreachable_code():
    current = state()
    step = n.Call("inc", (n.Var("memory"),))
    proposal = _candidate(current, "obs.memory", n.Var("memory"), ("read_x",), "int",
                          {"init": n.Lit(0), "step": step})
    hook = hook_for("observation")
    altered = replace(proposal.defn, body=n.Case(((n.Always(), n.Var("memory")),), n.Lit(9)))
    altered = replace(altered, spec=replace(altered.spec, body=altered.body))
    assert "unrecognized unreachable observation code" in hook.check(altered, current.library)
    nested = n.Case(((n.Always(), n.Var("memory")),), n.Call("inc", (n.Var("memory"),)))
    altered = replace(proposal.defn, body=n.Let("nested", nested, n.Var("memory")))
    altered = replace(altered, spec=replace(altered.spec, body=altered.body))
    assert "unrecognized unreachable observation code" in hook.check(altered, current.library)


def test_memory_scope_names_only_its_enumerated_truth_state_indices():
    proposal = _candidate(state(), "obs.memory", n.Var("memory"), ("read_x",), "int",
                          {"init": n.Lit(0), "step": n.Call("inc", (n.Var("memory"),))})
    scope = proposal.request.scope
    assert scope["domain"].startswith("bounded:")
    assert "explicitly enumerated truth state indices" in scope["domain"]
    assert "restricted to these states" in scope["domain"]
    assert str(scope["history_state_indices"]) in scope["domain"]
    assert "all truth states" not in scope["domain"]


def test_finding_7_probe_argument_selection_does_not_mutate_truth():
    current = state()
    class MutableTruth:
        def __init__(self, value):
            self.value = value

    truths = tuple(MutableTruth(index) for index in range(3))
    current.world.truth_states = truths
    current.world.atoms += (kernel.Atom("mutable_read", 2,
                                       lambda truth, extra: _mutating_read(truth, extra),
                                       kind="observation"),)
    current.world.probes += ("mutable_read",)
    current.world.decl = replace(current.world.decl,
                                 operations=current.world.decl.operations + (
                                     OperationSpec("mutable_read", "decide", (Edge("truth"), Edge("int")),
                                                   Edge("int"), "mutable read"),),
                                 observation={**current.world.decl.observation,
                                              "probes": [*current.world.decl.observation["probes"],
                                                         "mutable_read"]})
    current.world.signatures["mutable_read"] = Signature(("truth", "int"), "int")
    current.library = GenLibrary(current.world.decl, current.world.atoms)
    with pytest.raises(ValueError, match="facts_unchanged"):
        _probe_args(current, "mutable_read", current.library.scope())
    assert [truth.value for truth in truths] == [0, 1, 2]
    proposal = candidate("q598", ("mutable_read",), n.Var("mutable_read"))
    assert admit(current, proposal).stage == "callable"
    assert [truth.value for truth in truths] == [0, 1, 2]
    assert not hasattr(current, "_observation_arguments") or "mutable_read" not in current._observation_arguments

    current = state()
    original = current.world.truth_states[0].fields

    def mutating_card(truth):
        object.__setattr__(truth, "fields", (99, *truth.fields[1:]))
        return 99

    current.world.atoms = tuple(kernel.Atom("read_x", 1, mutating_card, kind="observation")
                                if atom.name == "read_x" else atom for atom in current.world.atoms)
    current.library = GenLibrary(current.world.decl, current.world.atoms)
    assert admit(current, candidate("q597", ("read_x",), n.Var("read_x"))).stage == "callable"
    assert current.world.truth_states[0].fields == original


def _mutating_read(truth, extra):
    truth.value += 1
    return truth.value + extra


@pytest.mark.skipif(os.environ.get("OPULSE_GEN_SLOW") != "1", reason="slow acceptance run")
def test_four_kinds_interleave_and_observe_invented_definitions():
    kinds = ("object", "operation", "combinator", "observation")
    world = toy_truth.gen_world(kinds)
    current = generate(world, 200, 76, per_kind_min=40, layer_target=8,
                       moves=discover_moves())
    observations = [entry for entry in current.entries.values() if entry.kind == "observation"]
    cross = [entry for entry in observations if any(
        dependency in current.entries and current.entries[dependency].kind != "observation"
        or "." in dependency and dependency.split(".")[0] in current.entries
        for dependency in entry.depends_on)]
    assert len(current.entries) >= 200
    assert set(Counter(entry.kind for entry in current.entries.values())) == set(kinds)
    assert len(observations) >= 40
    assert len(cross) * 10 >= len(observations) * 3
    assert any(current.entries[dependency].kind == "combinator"
               for entry in cross for dependency in entry.depends_on if dependency in current.entries)
    assert max(entry.layer for entry in cross) >= 3


@pytest.mark.parametrize("adapter", (action, automata, circuits, dice, grammar, hidden,
                                     integer, lists, rhythm, versions))
def test_catalogue_probe_moves_have_a_callable_observation(adapter):
    world = adapter.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))

    def grow():
        rng = random.Random(12)
        for index in range(50):
            proposal = MOVES[index % len(MOVES)](current, rng)
            if proposal is not None:
                admit(current, proposal)

    fast.deep(grow)
    assert any(entry.kind == "observation" for entry in current.entries.values())


def test_versions_short_generation_admits_observations():
    world = versions.gen_world()
    assert world.truth_states
    assert any(versions.hosts.valid_doc(truth) for truth in world.truth_states)
    assert any(versions.hosts.valid_history(truth) and len(truth.fields) > 1
               for truth in world.truth_states)
    assert world.probes == ("read", "read_version")
    local = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                       world.extra_scope, world.signatures), dict(world.sorts))
    proposal = _candidate(local, "obs.test", n.Var("read_version"), ("read_version",), "Version")
    assert tuple(args[0] for args in proposal.request.domain) == world.truth_states
    current = generate(world, 12, 1, per_kind_min=1, layer_target=1)
    assert sum(entry.kind == "observation" for entry in current.entries.values()) >= 2


def test_versions_observation_with_a_literal_truth_state_is_refused():
    world = versions.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope, world.signatures), dict(world.sorts))
    path = versions.hosts.PATHS[0]
    body = n.Call("edit", (n.Lit(world.truth_states[0]), n.Lit(path),
                           n.Call("at", (n.Var("read"), n.Lit(path)))))
    result = fast.deep(lambda: admit(current, _candidate(current, "obs.test", body, ("read",), "Doc")))
    assert not isinstance(result, Entry), result


def test_versions_observations_can_reuse_prior_observations_to_layer_ten():
    world = versions.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope, world.signatures), dict(world.sorts))

    def grow():
        previous = None
        for path in versions.hosts.PATHS[:10]:
            source = n.Call(previous) if previous else n.Var("read")
            body = n.Call("edit", (source, n.Lit(path), n.Lit("1")))
            proposal = _candidate(current, "obs.test", body, ("read",), "Doc")
            result = admit(current, proposal)
            assert isinstance(result, Entry), result
            previous = result.name
        assert current.entries[previous].layer == 10

    fast.deep(grow)


@pytest.mark.skipif(os.environ.get("OPULSE_GEN_SLOW") != "1", reason="slow acceptance run")
def test_versions_observation_acceptance():
    current = generate(versions.gen_world(), 400, 1, per_kind_min=50,
                       layer_target=10, time_limit=300)
    observations = [entry for entry in current.entries.values() if entry.kind == "observation"]
    assert len(observations) >= 50
    assert max(entry.layer for entry in observations) >= 10
    assert {"read", "read_version"} <= {
        probe for entry in observations for probe in current.library.get(entry.name).spec.reads}


def test_parameterized_probe_reads_use_a_typed_default():
    world = automata.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    sources = _sources(current)
    assert any(source[0] == "accept" and source[2] == n.Var("accept") for source in sources)
    assert all(source[0] != "accept" for source in sources if isinstance(source[2], n.Call))

    typed = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                      world.extra_scope, world.signatures), dict(world.sorts))
    fixed = [source for source in _sources(typed) if source[0] == "accept"
             and isinstance(source[2], n.Call)]
    assert len({repr(source[2].args[1].value) for source in fixed}) >= 2


def test_fixed_reads_sample_both_extra_arguments():
    world = circuits.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    sources = _sources(current)
    fixed = {tuple(repr(argument.value) for argument in source[2].args[1:])
             for source in sources if source[0] == "out_pin" and isinstance(source[2], n.Call)}
    assert len({arguments[0] for arguments in fixed}) >= 2
    assert len({arguments[1] for arguments in fixed}) >= 2


def test_mass_probe_fixed_reads_cover_distinct_events():
    world = dice.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope, world.signatures), dict(world.sorts))
    fixed = [source for source in _sources(current) if source[0] == "mass"
             and isinstance(source[2], n.Call)]
    assert len({repr(source[2].args[1].value) for source in fixed}) >= 2


def test_integer_reads_can_join_without_a_boolean_intermediate():
    world = automata.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    sources = _sources(current)
    first_source = next(source for source in sources if source[0] == "step"
                        and isinstance(source[2], n.Var))
    second_source = next(source for source in sources if source[0] == "step"
                         and isinstance(source[2], n.Call)
                         and len(set(zip(_source_partition(current, first_source),
                                         _source_partition(current, source)))) > max(
                             len(set(_source_partition(current, first_source))),
                             len(set(_source_partition(current, source)))))
    for source in (first_source, second_source):
        proposal = _candidate(current, "obs.test", source[2], source[3], source[1])
        assert isinstance(admit(current, proposal), Entry)
    joined = _join(current, random.Random(24))
    assert joined is not None
    assert joined.signature.output == "int"
    assert isinstance(admit(current, joined), Entry)


@pytest.mark.parametrize("adapter", (calendar, geometry, kitchen, melody, molecules,
                                     permutation, pixels, roads, shadows, text))
def test_new_catalogue_worlds_propose_safe_observations(adapter):
    world = adapter.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))

    def grow():
        rng = random.Random(12)
        for index in range(55):
            proposal = MOVES[index % len(MOVES)](current, rng)
            if proposal is not None:
                admit(current, proposal)

    fast.deep(grow)
    assert any(entry.kind == "observation" for entry in current.entries.values())


@pytest.mark.skipif(os.environ.get("OPULSE_GEN_SLOW") != "1", reason="slow acceptance run")
@pytest.mark.parametrize("adapter", (action, automata, circuits, dice, grammar, hidden,
                                     integer, lists, rhythm, versions))
def test_catalogue_observation_acceptance(adapter):
    start = monotonic()
    current = generate(adapter.gen_world(), 400, 1, per_kind_min=50, layer_target=10,
                       time_limit=300)
    observations = [entry for entry in current.entries.values() if entry.kind == "observation"]
    cross = [entry for entry in observations if any(
        dependency in current.entries and current.entries[dependency].kind != "observation" or
        "." in dependency and dependency.split(".")[0] in current.entries
        for dependency in entry.depends_on)]
    elapsed = monotonic() - start
    print(adapter.__name__, len(observations), max((entry.layer for entry in observations),
          default=0), len(cross), round(elapsed / max(len(observations), 1), 3))
    assert len(observations) >= 50
    assert max(entry.layer for entry in observations) >= 8
    assert len(cross) * 10 >= len(observations) * 3


def test_observation_can_return_an_invented_record():
    world = toy_truth.gen_world(("object", "observation"))
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))

    def grow():
        rng = random.Random(2)
        for _ in range(10):  # a record over the probe sorts
            proposal = OBJECT_MOVES[0](current, rng)
            if proposal is not None and isinstance(admit(current, proposal), Entry):
                break
        move = next(move for move in MOVES if move.name == "obs.via_ops")
        for _ in range(12):
            proposal = move(current, rng)
            if proposal:
                admit(current, proposal)
    fast.deep(grow)
    records = [entry for entry in current.entries.values() if entry.kind == "observation" and
               current.sorts[entry.signature.output].origin == "invented"]
    assert records
    assert all(any("." in dependency for dependency in entry.depends_on) for entry in records)


def test_truthless_world_uses_decide_operations_as_probes():
    world = toy.gen_world(("observation",))
    world.probes = ("is_pos", "is_zero")
    world.truth_states = tuple(range(-3, 9))
    world.decl = replace(world.decl, observation={"truth": None, "probes": list(world.probes),
                                                  "show": {}, "judge_view": "full_state"})
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    body = n.Case(((n.Test(n.Var("is_pos")), n.Lit(1)),), n.Lit(0))
    proposal = candidate("q201", ("is_pos",), body)
    proposal.signature = Signature(("int",), "int")
    assert isinstance(admit(current, proposal), Entry)
    assert current.entries["q201"].layer == 1
    mismatch = candidate("q202", ("is_zero",), n.Case(((n.Test(n.Var("is_zero")), n.Lit(1)),), n.Lit(0)))
    mismatch.signature = Signature(("int",), "int")
    mismatch.request = VerifyRequest("exhaustive", tuple((item,) for item in world.truth_states),
                                     {"domain": "all twelve integers", "size": 12},
                                     reference=lambda value: 99)
    assert admit(current, mismatch).stage == "verify"


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_truthless_moves_and_memory_observe_the_declared_sort():
    world = toy.gen_world(("observation",))
    world.probes = ("is_pos", "is_zero")
    world.truth_states = tuple(range(-3, 9))
    world.decl = replace(world.decl, observation={"truth": None, "probes": list(world.probes),
                                                  "show": {}, "judge_view": "full_state"})
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))

    def grow():
        rng = random.Random(23)
        for index in range(90):
            proposal = MOVES[index % len(MOVES)](current, rng)
            if proposal:
                assert proposal.signature.inputs == ("int",)
                admit(current, proposal)
    fast.deep(grow)
    assert len(current.entries) >= 2
    assert any(entry.move == "obs.memory" for entry in current.entries.values())
    assert all(set(current.library.get(entry.name).spec.reads) <= set(world.probes)
               for entry in current.entries.values())


def test_small_truthless_memory_observes_declared_sort():
    world = toy.gen_world(("observation",))
    world.probes = ("is_pos", "is_zero")
    world.truth_states = tuple(range(-3, 9))
    world.decl = replace(world.decl, observation={"truth": None, "probes": list(world.probes),
                                                  "show": {}, "judge_view": "full_state"})
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    step = n.Case(((n.Test(n.Var("is_pos")), n.Lit(1)),), n.Lit(0))
    proposal = _candidate(current, "obs.memory", n.Var("memory"), ("is_pos",), "int",
                          {"init": n.Lit(0), "step": step})
    assert proposal.signature.inputs == ("int",)
    result = fast.deep(admit, current, proposal)
    assert isinstance(result, Entry), result
    assert current.library.get(result.name).spec.reads == ("is_pos",)


def test_probe_with_extra_inputs_records_its_fixed_arguments():
    world = circuits.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    proposal = candidate("q400", ("out_pin",), n.Var("out_pin"))
    proposal.signature = Signature(("circuit",), "bit")
    result = admit(current, proposal)
    assert isinstance(result, Entry)
    assert "out_pin" in current.requests["q400"].scope["probe_arguments"]
    assert len({example[1]["ok"]["v"] for example in result.examples}) == 2


def test_probe_derived_truth_sort_is_safe_but_direct_truth_is_not():
    world = lists.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    derived = candidate("q410", ("items",), n.Call("tail", (n.Var("items"),)))
    derived.signature = Signature(("list",), "list")
    assert not hook_for("observation").check(derived.defn, current.library)
    assert isinstance(admit(current, derived), Entry)

    direct = candidate("q411", ("items",), n.Call("tail", (n.Var("list"),)))
    direct.signature = Signature(("list",), "list")
    rejected = admit(current, direct)
    assert rejected.stage == "check" and "undeclared observation input" in rejected.reason


def test_multiple_fixed_reads_of_same_probe_are_recorded_and_distinguished():
    world = circuits.gen_world()
    current = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    bits = world.sorts["bits"].values[0]
    first = n.Call("out_pin", (n.Var("__truth"), n.Lit(bits), n.Lit(0)))
    second = n.Call("out_pin", (n.Var("__truth"), n.Lit(bits), n.Lit(1)))
    body = n.Let("first", first, n.Let("second", second, n.Var("second")))
    proposal = candidate("q420", ("out_pin",), body)
    proposal.signature = Signature(("circuit",), "bit")
    result = admit(current, proposal)
    assert isinstance(result, Entry)
    arguments = current.requests["q420"].scope["probe_arguments"]["out_pin"]
    assert len(arguments) == 2
    assert repr((bits, 0)) in arguments and repr((bits, 1)) in arguments
    scope = current.library.scope()
    sample = tuple(next(truth for truth in world.truth_states
                        if fast.call("out_pin", (truth, bits, 0), scope, world.fuel,
                                     world.dialect).outcome == Ok(0) and
                        fast.call("out_pin", (truth, bits, 1), scope, world.fuel,
                                     world.dialect).outcome == Ok(output))
                   for output in (0, 1))
    first_values = [fast.call("out_pin", (truth, bits, 0), scope, world.fuel, world.dialect).outcome.value
                    for truth in sample]
    assert first_values == [0, 0]
    request = VerifyRequest("bounded", tuple((truth,) for truth in sample),
                            {"domain": "two distinct circuits", "size": 2})
    results = hook_for("observation").run(current, proposal, request)
    assert [outcome.value for _, outcome, _ in results] == [0, 1]
    assert current.library.get("q420").spec.reads == ("out_pin",)
    from opulse.gen_v2.audit import audit

    report = audit(current)
    assert report.ok, report.failures
    assert not report.skipped

    forbidden = candidate("q421", ("out_pin",), n.Call("eval_bits", (n.Var("__truth"), n.Lit(bits))))
    forbidden.signature = Signature(("circuit",), "bit")
    rejected = admit(current, forbidden)
    assert rejected.stage == "check" and "undeclared observation input" in rejected.reason

    marker = n.Var("__truth")
    reused = candidate("q422", ("out_pin",), n.Let("ignore", n.Call("out_pin", (
        marker, n.Lit(bits), n.Lit(0))), marker))
    reused.signature = Signature(("circuit",), "bit")
    assert "undeclared observation input" in admit(current, reused).reason


def test_independent_reference_is_recorded_only_when_supplied():
    current = state()
    proposal = candidate("q430", ("read_x",), n.Call("add", (n.Var("read_x"), n.Lit(1))))
    proposal.request = VerifyRequest("exhaustive", tuple((truth,) for truth in current.world.truth_states),
                                     {"domain": "truth", "size": len(current.world.truth_states)},
                                     reference=lambda truth: truth.fields[0] + 1,  # reads the full truth
                                     extra={"reference_origin": "oracle"})
    assert isinstance(admit(current, proposal), Entry)
    assert "reference" in current.library.get("q430").evidence.checks
    assert current.requests["q430"].scope["reference"] == "independent"


def test_classic_action_hook_is_callable_without_opening_the_kind():
    world = classic_world("action")
    current = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                         world.extra_scope), dict(world.sorts))
    body = n.Case(((n.Test(n.Var("front_wall")), n.Lit(False)),), n.Lit(True))
    proposal = candidate("q401", ("front_wall",), body)
    proposal.signature = Signature(("state",), "bool")
    hook = hook_for("observation")
    assert not hook.check(proposal.defn, current.library)
    request = VerifyRequest("bounded", tuple((truth,) for truth in world.truth_states[:16]),
                            {"domain": "classic action sample", "size": 16})
    assert all(isinstance(outcome, Ok) for _, outcome, _ in
               fast.deep(hook.run, current, proposal, request))


def test_memory_count_max_last_change_and_ever_true():
    current = state()
    states = (current.world.truth_states[0], current.world.truth_states[64],
              current.world.truth_states[32])
    request = VerifyRequest("sampled", (states,), {"domain": "one sampled three-state history", "size": 1},
                            seed=13)
    hook = hook_for("observation")
    count = candidate("q301", ("read_x",), n.Var("memory"),
                      {"init": n.Lit(0), "step": n.Call("add", (
                          n.Var("memory"), n.Case(((n.Test(n.Call("is_pos", (n.Var("read_x"),))),
                                                      n.Lit(1)),), n.Lit(0))))})
    maximum = candidate("q302", ("read_x",), n.Var("memory"),
                        {"init": n.Lit(-1000), "step": n.Call("maxv", (
                            n.Var("memory"), n.Var("read_x")))})
    change = candidate("q303", ("read_x",), n.Call("change", (n.Var("memory"),)),
                       {"init": n.Lit(0), "step": n.Call("remember", (
                           n.Var("memory"), n.Var("read_x")))})
    ever = candidate("q304", ("read_x",), n.Var("memory"),
                     {"init": n.Lit(False), "step": n.Case(((n.Or(n.Test(n.Var("memory")),
                         n.Test(n.Call("is_pos", (n.Var("read_x"),)))), n.Lit(True)),), n.Lit(False))})
    assert [hook.run(current, item, request)[0][1].value for item in (count, maximum, change, ever)] == [
        2, 2, 1, True]
