"""Published notation-v3 blocks must match their machine exports."""

import hashlib
import json
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from opulse import notation3
from opulse.atoms import notation
from opulse.notation3.export import add_notation3, notation3_block

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/assets/data'


def _files():
    # Site-rendered data only: gen_v2 and meta exports are not shown and carry no block.
    return sorted([*(path for family in ('worlds_v2', 'atoms2')
                     for path in (DATA / family).rglob('*.json')
                     if path != DATA / 'atoms2/parse_status.json'),
                   DATA / 'challenge/v2.json'])


def test_unrendered_exports_have_no_block():
    for path in [*(DATA / 'gen_v2').glob('*.json'), *(DATA / 'meta').glob('*.json')]:
        assert 'notation3' not in json.loads(path.read_text(encoding='utf-8')), path


def _block(path):
    if path.name == 'data.js':
        text = path.read_text(encoding='utf-8').split('A2.kernelData=', 1)[1]
        data = json.JSONDecoder().raw_decode(text)[0]
        return data, 'data_js', 'data.js'
    data = json.loads(path.read_text(encoding='utf-8'))
    family = path.relative_to(DATA).parts[0]
    source = (path.relative_to(DATA / family).as_posix() if family == 'gen_v2' else
              path.relative_to(DATA).as_posix() if family == 'atoms2' else None)
    return data, family, source


def test_add_notation3_deterministic_and_idempotent():
    original, family, source = _block(DATA / 'worlds_v2/integer.json')
    data = {key: value for key, value in original.items() if key != 'notation3'}
    first = add_notation3(data, family, source=source)['notation3']
    assert first == notation3_block(data, family, source=source)
    assert add_notation3(data, family, source=source)['notation3'] == first


def test_stamping_ignores_existing_blocks_in_other_files():
    original, family, source = _block(DATA / 'atoms2/grammar.json')
    stripped = {key: value for key, value in original.items() if key != 'notation3'}
    first = add_notation3(stripped, family, source=source)['notation3']
    assert add_notation3(stripped, family, source=source)['notation3'] == first
    assert notation3_block({key: value for key, value in stripped.items()
                            if key != 'notation3'}, family, source=source) == first


def test_cross_file_legend_ignores_stamped_keys(tmp_path, monkeypatch):
    from opulse.notation3 import legend as notation3_legend
    base = tmp_path / 'docs/assets/data/worlds_v2'
    base.mkdir(parents=True)
    world = {'world': 'stamp_test', 'layer0': {}, 'story': [
        {'decl': 'op split(w: Word) -> List = depth_zero_binary_positions(w) L1'}]}
    path = base / 'stamp_test.json'
    path.write_text(json.dumps(world))
    monkeypatch.setattr(notation3_legend, '_ROOT', tmp_path)
    unstamped = notation3_block({'world': 'stamp_test'}, 'challenge')
    world['notation3'] = {'world': 'bogus', 'decl': 'op bogus(x: Int) -> Int given'}
    path.write_text(json.dumps(world))
    stamped = notation3_block({'world': 'stamp_test', 'notation3': {'world': 'bogus'}},
                               'challenge')
    assert stamped == unstamped


def _assert_index_origins(block):
    for world in block['worlds'].values():
        indexed = set()
        for entry in world['legend']:
            mark = entry['mark']
            if mark is None:
                continue
            parsed = notation3.parse_expr(mark)
            if parsed.tag == 'group':
                continue
            atom = parsed.args[0].args[0]
            if atom.index_kind in ('def', 'given_num'):
                key = (atom.family, str(atom.index_value))
                assert key not in indexed
                indexed.add(key)
                assert (atom.index_kind == 'given_num') == (entry['origin'] == 'given')
                if atom.index_kind == 'given_num':
                    assert str(atom.index_value).startswith('0')
                    assert str(atom.index_value)[1] in '123456789'
                else:
                    assert str(atom.index_value)[0] in '123456789'


@pytest.mark.parametrize('path', [*_files(), ROOT / 'docs/assets/js/atoms2/data.js'],
                         ids=lambda path: str(path.relative_to(ROOT)))
