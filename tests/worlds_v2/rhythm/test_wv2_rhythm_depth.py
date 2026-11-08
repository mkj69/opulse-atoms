"""Independent catalogue oracle and four kernel invariants for rhythm depth."""

import json
from itertools import product
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.rhythm import hosts, reference
from opulse.worlds_v2.rhythm.export import build_export, example_inputs, expression
from opulse.worlds_v2.rhythm.story import build_library, definitions, reference_value
from opulse.worlds_v2.rhythm.world import decl


@pytest.fixture(scope='module')
def library():
    return build_library()


@pytest.fixture(scope='module')
def export():
    return build_export()


def test_fresh_first_three_cards():
    partial = build_library(limit=3)
    assert [partial.get(definition.name).status for definition in definitions()[:3]] == ['promoted'] * 3
    assert partial.run('start_heavy', (reference_value('accented', (0, 2)),)).outcome == values.Ok(
        reference_value('accented', (2, 0)))


def test_all_design_examples_and_pipeline(library):
    design = reference.design()
    samples, _ = design.calculated()
    for definition, args, expected in zip(definitions(), example_inputs(), samples):
        record = library.get(definition.name)
        assert record.status == 'promoted' and record.evidence.method in ('exhaustive', 'bounded')
        assert record.evidence.scope['size'] >= 50
        assert record.evidence.scope['checked']['size'] == record.evidence.scope['size']
        assert len(record.evidence.scope['checked']['sha256']) == 64
        assert record.evidence.method == 'bounded'
        if record.kind == 'combinator':
            assert len(record.evidence.scope['op_family']) >= 2
        if record.kind == 'object':
            assert {'canon_total', 'canon_idempotent', 'canon_keeps_valid'} <= set(record.evidence.checks)
        assert record.evidence.deps_hash == library._deps_hash(record.name)
        assert record.evidence.world_hash == library.world.world_hash()
        assert record.contract is not None
        assert record.layer == 1 + max((library.get(name.split('.')[0]).layer
                                        if name.endswith('.make') else library.get(name).layer
                                        for name in record.depends_on), default=0)
        result = library.run(definition.name + '.make' if definition.kind == 'object' else definition.name, args)
        assert isinstance(result.outcome, values.Ok), (definition.name, result.outcome)
        assert design.render(reference.to_reference(result.outcome.value)) == design.render(expected)


def test_failure_limits_and_large_cycle(library):
    missing = hosts.to_card(tuple(map(int, '010101010101')))
    failure = library.run('accented.make', (missing,), trace=True)
    assert failure.outcome == values.Bottom('invalid')
    assert failure.steps > 0 and failure.trace.outcome == failure.outcome
    assert library.run('start_heavy', (missing,)).outcome == values.Bottom('no_accent')
    a = reference_value('cycle', tuple(map(int, '201001010020010')))
    b = reference_value('cycle', tuple(map(int, '2010010100200101')))
    weave = library.run('weave', (kernel.FnRef('identity'), kernel.FnRef('identity'), a, b))
    assert isinstance(weave.outcome, values.Ok)
    assert len(hosts.cells(weave.outcome.value)) == 240
    assert weave.outcome.value == reference.evaluate('weave',
        (kernel.FnRef('identity'), kernel.FnRef('identity'), a, b))
    assert hosts.cells(hosts.left(a, -1)) == reference.design().left(reference.to_reference(a), -1).cells
    assert library.run('infer_phase', (a, a, b, -1)).outcome == values.Bottom('range')
    assert library.run('infer_phase', (a, a, b, 513)).outcome == values.Bottom('range')
    assert library.run('phase_score', (a, b, -1)).outcome == values.Bottom('range')
    assert library.run('seq', (kernel.FnRef('identity'), kernel.FnRef('identity'), a)).outcome == values.Ok(a)


def test_all_one_and_two_cell_phase_scores(library):
    rhythms = [hosts.to_card(pattern) for length in (1, 2)
               for pattern in product(range(3), repeat=length)]
    cycles = {library.run('cycle.make', (rhythm,)).outcome.value for rhythm in rhythms}
    for first in cycles:
        for second in cycles:
            for shift in range(len(hosts.cells(second))):
                actual = library.run('phase_score', (first, second, shift)).outcome
                expected = reference.evaluate('phase_score', (first, second, shift))
                assert actual == values.Ok(expected)


