"""Notation v3's lossless two-spelling surface contract."""

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.notation3 import (
    ALLOWED_DISPLAY_CHARS,
    Expr,
    Mark,
    NotationError,
    Stmt,
    check,
    kind_of,
    lex,
    parse,
    parse_expr,
    register_family,
    show,
    to_ascii,
    to_display,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tests/data/notation3'


def test_numbered_given_indices_are_lossless_and_distinct():
    for index in ('01', '07', '012'):
        display = '♦' + ''.join('₀₁₂₃₄₅₆₇₈₉'[int(digit)] for digit in index)
        ascii_text = '\\dia_' + index
        assert to_ascii(display) == ascii_text
        assert to_display(ascii_text) == display
        mark = lex(display)[0].value
        assert mark.index_kind == 'given_num' and mark.index_value == index
        assert parse_expr(ascii_text) == parse_expr(display)
        assert mark != lex('♦₇')[0].value
    assert lex('♦₇')[0].value.index_kind == 'def'
    for invalid in ('\\dia_0', '\\dia_00', '\\dia_007', '♦₀', '♦₀₀', '♦₀₀₇'):
        with pytest.raises(NotationError):
            lex(invalid)
    for sign in '@#$&':
        assert to_display('^0' + sign + ' : \\bbB -> \\bbZ') == '⁰' + sign + ' : 𝔹 → ℤ'


@pytest.fixture(scope='module')
def corpus():
    display = [row.split('\t', 1) for row in (DATA / 'corpus_final.txt').read_text().splitlines()]
    ascii_rows = [row.split('\t', 1) for row in (DATA / 'corpus_ascii.txt').read_text().splitlines()]
    assert [label for label, _ in display] == [label for label, _ in ascii_rows]
    return [(label, line, ascii_line) for (label, line), (_, ascii_line) in zip(display, ascii_rows)]


@pytest.fixture(scope='module')
def definitions():
    data = json.loads((ROOT / 'docs/assets/data/worlds/integer.json').read_text())
    result = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'definition' and isinstance(item, str):
                    result.append(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    assert len(result) == 100
    return result


def test_v1_definitions_roundtrip(definitions):
    for line in definitions:
        assert show(parse(line)) == line
        assert to_display(to_ascii(line)) == line


def test_corpus_spelling_and_ast(corpus):
    for _, display, ascii_line in corpus:
        assert show(parse(display)) == display
        assert show(parse(display), ascii=True) == ascii_line
        assert parse(display) == parse(ascii_line)


def test_c1_to_c20_have_no_kind_errors(corpus):
    for label, display, _ in corpus:
        if label.startswith('C'):
            assert check(parse(display)) == [], display


@pytest.mark.parametrize('line', [
    'a ▼₇ ♦₆ b', 'a ♦₆ b ♦₇ c', 'x ↦', 'a + b ≡₁ b + a ⇒ ?x',
    'Θ₁ [♡₄₅]x y z',
])
def test_must_reject(line):
    with pytest.raises(NotationError):
        parse(line)


@pytest.mark.parametrize(('left', 'right'), [
    ('Θ₁[♡₄₅] 3', 'Θ₁ [♡₄₅] 3'),
    ('♦₆(a, b)', '♦₆ (a, b)'),
    ('Ô₁⟨s⟩', 'Ô₁ ⟨s⟩'),
])
def test_whitespace_never_changes_parse(left, right):
    assert parse(left) == parse(right)


@pytest.mark.parametrize(('display', 'ascii_line'), [
    ('"a\\n"', '"a\\n"'),
    ('[-1, 2]', '[-1, 2]'),
    ('⊤ ⇒ ⊥', '\\top => \\bot'),
    ('fail("reason")', 'fail("reason")'),
    ('unknown("fuel")', 'unknown("fuel")'),
    ('let x = 1 in x + 1', 'let x = 1 in x + 1'),
    ('rec ♦ᵣ(x, y) = x ⊢ ↓ m in ♦ᵣ(a, b)',
     'rec \\dia_r(x, y) = x |- \\dec m in \\dia_r(a, b)'),
    ('memo rec ♦ᵣ(x) = x ⊢ fuel in ♦ᵣ(x)',
     'memo rec \\dia_r(x) = x |- fuel in \\dia_r(x)'),
    ('rec ♦ᵣ(x) = x ⊢ legacy in ♦ᵣ(x)',
     'rec \\dia_r(x) = x |- legacy in \\dia_r(x)'),
    ('■₄() + □₅(head: ℤ, tail: 𝕃₂)',
     '\\sq_4() + \\wsq_5(head: \\bbZ, tail: \\bbL_2)'),
    ('≡₁ : ∀ a, b ∈ ℤ, c ∈ 𝔹. a == b',
     '\\eqv_1 : \\all a, b \\in \\bbZ, c \\in \\bbB. a == b'),
    ('prog (x = 0, y = 1) entry L0 { L0: x := 3; jump L1; L1: halt x }',
     'prog (x = 0, y = 1) entry L0 { L0: x := 3; jump L1; L1: halt x }'),
    ('prog () entry L0 { L0: if x jump L1 else L2; L1: halt x; L2: halt 0 }',
     'prog () entry L0 { L0: if x jump L1 else L2; L1: halt x; L2: halt 0 }'),
    ('♦₃′', "\\dia_3'"),
    ('♦ₐ₂', '\\dia_a2'),
    ('◈¹⁰⁰⁰ₐ', '\\k1000_a'),
    ('♦⌞x⌟′', "\\dia{| x |}'"),
])
def test_extensions_both_spellings(display, ascii_line):
    assert show(parse(display)) == display
    assert to_ascii(display) == ascii_line
    assert to_display(ascii_line) == display


def test_lex_has_columns_on_errors():
    with pytest.raises(NotationError) as raised:
        lex('a + ☃')
    assert raised.value.column == 4


def test_lex_identical_tokens():
    assert lex('¹♦₆⟨x⟩') == lex('^1\\dia_6<|x|>')


def test_negative_whitespace_has_the_same_parse():
    assert parse('- 84') == parse('-84')
    assert show(parse('- 84')) == '- 84'
    assert show(parse('-0')) == '-0'


@pytest.mark.parametrize(('line', 'message'), [
    ('ℤ(3)', 'given number set'),
    ('𝔹(1)', 'given number set'),
    ('Φ₂[+][1, 2]', 'atoms expected; to pass a list write Φ₂[+]([1, 2])'),
    ('Φ₂[3]', 'atoms expected; to pass a list write Φ₂([1, 2])'),
    ('Φ₂["s"]', 'atoms expected; to pass a list write Φ₂([1, 2])'),
    ('a + (≡₁ b)', 'law mark'),
    ('Ô₁(s)', 'observation mark requires'),
    ('♦₁⟨s⟩', 'non-observation mark'),
])
def test_kind_checker_misuse(line, message):
    assert any(message in error.message for error in check(parse(line)))


def test_template_header_rejects_locally_wrong_slot_kind():
    tree = parse('Θ₁[♦ₐ] x = { Θ₁[𝕏ₜ] x }')
    assert any('expected operation slot, got object' in error.message for error in check(tree))


def test_group_is_lossless_node():
    assert parse_expr('(x)').tag == 'group'


def test_family_registration_is_append_only():
    register_family('frakTest', '𝔄', 'kind7')
    assert kind_of(Mark(None, 'frakTest')) == 'kind7'
    assert show(parse('𝔄₃')) == '𝔄₃'
    with pytest.raises(ValueError):
        register_family('frakTest', '𝔅', 'kind7')


def test_deep_groups():
    text = '(' * 200 + 'x' + ')' * 200
    assert show(parse(text)) == text


mark = st.sampled_from(['♦₆(2)', '♦₃(2)', '♦ₐ₂(2)', '♦⌞x⌟(2)', '◈¹⁰⁰⁰ₐ(2)',
                        'Ŝ₂′⟨s⟩', 'ℤ(2)', '@(2)', '↝₁(2)', '♦₁₀₀₀₀₀₀(2)'])
mark_ast = st.builds(Mark, st.sampled_from([None, 0, 1, 17]),
                     st.sampled_from(['dia', 'hatS', 'bbD', '#k']),
                     st.sampled_from([None, 1000]),
                     st.sampled_from(['def', 'slot', 'given', 'splice']),
                     st.one_of(st.just(None), st.just(10**6), st.just('a2'),
                               st.just(Expr('var', ('x',)))), st.booleans()).filter(
                                   lambda item: (item.family == '#k') == (item.kind_number is not None)
                                   and (item.index_kind == 'given' and item.index_value is None
                                        or item.index_kind == 'def' and item.index_value == 10**6
                                        or item.index_kind == 'slot' and item.index_value == 'a2'
                                        or item.index_kind == 'splice' and isinstance(item.index_value, Expr)))
marked_call = st.builds(lambda item: Expr('call', (Expr('mg', (item, ())),
                                                    '<|' if item.family == 'hatS' else '(',
                                                    (Expr('num', (2,)),))), mark_ast)
atom = st.one_of(st.builds(lambda number: Expr('num', (number,)), st.integers(-100, 10**6)),
                 st.builds(lambda name: Expr('var', (name,)), st.sampled_from(['a', 'x', 'y'])),
                 st.builds(lambda value: Expr('str', (value,)), st.text(alphabet='abc 0', max_size=8)),
                 st.builds(lambda text: parse_expr(text), mark),
                 marked_call,
                 st.sampled_from([parse_expr('-5'), parse_expr('⊤'), parse_expr('⊥'),
                                  parse_expr('[-1, 2]'), parse_expr('fail("oops")'),
                                  parse_expr('unknown("fuel")'), parse_expr('■₄()'),
                                  parse_expr('□₅(value: ℤ)'),
                                  parse_expr('♣₆(x, y)'),
                                  parse_expr('Θ₁[+] 3')]))
expression = st.recursive(atom, lambda child: st.one_of(
    st.builds(lambda item: Expr('group', ((item,),)), child),
    st.builds(lambda item: Expr('list', ((item,),)), child),
    st.builds(lambda item: Expr('fail', (item,)), child),
    st.builds(lambda item: Expr('un', ('-', Expr('group', ((item,),)))),
              child.filter(lambda item: item.tag == 'num')),
    st.builds(lambda item: Expr('let', ('x', item, parse_expr('x + 1'))), child)), max_leaves=12)
statement = st.one_of(st.builds(lambda item: Stmt('expr', (item,)), expression),
                      st.sampled_from([parse('rec ♦ᵣ(x) = x ⊢ ↓ x in ♦ᵣ(3)'),
                                       parse('memo rec ♦ᵣ(x) = x ⊢ legacy in ♦ᵣ(x)'),
                                       parse('prog () entry L0 { L0: halt 0 }'),
                                       parse('■₄() + □₅(head: ℤ)'),
                                       parse('□₅(value: ℤ)'),
                                       parse('≡₁ : ∀ a ∈ ℤ, b ∈ 𝔹. a == b')]))


@settings(max_examples=2000, derandomize=True, deadline=None)
@given(statement)
def test_generated_ast_roundtrips(node):
    display = show(node)
    ascii_line = show(node, ascii=True)
    assert parse(display) == node
    assert parse(ascii_line) == node
    assert to_display(to_ascii(display)) == display
    assert ascii_line.isascii()
    assert {char for char in display if not char.isascii()} <= ALLOWED_DISPLAY_CHARS


def test_constructor_call_in_operand_position():
    line = 'a ♦₆ ♣₄(x, y)'
    assert show(parse(line)) == line
    assert to_display(to_ascii(line)) == line


def test_double_colon_is_rejected():
    with pytest.raises(NotationError):
        parse('𝕃₂::cons(x, y)')


def test_function_type_inside_parentheses():
    line = 'Σ₁ : (ℝ → ℝ) × ℝ → ℝ'
    assert show(parse(line)) == line
    assert to_ascii(line) == 'Sigma_1 : (\\bbR -> \\bbR) \\x \\bbR -> \\bbR'.replace('Sigma', '\\Sigma')
    assert to_display(to_ascii(line)) == line