def test_published_block(path):
    data, family, source = _block(path)
    assert data['notation3'] == notation3_block(data, family, source=source)
    _assert_index_origins(data['notation3'])


@pytest.mark.parametrize('path', [ROOT / 'docs/worlds/designs.json',
                                  ROOT / 'docs/research/bundles/action-audit-v1/action-export.json'])
def test_extra_published_index_origins(path):
    _assert_index_origins(json.loads(path.read_text(encoding='utf-8'))['notation3'])


def test_research_bundle_matches_world_export():
    path = ROOT / 'docs/research/bundles/action-audit-v1/action-export.json'
    data = json.loads(path.read_text())
    assert data['notation3'] == notation3_block(data, 'worlds_v2')


def test_integer_world_has_formulas():
    data, _, _ = _block(DATA / 'worlds_v2/integer.json')
    assert len(data['notation3']['worlds']['integer']['formulas']) > 0


def test_grammar_support_operations_are_exported_from_kernel():
    data, _, _ = _block(DATA / 'worlds_v2/grammar.json')
    support = {row['name']: row for row in data['support']}
    assert support['zero']['kind'] == 'operation'
    assert support['zero']['layer'] == 1
    assert set(support['zero']) == {'name', 'kind', 'layer'}


def test_design_texts_are_sorted_and_not_counted_as_skipped():
    data = {'world': 'design_test', 'layer0': {},
            'story': [{'name': 'sketch', 'kind': 'operation', 'layer': 1,
                       'design_decl': 'A visual sketch of a machine',
                       'design_text': 'A story about its shape',
                       'decl': 'An informal declaration'}],
            'examples': [{'text': 'An example in everyday language'}]}
    block = notation3_block(data, 'worlds_v2')['worlds']['design_test']
    assert block['designs'] == sorted([
        'A visual sketch of a machine', 'A story about its shape',
        'An informal declaration', 'An example in everyday language',
    ])
    assert not set(block['designs']) & block['formulas'].keys()
    assert block['skipped'] == 0


def test_explicit_design_record_does_not_claim_undeclared_probes():
    data = {'source': 'Design record: illustration, not a runtime artifact.',
            'world': 'design_test', 'agents': [{'probe': '?modes{view}'}]}
    block = notation3_block(data, 'atoms2', source='checks.json')['worlds']['design_test']
    assert '?modes{view}' in block['designs']
    assert '?modes{view}' not in block['formulas']


def test_undeclared_value_sorts_are_design_text_not_phantom_atoms():
    data = {'world': 'design_test', 'layer0': {'objects': [{'name': 'Pair'}]},
            'answer': 'Tuple<Choice<diag,81,625>,Pair<2,4>>'}
    block = notation3_block(data, 'worlds_v2')['worlds']['design_test']
    assert block['designs'] == [data['answer']]
    assert 'Tuple' not in {entry['name'] for entry in block['legend']}


def test_real_world_helpers_are_declared_by_their_generators():
    walk = json.loads((DATA / 'atoms2/walk.json').read_text())
    assert {'add', 'is_even', 'advance'} <= {
        record['name'] for record in walk['layer0']['operations']}
    assert {'read_number'} <= {record['name'] for record in walk['layer0']['observations']}
    circuits = json.loads((DATA / 'worlds_v2/circuits.json').read_text())
    assert {'xor_value', 'adder_value', 'mult_value'} <= {
        record['name'] for record in circuits['support']}
    action = json.loads((DATA / 'worlds_v2/action.json').read_text())
    assert {'scan_default'} <= {record['name'] for record in action['support']}
    data_js = _block(ROOT / 'docs/assets/js/atoms2/data.js')[0]
    assert {'observe0', 'observe1', 'choose0', 'choose1', 'apply'} <= {
        record['name'] for record in data_js['modes']['layer0']['agents']}
    assert {'fib_memo'} <= {record['name'] for record in
                            data_js['modes']['definitions']['integer']}


_DECL_HEAD = re.compile(r'^(template\s+(?:obj|op|comb|obs)|obj|op|comb|obs|law|bridge|template)\s+'
                        r'[@?#~]?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)')