def test_refinement_constructors_reject_invalid_base_and_forged_cards(library):
    invalid = (values.Card('rhythm', 'beats', ()),
               values.Card('rhythm', 'beats', (2, 3)),
               values.Card('rhythm', 'beats', (True, 2)),
               values.Card('accented', 'val', (hosts.to_card((2,)),)),
               values.Card('cycle', 'val', (hosts.to_card((0, 1)),)))
    for name in ('accented.make', 'cycle.make'):
        for value in invalid:
            assert not isinstance(library.run(name, (value,)).outcome, values.Ok)
    assert library.run('accented.make', (hosts.to_card((0, 1)),)).outcome == values.Bottom('invalid')
    assert library.run('cycle.make', (hosts.to_card((0, 1, 0, 1)),)).outcome == values.Ok(
        reference_value('cycle', (0, 1)))
    assert hosts.make_rhythm((0, 1, 0, 1)) == hosts.to_card((0, 1, 0, 1))


@pytest.mark.parametrize('sort,pattern', [('accented', (0, 2, 1)), ('cycle', (0, 2, 1))])
def test_left_preserves_valid_refinement(library, sort, pattern):
    original = reference_value(sort, pattern)
    expected = reference_value(sort, (1, 0, 2))
    assert hosts.left(original, -1) == expected
    assert library.run('left', (original, -1)).outcome == values.Ok(expected)
    assert library.run('seq', (kernel.FnRef('identity'), kernel.FnRef('identity'),
                               expected)).outcome == values.Ok(expected)


@pytest.mark.parametrize('forged', [
    values.Card('accented', 'val', (hosts.to_card((0, 1)),)),
    values.Card('accented', 'val', (hosts.to_card((2,)), hosts.to_card((2,)))),
    values.Card('accented', 'wrong', (hosts.to_card((2,)),)),
    values.Card('cycle', 'val', (hosts.to_card((0, 1, 0, 1)),)),
    values.Card('cycle', 'val', (hosts.to_card((0,)), 1)),
    values.Card('cycle', 'val', (values.Card('rhythm', 'wrong', (0,)),)),
    values.Card('invented', 'val', (hosts.to_card((2,)),)),
])
def test_forged_cards_are_invalid_at_host_and_learner_boundaries(library, forged):
    assert hosts.cells(forged) == values.Bottom('invalid')
    assert hosts.left(forged, 1) == values.Bottom('invalid')
    assert hosts.identity((forged,)) == values.Bottom('invalid')
    for name, args in [('left', (forged, 1)), ('identity', (forged,)),
                       ('cells', ((hosts.to_card((0,)), forged),)),
                       ('seq', (kernel.FnRef('identity'), kernel.FnRef('identity'), forged)),
                       ('accented.base', (forged,))]:
        assert library.run(name, args).outcome == values.Bottom('invalid')


@settings(max_examples=16, deadline=None)
@given(st.lists(st.integers(min_value=0, max_value=2), min_size=1, max_size=4))
def test_random_offbeat_unfold_and_rotation_boundary(library, pattern):
    rhythm = hosts.to_card(tuple(pattern))
    result = library.run('offbeat', (rhythm,), trace=True)
    unfolded = kernel.evaluate(kernel.inline(nodes.Call('offbeat', (nodes.Lit(rhythm),)), library.scope()),
                               scope=library.scope())
    assert values.outcome_equal(result.outcome, unfolded.outcome)
    assert result.steps == unfolded.steps
    assert unfold_equivalent(result.trace, [Boundary(), Boundary(depth=0)]).ok
    assert result.outcome == values.Ok(reference.evaluate('offbeat', (rhythm,)))
    for shift in range(len(pattern)):
        assert hosts.cells(hosts.left(rhythm, shift)) == tuple(pattern[shift:] + pattern[:shift])


def test_unfold_boundaries_observation_and_promotion(library):
    beat = reference_value('accented', tuple(map(int, '020101002010')))
    for name, args in [('start_heavy', (beat,)),
                       ('offbeat', (beat,)),
                       ('stack', (kernel.FnRef('identity'), kernel.FnRef('start_heavy'), beat))]:
        result = library.run(name, args, trace=True)
        assert unfold_equivalent(result.trace, [Boundary(), Boundary(depth=0),
                             Boundary(open_names=frozenset({name})), Boundary(depth=2)]).ok
        unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),
                                                   library.scope()), scope=library.scope())
        assert values.outcome_equal(result.outcome, unfolded.outcome)
        assert result.steps == unfolded.steps
    before = beat
    observed = library.run('offbeat', (beat,))
    assert observed.outcome == values.Ok(reference.design().offbeat(reference.to_reference(beat)))
    assert beat == before
    assert hosts.cells(beat) == beat.fields[0].fields


