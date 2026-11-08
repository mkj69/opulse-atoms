"""Scoped conjecture-and-check law discovery."""

import json
from dataclasses import replace

from opulse.atoms import nodes as n
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.gen_v2 import laws
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import Candidate, Entry, GenState, Signature
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.operation import MOVES
from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import toy


def _state():
    return generate(toy.gen_world(("operation",)), 12, 9, per_kind_min=0,
                    layer_target=1, moves=MOVES[:3])


def test_discovery_rechecks_and_exports_ascii(tmp_path):
    state = _state()
    found = laws.discover(state, 30, seed=17)
    assert found
    assert all(item.kind == "law" and laws.check(state, item, 17) == item.evidence for item in found)
    assert all(item.depends_on == tuple(sorted(n.references(item.statement))) for item in found)
    assert all(item.layer == 1 + max(state.layer(name) for name in item.depends_on) for item in found)
    assert [item.shortens for item in found] == sorted(
        [item.shortens for item in found], key=lambda score: (-score["total_over_scope"], -score["sites"]))
    output = tmp_path / "laws.json"
    laws.write_json(found, output, state)
    content = output.read_text()
    assert content.isascii()
    assert json.loads(content)["schema"] == "opulse.gen_v2.law/1"
    assert all(item.text(state).startswith(f"law #{item.name}:") for item in found)


def test_false_and_degenerate_conjectures_refused():
    state = _state()
    invented = next(item for item in state.entries.values() if item.signature == Signature(("int",), "int"))
    variable = n.Var("a")
    bad = n.Call("eq", (n.Call(invented.name, (variable,)), n.Lit(10**10)))
    law = laws.LawRecord("l0", bad, (("a", "int"),), ("eq", invented.name), invented.layer + 1)
    assert laws.check(state, law) is None
    trivial = replace(law, statement=n.Call("eq", (variable, variable)), depends_on=("eq",), layer=1)
    assert laws.check(state, trivial) is None
    mistyped = replace(law, vars=(("a", "bool"),))
    assert laws.check(state, mistyped) is None
    verified = laws.discover(state, 1, seed=4)[0]
    old_fuel = state.world.fuel
    state.world.fuel = 0
    try:
        assert laws.check(state, verified, seed=4) is None
    finally:
        state.world.fuel = old_fuel


def test_deterministic_and_commutative_invented_operation():
    state = _state()
    name = state.names.fresh("operation")
    body = n.Call("add", (n.Call("add", (n.Var("a"), n.Var("b"))), n.Lit(37)))
    spec = OperationSpec(name, "combine", (Edge("int"), Edge("int")), Edge("int"),
                         "symmetric shifted addition", extra={"input_names": ["a", "b"]})
    definition = Definition(name, "operation", "invented", 1, ("add",), spec, body)
    result = admit(state, Candidate(definition, Signature(("int", "int"), "int"), "test.symmetric"))
    assert isinstance(result, Entry), result
    first = laws.discover(state, 100, seed=5)
    second = laws.discover(state, 100, seed=5)
    assert first == second
    assert any(isinstance(law.statement, n.Call) and law.statement.fn == "eq"
               and all(isinstance(side, n.Call) and side.fn == name for side in law.statement.args)
               and law.vars == (("a", "int"), ("b", "int")) for law in first)
    commutative = next(law for law in first if isinstance(law.statement, n.Call)
                       and all(isinstance(side, n.Call) and side.fn == name
                               for side in law.statement.args))
    swapped = replace(commutative, statement=n.Call("eq", tuple(reversed(commutative.statement.args))))
    renamed = replace(commutative, statement=n.Call("eq", (
        n.Call(name, (n.Var("x"), n.Var("y"))), n.Call(name, (n.Var("y"), n.Var("x"))))),
        vars=(("x", "int"), ("y", "int")))
    assert laws._key(commutative, state) == laws._key(swapped, state) == laws._key(renamed, state)
    bounded = laws.check(state, commutative, seed=5, bound=8)
    assert bounded["method"] == "bounded"
    assert len(bounded["scope"]["checked_inputs"]) == 4
    assert bounded["scope"]["domain"]["int"] == [
        {"t": "int", "v": 0}, {"t": "int", "v": -1}]
    assert bounded["scope"]["distinct_inputs"] == 4


