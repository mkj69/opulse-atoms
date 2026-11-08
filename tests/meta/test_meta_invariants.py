"""Seeded exact checks of the four invariants (atoms-meta section 8)."""

import random

import pytest
import strategies as S

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary, flatten_calls
from opulse.atoms.observations import judge
from opulse.atoms.spec import Contract, Definition, Edge, Evidence, OperationSpec
from opulse.atoms.values import Bottom, Card, Ok, Unknown, outcome_equal, value_equal
from opulse.meta import arith, code, engine, identity
from opulse.meta import gen_code as G
from opulse.meta.builder.instantiate import WorldError, extend
from opulse.meta.vn import machine, reference
from opulse.meta.vn.report import report, routine_id


def test_generator_shared_integer_rules_and_exact_steps():
    assert all(G._FUNCTIONS[name][1] is getattr(arith, name)
               for name in ("add", "sub", "mul", "div"))
    scope = G.scope()
    for name, arguments, expected in (
        ("add", (11, 7), Ok(18)), ("sub", (11, 7), Ok(4)),
        ("mul", (-3, 7), Ok(-21)), ("div", (11, 4), Ok(2)),
        ("div", (7, 0), Bottom("div_zero")),
        ("is_zero", (0,), Ok(Card("bool", "true"))),
        ("lt", (7, 4), Ok(Card("bool", "false"))),
    ):
        result = kernel.call(name, arguments, scope, trace=True)
        assert (result.outcome, result.steps) == (expected, 1)
        assert result.trace.steps == 1


def samples():
    rng = random.Random(20261104)
    for index in range(210):
        program = G.random_code(rng, index % 4)
        yield program, G.random_args(rng, program)


def run(program, args, fuel=None):
    node = n.Call("eval", (n.Lit(program), n.Lit(code.lst(args))))
    scope = G.scope()
    return node, scope, engine.evaluate(node, scope=scope,
                                        limits=kernel.Limits(fuel=fuel), trace=True)


def same(left, right):
    assert outcome_equal(left.outcome, right.outcome) or (
        isinstance(left.outcome, Bottom) and left.outcome == right.outcome)
    assert left.steps == right.steps


def layer_zero(node):
    """Expand metered given calls with children; core flatten_calls only opens invented calls."""
    result = []
    for child in node.children:
        result.extend(layer_zero(child))
    if node.given and not node.children and node.name not in ("eval", "run"):
        result.append((node.name, node.inputs, node.outcome, node.steps))
    return result


def test_i1_unfold_and_quote_eval_exact_fuel():
    outcomes = {"ok": 0, "div_zero": 0}
    for program, args in samples():
        node, scope, full = run(program, args)
        decoded = code.decode(program)
        assert len(decoded.deps) >= 1
        direct = engine.call(decoded.main.name, args,
                             scope.extend((decoded.main, *decoded.deps)), trace=True)
        same(full, direct)
        same(full, engine.evaluate(engine.inline(node, scope), scope=scope, trace=True))
        assert full.steps >= 1
        cutoff = full.steps - 1
        short = engine.evaluate(node, scope=scope, limits=kernel.Limits(fuel=cutoff))
        assert short.outcome == Unknown("fuel") and short.steps == cutoff
        short_inline = engine.evaluate(engine.inline(node, scope), scope=scope,
                                       limits=kernel.Limits(fuel=cutoff))
        assert short_inline.outcome == Unknown("fuel") and short_inline.steps == cutoff
        at_limit = engine.evaluate(node, scope=scope, limits=kernel.Limits(fuel=full.steps))
        same(full, at_limit)
        short_direct = engine.call(decoded.main.name, args,
                                   scope.extend((decoded.main, *decoded.deps)),
                                   kernel.Limits(fuel=cutoff))
        assert short_direct.outcome == short.outcome == Unknown("fuel")
        assert short_direct.steps == short.steps == cutoff
        if isinstance(full.outcome, Bottom):
            assert full.outcome == Bottom("div_zero")
            outcomes["div_zero"] += 1
        else:
            assert isinstance(full.outcome, Ok)
            outcomes["ok"] += 1
    assert outcomes == {"ok": 198, "div_zero": 12}


