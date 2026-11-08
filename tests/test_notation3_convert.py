"""Machine-to-v3 conversion keeps AST shape in both spellings."""

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from opulse import notation3 as v3
from opulse.atoms import nodes as n
from opulse.atoms import notation
from opulse.atoms.kernel import FnRef
from opulse.atoms.values import Bottom, Card
from opulse.notation3.convert import (
    ConversionError,
    UndeclaredAtom,
    _Converter,
    context_for,
    convert_definition,
    convert_outcome,
    convert_prose,
    convert_text,
    convert_value,
    is_design_text,
)
from opulse.notation3.legend import (
    Atom,
    _atom,
    _complete,
    _export_references,
    _layer0,
    _template_atoms,
    assign,
    atoms_from_atoms2,
    atoms_from_gen_v2,
    atoms_from_meta,
    atoms_from_worlds_v2,
)
from opulse.worlds_v2.export_util import parseable_declaration, parseable_expression


def assert_roundtrip(ast):
    stmt = ast if isinstance(ast, v3.Stmt) else v3.Stmt('expr', (ast,))
    assert v3.parse(v3.show(stmt)) == stmt
    assert v3.parse(v3.show(stmt, ascii=True)) == stmt
    assert v3.check(stmt) == []


@pytest.fixture
def legend():
    return assign([
        Atom('add', 'operation', 0, 'given', 2),
        Atom('mul', 'operation', 0, 'given', 2),
        Atom('eq', 'operation', 0, 'given', 2),
        Atom('succ', 'operation', 0, 'given', 1),
        Atom('f', 'operation', 1, 'invented', 2),
        Atom('g', 'operation', 1, 'invented', 2),
        Atom('double', 'operation', 1, 'invented', 1),
        Atom('R', 'object', 1, 'invented', forms=('nil', 'cons')),
        Atom('C', 'object', 1, 'invented', forms=('C',)),
        Atom('q', 'observation', 1, 'invented'),
        Atom('wall', 'observation', 0, 'given'),
        Atom('water', 'observation', 0, 'given'),
        Atom('rule', 'law', 1, 'invented'),
        Atom('translate', 'bridge', 1, 'invented'),
        Atom('t', 'combinator', 1, 'invented', 1, op_arity=1),
        Atom('Zn', 'template', 2, 'invented', produces='object'),
    ])


def test_infix_precedence(legend):
    node = n.Call('mul', (n.Call('add', (n.Var('a'), n.Var('b'))), n.Var('c')))
    result = _Converter(legend).node(node)
    assert v3.show(result) == '(a + b) * c'
    assert_roundtrip(result)


def test_infix_right_nested(legend):
    node = n.Call('add', (n.Var('a'), n.Call('mul', (n.Var('b'), n.Var('c')))))
    result = _Converter(legend).node(node)
    assert v3.show(result) == 'a + b * c'
    assert_roundtrip(result)


def test_nested_mark_requires_group(legend):
    result = _Converter(legend).node(n.Call('f', (n.Call('g', (n.Var('a'), n.Var('b'))), n.Var('c'))))
    assert v3.show(result) == '(a ♠₂ b) ♦₁ c'
    assert_roundtrip(result)


def test_keyword_variable_renamed(legend):
    result = _Converter(legend).node(n.Let('in', n.Lit(1), n.Var('in')))
    assert v3.show(result) == 'let in_ = 1 in in_'
    assert_roundtrip(result)


def test_negative_number_and_bottom(legend):
    for value in (-5, Bottom('reason'), (-1, 2)):
        assert_roundtrip(convert_value(value, legend))


def test_card_tag_and_single_form(legend):
    many = convert_value(Card('R', 'cons', (1, 2)), legend)
    single = convert_value(Card('C', 'C', (1,)), legend)
    assert v3.show(many) == v3.show(legend.constructor_mark('R', 'cons')) + '(1, 2)'
    assert v3.show(single) == '𝔻₂(1)'
    assert_roundtrip(many)
    assert_roundtrip(single)


def test_single_form_with_distinct_tag_uses_sort_mark():
    world = assign([Atom('Hour', 'object', 1, 'invented', forms=('hour',))])
    assert v3.show(convert_value(Card('Hour', 'hour', (3,)), world)) == (
        world.by_name('Hour', 'object').display + '(3)')


def test_declared_constructor_fields_use_names():
    world = assign([Atom('Tree', 'object', 1, 'invented', forms=('leaf', 'branch'),
                         form_fields=(('leaf', ('value',)), ('branch', ('left', 'right'))))])
    result = convert_value(Card('Tree', 'leaf', (3,)), world)
    assert v3.show(result) == v3.show(world.constructor_mark('Tree', 'leaf')) + '(value: 3)'
    assert_roundtrip(result)


