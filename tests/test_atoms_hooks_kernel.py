"""Cost and fast-path hooks (docs/spec/atoms-v2.md, sections 9.7 and 11)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.kernel import (
    Atom,
    Defn,
    DictScope,
    FastPath,
    FnRef,
    Limits,
    call,
    check_fast_path,
    evaluate,
    inline,
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown, decode, encode
from opulse.atoms.verify import unfold_equivalent_calls


def _scope():
    return DictScope(
        atoms=[Atom("bulk", 1, lambda events: len(events), cost=lambda events: len(events),
                    cost_rule="len(events)")],
        defns=[Defn("count", ("events",), n.Call("bulk", (n.Var("events"),)))],
    )


@given(size=st.integers(0, 20), fuel=st.one_of(st.none(), st.integers(0, 22)),
       dialect=st.sampled_from(("atoms-v2", "legacy-v1")))
@settings(max_examples=75, deadline=None)
def test_cost_function_preserves_unfolding_and_boundaries(size, fuel, dialect):
    world = _scope()
    expression = n.Call("count", (n.Lit(tuple(range(size))),))
    limits = Limits(fuel=fuel)
    direct = evaluate(expression, scope=world, limits=limits, dialect=dialect, trace=True)
    unfolded = evaluate(inline(expression, world), scope=world, limits=limits, dialect=dialect)
    assert (direct.outcome, direct.steps) == (unfolded.outcome, unfolded.steps)
    assert direct.steps == (size if fuel is None or fuel >= size else 0)
    assert unfold_equivalent_calls(direct.trace, [Boundary.unfold_none(), Boundary.unfold_all()]).ok
    if fuel is not None and fuel < size:
        assert direct.outcome == Unknown("fuel")


def test_cost_function_charges_before_host_call_and_rejects_invalid_cost():
    seen = []
    world = DictScope([Atom("bulk", 1, lambda value: seen.append(value) or value,
                            cost=lambda value: value, cost_rule="value")])
    result = call("bulk", (3,), world, Limits(fuel=2), trace=True)
    assert (result.outcome, result.steps, seen) == (Unknown("fuel"), 0, [])
    assert result.trace.children[0].steps == 0
    for bad in (-1, 1.5, True):
        world.atoms["bulk"] = Atom("bulk", 1, lambda value: value, cost=lambda value, bad=bad: bad)
        with pytest.raises(ValueError, match="cost"):
            call("bulk", (3,), world)


def test_nonstrict_cost_receives_outcomes():
    world = DictScope([Atom("inspect", 1, lambda result: result, strict=False,
                            cost=lambda result: 2 if isinstance(result, Bottom) else 1)])
    result = call("inspect", (Bottom("no"),), world, dialect="legacy-v1")
    assert (result.outcome, result.steps) == (Bottom("no"), 2)


@given(value=st.integers(-7, 7), fuel=st.one_of(st.none(), st.integers(0, 15)))
@settings(max_examples=85, deadline=None)
def test_fast_path_matches_unfolding_within_scope_and_bypasses_outside(value, fuel):
    world = DictScope(
        atoms=[Atom("twice", 1, lambda item: item * 2, cost=3)],
        defns=[Defn("double", ("item",), n.Call("twice", (n.Var("item"),)))],
        fast_paths={"double": FastPath("double", lambda item: item * 2, lambda item: 3,
                                        lambda item: item >= 0)},
    )
    expression = n.Call("double", (n.Lit(value),))
    result = evaluate(expression, scope=world, limits=Limits(fuel=fuel), trace=True)
    plain = evaluate(inline(expression, world), scope=world, limits=Limits(fuel=fuel))
    assert (result.outcome, result.steps) == (plain.outcome, plain.steps)
    frame = result.trace.children[0]
    assert frame.fast is (value >= 0)
    assert [child.name for child in frame.children] == ([] if value >= 0 else ["twice"])
    assert unfold_equivalent_calls(result.trace, [Boundary.unfold_all(), Boundary.unfold_none()]).ok
    assert sum(child.steps for child in flatten_calls(result.trace, Boundary.unfold_all())) == result.steps


def test_fast_path_checker_and_scope_extension():
    world = _scope()
    fast = FastPath("count", len, len, lambda events: len(events) <= 4)
    world.fast_paths["count"] = fast
    assert check_fast_path(fast, world, [((),), ((1, 2),), ((1, 2, 3, 4),)]) == []
    assert check_fast_path(fast, world, [((1, 2, 3, 4, 5),)]) == [
        "((1, 2, 3, 4, 5),): outside fast-path scope"]
    assert check_fast_path(FastPath("count", len, lambda events: 1, lambda events: True),
                           world, [((1, 2),)]) == ["((1, 2),): outcome or steps differ"]
    assert check_fast_path(FastPath("absent", len, len, lambda events: True), world, [()]) == [
        "absent: not a definition"]
    extended = world.extend([Defn("other", (), n.Lit(1))])
    assert extended.fast_paths == world.fast_paths
    assert call("count", ((1, 2),), extended).steps == 2
    replaced = world.extend([Defn("count", ("events",), n.Lit(9))])
    assert "count" not in replaced.fast_paths
    assert call("count", ((1, 2),), replaced).outcome == Ok(9)


def test_fast_path_preserves_argument_trace_and_never_runs_after_fuel():
    invoked = []
    world = _scope()
    world.atoms["source"] = Atom("source", 0, lambda: (1, 2), cost=1)
    world.fast_paths["count"] = FastPath("count", lambda events: invoked.append(events) or len(events),
                                         len, lambda events: True)
    expression = n.Call("count", (n.Call("source"),))
    result = evaluate(expression, scope=world, trace=True, limits=Limits(fuel=2))
    assert (result.outcome, result.steps, invoked) == (Unknown("fuel"), 1, [])
    assert [frame.name for frame in result.trace.children] == ["source", "count"]
    assert result.trace.children[1].fast


def test_fast_leaf_verifier_rejects_spurious_child_or_jumps():
    world = _scope()
    world.fast_paths["count"] = FastPath("count", len, len, lambda events: True)
    result = call("count", ((1, 2),), world, trace=True)
    boundaries = [Boundary.unfold_all(), Boundary.unfold_none()]
    assert unfold_equivalent_calls(result.trace, boundaries).ok
    frame = result.trace.children[0]
    frame.jumps = 1
    assert not unfold_equivalent_calls(result.trace, boundaries).ok
    frame.jumps = 0
    frame.fast = False
    assert not unfold_equivalent_calls(result.trace, boundaries).ok


def test_fnref_nested_in_card_and_tuple_json_and_dependencies():
    value = Card("ops", "pair", (FnRef("inc"), (FnRef("dec"), Card("ops", "one", (FnRef("id"),)))))
    assert decode(encode(value)) == value
    expression = n.Call("apply", (n.Lit(value), n.Lit((FnRef("square"), Card("n", "v")))))
    assert n.from_json(n.to_json(expression)) == expression
    assert n.references(expression) == {"apply"}
    assert n.all_dependencies(expression) == {"apply", "square", "inc", "dec", "id"}
    assert n.all_dependencies(n.Lit(FnRef("inc"))) == {"inc"}
    assert n.operation_literals(expression) == {"square", "inc", "dec", "id"}


@given(names=st.lists(st.text(min_size=1, max_size=5), min_size=1, max_size=6),
       integer=st.integers(-4, 4))
@settings(max_examples=90, deadline=None)
def test_nested_function_values_round_trip(names, integer):
    value = integer
    for name in names:
        value = Card("ops", "box", (value, (FnRef(name),)))
    assert decode(encode(value)) == value
    expression = n.Lit(value)
    assert n.from_json(n.to_json(expression)) == expression


def test_fnref_in_memoized_recursive_argument():
    expression = n.Rec("same", ("fn",), n.Var("fn"), (n.Lit(FnRef("inc")),), memo=True)
    assert evaluate(expression).outcome == Ok(FnRef("inc"))
