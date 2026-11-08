"""Exact accounting for explicitly cacheable promoted calls."""

import random

from opulse.atoms import kernel, nodes
from opulse.atoms.library import VerifyRequest
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.gen_v2 import fast
from opulse.gen_v2.moves.operation import MOVES
from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import classic, toy


def _compare(scope, name, args, dialect="atoms-v2", fuels=(None, 0, 1, 2, 5, 20)):
    def check():
        for fuel in fuels:
            limits = kernel.Limits(fuel=fuel)
            expected = kernel.call(name, args, scope, limits, dialect=dialect)
            uncached = fast.call(name, args, scope, fuel, dialect)
            cached = fast.call(name, args, scope, fuel, dialect, frozenset({name}))
            assert (cached.outcome, cached.steps, cached.jumps) == (
                uncached.outcome, uncached.steps, uncached.jumps) == (
                expected.outcome, expected.steps, expected.jumps)
            assert cached.trace is None
    fast.deep(check)


def test_cache_hits_charge_full_steps_and_jumps():
    calls = []

    def count(value):
        calls.append(value)
        return value

    block = nodes.Blocks((('x', nodes.Var('value')),), 'start', (
        ('start', nodes.Block((), nodes.Jump('done'))),
        ('done', nodes.Block((), nodes.Halt(nodes.Call('count', (nodes.Var('x'),)))))))
    scope = kernel.DictScope((kernel.Atom('count', 1, count, cost=2),),
                             (kernel.Defn('f1', ('value',), block),))

    def check():
        cacheable = frozenset({'f1'})
        first = fast.call('f1', (7,), scope, 10, cacheable=cacheable)
        assert (first.outcome, first.steps, first.jumps) == (Ok(7), 3, 1)
        hit = fast.call('f1', (7,), scope, 10, cacheable=cacheable)
        assert (hit.outcome, hit.steps, hit.jumps) == (first.outcome, first.steps, first.jumps)
        assert hit.work == first.work
        assert len(calls) == 2
        assert fast.call('f1', (7,), scope, 2, cacheable=cacheable) == kernel.call(
            'f1', (7,), scope, kernel.Limits(fuel=2))
        assert len(calls) == 2
        assert fast.call('f1', (7,), scope, 10).outcome == first.outcome
        assert len(calls) == 3
    fast.deep(check)


def test_bottom_cached_unknown_not_cached_and_unhashable_skipped():
    calls = []

    def check_value(value):
        calls.append(value)
        return Bottom('bad') if value == 0 else value

    scope = kernel.DictScope((kernel.Atom('check', 1, check_value),),
                             (kernel.Defn('f1', ('x',), nodes.Call('check', (nodes.Var('x'),))),))

    def check():
        cacheable = frozenset({'f1'})
        for _ in range(2):
            assert fast.call('f1', (0,), scope, 2, cacheable=cacheable).outcome == Bottom('bad')
        assert calls == [0, 0]
        for _ in range(2):
            assert fast.call('f1', (2,), scope, 0, cacheable=cacheable).outcome == Unknown('fuel')
        assert fast.call('f1', ([3],), scope, 2, cacheable=cacheable).outcome == Ok([3])
        assert fast.call('f1', ([3],), scope, 2, cacheable=cacheable).outcome == Ok([3])
        assert len(calls) == 4
    fast.deep(check)


def test_legacy_bottom_argument_is_never_cached():
    calls = []

    def inspect(value):
        calls.append(value)
        return 1

    scope = kernel.DictScope((kernel.Atom('inspect', 1, inspect),),
                             (kernel.Defn('f1', ('x',), nodes.Call('inspect', (nodes.Var('x'),))),))

    def check():
        for _ in range(2):
            actual = fast.evaluate(nodes.Call('f1', (nodes.Lit(Bottom('bad')),)), {}, scope,
                                   2, 'legacy-v1', frozenset({'f1'}))
            assert actual == kernel.call('f1', (Bottom('bad'),), scope,
                                         kernel.Limits(fuel=2), dialect='legacy-v1')
        assert len(calls) == 4
    fast.deep(check)