def test_capitalized_card_tag_is_unchanged():
    # A capitalised form that carries fields is a constructor; a nullary one is a constant.
    world = assign([Atom('E', 'object', 1, 'invented', forms=('Leaf', 'Branch'),
                         valued_forms=('Leaf', 'Branch'))])
    assert v3.show(convert_value(Card('E', 'Nil', ()), world)) == 'Nil'
    value = convert_value(Card('E', 'Leaf', (1,)), world)
    assert v3.show(value) == v3.show(world.constructor_mark('E', 'Leaf')) + '(1)'
    assert_roundtrip(value)


def test_case_flatten(legend):
    node = n.Case(((n.Test(n.Var('a')), n.Lit(1)),),
                  n.Case(((n.Test(n.Var('b')), n.Lit(2)),), n.Lit(3)))
    result = _Converter(legend).node(node)
    assert v3.show(result) == '{ 1, if a; 2, if b; 3, else }'
    assert_roundtrip(result)


def test_memo_rec(legend):
    node = n.Rec('loop', ('x',), n.Var('x'), (n.Lit(1),), 'fuel', True)
    result = _Converter(legend).node(node)
    assert v3.show(result) == 'memo rec ♦ᵣ(x) = x ⊢ fuel in ♦ᵣ(1)'
    assert_roundtrip(result)


def test_program_label_renaming(legend):
    program = n.Blocks((('x', n.Lit(0)),), 'start', (('start', n.Block((), n.Halt(n.Var('x')))),))
    result = _Converter(legend).node(program)
    assert v3.show(result) == 'prog (x = 0) entry L0 { L0: halt x }'
    assert_roundtrip(result)


def test_operation_definition(legend):
    defn = notation.parse_definition('op f(a: Int, b: Int) -> Int = add(a, b) L1')
    signature, formula = convert_definition(defn, legend)
    assert v3.show(formula) == 'a ♦₁ b = { a + b }'
    assert v3.show(signature) == '¹♦₁ : ℤ × ℤ → ℤ'
    assert_roundtrip(signature)
    assert_roundtrip(formula)


def test_c1_given_postfix(legend):
    defn = notation.parse_definition('op f(a: Int, b: Int) -> Int = mul(succ(a), b) L1')
    _, formula = convert_definition(defn, legend)
    assert v3.show(formula) == 'a ♦₁ b = { (a @) * b }'
    assert_roundtrip(formula)


def test_bin_sign_given_header(legend):
    defn = notation.parse_definition('op add(a: Int, b: Int) -> Int = 0 given')
    signature, formula = convert_definition(defn, legend)
    assert v3.show(signature) == '(+) : ℤ × ℤ → ℤ'
    assert v3.show(formula) == 'a + b = { 0 }'
    assert_roundtrip(signature)
    assert_roundtrip(formula)


def test_c8_combinator_slot(legend):
    defn = notation.parse_definition('comb @t[f: A -> A](x: A) -> A = f(f(x)) L1')
    _, formula = convert_definition(defn, legend)
    assert v3.show(formula) == 'Γ₁[♦ₐ] x = { ♦ₐ (♦ₐ x) }'
    assert_roundtrip(formula)


def test_c9_combinator_application(legend):
    result = _Converter(legend, machine_text='@t[double](3)').node(
        n.Call('t', (n.Lit(FnRef('double')), n.Lit(3))))
    assert v3.show(result) == 'Γ₁[▽₃] 3'
    assert_roundtrip(result)


def test_operation_and_combinator_share_name():
    legend = assign([Atom('pair', 'operation', 0, 'given', 2),
                     Atom('pair', 'combinator', 1, 'invented', 1),
                     Atom('step', 'operation', 0, 'given', 1)])
    ctx = context_for(legend)
    assert ctx['kinds']['pair'] == 'operation'
    combinator = convert_text('@pair[step](3)', legend, ctx)
    assert legend.by_name('pair', 'combinator').display in combinator['display']
    # An unsigiled call is the operation; the combinator always carries its sigil.
    operation = convert_text('pair(1, 2)', legend, ctx)
    assert legend.by_name('pair', 'operation').display in operation['display']
    assert legend.by_name('pair', 'combinator').display not in operation['display']
    call = n.Call('pair', (n.Lit(FnRef('step')), n.Lit(3)))
    assert v3.show(_Converter(legend, machine_text='@pair[step](3)').node(call)) == combinator['display']
    for result in (operation, combinator):
        assert_roundtrip(v3.parse(result['display']))


def test_c3_self_recursion(legend):
    from dataclasses import replace

    defn = notation.parse_definition('op g(a: Int, b: Int) -> Int = 0 L1')
    recursive = n.Rec('r', ('a', 'b'),
                      n.Case(((n.Test(n.Call('eq', (n.Var('b'), n.Lit(0)))), n.Lit(0)),),
                             n.Call('add', (n.Var('a'), n.Call('r', (n.Var('a'),
                                n.Call('add', (n.Var('b'), n.Lit(-1)))))))),
                      (n.Var('a'), n.Var('b')), n.Var('b'))
    defn = replace(defn, body=recursive)
    _, formula = convert_definition(defn, legend)
    assert v3.show(formula).startswith('a ♠₂ b = {')
    assert v3.show(formula).endswith('⊢ ↓ b')
    assert_roundtrip(formula)


