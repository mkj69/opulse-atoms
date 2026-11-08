"""Finite-domain checks for the extra combination modes."""

import random
from dataclasses import replace

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Ok, outcome_equal
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import admit
from opulse.gen_v2.audit import audit
from opulse.gen_v2.base import Entry, GenState
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves import modes
from opulse.gen_v2.moves import object as object_moves
from opulse.gen_v2.moves.registry import discover_moves
from opulse.gen_v2.run import load, save
from opulse.gen_v2.worlds import toy


def _state():
    world = toy.gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))


def _admit(state, candidate):
    assert candidate is not None
    result = admit(state, candidate)
    assert isinstance(result, Entry), result
    return result


def test_mode_moves_are_discovered_and_respect_closed_kinds():
    moves = discover_moves()
    assert {move.name for kind in moves for move in moves[kind] if move.name.startswith("mode.")} == {
        move.name for move in modes.MOVES}
    world = toy.gen_world(open_kinds=("object",))
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    assert modes.MOVES[0](state, random.Random(0)) is None


def test_combinator_with_missing_operation_slot_is_not_proposed():
    state = _state()
    assert modes._combinator(state, "mode.turns", n.Var("x"), ("x",),
                             ("choose0",), ("int",), "int",
                             {"observe0": [("inc", ("int",), "int")]}) is None


def test_mode_application_does_not_eagerly_call_plugged_operations():
    def check():
        state = _state()
        stable = _steps_and_fixpoint(state)
        application = modes.apply(state, random.Random(2))
        assert application is not None
        assert isinstance(application.defn.body, n.Call)
        assert stable.name in application.defn.depends_on
        assert set(application.meta["plugged"]) <= set(application.defn.depends_on)
        assert application.defn.layer == 1 + max(state.layer(name) for name in application.defn.depends_on)
        scope = state.library.scope().extend([kernel.Defn(application.defn.name, ("arg0",),
                                                          application.defn.body)])
        spec = state.library.get(stable.name).spec
        for value in (-3, -1, 0, 4, 8):
            plugged = iter(application.meta["plugged"])
            direct_args = tuple(kernel.FnRef(next(plugged)) if param in spec.op_params else value
                                for param in spec.params)
            direct = fast.call(stable.name, direct_args, scope, state.world.fuel)
            applied = fast.call(application.defn.name, (value,), scope, state.world.fuel)
            assert outcome_equal(direct.outcome, applied.outcome)
            assert direct.steps == applied.steps

    fast.deep(check)


def test_memo_tree_recursion_preserves_scope_outcomes_and_charged_steps():
    def check():
        state = _state()
        plain = _admit(state, modes.tree_recursive(state, random.Random(1)))
        memo = _admit(state, modes.memo(state, random.Random(1)))
        body = state.library.get(memo.name).body
        assert any(isinstance(node, n.Rec) and node.memo for node in n.walk(body))
        assert memo.meta["memo_of"] == plain.name
        assert len(memo.meta["plain_steps"]) == len(state.requests[plain.name].domain)
        for index, args in enumerate(state.requests[plain.name].domain):
            before = fast.call(plain.name, args, state.library.scope(), state.world.fuel)
            after = fast.call(memo.name, args, state.library.scope(), state.world.fuel)
            assert outcome_equal(before.outcome, after.outcome)
            assert before.steps == after.steps == memo.meta["plain_steps"][index]
        assert "memo_work_estimated" not in memo.meta
        assert memo.meta["memo_work"][-1] < memo.meta["plain_steps"][-1]
        params = state.library.get(memo.name).spec.extra["input_names"]
        for index, args in enumerate(state.requests[memo.name].domain):
            actual = kernel.evaluate(body, dict(zip(params, args)), state.library.scope(),
                                     kernel.Limits(fuel=state.world.fuel))
            assert memo.meta["memo_work"][index] == actual.work

    fast.deep(check)


def test_memoized_trace_audits_charged_steps_not_physical_work(tmp_path):
    from opulse.atoms.boundary import Boundary, flatten_calls

    def check():
        current = _state()
        _admit(current, modes.tree_recursive(current, random.Random(1)))
        memo = _admit(current, modes.memo(current, random.Random(1)))
        arguments = current.requests[memo.name].domain[-1]
        run = kernel.call(memo.name, arguments, current.library.scope(), trace=True)
        assert run.work < run.steps
        leaves = flatten_calls(run.trace, Boundary.unfold_all())
        assert sum(leaf.steps for leaf in leaves) + run.jumps == run.steps
        assert audit(current).ok
        checkpoint = tmp_path / "memo.json"
        save(current, checkpoint)
        assert audit(load(current.world, checkpoint)).ok

    fast.deep(check)


def _steps_and_fixpoint(state):
    bounds = set()
    for seed in range(30):
        candidate = modes.stable_step(state, random.Random(seed))
        if candidate is not None and candidate.meta["cap"] not in bounds:
            _admit(state, candidate)
            bounds.add(candidate.meta["cap"])
        if len(bounds) >= 3:
            break
    assert len(bounds) >= 3
    return _admit(state, modes.until_stable(state, random.Random(13)))


