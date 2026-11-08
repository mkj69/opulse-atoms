"""Twelve kernel-unfoldable inventions for origin-preserving polyrhythm."""

from dataclasses import replace
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import bounded
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    compute_layer,
)

from . import adapter, hosts
from .world import new_library


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def lit(value):
    return n.Lit(value)


def test(name, *args):
    return n.Test(call(name, *args))


def loop(name, bound, accumulator, update):
    index = var('index')
    body = n.Case(((test('eq', index, bound), var('acc')),),
                  call(name, call('add', index, lit(1)), update))
    return n.Rec(name, ('index', 'acc'), body, (lit(0), accumulator),
                 call('sub', bound, index))


def over_cells(left_cells, right_cells, count, mode):
    index = var('index')
    first = call('at', left_cells, call('mod', index, call('length', left_cells)))
    second = call('at', right_cells, call('mod', index, call('length', right_cells)))
    if mode == 'maximum':
        update = call('append', var('acc'), call('maximum', first, second))
    else:
        mismatch = call('ne', first, second)
        heavy_odd = call('eq', call('mod', index, lit(2)), lit(1))
        beat = call('eq', call('maximum', first, second), lit(2))
        update = call('pair', call('add', call('first', var('acc')), mismatch),
                      call('add', call('second', var('acc')),
                           n.Case(((n.And(n.Test(heavy_odd), n.Test(beat)), lit(1)),), lit(0))))
    return loop('cells_loop', count, lit(()) if mode == 'maximum' else lit((0, 0)), update)


def body_offbeat(value):
    sequence = call('cells', value)
    index = var('index')
    update = call('add', var('acc'), n.Case((
        (n.And(test('eq', call('mod', index, lit(2)), lit(1)),
               test('eq', call('at', sequence, index), lit(2))), lit(1)),), lit(0)))
    return loop('offbeat_loop', call('length', sequence), lit(0), update)


def body_cycle(value):
    sequence = call('cells', value)
    length = call('length', sequence)
    period = var('period')
    candidate = call('prefix', sequence, period)
    repeated = call('repeat', candidate, call('div', length, period))
    condition = n.And(test('eq', call('mod', length, period), lit(0)),
                      test('eq', sequence, repeated))
    search = n.Rec('find_period', ('period',),
                   n.Case(((condition, call('make_rhythm', candidate)),),
                          call('find_period', call('add', period, lit(1)))),
                   (lit(1),), call('sub', length, period))
    return n.Let('sequence', sequence, search)


def body_best_fit(first, second):
    index = var('index')
    score = call('phase_score', first, second, index)
    candidate = call('triple', call('first', score), call('second', score), index)
    return loop('best_loop', call('length', call('cells', second)), lit((513, 513, 513)),
                n.Case(((test('lt', candidate, var('acc')), candidate),), var('acc')))


def body_orbit(value):
    return call('unique', loop('orbit_loop', call('length', call('cells', value)), lit(()),
                               call('append', var('acc'), call('f',
                                                       call('left', value, var('index'))))))


def body_infer(observed, first, second, budget):
    phase_a = var('index')
    phase_b = var('index_b')
    mixed = call('weave', lit(kernel.FnRef('identity')), lit(kernel.FnRef('identity')),
                 call('left', first, phase_a), call('left', second, phase_b))
    score = call('phase_score', observed, mixed, lit(0))
    candidate = call('quad', call('first', score), call('offbeat', mixed), phase_a, phase_b)
    nested = n.Rec('inner', ('index_b', 'matches'),
                   n.Case(((test('eq', phase_b, call('length', call('cells', second))),
                            var('matches')),),
                          call('inner', call('add', phase_b, lit(1)),
                               n.Case(((test('le', call('first', score), budget),
                                        call('append', var('matches'), candidate)),), var('matches')))),
                   (lit(0), var('acc')),
                   call('sub', call('length', call('cells', second)), phase_b))
    all_candidates = loop('outer', call('length', call('cells', first)), lit(()), nested)
    sorted_candidates = call('sorted_list', all_candidates)
    best = call('first', call('first', var('candidates')))
    filtered = loop('keep', call('length', var('candidates')), lit(()),
                    n.Case(((test('eq', call('first', call('at', var('candidates'), var('index'))), best),
                             call('append', var('acc'), call('at', var('candidates'), var('index')))),),
                           var('acc')))
    valid = n.And(n.And(test('le', call('length', call('cells', first)), lit(32)),
                        test('le', call('length', call('cells', second)), lit(32))),
                  n.And(test('le', lit(0), budget), test('le', budget, lit(512))))
    limit = call('lcm', call('length', call('cells', observed)),
                 call('lcm', call('length', call('cells', first)), call('length', call('cells', second))))
    return n.Case(((valid, n.Let('limit', limit,
                                n.Let('candidates', sorted_candidates,
                                      n.Case(((test('eq', call('length', var('candidates')), lit(0)), lit(())),),
                                             filtered)))),), call('invalid'))


