"""Reference obligations for kind definitions (spec sections 4, 7, 9 and 11)."""

from __future__ import annotations

from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import Ok, outcome_equal
from opulse.tasks_v2 import kernel_engine as engine
from opulse.tasks_v2 import library_defs
from opulse.tasks_v2.angles import combinator, observation


def test_fraction_obligations_over_entire_recorded_scope():
    values = tuple(engine.fraction(num, den) for num in range(-12, 13)
                   for den in range(-12, 13) if den)
    scope = engine.scope("integer@1", library_defs.records()[1])
    valid = lambda value: scope.resolve("fraction_valid").fn(value).tag == "true"
    canon = scope.resolve("fraction_canon").fn
    assert len(values) == 600
    assert library_defs.verify_canon(valid, canon, (), values)
    assert library_defs.verify_fraction_interface(values, scope)
    definitions = library_defs.records()[1]
    assert engine.run("integer@1", n.Call("frac_add", (n.Lit(engine.fraction(1, 3)),
                                                     n.Lit(engine.fraction(1, 6)))), definitions).outcome == Ok(
        engine.fraction(1, 2))
    assert engine.run("integer@1", n.Call("frac_mul", (n.Lit(engine.fraction(2, 4)),
                                                     n.Lit(engine.fraction(3, 2)))), definitions).outcome == Ok(
        engine.fraction(3, 4))
    for value in (*values, engine.fraction(1, 0)):
        call = n.Call("fraction", (n.Lit(value),))
        result = engine.run("integer@1", call, library_defs.records()[1])
        unfolded = engine.run("integer@1", kernel.inline(call, scope), library_defs.records()[1])
        assert outcome_equal(result.outcome, unfolded.outcome)
        assert result.steps == unfolded.steps
    broken = scope.extend()
    broken.atoms["frac_mul_base"] = kernel.Atom("frac_mul_base", 2, lambda left, right: left)
    assert not library_defs.verify_fraction_interface((engine.fraction(1, 2), engine.fraction(2, 4)), broken)


def test_all_reference_costs_are_measured():
    for record in library_defs.records()[0]:
        assert record.status == "promoted"
        assert record.evidence.method in ("bounded", "exhaustive")
        assert record.evidence.world_hash == engine.world(record.id.split("/")[0]).lock["world_hash"]
        assert record.contract.guarantees
        assert record.cost.steps["over"] == "evidence scope"
        assert 0 <= record.cost.steps["min"] <= record.cost.steps["mean"] <= record.cost.steps["max"]
        assert record.cost.length == n.length(record.body)
    definitions = {definition.name: definition for definition in library_defs.records()[1]}
    assert definitions["frac_add"].layer == definitions["frac_mul"].layer == 2


def test_action_host_codec_round_trips_and_preserves_probes():
    for state in observation.states(4, 0):
        card = engine.to_card(state)
        assert engine.from_card(card) == state
        assert engine.unwire(engine.wire(card)) == state
        for probe in ("front_wall", "front_water"):
            native = engine.run("action@1", n.Call(probe, (n.Lit(state),))).outcome
            encoded = engine.run("action@1", n.Call(probe, (n.Lit(card),))).outcome
            assert outcome_equal(native, encoded)
        native = engine.run("action@1", n.Call("turn_left", (n.Lit(state),)))
        encoded = engine.run("action@1", n.Call("turn_left", (n.Lit(card),)))
        assert isinstance(native.outcome, Ok) and isinstance(encoded.outcome, Ok)
        assert engine.from_card(encoded.outcome.value) == native.outcome.value
        assert native.steps == encoded.steps


def test_combinator_family_and_bounded_ilist_recurrences():
    bodies = {record.name: record.body for record in library_defs.records()[0]}
    assert library_defs.verify_combinator(bodies["twice"], bodies["twice"], combinator.FAMILY,
                                          tuple(range(20)))
    for items in ((), (3,), (-2, 0, 4), (1, 2, 3, 4)):
        value = engine.ilist(items)
        for name, args, expected in (("ilen", (value,), len(items)),
                                     ("isum", (value,), sum(items)),
                                     ("iappend", (value, engine.ilist((5,))), engine.ilist(items + (5,))),
                                     ("fold", (kernel.FnRef("add"), 0, value), sum(items))):
            outcome = engine.run("integer@1", n.Call(name, tuple(n.Lit(arg) for arg in args)),
                                 library_defs.records()[1]).outcome
            assert outcome == Ok(expected), (name, items)
            node = n.Call(name, tuple(n.Lit(arg) for arg in args))
            expanded = engine.run("integer@1", kernel.inline(node, engine.scope("integer@1", library_defs.records()[1])),
                                  library_defs.records()[1])
            assert outcome_equal(outcome, expanded.outcome)


