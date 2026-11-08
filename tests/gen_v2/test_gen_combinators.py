import itertools
import json
import os
import random
from collections import Counter
from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.spec import (
    CombinatorSpec,
    Definition,
    Edge,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Ok
from opulse.gen_v2 import fast
from opulse.gen_v2.admit import admit
from opulse.gen_v2.audit import _domain, _mixed_expression, audit
from opulse.gen_v2.base import Candidate, Entry, GenState, Rejection, Signature, Sort
from opulse.gen_v2.kinds import combinators as combinator_hook
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.combinator import MOVES, _base_tester, card_measure
from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import lists, permutation, rhythm, toy


def _state():
    world = toy.gen_world()
    return GenState(world, GenLibrary(world.decl, world.atoms, world.dialect), dict(world.sorts))


def _move(name):
    return next(move for move in MOVES if move.name == name)


def _predicate(state):
    body = n.Call("lt", (n.Var("arg0"), n.Lit(2)))
    spec = OperationSpec("f_pred", "decide", (Edge("int"),), Edge("bool"), "x < 2")
    definition = Definition("f_pred", "operation", "invented", 1, ("lt",), spec, body)
    assert isinstance(admit(state, Candidate(definition, Signature(("int",), "bool"), "op.test")), Entry)


def test_rhythm_host_type_error_refuses_combinator_at_admission():
    world = rhythm.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                       world.extra_scope), dict(world.sorts))
    body = n.Call("f", (n.Var("x"), n.Lit(0)))
    spec = CombinatorSpec("k_bad", ("f", "x"), ("f",), body)
    request = combinator_hook.family_request(state, ("any",), ("lt", "eq"))
    assert request is not None
    candidate = Candidate(Definition("k_bad", "combinator", "invented", 1, (), spec, body),
                          Signature(("any",), "bool", (Signature(("any", "any"), "bool"),)),
                          "comb.test", request, meta={"slot_families": {"f": ("lt", "eq")}})
    refusal = admit(state, candidate)
    assert isinstance(refusal, Rejection) and refusal.stage == "callable"
    assert "TypeError" in refusal.reason and "k_bad" not in state.entries


def test_combinator_rejects_wrong_slot_family_before_evaluation():
    state = _state()
    candidate = _move("comb.chain")(state, random.Random(11))
    assert candidate is not None
    slot = candidate.defn.spec.op_params[0]
    candidate.meta["slot_families"][slot] = ("lt",)
    refusal = admit(state, candidate)
    assert isinstance(refusal, Rejection) and refusal.stage == "callable"
    assert "incompatible signature" in refusal.reason


def test_audit_mixed_expression_stays_within_combinator_probe_scope():
    state = _state()
    _predicate(state)
    candidate = _move("comb.guard")(state, random.Random(11))
    assert candidate is not None
    entry = admit(state, candidate)
    assert isinstance(entry, Entry)
    assignments = itertools.product(*(candidate.meta["slot_families"][slot]
                                      for slot in candidate.defn.spec.op_params))
    expected = tuple(tuple(kernel.FnRef(name) for name in names) + values
                     for names in assignments for values in candidate.request.domain)
    assert _domain(state, entry, state.library.get(entry.name)) == expected
    sort = entry.signature.inputs[0]
    assert sort == "int"
    state.library.add_atoms((kernel.Defn("bad_probe", ("x",), n.Lit((0,)), kind="operation"),
                             kernel.Defn("outside_probe", ("x",), n.Lit(8), kind="operation")))
    for name in ("bad_probe", "outside_probe"):
        state.entries[name] = Entry(name, "operation", 1, Signature((sort,), sort), "test", ())
        state.requests[name] = VerifyRequest("bounded", ((candidate.request.domain[0][0],),),
                                             {"domain": "probe", "size": 1})
    args = tuple(kernel.FnRef(candidate.meta["slot_families"][slot][0])
                 for slot in candidate.defn.spec.op_params) + candidate.request.domain[0]
    expression = _mixed_expression(state, entry, args, random.Random(1))
    assert "bad_probe" not in n.references(expression)
    assert "outside_probe" not in n.references(expression)
    outcome = kernel.evaluate(expression, scope=state.library.scope()).outcome
    assert isinstance(outcome, Ok)


