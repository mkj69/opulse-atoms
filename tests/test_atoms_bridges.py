"""Bridges, partial domains, composition and the commuting diagram."""

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import (
    BridgeContext,
    bridge_defn,
    check_bridge,
    compose_bridges,
    verify_bridge,
)
from opulse.atoms.library import Library, VerifyRequest, register_kind
from opulse.atoms.spec import BridgeSpec, Definition, Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok, outcome_equal
from opulse.atoms.world import WorldDecl


def library(name="numbers", atoms=(), sorts=("Int",)):
    world = WorldDecl(name, 1, "atoms-v2", {}, {}, tuple(ObjectSpec(sort, "given") for sort in sorts),
                      (), {"nodes": list(n.NODE_NAMES), "recursion": "measure"},
                      {"truth": "int", "probes": [], "capabilities": {}}, {},
                      open_kinds=("operation", "bridge"))
    return Library(world, atoms)


def definition(spec):
    return Definition(spec.name, "bridge", "invented", 1, tuple(sorted(n.references(spec.map))),
                      spec, bridge_defn(spec).body)


def request(values, **extra):
    return VerifyRequest("bounded", tuple((value,) for value in values),
                         {"domain": "values up to bound 5", "size": len(values)}, extra=extra)


def pair_library():
    return library(atoms=(kernel.Atom("pair_add", 2, lambda a, b: (a[0] + b[0], a[1] + b[1])),
                          kernel.Atom("pair_neg", 1, lambda a: (a[1], a[0])),
                          kernel.Atom("difference", 1, lambda a: a[0] - a[1]),
                          kernel.Atom("add", 2, lambda a, b: a + b),
                          kernel.Atom("neg", 1, lambda a: -a)), sorts=("Pair", "Int"))


def abs_spec(map_=None, domain=None):
    return BridgeSpec("abs_pair", "Pair", "Int", map_ or n.Call("difference", (n.Var("x"),)),
                      domain, (("pair_add", "add"), ("pair_neg", "neg")))


def test_bridge_defn_partial_and_inline_equivalence():
    spec = BridgeSpec("positive", "Int", "Int", n.Call("inc", (n.Var("x"),)),
                      n.Call("positive_test", (n.Var("x"),)))
    scope = kernel.DictScope((kernel.Atom("inc", 1, lambda x: x + 1),
                              kernel.Atom("positive_test", 1, lambda x: x >= 0)), (bridge_defn(spec),))
    for value in (-1, 0, 4):
        call = n.Call("positive", (n.Lit(value),))
        direct = kernel.evaluate(call, scope=scope)
        unfolded = kernel.evaluate(kernel.inline(call, scope), scope=scope)
        assert outcome_equal(direct.outcome, unfolded.outcome)
        assert direct.steps == unfolded.steps
    assert kernel.call("positive", (-1,), scope).outcome == Bottom("outside_domain")


@settings(deadline=None)
@given(st.integers(-15, 15))
def test_bridge_named_call_matches_inline_for_random_inputs(value):
    spec = BridgeSpec("shift", "Int", "Int", n.Call("inc", (n.Var("x"),)))
    scope = kernel.DictScope((kernel.Atom("inc", 1, lambda item: item + 1),), (bridge_defn(spec),))
    call = n.Call("shift", (n.Lit(value),))
    named = kernel.evaluate(call, scope=scope)
    inline = kernel.evaluate(kernel.inline(call, scope), scope=scope)
    assert outcome_equal(named.outcome, inline.outcome) and named.steps == inline.steps


def test_invented_pair_to_given_int_commutes():
    register_kind("bridge", check_bridge, verify_bridge)
    lib = pair_library()
    spec = abs_spec()
    lib.write(definition(spec))
    assert not check_bridge(lib.get("abs_pair"), lib)
    lib.check("abs_pair")
    values = [(left, right) for left in range(6) for right in range(6)]
    verification = request(values)
    result = verify_bridge(lib.get("abs_pair"), lib, verification)
    assert result.ok, result.problems
    assert set(result.checks) == {"commutes", "total_on_domain"}
    assert verification.scope["pairs_checked"] == len(values) ** 2 + len(values)
    assert verification.scope["domain_size"] == len(values)
    assert kernel.call("abs_pair", ((5, 2),),
                       lib.scope().extend((bridge_defn(spec),))).outcome == Ok(3)