def test_combinator_unfold_rules_on_recorded_family_and_inputs():
    definitions = library_defs.records()[1]
    records = {record.name: record for record in library_defs.records()[0]}
    for name in ("twice", "repeat", "seq", "fold"):
        recorded = records[name].evidence.scope
        assert recorded["size"] == len(recorded["family"]) * len(recorded["inputs"])
        for function in recorded["family"]:
            for encoded in recorded["inputs"]:
                value = engine.unwire(encoded)
                passed = n.Lit(kernel.FnRef(function))
                argument = n.Lit(value)
                if name == "twice":
                    args = (passed, argument)
                    unfolded = n.Call(function, (n.Call(function, (argument,)),))
                elif name == "repeat":
                    args = (passed, n.Lit(3), argument)
                    unfolded = argument
                    for _ in range(3):
                        unfolded = n.Call(function, (unfolded,))
                elif name == "seq":
                    args = (passed, n.Lit(kernel.FnRef("neg")), argument)
                    unfolded = n.Call("neg", (n.Call(function, (argument,)),))
                else:
                    args = (passed, n.Lit(0), argument)
                    unfolded = n.Lit(0)
                    for item in reversed(engine.list_items(value)):
                        unfolded = n.Call(function, (n.Lit(item), unfolded))
                result = engine.run("integer@1", n.Call(name, args), definitions)
                expected = engine.run("integer@1", unfolded, definitions)
                assert outcome_equal(result.outcome, expected.outcome), (name, function, value)
                if name in ("twice", "seq"):
                    assert result.steps == expected.steps, (name, function, value)
                expanded = engine.run("integer@1", kernel.inline(n.Call(name, args),
                                                                 engine.scope("integer@1", definitions)), definitions)
                assert outcome_equal(result.outcome, expanded.outcome)
                assert result.steps == expanded.steps


def test_observations_have_only_granted_probe_dependencies():
    states = observation.states(4, 0)
    records = {record.name: record for record in library_defs.records()[0]}
    roles = {operation.name: operation.role for operation in engine.world("action@1").operations}

    def evaluate(node, env=None):
        outcome = kernel.evaluate(node, env or {}, engine.scope("action@1", library_defs.records()[1])).outcome
        assert isinstance(outcome, Ok)
        return outcome.value

    for name in ("front_free", "blocked_count"):
        spec = records[name].spec
        assert library_defs.verify_observation(spec, ("front_wall", "front_water"), roles,
                                                states, evaluate)
        for state, memory in product(states, (0, 1, 3)):
            initial_state = state.to_dict()
            args = (state, memory) if name == "blocked_count" else (state,)
            call = n.Call(name, tuple(n.Lit(value) for value in args))
            scope = engine.scope("action@1", library_defs.records()[1])
            original = engine.run("action@1", call, library_defs.records()[1])
            unfolded = engine.run("action@1", kernel.inline(call, scope), library_defs.records()[1])
            assert outcome_equal(original.outcome, unfolded.outcome)
            assert original.steps == unfolded.steps
            assert state.to_dict() == initial_state
    alias = library_defs.ObservationSpec("alias", (), n.Call("front_free", (n.Var("state"),)))
    assert library_defs.verify_observation(alias, ("front_wall", "front_water"), roles, states, evaluate,
                                           {"front_free": records["front_free"].spec})
    action_alias = library_defs.ObservationSpec("action_alias", (), n.Call("forward", (n.Var("state"),)))
    leak = library_defs.ObservationSpec("leak", (), n.Call("action_alias", (n.Var("state"),)))
    assert not library_defs.verify_observation(leak, ("front_wall", "front_water"), roles, states, evaluate,
                                               {"action_alias": action_alias})
    cycle = library_defs.ObservationSpec("cycle", (), n.Call("cycle", (n.Var("state"),)))
    assert not library_defs.verify_observation(cycle, (), roles, states, evaluate, {"cycle": cycle})