def test_each_available_template_verifies_with_typed_family():
    state = _state()
    _predicate(state)
    for move in MOVES:
        if move.name in ("comb.fold", "app.apply"):
            continue
        candidate = move(state, random.Random(11))
        assert candidate is not None, move.name
        entry = admit(state, candidate)
        assert isinstance(entry, Entry), (move.name, entry)
        record = state.library.get(entry.name)
        assert record.status == "promoted"
        assert record.evidence.method == "bounded"
        assert set(candidate.request.extra["op_family"]) == set(record.evidence.scope["op_family"])
        assert entry.signature.op_inputs
        assert 3 <= len(candidate.request.extra["op_family"]) <= 6
        assert "unfold_equivalence" in record.evidence.checks
    assert state.entries[next(reversed(state.entries))].meta["derived_from"]
    composed = state.entries[next(reversed(state.entries))]
    assert composed.meta["derived_from"][0] in composed.depends_on
    assert any(isinstance(node, n.Call) and node.fn == composed.meta["derived_from"][0]
               for node in n.walk(state.library.get(composed.name).body))
    search_entry = next(entry for entry in state.entries.values() if entry.move == "comb.search")
    search_spec = state.library.get(search_entry.name).spec
    assert n.from_json(n.to_json(search_spec.body)) == search_spec.body
    search_result = state.library.run(search_entry.name, (kernel.FnRef("is_zero"), -1))
    assert search_result.outcome == Bottom("no_branch")
    assert state.library.run(search_entry.name, (kernel.FnRef("is_pos"), 0)).outcome == Bottom("no_branch")
    application = _move("app.apply")(state, random.Random(17))
    assert application is not None
    assert any(isinstance(node, n.Lit) and isinstance(node.value, kernel.FnRef)
               for node in n.walk(application.defn.body))
    assert application.meta["combinator"] in application.defn.depends_on
    assert application.defn.depends_on == tuple(sorted(n.references(application.defn.body) |
                                                       n.operation_literals(application.defn.body)))
    assert not any(isinstance(node, n.Let) and node.name.startswith("used_slot_")
                   for node in n.walk(application.defn.body))
    assert isinstance(admit(state, application), Entry)


def test_closed_combinator_refused_by_admit_and_core_library():
    world = toy.gen_world(open_kinds=("operation",))
    world.decl = replace(world.decl, open_kinds=("operation",))
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    source = _state()
    candidate = _move("comb.chain")(source, random.Random(11))
    assert isinstance(admit(state, candidate), Rejection)
    assert state.rejections == []
    with pytest.raises(PipelineError, match="closed"):
        state.library.write(candidate.defn)


def test_predicate_composition_forwards_both_operation_slots():
    state = _state()
    _predicate(state)
    original = admit(state, _move("comb.blend")(state, random.Random(11)))
    assert isinstance(original, Entry), original
    derived = _move("comb.compose")(state, random.Random(7))
    assert derived is not None
    assert original.name in derived.defn.depends_on
    assert any(isinstance(node, n.Var) and node.name == "slot0"
               for node in n.walk(derived.defn.body))
    assert isinstance(admit(state, derived), Entry)


def test_card_measure_uses_card_projections_and_typed_int_combiners():
    world = permutation.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms, world.dialect,
                                       world.extra_scope), dict(world.sorts))

    def check():
        candidate = card_measure(state, random.Random(0))
        assert candidate is not None
        assert candidate.signature.inputs == ("sequence",)
        assert candidate.signature.output == "int"
        entry = admit(state, candidate)
        assert isinstance(entry, Entry), entry
        assert entry.layer >= 1
        for seed in range(1, 12):
            variant = card_measure(state, random.Random(seed))
            if variant is not None:
                admit(state, variant)
        assert state.max_layer("combinator") >= 8

    fast.deep(check)


def test_slot_independent_combinator_is_rejected():
    state = _state()
    candidate = _move("comb.guard")(state, random.Random(11))
    assert candidate is not None
    body = n.Call("f", (n.Var("x"),))
    spec = replace(candidate.defn.spec, body=body)
    candidate.defn = replace(candidate.defn, spec=spec, body=body, depends_on=())
    def check():
        results = combinator_hook.run(state, candidate, candidate.request)
        checks, problems = combinator_hook.verify(state, candidate, candidate.request, results)
        assert not checks
        assert problems == [f"behaviour does not depend on operation slot {candidate.defn.spec.op_params[0]}"]

    fast.deep(check)