def definitions():
    rhythm = var('arg0')
    first, second = var('voice_a'), var('voice_b')
    sequence = var('sequence')
    objects = {
        'accented': (call('make_rhythm', call('cells', rhythm)),
                     ObjectSpec('accented', 'refine', base='rhythm',
                                valid=n.Case(((n.And(test('eq', var('x'), call('make_rhythm', call('cells', var('x')))),
                                                      test('le', lit(0), call('index_of', call('cells', var('x')), lit(2)))),
                                               lit(True)),), lit(False)),
                                canon=call('make_rhythm', call('cells', var('x'))))),
        'cycle': (body_cycle(rhythm),
                  ObjectSpec('cycle', 'refine', base='rhythm',
                             valid=n.Case(((n.And(test('eq', var('x'), call('make_rhythm', call('cells', var('x')))),
                                                   test('le', lit(1), call('length', call('cells', var('x'))))),
                                            lit(True)),), lit(False)),
                             canon=body_cycle(var('x')))),
    }
    start = n.Case(((test('le', lit(0), call('index_of', call('cells', rhythm), lit(2))),
                     n.Let('accent', call('accented.make', call('make_rhythm', call('cells', rhythm))),
                           call('left', var('accent'),
                                call('index_of', call('cells', var('accent')), lit(2))))),),
                   call('no_accent'))
    stack = n.Let('a', call('f', sequence),
                  n.Let('b', call('g', sequence),
                        n.Case(((test('eq', call('length', call('cells', var('a'))),
                                      call('length', call('cells', var('b')))),
                                 call('make_rhythm', over_cells(call('cells', var('a')),
                                                                call('cells', var('b')),
                                                                call('length', call('cells', var('a'))), 'maximum'))),),
                               call('invalid'))))
    phase_a, phase_b, shift = first, second, var('shift')
    phase_window = call('lcm', call('length', call('cells', phase_a)),
                        call('length', call('cells', var('b'))))
    phase_score = over_cells(call('cells', phase_a), call('cells', var('b')),
                             var('count'), 'score')
    phase_overlay = over_cells(call('cells', phase_a), call('cells', var('b')),
                               var('count'), 'maximum')
    phase_result = n.Let('b', call('left', phase_b, shift),
                         n.Let('count', phase_window, n.Let('score', phase_score,
                               call('pair', call('first', var('score')),
                                    call('offbeat', call('make_rhythm', phase_overlay))))))
    phase = n.Case(((n.And(test('le', lit(0), shift),
                           test('lt', shift, call('length', call('cells', phase_b)))), phase_result),),
                   call('invalid'))
    weave = n.Let('a', call('f', first), n.Let('b', call('g', second),
                  call('cycle.make', call('make_rhythm',
                        over_cells(call('cells', var('a')), call('cells', var('b')),
                                   call('lcm', call('length', call('cells', var('a'))),
                                        call('length', call('cells', var('b')))), 'maximum')))))
    muted = call('cycle.make', call('make_rhythm', loop('mute_loop',
                 call('length', call('cells', rhythm)), lit(()),
                 call('append', var('acc'), n.Case((
                     (test('eq', call('at', call('cells', rhythm), var('index')), lit(2)), lit(2)),),
                     lit(0))))))
    count = n.Let('minimum_errors', call('first', call('best_fit', call('pair', first, second))),
                  n.Let('rotations', call('orbit', lit(kernel.FnRef('identity')), second),
                        loop('count_loop', call('length', var('rotations')), lit(0),
                             call('add', var('acc'), n.Case((
                                 (test('eq', call('first', call('phase_score', first,
                                       call('at', var('rotations'), var('index')), lit(0))),
                                       var('minimum_errors')), lit(1)),), lit(0))))))
    observed_pair = call('cells', var('arg0'))
    best_body = n.Let('voice_a', call('first', observed_pair),
                      n.Let('voice_b', call('second', observed_pair), body_best_fit(first, second)))
    count_body = n.Let('voice_a', call('first', observed_pair),
                       n.Let('voice_b', call('second', observed_pair), count))
    bodies = [objects['accented'][0], start, stack, body_offbeat(rhythm),
              objects['cycle'][0], phase, weave, best_body,
              muted, body_orbit(rhythm), count_body,
              body_infer(var('observed'), first, second, var('budget'))]
    names = ['accented', 'start_heavy', 'stack', 'offbeat', 'cycle', 'phase_score',
             'weave', 'best_fit', 'silence_weak', 'orbit', 'phase_count', 'infer_phase']
    kinds = ['object', 'operation', 'combinator', 'observation'] * 2 + [
        'operation', 'combinator', 'observation', 'operation']
    parameters = [('arg0',), ('arg0',), ('f', 'g', 'sequence'), ('arg0',),
                  ('arg0',), ('voice_a', 'voice_b', 'shift'), ('f', 'g', 'voice_a', 'voice_b'),
                  ('arg0',), ('arg0',), ('f', 'arg0'), ('arg0',),
                  ('observed', 'voice_a', 'voice_b', 'budget')]
    levels = {op: 0 for op in ('cells', *(item for item in vars(hosts)
                                        if not item.startswith('_')))}
    output = []
    for name, kind, params, body in zip(names, kinds, parameters, bodies):
        references = tuple(sorted(n.references(body) - set(params[:2] if kind == 'combinator' else
                                                           params[:1] if name == 'orbit' else ())))
        if kind == 'object':
            spec = objects[name][1]
        elif kind == 'combinator':
            slots = ('f', 'g') if name in ('stack', 'weave') else ('f',)
            references = tuple(sorted(n.references(body) - set(slots)))
            spec = CombinatorSpec(name, params, slots, body)
        elif kind == 'observation':
            spec = ObservationSpec(name, ('cells',), body, extra={'subject': 'arg0'})
        else:
            spec = OperationSpec(name, 'transform', tuple(Edge('any') for _ in params), Edge('unknown'),
                                 name + ' unfolds through declared rhythm and list operations.',
                                 ('invalid', 'range', 'no_accent'), extra={'input_names': list(params)})
        level = compute_layer(references, {**levels, **{f'{key}.make': value for key, value in levels.items()}})
        output.append(Definition(name, kind, 'invented', level, references, spec, body))
        levels[name] = level
    return tuple(output)