def test_c11_observation_boolean(legend):
    statement = n.Case(((n.And(n.Not(n.Test(n.Call('wall', (n.Var('s'),)))),
                                 n.Not(n.Test(n.Call('water', (n.Var('s'),))))), n.Lit(True)),),
                       n.Lit(False))
    defn = notation.parse_definition('obs ?q{s} = true L1')
    from dataclasses import replace

    defn = replace(defn, body=statement)
    _, formula = convert_definition(defn, legend, machine_text='obs ?q{s} = not ?wall{s} and not ?water{s} L1')
    assert v3.show(formula) == 'Â₁⟨s⟩ = { not Â⟨s⟩ and not Ĉ⟨s⟩ }'
    assert_roundtrip(formula)


def test_machine_sigils_select_declared_kind(legend):
    assert legend.by_name('wall', 'observation').display in convert_text('?wall{s}', legend)['display']
    with pytest.raises(UndeclaredAtom, match="undeclared observation atom 'succ'"):
        convert_text('?succ{s}', legend)


def test_later_strategy_recovers_from_undeclared_first_parse(legend):
    assert convert_text('Ok(18)', legend)['display'] == '18'
    assert convert_text('?wall{front_wall,front_water}', legend)['display'] == (
        legend.by_name('wall', 'observation').display)


def test_bare_prose_and_context_free_undeclared_call_are_not_formulas(legend):
    with pytest.raises(ConversionError):
        convert_text('given', legend)
    with pytest.raises(ConversionError):
        convert_text('cut_certificate(Roads.graph<1>)', legend)


def test_given_operation_and_probe_keep_their_own_marks():
    world = assign([Atom('read', 'observation', 0, 'given', 1),
                    Atom('read', 'operation', 0, 'given', 1)])
    observation = world.by_name('read', 'observation').display
    operation = world.by_name('read', 'operation').display
    assert observation != operation
    assert convert_text('?read{s}', world)['display'] == observation + '⟨s⟩'
    # An unsigiled call names the operation when one is declared.
    assert convert_text('read(s)', world)['display'] in (operation + ' s', 's ' + operation)


def test_unsigiled_calls_and_function_references_use_declared_kind():
    world = assign([Atom('look', 'observation', 0, 'given', 1),
                    Atom('plan', 'combinator', 1, 'invented', op_arity=1),
                    Atom('step', 'operation', 0, 'given', 1)])
    assert convert_text('look(1)', world)['display'] == world.by_name('look', 'observation').display + '⟨1⟩'
    plan = convert_text('plan(step, 1)', world)
    assert world.by_name('plan', 'combinator').display in plan['display']
    assert world.by_name('step', 'operation').display in plan['display']
    assert convert_value(FnRef('look'), world) == v3.Expr('bare', (
        world.mark_expr('look', 'observation'),))


def test_object_constructor_operation_keeps_an_operation_mark():
    from opulse.notation3.legend import _complete

    world = assign(_complete([Atom('read', 'operation', 0, 'given', 1, ('Int',), 'Int'),
                              Atom('read', 'observation', 0, 'given', 1, ('Bool',), 'Bool'),
                              Atom('pair', 'object', 0, 'given', forms=('pair',)),
                              Atom('pair', 'operation', 0, 'given', 2)], {}))
    constructor = world.by_name('pair', 'operation').display
    assert convert_text('pair(1, 2)', world)['display'] == '1 ' + constructor + ' 2'
    result = convert_text('op read(x: Int) -> Int given', world)
    assert result['display'] == world.by_name('read', 'operation').display
    assert result['signature']['display'] == v3.show(world.by_name('read', 'operation').signature)


def test_record_fields_in_given_signature_are_not_object_sorts():
    world = assign([Atom('Record', 'object', 0, 'given'),
                    Atom('stats', 'observation', 0, 'given')])
    result = convert_text('obs ?stats{s: Record} -> Record<scans,moves> given', world)
    assert result['signature'] is not None
    assert all(entry.atom.name not in ('scans', 'moves') for entry in world.entries)


def test_declared_nullary_constant_uses_its_object_mark():
    world = assign([Atom('A0', 'object', 0, 'given'),
                    Atom('B0', 'object', 0, 'given')])
    for name in ('A0', 'B0'):
        assert convert_text(name, world)['display'] == world.by_name(name, 'object').display
    assert v3.show(convert_value(Card('E', 'E'), world)) == 'E'