def test_bounded_combinator_domain_is_complete_prefix_and_rejects_scattered_values():
    state = _state()
    candidate = _move("comb.chain")(state, random.Random(0))
    assert candidate is not None
    request = candidate.request
    bound = request.scope["bound"]
    assert request.domain == tuple((value,) for value in state.sorts["int"].values[:bound])
    scattered = replace(request, domain=request.domain[:-1] + ((state.sorts["int"].values[-1],),))

    def check():
        results = combinator_hook.run(state, candidate, scattered)
        _, problems = combinator_hook.verify(state, candidate, scattered, results)
        assert problems == ["bounded domain must be the complete probe-value prefix"]

    fast.deep(check)


def test_binary_combinator_domain_is_cartesian_prefix():
    state = _state()
    candidate = _move("comb.weave")(state, random.Random(9))
    assert candidate is not None
    request = candidate.request
    bound = request.scope["bound"]
    assert request.domain == tuple(itertools.product(state.sorts["int"].values[:bound], repeat=2))
    assert request.scope["size"] == len(request.domain)


def test_application_is_exact_substitution_even_on_bottom_and_short_circuit():
    def check():
        state = _state()
        _predicate(state)
        chain = admit(state, _move("comb.chain")(state, random.Random(0)))
        assert isinstance(chain, Entry)
        application = _move("app.apply")(state, random.Random(0))
        assert application is not None
        assert isinstance(application.defn.body, n.Call)
        assert application.defn.depends_on == tuple(sorted(n.references(application.defn.body) |
                                                           n.operation_literals(application.defn.body)))
        assert set(application.meta["plugged"]) <= set(application.defn.depends_on)
        scope = state.library.scope().extend([kernel.Defn(application.defn.name, ("arg0",),
                                                          application.defn.body)])
        spec = state.library.get(application.meta["combinator"]).spec
        for value in (-3, 0, 2, 7):
            plugged = iter(application.meta["plugged"])
            direct_args = tuple(kernel.FnRef(next(plugged)) if param in spec.op_params else value
                                for param in spec.params)
            direct = fast.call(application.meta["combinator"], direct_args, scope, state.world.fuel)
            actual = fast.call(application.defn.name, (value,), scope, state.world.fuel)
            assert actual.outcome == direct.outcome
            assert actual.steps == direct.steps
        search = admit(state, _move("comb.search")(state, random.Random(2)))
        assert isinstance(search, Entry)
        observed = []
        for predicate, value in (("is_zero", -1), ("is_zero", 0)):
            body = n.Call(search.name, (n.Lit(kernel.FnRef(predicate)), n.Var("arg0")))
            named = state.library.scope().extend([kernel.Defn("test_application", ("arg0",), body)])
            direct = fast.call(search.name, (kernel.FnRef(predicate), value), named, state.world.fuel)
            applied = fast.call("test_application", (value,), named, state.world.fuel)
            assert applied.outcome == direct.outcome
            assert applied.steps == direct.steps
            observed.append(direct.outcome)
        assert observed[0] == Bottom("no_branch")
        short_body = n.Case(((n.Test(n.Call("is_zero", (n.Var("x"),))), n.Lit(11)),),
                            n.Call("f", (n.Var("x"),)))
        short_scope = state.library.scope().extend([
            kernel.Defn("fail", ("x",), n.Case((), None)),
            kernel.Defn("short", ("f", "x"), short_body, kind="combinator"),
            kernel.Defn("short_app", ("arg0",),
                        n.Call("short", (n.Lit(kernel.FnRef("fail")), n.Var("arg0"))))])
        for value in (0, 1):
            direct = fast.call("short", (kernel.FnRef("fail"), value), short_scope, state.world.fuel)
            applied = fast.call("short_app", (value,), short_scope, state.world.fuel)
            assert applied.outcome == direct.outcome
            assert applied.steps == direct.steps
            assert applied.outcome == (Bottom("no_branch") if value else Ok(11))

    fast.deep(check)