def test_bool_and_int_arguments_have_distinct_keys():
    scope = kernel.DictScope((), (kernel.Defn('f1', ('x',), nodes.Var('x')),))

    def check():
        for value in (True, 1, (True,), (1,)):
            run = fast.call('f1', (value,), scope, None, cacheable=frozenset({'f1'}))
            assert type(run.outcome.value) is type(value)
            assert run.outcome.value == value
    fast.deep(check)


def test_scope_and_argument_evaluation_are_not_cached():
    calls = []

    def count(value):
        calls.append(value)
        return value

    body = nodes.Call('count', (nodes.Var('x'),))
    scope = kernel.DictScope((kernel.Atom('count', 1, count),),
                             (kernel.Defn('f1', ('x',), body),))
    other_scope = kernel.DictScope((), (kernel.Defn('f1', ('x',), nodes.Lit(100)),))
    node = nodes.Call('f1', (nodes.Call('count', (nodes.Lit(4),)),))

    def check():
        for _ in range(2):
            run = fast.evaluate(node, {}, scope, None, cacheable=frozenset({'f1'}))
            assert (run.outcome, run.steps) == (Ok(4), 2)
        assert calls == [4, 4, 4, 4]
        assert fast.call('f1', (4,), other_scope, None, cacheable=frozenset({'f1'})).outcome == Ok(100)
    fast.deep(check)


def test_scoped_name_precedes_environment_reference_in_cache():
    scope = kernel.DictScope((), (kernel.Defn('f1', (), nodes.Lit(1)),
                                  kernel.Defn('f2', (), nodes.Lit(2))))

    def check():
        expression = nodes.Call('f1')
        environment = {'f1': kernel.FnRef('f2')}
        cacheable = frozenset({'f1', 'f2'})
        actual = fast.evaluate(expression, environment, scope, None, cacheable=cacheable)
        expected = kernel.evaluate(expression, environment, scope)
        assert (actual.outcome, actual.steps) == (expected.outcome, expected.steps)
        assert fast.call('f2', (), scope, None, cacheable=cacheable).outcome == Ok(2)

    fast.deep(check)


def test_environment_reference_calls_are_not_cached():
    scope = kernel.DictScope((), (kernel.Defn('f1', (), nodes.Lit(1)),
                                  kernel.Defn('f2', (), nodes.Lit(2))))

    def check():
        expression = nodes.Call('alias')
        for target in ('f1', 'f2'):
            environment = {'alias': kernel.FnRef(target)}
            actual = fast.evaluate(expression, environment, scope, None,
                                   cacheable=frozenset({'f1', 'f2'}))
            expected = kernel.evaluate(expression, environment, scope)
            assert (actual.outcome, actual.steps) == (expected.outcome, expected.steps)

    fast.deep(check)


def test_unhashable_scope_keeps_kernel_behavior():
    class UnhashableScope:
        __hash__ = None

        def resolve(self, name):
            return kernel.Defn('f1', ('x',), nodes.Var('x')) if name == 'f1' else None

    scope = UnhashableScope()
    assert fast.deep(fast.call, 'f1', (3,), scope, None,
                     cacheable=frozenset({'f1'})) == kernel.call('f1', (3,), scope)


def test_mutable_output_is_not_reused():
    calls = []

    def make_list(value):
        calls.append(value)
        return [value]

    scope = kernel.DictScope((kernel.Atom('make_list', 1, make_list),),
                             (kernel.Defn('f1', ('value',), nodes.Call('make_list', (nodes.Var('value'),))),))

    def check():
        first = fast.call('f1', (4,), scope, None, cacheable=frozenset({'f1'}))
        first.outcome.value.append(9)
        second = fast.call('f1', (4,), scope, None, cacheable=frozenset({'f1'}))
        assert second.outcome == Ok([4])
        assert calls == [4, 4]
    fast.deep(check)


def test_explicit_cacheable_does_not_cache_impure_transitive_host():
    calls = []

    def bump(value):
        calls.append(value)
        return len(calls)

    scope = kernel.DictScope((kernel.Atom("bump", 1, bump),), (
        kernel.Defn("inner", ("value",), nodes.Call("bump", (nodes.Var("value"),))),
        kernel.Defn("outer", ("value",), nodes.Call("inner", (nodes.Var("value"),))),
    ))

    def check():
        for _ in range(2):
            result = fast.call("outer", (1,), scope, 10, cacheable=frozenset({"outer", "inner"}))
            assert result.outcome == Ok(len(calls))
        assert calls == [1, 1]

    fast.deep(check)