def build_library(limit=12):
    library = new_library()
    sample = hosts.to_card(tuple(map(int, '020101002010')))
    accented = reference_value('accented', sample.fields)
    first = reference_value('cycle', sample.fields)
    small_a = reference_value('cycle', (0, 2))
    small_b = reference_value('cycle', (2, 1, 0))
    examples = [(sample,), (accented,), (kernel.FnRef('start_heavy'), kernel.FnRef('identity'), accented),
                (sample,), (sample,), (small_a, small_b, 1),
                (kernel.FnRef('identity'), kernel.FnRef('identity'), small_a, small_b),
                ((small_a, small_b),), (first,), (kernel.FnRef('silence_weak'), small_a),
                ((small_a, small_b),), (small_a, small_a, small_b, 0)]
    rhythms = tuple(hosts.to_card(pattern) for length in (1, 2, 3, 4)
                    for pattern in product(range(3), repeat=length))
    accented_words = tuple(word for word in rhythms if 2 in word.fields)
    cycles = tuple(reference_value('cycle', word.fields) for word in rhythms
                   if all(word.fields != word.fields[:period] * (len(word.fields) // period)
                          for period in range(1, len(word.fields)) if len(word.fields) % period == 0))
    cycles = tuple(dict.fromkeys(cycles))
    short = tuple(item for item in cycles if len(hosts.cells(item)) <= 2)
    pairs = tuple(product(short, repeat=2))
    tiny = tuple(item for item in short if len(hosts.cells(item)) == 1)
    for definition, args in zip(definitions()[:limit], examples[:limit]):
        library.write(definition)
        if definition.name == 'offbeat':
            library.check(definition.name)
            library.make_callable(definition.name, (args,))
            domain = tuple((item,) for item in rhythms[:81])
            description = f'bounded: first {len(domain)} ternary words of length <= 4'
            request = replace(bounded((domain,), description), domain=domain,
                              scope={'domain': description, 'size': len(domain)},
                              reference=lambda *arguments: oracle('offbeat', arguments))
            library.verify(definition.name, request)
        elif definition.kind == 'observation':
            adapter.check(library, definition.name)
            adapter.make_callable(library, definition.name, args)
            domain = tuple((pair,) for pair in pairs[:54])
            adapter.verify(library, definition.name, domain,
                           f'bounded: first {len(domain)} ordered cycle pairs of length <= 2',
                           reference=lambda *arguments, name=definition.name: oracle(name, arguments))
        elif definition.kind == 'object':
            library.check(definition.name)
            library.make_callable(definition.name, ((sample,),))
            domain = tuple((item,) for item in rhythms[:110 if definition.name == 'accented' else 81])
            request = replace(bounded((domain,),
                                      f'bounded: first {len(domain)} ternary words of length <= 4'),
                              domain=domain)
            library.verify(definition.name, request)
        else:
            library.check(definition.name)
            library.make_callable(definition.name, (args,))
            if definition.kind == 'combinator':
                family = ('identity', 'silence_weak') if definition.name == 'orbit' else ('identity', 'start_heavy')
                heavy_cycles = tuple(item for item in cycles if 2 in hosts.cells(item))
                domain = (tuple(product(heavy_cycles[:8], repeat=2)) if definition.name == 'weave' else
                          tuple((item,) for item in cycles[:54]) if definition.name == 'orbit'
                          else tuple((reference_value('accented', item.fields),) for item in accented_words[:54]))
                request = bounded((domain,),
                    f'bounded: first {len(domain)} '
                    f'{"heavy-cycle pairs" if definition.name == "weave" else "cycles" if definition.name == "orbit" else "accented words"} '
                    f'of length <= 4; operation slots {"/".join(family)}')
                request = replace(request, domain=domain,
                    scope={**request.scope, 'op_family': list(family)}, extra={'op_family': family},
                    reference=lambda assignment, inputs, name=definition.name:
                        oracle(name, tuple(kernel.FnRef(assignment[slot]) for slot in
                                           library.get(name).spec.op_params) + tuple(inputs)))
            else:
                if definition.name == 'start_heavy':
                    domain = tuple((reference_value('accented', item.fields),)
                                   for item in accented_words[:81])
                elif definition.name == 'phase_score':
                    domain = tuple((one, two, shift) for one, two in pairs
                                   for shift in range(len(hosts.cells(two))))
                elif definition.name == 'silence_weak':
                    domain = tuple((item,) for item in cycles[:54])
                else:
                    domain = tuple((observed, one, two, 0) for observed in tiny
                                   for one, two in pairs[:18])
                description = {
                    'start_heavy': f'first {len(domain)} accented words of length <= 4',
                    'phase_score': f'all {len(domain)} ordered cycle pairs of length <= 2 and valid shifts',
                    'silence_weak': f'first {len(domain)} canonical cycles of length <= 4',
                    'infer_phase': f'{len(domain)} observed/voice triples of length <= 2 with budget 0',
                }[definition.name]
                request = replace(bounded((domain,), f'bounded: {description}'),
                                  domain=domain)
            library.verify(definition.name, request if definition.kind == 'combinator' else
                           replace(request,
                               reference=lambda *arguments, name=definition.name: oracle(name, arguments)))
        library.account(definition.name)
        library.promote(definition.name, Contract(f'{definition.name}: exact discrete cells on recorded scope; failures propagate.'))
    return library


def oracle(name, args):
    from . import reference
    return reference.evaluate(name, args)


def reference_value(sort, cells):
    from opulse.atoms.values import Card
    return Card(sort, 'val', (hosts.to_card(cells),))