@pytest.mark.parametrize('world,text,expected', [
    ('calendar', 'obs ?workday{s} = lt(?weekday{s}, 5) L1', 'Â₁⟨s⟩ = { Â⟨s⟩ < 5 }'),
    ('action', 'obs ?front_clear{b: Bot} -> bool = not(?front_wall{b}) and not(?front_water{b}) L1',
     'Â₁⟨b⟩ = { not Â⟨b⟩ and not Ĉ⟨b⟩ }'),
    ('shadows', '@plan[front,diag,anti]', 'Λ₄'),
    ('integer', 'obs ?seen_value{value} = ?value{value} L1', 'Ĉ₂⟨value⟩ = { Â⟨value⟩ }'),
])
def test_review_cases_use_machine_kind(world, text, expected):
    data = json.loads((Path('docs/assets/data/worlds_v2') / (world + '.json')).read_text())
    atoms = [*_layer0(data['layer0']), *_layer0(data['decl']),
             *(_atom(item) for item in data['story']), *_template_atoms(data),
             *_export_references(data)]
    source = copy.deepcopy(data)

    def without_dependencies(value):
        if isinstance(value, dict):
            value.pop('depends_on', None)
            value.pop('dependencies', None)
            for child in value.values():
                without_dependencies(child)
        elif isinstance(value, list):
            for child in value:
                without_dependencies(child)

    without_dependencies(source)
    atoms = _complete(atoms, source)
    if world == 'integer':
        first = json.loads(Path('docs/assets/data/atoms2/first_tower.json').read_text())
        without_dependencies(first)
        atoms.extend(_complete([_atom(item) for item in first['cards']], first))
    world_legend = assign({(atom.name, atom.kind): atom for atom in atoms}.values())
    assert convert_text(text, world_legend)['display'] == expected
    if world == 'shadows':
        assert not any(atom.name == 'plan' and atom.kind == 'operation' and atom.origin == 'given'
                       for atom in atoms)


def test_audit_uses_observation_marks_for_log_and_orders():
    data = json.loads(Path('docs/assets/data/worlds_v2/comb_obs.json').read_text())
    atoms = [*_layer0(data['layer0']), *_layer0(data['decl']),
             *(_atom(item) for item in data['story']), *_export_references(data)]
    world = assign({(atom.name, atom.kind): atom for atom in atoms}.values())
    declaration = next(item['decl'] for item in data['story'] if item['name'] == 'audit')
    display = convert_text(declaration, world)['display']
    for name in ('log', 'orders'):
        assert world.by_name(name, 'observation').display + '⟨s⟩' in display


def test_law_definition(legend):
    defn = notation.parse_definition('law #rule: eq(g(a, b), g(b, a)) for a: Int, b: Int L1')
    signature, formula = convert_definition(defn, legend)
    assert signature is None
    assert v3.show(formula) == '≡₁ : ∀ a, b ∈ ℤ. a ♠₂ b == b ♠₂ a'
    assert_roundtrip(formula)


def test_bridge_signature_and_formula(legend):
    defn = notation.parse_definition('bridge ~translate: R -> C = f(x) L1')
    signature, formula = convert_definition(defn, legend)
    assert v3.show(signature) == '↝₁ : 𝔸₁ → 𝔻₂'
    assert v3.show(formula) == '↝₁(x) = { ♦₁ x }'
    assert_roundtrip(signature)
    assert_roundtrip(formula)


def test_object_refinement(legend):
    defn = notation.parse_definition('obj R = <n: int> where eq(n, 0) L1')
    _, formula = convert_definition(defn, legend)
    assert v3.show(formula) == '𝔸₁ = { (n) ∈ ℤ ∣ n == 0 }'
    assert_roundtrip(formula)


def test_object_constant(legend):
    defn = notation.parse_definition('obj C = (2) L1')
    _, formula = convert_definition(defn, legend)
    assert v3.show(formula) == '𝔻₂ = (2)'
    assert_roundtrip(formula)


def test_symbol_shape(legend):
    with pytest.raises(ConversionError, match="undeclared combinator atom 'f'"):
        convert_text('@f[argument]', legend)
    assert convert_text('@t[double]', legend)['display'] == 'Γ₁'
    assert convert_text('Int<...>', legend)['display'] == 'ℤ'


def test_given_header_shapes():
    names = [('first', 'operation'), ('maximum', 'operation'), ('List', 'object'),
             ('Cell', 'object'), ('Run', 'object'), ('Int', 'object'),
             ('pos', 'observation'), ('seq', 'combinator'), ('search', 'combinator'),
             ('Map', 'object'), ('Bool', 'object')]
    legend = assign([Atom(name, kind, 0, 'given') for name, kind in names])
    cases = [
        'op first given', 'op maximum(...) given', 'obj List given',
        'obs ?pos{s: Run} -> Cell given',
        'comb @seq[f: Run->Run, g: Run->Run](s: Run) -> Run = g(f(s)) given',
        ('comb @search[neighbors: Cell->List<Cell>, valid: Cell->Bool]'
         '(start: Cell, target: Cell, known: Map<Cell,Bool>) -> List<Cell> given'),
        'op maximum(x: Int, y: Int) -> List<Cell> given',
        'obs ?pos{s: Run} -> (Cell,Int) given',
    ]
    for text in cases:
        result = convert_text(text, legend)
        assert_roundtrip(v3.parse(result['display']))
        if result['signature']:
            assert_roundtrip(v3.parse(result['signature']['display']))
    assert '𝔸[' in convert_text(cases[-2], legend)['signature']['display']
    assert '×' in convert_text(cases[-1], legend)['signature']['display']
    # A given declaration shows its head only; its body is never converted (review N2).
    assert convert_text(cases[4], legend)['display'] == legend.by_name('seq', 'combinator').display