def test_declaration_and_committed_export(library, export):
    data = json.loads(Path('worlds/decl/v2/rhythm@1.json').read_text(encoding='utf-8'))
    assert {key: value for key, value in WorldDecl.from_dict(data).to_dict().items()
            if key != "open_kinds"} == data
    assert decl().world_hash() == library.world.world_hash()
    assert json.loads(Path('docs/assets/data/worlds_v2/rhythm.json').read_text(encoding='utf-8')) == export
    assert len(export['story']) == 12
    assert all(card['title'] and card['definition'] for card in export['story'])
    assert all(item['title'] and item['definition'] for category in ('objects', 'operations')
               for item in export['layer0'][category])
    assert all(item['title'] and item['definition'] for item in export['layer0']['combinators']['library'])
    assert all(item['title'] and item['definition'] for item in export['layer0']['observation']['probes'])
    for card, args in zip(export['story'], example_inputs()):
        assert card['examples'][0]['text'] == expression(card['name'], args, card['kind'])
        if card['kind'] == 'combinator':
            assert card['examples'][0]['inputs'][0]['t'] == 'fn'
    assert all(card['examples'][0]['outcome'].get('ok') for card in export['story'])
    assert export['story'][1]['examples'][-1]['outcome'] == {'bottom': 'no_accent'}
    assert all(len(card['examples']) >= 2 for card in export['story'])
    assert all(card['examples'][0]['inputs'] != card['examples'][1]['inputs'] for card in export['story'])
    assert all(item['answer_checked'] for item in export['showcase'])
    assert Path('docs/assets/data/worlds_v2/rhythm.json').stat().st_size < 3_000_000


def test_export_ascii_notation(export):
    forbidden = '⟨⟩⟦⟧⦅⦆♠♦○◉ℚ𝔹'
    def walk(item, key=''):
        if isinstance(item, dict):
            for field, value in item.items():
                if field == 'notation3':  # Notation v3: the generated display block
                    continue
                yield from walk(value, field)
        elif isinstance(item, list):
            for value in item:
                yield from walk(value, key)
        elif isinstance(item, str) and not key.endswith('_zh'):
            yield item
    assert all(not any(char in value for char in forbidden) for value in walk(export))


def test_export_typed_outcomes_and_notation(export):
    by_name = {item['name']: item for item in export['story']}
    for name in ('phase_score', 'best_fit'):
        assert by_name[name]['examples'][0]['outcome']['ok']['t'] == 'Pair'
    for name in ('orbit', 'infer_phase'):
        assert by_name[name]['examples'][0]['outcome']['ok']['t'] == 'List'
    assert by_name['infer_phase']['examples'][0]['outcome']['ok']['f'][0]['t'] == 'Pair'
    for card in export['story']:
        assert card['layer'] == card['def_layer']
        assert card['symbol'].startswith({'object': card['name'].capitalize() + '<',
                                          'operation': card['name'] + '(',
                                          'combinator': '@' + card['name'] + '[',
                                          'observation': '?' + card['name'] + '{'}[card['kind']])
        assert all(example['trace']['kind'] == 'root' and example['trace']['children'] and
                   example['trace']['children'][0]['name'] == (
                       card['name'] + '.make' if card['kind'] == 'object' else card['name'])
                   for example in card['examples'])
    assert '互质长度 12 与 16' not in export['ladder'][2]['knobs_zh']
    assert 'gcd 4' in export['ladder'][2]['knobs_en'] + export['ladder'][2]['what_changes_en']


def test_published_ascii_matches_stored_body(export, library):
    assert [row['name'] for row in export['story'] if 'ascii' not in row] == [
        'accented', 'start_heavy', 'cycle', 'phase_score', 'weave', 'silence_weak', 'infer_phase']
    for row in export['story']:
        digest = export_util.body_sha256(library.get(row['name']).body)
        assert row['body_sha256'] == digest
        if 'ascii' in row:
            assert export_util.source_matches(row['ascii'], digest)
        else:
            assert 'decl' not in row


def test_story_declarations_and_example_sources(export, library):
    for card, inputs in zip(export['story'], example_inputs()):
        assert card['body_sha256'] == export_util.body_sha256(library.get(card['name']).body)
        if 'ascii' in card:
            parsed = notation.parse_definition(card['ascii'])
            assert parsed.layer == card['def_layer']
            assert card['ascii'] == card['decl']
            assert export_util.source_matches(card['ascii'], card['body_sha256'])
        else:
            assert 'decl' not in card
        assert card['design_decl'] == card['design_text']
        if card['kind'] != 'object':
            context = library if card['kind'] == 'combinator' else None
            assert notation.parse_expr(card['examples'][0]['text'], context) == nodes.Call(
                card['name'], tuple(nodes.Lit(value) for value in inputs))
        for example in card['examples']:
            if 'ascii' in example:
                parsed_expr = notation.parse_expr(example['text'])
                assert example['ascii'] == example['text']
                assert card['kind'] in ('operation', 'observation')
                assert parsed_expr.fn == card['name']
                assert len(parsed_expr.args) == len(example['inputs'])
            else:
                assert card['kind'] in ('object', 'combinator')
                with pytest.raises(notation.NotationError):
                    notation.parse_expr(example['text'])
