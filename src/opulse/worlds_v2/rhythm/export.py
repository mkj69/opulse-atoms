"""Export kernel-computed depth tower, exact answers, and bounded traces."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export

from . import hosts, reference
from .story import build_library, definitions, reference_value

ROOT = Path(__file__).resolve().parents[4]

ENGLISH = {
    'accented': 'Refine a rhythm containing at least one heavy beat.',
    'start_heavy': 'Rotate a heavy beat to the origin without changing the remaining cells.',
    'stack': 'Apply two unary operations to one rhythm and take their cellwise maximum.',
    'offbeat': 'Count heavy beats at odd cell indices.',
    'cycle': 'Normalize a rhythm to its shortest repeating block while preserving its origin.',
    'phase_score': 'Compare complete cycles at a shift by mismatch count and offbeat count.',
    'weave': 'Combine two transformed cycles across their least common period.',
    'best_fit': 'Find the lexicographically best shift of the second cycle.',
    'silence_weak': 'Erase weak beats and normalize the resulting cycle.',
    'orbit': 'Apply one operation to every distinct phase in first-seen order.',
    'phase_count': 'Count distinct shifts achieving the minimum mismatch score.',
    'infer_phase': 'Search both voices for globally optimal phase pairs within a mismatch budget.',
}

LADDER_EN = (
    ('8-12 cells; one voice; up to one heavy beat',
     'Check each rotated cell and the failure when no heavy beat exists.'),
    ('12-16 cells; two intensities; equal-length voices',
     'Contrast sequential composition with simultaneous cellwise maximum.'),
    ('12- and 16-cell voices; 48-cell LCM window',
     'Compare every shift over the full window; these lengths have gcd 4.'),
    ('15- and 16-cell voices; 240-cell LCM; 2-3 perturbed cells',
     'Distinguish tied best shifts from aliases caused by lost observations.'),
    ('Up to 32 cells per voice; LCM at most 512; up to 1024 phase pairs',
     'Enumerate both phases and certify all global optima within bounds.'),
)


def portable_body(body):
    return nodes.to_json(body)


def typed_value(value, *, sequence=False):
    if isinstance(value, kernel.FnRef):
        return values.encode(value)
    if isinstance(value, tuple):
        return {'t': 'List' if sequence else 'Pair',
                'tag': 'list' if sequence else 'pair',
                'f': [typed_value(item) for item in value]}
    return export_util._value(value)


def expression(name, args, kind):
    def literal(value):
        if isinstance(value, kernel.FnRef):
            return value.name
        return notation.print_value(value)

    if kind == 'combinator':
        slots = 1 if name == 'orbit' else 2
        return f'@{name}[{",".join(map(literal, args[:slots]))}]({",".join(map(literal, args[slots:]))})'
    if kind == 'observation':
        return f'{name}({",".join(map(literal, args))})'
    operation = f'{name}.make' if kind == 'object' else name
    return f'{operation}({",".join(map(literal, args))})'


def source_definition(record, context):
    written = replace(record, status='written', evidence=None, contract=None,
                      id=None, cost=Cost())
    try:
        source = notation.print_definition(written, context)
    except (ValueError, TypeError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(record.body)) else None


def encoded_inputs(args):
    return [typed_value(arg) for arg in args]


def example_inputs():
    a = reference_value('cycle', tuple(map(int, '020101002010')))
    b = reference_value('cycle', tuple(map(int, '2010010100200101')))
    accented = reference_value('accented', hosts.cells(a))
    observed = reference_value('cycle', tuple(map(int, '200201102211101211022010120201102012101212012010')))
    stack = hosts.to_card(tuple(map(int, '221111022110')))
    return (
        (hosts.to_card(hosts.cells(a)),), (accented,),
        (kernel.FnRef('start_heavy'), kernel.FnRef('identity'), accented), (stack,),
        (hosts.to_card(hosts.cells(a) * 2),), (a, b, 3),
        (kernel.FnRef('identity'), kernel.FnRef('identity'), a, hosts.left(b, 3)),
        ((a, b),), (a,), (kernel.FnRef('silence_weak'), a),
        ((a, b),), (observed, a, b, 1))


def fresh_inputs(library):
    accented = reference_value('accented', tuple(map(int, '010202100120')))
    second = reference_value('cycle', tuple(map(int, '120110020011')))
    first = reference_value('cycle', hosts.cells(accented))
    layered = library.run('stack', (kernel.FnRef('start_heavy'),
                                    kernel.FnRef('identity'), accented)).outcome.value
    woven = library.run('weave', (kernel.FnRef('identity'), kernel.FnRef('identity'),
                                  first, second)).outcome.value
    small_a = reference_value('cycle', (0, 2))
    small_b = reference_value('cycle', (2, 1, 0))
    observed = library.run('weave', (kernel.FnRef('identity'), kernel.FnRef('identity'),
                                     small_a, small_b)).outcome.value
    return (
        ('Accented<"010202100120">', (hosts.to_card(hosts.cells(accented)),)),
        ('start_heavy(Accented<"010202100120">)', (accented,)),
        ('@stack[start_heavy,identity](Accented<"010202100120">)',
         (kernel.FnRef('start_heavy'), kernel.FnRef('identity'), accented)),
        ('?offbeat{@stack[start_heavy,identity](Accented<"010202100120">)}', (layered,)),
        ('Cycle<"010202100120010202100120">', (hosts.to_card(hosts.cells(accented) * 2),)),
        ('phase_score(Cycle<"010202100120">,Cycle<"120110020011">,2)', (first, second, 2)),
        ('@weave[identity,identity](Cycle<"010202100120">,Cycle<"120110020011">)',
         (kernel.FnRef('identity'), kernel.FnRef('identity'), first, second)),
        ('?best_fit{Pair<Cycle<"010202100120">,Cycle<"120110020011">>}', ((first, second),)),
        ('silence_weak(@weave[identity,identity](Cycle<"010202100120">,Cycle<"120110020011">))',
         (woven,)),
        ('@orbit[silence_weak](Cycle<"010202100120">)',
         (kernel.FnRef('silence_weak'), first)),
        ('?phase_count{Pair<Cycle<"010202100120">,Cycle<"120110020011">>}', ((first, second),)),
        ('infer_phase(@weave[identity,identity](Cycle<"02">,Cycle<"210">),Cycle<"02">,Cycle<"210">,0)',
         (observed, small_a, small_b, 0)),
    )


def build_export():
    design = json.loads((ROOT / 'worlds/catalogue/depth/rhythm.json').read_text(encoding='utf-8'))
    library = build_library()
    declaration = library.world.to_dict()
    entries = []
    context = {'kinds': {definition.name: definition.kind for definition in definitions()},
               'op_arity': {'stack': 2, 'weave': 2, 'orbit': 1}}
    additional = fresh_inputs(library)
    for definition, args, card in zip(definitions(), example_inputs(), design['tower']):
        operation = definition.name + '.make' if definition.kind == 'object' else definition.name
        result = library.run(operation, args, trace=True)
        if not isinstance(result.outcome, values.Ok):
            raise TypeError(f'{definition.name}: {result.outcome!r}')
        if reference.design().render(reference.to_reference(result.outcome.value)) != card['value']:
            raise ValueError(f'{definition.name}: design example mismatch')
        record = library.get(definition.name)
        outcome = {'ok': typed_value(result.outcome.value, sequence=definition.name in ('orbit', 'infer_phase'))}
        entries.append({
            'layer': record.layer, 'def_layer': record.layer, 'kind': record.kind, 'name': record.name,
            'body_sha256': export_util.body_sha256(record.body),
            **({'decl': source_text} if (source_text := source_definition(record, context)) else {}),
            'design_decl': card['decl'],
            'plain_zh': card['plain'], 'symbol': (
                record.name.capitalize() + '<...>' if record.kind == 'object' else
                '@' + record.name + '[...]' if record.kind == 'combinator' else
                '?' + record.name + '{...}' if record.kind == 'observation' else
                record.name + '(...)'),
            'title': record.name.replace('_', ' ').title(),
            'definition': ENGLISH[record.name],
            'title_zh': card['plain'].split('，')[0], 'definition_zh': card['plain'],
            'depends_on': list(record.depends_on), 'body': portable_body(record.body),
            'status': record.status, 'evidence': record.evidence.to_dict(),
            'contract': record.contract.to_dict(), 'cost': record.cost.to_dict(),
            'examples': [{'text': expression(definition.name, args, definition.kind), 'inputs': encoded_inputs(args),
                          'outcome': outcome, 'steps': result.steps,
                          'trace': export_util.trace_json(result.trace, max_nodes=25)}]})
        _, extra_args = additional[len(entries) - 1]
        extra_run = library.run(operation, extra_args, trace=True)
        expected_extra = reference.evaluate(definition.name, extra_args)
        if not isinstance(extra_run.outcome, values.Ok) or extra_run.outcome.value != expected_extra:
            raise ValueError(f'{definition.name}: independent fresh-input mismatch')
        entries[-1]['examples'].append({
            'text': expression(definition.name, extra_args, definition.kind), 'inputs': encoded_inputs(extra_args),
            'outcome': {'ok': typed_value(extra_run.outcome.value, sequence=definition.name in ('orbit', 'infer_phase'))}, 'steps': extra_run.steps,
            'trace': export_util.trace_json(extra_run.trace, max_nodes=12)})
    failure = library.run('start_heavy', (hosts.to_card((0, 1) * 6),), trace=True)
    if failure.outcome != reference.evaluate('start_heavy', (hosts.to_card((0, 1) * 6),)):
        raise ValueError('failure example differs from the depth oracle')
    entries[1]['examples'].append({
        'text': expression('start_heavy', (hosts.to_card((0, 1) * 6),), 'operation'),
        'inputs': [values.encode(hosts.to_card((0, 1) * 6))],
        'outcome': values.encode_outcome(failure.outcome), 'steps': failure.steps,
        'trace': export_util.trace_json(failure.trace, max_nodes=25)})
    showcase_names = ('best_fit', 'infer_phase', 'phase_count')
    showcases = []
    for item, name in zip(design['showcase'], showcase_names):
        source = entries[next(index for index, entry in enumerate(entries) if entry['name'] == name)]
        actual = source['examples'][0]['outcome']['ok']
        args = example_inputs()[7 if name == 'best_fit' else 11 if name == 'infer_phase' else 10]
        expected = reference.evaluate(name, args)
        if name == 'phase_count':
            checked = actual == typed_value(expected) and item['answer'] == str(expected == 1).lower()
        else:
            checked = (actual == typed_value(expected, sequence=name == 'infer_phase') and
                       item['answer'] == reference.design().render(reference.to_reference(expected)))
        showcases.append({**{key: value for key, value in item.items() if key != 'why_hard'},
                          'why_hard_zh': item['why_hard'].replace('两个互质小节', '两个不同长度的小节'),
                          'answer_checked': checked,
                          'answer_check_method': 'kernel outcome; independent depth oracle; exhaustive discrete search',
                          'kernel_outcome': actual})
    return {
        'schema': 'opulse.world_v2_export/1', 'world': 'rhythm', 'version': 1, 'wave': 1,
        'tower_source': 'depth', 'title': declaration['title'], 'title_zh': design['name'],
        'pitch_zh': design['pitch'].replace('互质拍长', '不同拍长'), 'modality_zh': '时间 / 听觉 / 格子',
        'decl': declaration, 'layer0': {
            'objects': [{'name': item['name'], 'form': item['form'], 'symbol': item['name'].capitalize() + '<...>',
                         'title': item['name'].capitalize(),
                         'definition': ('A rhythm is an origin-preserving sequence of 1 to 512 ternary cells.'
                                        if item['name'] == 'rhythm' else
                                        item['doc'] or f'{item["name"].capitalize()} is a generic scalar sort.'),
                         'doc': item.get('doc', ''),
                         'decl': design['layer0']['objects'][0].split(' — ')[0]
                                 if item['name'] == 'rhythm' else f"obj {item['name'].capitalize()} given",
                         'doc_zh': design['layer0']['objects'][0].split(' — ')[1]
                                   if item['name'] == 'rhythm' else ''}
                        for item in declaration['objects']],
            'operations': [{'name': item['name'], 'symbol': item['name'] + '(...)', 'rule': item['rule'],
                            'title': item['name'].replace('_', ' ').title(),
                            'definition': item['rule'].rstrip('.') + '.',
                            'rule_zh': design['layer0']['operations'][0] if item['name'] == 'left' else '',
                            'errors': item['errors'], 'cost': item['cost'],
                            'inputs': [{'name': edge['name'], 'sort': edge['sort']} for edge in item['inputs']],
                            'output': item['output']['sort'], 'decl': next(
                                (text.split(' — ')[0] for text in design['layer0']['operations']
                                 if text.startswith('op '+item['name']+'(')),
                                f"op {item['name']}(...) given"),
                            'doc_zh': next((text.split(' — ')[1] for text in design['layer0']['operations']
                                            if text.startswith('op '+item['name']+'(')), '')}
                           for item in declaration['operations']],
            'combinators': {**declaration['combinators'],
                'library': [{**spec,
                    'symbol': '@' + spec['name'] + '[...]',
                    'title': spec['name'].replace('_', ' ').title(),
                    'definition': 'Apply the first operation, then the second operation to its result.',
                    'decl': design['layer0']['combinators'][0].split(' — ')[0],
                    'doc_zh': design['layer0']['combinators'][0].split(' — ')[1]}
                    for spec in declaration['combinators']['library']]},
            'observation': {**{key: declaration['observation'][key] for key in
                                   ('truth', 'show', 'judge_view')},
                'probes': [{**probe,
                            'title': probe['name'].replace('_', ' ').title(),
                            'definition': 'Read every public ternary cell in the rhythm.',
                            'symbol': '?' + probe['name'] + '{...}',
                            'decl': design['layer0']['observations'][0].split(' — ')[0],
                            'doc_zh': design['layer0']['observations'][0].split(' — ')[1]}
                           for probe in declaration['observation']['probes']]}},
        'story': entries,
        'ladder': [{'level': rung['level'], 'knobs_zh': rung['knobs'].replace('互质长度 12 与 16', '长度 12 与 16'),
                    'what_changes_zh': rung['what_changes'], 'knobs_en': english[0],
                    'what_changes_en': english[1]}
                   for rung, english in zip(design['ladder'], LADDER_EN)],
        'showcase': showcases,
        'modalities_zh': design['modalities'], 'toy_risk_zh': design['toy_risk'],
        'tags': {'domain': 'music', 'modalities': ['text', 'image', 'audio'],
                 'open_kinds': ['object', 'operation', 'combinator', 'observation'],
                 'star_kind': 'combinator', 'reasoning': ['compute', 'search', 'counting', 'inference'],
                 'state': 'stateless', 'outcomes': 'deterministic', 'visibility': 'full',
                 'agents': 1, 'scale': '1-512 cells; 12 definitions',
                 'difficulty': '8-cell single rhythm to 1024 phase pairs',
                 'uses': ['evaluation', 'teaching', 'experiment']},
        'open_kinds': ['object', 'operation', 'combinator', 'observation'],
        'emerges_zh': design['pitch'].replace('互质拍长', '不同拍长'),
        'checking_zh': '独立离散全枚举与有界内核展开。'}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == '__main__':
    output = ROOT / 'docs/assets/data/worlds_v2/rhythm.json'
    output.write_text(json.dumps(build_export(), sort_keys=True, indent=1,
                                 ensure_ascii=False) + '\n', encoding='utf-8')