def test_display_text_classification_and_symbol_names(legend):
    for text in ('op trace(xs: List<Int>) -> List<Int> = for each target position i',
                 'Lex.make(List<Pair<Word<\'b\'>, 3>)',
                 'comb @pair[f,g](n)->Circuit<n,outputs(f)+outputs(g)> = parallel_copy_inputs(f,g) | L2'):
        assert is_design_text(text, context_for(legend))
    assert not is_design_text('op first given', context_for(legend))
    assert not is_design_text('add(1, 2)', context_for(legend))
    assert convert_text('R<...>', legend)['display'] == legend.by_name('R').display
    assert convert_text('?q', legend)['display'] == legend.by_name('q').display
    with pytest.raises(ConversionError, match="symbol 'missing'"):
        convert_text('missing(int,int)', legend)


def test_symbol_shapes_use_only_declared_names():
    legend = assign([Atom('Ports', 'object', 0, 'given'),
                     Atom('map_components', 'combinator', 0, 'given'),
                     Atom('read', 'observation', 0, 'given'),
                     Atom('event', 'operation', 0, 'given'),
                     Atom('op', 'operation', 0, 'given')])
    for text, name in [('Ports<...>', 'Ports'), ('@map_components[f](...)', 'map_components'),
                       ('?read', 'read'), ('event(int,int)', 'event'), ('op(...)', 'op')]:
        assert convert_text(text, legend)['display'] == legend.by_name(name).display


def test_worlds_v2_published_ascii():
    root = Path(__file__).resolve().parents[1] / 'docs/assets/data/worlds_v2'
    failures = []
    for path in sorted(root.glob('*.json')):
        data = json.loads(path.read_text())
        for unit, atoms in _corpus_units(path, data):
            texts = _export_formulas(unit)
            if not atoms or not any(field == 'ascii' for field, _ in texts):
                continue
            published = unit.get('notation3', {}).get('worlds', {}).get(unit.get('world'), {})
            legend = assign(atoms)
            ctx = context_for(legend)
            for field, text in texts:
                if field != 'ascii' or text not in published.get('formulas', {}):
                    continue
                assert parseable_declaration(text, None) or parseable_expression(text)
                try:
                    result = convert_text(text, legend, ctx)
                    assert v3.check(v3.parse(result['display'])) == []
                    assert result == published['formulas'][text]
                except (ConversionError, v3.NotationError) as exc:
                    failures.append((path.name, text[:100], str(exc)[-120:]))
    assert not failures, failures


def test_dotted_tag_call(legend):
    assert convert_text('R.cons(1, 2)', legend)['display'] == v3.show(legend.constructor_mark('R', 'cons')) + '(1, 2)'
    assert convert_text('R.nil()', legend)['display'] == v3.show(legend.constructor_mark('R', 'nil')) + '()'


def test_structured_record_and_observation(legend):
    result = convert_text('?q{R<pos=1, flag=false>}', legend)
    assert result['display'] == 'Â₁⟨𝔸₁(pos: 1, flag: ⊥)⟩'
    assert v3.to_ascii(result['display']) == result['ascii']


def test_generated_variant_declaration(legend):
    result = convert_text('obj R = <nil() | cons(head: int, tail: R)> L1', legend)
    assert result['display'] == ('𝔸₁ = ' + v3.show(legend.constructor_mark('R', 'nil')) +
                                 '() + ' + v3.show(legend.constructor_mark('R', 'cons')) +
                                 '(head: ℤ, tail: 𝔸₁)')
    assert v3.to_ascii(result['display']) == result['ascii']


def test_prose_without_atom_stays_plain(legend):
    assert convert_prose('This `word` is not an atom.', legend) is None


def test_outcomes(legend):
    for text, display in [('Ok(12)', '12'), ('Bottom("reason")', 'fail("reason")'),
                          ('Unknown(fuel)', 'unknown("fuel")')]:
        expr = convert_outcome(text, legend)
        assert v3.show(expr) == display
        assert_roundtrip(expr)


def test_convert_text(legend):
    formula = convert_text('add(1, 2)', legend)
    assert formula['display'] == '1 + 2'
    assert formula['signature'] is None


def test_machine_context_from_legend(legend):
    ctx = context_for(legend)
    assert ctx['kinds']['t'] == 'combinator'
    assert ctx['op_arity']['t'] == 1
    assert ctx['infix'] == {'add': '+', 'mul': '*'}
    assert notation.parse_expr('@t[double](3)', ctx) == n.Call(
        't', (n.Lit(FnRef('double')), n.Lit(3)))
    assert convert_text('@t[double](3)', legend)['display'] == 'Γ₁[▽₃] 3'


