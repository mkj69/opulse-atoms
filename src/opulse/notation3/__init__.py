"""Lossless notation v3 surface grammar (display and v3-ASCII share one AST).

Parentheses are explicit Group nodes; the printer does not infer precedence.
Nesting to at least 200 levels is supported; extremely deep inputs remain limited
by Python's recursion limit (both parsing and printing recurse on the AST).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, fields
from typing import Any

SUB = '₀₁₂₃₄₅₆₇₈₉'
SUP = '⁰¹²³⁴⁵⁶⁷⁸⁹'
SLOT = dict(zip('aehijklmnoprstuvx', 'ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ'))
SLOT_REVERSE = {value: key for key, value in SLOT.items()}
FAMILIES: dict[str, tuple[str, str]] = {}
GLYPHS: dict[str, str] = {}


def register_family(ascii_name: str, glyph: str, kind: str) -> None:
    """Append a globally unique family (existing mappings are immutable)."""
    if (not re.fullmatch(r'[A-Za-z]+', ascii_name) or len(glyph) != 1
            or ascii_name in FAMILIES or glyph in GLYPHS
            or glyph.isascii()):
        raise ValueError('family must have a fresh ASCII name and display glyph')
    global ALLOWED_DISPLAY_CHARS
    FAMILIES[ascii_name] = (glyph, kind)
    GLYPHS[glyph] = ascii_name
    ALLOWED_DISPLAY_CHARS = frozenset((*ALLOWED_DISPLAY_CHARS, glyph))


ALLOWED_DISPLAY_CHARS = frozenset(SUB + SUP + ''.join(SLOT.values()) +
                                  '′⟨⟩⌜⌝⌞⌟⇒→↦⊢…×∈∀∣↾↓⊤⊥◈≡↝⇝')
for _name, _glyph in zip(['spade', 'wspade', 'heart', 'wheart', 'dia', 'wdia', 'club', 'wclub', 'sq', 'wsq', 'dot', 'wdot', 'up', 'wup', 'dn', 'wdn', 'lz', 'wlz', 'st', 'wst'],
                         '♠♤♥♡♦♢♣♧■□●○▲△▼▽◆◇★☆'):
    register_family(_name, _glyph, 'operation')
_bmp = dict(zip('CHNPQRZ', 'ℂℍℕℙℚℝℤ'))
for _position, _letter in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
    register_family('bb' + _letter, _bmp.get(_letter, chr(0x1D538 + _position)), 'object')
for _name, _glyph in zip(['Gamma', 'Delta', 'Theta', 'Lambda', 'Xi', 'Pi', 'Sigma', 'Phi', 'Psi', 'Omega'], 'ΓΔΘΛΞΠΣΦΨΩ'):
    register_family(_name, _glyph, 'combinator')
for _letter, _glyph in zip('ACEGHIJOSUWYZ', 'ÂĈÊĜĤÎĴÔŜÛŴŶẐ'):
    register_family('hat' + _letter, _glyph, 'observation')
register_family('eqv', '≡', 'law')
register_family('squig', '↝', 'bridge')
register_family('Squig', '⇝', 'bridge')

PUNCT = [('⇒', '=>', '=>'), ('==', '==', '=='), ('!=', '!=', '!='), ('<=', '<=', '<='),
         ('>=', '>=', '>='), ('↦', '|->', '|->'), ('→', '->', '->'), ('⊢', '|-', '|-'),
         ('⟨', '<|', '<|'), ('⟩', '|>', '|>'), ('⌜', '[|', '[|'), ('⌝', '|]', '|]'),
         ('⌞', '{|', '{|'), ('⌟', '|}', '|}'), ('…', '...', '...'),
         ('×', '\\x', 'x*'), ('∈', '\\in', 'in'), ('∀', '\\all', 'all'),
         ('∣', '\\mid', 'mid'), ('↾', '\\seal', 'seal'), ('↓', '\\dec', 'dec'),
         ('⊤', '\\top', 'top'), ('⊥', '\\bot', 'bot'),
         ('′', "'", 'prime'),
         (':=', ':=', ':='),
         *[(sign, sign, sign) for sign in '=<>+-*/%()[]{} ,;:.?@#$&' if sign != ' ']]
DISPLAY = {token: display for display, _, token in PUNCT}
ASCII = {token: ascii_text for _, ascii_text, token in PUNCT}
SPELLINGS = sorted({(spelling, token) for display, ascii_text, token in PUNCT
                    for spelling in (display, ascii_text)}, key=lambda item: -len(item[0]))
KEYWORDS = {'if', 'else', 'and', 'or', 'not', 'let', 'in', 'rec', 'memo', 'fail', 'unknown',
            'prog', 'entry', 'jump', 'halt', 'fuel', 'legacy'}
BIN_SIGNS = {'+', '-', '*', '/', '%', '==', '!=', '<', '<=', '>', '>=', 'x*', 'in',
             'seal', 'and', 'or', 'not'}
FIRST = {'VAR', 'NUM', 'CONST', 'STR', '?', 'top', 'bot', '...', '(', '[', '{', '[|', 'MARK',
         'let', 'rec', 'memo', 'fail', 'unknown', 'prog'}


class NotationError(ValueError):
    """Invalid source, with a zero-based source column."""

    def __init__(self, message: str, column: int):
        self.message = message
        self.column = column
        super().__init__(f'{message} at column {column}')


@dataclass(frozen=True)
class Mark:
    layer: int | None
    family: str
    kind_number: int | None = None
    index_kind: str = 'given'
    index_value: int | str | Expr | None = None
    prime: bool = False


@dataclass(frozen=True)
class Expr:
    """Expression node; tag and args are the public, lossless node discriminant."""

    tag: str
    args: tuple[Any, ...]
    style: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Stmt:
    """Statement node; ``expr`` wraps a standalone expression."""

    tag: str
    args: tuple[Any, ...]


@dataclass(frozen=True)
class BinderGroup:
    names: tuple[str, ...]
    domain: Expr


@dataclass(frozen=True)
class Assignment:
    name: str
    value: Expr


@dataclass(frozen=True)
class Block:
    label: str
    assignments: tuple[Assignment, ...]
    terminator: Expr


NODE_TYPES = (Mark, Expr, Stmt, BinderGroup, Assignment, Block)


@dataclass(frozen=True)
class Token:
    kind: str
    value: Any
    column: int = field(compare=False)


def kind_of(mark: Mark) -> str:
    """Lexical kind, independent of the world legend."""
    if mark.family == '#k':
        return f'kind{mark.kind_number}'
    return 'operation' if mark.family in '@#$&' else FAMILIES[mark.family][1]


def _digits(text: str, alphabet: str) -> int:
    return int(''.join(str(alphabet.index(char)) for char in text))


def _mark_index(digits: str, column: int) -> tuple[str, int | str]:
    if digits[0] == '0':
        if len(digits) == 1 or digits[1] == '0':
            raise NotationError('bad numbered given index', column)
        return 'given_num', digits
    return 'def', int(digits)


def _mark_at(text: str, start: int) -> tuple[Mark, int] | None:
    cursor = start
    layer = None
    match = re.match(r'[' + SUP + r']+', text[cursor:])
    if match:
        layer = _digits(match.group(), SUP)
        cursor += len(match.group())
    elif text.startswith('^', cursor):
        match = re.match(r'\^([0-9]+)', text[cursor:])
        if match:
            layer = int(match.group(1))
            cursor += len(match.group())
    family = None
    number = None
    if cursor < len(text) and text[cursor] in GLYPHS:
        family = GLYPHS[text[cursor]]
        cursor += 1
    elif cursor < len(text) and text[cursor] in '@#$&':
        family = text[cursor]
        cursor += 1
    elif text.startswith('◈', cursor):
        match = re.match(r'[' + SUP + r']+', text[cursor + 1:])
        if not match:
            raise NotationError('◈ needs a kind number', cursor)
        family, number = '#k', _digits(match.group(), SUP)
        cursor += 1 + len(match.group())
    elif text.startswith('\\', cursor):
        match = re.match(r'\\(k[0-9]+|[A-Za-z]+)', text[cursor:])
        if match and match.group(1).startswith('k') and match.group(1)[1:].isdigit():
            family, number = '#k', int(match.group(1)[1:])
            cursor += len(match.group())
        elif match and match.group(1) in FAMILIES:
            family = match.group(1)
            cursor += len(match.group())
    if family is None:
        if layer is not None:
            raise NotationError('layer without mark', start)
        return None
    index_kind, index_value = 'given', None
    match = re.match(r'[' + SUB + r']+', text[cursor:])
    if match:
        digits = ''.join(str(SUB.index(char)) for char in match.group())
        index_kind, index_value = _mark_index(digits, cursor)
        cursor += len(match.group())
    elif cursor < len(text) and text[cursor] in SLOT_REVERSE:
        letter = SLOT_REVERSE[text[cursor]]
        cursor += 1
        match = re.match(r'[' + SUB + r']+', text[cursor:])
        if match:
            letter += str(_digits(match.group(), SUB))
            cursor += len(match.group())
        index_kind, index_value = 'slot', letter
    elif text.startswith('_', cursor):
        match = re.match(r'_([0-9]+|[a-z][0-9]*)', text[cursor:])
        if not match or (not match.group(1).isdigit() and match.group(1)[0] not in SLOT):
            raise NotationError('bad index', cursor)
        raw = match.group(1)
        index_kind, index_value = _mark_index(raw, cursor) if raw.isdigit() else ('slot', raw)
        cursor += len(match.group())
    elif text.startswith('⌞', cursor) or text.startswith('{|', cursor):
        index_kind = 'splice'
        cursor += 1 if text[cursor] == '⌞' else 2
    prime = index_kind != 'splice' and cursor < len(text) and text[cursor] in "′'"
    if prime:
        cursor += 1
    return Mark(layer, family, number, index_kind, index_value, prime), cursor


def lex(text: str) -> list[Token]:
    """Tokenize either spelling identically, preserving zero-based error columns."""
    result = []
    cursor = 0
    while cursor < len(text):
        if text[cursor].isspace():
            cursor += 1
            continue
        start = cursor
        mark = _mark_at(text, cursor)
        if mark:
            value, cursor = mark
            result.append(Token('MARK', value, start))
            continue
        if text[cursor] == '"':
            match = re.match(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"', text[cursor:])
            if not match:
                raise NotationError('invalid string', start)
            value = json.loads(match.group())
            if any(ord(char) > 127 for char in value):
                raise NotationError('string must be ASCII', start)
            result.append(Token('STR', value, start))
            cursor += len(match.group())
            continue
        if text[cursor].isascii() and text[cursor].isalpha():
            match = re.match(r'[A-Z][A-Za-z0-9_]*' if text[cursor].isupper()
                             else r'[a-z][A-Za-z0-9_]*', text[cursor:])
            assert match is not None
            word = match.group()
            kind = ('CONST' if word[0].isupper() else
                    'inword' if word == 'in' else word if word in KEYWORDS else 'VAR')
            result.append(Token(kind, word, start))
            cursor += len(word)
            continue
        if text[cursor] in '0123456789':
            match = re.match(r'[0-9]+', text[cursor:])
            assert match is not None
            result.append(Token('NUM', int(match.group()), start))
            cursor += len(match.group())
            continue
        for spelling, kind in SPELLINGS:
            if text.startswith(spelling, cursor):
                result.append(Token(kind, kind, start))
                cursor += len(spelling)
                break
        else:
            raise NotationError(f'bad character {text[cursor]!r}', start)
    result.append(Token('EOF', None, len(text)))
    return result


def _expr(tag: str, *args: Any) -> Expr:
    return Expr(tag, args)


class _Parser:
    def __init__(self, text: str):
        self.tokens = lex(text)
        self.position = 0

    def tok(self, ahead: int = 0) -> str:
        return self.tokens[min(self.position + ahead, len(self.tokens) - 1)].kind

    def eat(self, expected: str | None = None) -> Token:
        token = self.tokens[self.position]
        if expected is not None and token.kind != expected:
            raise NotationError(f'expected {expected}, got {token.kind}', token.column)
        self.position += 1
        return token

    def top(self) -> Stmt:
        result = self.stmt()
        self.eat('EOF')
        return result

    def stmt(self) -> Stmt:
        head = self.e()
        if self.tok() == '=':
            self.eat()
            return Stmt('def', (head, self.e(), self.check()))
        if self.tok() == '=>':
            self.eat()
            return Stmt('res', (head, self.e()))
        if self.tok() == ':':
            self.eat()
            if self.tok() == 'all':
                self.eat()
                groups = []
                while True:
                    names = [self.eat('VAR').value]
                    while self.tok() == ',' and self.tok(1) == 'VAR':
                        self.eat()
                        names.append(self.eat('VAR').value)
                    self.eat('in')
                    domain = self.e()
                    groups.append(BinderGroup(tuple(names), domain))
                    if self.tok() != ',':
                        break
                    self.eat()
                self.eat('.')
                return Stmt('law', (head, tuple(groups), self.e(), self.check()))
            signature = self.e()
            if self.tok() == '->':
                self.eat()
                signature = _expr('arrow', signature, self.e())
            return Stmt('sig', (head, signature, self.check()))
        return Stmt('expr', (head,))

    def check(self) -> Expr | None:
        if self.tok() == '|-':
            self.eat()
            return self.e()
        return None

    def e(self) -> Expr:
        if self.tok() == 'let':
            self.eat()
            name = self.eat('VAR').value
            self.eat('=')
            value = self.e()
            self.eat('inword')
            return _expr('let', name, value, self.e())
        if self.tok() in ('memo', 'rec'):
            memo = self.tok() == 'memo'
            if memo:
                self.eat()
            self.eat('rec')
            mark = self.mg()
            self.eat('(')
            params = self.items(')')
            self.eat(')')
            self.eat('=')
            body = self.e()
            self.eat('|-')
            if self.tok() == 'dec':
                self.eat()
                measure = _expr('measure', 'dec', self.e())
            else:
                measure = _expr('measure', self.eat().kind)
                if measure.args[0] not in ('fuel', 'legacy'):
                    raise NotationError('expected fuel or legacy', self.tokens[self.position - 1].column)
            self.eat('inword')
            return _expr('rec', memo, mark, tuple(params), body, measure, self.e())
        left = self._chain()
        if self.tok() == '|->':
            if left.tag != 'var':
                raise NotationError('left of ↦ must be a variable', self.tokens[self.position].column)
            self.eat()
            return _expr('map', left.args[0], self.e())
        return left

    def _chain(self) -> Expr:
        return self._left(self._and, {'or'})

    def _left(self, sub: Any, operators: set[str]) -> Expr:
        left = sub()
        while self.tok() in operators:
            op = self.eat().kind
            left = _expr('bin', op, left, sub())
        return left

    def _and(self) -> Expr:
        return self._left(self._not, {'and'})

    def _not(self) -> Expr:
        if self.tok() in ('not', 'dec'):
            return _expr('un', self.eat().kind, self._not())
        return self._rel()

    def _rel(self) -> Expr:
        left = self._seal()
        if self.tok() in ('==', '!=', '<', '<=', '>', '>=', 'in'):
            left = _expr('bin', self.eat().kind, left, self._seal())
        return left

    def _seal(self) -> Expr:
        return self._left(self._add, {'seal'})

    def _add(self) -> Expr:
        return self._left(self._mul, {'+', '-'})

    def _mul(self) -> Expr:
        return self._left(self._prod, {'*', '/', '%'})

    def _prod(self) -> Expr:
        return self._left(self._neg, {'x*'})

    def _neg(self) -> Expr:
        if self.tok() == '-':
            sign = self.eat()
            if self.tok() == 'NUM':
                spaced = self.tokens[self.position].column != sign.column + 1
                number = self.eat().value
                style = ('negative-spaced' if spaced else 'negative') if number == 0 else (
                    'spaced' if spaced else None)
                return Expr('num', (-number,), style)
            return _expr('un', '-', self._neg())
        return self.term()

    def term(self) -> Expr:
        if self.tok() == 'MARK':
            mark = self.mg()
            if self.tok() in ('(', '<|'):
                return self.tail(self.call(mark))
            if self.tok() in FIRST and self.tok() not in ('let', 'rec', 'memo', 'prog'):
                return _expr('pre', mark, self.unit())
            return _expr('bare', mark)
        return self.tail(self.unit())

    def tail(self, operand: Expr) -> Expr:
        if self.tok() == 'MARK':
            mark = self.mg()
            if self.tok() in FIRST and self.tok() not in ('let', 'rec', 'memo', 'prog'):
                return _expr('inf', operand, mark, self.unit())
            return _expr('post', operand, mark)
        return operand

    def mg(self) -> Expr:
        mark = self.eat('MARK').value
        if mark.index_kind == 'splice':
            mark = Mark(mark.layer, mark.family, mark.kind_number, 'splice', self.e(), mark.prime)
            self.eat('|}')
            if self.tok() == 'prime':
                self.eat()
                mark = Mark(mark.layer, mark.family, mark.kind_number, 'splice',
                            mark.index_value, True)
        groups = []
        while self.tok() == '[':
            self.eat()
            groups.append(tuple(self.items(']', atoms=True)))
            self.eat(']')
        return _expr('mg', mark, tuple(groups))

    def call(self, mark: Expr) -> Expr:
        opening = self.eat().kind
        closing = ')' if opening == '(' else '|>'
        arguments = tuple(self.items(closing))
        self.eat(closing)
        return _expr('call', mark, opening, arguments)

    def items(self, closing: str, atoms: bool = False) -> list[Expr]:
        result = []
        while self.tok() != closing:
            if self.tok() in BIN_SIGNS and self.tok(1) in (closing, ','):
                item = _expr('binref', self.eat().kind)
            else:
                item = self.e()
                if not atoms and self.tok() == '->':
                    self.eat()
                    item = _expr('arrow', item, self.e())
                if not atoms and self.tok() == ':' and item.tag == 'var':
                    self.eat()
                    item = _expr('field', item.args[0], self.e())
            result.append(item)
            if self.tok() != ',':
                break
            self.eat()
        return result

    def unit(self) -> Expr:
        token = self.tok()
        if token in ('VAR', 'CONST', 'NUM', 'STR'):
            return _expr({'VAR': 'var', 'CONST': 'const', 'NUM': 'num', 'STR': 'str'}[token],
                         self.eat().value)
        if token in ('?', 'top', 'bot', '...'):
            return _expr('lit', self.eat().kind)
        if token in ('fail', 'unknown'):
            self.eat()
            self.eat('(')
            value = self.e()
            self.eat(')')
            return _expr(token, value)
        if token == 'prog':
            return self.program()
        if token in ('(', '['):
            self.eat()
            closing = ')' if token == '(' else ']'
            items = tuple(self.items(closing))
            self.eat(closing)
            return _expr('group' if token == '(' else 'list', items)
        if token == '[|':
            self.eat()
            quoted = self.stmt()
            self.eat('|]')
            return _expr('quote', quoted)
        if token == '{':
            self.eat()
            value = self.e()
            if self.tok() == '}':
                self.eat()
                return _expr('brace', value)
            if self.tok() == 'mid':
                self.eat()
                condition = self.e()
                self.eat('}')
                return _expr('setb', value, condition)
            cases = []
            while True:
                self.eat(',')
                condition = None if self.tok() == 'else' else self._case_condition()
                if condition is None:
                    self.eat('else')
                cases.append((value, condition))
                if self.tok() == '}':
                    self.eat()
                    return _expr('cases', tuple(cases))
                self.eat(';')
                value = self.e()
        if token == 'MARK':
            mark = self.mg()
            if self.tok() not in ('(', '<|'):
                raise NotationError('a mark in operand position must be called',
                                    self.tokens[self.position].column)
            return self.call(mark)
        raise NotationError(f'unexpected {token}', self.tokens[self.position].column)

    def _case_condition(self) -> Expr:
        self.eat('if')
        return self.e()

    def program(self) -> Expr:
        self.eat('prog')
        self.eat('(')
        initial = []
        while self.tok() != ')':
            name = self.eat('VAR').value
            self.eat('=')
            initial.append(Assignment(name, self.e()))
            if self.tok() != ',':
                break
            self.eat()
        self.eat(')')
        self.eat('entry')
        entry = self.eat('CONST').value
        self.eat('{')
        blocks = []
        while self.tok() != '}':
            label = self.eat('CONST').value
            self.eat(':')
            assignments = []
            while self.tok() == 'VAR' and self.tok(1) == ':=':
                name = self.eat().value
                self.eat(':=')
                assignments.append(Assignment(name, self.e()))
                self.eat(';')
            if self.tok() == 'jump':
                self.eat()
                terminator = _expr('jump', self.eat('CONST').value)
            elif self.tok() == 'halt':
                self.eat()
                terminator = _expr('halt', self.e())
            else:
                self.eat('if')
                condition = self.e()
                self.eat('jump')
                target = self.eat('CONST').value
                self.eat('else')
                terminator = _expr('branch', condition, target, self.eat('CONST').value)
            blocks.append(Block(label, tuple(assignments), terminator))
            if self.tok() != ';':
                break
            self.eat()
        self.eat('}')
        return _expr('prog', tuple(initial), entry, tuple(blocks))


def parse(text: str) -> Stmt:
    """Parse one complete statement, accepting either display or v3-ASCII."""
    limit = sys.getrecursionlimit()
    if len(text) > 150:
        sys.setrecursionlimit(max(limit, 12000))
    try:
        return _Parser(text).top()
    finally:
        if sys.getrecursionlimit() != limit:
            sys.setrecursionlimit(limit)


def parse_expr(text: str) -> Expr:
    """Parse one complete expression without a statement wrapper."""
    limit = sys.getrecursionlimit()
    if len(text) > 150:
        sys.setrecursionlimit(max(limit, 12000))
    try:
        parser = _Parser(text)
        result = parser.e()
        parser.eat('EOF')
        return result
    finally:
        if sys.getrecursionlimit() != limit:
            sys.setrecursionlimit(limit)


def _mark_text(mark: Mark, ascii: bool) -> str:
    result = '' if mark.layer is None else ('^' + str(mark.layer) if ascii else
                                            ''.join(SUP[int(char)] for char in str(mark.layer)))
    if mark.family == '#k':
        number = str(mark.kind_number)
        result += '\\k' + number if ascii else '◈' + ''.join(SUP[int(char)] for char in number)
    elif mark.family in '@#$&':
        result += mark.family
    else:
        result += '\\' + mark.family if ascii else FAMILIES[mark.family][0]
    if mark.index_kind in ('def', 'given_num'):
        number = str(mark.index_value)
        result += '_' + number if ascii else ''.join(SUB[int(char)] for char in number)
    elif mark.index_kind == 'slot':
        slot = str(mark.index_value)
        result += '_' + slot if ascii else SLOT[slot[0]] + ''.join(SUB[int(char)] for char in slot[1:])
    elif mark.index_kind == 'splice':
        result += ('{| ' + show(mark.index_value, ascii) + ' |}' if ascii else
                   '⌞' + show(mark.index_value, ascii) + '⌟')
    return result + ("'" if ascii else '′') if mark.prime else result


def _show(node: Stmt | Expr | Mark, ascii: bool = False) -> str:
    """Print the canonical display or ASCII spelling; explicit groups stay explicit."""
    if isinstance(node, Mark):
        return _mark_text(node, ascii)
    tag, args = node.tag, node.args
    spell = ASCII if ascii else DISPLAY
    render = lambda child: show(child, ascii)
    items = lambda values: ', '.join(map(render, values))
    check = lambda value: '' if value is None else ' ' + spell['|-'] + ' ' + render(value)
    if isinstance(node, Stmt):
        if tag == 'def':
            return render(args[0]) + ' = ' + render(args[1]) + check(args[2])
        if tag == 'res':
            return render(args[0]) + ' ' + spell['=>'] + ' ' + render(args[1])
        if tag == 'sig':
            return render(args[0]) + ' : ' + render(args[1]) + check(args[2])
        if tag == 'law':
            groups = ', '.join(', '.join(group.names) + ' ' + spell['in'] + ' ' +
                               render(group.domain) for group in args[1])
            return (render(args[0]) + ' : ' + spell['all'] + ' ' + groups + '. ' +
                    render(args[2]) + check(args[3]))
        if tag == 'expr':
            return render(args[0])
    if tag == 'mg':
        return render(args[0]) + ''.join('[' + items(group) + ']' for group in args[1])
    if tag == 'call':
        mark, opening, values = args
        if opening == '<|':
            return render(mark) + spell['<|'] + items(values) + spell['|>']
        space = ' ' if len(values) == 1 and values[0].tag not in (
            'var', 'num', 'const', 'str', 'lit', 'list', 'quote', 'field') else ''
        return render(mark) + space + '(' + items(values) + ')'
    if tag in ('pre', 'post'):
        return render(args[0]) + ' ' + render(args[1])
    if tag == 'inf':
        return render(args[0]) + ' ' + render(args[1]) + ' ' + render(args[2])
    if tag == 'bare':
        return render(args[0])
    if tag == 'bin':
        return render(args[1]) + ' ' + spell.get(args[0], args[0]) + ' ' + render(args[2])
    if tag == 'un':
        return spell.get(args[0], args[0]) + ' ' + render(args[1])
    if tag == 'map':
        return args[0] + ' ' + spell['|->'] + ' ' + render(args[1])
    if tag == 'let':
        return 'let ' + args[0] + ' = ' + render(args[1]) + ' in ' + render(args[2])
    if tag == 'rec':
        memo, mark, params, body, measure, continuation = args
        return (('memo ' if memo else '') + 'rec ' + render(mark) + '(' + items(params) +
                ') = ' + render(body) + ' ' + spell['|-'] + ' ' + render(measure) +
                ' in ' + render(continuation))
    if tag == 'measure':
        return spell['dec'] + ' ' + render(args[1]) if args[0] == 'dec' else args[0]
    if tag == 'arrow':
        return render(args[0]) + ' ' + spell['->'] + ' ' + render(args[1])
    if tag in ('group', 'list'):
        opening, closing = ('(', ')') if tag == 'group' else ('[', ']')
        return opening + items(args[0]) + closing
    if tag == 'field':
        return args[0] + ': ' + render(args[1])
    if tag == 'quote':
        return spell['[|'] + render(args[0]) + spell['|]']
    if tag == 'brace':
        return '{ ' + render(args[0]) + ' }'
    if tag == 'setb':
        return '{ ' + render(args[0]) + ' ' + spell['mid'] + ' ' + render(args[1]) + ' }'
    if tag == 'cases':
        return '{ ' + '; '.join(render(value) + ', ' + ('else' if condition is None else
                               'if ' + render(condition)) for value, condition in args[0]) + ' }'
    if tag == 'prog':
        initial, entry, blocks = args
        assignment = lambda item, sign: item.name + sign + render(item.value)
        return ('prog (' + ', '.join(assignment(item, ' = ') for item in initial) + ') entry ' +
                entry + ' { ' + '; '.join(block.label + ': ' +
                                         ''.join(assignment(item, ' := ') + '; ' for item in block.assignments) +
                                         render(block.terminator) for block in blocks) + ' }')
    if tag == 'jump':
        return 'jump ' + args[0]
    if tag == 'halt':
        return 'halt ' + render(args[0])
    if tag == 'branch':
        return 'if ' + render(args[0]) + ' jump ' + args[1] + ' else ' + args[2]
    if tag in ('fail', 'unknown'):
        return tag + '(' + render(args[0]) + ')'
    if tag in ('var', 'const'):
        return args[0]
    if tag == 'num':
        if node.style in ('negative', 'negative-spaced'):
            return '- 0' if node.style == 'negative-spaced' else '-0'
        return '- ' + str(-args[0]) if node.style == 'spaced' else str(args[0])
    if tag == 'str':
        return json.dumps(args[0], ensure_ascii=True)
    if tag in ('lit', 'binref'):
        return spell.get(args[0], args[0])
    raise ValueError(f'unknown AST node {tag}')


def show(node: Stmt | Expr | Mark, ascii: bool = False) -> str:
    """Print a lossless AST, supporting at least 200 nested groups."""
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 12000))
    try:
        return _show(node, ascii)
    finally:
        if sys.getrecursionlimit() != limit:
            sys.setrecursionlimit(limit)


def to_ascii(display_text: str) -> str:
    """Canonical v3-ASCII spelling of a display statement."""
    return show(parse(display_text), ascii=True)


def to_display(ascii_text: str) -> str:
    """Canonical display spelling of a v3-ASCII statement."""
    return show(parse(ascii_text))


@dataclass(frozen=True)
class KindError:
    message: str


def check(ast: Stmt | Expr, families: dict[str, tuple[str, str]] | None = None) -> list[KindError]:
    """Check local misuse only; no world signatures, inference or semantic verification.

    ``families`` can override lexical kinds for registered names; the parser never
    consults this table. Slots are compared only when a header supplies their kind.
    """
    errors: list[KindError] = []
    kinds = FAMILIES if families is None else families
    header: dict[Mark, tuple[tuple[str | None, ...], ...]] = {}

    def category(mark: Mark) -> str:
        if mark.family == '#k':
            return f'kind{mark.kind_number}'
        return 'operation' if mark.family in '@#$&' else kinds[mark.family][1]

    if isinstance(ast, Stmt) and ast.tag == 'def':
        head = ast.args[0]
        if head.tag in ('pre', 'bare', 'call'):
            head = head.args[0]
        elif head.tag == 'inf' or head.tag == 'post':
            head = head.args[1]
        if isinstance(head, Expr) and head.tag == 'mg':
            slots = []
            for group in head.args[1]:
                slots.append(tuple(category(item.args[0].args[0])
                                   if item.tag == 'bare' and item.args[0].tag == 'mg'
                                   and item.args[0].args[0].index_kind == 'slot' else None
                                   for item in group))
            header[head.args[0]] = tuple(slots)

    def walk(value: Any, *, top: bool = False, step: bool = False) -> None:
        if isinstance(value, Mark):
            if category(value) == 'law' and not (top or step):
                errors.append(KindError('law mark is only allowed as a statement head or rewrite step'))
            if value.index_kind == 'splice':
                walk(value.index_value)
            return
        if isinstance(value, (Stmt, Expr)):
            tag, args = value.tag, value.args
            if tag == 'mg':
                mark = args[0]
                walk(mark, top=top, step=step)
                if mark in header:
                    for expected_group, actual_group in zip(header[mark], args[1]):
                        for expected_kind, actual in zip(expected_group, actual_group):
                            if expected_kind is not None and actual.tag == 'bare' and actual.args[0].tag == 'mg':
                                actual_kind = category(actual.args[0].args[0])
                                if actual_kind != expected_kind:
                                    errors.append(KindError(f'expected {expected_kind} slot, got {actual_kind}'))
                for group_index, group in enumerate(args[1]):
                    for item in group:
                        if (item.tag in ('num', 'str', 'list') or
                                item.tag == 'un' and item.args[0] == '-' and item.args[1].tag == 'num'):
                            example = show(_expr('mg', mark, args[1][:group_index]))
                            errors.append(KindError('atoms expected; to pass a list write ' +
                                                    example + '([1, 2])'))
                        walk(item)
                return
            if tag == 'bare':
                walk(args[0], top=top)
                return
            if tag == 'call':
                mark_expr, opening, items = args
                base = mark_expr.args[0] if mark_expr.tag == 'mg' else mark_expr.args[0].args[0]
                kind = category(base)
                if kind == 'observation' and opening != '<|':
                    errors.append(KindError('observation mark requires ⟨ ⟩'))
                if kind != 'observation' and opening == '<|':
                    errors.append(KindError('non-observation mark cannot use ⟨ ⟩'))
                if (base.family in ('bbZ', 'bbB') and base.index_kind == 'given' and
                        len(items) == 1 and items[0].tag == 'num'):
                    errors.append(KindError('given number set is not callable on a number literal'))
                walk(mark_expr, top=top)
                walk(items)
                return
            if tag == 'inf' and args[1].tag == 'mg' and category(args[1].args[0]) == 'law':
                walk(args[0])
                walk(args[1], step=isinstance(ast, Stmt) and ast.tag == 'expr' and top)
                walk(args[2])
                return
            if isinstance(value, Stmt) and tag in ('def', 'sig', 'law'):
                walk(args[0], top=True)
                for item in args[1:]:
                    walk(item)
                return
            if isinstance(value, Stmt) and tag == 'expr':
                walk(args[0], top=True)
                return
            for item in args:
                walk(item)
            return
        if isinstance(value, (tuple, list)):
            for item in value:
                walk(item)
        elif isinstance(value, (BinderGroup, Assignment, Block)):
            for field in fields(value):
                walk(getattr(value, field.name))

    walk(ast)
    return errors