_DECL_KINDS = {'obj': 'object', 'op': 'operation', 'comb': 'combinator', 'obs': 'observation',
               'law': 'law', 'bridge': 'bridge', 'template': 'template'}
_LIST_KINDS = {'objects': 'object', 'operations': 'operation', 'combinators': 'combinator',
               'library': 'combinator', 'observations': 'observation', 'observation': 'observation',
               'probes': 'observation'}
_ATOM_KINDS = frozenset(_DECL_KINDS.values())


def _machine_atoms(data):
    """(name, kind) of every atom a machine export declares, read without the legend code.

    Sources: declaration records (name or def with a kind, or inside a layer-0 kind list),
    template instances, machine calls of an object's dotted operations, machine declaration headers (decl, ascii, declaration, definition) with
    the sort words of their signature, and value sorts (t). Design text (design_*) is skipped.
    """
    atoms = set()

    def header(text):
        match = _DECL_HEAD.match(text.strip())
        if not match:
            return
        atoms.add((match[2], _DECL_KINDS[match[1].split()[0]]))
        head = re.match(r'\s*(?:<[^>]*>)?\s*=\s*([A-Z][A-Za-z_0-9]*)\s*[<\[]', text.strip()[match.end():])
        if match[1] == 'obj' and head and '|' not in text:
            atoms.add((head[1], 'object'))  # obj State = Pair<...>: the head sort
        signature = re.split(r' = | where | given$|\s+L\d+\s*$', text.strip()[match.end():], maxsplit=1)[0]
        for typed, output in re.findall(r':\s*([^,)}\]]+(?:<[^>]*>)?)|->\s*(\S+)', signature):
            sort = (typed or output).strip()
            if '|' in sort:
                continue
            atoms.update((word, 'object') for word in re.findall(r'\b[A-Z][A-Za-z_0-9]+\b', sort))
            if re.fullmatch(r'[a-z][A-Za-z_0-9]+', sort):
                atoms.add((sort, 'object'))

    def walk(value, key=None):
        if isinstance(value, dict):
            name = value.get('name') if isinstance(value.get('name'), str) else value.get('def')
            kind = value.get('kind') if value.get('kind') in _ATOM_KINDS else _LIST_KINDS.get(key)
            if isinstance(name, str) and kind:
                atoms.add((name.lstrip('?@#~'), kind))
            if isinstance(name, str) and key in ('instances', 'templates'):
                symbol = value.get('symbol', '')
                atoms.add((name.lstrip('?@#~'), 'template' if key == 'templates' else
                           {'?': 'observation', '@': 'combinator', '~': 'bridge', '#': 'law'}.get(
                               symbol[:1], 'object' if symbol[:1].isupper() else 'operation')))
            if isinstance(value.get('t'), str):
                atoms.add((value['t'], 'object'))
            if value.get('node') == 'Call' and isinstance(value.get('fn'), str) and '.' in value['fn']:
                atoms.add((value['fn'], 'operation'))  # an object's own operation (Xor.base)
            for item_key, item in value.items():
                if item_key == 'notation3' or item_key.startswith('design'):
                    continue
                if isinstance(item, str) and item_key in ('decl', 'ascii', 'declaration', 'definition'):
                    header(item)
                walk(item, item_key)
        elif isinstance(value, list):
            for item in value:
                if (isinstance(item, str) and key in _LIST_KINDS and
                        re.fullmatch(r'[?@~#]?[A-Za-z_]\w*', item)):
                    atoms.add((item.lstrip('?@#~'), _LIST_KINDS[key]))
                elif isinstance(item, str) and key == 'decl':
                    header(item)
                else:
                    walk(item, key)

    walk(data)
    return atoms