def test_i2_random_boundaries_splice_all_layer_zero_calls():
    rng = random.Random(7239)
    for program, args in samples():
        node, scope, full = run(program, args)
        expanded = engine.evaluate(engine.inline(node, scope), scope=scope, trace=True)
        baseline = layer_zero(full.trace)
        assert baseline == layer_zero(expanded.trace)
        for _ in range(5):
            boundary = Boundary(depth=rng.choice((None, 0, 1, 2)),
                                open_names=frozenset(rng.sample(("eval", "run", "add", "sub"),
                                                               rng.randrange(3))),
                                keep_names=frozenset(rng.sample(("eval", "run", "add"),
                                                               rng.randrange(3))),
                                open_paths=frozenset((rng.choice(((), (0,), (0, 0))),)),
                                kinds=frozenset(rng.sample(("operation", "combinator", "object",
                                                            "observation"), rng.randrange(5))))
            view = flatten_calls(full.trace, boundary)
            same(full, expanded)
            assert [entry for visible in view for entry in layer_zero(visible)] == baseline


def test_i3_code_reads_and_vn_probes_leave_inputs_unchanged():
    for program, args in samples():
        before = code.encode(program)
        quoted = code.canonicalize(program)
        digest = code.code_hash(program)
        assert quoted == program and digest == code.code_hash(quoted)
        assert value_equal(program, quoted)
        decoded = code.decode(program)
        def definition(entry, decoded=decoded):
            output = decoded.sig.fields[1].fields[0] if entry is decoded.main else "int"
            spec = OperationSpec(entry.name, "transform", (Edge("int"),), Edge(output),
                                 "Integer definition", extra={"input_names": ["x0"]})
            return Definition(entry.name, "operation", "invented", 1, (), spec, entry.body)
        dependencies = {entry.name: definition(entry) for entry in decoded.deps}
        assert code.quote(definition(decoded.main), dependencies.get, G.DIGESTS) == program
        assert code.encode(program) == before
        state = machine.to_card(reference.load([1, args[0], 0, 0], 16))
        original = machine.from_card(state)
        probes = kernel.DictScope(machine.atoms(16))
        for name, values in (("pc", (state,)), ("a", (state,)),
                             ("cell", (state, 1)), ("halted", (state,))):
            first = kernel.call(name, values, probes)
            second = kernel.call(name, values, probes)
            assert first.outcome == second.outcome and first.steps == second.steps == 0
            assert state == machine.to_card(original)
            assert machine.from_card(state) == original
    cases = (
        (reference.load([1, 0, 4, 12, 3, 15, 2, 3, 8, 1, 3, 3, 2, 15, 0, 0], 16), True),
        (reference.load([1, 7, 0, 0], 16), False),
        (reference.load([1, 7, 3, 15, 0, 0], 16), False),
    )
    for state, expected in cases:
        original = machine.to_card(state)
        full_report = report(state, 100)
        assert full_report.self_modifying is expected
        for answer in (True, False):
            full_view, full_verdict = S.vn_self_modifying_grade(
                state, 100, ("pc", "a", "cell", "halted"), answer)
            partial_view, partial_verdict = S.vn_self_modifying_grade(
                state, 100, ("pc", "halted"), answer)
            assert full_view != partial_view
            assert all(result.steps == 0 for _, result in (*full_view, *partial_view))
            assert full_verdict == partial_verdict == (answer is expected)
            assert full_verdict == judge("full_state", full_report.self_modifying, answer)
            assert machine.to_card(state) == original


def _int_paths(value, prefix=()):
    if not isinstance(value, Card):
        return
    if value.sort == "code":
        return
    if value.sort == "expr" and value.tag == "lit" and type(value.fields[0]) is int:
        yield prefix + (0,)
    for index, field in enumerate(value.fields):
        if isinstance(field, Card):
            yield from _int_paths(field, prefix + (index,))