def test_convert_prose(legend):
    assert convert_prose('Use `add(1, 2)` and @missing.', legend) == [
        ['t', 'Use '], ['f', '1 + 2', '1 + 2'], ['t', ' and @missing.']]


def test_unknown_name_fails(legend):
    with pytest.raises(ConversionError):
        convert_text('missing(1)', legend)


def test_unexpressible_template_fails(legend):
    text = 'template obj Zn[n: int] = refine world canon(make_zn) L2'
    with pytest.raises(ConversionError, match='template pattern cannot be parsed'):
        convert_definition(notation.parse_definition(text), legend)


def _export_formulas(data):
    keys = {'decl', 'ascii', 'design_decl', 'call', 'declaration',
            'expression', 'symbol', 'outcome'}

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'notation3':
                    continue
                if isinstance(item, str) and (key in keys or key == 'text' and
                                              any(k in value for k in ('call', 'outcome', 'result'))):
                    if key == 'design_decl' and not (parseable_declaration(item, None) or
                            re.match(r'^(?:op|obj|comb|obs|law|bridge|template)\s', item)):
                        continue
                    if key == 'text' and not (parseable_expression(item) or
                            re.match(r'^[A-Za-z_@?~#][\w.]*[({<\[]', item)):
                        continue
                    yield key, item
                else:
                    yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)

    return list(dict.fromkeys(walk(data)))


def _export_atoms(path, data):
    family = path.parent.name
    if family == 'worlds_v2' and 'layer0' in data:
        return atoms_from_worlds_v2(data)[1]
    if family == 'gen_v2' and any(key in data for key in ('entries', 'story', 'laws', 'bridges', 'templates')):
        if not data.get('world'):
            data = {**data, 'world': path.stem.split('.')[0]}
        return atoms_from_gen_v2(data)[1]
    if family == 'meta' and data.get('world'):
        return atoms_from_meta(data)[1]
    if family == 'atoms2' or path.suffix == '.js':
        result = atoms_from_atoms2(path.name, data)
        if isinstance(result, dict):
            return [atom for atoms in result.values() for atom in atoms]
        return result[1]
    return []


def _corpus_units(path, data):
    if path.stem == 'index' and path.parent.name in ('worlds_v2', 'meta'):
        for record in data['worlds']:
            source = path.with_name(record['file'])
            if source.exists():
                yield record, _export_atoms(source, json.loads(source.read_text()))
    elif path.name == 'grammar_core.json':
        rows = data.get('rows', {})
        atoms = [Atom(row['name'], kind, int(row.get('layer', 1)), 'invented')
                 for kind, entry in rows.items()
                 for row in (entry if isinstance(entry, list) else [entry])
                 if isinstance(row, dict) and row.get('name') and
                 kind in ('object', 'operation', 'combinator', 'observation', 'law', 'bridge')]
        yield data, atoms
    elif path.suffix == '.js':
        for source in (data, data.get('modes', {})):
            for identifier, record in source.get('derivations', {}).items():
                world = record['world']
                run = source.get('runs', {}).get(identifier, {})
                atoms = atoms_from_atoms2('data.js', {
                    'derivations': {identifier: record},
                    'modes': {'derivations': {world: record}, 'runs': {world: run}},
                })[world]
                yield {'derivation': record, 'run': run}, atoms
    else:
        yield data, _export_atoms(path, data)