def _export_legends():
    """Yield (path, world, legend rows, machine atoms of the export and its world)."""
    from tools.notation3_export import targets

    builtins = {(name, 'object') for name in ('Int', 'Bool', 'List', 'int', 'bool', 'list')}
    for path in targets():
        data = (_block(path)[0] if path.name == 'data.js' else json.loads(path.read_text()))
        block = data.pop('notation3')
        own = _machine_atoms(data) | builtins
        for world, record in block['worlds'].items():
            declared = set(own)
            base = world.split('@')[0].removeprefix('design:')
            for family in ('worlds_v2', 'gen_v2', 'meta'):
                world_file = DATA / family / (base + '.json')
                if world_file.exists():
                    world_data = json.loads(world_file.read_text())
                    world_data.pop('notation3', None)
                    declared |= _machine_atoms(world_data)
            yield path, world, record['legend'], declared


def _declared_entry(entry, declared):
    return ((entry['name'], entry['kind']) in declared or
            entry.get('form_of') is not None and (entry['form_of'], 'object') in declared or
            entry['kind'] == 'template' and (entry['name'], 'object') in declared)


def test_every_legend_entry_is_a_declared_machine_atom_of_its_world():
    # The legend lists only atoms that the world's machine declarations name (and the
    # constructors of declared objects); design text never adds an entry.
    count = 0
    for path, world, legend, declared in _export_legends():
        for entry in legend:
            count += 1
            # Identifiers, dotted constructors, Bot.bot:<sha256> programs, and kernel value
            # sorts such as list[value]; never a type expression or a word of design text.
            assert re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(\[[a-z_]+\])?(\.[A-Za-z_][A-Za-z_0-9]*)?'
                                r'(:[0-9a-f]{64})?', entry['name']), (path, world, entry['name'])
            assert not re.fullmatch(r'L[0-9]+', entry['name']), (path, world, entry['name'])
            assert _declared_entry(entry, declared), (path, world, entry['name'], entry['kind'])
    assert count > 3000


def test_design_text_adds_no_legend_entry():
    data = {'world': 'design_test', 'layer0': {'objects': [{'name': 'Grid', 'decl': 'obj Grid<rows: Int> given'}]},
            'story': [{'name': 'walk', 'kind': 'combinator', 'def_layer': 3,
                       'design_decl': 'comb @walk[probe: Run->Run](s: Run, target: Cell=?goal{s}) '
                                      '-> Run = if Ready then Bottom(unknown) L3'},
                      {'name': 'cf', 'kind': 'object', 'def_layer': 2,
                       'design_decl': 'obj CF = sealed finite List<Int> from Frac unless singleton L10'}]}
    block = notation3_block(data, 'worlds_v2')['worlds']['design_test']
    names = {entry['name'] for entry in block['legend']}
    assert {'Grid', 'walk', 'cf'} <= names
    assert not names & {'L3', 'L10', 'Run', 'Cell', 'Cell=?goal{s}', 'Ready', 'Frac', 'CF', 'Bottom'}


def test_refinement_unwraps_show_the_unwrap_operation_not_the_object():
    # Xor.base is the kernel unwrap of the Xor refinement (worlds_v2/circuits/world.py):
    # base(make(g)) is g again, so the formula shows the unwrap operation applied to the
    # constructed object, never 'Xor of Xor'.
    record = json.loads((DATA / 'worlds_v2/circuits.json').read_text())['notation3']['worlds']['circuits']
    marks = {(entry['name'], entry['kind']): entry['display'] for entry in record['legend']}
    formulas = record['formulas']
    xor = f"{marks['Xor.base', 'operation']} ({marks['Xor', 'object']} ({marks['xor_graph', 'operation']}()))"
    adder = (f"{marks['Adder8.base', 'operation']} ({marks['Adder8', 'object']} "
             f"({marks['adder8_graph', 'operation']}()))")
    out_pin, bits = marks['out_pin', 'observation'], marks['bits', 'object']
    first_diff = marks['first_diff', 'observation']
    expected = {
        '?out_pin{Xor.base(Xor.make(xor_graph())),bits.list<1, 0>,0}': f'{out_pin}⟨{xor}, {bits}(1, 0), 0⟩',
        '?out_pin{Xor.base(Xor.make(xor_graph())),bits.list<0, 1>,0}': f'{out_pin}⟨{xor}, {bits}(0, 1), 0⟩',
        '?truth_table{Xor.base(Xor.make(xor_graph()))}': f"{marks['truth_table', 'observation']}⟨{xor}⟩",
        '?out_pin{Adder8.base(Adder8.make(adder8_graph())),bits.list<0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 1, 0>,8}':
            f'{out_pin}⟨{adder}, {bits}(0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 1, 0), 8⟩',
        '?first_diff{Adder8.base(Adder8.make(adder8_graph())),cut_add8()}':
            f"{first_diff}⟨{adder}, {marks['cut_add8', 'operation']}()⟩",
        '?first_diff{Adder8.base(Adder8.make(adder8_graph())),and2()}':
            f"{first_diff}⟨{adder}, {marks['and2', 'operation']}()⟩",
    }
    for text, display in expected.items():
        assert formulas[text]['display'] == display, text
    for sort in ('Xor', 'Adder8'):
        unwrap = next(entry for entry in record['legend'] if entry['name'] == sort + '.base')
        owner = next(entry for entry in record['legend'] if entry['name'] == sort)
        assert unwrap['kind'] == 'operation' and unwrap['display'] != owner['display']
        assert (unwrap['layer'], unwrap['origin']) == (owner['layer'], owner['origin'])