def test_fold_uses_a_recursive_sort_and_size_measure():
    world = toy.gen_world()
    operations = (("items.empty", ("items",), "bool", lambda items: len(items) == 0),
                  ("items.head", ("items",), "int", lambda items: items[0]),
                  ("items.tail", ("items",), "items", lambda items: items[1:]),
                  ("items.size", ("items",), "int", len))
    world.decl = replace(world.decl, objects=world.decl.objects + (ObjectSpec("items", "given"),),
                         operations=world.decl.operations + tuple(
                             OperationSpec(name, "transform", tuple(Edge(sort) for sort in inputs),
                                           Edge(output), name)
                             for name, inputs, output, _ in operations))
    world.atoms = tuple(world.atoms) + tuple(kernel.Atom(name, len(inputs), function)
                                           for name, inputs, _, function in operations)
    world.signatures.update({name: Signature(inputs, output)
                             for name, inputs, output, _ in operations})
    world.sorts["items"] = Sort("items", ((), (1,), (2, 3), (0, 1, 2)),
                                base="int", testers=("items.empty",), accessors=("items.head",))
    world.measures["items"] = [("items.tail", "items.size")]
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    candidate = _move("comb.fold")(state, random.Random(5))
    assert candidate is not None
    result = admit(state, candidate)
    assert isinstance(result, Entry), result
    assert state.library.get(result.name).evidence.method == "bounded"


def test_binary_weave_uses_both_slots():
    state = _state()
    candidate = _move("comb.weave")(state, random.Random(9))
    assert candidate is not None
    assert isinstance(admit(state, candidate), Entry)
    assert candidate.defn.spec.op_params == ("f", "g")
    assert all(any(isinstance(node, n.Call) and node.fn == slot
                   for node in n.walk(candidate.defn.body)) for slot in ("f", "g"))


def test_templates_respect_world_node_dialect():
    world = toy.gen_world()
    world.decl = replace(world.decl, combinators={**world.decl.combinators,
                                                  "nodes": ["Var", "Lit", "Call", "Let"]})
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    assert "Case" not in world.decl.opened_nodes()
    for name in ("comb.blend", "comb.guard", "comb.loop", "comb.search", "comb.fixpoint", "comb.fold"):
        assert _move(name)(state, random.Random(4)) is None
    candidate = _move("comb.chain")(state, random.Random(4))
    assert candidate is not None
    assert all(type(node).__name__ in world.decl.opened_nodes()
               for node in n.walk(candidate.defn.body) if isinstance(node, (n.Call, n.Case, n.Let, n.Rec)))


def test_measured_search_on_card_lists():
    world = lists.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    value = n.Var("arg0")
    predicates = (
        ("f_nonempty", n.Case(((n.Test(n.Call("is_empty", (value,))), n.Lit(False)),),
                               n.Lit(True)), ("is_empty",)),
        ("f_single", n.Case(((n.Test(n.Call("is_empty", (value,))), n.Lit(False)),),
                             n.Call("is_empty", (n.Call("tail", (value,)),))),
         ("is_empty", "tail")),
    )
    for name, body, dependencies in predicates:
        spec = OperationSpec(name, "decide", (Edge("list"),), Edge("bool"), name)
        definition = Definition(name, "operation", "invented", 1, dependencies, spec, body)
        assert isinstance(admit(state, Candidate(definition, Signature(("list",), "bool"),
                                                 "op.test")), Entry)
    candidate = _move("comb.search")(state, random.Random(4))
    assert candidate is not None
    assert candidate.signature.inputs == ("list",)
    assert isinstance(admit(state, candidate), Entry)
    report = audit(state)
    assert not [failure for failure in report.failures if failure.name == candidate.defn.name]


def test_base_tester_checks_each_sort_and_measure_once(monkeypatch):
    world = lists.gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    calls = []
    original = kernel.call

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(kernel, "call", counted)
    assert _base_tester(state, state.sorts["list"], "length") == "is_empty"
    first_count = len(calls)
    assert first_count > 0
    assert _base_tester(state, state.sorts["list"], "length") == "is_empty"
    assert len(calls) == first_count


def test_small_integrated_combinators_audit_and_serialize():
    state = generate(toy.gen_world(), 48, 149, per_kind_min=4, layer_target=0)
    combinators = [entry for entry in state.entries.values() if entry.kind == "combinator"]
    assert combinators
    for entry in combinators:
        definition = state.library.get(entry.name)
        assert Definition.from_dict(json.loads(json.dumps(definition.to_dict()))) == definition
    report = audit(state, sample=20)
    assert not [failure for failure in report.failures
                if failure.name in state.entries and state.entries[failure.name].kind == "combinator"]