def test_shortening_counts_reused_call_sites():
    state = _state()
    first = state.names.fresh("operation")
    body = n.Call("maxv", (n.Var("x"), n.Lit(2)))
    spec = OperationSpec(first, "transform", (Edge("int"),), Edge("int"),
                         "floor at two", extra={"input_names": ["x"]})
    assert isinstance(admit(state, Candidate(Definition(first, "operation", "invented", 1,
                             ("maxv",), spec, body), Signature(("int",), "int"), "test.floor")), Entry)
    second = state.names.fresh("operation")
    nested = n.Call(first, (n.Call(first, (n.Var("x"),)),))
    body = n.Call("add", (nested, n.Var("x")))
    spec = OperationSpec(second, "transform", (Edge("int"),), Edge("int"),
                         "reuse the floor", extra={"input_names": ["x"]})
    assert isinstance(admit(state, Candidate(Definition(second, "operation", "invented", 2,
                             ("add", first), spec, body), Signature(("int",), "int"), "test.reuse")), Entry)
    statement = n.Call("eq", (nested, n.Call(first, (n.Var("x"),))))
    law = laws.LawRecord("l0", statement, (("x", "int"),), ("eq", first), 2)
    assert laws.check(state, law)
    score = laws.value(state, law)
    assert score["sites"] >= 1 and score["steps_saved_per_use"] > 0


def test_finding_1_bounded_enumerates_distinct_prefix_and_samples_are_labeled():
    state = _state()
    name = state.names.fresh("operation")
    body = n.Call("add", (n.Var("x"), n.Lit(37)))
    spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"),
                         "shift by 37", extra={"input_names": ["x"]})
    assert isinstance(admit(state, Candidate(Definition(name, "operation", "invented", 1,
                             ("add",), spec, body), Signature(("int",), "int"), "test.shift")), Entry)
    statement = n.Call("eq", (n.Call(name, (n.Var("a"),)), n.Call("add", (n.Var("a"), n.Lit(37)))))
    law = laws.LawRecord("prefix", statement, (("a", "int"),), ("add", "eq", name), 2)
    bounded = laws.check(state, law, bound=8, seed=0)
    assert bounded["method"] == "bounded"
    assert bounded["scope"]["distinct_inputs"] == bounded["scope"]["size"] == 8
    assert bounded["scope"]["domain"]["int"] == [
        {"t": "int", "v": value} for value in sorted(state.sorts["int"].values, key=abs)[:8]]
    assert len(bounded["scope"]["checked_inputs"]) == 8
    sampled = laws.check(state, law, bound=8, seed=0, sampled=True)
    assert sampled["method"] == "sampled"
    assert sampled["scope"]["distinct_inputs"] == len(sampled["scope"]["checked_inputs"])
    full_probes = laws.check(state, law, bound=12)
    assert full_probes["method"] == "bounded"
    assert full_probes["scope"]["size"] == full_probes["scope"]["distinct_inputs"] == 12
    assert len(full_probes["scope"]["checked_inputs"]) == 12


def test_finding_29_only_certified_finite_full_product_is_exhaustive():
    state = _state()
    name = state.names.fresh("operation")
    body = n.Call("add", (n.Var("a"), n.Lit(37)))
    spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"), "shift by 37",
                         extra={"input_names": ["a"]})
    assert isinstance(admit(state, Candidate(Definition(name, "operation", "invented", 1,
                             ("add",), spec, body), Signature(("int",), "int"), "test.shift")), Entry)
    statement = n.Call("eq", (n.Call(name, (n.Var("a"),)), body))
    law = laws.LawRecord("scope", statement, (("a", "int"),), ("add", "eq", name), 2)
    evidence = laws.check(state, law, bound=len(state.sorts["int"].values))
    assert evidence["method"] == "bounded"
    assert len(evidence["scope"]["checked_inputs"]) == len(state.sorts["int"].values)
    state.sorts["int"] = replace(state.sorts["int"], finite=True)
    assert laws.check(state, law, bound=12)["method"] == "bounded"
    state.requests[name] = replace(state.requests[name], method="exhaustive")
    assert laws.check(state, law, bound=12)["method"] == "exhaustive"
    original = state.requests[name]
    state.requests[name] = replace(original, domain=original.domain[:-1])
    assert laws.check(state, law, bound=12)["method"] == "bounded"
    state.requests[name] = original
    assert laws.check(state, law, bound=8)["method"] == "bounded"

    world = toy.gen_world(("operation",))
    world.sorts["int"] = replace(world.sorts["int"], finite=True)
    finite_state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect),
                            dict(world.sorts))
    finite_name = finite_state.names.fresh("operation")
    finite_spec = replace(spec, name=finite_name)
    finite_body = n.Call("add", (n.Var("a"), n.Lit(37)))
    result = admit(finite_state, Candidate(Definition(finite_name, "operation", "invented", 1,
                   ("add",), finite_spec, finite_body), Signature(("int",), "int"), "test.finite"))
    assert isinstance(result, Entry), result
    assert finite_state.requests[finite_name].method == "exhaustive"
    finite_statement = n.Call("eq", (n.Call(finite_name, (n.Var("a"),)), finite_body))
    finite_law = laws.LawRecord("finite", finite_statement, (("a", "int"),),
                                ("add", "eq", finite_name), 2)
    assert laws.check(finite_state, finite_law, bound=12)["method"] == "exhaustive"