def test_dotted_symbols_show_their_declared_operation():
    # Field reads and unwraps declared as operations show their own mark, not the object's.
    for world, names in (('roads', ('ClosureRaw.base', 'RouteRaw.vertices', 'RouteRaw.graph',
                                    'ClosureRaw.closed_edges', 'Edges.edge_ids')),
                         ('hidden', ('BeliefPair.b', 'BeliefPair.r'))):
        record = json.loads((DATA / f'worlds_v2/{world}.json').read_text())['notation3']['worlds'][world]
        marks = {(entry['name'], entry['kind']): entry['display'] for entry in record['legend']}
        for name in names:
            assert record['formulas'][name + '(...)']['display'] == marks[name, 'operation'], name
            assert marks[name, 'operation'] != marks[name.split('.')[0], 'object']


def test_every_export_legend_reports_declared_name_collisions():
    # The glyph family tells the kind, so a world that declares one name under two kinds
    # keeps both atoms, and only these two: a layer-0 operation next to the probe of that
    # name, or an object next to its constructor operation (noted 'constructor of <mark>').
    # Both atoms of a pair must be declared by the world itself (_machine_atoms).
    pairs = 0
    for path, world, legend, declared in _export_legends():
        names = [entry['name'] for entry in legend]
        assert len({(entry['name'], entry['kind']) for entry in legend}) == len(names)
        assert all(not name.startswith('__opulse_') for name in names), (path, world)
        assert all(entry.get('note') != 'undeclared helper' for entry in legend)
        for name in {name for name in names if names.count(name) > 1}:
            pairs += 1
            rows = [entry for entry in legend if entry['name'] == name]
            kinds = {entry['kind'] for entry in rows}
            for entry in rows:
                assert (name, entry['kind']) in declared, (path, world, name, entry['kind'])
            if kinds == {'operation', 'observation'}:
                assert all(entry['origin'] == 'given' for entry in rows), (path, world, name)
            elif kinds == {'operation', 'object'}:
                constructor = next(entry for entry in rows if entry['kind'] == 'operation')
                target = next(entry for entry in rows if entry['kind'] == 'object')
                assert constructor.get('note') == 'constructor of ' + target['display'], (
                    path, world, name)
            else:
                raise AssertionError((path, world, name, sorted(kinds)))
    assert pairs > 50