def test_invented_pair_of_nats_to_given_int():
    pair = ObjectSpec("PairNat", "compose", tags={"pair": (("pos", "int"), ("neg", "int"))})
    lib = library(atoms=(
        kernel.Atom("pair_add", 2, lambda left, right: Card(
            "PairNat", "pair", (left.fields[0] + right.fields[0], left.fields[1] + right.fields[1]))),
        kernel.Atom("pair_neg", 1, lambda value: Card(
            "PairNat", "pair", (value.fields[1], value.fields[0]))),
        kernel.Atom("difference", 1, lambda value: value.fields[0] - value.fields[1]),
        kernel.Atom("add", 2, lambda left, right: left + right),
        kernel.Atom("neg", 1, lambda value: -value),
    ))
    lib.world = replace(lib.world, open_kinds=("object", "bridge", "operation"))
    lib.write(Definition("PairNat", "object", "invented", 1, (), pair, None))
    lib.check("PairNat")
    lib.make_callable("PairNat", [(0, 0)])
    spec = replace(abs_spec(), source="PairNat")
    values = [Card("PairNat", "pair", (left, right)) for left in range(6) for right in range(6)]
    verification = request(values)
    assert not check_bridge(definition(spec), lib)
    result = verify_bridge(definition(spec), lib, verification)
    assert result.ok, result.problems
    assert verification.scope["pairs_checked"] == 36 * 36 + 36


def test_cross_world_failure_detects_noncommuting_pair():
    hours = library("clock", (kernel.Atom("add_hour", 2, lambda a, b: (a + b) % 12),), ("Hour",))
    integers = library("integers", (kernel.Atom("add_int", 2, lambda a, b: a + b),), ("Int",))
    context = BridgeContext(hours, integers)
    spec = BridgeSpec("to_int", "clock@1:Hour", "integers@1:Int", n.Var("x"),
                      interface=(("add_hour", "add_int"),))
    assert not check_bridge(definition(spec), context)
    failed = verify_bridge(definition(spec), context, request(range(12), bridge_context=context,
                                                              pairs=((8, 5),)))
    assert not failed.ok and "(8, 5)" in failed.problems[0]
    assert failed.checks == ()
    assert failed.steps


def test_cross_world_target_map_calls_and_non_source_outputs():
    hours = library("clock", (kernel.Atom("is_zero_hour", 1, lambda hour: hour == 0),), ("Hour",))
    integers = library("integers", (kernel.Atom("to_int_op", 1, lambda hour: hour),
                                    kernel.Atom("is_zero_int", 1, lambda value: value == 0)), ("Int",))
    hours.world = replace(hours.world, operations=(
        OperationSpec("is_zero_hour", "decide", (Edge("Hour"),), Edge("bool"), "zero?"),))
    integers.world = replace(integers.world, operations=(
        OperationSpec("is_zero_int", "decide", (Edge("Int"),), Edge("bool"), "zero?"),))
    spec = BridgeSpec("to_int", "clock@1:Hour", "integers@1:Int",
                      n.Call("to_int_op", (n.Var("x"),)),
                      interface=(("is_zero_hour", "is_zero_int"),))
    context = BridgeContext(hours, integers)
    verification = request((0, 2), bridge_context=context)
    assert not check_bridge(definition(spec), context)
    assert verify_bridge(definition(spec), context, verification).ok
    assert verification.scope["pairs_checked"] == 2