def test_generated_toy_and_classic_equivalence():
    rng = random.Random(239)
    for world, target, seed in ((toy.gen_world(('operation',)), 18, 31),
                                (classic.gen_world('integer'), 8, 41)):
        state = generate(world, target, seed, per_kind_min=0, layer_target=0,
                         time_limit=15, moves=MOVES)
        assert state.entries
        assert fast.promoted_names(state.library) <= frozenset(state.entries)
        entries = list(state.entries.values())
        for _ in range(12):
            entry = rng.choice(entries)
            if not entry.signature or any(sort not in state.sorts for sort in entry.signature.inputs):
                continue
            args = tuple(rng.choice(state.sorts[sort].values) for sort in entry.signature.inputs)
            _compare(state.library.scope(), entry.name, args, world.dialect,
                     (None, 0, 1, 2, 3, 8, 32, rng.randrange(1, 20)))


def test_fast_evaluation_matches_kernel_inside_and_outside_the_deep_thread():
    world = toy.gen_world(("operation",))
    state = generate(world, 40, 5, per_kind_min=0, layer_target=1, moves=MOVES)
    scope = state.library.scope()

    def compare():
        for name in state.entries:
            for value in world.sorts["int"].values:
                sig = state.signature(name)
                args = tuple(value for _ in sig.inputs)
                slow = kernel.call(name, args, scope, kernel.Limits(fuel=world.fuel))
                quick = fast.call(name, args, scope, world.fuel)
                assert (quick.outcome, quick.steps, quick.jumps) == (slow.outcome, slow.steps, slow.jumps)
        return True

    assert fast.deep(compare) and compare()


def test_once_verifier_agrees_with_the_core_operation_verifier():
    world = toy.gen_world(("operation",))
    state = generate(world, 30, 6, per_kind_min=0, layer_target=1, moves=MOVES)
    lib = state.library
    for name in list(state.entries)[-10:]:
        defn = lib.get(name)
        domain = tuple((value,) * len(state.signature(name).inputs) for value in world.sorts["int"].values)
        table = {args: kernel.call(name, args, lib.scope()).outcome for args in domain}
        request = VerifyRequest("exhaustive", domain, {"domain": "d", "size": len(domain)},
                                reference=lambda *args, table=table: table[tuple(args)],
                                extra={"reference_origin": "table"})
        checks, problems, steps = fast.deep(lib._operation_verifier_once, defn, request)
        from opulse.atoms.library import _operation_verifier

        core = _operation_verifier(defn, lib, request)
        assert (core.ok, tuple(core.checks), core.steps) == (not problems, tuple(checks), steps)
        wrong = VerifyRequest("exhaustive", domain, {"domain": "d", "size": len(domain)},
                              reference=lambda *args: 10 ** 9, extra={"reference_origin": "oracle"})
        assert lib._operation_verifier_once(defn, wrong)[1]


def test_review4_11_precomputed_runs_require_matching_scope_and_fuel():
    from test_gen_admit import X0, _op, _state

    from opulse.gen_v2.admit import admit
    from opulse.gen_v2.base import Entry

    state = _state()
    body = nodes.Call("add", (nodes.Call("mul", (X0, X0)), nodes.Lit(1)))
    assert isinstance(admit(state, _op("f1", ("int",), "int", body, 1)), Entry)
    library = state.library
    request = VerifyRequest("bounded", ((1,),), {"domain": "one probe", "size": 1},
                            reference=lambda value: value * value + 1,
                            extra={"reference_origin": "oracle", "fuel": 20000,
                                   "precomputed": {(1,): kernel.Run(Ok(999), 1, 0, None)},
                                   "precomputed_scope": id(library.scope()),
                                   "precomputed_fuel": 5})
    checks, problems, _ = library._operation_verifier_once(library.get("f1"), request)
    assert not problems and checks == ("reference", "unfold_equivalence")