def test_every_export_formula_references_declared_machine_kinds():
    from tools.notation3_export import targets

    sigils = {'?': 'observation', '@': 'combinator', '~': 'bridge', '#': 'law'}
    count = 0
    for path in targets():
        block = (_block(path)[0]['notation3'] if path.name == 'data.js' else
                 json.loads(path.read_text())['notation3'])
        for world, record in block['worlds'].items():
            entries = {}
            for entry in record['legend']:
                entries.setdefault(entry['name'], []).append(entry)
            for text, formula in record['formulas'].items():
                machine_text = (text.split(' = ', 1)[0].split(' where ', 1)[0]
                                if text.endswith(' given') else text)
                tokens = [match.group() for match in notation._TOKEN.finditer(machine_text)]
                for index, token in enumerate(tokens[:-1]):
                    if not re.fullmatch(r'[a-z][A-Za-z_0-9]*', token):
                        continue
                    if token in ('fail', 'if', 'then', 'else', 'in', 'let', 'rec',
                                 'memo', 'measure', 'where', 'given', 'for'):
                        continue
                    previous = tokens[index - 1] if index else ''
                    following = tokens[index + 1]
                    if previous == '.':
                        sort = tokens[index - 2] if index > 1 else ''
                        constructor = next((entry for entry in entries.get(sort + '.' + token, ())
                                            if entry['kind'] == 'operation'), None)
                        parent = next((entry for entry in entries.get(sort, ())
                                       if entry['kind'] == 'object'), None)
                        if (constructor and not constructor.get('form_of') and following == '(' and
                                not text.startswith('op ')):
                            # An unwrap or field read (Xor.base, BeliefPair.b) shows its own
                            # operation mark, never the object it reads.
                            assert constructor['display'] in formula['display'], (path, world, text)
                            if parent:
                                assert not re.search(re.escape(parent['display']) + r'(?![₀-₉])\s*\(?$',
                                                     formula['display']), (path, world, text)
                            count += 1
                        elif constructor and text.startswith('op ' + sort + '.' + token):
                            assert constructor['display'] in formula['display'], (path, world, text)
                            count += 1
                        elif parent and len(parent.get('forms', ())) == 1:
                            assert parent['display'] in formula['display'], (path, world, text)
                            count += 1
                        elif constructor and '...' not in text:
                            assert constructor['display'] in formula['display'], (path, world, text)
                            count += 1
                        elif parent and parent['kind'] == 'object':
                            assert parent['display'] in formula['display'], (path, world, text)
                            count += 1
                        continue
                    kind = sigils.get(previous) if following in ('{', '[', '(') else None
                    if kind is not None:
                        assert token in entries, (path, world, text, token, kind)
                    if kind is None and following == '(' and len(entries.get(token, ())) == 1:
                        kind = entries[token][0]['kind']
                    if kind == 'operation' and not any(entry['kind'] == kind for entry in entries.get(token, ())) and following == '(':
                        equivalent = [entry for entry in entries.get(token, ())
                                      if entry['kind'] in ('observation', 'object') and entry['origin'] == 'given']
                        assert len(equivalent) == 1, (path, world, text, token)
                        kind = equivalent[0]['kind']
                    if kind is None or token not in entries:
                        continue
                    matching = [entry for entry in entries[token] if entry['kind'] == kind]
                    assert len(matching) == 1, (path, world, text, token, kind)
                    entry = matching[0]
                    if entry['mark']:
                        visible = (entry['display'][1:-1] if entry['display'].startswith('(') and
                                   entry['display'].endswith(')') else entry['display'])
                        assert visible in formula['display'], (path, world, text, token)
                    count += 1
    print(f'Validated {count} machine-kind references across published formulas.')
    assert count > 100


def test_every_export_display_mark_belongs_to_its_legend():
    from tools.notation3_export import targets

    def marks(node):
        if isinstance(node, notation3.Mark):
            yield node
        elif isinstance(node, (tuple, list)):
            for item in node:
                yield from marks(item)
        elif is_dataclass(node):
            for field in fields(node):
                yield from marks(getattr(node, field.name))

    count = 0
    for path in targets():
        block = (_block(path)[0]['notation3'] if path.name == 'data.js' else
                 json.loads(path.read_text())['notation3'])
        for world, record in block['worlds'].items():
            declared = {(mark.family, mark.index_kind, mark.index_value)
                        for entry in record['legend'] for mark in marks(
                            notation3.parse_expr(entry['display']))}
            for text, formula in record['formulas'].items():
                for mark in marks(notation3.parse(formula['display'])):
                    if mark.index_kind == 'slot' or mark.family in ('bbZ', 'bbB'):
                        continue
                    assert (mark.family, mark.index_kind, mark.index_value) in declared, (
                        path, world, text, mark)
                    count += 1
    print(f'Validated {count} non-slot display marks across published formulas.')
    assert count > 100