def _referenced_atoms(texts, atoms):
    """Include references in source bodies omitted by partial export adapters."""
    names = {(atom.name, atom.kind) for atom in atoms}
    extra = []

    def add(name, kind, arity=None):
        if name in ('int', 'bool', 'Int', 'Bool') or (name, kind) in names or (
            kind == 'operation' and any(existing == name for existing, _ in names)
        ):
            return
        names.add((name, kind))
        extra.append(Atom(name, kind, 0, 'given', arity))

    def value(item):
        if isinstance(item, Card):
            add(item.sort, 'object')
            for field in item.fields:
                value(field)
        elif isinstance(item, FnRef):
            add(item.name, 'operation')
        elif isinstance(item, tuple):
            for field in item:
                value(field)

    def node(item):
        if isinstance(item, n.Call):
            add(item.fn, 'operation', len(item.args))
        if isinstance(item, n.Lit):
            value(item.value)
        for child in n.children(item):
            node(child)

    ctx = context_for(assign(atoms))
    for _, text in texts:
        observation = re.fullmatch(r'obs\s+\?([A-Za-z_][A-Za-z_0-9]*).*\s+given', text, re.DOTALL)
        if observation:
            add(observation[1], 'observation')
        try:
            parsed = notation.parse_definition(text, ctx)
        except (ValueError, TypeError):
            try:
                parsed = notation.parse_definition(text)
            except (ValueError, TypeError):
                try:
                    parsed = notation.parse_expr(text, ctx)
                except (ValueError, TypeError):
                    try:
                        parsed = notation.parse_value(text)
                    except (ValueError, TypeError):
                        continue
        if hasattr(parsed, 'spec'):
            add(parsed.name, parsed.kind)
            spec = parsed.spec
            if parsed.kind == 'operation':
                for edge in (*spec.inputs, spec.output):
                    add(edge.sort, 'object')
            if parsed.kind == 'bridge':
                add(spec.source, 'object')
                add(spec.target, 'object')
            if parsed.kind == 'object':
                for _, sort in spec.extra.get('notation_fields', ()):
                    add(sort, 'object')
                if spec.canon:
                    add(spec.canon.fn, 'operation')
                for name in spec.interface:
                    add(name, 'operation')
                for fields in (spec.tags or {}).values():
                    for _, sort in fields:
                        add(sort, 'object')
                instantiation = spec.extra.get('notation_instantiation')
                if instantiation:
                    for name in re.findall(r'([A-Za-z_][A-Za-z_0-9]*)\s*[<\[]', instantiation):
                        add(name, 'object')
                    for name in re.findall(r',\s*([a-z][A-Za-z_0-9]*)\s*\]', instantiation):
                        add(name, 'operation')
            if isinstance(parsed.body, n.NODE_TYPES):
                node(parsed.body)
        elif isinstance(parsed, n.NODE_TYPES):
            node(parsed)
        else:
            value(parsed)
    return [*atoms, *extra]


def test_published_machine_formulas_roundtrip():
    from opulse.notation3.export import _worlds

    root = Path(__file__).resolve().parents[1] / 'docs/assets/data'
    files = [path for family in ('worlds_v2', 'atoms2')
             for path in (root / family).glob('*.json')]
    files.append(Path(__file__).resolve().parents[1] / 'docs/assets/js/atoms2/data.js')
    converted = Counter()
    failures = []
    for path in files:
        if path.suffix == '.js':
            source = path.read_text()
            data = json.JSONDecoder().raw_decode(source.split('.kernelData=', 1)[1])[0]
        else:
            data = json.loads(path.read_text())
        if 'notation3' not in data or path.name == 'parse_status.json':
            continue
        family = path.parent.name if path.suffix != '.js' else 'data_js'
        source = path.relative_to(root).as_posix() if family == 'atoms2' else 'data.js' if family == 'data_js' else None
        worlds = _worlds(data, family, source)
        for world, block in data['notation3']['worlds'].items():
            legend = assign(worlds[world])
            ctx = context_for(legend)
            for text, expected in block['formulas'].items():
                try:
                    result = convert_text(text, legend, ctx)
                    assert result == expected
                    assert v3.to_ascii(result['display']) == result['ascii']
                    assert v3.to_display(result['ascii']) == result['display']
                    assert v3.check(v3.parse(result['display'])) == []
                    converted[family] += 1
                except (ConversionError, v3.NotationError, AssertionError, KeyError) as exc:
                    failures.append((family, path.name, world, text[:100], str(exc)[:160]))
    print('converted published machine formulas:', dict(converted))
    assert not failures, failures[:30]


def test_unpublished_machine_formulas_convert():
    # gen_v2 and meta exports carry no published block, but every machine-parseable
    # formula in them must still convert and round-trip (restores the corpus check
    # dropped when the published-block test above took over worlds_v2 and atoms2).
    root = Path(__file__).resolve().parents[1] / 'docs/assets/data'
    converted = Counter()
    failures = []
    for path in [path for family in ('gen_v2', 'meta') for path in sorted((root / family).glob('*.json'))]:
        data = json.loads(path.read_text())
        for unit, atoms in _corpus_units(path, data):
            texts = _export_formulas(unit)
            if not atoms or not texts:
                continue
            legend = assign(_referenced_atoms(texts, atoms))
            ctx = context_for(legend)
            for field, text in texts:
                if field in ('text', 'design_decl') and is_design_text(text, ctx):
                    continue
                parsed = None
                for parser in (lambda text, ctx=ctx: notation.parse_definition(text, ctx),
                               lambda text, ctx=ctx: notation.parse_expr(text, ctx), notation.parse_value):
                    try:
                        parsed = parser(text)
                        break
                    except (ValueError, TypeError):
                        pass
                try:
                    result = convert_text(text, legend, ctx)
                    assert v3.to_ascii(result['display']) == result['ascii']
                    assert v3.to_display(result['ascii']) == result['display']
                    assert v3.check(v3.parse(result['display'])) == []
                    converted[path.parent.name] += 1
                except (ConversionError, v3.NotationError, AssertionError, KeyError) as exc:
                    if parsed is not None:
                        failures.append((path.parent.name, path.name, text[:100], str(exc)[:160]))
    print('converted unpublished machine formulas:', dict(converted))
    assert converted['gen_v2'] > 1000 and converted['meta'] > 50, dict(converted)
    assert not failures, failures[:30]