def test_partial_domain_skips_and_rejects_non_total_map():
    lib = library(atoms=(kernel.Atom("nonnegative", 1, lambda x: x >= 0),
                         kernel.Atom("map", 1, lambda x: x if x != 2 else Bottom("hole")),))
    spec = BridgeSpec("positive", "Int", "Int", n.Call("map", (n.Var("x"),)),
                      n.Call("nonnegative", (n.Var("x"),)))
    domain = request((-2, -1, 0, 1))
    assert verify_bridge(definition(spec), lib, domain).ok
    assert domain.scope["skipped"] == 2
    assert domain.scope["pairs_checked"] == 0
    assert "total_on_domain" in verify_bridge(definition(spec), lib, request((-1, 2))).problems[0]


def test_partial_bridge_skips_pairs_with_outside_domain_input_or_output():
    lib = library(atoms=(kernel.Atom("nonnegative", 1, lambda value: value >= 0),
                         kernel.Atom("neg", 1, lambda value: -value),
                         kernel.Atom("add", 2, lambda left, right: left + right)))
    spec = BridgeSpec("identity", "Int", "Int", n.Var("x"),
                      n.Call("nonnegative", (n.Var("x"),)),
                      (("neg", "neg"), ("add", "add")))
    verification = request((-1, 0, 1), pairs=((-2, 1), (0, 1)))
    result = verify_bridge(definition(spec), lib, verification)
    assert result.ok, result.problems
    assert verification.scope["pairs_checked"] == 2
    assert verification.scope["skipped"] == 3


def test_checker_reports_unbound_unknown_arity_and_sorts():
    lib = library(atoms=(kernel.Atom("inc", 1, lambda x: x + 1),))
    spec = BridgeSpec("bad", "Missing", "Int", n.Call("inc", (n.Var("y"), n.Var("x"))),
                      n.Call("unknown", (n.Var("x"),)), (("inc", "missing"),))
    problems = check_bridge(definition(spec), lib)
    assert any("unknown source sort" in issue for issue in problems)
    assert any("unbound variable y" in issue for issue in problems)
    assert any("expects 1" in issue for issue in problems)
    assert any("unresolved" in issue for issue in problems)


def test_composition_keeps_domains_not_evidence():
    first = definition(BridgeSpec("double", "Int", "Int", n.Call("double_op", (n.Var("x"),)),
                                  n.Call("positive", (n.Var("x"),))))
    second = definition(BridgeSpec("increment", "Int", "Int", n.Call("inc", (n.Var("x"),)),
                                   n.Call("small", (n.Var("x"),))))
    composite = compose_bridges(first, second)
    assert composite.depends_on == ("double", "increment")
    assert composite.evidence is None and composite.contract is None
    scope = kernel.DictScope((kernel.Atom("double_op", 1, lambda x: 2 * x),
                              kernel.Atom("inc", 1, lambda x: x + 1),
                              kernel.Atom("positive", 1, lambda x: x >= 0),
                              kernel.Atom("small", 1, lambda x: x < 6)),
                             (bridge_defn(first.spec), bridge_defn(second.spec), bridge_defn(composite.spec)))
    assert kernel.call(composite.name, (2,), scope).outcome == Ok(5)
    assert kernel.call(composite.name, (3,), scope).outcome == Bottom("outside_domain")
    assert kernel.call(composite.name, (-1,), scope).outcome == Bottom("outside_domain")


@settings(deadline=None)
@given(st.lists(st.tuples(st.integers(-10, 10), st.integers(-10, 10)), min_size=1, max_size=6))
def test_random_domains_commute(values):
    result = verify_bridge(definition(abs_spec()), pair_library(), request(values))
    assert result.ok, result.problems


@settings(deadline=None)
@given(st.integers(-8, 8), st.integers(-8, 8))
def test_perturbed_map_is_detected_when_affected_value_is_in_domain(left, right):
    lib = pair_library()
    lib.atoms = (*lib.atoms, kernel.Atom("perturbed", 1, lambda pair: pair[0] - pair[1] +
                                       (pair == (left, right))))
    bad = abs_spec(n.Call("perturbed", (n.Var("x"),)))
    result = verify_bridge(definition(bad), lib, request(((left, right), (0, 0))))
    assert not result.ok
    assert any("commutes" in issue for issue in result.problems)