def test_review_formulas_use_declared_marks():
    def world(family, name, identifier=None):
        data = json.loads((DATA / family / (name + '.json')).read_text())
        return data['notation3']['worlds'][identifier or name]

    calendar = world('worlds_v2', 'calendar')
    assert calendar['formulas']['obs ?workday{s} = lt(?weekday{s}, 5) L1']['display'] == (
        'Â₁⟨s⟩ = { Â⟨s⟩ < 5 }')
    audit = world('worlds_v2', 'comb_obs')['formulas']
    text = next(text for text in audit if text.startswith('obs ?audit{s} ='))
    assert audit[text]['display'].startswith('Ĝ₄⟨s⟩ = { let events = Ĵ⟨s⟩ in '
                                             'let orders_map = Ĥ⟨s⟩')
    assert hashlib.sha256(audit[text]['display'].encode()).hexdigest() == (
        '69ff489b5cd99a8d742e651ec686342e1d0e8bac9db0b85084f31d30d91ca547')
    tower = world('atoms2', 'first_tower', 'integer')
    assert tower['formulas']['obs ?seen_value{value} = ?value{value} L1']['display'] == (
        'Ĉ₂⟨value⟩ = { Â⟨value⟩ }')
    shadows = world('worlds_v2', 'shadows')
    text = 'plan(front, diag, anti, candidates(m, capture(top, side, s)))'
    assert shadows['formulas'][text]['display'] == 'Λ₄[★, ☆, ♦₀₁] (m ●₃ (Γ₁[◆, ◇] s))'
    assert not any(row['name'] == 'plan' and row['origin'] == 'given'
                   for row in shadows['legend'])
    action = world('worlds_v2', 'action')
    text = ('obs ?front_clear{b: Bot} -> bool = not(?front_wall{b}) '
            'and not(?front_water{b}) L1')
    assert action['formulas'][text]['display'] == (
        'Â₁⟨b⟩ = { not Â⟨b⟩ and not Ĉ⟨b⟩ }')
    pixels = world('worlds_v2', 'pixels')
    for name in ('A0', 'B0'):
        entry = next(entry for entry in pixels['legend'] if entry['name'] == name)
        assert pixels['formulas'][name]['display'] == entry['display']


def test_undeclared_formula_reports_world_field_text_name_and_kind():
    data = {'world': 'design_test', 'layer0': {}, 'probe': '?missing{s}'}
    with pytest.raises(ValueError, match=(r"world='design_test' field='probe' "
                                           r"text='\?missing\{s\}' name='missing' "
                                           r"kind='observation'")):
        notation3_block(data, 'worlds_v2')


def test_duplicate_prose_and_design_is_independent_of_field_order():
    text = 'Describe the result in words.'
    base = {'world': 'design_test', 'layer0': {}}
    for record in ({'name': 'example', 'kind': 'operation', 'layer': 1,
                    'definition': text, 'design_decl': text},
                   {'name': 'example', 'kind': 'operation', 'layer': 1,
                    'design_decl': text, 'definition': text}):
        block = notation3_block({**base, 'story': [record]}, 'worlds_v2')['worlds']['design_test']
        assert block['designs'] == [text]


def test_parseable_declarations_are_not_design_texts():
    data = {'world': 'design_test', 'layer0': {},
            'story': [{'decl': 'op add(a: Int, b: Int) -> Int = a L1'}]}
    block = notation3_block(data, 'worlds_v2')['worlds']['design_test']
    assert block['designs'] == []
    assert 'op add(a: Int, b: Int) -> Int = a L1' in block['formulas']


def test_non_design_conversion_failures_count_as_skipped():
    data = {'world': 'design_test', 'layer0': {},
            'ascii': 'template obj Quot[T: obj, canon: op] = refine T canon(canon) L1'}
    block = notation3_block(data, 'worlds_v2')['worlds']['design_test']
    assert block['designs'] == []
    assert block['formulas'] == {}
    assert block['skipped'] == 1