def test_i4_edits_renames_and_ledger_roundtrip():
    rng = random.Random(493)
    ledger = identity.Ledger()
    world = "small-int-world/1"
    contract = Contract("exact integer outcome", keeps=("inputs",))
    for index, (program, _) in enumerate(samples()):
        original = ledger.add(program, world, f"program{index}")
        if ledger.record(original, world).status != "promoted":
            ledger.attach_evidence(original, world, Evidence("bounded", {"domain": "0..4", "size": 5},
                                                             checks=("full state",), world_hash=world,
                                                             deps_hash=ledger.record(original, world).deps_hash))
            ledger.promote(original, world, contract)
        assert ledger.record(original, world).status == "promoted"
        if index < 50:
            paths = tuple(_int_paths(program.fields[2], (2,)))
            assert paths
            path = rng.choice(paths)
            current = program
            for part in path:
                current = current.fields[part]
            modified = identity.edit(program, path, current + 1)
            changed = code.code_hash(modified)
            assert changed != original
            assert ledger.add(modified, world) == changed
            assert ledger.record(changed, world).evidence == ()
            with pytest.raises(identity.LedgerError, match="promotion needs"):
                ledger.promote(changed, world, contract)
        assert code.code_hash(code.canonicalize(program)) == original
    payload = ledger.to_dict()
    restored = identity.Ledger.from_dict(payload)
    assert restored.to_dict() == payload
    for item in payload["records"]:
        assert restored.record(item["hash"], item["world_hash"]).to_dict() == item


def test_i4_vn_routine_identity_and_foreign_builder_evidence():
    state = reference.load([1, 0, 4, 12, 3, 15, 2, 3, 8, 1, 3, 3, 2, 15, 0, 0], 16)
    result = report(state, 100)
    status, final, steps = reference.run(state, 100)
    assert status == "ok" and steps == 8 and result.self_modifying is True
    assert final.mem[3] == 13 and state.mem[3] == 12
    assert routine_id(16, 0, state.mem) != routine_id(16, 0, final.mem)
    from test_builder_instantiate import StubLedger, body_world

    world_card, program = body_world()
    foreign = Evidence("bounded", {"domain": "z", "size": 5}, world_hash="other-world")
    with pytest.raises(WorldError, match="evidence or contract is not promoted"):
        extend(world_card, program, StubLedger((foreign, Contract("same output"))))


def test_rename_only_preserves_identity():
    resolve = lambda name: code.Resolved(digest=G.DIGESTS[name]) if name == "add" else None
    first = code.make_code("operation", G.SIG, ("input",),
                           n.Let("temporary", n.Call("add", (n.Var("input"), n.Lit(1))),
                                 n.Var("temporary")), resolve)
    renamed = code.make_code("operation", G.SIG, ("renamed",),
                             n.Let("different", n.Call("add", (n.Var("renamed"), n.Lit(1))),
                                   n.Var("different")), resolve)
    assert first == renamed and code.code_hash(first) == code.code_hash(renamed)


def test_run_budget_out_is_a_value_with_exact_inner_steps():
    nested = code.make_code("operation", G.SIG, ("x",),
                            n.Call("add", (n.Call("add", (n.Var("x"), n.Lit(1))), n.Lit(2))),
                            lambda name: code.Resolved(digest=G.DIGESTS[name]))
    for budget, expected_steps, expected in ((0, 0, Card("result", "out", (0,))),
                                             (1, 1, Card("result", "out", (1,))),
                                             (2, 2, Card("result", "ok", (6,)))):
        result = engine.call("run", (nested, code.lst((3,)), budget), G.scope())
        assert result.outcome == Ok(expected) and result.steps == expected_steps


def test_run_zero_budget_exact_outer_fuel_regression():
    nested = code.make_code("operation", G.SIG, ("x",),
                            n.Call("add", (n.Var("x"), n.Lit(1))),
                            lambda name: code.Resolved(digest=G.DIGESTS[name]))
    node = n.Call("run", (n.Lit(nested), n.Lit(code.lst((3,))), n.Lit(0)))
    unrestricted = engine.evaluate(node, scope=G.scope())
    limited = engine.evaluate(node, scope=G.scope(), limits=kernel.Limits(fuel=0))
    assert unrestricted.outcome == Ok(Card("result", "out", (0,))) and unrestricted.steps == 0
    assert limited.outcome == unrestricted.outcome and limited.steps == unrestricted.steps


def test_determinism_and_spec_version_hashes():
    for seed, expected in (
        (0, "8b87643870316abd20412876940e6e18d6d9a3e7cbc0600a5acbe5fb30c60125"),
        (1, "d6a1334eb9aba10928d516eb9b19dd6dfcb3514c7b15409137389a772becd4ac"),
        (2, "8b9873635485a72ca5b4ff307cb6520525a01d2262d26ae3c0a90cf210d55f8e")):
        first = G.random_code(random.Random(seed), 3)
        second = G.random_code(random.Random(seed), 3)
        assert first == second and code.code_hash(first) == code.code_hash(second)
        assert code.code_hash(first) == expected