def test_until_stable_converges_for_every_scoped_operation():
    def check():
        state = _state()
        entry = _steps_and_fixpoint(state)
        spec = state.library.get(entry.name).spec
        assert any(isinstance(node, n.Rec) and not isinstance(node.measure, str)
                   for node in n.walk(spec.body))
        assert any(isinstance(node, n.Lit) and getattr(node.value, "reason", None) == "not_stable"
                   for node in n.walk(spec.body))
        for name in entry.meta["slot_families"]["step"]:
            for (value,) in state.requests[entry.name].domain:
                run = fast.call(entry.name, (kernel.FnRef(name), value), state.library.scope(),
                                state.world.fuel)
                assert isinstance(run.outcome, Ok), (name, value, run.outcome)
                next_run = fast.call(name, (run.outcome.value,), state.library.scope(), state.world.fuel)
                assert outcome_equal(next_run.outcome, run.outcome)
        exhausted = fast.call(entry.name, (kernel.FnRef("inc"), 0), state.library.scope(),
                              state.world.fuel)
        assert exhausted.outcome == Bottom("not_stable")
        application = _admit(state, modes.apply(state, random.Random(2)))
        assert application.meta["combinator"] == entry.name

    fast.deep(check)


def test_compose_sort_uses_core_fold_and_size():
    def check():
        state = _state()
        rng = random.Random(5)
        for _ in range(16):
            candidate = object_moves.MOVES[2](state, rng)
            if candidate is not None:
                result = admit(state, candidate)
                if isinstance(result, Entry):
                    sort = result.name
                    assert state.library.scope().resolve(f"{sort}.fold") is not None
                    assert state.library.scope().resolve(f"{sort}.size") is not None
                    assert f"{sort}.size" in n.references(
                        state.library.scope().resolve(f"{sort}.fold").body)
                    assert not any(entry.move == "mode.fold_of" for entry in state.entries.values())
                    fold = modes.fold_of(state, rng)
                    assert fold is not None
                    application = _admit(state, fold)
                    assert application.depends_on == fold.defn.depends_on
                    assert f"{sort}.fold" in application.depends_on
                    assert application.layer >= 2
                    assert not [failure for failure in audit(state, sample=3).failures
                                if failure.name == application.name]
                    return
        assert False, "no admitted compose sort"

    fast.deep(check)


def test_fold_helper_is_promoted_and_survives_checkpoint(tmp_path):
    def check():
        state = _state()
        rng = random.Random(5)
        for _ in range(16):
            candidate = object_moves.MOVES[2](state, rng)
            if candidate is not None and isinstance(admit(state, candidate), Entry):
                break
        else:
            assert False, "no admitted compose sort"
        application = _admit(state, modes.fold_of(state, rng))
        helper = next(entry for entry in state.entries.values() if entry.move == "mode.fold_zero")
        assert helper.kind == "operation"
        assert state.library.get(helper.name).status == "promoted"
        assert state.library.get(helper.name).evidence is not None
        assert any(isinstance(node, n.Lit) and node.value == kernel.FnRef(helper.name)
                   for node in n.walk(state.library.get(application.name).body))
        assert helper.name in application.depends_on
        assert not any(atom.name == helper.name for atom in state.library._extra_defns.values())
        path = tmp_path / "fold.json"
        save(state, path)
        restored = load(state.world, path)
        assert helper.name in restored.entries
        for (value,) in state.requests[application.name].domain:
            original = fast.call(application.name, (value,), state.library.scope(), state.world.fuel)
            replayed = fast.call(application.name, (value,), restored.library.scope(), state.world.fuel)
            assert outcome_equal(original.outcome, replayed.outcome)
            assert original.steps == replayed.steps

    fast.deep(check)


def test_turn_taking_verifies_both_agents_and_replays_schedule():
    def check():
        state = _state()
        candidate = modes.turns(state, random.Random(1))
        entry = _admit(state, candidate)
        assert entry.meta["agents"] == 2
        assert len(entry.signature.op_inputs) == 5
        assert any(isinstance(node, n.Rec) for node in n.walk(candidate.defn.body))
        operation_names = tuple(candidate.meta["slot_families"][slot][0]
                                for slot in candidate.defn.spec.op_params)
        operation_names = (*operation_names[:3], candidate.meta["slot_families"]["choose1"][1],
                           operation_names[4])
        args = tuple(kernel.FnRef(name) for name in operation_names)
        for value in (-2, 0, 3):
            actual = fast.call(entry.name, (*args, value), state.library.scope(), state.world.fuel)
            observation0 = fast.call(operation_names[0], (value,), state.library.scope(), state.world.fuel)
            chosen0 = fast.call(operation_names[1], (observation0.outcome.value,),
                                state.library.scope(), state.world.fuel)
            first = fast.call(operation_names[4], (chosen0.outcome.value, 0, value),
                              state.library.scope(), state.world.fuel)
            observation1 = fast.call(operation_names[2], (first.outcome.value,),
                                     state.library.scope(), state.world.fuel)
            chosen1 = fast.call(operation_names[3], (observation1.outcome.value,),
                                state.library.scope(), state.world.fuel)
            last = fast.call(operation_names[4], (chosen1.outcome.value, 1, first.outcome.value),
                             state.library.scope(), state.world.fuel)
            assert outcome_equal(actual.outcome, last.outcome)
        all_orders = replace(candidate.defn.body, value=n.Lit(("all", 2)))
        scope = state.library.scope().extend([kernel.Defn("all_orders", candidate.defn.spec.params,
                                                         all_orders, kind="combinator")])
        run = fast.call("all_orders", (*args, 2), scope, state.world.fuel)
        assert isinstance(run.outcome, Ok)
        assert 2 in run.outcome.value
        assert len(run.outcome.value) >= 2

    fast.deep(check)


def test_mode_proposals_are_deterministic():
    def proposals():
        state = _state()
        rng = random.Random(5)
        sequence = []
        for builder in (modes.tree_recursive, modes.memo, modes.stable_step,
                        modes.stable_step, modes.stable_step, modes.until_stable):
            candidate = builder(state, rng)
            sequence.append((candidate.defn.to_dict() if candidate else None,
                             candidate.meta if candidate else None))
            if candidate is not None:
                admit(state, candidate)
        return sequence

    assert fast.deep(proposals) == fast.deep(proposals)