def test_moves_are_deterministic_for_the_same_state_and_rng():
    for move in MOVES:
        if move.name in ("comb.fold", "comb.compose", "app.apply"):
            continue
        first, second = _state(), _state()
        _predicate(first)
        _predicate(second)
        candidate1 = move(first, random.Random(2026))
        candidate2 = move(second, random.Random(2026))
        assert candidate1 is not None and candidate2 is not None
        assert candidate1.defn.to_dict() == candidate2.defn.to_dict()
        assert candidate1.request.scope == candidate2.request.scope
        assert candidate1.meta == candidate2.meta
    first, second = _state(), _state()
    for state in (first, second):
        chain = _move("comb.chain")(state, random.Random(11))
        assert isinstance(admit(state, chain), Entry)
    for move_name in ("comb.compose", "app.apply"):
        first_candidate = _move(move_name)(first, random.Random(2026))
        second_candidate = _move(move_name)(second, random.Random(2026))
        assert first_candidate is not None and second_candidate is not None
        assert first_candidate.defn.to_dict() == second_candidate.defn.to_dict()
        assert first_candidate.meta == second_candidate.meta


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_toy_grows_many_combinators_and_applications():
    state = _state()
    _predicate(state)
    rng = random.Random(149)
    admitted = Counter()
    for _ in range(350):
        for move in MOVES:
            if move.name == "comb.fold":
                continue
            if move.kind == "combinator" and sum(
                    count for name, count in admitted.items() if name.startswith("comb.")) >= 60:
                continue
            candidate = move(state, rng)
            if candidate is not None and isinstance(admit(state, candidate), Entry):
                admitted[move.name] += 1
        if admitted["app.apply"] >= 100 and sum(count for name, count in admitted.items()
                                                 if name.startswith("comb.")) >= 60:
            break
    assert admitted["app.apply"] >= 100
    assert sum(count for name, count in admitted.items() if name.startswith("comb.")) >= 60
    assert sum(bool(admitted[move.name]) for move in MOVES if move.kind == "combinator") >= 6
    assert all(entry.kind != "combinator" or state.library.get(entry.name).evidence.method == "bounded"
               for entry in state.entries.values())


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
def test_integrated_toy_combinators_reach_deep_layers_and_serialize():
    state = generate(toy.gen_world(), 400, 149, per_kind_min=40, layer_target=10)
    combinators = [entry for entry in state.entries.values() if entry.kind == "combinator"]
    applications = [entry for entry in state.entries.values() if entry.move == "app.apply"]
    assert len(state.entries) == 400
    assert max(entry.layer for entry in combinators) >= 8
    assert sum(entry.layer >= 3 for entry in combinators) >= 10
    assert applications
    assert any(entry.layer >= 8 for entry in applications)
    for entry in combinators + applications:
        definition = state.library.get(entry.name)
        assert Definition.from_dict(json.loads(json.dumps(definition.to_dict()))) == definition
        references = n.references(definition.body)
        if entry.kind == "combinator":
            references -= set(definition.spec.op_params)
        assert definition.depends_on == tuple(sorted(references | n.operation_literals(definition.body)))
        assert definition.layer == 1 + max((state.layer(name) for name in definition.depends_on), default=0)
    for entry in combinators:
        family = state.library.get(entry.name).evidence.scope["op_family"]
        assert 3 <= len(family) <= 6
    assert any(any(state.layer(name) >= 3 for name in state.library.get(entry.name).evidence.scope["op_family"])
               for entry in combinators)
    assert any(entry.move in ("comb.guard", "comb.loop", "comb.fixpoint") and
               any(state.layer(name) >= 3 for name in entry.depends_on)
               for entry in combinators)
    assert all(entry.meta["derived_from"] and entry.meta["derived_from"][0] in entry.depends_on
               for entry in combinators if entry.move == "comb.compose")
    assert any(any(state.layer(name) >= 3 for name in entry.meta["plugged"])
               for entry in applications)
    for entry in applications:
        assert state.layer(entry.name) == 1 + max(state.layer(name) for name in entry.depends_on)
        assert entry.meta["combinator"] in entry.depends_on
        assert entry.depends_on == tuple(sorted(n.references(state.library.get(entry.name).body) |
                                                n.operation_literals(state.library.get(entry.name).body)))


def test_search_uses_serializable_failure_not_literal_bottom():
    state = _state()
    _predicate(state)
    candidate = _move("comb.search")(state, random.Random(3))
    assert candidate is not None
    assert not any(isinstance(node, n.Lit) and isinstance(node.value, Bottom)
                   for node in n.walk(candidate.defn.body))
    assert Definition.from_dict(json.loads(json.dumps(candidate.defn.to_dict()))) == candidate.defn