def test_design_call_under_design_field_and_skipped_report():
    template = 'template obj Quot[T: obj, canon: op] = refine T canon(canon) L1'
    with pytest.raises(ValueError, match="name='cut_certificate' kind='observation'"):
        notation3_block({'world': 'design_test', 'layer0': {},
                         'input': '?cut_certificate{Metro,A,L}'}, 'worlds_v2')
    data = {'world': 'design_test', 'layer0': {}, 'design_text': '?cut_certificate{Metro,A,L}',
            'ascii': template}
    report = []
    block = notation3_block(data, 'worlds_v2', report=report)['worlds']['design_test']
    assert block['designs'] == ['?cut_certificate{Metro,A,L}']
    assert report and report[0][:3] == ('design_test', 'ascii', template)


def test_published_spellings_round_trip():
    for path in [*_files(), ROOT / 'docs/assets/js/atoms2/data.js']:
        data, _, _ = _block(path)
        for world in data['notation3']['worlds'].values():
            marks = [entry['mark'] for entry in world['legend']]
            assert len(marks) == len(set(marks)), path
            pairs = [(entry['display'], entry['mark']) for entry in world['legend']]
            pairs.extend((entry['signature']['display'], entry['signature']['ascii'])
                         for entry in world['legend'] if entry['signature'])
            for entry in world['formulas'].values():
                pairs.append((entry['display'], entry['ascii']))
                if entry['signature']:
                    pairs.append((entry['signature']['display'], entry['signature']['ascii']))
            pairs.extend((segment[1], segment[2]) for segments in world['prose'].values()
                         for segment in segments if segment[0] == 'f')
            for display, ascii_text in pairs:
                assert notation3.to_ascii(display) == ascii_text, (path, display)
                assert notation3.to_display(ascii_text) == display, (path, ascii_text)


@pytest.mark.parametrize('family,path,key', [
    ('tower decl', 'worlds_v2/integer.json', 'decl'),
    ('example call', 'atoms2/first_tower.json', 'call'),
    ('catalog layer0 decl', 'worlds_v2/roads.json', 'decl'),
    ('ladders task definition', 'challenge/v2.json', 'definition'),
    ('roads declaration', 'atoms2/roads.json', 'declaration'),
    ('walk declaration', 'atoms2/walk.json', 'declaration'),
    ('first_tower call', 'atoms2/first_tower.json', 'call'),
])
def test_machine_join_coverage(family, path, key):
    data, _, _ = _block(DATA / path)
    blocks = data['notation3']['worlds']
    found = []
    missed = []

    def visit(node, world=None):
        if isinstance(node, dict):
            world = node.get('world', world)
            if key in node and isinstance(node[key], str):
                text = node[key]
                try:
                    notation.parse_definition(text)
                except (ValueError, TypeError):
                    try:
                        notation.parse_expr(text)
                    except (ValueError, TypeError):
                        pass
                    else:
                        (found if world in blocks and text in blocks[world]['formulas'] else missed).append(text)
                else:
                    (found if world in blocks and text in blocks[world]['formulas'] else missed).append(text)
            for child_key, value in node.items():
                if child_key != 'notation3':
                    visit(value, world)
        elif isinstance(node, list):
            for value in node:
                visit(value, world)

    visit(data, next(iter(blocks)) if len(blocks) == 1 else None)
    if family == 'catalog layer0 decl' and path == 'worlds_v2/roads.json':
        failures = next(row['ascii'] for row in data['story'] if row.get('name') == 'failures')
        assert missed == []
        assert failures in blocks['roads']['formulas']
        assert blocks['roads']['skipped'] == 0
        return
    ratio = len(found) / (len(found) + len(missed)) if found or missed else 1
    print(f'{family}: {len(found)}/{len(found) + len(missed)} = {ratio:.1%}; misses: {missed[:10]}')
    assert ratio >= 0.95, f'{family}: {len(found)}/{len(found) + len(missed)}; misses: {missed[:10]}'