def test_calls_with_values_are_never_collapsed_to_a_symbol_mark():
    legend = assign([Atom('turns', 'combinator', 0, 'given', 2, op_arity=1),
                     Atom('count', 'observation', 0, 'given', 1)])
    assert convert_text('?count{xs}', legend)['display'] == 'Â⟨xs⟩'
    with pytest.raises(ConversionError):
        convert_text('@turns[missing](List<5, 9, 0>, List<0, 1>)', legend)


def test_integer_branches_are_not_boolean_predicates(legend):
    from dataclasses import replace

    # Lit(1) == Lit(True) in Python: an Int-valued branch must not collapse to a predicate.
    indicator = assign([Atom('indicator', 'operation', 0, 'given', 1)])
    given = convert_text('op indicator(b: Bool) -> Int = if b then 1 else 0 given', indicator)
    assert given['display'] == indicator.by_name('indicator', 'operation').display
    defn = notation.parse_definition('op f(b: Bool) -> Int = if b then 1 else 0 L1')
    result = convert_definition(defn, legend)[1]
    assert v3.show(result) == '♦₁ b = { { 1, if b; 0, else } }'
    boolean = replace(defn, body=n.Case(((n.Test(n.Var('b')), n.Lit(True)),), n.Lit(False)))
    assert v3.show(convert_definition(boolean, legend)[1]) == '♦₁ b = { b }'


def test_given_bodies_never_become_formulas(legend):
    for text in ('op succ(x: Int) -> Int = add(x, 1) given',
                 'obs ?wall{s: Int} -> Bool = not(?water{s}) given',
                 'comb @t[f: Int -> Int](x: Int) -> Int = f(x) given'):
        result = convert_text(text, legend)
        assert '=' not in result['display']
        assert result['signature'] is not None


def test_published_given_declarations_keep_only_the_head():
    examples = (
        ('head', 'op head(xs: List) -> Int = first(xs) or Bottom(empty) given'),
        ('tail', 'op tail(xs: List) -> List = rest(xs) or Bottom(empty) given'),
        ('next', 'op next(d: Date) -> Date = step_day(d) given'),
        ('distinct_count', 'op distinct_count(xs: List) -> Int = Set<blocks> given'),
        ('fold', 'op fold(xs: List) -> Int = move(xs) given'),
        ('chain', 'op chain(xs: List) -> Int = fs(xs) given'),
        ('indicator', 'op indicator(b: Bool) -> Int = if b then 1 else 0 given'),
    )
    atoms = [Atom(name, 'operation', 0, 'given', 1) for name, _ in examples]
    atoms.extend((Atom('List', 'object', 0, 'given'), Atom('Date', 'object', 0, 'given')))
    world = assign(atoms)
    for name, declaration in examples:
        converted = convert_text(declaration, world)
        assert converted['display'] == world.by_name(name, 'operation').display
        assert converted['signature'] is not None


def test_unwrap_call_is_the_unwrap_operation_and_make_constructs():
    from opulse.notation3.convert import UndeclaredAtom
    from opulse.notation3.legend import Atom, assign

    legend = assign([Atom('Xor', 'object', 4, 'invented'),
                     Atom('Xor.base', 'operation', 4, 'invented', 1),
                     Atom('graph', 'operation', 0, 'given', 0),
                     Atom('table', 'observation', 0, 'given', 1)])
    base = legend.by_name('Xor.base', 'operation').display
    xor = legend.by_name('Xor', 'object').display
    graph = legend.by_name('graph', 'operation').display
    table = legend.by_name('table', 'observation').display
    shown = convert_text('?table{Xor.base(Xor.make(graph()))}', legend)['display']
    assert shown == f'{table}⟨{base} ({xor} ({graph}()))⟩'
    assert convert_text('Xor.base(...)', legend)['display'] == base
    # A dotted name that is neither declared nor a constructor never prints as the object.
    with pytest.raises(UndeclaredAtom):
        convert_text('?table{Xor.width(Xor.make(graph()))}', legend)


def test_given_signature_type_variables_are_distinct_slots_never_bool():
    # B in a given combinator signature is a type variable, not Bool; each variable keeps
    # its own slot within the declaration.
    world = assign([Atom('seq', 'combinator', 0, 'given', 1, op_arity=2)])
    signature = convert_text('comb @seq[f: A->B,g: B->C](x: A) -> C given', world)['signature']['display']
    mark = world.by_name('seq', 'combinator').display
    assert signature == f'{mark} : (𝕏ₐ → 𝕏ₑ) × (𝕏ₑ → 𝕏ₕ) × 𝕏ₐ → 𝕏ₕ'
    assert '𝔹' not in signature
    boolean = assign([Atom('branch', 'combinator', 0, 'given', 1, op_arity=1)])
    assert '𝔹' in convert_text('comb @branch[t: Bool -> Bool](x: A) -> A given',
                               boolean)['signature']['display']
