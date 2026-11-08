"""Deterministic per-world assignment of notation-v3 marks."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from opulse import notation3 as n3
from opulse.atoms import notation


@dataclass(frozen=True)
class Atom:
    name: str
    kind: str
    layer: int
    origin: str
    arity: int | None = None
    inputs: tuple[str, ...] = ()
    output: str | None = None
    forms: tuple[str, ...] = ()
    produces: str | None = None
    op_arity: int | None = None
    form_of: str | None = None
    note: str | None = None
    form_fields: tuple[tuple[str, tuple[str, ...]], ...] = ()
    valued_forms: tuple[str, ...] = ()  # forms observed with at least one field


@dataclass(frozen=True)
class LegendEntry:
    atom: Atom
    mark: n3.Mark | None
    binsign: str | None
    display: str
    ascii: str
    signature: n3.Stmt | None


_SIGNS = dict(zip(('add', 'sub', 'mul', 'div', 'mod', 'eq', 'ne', 'lt', 'le',
                   'gt', 'ge', 'and', 'or', 'not'),
                  ('+', '-', '*', '/', '%', '==', '!=', '<', '<=', '>', '>=',
                   'and', 'or', 'not')))
_OPS = '@#$&♠♤♥♡♦♢♣♧■□●○▲△▼▽◆◇★☆'
_COMBS = 'ΓΔΘΛΞΠΣΦΨΩ'
_HATS = 'ÂĈÊĜĤÎĴÔŜÛŴŶẐ'
_OBJECTS = 'ABDEGHIJKLMOSTUVWXYZ'
_ARITY = {1: '▼▲▽△', 2: '♦♠♥♣♢♤♡♧'}
_NARY = '■□●○◆◇★☆'
_ROOT = Path(__file__).resolve().parents[3]
_HEADER = re.compile(r'^(obj|op|comb|obs|law|bridge|template)\s+[@?#~]?([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)?)', re.DOTALL)
_KINDS = {'obj': 'object', 'op': 'operation', 'comb': 'combinator',
          'obs': 'observation', 'law': 'law', 'bridge': 'bridge', 'template': 'template'}


def declaration_header(text: str) -> dict | None:
    """Read an export header even when its design body is not machine-parseable."""
    text = text.strip()
    text = re.sub(r'^template\s+(?:obj|op|comb|obs)\s+', 'template ', text)
    given = bool(re.search(r'\s+given$', text))
    match = _HEADER.match(text)
    if not match:
        return None
    label, name = match.groups()
    tail = text[match.end():]
    tail = re.sub(r'\s+given$', '', tail) if given else tail
    groups = []
    remaining = tail.strip()
    closings = {'[': ']', '{': '}', '(': ')', '<': '>'}
    while remaining and remaining[0] in closings:
        rest = _skip_group(remaining, remaining[0], closings[remaining[0]])
        if rest == remaining:
            break
        groups.append((remaining[0], remaining[1:len(remaining) - len(rest) - 1]))
        remaining = rest.strip()
    inputs = ()
    arity = None
    opening = {'op': '(', 'comb': '(', 'obs': '{', 'obj': '<'}.get(label)
    for group_opening, parameters in groups:
        if group_opening == opening:
            parts = _split_params(parameters)
            arity = len(parts) if label in ('op', 'comb', 'obs') else None
            inputs = tuple(part.split(':', 1)[1].strip() for part in parts if ':' in part)
            break
    output_match = re.match(r'\s*->\s*([A-Za-z_][\w]*(?:[<\[][\w, <>\[\]]+[>\]])?)', remaining)
    layer_match = re.search(r'\bL(\d+)\s*$', text)
    op_arity = (len(_split_params(next((body for opening, body in groups
                                       if opening == '['), ''))) if label == 'comb' else None)
    return {'name': name, 'kind': _KINDS[label], 'inputs': inputs,
            'arity': arity, 'output': output_match[1].strip() if output_match else None,
            'op_arity': op_arity,
            'layer': int(layer_match[1]) if layer_match else None,
            'given': given, 'groups': tuple(groups), 'remainder': remaining}


def _skip_group(text: str, opening: str, closing: str) -> str:
    depth = 0
    for index, char in enumerate(text):
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if not depth:
                return text[index + 1:]
    return text


def _split_params(text: str) -> list[str]:
    parts = []
    depth = 0
    start = 0
    index = 0
    while index < len(text):
        if text.startswith('->', index):
            index += 2
            continue
        char = text[index]
        if char in '([{<':
            depth += 1
        elif char in ')]}>':
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
        index += 1
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


def _family(glyph: str) -> str:
    if glyph in _OBJECTS:
        return 'bb' + glyph
    return n3.GLYPHS.get(glyph, glyph)


def _expr(mark: n3.Mark) -> n3.Expr:
    return n3.Expr('mg', (mark, ()))


def _sign_ref(sign: str) -> n3.Expr:
    """A given BIN sign used as an operation value: ``(+)``."""
    return n3.Expr('group', ((n3.Expr('binref', (sign,)),),))


def _sort_key(name: str) -> str:
    if name.lower() in ('int', 'integer'):
        return 'int'
    if name.lower() == 'bool':
        return 'bool'
    if name.lower() == 'list' or name.lower().startswith('list[') or name.lower().startswith('list<'):
        return 'list'
    return name


class Legend:
    def __init__(self, entries: Iterable[LegendEntry]):
        self.entries = tuple(entries)
        self._names = {(entry.atom.name, entry.atom.kind): entry for entry in self.entries}
        if len(self._names) != len(self.entries):
            raise ValueError('duplicate atom name and kind')
        self._sorts = {}
        self._aliases = defaultdict(list)
        for entry in self.entries:
            if entry.atom.kind == 'object':
                self._sorts.setdefault(_sort_key(entry.atom.name), entry)
                self._aliases[entry.atom.name.lower()].append(entry)

    def by_name(self, name: str, kind: str | None = None) -> LegendEntry:
        if kind is not None:
            if (name, kind) in self._names:
                return self._names[(name, kind)]
            if kind == 'object':
                aliases = self._aliases.get(name.lower(), ())
                if len(aliases) == 1:
                    return aliases[0]
            template = self._names.get((name, 'template'))
            if template and template.atom.produces == kind:
                return template
            if kind == 'object' and _sort_key(name) in self._sorts:
                return self._sorts[_sort_key(name)]
            if kind == 'object' and _sort_key(name) in ('int', 'bool', 'list'):
                self.sort_mark(name)
                return self._sorts[_sort_key(name)]
            raise KeyError((name, kind))
        matches = [entry for (atom_name, _), entry in self._names.items() if atom_name == name]
        if len(matches) != 1:
            if not matches and _sort_key(name) in self._sorts:
                return self._sorts[_sort_key(name)]
            raise KeyError(name)
        return matches[0]

    def declared_kind(self, name: str) -> str:
        matches = {entry.atom.kind for entry in self.entries if entry.atom.name == name}
        if not matches:
            raise KeyError(name)
        if 'operation' in matches:
            return 'operation'  # an unsigiled call names the operation when one is declared
        if len(matches) > 1:
            raise ValueError(f'ambiguous atom {name!r}: {sorted(matches)}')
        return next(iter(matches))

    def mark_expr(self, name: str, kind: str | None = None) -> n3.Expr | None:
        mark = self.by_name(name, kind).mark
        return _expr(mark) if mark is not None else None

    def binsign(self, name: str) -> str | None:
        try:
            return self.by_name(name, 'operation').binsign
        except KeyError:
            return None

    def declared_sort(self, sort_name: str) -> LegendEntry | None:
        """The declared object (or object template) named by a sort, without adding one."""
        template = self._names.get((sort_name, 'template'))
        if template and template.atom.produces == 'object':
            return template
        if (sort_name, 'object') in self._names:
            return self._names[(sort_name, 'object')]
        aliases = self._aliases.get(sort_name.lower(), ())
        if len(aliases) == 1:
            return aliases[0]
        return self._sorts.get(_sort_key(sort_name))

    def sort_mark(self, sort_name: str) -> n3.Expr:
        template = self._names.get((sort_name, 'template'))
        if template and template.atom.produces == 'object':
            return _expr(template.mark)
        aliases = self._aliases.get(sort_name.lower(), ())
        if len(aliases) == 1 and (sort_name, 'object') not in self._names:
            return _expr(aliases[0].mark)
        key = _sort_key(sort_name)
        if key in self._sorts:
            return _expr(self._sorts[key].mark)
        if key in ('int', 'bool'):
            mark = n3.Mark(None, 'bbZ' if key == 'int' else 'bbB')
            entry = LegendEntry(Atom(sort_name, 'object', 0, 'given'), mark, None,
                                n3.show(mark), n3.show(mark, ascii=True), None)
            self.entries += (entry,)
            self._names[(sort_name, 'object')] = entry
            self._sorts[key] = entry
            self._aliases[sort_name.lower()].append(entry)
            return _expr(mark)
        used = {entry.mark.family for entry in self.entries if entry.atom.kind == 'object'
                and entry.mark is not None and entry.mark.index_kind == 'given'}
        choices = ''.join(letter for letter in _OBJECTS if letter not in 'BZ')
        glyph = next((letter for letter in choices if 'bb' + letter not in used), None)
        if glyph is None:
            used_indices = {entry.mark.index_value for entry in self.entries
                            if entry.atom.kind == 'object' and entry.mark is not None
                            and entry.mark.index_kind == 'given_num'}
            index = 1
            while '0' + str(index) in used_indices or any(entry.mark is not None and
                                                entry.mark.family == 'bbA' and
                                                entry.mark.index_value == '0' + str(index)
                                                for entry in self.entries):
                index += 1
            mark = n3.Mark(None, 'bbA', index_kind='given_num', index_value='0' + str(index))
        else:
            mark = n3.Mark(None, 'bb' + glyph)
        atom = Atom(sort_name, 'object', 0, 'given')
        entry = LegendEntry(atom, mark, None, n3.show(mark), n3.show(mark, ascii=True), None)
        self.entries += (entry,)
        self._names[(sort_name, 'object')] = entry
        self._sorts[key] = entry
        self._aliases[sort_name.lower()].append(entry)
        return _expr(mark)

    def single_form(self, sort_name: str) -> bool:
        entry = self._sorts.get(_sort_key(sort_name))
        return entry is not None and len(entry.atom.forms) == 1

    def constructor_mark(self, sort_name: str, tag: str) -> n3.Expr:
        return self.mark_expr(f'{sort_name}.{tag}', 'operation')

    def to_json(self) -> list[dict]:
        return [{'mark': entry.ascii, 'display': entry.display,
                 'name': entry.atom.name, 'kind': entry.atom.kind,
                 'layer': entry.atom.layer, 'origin': entry.atom.origin,
                 **({'forms': list(entry.atom.forms)} if entry.atom.kind == 'object' else {}),
                 **({'form_of': entry.atom.form_of} if entry.atom.form_of else {}),
                 **({'note': entry.atom.note} if entry.atom.note else {}),
                 **({'produces': entry.atom.produces} if entry.atom.kind == 'template' else {}),
                 'signature': ({'ascii': n3.show(entry.signature, ascii=True),
                                'display': n3.show(entry.signature)}
                               if entry.signature else None)} for entry in self.entries]

    @classmethod
    def from_json(cls, rows: list[dict]) -> Legend:
        entries = []
        for row in rows:
            parsed = n3.parse_expr(row['mark'])
            sign = parsed.args[0][0].args[0] if parsed.tag == 'group' else None
            mark = None if sign else parsed.args[0].args[0]
            signature = n3.parse(row['signature']['ascii']) if row['signature'] else None
            atom = Atom(row['name'], row['kind'], row['layer'], row['origin'],
                        forms=tuple(row.get('forms', ())), form_of=row.get('form_of'),
                        note=row.get('note'), produces=row.get('produces'))
            entries.append(LegendEntry(atom, mark, sign, row['display'], row['mark'], signature))
        return cls(entries)


def assign(atoms: Iterable[Atom]) -> Legend:
    source = list(atoms)
    source = _canonical_atoms(source)
    aliases = set()
    distinct = []
    for atom in source:
        key = _sort_key(atom.name) if atom.kind == 'object' else None
        if key in ('int', 'bool', 'list'):
            if key in aliases:
                continue
            aliases.add(key)
        distinct.append(atom)
    source = distinct
    constructors = []
    for atom in source:
        if atom.kind == 'object' and len(atom.forms) > 1:
            declared = dict(atom.form_fields)
            # A capitalised form never seen with fields is a constant (E, P1), not an atom.
            constructors.extend(Atom(f'{atom.name}.{tag}', 'operation', atom.layer, atom.origin,
                                     arity=len(declared.get(tag, ())), form_of=atom.name)
                                for tag in atom.forms
                                if declared.get(tag) or tag in atom.valued_forms or
                                not re.fullmatch(r'[A-Z][A-Za-z0-9_]*', tag))
    constructor_names = {constructor.name for constructor in constructors}
    source = [atom for atom in source if atom.name not in constructor_names or
              atom.kind not in ('object', 'operation')]
    source.extend(constructors)
    if any(atom.layer < 0 or atom.kind not in
           ('object', 'operation', 'combinator', 'observation', 'law', 'bridge', 'template')
           for atom in source):
        raise ValueError('invalid atom kind or layer')
    given = [atom for atom in source if atom.origin == 'given']
    defined = [atom for atom in source if atom.origin != 'given']
    defined.sort(key=lambda atom: atom.layer)
    existing_sorts = {_sort_key(atom.name) for atom in source if atom.kind == 'object'}
    existing_sorts.update(_sort_key(atom.name) for atom in source
                          if atom.kind == 'template' and atom.produces == 'object')
    # A signature sort is never an atom of its own: the legend lists only declared atoms, so
    # a sort no declaration names (a type expression such as Pair<Int, Int>, or a word of
    # design text) adds no entry; the atom then shows no signature (see _signature_sort).
    if any(_sort_key(sort) == 'list' for atom in source
           for sort in (*atom.inputs, *((atom.output,) if atom.output else ()))) and \
            'list' not in existing_sorts:
        existing_sorts.add('list')
        given.append(Atom('List', 'object', 0, 'given'))
    used_glyphs: dict[str, set[str]] = defaultdict(set)
    overflow: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    occupied: set[str] = set()
    occupied_indices: set[tuple[str, str]] = set()
    preliminary = []

    def candidates(atom: Atom) -> str:
        kind = (atom.produces or 'object') if atom.kind == 'template' else atom.kind
        if kind == 'object':
            if _sort_key(atom.name) == 'int':
                return 'Z' + _OBJECTS
            if _sort_key(atom.name) == 'bool':
                return 'B' + ''.join(letter for letter in _OBJECTS if letter != 'B')
            # Each kind uses only its own families, in table order; atoms of one kind are
            # told apart by their index, never by the initial of their name.
            return ''.join(letter for letter in _OBJECTS if letter not in 'BZ')
        if kind == 'operation':
            return _OPS
        if kind == 'combinator':
            return _COMBS
        if kind == 'observation':
            return _HATS
        if kind == 'law':
            return '≡'
        if kind == 'bridge':
            return '↝'
        raise ValueError(f'unknown produced kind: {kind}')

    for atom in (*given, *defined):
        sign = (_SIGNS.get(atom.name) if atom.origin == 'given' and atom.kind == 'operation'
                and atom.arity == (1 if atom.name == 'not' else 2) else None)
        mark = None
        if sign is None:
            kind = atom.kind
            available = candidates(atom)
            if atom.origin == 'given':
                glyph = next((item for item in available if item not in used_glyphs[kind]), None)
                if glyph is None:
                    overflow[kind] += 1
                    overflow_family = '♦' if kind == 'operation' else available[0]
                    mark = n3.Mark(None, _family(overflow_family), index_kind='given_num',
                                   index_value='0' + str(overflow[kind]))
                else:
                    mark = n3.Mark(None, _family(glyph))
                    used_glyphs[kind].add(glyph)
            else:
                counts[kind] += 1
                index = counts[kind]
                if ((atom.produces or 'object') if kind == 'template' else kind) == 'operation':
                    choices = _ARITY.get(atom.arity, _NARY)
                    glyph = choices[(index - 1) % len(choices)]
                else:
                    glyph = available[(index - 1) % len(available)]
                mark = n3.Mark(None, _family(glyph), index_kind='def', index_value=index)
            while (n3.show(mark) in occupied or
                   mark.index_kind in ('def', 'given_num') and
                   (mark.family, str(mark.index_value)) in occupied_indices):
                if atom.origin == 'given':
                    overflow[kind] += 1
                    mark = replace(mark, layer=None, index_kind='given_num',
                                   index_value='0' + str(overflow[kind]))
                else:
                    counts[kind] += 1
                    mark = replace(mark, index_value=counts[kind])
            occupied.add(n3.show(mark))
            if mark.index_kind in ('def', 'given_num'):
                occupied_indices.add((mark.family, str(mark.index_value)))
        preliminary.append((atom, mark, sign))
    legend = Legend(LegendEntry(atom, mark, sign, n3.show(mark or _sign_ref(sign)),
                                n3.show(mark or _sign_ref(sign), ascii=True), None)
                    for atom, mark, sign in preliminary)
    entries = []
    for atom, mark, sign in preliminary:
        signature = None
        slots: dict[str, str] = {}
        sorts = [_signature_sort(legend, sort, slots)
                 for sort in (*atom.inputs, *((atom.output,) if atom.output else ()))]
        if atom.output and atom.inputs and all(sort is not None for sort in sorts):
            terms = [n3.Expr('bare', (sort,)) for sort in sorts[:-1]]
            domain = terms[0]
            for term in terms[1:]:
                domain = n3.Expr('bin', ('x*', domain, term))
            target = n3.Expr('bare', (sorts[-1],))
            head = (_sign_ref(sign) if sign else
                    n3.Expr('bare', (_expr(replace(mark, layer=atom.layer)
                                            if atom.origin != 'given' and atom.layer > 0 else mark),)))
            signature = n3.Stmt('sig', (head, n3.Expr('arrow', (domain, target)), None))
        if atom.note and atom.note.startswith(CONSTRUCTOR_NOTE):
            target = legend.by_name(atom.note[len(CONSTRUCTOR_NOTE):], 'object')
            atom = replace(atom, note=CONSTRUCTOR_NOTE + target.display)
        entries.append(LegendEntry(atom, mark, sign, n3.show(mark or _sign_ref(sign)),
                                   n3.show(mark or _sign_ref(sign), ascii=True), signature))
    return Legend(entries)


def _signature_sort(legend: Legend, sort: str, slots: dict[str, str]) -> n3.Expr | None:
    """The mark of a signature sort, or None when no declared atom is that sort.

    Builtin Int and Bool keep their fixed marks, a List type shows the List sort, a one-letter
    type variable is a slot (𝕏ₐ, 𝕏ₑ, ... in order of appearance), and a generic type shows its
    declared head sort. Anything else (unions, arrows, words of design text) has no mark.
    """
    sort = sort.strip()
    key = _sort_key(sort)
    if key in ('int', 'bool', 'list'):
        return legend.sort_mark(sort)
    head = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)(?:<.*>|\[.*\])?', sort, re.DOTALL)
    if head is None:
        return None
    entry = legend.declared_sort(head[1])
    if entry is not None:
        return _expr(entry.mark)
    if re.fullmatch(r'[A-Z]', sort):
        letters = [letter for letter in n3.SLOT if letter not in slots.values()]
        if sort not in slots and letters:
            slots[sort] = letters[0]
        if sort in slots:
            return _expr(n3.Mark(None, 'bbX', index_kind='slot', index_value=slots[sort]))
    return None


def _atom(data: dict, *, layer: int | None = None, kind: str | None = None) -> Atom:
    spec = data.get('spec') if isinstance(data.get('spec'), dict) else data
    text = next((data[key] for key in ('decl', 'ascii', 'declaration', 'design_decl')
                 if isinstance(data.get(key), str)), None)
    header = declaration_header(text or '')
    kind = kind or data.get('kind') or (header['kind'] if header else None)
    if kind is None:
        raise ValueError('missing atom kind')
    # worlds_v2 story rows keep the display row in 'layer' and the dependency layer in
    # 'def_layer' (export_util.finalize_export); the legend uses the dependency layer.
    layer = int(data.get('def_layer', data.get('layer', layer if layer is not None else
                         (header['layer'] if header and header['layer'] is not None else 0))))
    inputs = spec.get('inputs', ())
    if inputs and isinstance(inputs[0], dict):
        inputs = tuple(item['sort'] for item in inputs)
    else:
        inputs = tuple(inputs)
    output = spec.get('output')
    if isinstance(output, dict):
        output = output.get('sort')
    if kind == 'observation':
        inputs = inputs or ((spec['subject'],) if 'subject' in spec and spec['subject'] != 's' else ())
        output = output or spec.get('sort')
    if kind == 'bridge':
        source = spec.get('source')
        target = spec.get('target')
        inputs = ((source[-1] if isinstance(source, (list, tuple)) else source),) if source else inputs
        output = output or (target[-1] if isinstance(target, (list, tuple)) else target)
    tags = spec.get('tags')
    forms = tuple(tags) if isinstance(tags, dict) else ()
    form_fields = tuple((tag, tuple(fields) if isinstance(fields, dict) else
                         tuple(field[0] for field in fields))
                        for tag, fields in tags.items()) if isinstance(tags, dict) else ()
    arity = data.get('arity', len(inputs) if inputs else None)
    op_params = spec.get('op_params', data.get('op_params'))
    op_arity = len(op_params) if op_params is not None else None
    if kind == 'combinator' and arity is None and spec.get('params'):
        arity = len(spec['params']) - len(spec.get('op_params', ()))
    if header:
        inputs = inputs or header['inputs']
        output = output or header['output']
        arity = arity if arity is not None else header['arity']
        op_arity = op_arity if op_arity is not None else header['op_arity']
    definition = None
    if text:
        try:
            definition = notation.parse_definition(text)
        except (ValueError, TypeError):
            pass
    if definition is not None:
        layer = definition.layer
        if not inputs or not output or arity is None or not forms:
            parsed = definition.spec
            if kind == 'operation':
                inputs = inputs or tuple(edge.sort for edge in parsed.inputs)
                output = output or parsed.output.sort
            elif kind == 'object' and not forms and getattr(parsed, 'tags', None):
                forms = tuple(parsed.tags)
                form_fields = tuple((tag, tuple(field[0] for field in fields))
                                    for tag, fields in parsed.tags.items())
            elif kind == 'bridge':
                inputs = inputs or (parsed.source,)
                output = output or parsed.target
            elif kind == 'combinator' and arity is None:
                arity = len(parsed.params) - len(parsed.op_params)
            if arity is None and kind == 'operation':
                arity = len(inputs)
        if kind == 'combinator' and op_arity is None:
            op_arity = len(definition.spec.op_params)
    name = data.get('name') or (header['name'] if header else None)
    if name is None:
        raise ValueError('missing atom name')
    if name.startswith(('@', '?', '#', '~')):
        name = name[1:]
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?(?::[0-9a-f]+)?', name):
        # A record named by an example (split(Word<...>)) is the atom its declaration names.
        leading = re.match(r'[A-Za-z_]\w*', name)
        name = header['name'] if header else leading[0] if leading else name
    pattern = spec.get('pattern')
    produces = spec.get('produces') or (pattern.get('produces') if isinstance(pattern, dict) else None)
    if kind == 'template' and not produces:
        symbol = data.get('symbol', '')
        produces = ('object' if symbol[:1].isupper() else
                    {'@': 'combinator', '?': 'observation', '#': 'law', '~': 'bridge'}.get(
                        symbol[:1], 'operation'))
    return Atom(name, kind, layer, 'given' if layer == 0 else 'invented',
                arity, inputs, output, forms, produces, op_arity,
                form_fields=form_fields)


def _layer0(value) -> list[Atom]:
    if isinstance(value, list):
        return [_atom(item, layer=0, kind='operation') for item in value]
    result = []
    for field, kind in (('objects', 'object'), ('operations', 'operation'),
                        ('combinators', 'combinator'), ('observation', 'observation'),
                        ('observations', 'observation')):
        items = value.get(field, ())
        if isinstance(items, dict):
            items = items.get('library' if kind == 'combinator' else 'probes', ())
        result.extend(_atom(item if isinstance(item, dict) else {'name': item},
                            layer=0, kind=kind) for item in items
                      if isinstance(item, str) or 'name' in item or 'decl' in item)
    return result


def _header_sorts(header: dict) -> tuple[str, ...]:
    """Input and output sorts of a machine declaration header (a tuple output included)."""
    output = header['output']
    if output is None and header['remainder'].startswith('->'):
        output = re.split(r' = | where ', header['remainder'][2:], maxsplit=1)[0]
        output = re.sub(r'\s+(?:L\d+|given)\s*$', '', output).strip() or None
    # A machine object defined as an instance of another sort (obj State = Pair<...> given)
    # names that head sort; the rest of the body is not read.
    head = (re.match(r'=\s*([A-Z][A-Za-z_0-9]*)\s*[<\[]', header['remainder'])
            if header['kind'] == 'object' and '|' not in header['remainder'] else None)
    return (*header['inputs'], *((output,) if output else ()), *((head[1],) if head else ()))


def _export_references(export_dict: dict) -> list[Atom]:
    """Collect actual declaration headers and their signature sorts."""
    result = []

    def walk(value):
        if isinstance(value, dict):
            for key in sorted(value):
                if key == 'notation3':
                    continue
                item = value[key]
                # Only machine declarations name atoms; design text ('design_decl') never does.
                if isinstance(item, str) and key in ('decl', 'ascii', 'declaration', 'definition'):
                    try:
                        definition = notation.parse_definition(item)
                    except (ValueError, TypeError):
                        definition = None
                    header = declaration_header(item)
                    if definition or header:
                        name = definition.name if definition else header['name']
                        kind = definition.kind if definition else header['kind']
                        layer = definition.layer if definition else header['layer'] or 0
                        result.append(Atom(name, kind, layer,
                                           'given' if layer == 0 else 'invented',
                                           header['arity'] if header else None,
                                           header['inputs'] if header else (),
                                           header['output'] if header else None,
                                           op_arity=header['op_arity'] if header else None))
                        sorts = _header_sorts(header) if header else ()
                        # A union of constants (M1|M2|M3) names values, not sorts.
                        for sort in (sort for sort in sorts if '|' not in sort):
                            for name in re.findall(r'\b[A-Z][A-Za-z_0-9]*\b', sort):
                                if len(name) > 1 and not name.startswith('__opulse_'):
                                    result.append(Atom(name, 'object', 0, 'given'))
                            if re.fullmatch(r'[a-z][A-Za-z_0-9]+', sort):
                                result.append(Atom(sort, 'object', 0, 'given'))
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            header = declaration_header(value)
            if header and header['given']:
                result.append(Atom(header['name'], header['kind'], 0, 'given',
                                   header['arity'], header['inputs'], header['output'],
                                   op_arity=header['op_arity']))
                for sort in _header_sorts(header):
                    if '|' in sort:
                        continue
                    for name in re.findall(r'\b[A-Z][A-Za-z_0-9]*\b', sort):
                        if len(name) > 1:
                            result.append(Atom(name, 'object', 0, 'given'))
                    if re.fullmatch(r'[a-z][A-Za-z_0-9]+', sort):
                        result.append(Atom(sort, 'object', 0, 'given'))

    walk(export_dict)
    return result


def _complete(atoms: list[Atom], export_dict: dict) -> list[Atom]:
    declared = _unique(atoms)
    observed: dict[str, list[str]] = defaultdict(list)
    valued: dict[str, list[str]] = defaultdict(list)
    trace_atoms: list[Atom] = []
    local_names = set()
    machine_texts = []
    part_calls: dict[str, int] = {}
    kinds = {'object', 'operation', 'combinator', 'observation', 'law', 'bridge'}

    def walk(value):
        if isinstance(value, dict):
            if value.get('node') == 'Rec' and isinstance(value.get('fn'), str):
                local_names.add(value['fn'])
            if (value.get('node') == 'Call' and isinstance(value.get('fn'), str) and
                    re.fullmatch(r'[A-Za-z_]\w*\.[A-Za-z_]\w*', value['fn'])):
                part_calls.setdefault(value['fn'], len(value.get('args') or ()))
            if (isinstance(value.get('name'), str) and value.get('kind') in kinds and
                    ('given' in value or 'steps' in value)):
                name = value['name'].lstrip('?@~#')
                layer = int(value.get('layer') or 0)
                # 'Sort.part' frames run an object's machinery (make, canon, store, check);
                # they are not atoms of their own (constructor atoms come from declared forms).
                if not name.startswith('__opulse_') and '.' not in name:
                    trace_atoms.append(Atom(name, value['kind'], layer,
                                            'given' if value.get('given') or layer == 0 else 'invented'))
            if isinstance(value.get('t'), str) and not value['t'].startswith('__opulse_'):
                trace_atoms.append(Atom(value['t'], 'object', 0, 'given'))
            if value.get('t') and isinstance(value.get('tag'), str):
                observed[value['t']].append(value['tag'])
                if value.get('f'):
                    valued[value['t']].append(value['tag'])
            for key, item in value.items():
                if key == 'notation3':
                    continue
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            machine_texts.append(value)
            for match in re.finditer(r'\b([A-Z][A-Za-z_0-9]*)\.([A-Za-z_][A-Za-z_0-9]*)\s*<(\s*>)?', value):
                observed[match[1]].append(match[2])
                if not match[3]:
                    valued[match[1]].append(match[2])

    walk(export_dict)
    for text in machine_texts:
        local_names.update(re.findall(r'\b(?:memo\s+)?rec\s+([a-z][A-Za-z_0-9]*)\s*\(', text))
    # Observed forms are sorted: the walk order follows key order, which differs between an
    # in-memory export and its serialized file.
    declared = [replace(atom, forms=tuple(sorted(set(observed.get(atom.name, ())))))
                if atom.kind == 'object' and not atom.forms and atom.name in observed else atom
                for atom in declared]
    declared = [replace(atom, valued_forms=tuple(sorted(set(valued[atom.name]))))
                if atom.kind == 'object' and atom.name in valued else atom for atom in declared]
    known = {(atom.name, atom.kind) for atom in declared}
    known.update((atom.name, atom.produces) for atom in declared
                 if atom.kind == 'template' and atom.produces)
    sorts = {_sort_key(atom.name).lower() for atom in declared if atom.kind == 'object'}
    referenced = []
    for atom in (*_export_references(export_dict),
                 # Sorted: the walk follows key order, which differs between an in-memory
                 # export and its serialized (sort_keys) file.
                 *sorted((atom for atom in trace_atoms if atom.name not in local_names),
                         key=lambda atom: (atom.name, atom.kind, atom.layer, atom.origin))):
        if (atom.name, atom.kind) not in known and not (atom.kind == 'object' and
                                                       _sort_key(atom.name).lower() in sorts):
            known.add((atom.name, atom.kind))
            referenced.append(replace(atom, forms=tuple(sorted(set(observed[atom.name]))),
                                      valued_forms=tuple(sorted(set(valued[atom.name]))))
                              if atom.kind == 'object' and atom.name in observed else atom)
            if atom.kind == 'object':
                sorts.add(_sort_key(atom.name).lower())
    # A machine call of an object's own operation other than its constructor (Xor.base
    # unwraps a refinement, BeliefPair.b reads a field) is an operation atom of that object,
    # with the object's layer and origin; make and the declared forms construct the object.
    objects = {atom.name: atom for atom in (*declared, *referenced) if atom.kind == 'object'}
    for name in sorted(part_calls):
        sort, part = name.split('.', 1)
        owner = objects.get(sort)
        if (owner is None or part == 'make' or part in owner.forms or
                (name, 'operation') in known):
            continue
        known.add((name, 'operation'))
        referenced.append(Atom(name, 'operation', owner.layer, owner.origin, part_calls[name]))
    return _canonical_atoms([*declared, *referenced])


def _canonical_atoms(complete: list[Atom]) -> list[Atom]:
    # The glyph family tells the kind, so a layer-0 operation keeps its own operation mark
    # even when the world also declares a probe or an object of the same name; an operation
    # named like a declared object is noted as that object's constructor.
    objects = {atom.name for atom in complete if atom.kind == 'object'}
    templates = {atom.name for atom in complete if atom.kind == 'template'}
    return [replace(atom, note=CONSTRUCTOR_NOTE + atom.name)
            if atom.kind == 'operation' and atom.name in objects and not atom.note else atom
            for atom in complete if not (atom.kind == 'object' and atom.name in templates)]


CONSTRUCTOR_NOTE = 'constructor of '


def _design_record(record: dict, text: str) -> bool:
    """A record whose declaration is design text proposes its dependencies; none is checked."""
    if not text:
        return isinstance(record.get('design_decl'), str)
    header = declaration_header(text)
    if header is not None and header['given']:
        return False
    try:
        notation.parse_definition(text)
    except (ValueError, TypeError):
        return True
    return False


def validate_dependencies(atoms: list[Atom], export_dict: dict) -> None:
    declared_kinds = {(atom.name, atom.kind) for atom in atoms}
    templates = {(atom.name, atom.produces) for atom in atoms
                 if atom.kind == 'template' and atom.produces}
    objects = {atom.name: atom for atom in atoms if atom.kind == 'object'}
    dependencies = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'notation3':
                    continue
                if key in ('depends_on', 'dependencies') and isinstance(item, list):
                    text = next((value[field] for field in ('decl', 'declaration', 'definition')
                                 if isinstance(value.get(field), str)), '')
                    if not _design_record(value, text):
                        dependencies.extend((name, key, text) for name in item if isinstance(name, str))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(export_dict)
    sigils = {'?': 'observation', '@': 'combinator', '#': 'law', '~': 'bridge'}
    missing = []
    for name, field, text in dict.fromkeys(dependencies):
        kind = sigils.get(name[:1])
        bare = name[1:] if kind else name
        if '.' in bare:
            sort, tag = bare.split('.', 1)
            valid = (sort in objects and tag in objects[sort].forms and
                     len(objects[sort].forms) > 1) or sort in objects
        else:
            valid = any(atom_name == bare and (kind is None or atom_kind == kind)
                        for atom_name, atom_kind in declared_kinds | templates) or (
                            kind is None and bare in ('Int', 'int', 'Bool', 'bool'))
        if not valid:
            missing.append(f'undeclared dependency {name!r} field={field!r} '
                           f'text={text!r} kind={kind or "unknown"!r}')
    if missing:
        raise ValueError('; '.join(missing))


def _template_atoms(export_dict: dict) -> list[Atom]:
    atoms = []
    kinds = {'?': 'observation', '@': 'combinator', '#': 'law', '~': 'bridge'}
    for template in export_dict.get('templates', ()):
        symbol = template.get('symbol', '')
        kind = kinds.get(symbol[:1], 'object' if symbol[:1].isupper() else 'operation')
        atoms.append(replace(_atom(template, kind='template'), produces=kind))
        atoms.extend(_atom(instance, kind=kinds.get(instance.get('symbol', '')[:1], kind))
                     for instance in template.get('instances', ()))
    return atoms


def atoms_from_worlds_v2(export_dict: dict) -> tuple[str, list[Atom]]:
    atoms = _layer0(export_dict['layer0'])
    atoms.extend(_layer0(export_dict.get('decl', {})))
    atoms.extend(_atom(item) for item in export_dict.get('story', ()))
    atoms.extend(_atom(item) for item in export_dict.get('support', ()))
    atoms.extend(_template_atoms(export_dict))
    tower = export_dict.get('tower_source')
    if isinstance(tower, (list, dict)):
        records = tower if isinstance(tower, list) else tower.get('definitions', ())
        atoms.extend(_atom(item) for item in records if isinstance(item, dict))
    return export_dict['world'], _complete(atoms, export_dict)


def _unique(atoms: Iterable[Atom]) -> list[Atom]:
    result = {}
    for atom in atoms:
        result.setdefault((atom.name, atom.kind), atom)
    return list(result.values())


def atoms_from_gen_v2(export_dict: dict) -> tuple[str, list[Atom]]:
    world = export_dict.get('world')
    if world is None:
        raise ValueError('gen_v2 export needs its world id')
    base = _ROOT / 'docs/assets/data/worlds_v2' / (world + '.json')
    atoms = _layer0(json.loads(base.read_text())['layer0']) if base.exists() else []
    atoms.extend(_atom(item) for item in export_dict.get('entries', ()))
    atoms.extend(_atom(item) for item in export_dict.get('story', ()))
    for key, kind in (('laws', 'law'), ('bridges', 'bridge'), ('templates', 'template')):
        items = export_dict.get(key, ())
        if isinstance(items, dict):
            items = items.get(key, ())
        atoms.extend(_atom(item, layer=1, kind=kind) for item in items)
    return world, _complete(atoms, export_dict)


DESIGN_PREFIX = 'design:'


def atoms_from_designs(design_bundle: dict) -> dict[str, list[Atom]]:
    """Legends for the catalog's world design records (docs/worlds/designs.json).

    Design towers propose atoms that no export defines, so each design gets its own legend
    world, ``design:<world>``, separate from the world's export legend.
    """
    result = {}
    for world in sorted(design_bundle.get('worlds', {})):
        entry = design_bundle['worlds'][world]
        rows = [row for row in entry.get('tower', ()) or () if isinstance(row, dict)
                and row.get('name') and row.get('kind')]
        atoms = [_atom(row) for row in rows]
        if atoms or entry.get('tower'):
            result[DESIGN_PREFIX + world] = _complete(atoms, entry)
    return result


def atoms_from_meta(export_dict: dict) -> tuple[str, list[Atom]]:
    atoms = _layer0(export_dict.get('layer0', {}))
    atoms.extend(_layer0(export_dict.get('decl', {})))
    atoms.extend(_atom(item) for item in export_dict.get('story', ()))
    atoms.extend(_template_atoms(export_dict))
    return export_dict['world'], _complete(atoms, export_dict)


def atoms_from_atoms2(name: str, export_dict: dict | str) -> tuple[str, list[Atom]] | dict[str, list[Atom]]:
    if isinstance(export_dict, str):
        start = export_dict.index('A2.kernelData=') + len('A2.kernelData=')
        export_dict = json.JSONDecoder().raw_decode(export_dict[start:])[0]
    if name == 'data.js':
        worlds: dict[str, list[Atom]] = defaultdict(list)

        def walk(node: dict, world: str) -> None:
            if node.get('def') and node.get('kind'):
                layer = int(node.get('layer', 0))
                worlds[world].append(Atom(node['def'], node['kind'], layer,
                                          'given' if layer == 0 else 'invented',
                                          len(node.get('args', ()))))
            for child in node.get('children', ()):
                walk(child, world)

        for record in export_dict.get('derivations', {}).values():
            walk(record['root'], record['world'])
        modes = export_dict.get('modes', {})
        for mode, record in modes.get('derivations', {}).items():
            # A combination-mode run is its own legend world, keyed by the mode (modes.js).
            walk(record['root'], mode)
        result = {world: _unique(atoms) for world, atoms in worlds.items()}
        for mode, record in modes.get('runs', {}).items():
            world = modes.get('derivations', {}).get(mode, {}).get('world', mode)
            layer0 = [Atom(item['name'], item['kind'], 0, 'given')
                      for item in modes.get('layer0', {}).get(world, ())]
            result[mode] = _complete([*result.get(mode, []), *layer0],
                                     {'run': record, 'derivation': modes.get('derivations', {}).get(mode, {})})
        for world, records in modes.get('layer0', {}).items():
            result[world] = _unique([*result.get(world, []), *(Atom(item['name'], item['kind'], 0, 'given')
                                                             for item in records)])
        for world, records in modes.get('definitions', {}).items():
            result[world] = _unique([*result.get(world, []), *(Atom(item['name'], item['kind'],
                item['layer'], 'invented') for item in records)])
        return result
    items = [*export_dict.get('tower', ()), *export_dict.get('definitions', ()),
             *export_dict.get('cards', ())]
    if isinstance(export_dict.get('definition'), dict):
        items.append(export_dict['definition'])
    elif isinstance(export_dict.get('definition'), str):
        items.append(_from_declaration(export_dict['definition']))
    if isinstance(export_dict.get('template'), dict) and export_dict['template'].get('definition'):
        items.append(_from_declaration(export_dict['template']['definition']))
    rows = export_dict.get('rows')
    if isinstance(rows, dict):
        for kind, records in rows.items():
            if isinstance(records, list):
                items.extend(dict(item, kind=kind) for item in records if isinstance(item, dict)
                             and 'name' in item)
    if isinstance(export_dict.get('law_and_bridge'), dict):
        items.extend(value for value in export_dict['law_and_bridge'].values()
                     if isinstance(value, dict) and 'name' in value)
    atoms = [*_layer0(export_dict.get('layer0', {})),
             *(_atom(item) for item in items if isinstance(item, dict) and item.get('name')
               and item.get('kind'))]
    return export_dict.get('world', export_dict.get('id', name)), _complete(atoms, export_dict)


def _from_declaration(text: str) -> dict:
    try:
        definition = notation.parse_definition(text)
    except (ValueError, TypeError):
        match = re.match(r'(obj|op|comb|obs|law|bridge|template)\s+[@?#~]?([A-Za-z_][A-Za-z0-9_]*)', text)
        if match is None:
            raise ValueError(f'invalid declaration: {text}') from None
        kind = {'obj': 'object', 'op': 'operation', 'comb': 'combinator',
                'obs': 'observation'}.get(match[1], match[1])
        layer = re.search(r'\bL([0-9]+)\s*$', text)
        return {'name': match[2], 'kind': kind, 'layer': int(layer[1]) if layer else 1,
                'declaration': text}
    return {'name': definition.name, 'kind': definition.kind, 'layer': definition.layer,
            'declaration': text}


def atoms_for_world(world_id: str) -> list[Atom]:
    name = world_id.split('@', 1)[0]
    for family, adapter in (('worlds_v2', atoms_from_worlds_v2),
                            ('gen_v2', atoms_from_gen_v2), ('meta', atoms_from_meta)):
        file = _ROOT / 'docs/assets/data' / family / (name + '.json')
        if file.exists():
            data = json.loads(file.read_text())
            if family == 'gen_v2':
                for suffix, key in (('.laws', 'laws'), ('.bridges', 'bridges'),
                                    ('.templates', 'templates')):
                    sibling = file.with_name(name + suffix + '.json')
                    if sibling.exists():
                        data[key] = json.loads(sibling.read_text()).get(key, [])
            return adapter(data)[1]
    raise KeyError(world_id)