def test_finding_5_unreachable_and_reflexive_statements_are_rejected():
    state = _state()
    name = next(entry.name for entry in state.entries.values() if entry.signature == Signature(("int",), "int"))
    call = n.Call(name, (n.Var("a"),))
    reflexive = n.Call("eq", (call, call))
    statement = n.Case(((n.Test(n.Lit(True)), n.Lit(True)),), reflexive)
    law = laws.LawRecord("taut", statement, (("a", "int"),), ("eq", name), state.layer(name) + 1)
    assert laws.check(state, law) is None
    assert laws.check(state, replace(law, statement=reflexive)) is None
    condition = n.Test(n.Call("eq", (n.Var("a"), n.Var("a"))))
    assert laws.check(state, replace(law, statement=n.Case(((condition, n.Lit(True)),),
                                                            reflexive))) is None
    constant = n.Case(((n.Test(n.Call("eq", (call, n.Lit(0)))), n.Lit(True)),), n.Lit(True))
    assert laws.check(state, replace(law, statement=constant)) is None


def test_finding_5_dynamic_unreached_definition_requires_call_witness():
    state = _state()
    name = next(entry.name for entry in state.entries.values() if entry.signature == Signature(("int",), "int"))
    state.sorts["int"] = replace(state.sorts["int"], values=(1, 2))
    variable = n.Var("a")
    statement = n.Case(((n.Test(n.Call("is_pos", (variable,))), n.Lit(True)),),
                       n.Call("eq", (n.Call(name, (variable,)), n.Lit(0))))
    law = laws.LawRecord("unreached", statement, (("a", "int"),),
                         ("eq", "is_pos", name), state.layer(name) + 1)
    assert laws.check(state, law) is None


def test_finding_6_asymmetric_relation_is_not_deduplicated():
    state = _state()
    left = n.Call("add", (n.Var("x"), n.Lit(1)))
    right = n.Var("y")
    law = laws.LawRecord("order", n.Call("lt", (left, right)),
                         (("x", "int"), ("y", "int")), ("add", "lt"), 1)
    swapped = replace(law, statement=n.Call("lt", (right, left)))
    assert laws._key(law, state) != laws._key(swapped, state)
    equality = replace(law, statement=n.Call("eq", (left, right)))
    assert laws._key(equality, state) == laws._key(replace(equality, statement=n.Call("eq", (right, left))), state)


def test_finding_7_shortens_is_per_use_mean_not_sum_of_trials():
    state = _state()
    name = state.names.fresh("operation")
    spec = OperationSpec(name, "transform", (Edge("int"),), Edge("int"),
                         "floor at two", extra={"input_names": ["x"]})
    assert isinstance(admit(state, Candidate(Definition(name, "operation", "invented", 1,
                             ("maxv",), spec, n.Call("maxv", (n.Var("x"), n.Lit(2)))),
                             Signature(("int",), "int"), "test.floor")), Entry)
    nested = n.Call(name, (n.Call(name, (n.Var("x"),)),))
    consumer = state.names.fresh("operation")
    consumer_spec = OperationSpec(consumer, "transform", (Edge("int"),), Edge("int"),
                                  "reuse floor", extra={"input_names": ["x"]})
    assert isinstance(admit(state, Candidate(Definition(consumer, "operation", "invented", 2,
                             ("add", name), consumer_spec, n.Call("add", (nested, n.Var("x")))),
                             Signature(("int",), "int"), "test.consumer")), Entry)
    statement = n.Call("eq", (nested, n.Call(name, (n.Var("x"),))))
    law = laws.LawRecord("floor", statement, (("x", "int"),), ("eq", name), 2)
    score = laws.value(state, law)
    assert set(score) == {"sites", "steps_saved_per_use", "total_over_scope"}
    assert score["sites"] >= 1 and score["steps_saved_per_use"] == 1
    assert score["total_over_scope"] == score["sites"] * score["steps_saved_per_use"]


def test_literal_sort_lookup_reads_sort_values():
    from opulse.atoms import nodes as n
    from opulse.gen_v2 import laws
    from opulse.gen_v2.base import GenState, Sort
    from opulse.gen_v2.library import GenLibrary
    from opulse.gen_v2.worlds import toy

    world = toy.gen_world(("operation",))
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))
    state.sorts["pair"] = Sort("pair", ((1, 2), (3, 4)))
    assert laws._sort(state, n.Lit((3, 4)), {}) == "pair"


def test_discovery_survives_host_type_errors():
    """geometry's sorted_items raises TypeError on mixed values; discovery must skip, not crash."""
    from opulse.gen_v2 import laws
    from opulse.gen_v2.run import generate
    from opulse.gen_v2.worlds import geometry

    state = generate(geometry.gen_world(), 40, 1, per_kind_min=0, layer_target=0, time_limit=120)
    assert isinstance(laws.discover(state, max_laws=20, seed=1), list)
