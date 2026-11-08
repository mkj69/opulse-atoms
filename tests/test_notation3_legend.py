"""Published-export and synthetic-world checks for the v3 legend."""

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from opulse import notation3 as n3
from opulse.notation3.legend import (
    Atom,
    Legend,
    _complete,
    assign,
    atoms_for_world,
    atoms_from_atoms2,
    atoms_from_gen_v2,
    atoms_from_meta,
    atoms_from_worlds_v2,
    declaration_header,
    validate_dependencies,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/assets/data'
EXPORTS = [*(('worlds_v2', path) for path in sorted((DATA / 'worlds_v2').glob('*.json'))
             if path.name != 'index.json'),
           *(('gen_v2', path) for path in sorted((DATA / 'gen_v2').glob('*.json'))
             if path.name != 'index.json' and
             not path.name.endswith(('.laws.json', '.bridges.json', '.templates.json'))),
           *(('meta', path) for path in sorted((DATA / 'meta').glob('*.json'))
             if path.name != 'index.json'),
           *(('atoms2', path) for path in sorted((DATA / 'atoms2').glob('*.json'))),
           *(('atoms2', ROOT / 'docs/assets/js/atoms2/data.js', world)
             for world in ('integer', 'robot'))]


def test_example_calls_do_not_declare_atoms_but_trace_frames_do():
    declared = [Atom('run', 'operation', 1, 'invented')]
    data = {'example': {'call': 'missing(1)', 'trace': {'name': 'loop', 'kind': 'operation',
                                                       'steps': 1}},
            'story': [{'decl': 'op run(x: Int) -> Int = missing(x) L1'}]}
    names = {atom.name for atom in _complete(declared, data)}
    assert 'run' in names
    assert 'missing' not in names
    assert 'loop' in names


def test_undeclared_dependencies_fail_instead_of_creating_helpers():
    with pytest.raises(ValueError, match="undeclared dependency 'missing'"):
        validate_dependencies(_complete([Atom('run', 'operation', 1, 'invented')],
                                        {'story': [{'depends_on': ['missing']}]}),
                              {'story': [{'depends_on': ['missing']}]})


def test_dependencies_validate_after_combining_world_sources():
    data = {'story': [{'depends_on': ['add', '?watch', 'Int']}]}
    atoms = _complete([Atom('watch', 'observation', 1, 'invented')], data)
    validate_dependencies([*atoms, Atom('add', 'operation', 0, 'given')], data)


def test_trace_frames_declare_real_atoms_but_not_local_loops():
    data = {'trace': [{'name': 'step', 'kind': 'operation', 'layer': 2, 'steps': 3},
                      {'name': 'loop', 'kind': 'operation', 'steps': 2}],
            'body': {'node': 'Rec', 'fn': 'loop'},
            'value': {'t': 'Hour', 'tag': 'H', 'f': [1]}}
    atoms = _complete([Atom('hour', 'object', 2, 'invented')], data)
    assert ('step', 'operation', 2) in {(atom.name, atom.kind, atom.layer) for atom in atoms}
    assert 'loop' not in {atom.name for atom in atoms}
    assert 'Hour' not in {atom.name for atom in atoms}


def test_combinator_parameter_is_local_to_its_body_not_other_trace_frames():
    data = {'story': [{'decl': 'comb @repeat[cf_step: Int -> Int](x: Int) -> Int = cf_step(x) L1'}],
            'example': {'trace': {'name': 'cf_step', 'kind': 'operation',
                                  'layer': 2, 'steps': 1}}}
    atoms = _complete([], data)
    assert ('cf_step', 'operation') in {(atom.name, atom.kind) for atom in atoms}


def test_observation_read_is_a_dependency_not_an_object_sort():
    from opulse.notation3.legend import _atom

    atom = _atom({'name': 'whole', 'kind': 'observation', 'spec': {'reads': 'value'}})
    assert atom.inputs == ()


def test_trace_frames_normalize_sigils_and_ignore_kernel_sorts():
    data = {'trace': [{'name': '?watch', 'kind': 'observation', 'steps': 1},
                      {'name': '__opulse_edge_x_0', 'kind': 'operation', 'steps': 1}],
            'value': {'t': '__opulse_edge_x_output', 'v': 1}}
    atoms = _complete([], data)
    assert [(atom.name, atom.kind) for atom in atoms] == [('watch', 'observation')]


def test_signature_declares_nested_and_lowercase_sorts():
    from opulse.notation3.legend import _export_references

    refs = _export_references({'story': [
        {'decl': 'obs ?cargo{s: Run} -> (Set<Text>,Set<Text>,Int) given'},
        {'decl': 'op eq(a: finite_value, b: finite_value) -> Bool given'},
    ]})
    assert {'Run', 'Set', 'Text', 'finite_value'} <= {
        atom.name for atom in refs if atom.kind == 'object'}


def _adapt(family, path, data):
    if family == 'worlds_v2':
        return atoms_from_worlds_v2(data)
    if family == 'meta':
        return atoms_from_meta(data)
    if family == 'atoms2':
        return atoms_from_atoms2(path.name if path.suffix == '.js' else path.stem, data)
    if family == 'gen_v2':
        data = copy.deepcopy(data)
        for extension, key in (('.laws', 'laws'), ('.bridges', 'bridges'),
                               ('.templates', 'templates')):
            sibling = path.with_name(path.stem + extension + '.json')
            if sibling.exists():
                data[key] = json.loads(sibling.read_text())[key]
        return atoms_from_gen_v2(data)
    raise AssertionError(family)


@pytest.fixture(scope='module', params=EXPORTS, ids=lambda item: item[1].name)
def published(request):
    family, path, *selected = request.param
    data = path.read_text() if path.suffix == '.js' else json.loads(path.read_text())
    adapted = _adapt(family, path, data)
    world, atoms = (selected[0], adapted[selected[0]]) if selected else adapted
    return family, path, data, world, atoms, assign(atoms)


def test_injective(published):
    _, _, _, _, _, legend = published
    names = [(entry.atom.name, entry.atom.kind) for entry in legend.entries]
    marks = [entry.ascii for entry in legend.entries]
    assert len(names) == len(set(names))
    assert len(marks) == len(set(marks))
    for entry in legend.entries:
        assert legend.by_name(entry.atom.name, entry.atom.kind) == entry
        assert legend.mark_expr(entry.atom.name, entry.atom.kind) == (
            n3.Expr('mg', (entry.mark, ())) if entry.mark else None)


def test_marks_roundtrip(published):
    _, _, _, _, _, legend = published
    for entry in legend.entries:
        if entry.mark is None:
            assert legend.binsign(entry.atom.name) == entry.binsign
            continue
        assert n3.parse_expr(entry.display) == n3.Expr('bare', (n3.Expr('mg', (entry.mark, ())),))
        assert n3.to_ascii(entry.display) == entry.ascii
        assert n3.to_display(entry.ascii) == entry.display


def test_signatures_roundtrip(published):
    _, _, _, _, _, legend = published
    for entry in legend.entries:
        if entry.signature is not None:
            display = n3.show(entry.signature)
            ascii_text = n3.show(entry.signature, ascii=True)
            assert n3.parse(display) == entry.signature
            assert n3.parse(ascii_text) == entry.signature
            assert n3.to_ascii(display) == ascii_text


def test_json_roundtrip(published):
    _, _, _, _, _, legend = published
    assert Legend.from_json(legend.to_json()).to_json() == legend.to_json()


def test_published_index_origins(published):
    _, _, _, _, _, legend = published
    indexed = set()
    for entry in legend.entries:
        mark = entry.mark
        if mark is None:
            continue
        if mark.index_kind == 'def':
            assert entry.atom.origin != 'given'
            assert str(mark.index_value)[0] in '123456789'
        elif mark.index_kind == 'given_num':
            assert entry.atom.origin == 'given'
            assert str(mark.index_value).startswith('0')
            assert mark.layer is None
            if entry.signature:
                assert not n3.show(entry.signature).startswith('⁰')
        if mark.index_kind in ('def', 'given_num'):
            key = (mark.family, str(mark.index_value))
            assert key not in indexed
            indexed.add(key)
    assert Legend.from_json(legend.to_json()).to_json() == legend.to_json()


def test_assignment_is_stable(published):
    family, path, data, _, atoms, legend = published
    assert assign(atoms).to_json() == legend.to_json()
    changed = copy.deepcopy(data)
    if isinstance(changed, dict):
        changed['unrelated_display_text'] = {'arbitrary': [1, 2, 3]}
        assert assign(_adapt(family, path, changed)[1]).to_json() == legend.to_json()


def test_integer_givens_and_layer_signature():
    atoms = atoms_for_world('integer@1')
    legend = assign(atoms)
    assert legend.binsign('add') == '+'
    assert legend.binsign('eq') == '=='
    assert legend.sort_mark('int') == n3.parse_expr('ℤ').args[0]
    assert legend.sort_mark('Bool') == n3.parse_expr('𝔹').args[0]
    invented = next(entry for entry in legend.entries if entry.atom.kind == 'operation'
                    and entry.atom.origin == 'invented' and entry.atom.arity == 2)
    # Binary operations take a suit, cycling by index (SPEC section 2); which suit depends on
    # how many defined operations precede it.
    assert invented.display[0] in '♦♠♥♣♢♤♡♧'
    assert invented.display[0] == '♦♠♥♣♢♤♡♧'[(invented.mark.index_value - 1) % 8]
    signature_header = n3.Mark(invented.atom.layer, invented.mark.family,
                               index_kind='def', index_value=invented.mark.index_value)
    assert n3.show(invented.signature).startswith(n3.show(signature_header))


def test_overflow_givens_never_reuse_defined_indices():
    atoms = [Atom(f'given{index}', 'operation', 0, 'given', 2)
             for index in range(40)]
    atoms.append(Atom('invented', 'operation', 1, 'invented', 2, ('int', 'int'), 'int'))
    legend = assign(atoms)
    overflow = [entry for entry in legend.entries if entry.atom.origin == 'given'
                and entry.mark and entry.mark.index_kind == 'given_num']
    assert len(overflow) == 16
    assert [entry.mark.index_value for entry in overflow] == ['0' + str(index) for index in range(1, 17)]
    assert all(entry.display.startswith('♦') and entry.mark.layer is None for entry in overflow)
    assert legend.by_name('invented').display == '♦₁'
    pairs = [(entry.mark.family, entry.mark.index_value) for entry in legend.entries
             if entry.mark and entry.mark.index_kind in ('def', 'given_num')]
    assert len(pairs) == len(set(pairs))


def test_thousand_invented_operations():
    atoms = (Atom(f'op{index}', 'operation', 1, 'invented', 2)
             for index in range(1, 1001))
    legend = assign(atoms)
    assert legend.by_name('op1000').display.endswith('₁₀₀₀')
    assert len({entry.display for entry in legend.entries}) == 1000


def test_object_forms_and_unknown_sort_order():
    legend = assign([Atom('Variant', 'object', 1, 'invented', forms=('left', 'right')),
                     Atom('Single', 'object', 1, 'invented', forms=('only',)),
                     Atom('use', 'operation', 1, 'invented', 2, ('Unknown', 'Another'), 'Unknown')])
    assert legend.single_form('Single')
    assert not legend.single_form('Variant')
    # A signature sort that no atom declares adds no legend entry, and the atom whose
    # signature names it shows no signature; the converter can still ask for its mark.
    assert {'Unknown', 'Another'}.isdisjoint(entry.atom.name for entry in legend.entries)
    assert legend.by_name('use', 'operation').signature is None
    assert legend.sort_mark('Unknown') == legend.mark_expr('Unknown', 'object')


def test_constructor_atoms_and_json_roundtrip():
    legend = assign([Atom('Tree', 'object', 2, 'invented', forms=('leaf', 'branch'),
                          form_fields=(('leaf', ('int',)), ('branch', ('Tree', 'Tree'))))])
    for tag, arity in (('leaf', 1), ('branch', 2)):
        entry = legend.by_name(f'Tree.{tag}', 'operation')
        assert entry.atom.form_of == 'Tree'
        assert entry.atom.layer == 2
        assert entry.atom.arity == arity
        assert entry.mark.index_kind == 'def'
    assert Legend.from_json(legend.to_json()).to_json() == legend.to_json()


def test_observed_forms_and_undeclared_dependencies():
    data = {'world': 'example', 'layer0': {'objects': [{'name': 'Tree'}]},
            'story': [{'name': 'use', 'kind': 'operation', 'layer': 1,
                       'depends_on': ['missing', 'missing']}],
            'examples': ['Tree.leaf<1>', {'t': 'Tree', 'tag': 'branch', 'f': []}]}
    with pytest.raises(ValueError, match="undeclared dependency 'missing'"):
        validate_dependencies(atoms_from_worlds_v2(data)[1], data)
    data['story'][0]['depends_on'] = ['Tree.leaf', 'Tree.branch']
    legend = assign(atoms_from_worlds_v2(data)[1])
    # Observed forms are sorted, so a serialized export and its in-memory build agree.
    assert legend.by_name('Tree', 'object').atom.forms == ('branch', 'leaf')
    assert legend.by_name('Tree.branch', 'operation').atom.form_of == 'Tree'
    assert not any(entry.atom.name == 'missing' for entry in legend.entries)
    assert Legend.from_json(legend.to_json()).to_json() == legend.to_json()


def test_integer_quot_is_a_template_atom():
    legend = assign(atoms_for_world('integer'))
    assert legend.by_name('Quot', 'template').mark.index_kind == 'def'


def test_names_repeated_between_kinds_are_disambiguated():
    legend = assign([Atom('same', 'object', 1, 'invented'),
                     Atom('same', 'operation', 1, 'invented', 1)])
    with pytest.raises(KeyError):
        legend.by_name('same')
    assert legend.by_name('same', 'object') != legend.by_name('same', 'operation')


def test_operations_keep_operation_glyphs_next_to_probes_and_objects():
    # The glyph family tells the kind: a layer-0 operation named like a probe or an object
    # keeps its own operation mark; a template-named sort is the template.
    atoms = [Atom('read', 'operation', 0, 'given', 1),
             Atom('read', 'observation', 0, 'given', 1),
             Atom('pair', 'object', 0, 'given', forms=('pair',)),
             Atom('pair', 'operation', 0, 'given', 2),
             Atom('Quot', 'template', 1, 'invented', produces='object'),
             Atom('Quot', 'object', 0, 'given')]
    legend = assign(_complete(atoms, {}))
    assert [(entry.atom.name, entry.atom.kind) for entry in legend.entries
            if entry.atom.name in ('read', 'pair', 'Quot')] == [
                ('read', 'operation'), ('read', 'observation'), ('pair', 'object'),
                ('pair', 'operation'), ('Quot', 'template')]
    assert legend.by_name('read', 'operation').mark.family not in ('hatR',)
    assert legend.by_name('read', 'observation').mark.family.startswith('hat')
    constructor = legend.by_name('pair', 'operation')
    assert not constructor.mark.family.startswith('bb')
    assert constructor.atom.note == 'constructor of ' + legend.by_name('pair', 'object').display
    assert legend.by_name('Quot', 'object') == legend.by_name('Quot', 'template')


def test_inferred_sort_named_like_constructor_is_not_a_second_atom():
    legend = assign([Atom('Tree', 'object', 1, 'invented', forms=('leaf', 'branch'),
                          valued_forms=('leaf', 'branch')),
                     Atom('Tree.leaf', 'object', 0, 'given')])
    assert [(entry.atom.name, entry.atom.kind) for entry in legend.entries
            if entry.atom.name == 'Tree.leaf'] == [('Tree.leaf', 'operation')]


def test_template_and_object_never_reuse_family_index():
    legend = assign([Atom('Alpha', 'object', 1, 'invented'),
                     Atom('Again', 'template', 1, 'invented', produces='object')])
    marks = [entry.mark for entry in legend.entries]
    assert len({(mark.family, mark.index_value) for mark in marks}) == 2


def test_sort_mark_assigns_unknown_sorts_on_first_lookup():
    legend = assign([Atom('int', 'object', 0, 'given')])
    first = legend.sort_mark('Mystery')
    second = legend.sort_mark('Second')
    assert first == legend.sort_mark('Mystery')
    assert first != second
    assert [entry.atom.name for entry in legend.entries[-2:]] == ['Mystery', 'Second']


def test_export_families_have_real_atoms():
    counts = Counter()
    for family, path, *selected in EXPORTS:
        data = path.read_text() if path.suffix == '.js' else json.loads(path.read_text())
        adapted = _adapt(family, path, data)
        counts[family] += len(adapted[selected[0]] if selected else adapted[1])
    assert counts['worlds_v2'] > 500
    assert counts['gen_v2'] > 500
    assert counts['meta'] > 50
    assert counts['atoms2'] > 20


def test_sign_givens_display_as_parenthesised_signs_and_round_trip_json():
    atoms = [Atom('add', 'operation', 0, 'given', 2, ('int', 'int'), 'int'),
             Atom('list', 'object', 0, 'given', forms=('nil', 'cons'))]
    legend = assign(atoms)
    rows = legend.to_json()
    assert rows[0]['display'] == rows[0]['mark'] == '(+)'
    assert rows[1]['forms'] == ['nil', 'cons']
    again = Legend.from_json(rows)
    assert again.binsign('add') == '+' and again.to_json() == rows


@pytest.mark.parametrize(('text', 'kind', 'name', 'inputs', 'output'), [
    ('op add(a: Int, b: Int) -> Int given', 'operation', 'add', ('Int', 'Int'), 'Int'),
    ('op apply(f: A -> B, xs: List<A>) -> B given', 'operation', 'apply',
     ('A -> B', 'List<A>'), 'B'),
    ('op next given', 'operation', 'next', (), None),
    ('op BeliefPair.b(arg0: BeliefPair) -> Rational given', 'operation',
     'BeliefPair.b', ('BeliefPair',), 'Rational'),
    ('obj Pair<A,B> = data given', 'object', 'Pair', (), None),
    ('obs ?cargo{s: Run} -> Bool given', 'observation', 'cargo', ('Run',), 'Bool'),
    ('comb @seq[f: A -> A](s: A) -> A given', 'combinator', 'seq', ('A',), 'A'),
    ('law #identity given', 'law', 'identity', (), None),
    ('bridge ~cast: A -> B given', 'bridge', 'cast', (), None),
    ('template op compiled[src: op] = build(src) L2', 'template', 'compiled', (), None),
])
def test_lenient_declaration_header(text, kind, name, inputs, output):
    header = declaration_header(text)
    assert (header['kind'], header['name'], header['inputs'], header['output']) == (
        kind, name, inputs, output)


def test_sort_alias_is_the_same_entry_as_sort_mark():
    legend = assign([Atom('Int', 'object', 0, 'given'),
                     Atom('Bool', 'object', 0, 'given'),
                     Atom('List', 'object', 0, 'given')])
    for alias in ('Int', 'int', 'integer', 'Bool', 'bool', 'List', 'List<Int>'):
        assert legend.mark_expr(legend.by_name(alias, 'object').atom.name, 'object') == (
            legend.sort_mark(alias))


def test_action_templates_keep_declared_layers():
    data = json.loads((DATA / 'worlds_v2/action.json').read_text())
    legend = assign(atoms_from_worlds_v2(data)[1])
    for name, kind, layer in [('Count', 'template', 1),
                              ('count_front_wall', 'observation', 2),
                              ('count_front_water', 'observation', 2)]:
        assert legend.by_name(name, kind).atom.layer == layer


def test_derived_combinators_do_not_declare_given_body_references():
    for world, names in [('automata', [('fold', 'combinator')]),
                         ('comb_obs', [('repeat', 'combinator'), ('search', 'combinator'),
                                       ('seq', 'combinator'), ('cargo', 'observation')])]:
        data = json.loads((DATA / 'worlds_v2' / (world + '.json')).read_text())
        legend = assign(atoms_from_worlds_v2(data)[1])
        for name, kind in names:
            assert legend.by_name(name, kind).atom.layer == 0
    # Names that occur only inside a given's body are not atoms of the world (review N2).
    for world, name in [('automata', 'left_fold'), ('molecules', 'fold_left')]:
        data = json.loads((DATA / 'worlds_v2' / (world + '.json')).read_text())
        legend = assign(atoms_from_worlds_v2(data)[1])
        assert not any(entry.atom.name == name for entry in legend.entries)


def test_meta_calls_not_in_headers_are_not_given_atoms():
    data = json.loads((DATA / 'meta/compiler.json').read_text())
    legend = assign(atoms_from_meta(data)[1])
    assert not any(entry.atom.name == 'pack_prog' for entry in legend.entries)


def test_atoms2_js_mode_declaration_resolves():
    text = (ROOT / 'docs/assets/js/atoms2/data.js').read_text()
    worlds = atoms_from_atoms2('data.js', text)
    assert assign(worlds['fold']).by_name('Tree', 'object').atom.layer == 1


def test_published_symbols_and_headers_resolve(published):
    family, path, data, _, _, legend = published
    if path.suffix == '.js':
        return
    if family == 'gen_v2':
        data = copy.deepcopy(data)
        for extension, key in (('.laws', 'laws'), ('.bridges', 'bridges'),
                               ('.templates', 'templates')):
            sibling = path.with_name(path.stem + extension + '.json')
            if sibling.exists():
                data[key] = json.loads(sibling.read_text())[key]
    found = Counter()
    sigils = {'@': 'combinator', '?': 'observation', '#': 'law', '~': 'bridge'}

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'design_decl' and isinstance(item, str):
                    # Design text names no atom: its header resolves only when a machine
                    # declaration of the world names the same atom (test_notation3_export).
                    found['design_headers'] += 1
                elif key in ('decl', 'ascii', 'declaration') and isinstance(item, str):
                    header = declaration_header(item)
                    if header:
                        kind = header['kind']
                        if (kind == 'operation' and (header['name'], kind) not in legend._names
                                and (header['name'], 'template') not in legend._names):
                            equivalent = [entry for entry in legend.entries
                                          if entry.atom.name == header['name'] and
                                          entry.atom.origin == 'given' and
                                          entry.atom.kind in ('observation', 'object')]
                            assert len(equivalent) == 1, (family, path.name, item)
                            kind = equivalent[0].atom.kind
                        assert legend.by_name(header['name'], kind)
                        for sort in (*header['inputs'], *((header['output'],) if header['output'] else ())):
                            for name in re.findall(r'\b[A-Z][A-Za-z_0-9]*\b', sort):
                                if len(name) > 1:
                                    assert legend.sort_mark(name) == legend.mark_expr(name, 'object')
                                    found['sorts'] += 1
                        found['headers'] += 1
                elif key == 'symbol' and isinstance(item, str):
                    for match in re.finditer(r'([@?#~])([A-Za-z_]\w*)|\b([A-Z]\w*)\s*<|'
                                             r'\b([a-z]\w*)\s*\(', item):
                        name = match[2] or match[3] or match[4]
                        kind = sigils[match[1]] if match[1] else (
                            'object' if match[3] else 'operation')
                        parent = re.search(r'([A-Z][A-Za-z_0-9]*)\.$', item[:match.start()])
                        if parent:
                            assert legend.by_name(parent[1], 'object')
                            found['symbols'] += 1
                            continue
                        try:
                            resolved_kind = kind
                            if (kind == 'operation' and (name, kind) not in legend._names
                                    and (name, 'template') not in legend._names):
                                equivalent = [entry for entry in legend.entries
                                              if entry.atom.name == name and entry.atom.origin == 'given'
                                              and entry.atom.kind in ('observation', 'object')]
                                if len(equivalent) == 1:
                                    resolved_kind = equivalent[0].atom.kind
                            assert legend.by_name(name, resolved_kind), (family, path.name, name, kind)
                        except KeyError:
                            published = (data.get('notation3', {}).get('worlds', {}).get(
                                data.get('world'), {}).get('formulas', {}))
                            assert item not in published, (family, path.name, name, kind)
                            found['design_symbols'] += 1
                        else:
                            found['symbols'] += 1
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    if family == 'worlds_v2' and path.name != 'index.json':
        assert found['headers'] + found['symbols'] > 0


def test_operation_parameters_given_as_records_are_local_names():
    from opulse.notation3.legend import atoms_from_worlds_v2
    export = {'world': 'w', 'layer0': {'combinators': {'library': [
        {'name': 'twice', 'op_params': [{'name': 'f'}], 'params': [{'name': 'x', 'sort': 'int'}],
         'output': {'sort': 'int'}, 'decl': 'comb @twice[f: A -> A](x: A) -> A = f(f(x)) given'}]}}}
    world, atoms = atoms_from_worlds_v2(export)
    assert world == 'w' and 'f' not in {atom.name for atom in atoms}


def test_declaration_headers_do_not_declare_body_dependencies():
    from opulse.notation3.legend import atoms_from_atoms2
    data = {'world': 'grammar', 'declarations': [
        {'declaration': 'op split(w: Word) -> List = depth_zero_binary_positions(w) L1'},
        {'declaration': 'obj Frac = Quot[Pair<Int, Int>, reduce] L2'},
        {'declaration': 'template obj Quot[T: obj, canon: op] = refine T canon(canon) L1'},
    ]}
    _, atoms = atoms_from_atoms2('grammar.json', data)
    legend = assign(atoms)
    for name, kind, layer in (('split', 'operation', 1),
                              ('Frac', 'object', 2), ('Quot', 'template', 1)):
        assert legend.by_name(name, kind).atom.layer == layer
    assert not any(entry.atom.name == 'depth_zero_binary_positions'
                   for entry in legend.entries)


def test_combinator_operation_arity_is_distinct_from_value_arity():
    from opulse.notation3.convert import context_for
    _, atoms = atoms_from_worlds_v2({'world': 'grammar', 'layer0': {'combinators': {
        'library': [{'name': 'chart', 'kind': 'combinator',
                     'decl': 'comb @chart[one, multiply, identity, combine_count, zero](w: Word) -> Word = w given'}]}}})
    chart = assign(atoms).by_name('chart', 'combinator').atom
    assert chart.arity == 1
    assert chart.op_arity == 5
    assert context_for(assign(atoms))['op_arity']['chart'] == 5


def test_published_chart_call_has_five_operation_parameters():
    from opulse.atoms import notation
    from opulse.notation3.convert import context_for
    legend = assign(atoms_for_world('grammar'))
    context = context_for(legend)
    assert context['op_arity']['chart'] == 5
    notation.parse_expr('@chart[one, multiply, identity, combine_count, zero](w)', context)


def test_combinator_call_arguments_need_declared_operations():
    data = {'world': 'grammar', 'layer0': {}, 'story': [
        {'decl': 'comb @chart[leaf: A -> A](w: A) -> A = leaf(w) L1'},
        {'decl': 'obs ?parse_count{w} = @chart[one](w) L2'}]}
    _, atoms = atoms_from_worlds_v2(data)
    assert not any(atom.name == 'one' for atom in atoms)
    assert 'leaf' not in {atom.name for atom in atoms if atom.kind == 'operation'}


def test_parseable_declaration_layer_overrides_story_metadata():
    data = {'world': 'w', 'layer0': {}, 'story': [
        {'name': 'split', 'kind': 'operation', 'layer': 5,
         'decl': 'op split(w: Word) -> List = depth_zero_binary_positions(w) L1'}]}
    _, atoms = atoms_from_worlds_v2(data)
    assert assign(atoms).by_name('split', 'operation').atom.layer == 1


def test_parseable_design_declaration_layer_overrides_story_metadata():
    data = {'world': 'w', 'layer0': {}, 'story': [
        {'name': 'open_day', 'kind': 'observation', 'layer': 6,
         'design_decl': 'obs ?open_day{d: Date} -> Bool = ?workday{d} L11'}]}
    _, atoms = atoms_from_worlds_v2(data)
    assert assign(atoms).by_name('open_day', 'observation').atom.layer == 11


def test_story_rows_use_the_dependency_layer_not_the_display_row():
    from opulse.notation3.legend import atoms_from_worlds_v2
    export = {'world': 'w', 'layer0': {}, 'story': [
        {'name': 'hour', 'kind': 'object', 'layer': 20, 'def_layer': 3}]}
    _, atoms = atoms_from_worlds_v2(export)
    assert next(atom for atom in atoms if atom.name == 'hour').layer == 3


def test_dotted_trace_frames_are_object_machinery_not_atoms():
    data = json.loads((DATA / 'worlds_v2' / 'integer.json').read_text())
    legend = assign(atoms_from_worlds_v2(data)[1])
    calls, frames = set(), set()

    def walk(value):
        if isinstance(value, dict):
            if value.get('node') == 'Call' and '.' in str(value.get('fn')):
                calls.add(value['fn'])
            if isinstance(value.get('name'), str) and '.' in value['name'] and 'steps' in value:
                frames.add(value['name'])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    dotted = {entry.atom.name for entry in legend.entries
              if '.' in entry.atom.name and not entry.atom.form_of}
    # Frames that only run an object's machinery (cf._pack, hour.make) are not atoms; an
    # object operation that a machine definition calls (cf.base, an unwrap) is one.
    assert frames - calls and not dotted & (frames - calls)
    assert dotted == {name for name in calls if not name.endswith('.make')}
