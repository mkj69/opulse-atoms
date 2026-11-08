"""One-way conversion from machine notation to the lossless v3 surface."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass

from opulse import notation3 as v3
from opulse.atoms import nodes as n
from opulse.atoms import notation
from opulse.atoms.kernel import FnRef
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.notation3.legend import declaration_header
from opulse.worlds_v2.export_util import parseable_declaration, parseable_expression

CONSTANT = re.compile(r'[A-Z][A-Za-z0-9_]*')


class ConversionError(ValueError):
    """Machine input has no honest v3 representation."""


class UndeclaredAtom(ConversionError):
    """A machine reference has no declaration of its machine kind."""

    def __init__(self, name, kind):
        self.name = name
        self.kind = kind
        super().__init__(f'undeclared {kind} atom {name!r}')


def _machine_kinds(text):
    tokens = [match.group() for match in notation._TOKEN.finditer(text)]
    kinds = {}
    for index, token in enumerate(tokens[:-1]):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', token):
            continue
        previous = tokens[index - 1] if index else ''
        following = tokens[index + 1]
        kind = ({'?': 'observation', '@': 'combinator', '~': 'bridge'}.get(previous)
                if following in ('{', '[', '(') else None)
        if kind is not None:
            kinds.setdefault(token, []).append(kind)
    return kinds


def _expr(tag, *args):
    return v3.Expr(tag, args)


def _group(expr):
    return _expr('group', (expr,))


def _mark(legend, name, kind):
    try:
        entry = legend.by_name(name, kind)
    except KeyError:
        raise UndeclaredAtom(name, kind) from None
    return entry.mark


def _mg(legend, name, kind, groups=()):
    sign = legend.binsign(name) if kind == 'operation' else None
    if sign and hasattr(legend, 'mark_expr') and legend.mark_expr(name, kind) is None:
        return _expr('binref', sign)
    return _expr('mg', _mark(legend, name, kind), tuple(groups))


def _declared_kind(legend, name):
    try:
        return legend.declared_kind(name)
    except KeyError:
        raise UndeclaredAtom(name, 'unknown') from None


def _call_kind(legend, name, kind):
    if kind == 'operation':
        try:
            legend.by_name(name, 'operation')
            return kind
        except KeyError:
            pass
        for equivalent in ('observation', 'object'):
            entry = legend._names.get((name, equivalent))
            if entry is None:
                continue
            if entry.atom.origin == 'given':
                return equivalent
    return kind


def _constructor(legend, sort, tag):
    return _mg(legend, f'{sort}.{tag}', 'operation')


def _variable(name):
    if not re.fullmatch(r'[a-z][A-Za-z0-9_]*', name) or name in v3.KEYWORDS:
        name += '_'
        if not re.fullmatch(r'[a-z][A-Za-z0-9_]*', name):
            name = 'v' + name.lstrip('_')
    return name


def _sort(sort, legend, slots=None):
    if sort in ('Int', 'int', 'Z'):
        return _expr('bare', _expr('mg', v3.Mark(None, 'bbZ'), ()))
    if sort in ('Bool', 'bool'):
        return _expr('bare', _expr('mg', v3.Mark(None, 'bbB'), ()))
    try:
        legend.by_name(sort, 'object')
    except KeyError:
        if re.fullmatch(r'[A-Z]', sort):
            # A one-letter type variable (A, B, C) is a slot; within one declaration each
            # variable keeps its own slot letter, in order of appearance (𝕏ₐ, 𝕏ₑ, 𝕏ₕ).
            letter = 'a'
            if slots is not None:
                if sort not in slots:
                    free = [item for item in v3.SLOT if item not in slots.values()]
                    slots[sort] = free[0] if free else 'a'
                letter = slots[sort]
            return _expr('bare', _expr('mg', v3.Mark(None, 'bbX', index_kind='slot',
                                                   index_value=letter), ()))
    return _expr('bare', legend.sort_mark(sort))


def context_for(legend):
    """Machine parser context for the atoms belonging to this world."""
    kinds = {entry.atom.name: entry.atom.kind for entry in legend.entries}
    kinds.update((entry.atom.name, 'operation') for entry in legend.entries
                 if entry.atom.kind == 'operation')
    return {
        'kinds': kinds,
        'op_arity': {entry.atom.name: entry.atom.op_arity for entry in legend.entries
                     if entry.atom.kind == 'combinator' and entry.atom.op_arity is not None},
        'infix': {entry.atom.name: notation._INFIX[entry.atom.name]
                  for entry in legend.entries if entry.atom.kind == 'operation'
                  and entry.atom.origin == 'given' and entry.atom.name in notation._INFIX
                  and entry.atom.arity == 2},
    }


_PRECEDENCE = {'or': 1, 'and': 2, '==': 3, '!=': 3, '<': 3,
               '<=': 3, '>': 3, '>=': 3, 'in': 3, 'seal': 4,
               '+': 5, '-': 5, '*': 6, '/': 6, '%': 6, 'x*': 7}


class _Converter:
    def __init__(self, legend, slots=None, machine_text=''):
        self.legend = legend
        self.slots = slots or {}
        self.recursive = {}
        self.bound = set()
        self.machine_kinds = _machine_kinds(machine_text)

    def atom(self, name, kind):
        if name in self.slots:
            return self.slots[name]
        if name in self.recursive:
            return self.recursive[name]
        return _mg(self.legend, name, kind)

    def _operand(self, expr, *, priority=0, right=False):
        if expr.tag == 'group':
            return expr
        if expr.tag == 'bin':
            level = _PRECEDENCE[expr.args[0]]
            if level < priority or right and level == priority:
                return _group(expr)
        elif (expr.tag in ('inf', 'pre') and priority >= 8 or
              expr.tag == 'post' and priority or
              expr.tag in ('let', 'rec', 'map') and priority or
              priority >= 8 and (expr.tag == 'bare' or
                                 expr.tag == 'num' and expr.args[0] < 0)):
            return _group(expr)
        return expr

    def call(self, name, args, *, head=False):
        if name in self.slots or name in self.recursive:
            kind = 'operation'
        else:
            references = self.machine_kinds.get(name, [])
            kind = references.pop(0) if references else _declared_kind(self.legend, name)
        kind = _call_kind(self.legend, name, kind)
        mark = self.atom(name, kind)
        values = tuple(self.node(arg) for arg in args)
        if name in self.recursive:
            return _expr('call', mark, '(', values)
        if kind == 'combinator':
            count = 0
            for arg in args:
                if (isinstance(arg, n.Lit) and isinstance(arg.value, FnRef) or
                        isinstance(arg, n.Var) and (arg.name in self.slots or
                                                     any(entry.atom.name == arg.name
                                                         for entry in self.legend.entries))):
                    count += 1
                else:
                    break
            atom_args = []
            for arg in args[:count]:
                if isinstance(arg, n.Lit) and isinstance(arg.value, FnRef):
                    sign = self.legend.binsign(arg.value.name)
                    atom_args.append(_expr('binref', sign) if sign else
                                     _expr('bare', _mg(self.legend, arg.value.name, 'operation')))
                elif isinstance(arg, n.Var) and arg.name in self.slots:
                    atom_args.append(_expr('bare', self.slots[arg.name]))
                elif isinstance(arg, n.Var):
                    atom_args.append(_expr('bare', _mg(self.legend, arg.name,
                                                       _declared_kind(self.legend, arg.name))))
                else:
                    raise ConversionError(f'combinator {name!r} requires atom slots')
            mark = _expr('mg', mark.args[0], (tuple(atom_args),))
            return _application(mark, values[count:], 'combinator')
        if kind == 'observation':
            return _expr('call', mark, '<|', values)
        if kind in ('bridge', 'object'):
            return _expr('call', mark, '(', values)
        sign = None if name in self.slots or name in self.recursive else self.legend.binsign(name)
        if sign and len(values) == 2:
            level = _PRECEDENCE[sign]
            left = self._operand(values[0], priority=level)
            right = self._operand(values[1], priority=level, right=True)
            return _expr('bin', sign, left, right)
        if sign == 'not' and len(values) == 1:
            return _expr('un', 'not', self._operand(values[0], priority=3))
        if len(values) == 1 and kind == 'operation' and mark.args[0].family == '@':
            return _expr('post', self._operand(values[0], priority=8), mark)
        if len(values) == 2 and kind == 'operation':
            return _expr('inf', self._operand(values[0], priority=8), mark,
                         _group(values[1]) if values[1].tag == 'list' else
                         self._operand(values[1], priority=8))
        if len(values) == 1 and kind == 'operation':
            if (values[0].tag in ('inf', 'bin', 'post', 'pre', 'let', 'rec', 'cases', 'group', 'list', 'bare')
                    or values[0].tag == 'num' and values[0].args[0] < 0):
                return _expr('call', mark, '(', values)
            return _expr('pre', mark, self._operand(values[0], priority=8))
        return _expr('call', mark, '(', values)

    def condition(self, node):
        if isinstance(node, n.Test):
            return self.node(node.expr)
        if isinstance(node, n.Always):
            return _expr('lit', 'top')
        if isinstance(node, n.Not):
            operand = self.condition(node.operand)
            return _expr('un', 'not', self._operand(operand, priority=3))
        if isinstance(node, (n.And, n.Or)):
            sign = 'and' if isinstance(node, n.And) else 'or'
            priority = _PRECEDENCE[sign]
            left = self._operand(self.condition(node.left), priority=priority)
            right = self._operand(self.condition(node.right), priority=priority, right=True)
            return _expr('bin', sign, left, right)
        raise ConversionError(f'unsupported condition: {type(node).__name__}')

    def node(self, node):
        if isinstance(node, n.Var):
            return _expr('var', _variable(node.name))
        if isinstance(node, n.Lit):
            if (isinstance(node.value, Card) and node.value.sort in self.bound and
                    node.value.tag == node.value.sort and not node.value.fields):
                return _expr('var', _variable(node.value.sort))
            return convert_value(node.value, self.legend)
        if isinstance(node, n.Call):
            return self.call(node.fn, node.args)
        if isinstance(node, n.Let):
            return _expr('let', _variable(node.name), self.node(node.value), self.node(node.body))
        if isinstance(node, n.Case):
            arms = [(self.node(body), self.condition(cond)) for cond, body in node.arms]
            default = node.default
            while isinstance(default, n.Case):
                arms.extend((self.node(body), self.condition(cond)) for cond, body in default.arms)
                default = default.default
            if default is None:
                raise ConversionError('case without default cannot be represented')
            arms.append((self.node(default), None))
            return _expr('cases', tuple(arms))
        if isinstance(node, n.Rec):
            slot = v3.Mark(None, 'dia', index_kind='slot', index_value='r')
            mark = _expr('mg', slot, ())
            old = self.recursive
            self.recursive = {**old, node.fn: mark}
            try:
                body = self.node(node.body)
                continuation = self.call(node.fn, node.args)
            finally:
                self.recursive = old
            measure = (_expr('measure', node.measure) if isinstance(node.measure, str) else
                       _expr('measure', 'dec', self.node(node.measure)))
            return _expr('rec', node.memo, mark, tuple(_expr('var', _variable(param)) for param in node.params),
                         body, measure, continuation)
        if isinstance(node, n.Blocks):
            labels = {label: label for label, _ in node.blocks}
            if any(not re.fullmatch(r'[A-Z][0-9]*', label) for label in labels):
                labels = {label: f'L{index}' for index, label in enumerate(labels)}
            blocks = []
            for label, block in node.blocks:
                if isinstance(block.end, n.Jump):
                    end = _expr('jump', labels[block.end.target])
                elif isinstance(block.end, n.Halt):
                    end = _expr('halt', self.node(block.end.value))
                elif isinstance(block.end, n.CondJump):
                    end = _expr('branch', self.condition(block.end.cond),
                                labels[block.end.then], labels[block.end.else_])
                else:
                    raise ConversionError('unknown program terminator')
                blocks.append(v3.Block(labels[label], tuple(v3.Assignment(_variable(name), self.node(value))
                                                            for name, value in block.assigns), end))
            return _expr('prog', tuple(v3.Assignment(_variable(name), self.node(value))
                                       for name, value in node.vars), labels[node.entry], tuple(blocks))
        if isinstance(node, (n.Test, n.And, n.Or, n.Not, n.Always)):
            return self.condition(node)
        raise ConversionError(f'unsupported node: {type(node).__name__}')


def convert_value(value, legend):
    """Render a host value (not a machine expression) as a v3 value."""
    if isinstance(value, Ok):
        return convert_value(value.value, legend)
    if isinstance(value, Bottom):
        return _expr('fail', convert_value(value.reason, legend))
    if isinstance(value, Unknown):
        return _expr('unknown', convert_value(value.resource, legend))
    if type(value) is bool:
        return _expr('lit', 'top' if value else 'bot')
    if type(value) is int:
        return _expr('num', value)
    if type(value) is str:
        if not value.isascii():
            raise ConversionError('v3 string must contain ASCII only')
        return _expr('str', value)
    if isinstance(value, tuple):
        return _expr('list', tuple(convert_value(item, legend) for item in value))
    if isinstance(value, FnRef):
        return _expr('bare', _mg(legend, value.name, _declared_kind(legend, value.name)))
    if isinstance(value, Card):
        if value.sort in ('int', 'Int') and value.tag == value.sort and len(value.fields) == 1:
            return convert_value(value.fields[0], legend)
        if value.sort in ('int', 'Int') and not value.fields and value.tag == value.sort:
            return _sort('int', legend)
        if value.sort in ('bool', 'Bool') and not value.fields and value.tag == value.sort:
            return _sort('bool', legend)
        if value.sort == 'bool' and value.tag in ('true', 'false') and not value.fields:
            return _expr('lit', 'top' if value.tag == 'true' else 'bot')
        if value.sort == 'List' and value.tag == 'List':
            return _expr('list', tuple(convert_value(item, legend) for item in value.fields))
        if not value.fields and CONSTANT.fullmatch(value.tag):
            if value.sort == value.tag:
                try:
                    legend.by_name(value.sort, 'object')
                except KeyError:
                    pass
                else:
                    return _expr('bare', _mg(legend, value.sort, 'object'))
            return _expr('const', value.tag)  # a nullary capitalised form is a constant (E, P1, Metro)
        mark = _mg(legend, value.sort, 'object')
        if value.tag != value.sort and not legend.single_form(value.sort) and len(legend.by_name(value.sort, 'object').atom.forms) > 1:
            mark = _constructor(legend, value.sort, value.tag)
        fields = tuple(convert_value(item, legend) for item in value.fields)
        names = dict(legend.by_name(value.sort, 'object').atom.form_fields).get(value.tag, ())
        if len(names) == len(fields):
            fields = tuple(_expr('field', _variable(name), field)
                           for name, field in zip(names, fields))
        return _expr('call', mark, '(', fields)
    raise ConversionError(f'unsupported value: {type(value).__name__}')


def _body(node, converter):
    if (isinstance(node, n.Case) and len(node.arms) == 1 and
            isinstance(node.arms[0][1], n.Lit) and type(node.arms[0][1].value) is bool and
            node.arms[0][1].value is True and isinstance(node.default, n.Lit) and
            type(node.default.value) is bool and node.default.value is False):
        return _expr('brace', converter.condition(node.arms[0][0]))
    return _expr('brace', converter.node(node))


def convert_definition(defn, legend, ctx=None, machine_text=''):
    """Return separate signature and formula statements for a machine definition."""
    spec = defn.spec
    converter = _Converter(legend, machine_text=machine_text.split(' = ', 1)[-1]
                           if ' = ' in machine_text else machine_text)
    name = defn.name
    try:
        mark = _mg(legend, name, _call_kind(legend, name, defn.kind))
    except ConversionError:
        if defn.kind == 'object' and name in ('Bool', 'bool', 'Int', 'int'):
            mark = legend.sort_mark(name)
        elif defn.kind != 'template':
            raise
        else:
            mark = _mg(legend, name, spec.produces)
    signature = None
    if defn.kind == 'operation':
        params = tuple(n.Var(edge.name) for edge in spec.inputs)
        head = converter.call(name, params, head=True)
        sorts = [_sort(edge.sort, legend) for edge in spec.inputs]
        domain = sorts[0] if len(sorts) == 1 else _fold('x*', sorts) if sorts else _expr('group', ())
        signature_head = (_group(mark) if mark.tag == 'binref' else
                          _expr('bare', _expr('mg', v3.Mark(defn.layer, mark.args[0].family,
                                                            mark.args[0].kind_number,
                                                            mark.args[0].index_kind,
                                                            mark.args[0].index_value), ())))
        signature = v3.Stmt('sig', (signature_head,
                                     _expr('arrow', domain, _sort(spec.output.sort, legend)), None))
    elif defn.kind == 'combinator':
        slots = {}
        for index, op_name in enumerate(spec.op_params):
            slot_index = list(v3.SLOT)[index % len(v3.SLOT)] + (str(index // len(v3.SLOT) + 1)
                                                               if index >= len(v3.SLOT) else '')
            slots[op_name] = _expr('mg', v3.Mark(None, 'dia', index_kind='slot', index_value=slot_index), ())
        converter.slots = slots
        converter.bound.update(spec.params)
        mark = _expr('mg', mark.args[0], (tuple(_expr('bare', slots[name]) for name in spec.op_params),))
        args = tuple(n.Var(name) for name in spec.params if name not in spec.op_params)
        head = _application(mark, tuple(converter.node(arg) for arg in args), 'combinator')
    elif defn.kind == 'observation':
        inputs = spec.extra.get('inputs', spec.extra.get('notation_inputs'))
        names = [item[0] for item in inputs] if inputs else [spec.subject]
        converter.bound.update(names)
        head = _expr('call', mark, '<|', tuple(_expr('var', _variable(item)) for item in names))
    elif defn.kind == 'law':
        converter.bound.update(name for name, _ in spec.vars)
        groups = []
        for variable, sort in spec.vars:
            domain = _sort(sort, legend)
            if groups and groups[-1].domain == domain:
                previous = groups[-1]
                groups[-1] = v3.BinderGroup((*previous.names, _variable(variable)), domain)
            else:
                groups.append(v3.BinderGroup((_variable(variable),), domain))
        if spec.equation is not None:
            left, right = (converter.node(item) for item in spec.equation)
            statement = _expr('bin', '==', converter._operand(left, priority=3),
                              converter._operand(right, priority=3, right=True))
        else:
            statement = converter.node(spec.statement)
        formula = v3.Stmt('law', (_expr('bare', mark), tuple(groups), statement, None))
        return None, formula
    elif defn.kind == 'bridge':
        head = _expr('call', mark, '(', (_expr('var', 'x'),))
        signature = v3.Stmt('sig', (_expr('bare', mark),
                                     _expr('arrow', _sort(spec.source, legend), _sort(spec.target, legend)),
                                     converter.node(spec.domain) if spec.domain is not None else None))
    elif defn.kind == 'object':
        head = _expr('bare', mark)
        if spec.form == 'compose':
            variants = []
            for tag, fields in spec.tags.items():
                tagged = _constructor(legend, defn.name, tag)
                fields = tuple(_expr('field', _variable(field), _sort(sort, legend)) for field, sort in fields)
                variants.append(_expr('call', tagged, '(', fields))
            return None, v3.Stmt('def', (head, _fold('+', variants), None))
        if spec.form == 'refine':
            fields = spec.extra.get('notation_fields', ())
            if not fields:
                raise ConversionError('refine object has no published fields')
            names = tuple(_expr('var', _variable(field)) for field, _ in fields)
            domains = tuple(_sort(sort, legend) for _, sort in fields)
            binder = _expr('bin', 'in', _expr('group', names), _fold('x*', domains))
            condition = converter.node(spec.valid)
            result = _expr('setb', binder, condition)
            if spec.canon is not None:
                result = _expr('bin', '/', result, _expr('bare', _mg(legend, spec.canon.fn, 'operation')))
            if spec.interface:
                result = _expr('bin', 'seal', result, _expr('list', tuple(_expr('bare', _mg(legend, op, 'operation'))
                                                                for op in spec.interface)))
            return None, v3.Stmt('def', (head, result, None))
        if spec.form == 'constant' and isinstance(defn.body, str):
            return None, v3.Stmt('def', (head, _template_instance(defn.body, legend), None))
        if spec.form != 'constant':
            raise ConversionError(f'unsupported object form {spec.form}')
        return None, v3.Stmt('def', (head, _group(converter.node(defn.body)), None))
    elif defn.kind == 'template':
        slots = []
        for index, (param, kind) in enumerate(spec.params):
            if kind in ('int', 'str', 'bool'):
                slots.append(_expr('var', _variable(param)))
                continue
            if kind == 'sort':
                slot_family = 'bbX'
            else:
                slot_family = {'operation': 'dia', 'combinator': 'Theta',
                               'observation': 'hatO', 'object': 'bbX'}.get(kind)
            if slot_family is None:
                raise ConversionError(f'unsupported template parameter kind {kind!r}')
            letter = list(v3.SLOT)[index % len(v3.SLOT)]
            slots.append(_expr('bare', _expr('mg', v3.Mark(None, slot_family, index_kind='slot',
                                                          index_value=letter), ())))
        head = _expr('bare', _expr('mg', mark.args[0], (tuple(slots),)))
        if not isinstance(defn.body, str):
            raise ConversionError('template pattern has no machine expression')
        try:
            pattern = converter.node(notation.parse_expr(defn.body, ctx))
        except notation.NotationError as exc:
            raise ConversionError(f'template pattern cannot be parsed: {defn.body!r}') from exc
        return None, v3.Stmt('def', (head, pattern, None))
    else:
        raise ConversionError(f'unknown definition kind {defn.kind}')
    if defn.body is None:
        raise ConversionError('definition has no body')
    body_node = defn.body
    check = None
    if (defn.kind == 'operation' and isinstance(body_node, n.Rec) and not body_node.memo and
            not isinstance(body_node.measure, str) and
            tuple(body_node.params) == tuple(edge.name for edge in spec.inputs) and
            tuple(body_node.args) == tuple(n.Var(param) for param in body_node.params)):
        old = converter.recursive
        converter.recursive = {**old, body_node.fn: mark}
        try:
            body = _body(body_node.body, converter)
            check = _expr('un', 'dec', converter.node(body_node.measure))
        finally:
            converter.recursive = old
    else:
        body = _body(body_node, converter)
    return signature, v3.Stmt('def', (head, body, check))


def _fold(sign, values):
    if not values:
        raise ConversionError('empty product or sum')
    result = values[0]
    for value in values[1:]:
        result = _expr('bin', sign, result, value)
    return result


def _application(mark, values, kind):
    if kind == 'combinator' and len(values) == 2:
        return _expr('inf', _group(values[0]) if values[0].tag in ('inf', 'bin', 'post', 'pre', 'bare') or
                     values[0].tag == 'num' and values[0].args[0] < 0
                     else values[0], mark,
                     _group(values[1]) if values[1].tag in ('inf', 'bin', 'post', 'pre', 'list', 'bare') else values[1])
    if kind == 'combinator' and len(values) == 1:
        value = values[0]
        if (value.tag in ('inf', 'bin', 'post', 'pre', 'let', 'rec', 'cases', 'group', 'bare', 'list') or
                value.tag == 'num' and value.args[0] < 0):
            return _expr('call', mark, '(', (value,))
        return _expr('pre', mark, value)
    return _expr('call', mark, '(', values)


def _template_instance(text, legend):
    match = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)([<\[])(.*)([>\]])', text)
    if not match:
        raise ConversionError(f'cannot express template pattern {text!r}')
    if (match[2], match[4]) not in (('[', ']'), ('<', '>')):
        raise ConversionError(f'unbalanced template instance {text!r}')
    arguments = []
    depth = 0
    start = 0
    for index, char in enumerate(match[3]):
        if char in '<[':
            depth += 1
        elif char in '>]':
            depth -= 1
        elif char == ',' and depth == 0:
            arguments.append(match[3][start:index].strip())
            start = index + 1
    arguments.append(match[3][start:].strip())
    mark = _mg(legend, match[1], 'template')
    values = []
    for arg in arguments:
        if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*[<\[].*[>\]]', arg):
            values.append(_template_instance(arg, legend))
            continue
        try:
            values.append(_expr('bare', _mg(legend, arg, 'operation')))
        except UndeclaredAtom:
            try:
                legend.by_name(arg, 'object')
            except KeyError:
                if not re.fullmatch(r'[A-Z]', arg):
                    raise UndeclaredAtom(arg, 'operation') from None
            values.append(_sort(arg, legend))
    return _expr('bare', _expr('mg', mark.args[0], (tuple(values),)))


def convert_outcome(text_or_outcome, legend):
    """Convert an outcome or its stored machine spelling."""
    if isinstance(text_or_outcome, str):
        text = text_or_outcome.strip()
        if text.startswith('Ok(') and text.endswith(')'):
            return _structured_expr(text[3:-1], legend)
        if text.startswith('Unknown(') and text.endswith(')'):
            return convert_value(Unknown(text[8:-1].strip('"')), legend)
        if text.startswith('Bottom(') and text.endswith(')'):
            reason = text[7:-1].strip()
            if re.fullmatch(r'[a-z][A-Za-z0-9_]*', reason):
                return convert_value(Bottom(reason), legend)  # a stored reason word, not an atom
            return _expr('fail', _structured_expr(reason, legend))
        if text.startswith('fail('):
            return convert_value(notation.parse_value(text), legend)
        raise ConversionError('not a stored outcome')
    return convert_value(text_or_outcome, legend)


def _split_fields(text):
    fields = []
    depth = 0
    start = 0
    quoted = False
    escaped = False
    for index, character in enumerate(text):
        if character == '"' and not escaped:
            quoted = not quoted
        if not quoted:
            if character in '(<[{':
                depth += 1
            elif character in ')>]}':
                depth -= 1
                if depth < 0:
                    raise ConversionError('unbalanced structured value')
            elif character == ',' and depth == 0:
                fields.append(text[start:index].strip())
                start = index + 1
        escaped = character == '\\' and not escaped
    if depth or quoted:
        raise ConversionError('unbalanced structured value')
    if text[start:].strip():
        fields.append(text[start:].strip())
    return fields


def _argument(text, legend):
    """A call argument: a one-letter name no atom has (the run state s) is a variable."""
    text = text.strip()
    if re.fullmatch(r'[a-z]', text) and not any(entry.atom.name == text for entry in legend.entries):
        return _expr('var', text)
    return _structured_expr(text, legend)


def _structured_expr(text, legend):
    text = text.strip()
    try:
        return convert_value(notation.parse_value(text), legend)
    except UndeclaredAtom:
        raise
    except (notation.NotationError, ConversionError):
        pass
    sigiled = re.fullmatch(r'@([a-z][A-Za-z_0-9]*)\[(.*)\]\((.*)\)', text, re.DOTALL)
    if sigiled:
        mark = _mg(legend, sigiled[1], 'combinator')
        refs = tuple(_expr('bare', _mg(legend, reference.lstrip('?@~#'),
                                       {'?': 'observation', '@': 'combinator',
                                        '~': 'bridge', '#': 'law'}.get(reference[:1]) or
                                       _declared_kind(legend, reference)))
                     for reference in _split_fields(sigiled[2]))
        mark = _expr('mg', mark.args[0], (refs,))
        return _application(mark, tuple(_argument(field, legend)
                                        for field in _split_fields(sigiled[3])), 'combinator')
    sigiled = re.fullmatch(r'\?([a-z][A-Za-z_0-9]*)\{(.*)\}', text, re.DOTALL)
    if sigiled:
        return _expr('call', _mg(legend, sigiled[1], 'observation'), '<|',
                     tuple(_structured_expr(field, legend) for field in _split_fields(sigiled[2])))
    sigiled = re.fullmatch(r'~([a-z][A-Za-z_0-9]*)\((.*)\)', text, re.DOTALL)
    if sigiled:
        return _expr('call', _mg(legend, sigiled[1], 'bridge'), '(',
                     tuple(_structured_expr(field, legend) for field in _split_fields(sigiled[2])))
    match = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)(?:\.([a-z][A-Za-z_0-9]*))?([(<])(.*)([)>])',
                         text, re.DOTALL)
    if not match or (match[3], match[5]) not in (('(', ')'), ('<', '>')):
        raise ConversionError(f'not a structured value: {text!r}')
    name, tag, opener, content, _ = match.groups()
    if opener == '<' and name == 'List' and tag is None:
        return _expr('list', tuple(_structured_expr(field, legend) for field in _split_fields(content)))
    if opener == '<' and ':' in content and '=' not in content:
        tag, _, content = content.partition(':')
        tag = tag.strip()
    if tag and opener == '(':
        # Sort.part(...) is a machine call: the declared operation of that dotted name when
        # it is not a constructor (Xor.base unwraps, BeliefPair.b reads a field), otherwise
        # make or a declared form, which constructs the object.
        part = legend._names.get((f'{name}.{tag}', 'operation'))
        if part is not None and part.atom.form_of is None:
            return _expr('call', _mg(legend, part.atom.name, 'operation'), '(',
                         tuple(_argument(field, legend) for field in _split_fields(content)))
        owner = legend._names.get((name, 'object'))
        if part is None and tag not in ('make', name, name.lower()) and (
                owner is None or tag not in owner.atom.forms):
            raise UndeclaredAtom(f'{name}.{tag}', 'operation')
    try:
        entry = legend.by_name(name, 'object' if opener == '<' or tag else
                               _declared_kind(legend, name))
        mark = _expr('mg', entry.mark, ())
        kind = entry.atom.kind
    except KeyError:
        if opener != '<' and tag is None:
            raise UndeclaredAtom(name, 'unknown') from None
        mark = _mg(legend, name, 'object')
        kind = 'object'
    if tag and tag != name and len(legend.by_name(name, 'object').atom.forms) > 1:
        mark = _constructor(legend, name, tag)
    values = []
    for field in _split_fields(content):
        named = re.fullmatch(r'([a-z][A-Za-z0-9_]*)\s*=\s*(.+)', field, re.DOTALL)
        if named:
            values.append(_expr('field', _variable(named[1]), _structured_expr(named[2], legend)))
        else:
            values.append(_argument(field, legend))
    if kind == 'observation':
        return _expr('call', mark, '<|', tuple(values))
    if tag or kind == 'object':
        return _expr('call', mark, '(', tuple(values))
    if kind == 'combinator':
        return _application(mark, tuple(values), kind)
    return _expr('call', mark, '(', tuple(values))


def _variant_declaration(text, legend):
    match = re.fullmatch(r'obj\s+([A-Za-z_][A-Za-z_0-9]*)\s*=\s*<(.+)>\s+(?:L\d+|given)',
                         text, re.DOTALL)
    if not match or ' | ' not in match[2]:
        raise ConversionError('not a variant declaration')
    mark = legend.sort_mark(match[1])
    variants = []
    for form in match[2].split(' | '):
        constructor = re.fullmatch(r'([a-z][A-Za-z0-9_]*)\((.*)\)', form.strip(), re.DOTALL)
        if not constructor:
            raise ConversionError('invalid variant constructor')
        fields = []
        for field in _split_fields(constructor[2]):
            named = re.fullmatch(r'([a-z][A-Za-z0-9_]*)\s*:\s*(.+)', field)
            if not named:
                raise ConversionError('invalid variant field')
            fields.append(_expr('field', _variable(named[1]), _sort(named[2], legend)))
        tagged = _constructor(legend, match[1], constructor[1])
        variants.append(_expr('call', tagged, '(', tuple(fields)))
    return v3.Stmt('def', (_expr('bare', mark), _fold('+', variants), None))


def _pair(stmt):
    return {'display': v3.show(stmt), 'ascii': v3.show(stmt, ascii=True)}


def _top_split(text, separator=','):
    """Split a type/header at top level, treating the arrow as one token."""
    parts = []
    stack = []
    opening = {'(': ')', '[': ']', '<': '>', '{': '}'}
    start = 0
    index = 0
    while index < len(text):
        if not stack and text.startswith(separator, index):
            parts.append(text[start:index].strip())
            index += len(separator)
            start = index
            continue
        char = text[index]
        if text.startswith('->', index):
            index += 2
            continue
        if char in opening:
            stack.append(opening[char])
        elif char in ')]}>' and (not stack or stack.pop() != char):
            raise ConversionError('unbalanced given header')
        index += 1
    if stack:
        raise ConversionError('unbalanced given header')
    parts.append(text[start:].strip())
    return parts


def _decl_type(text, legend, slots=None):
    text = text.strip()
    arrows = _top_split(text, '->')
    if len(arrows) > 1:
        parts = [_decl_type(part, legend, slots) for part in arrows]  # slots in reading order
        result = parts[-1]
        for domain in reversed(parts[:-1]):
            result = _expr('arrow', domain, result)
        return _group(result)
    if text.startswith('(') and text.endswith(')'):
        values = _top_split(text[1:-1])
        if len(values) > 1:
            return _fold('x*', [_decl_type(value, legend, slots) for value in values])
        return _decl_type(text[1:-1], legend, slots)
    generic = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)[<\[](.+)[>\]]', text)
    if generic and (text[len(generic[1])] == '<' and text.endswith('>') or
                    text[len(generic[1])] == '[' and text.endswith(']')):
        values = tuple(_expr('var', _variable(value)) if generic[1] == 'Record' and
                       re.fullmatch(r'[a-z][A-Za-z_0-9]*', value) else _decl_type(value, legend, slots)
                       for value in _top_split(generic[2]))
        return _expr('bare', _expr('mg', legend.sort_mark(generic[1]).args[0], (values,)))
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', text):
        raise ConversionError(f'invalid given sort {text!r}')
    return _sort(text, legend, slots)


def _given_declaration(text, legend, ctx):
    header = declaration_header(text)
    if header is None or not header['given']:
        raise ConversionError('not a given declaration')
    name, kind = header['name'], _call_kind(legend, header['name'], header['kind'])
    try:
        entry = legend.by_name(name, kind)
    except KeyError:
        raise UndeclaredAtom(name, kind) from None
    mark = _mg(legend, name, kind)
    head = _expr('bare', mark) if mark.tag == 'mg' else _group(mark)
    if kind != header['kind']:
        return {**_pair(v3.Stmt('expr', (head,))),
                'signature': _pair(entry.signature) if entry.signature else None}
    tail = header['remainder']
    if ' = ' in tail:
        tail = tail.split(' = ', 1)[0]  # a given's body is host prose: never converted or shown
    op_slots = []
    typed = []
    for opening, parameters in header['groups']:
        items = _top_split(parameters) if parameters.strip() else []
        for item in items:
            param = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)\s*:\s*(.+)', item, re.DOTALL)
            if param:
                (op_slots if opening == '[' else typed).append((param[1], param[2]))
            elif opening == '[' and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', item):
                op_slots.append((item, None))
            elif (opening in ('(', '<') and (item == '...' or re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', item))
                  or opening == '{' and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', item)):
                pass
            else:
                raise ConversionError('invalid given parameters')
    output = re.fullmatch(r'->\s*(.+)', tail, re.DOTALL)
    if tail and not output:
        raise ConversionError('invalid given return type')
    signature = entry.signature
    if output and (typed or op_slots or kind in ('operation', 'observation', 'bridge')):
        try:
            slots = {}
            domains = [_decl_type(sort, legend, slots) for _, sort in op_slots if sort]
            domains += [_decl_type(sort, legend, slots) for _, sort in typed]
            domain = _fold('x*', domains) if domains else _expr('group', ())
            proposed = v3.Stmt('sig', (head, _expr('arrow', domain, _decl_type(output[1], legend, slots)), None))
            if v3.check(v3.parse(v3.show(proposed))):
                raise ConversionError('given signature has kind errors')
            signature = proposed
        except UndeclaredAtom:
            raise
        except (ConversionError, v3.NotationError):
            pass
    elif kind == 'object' and not tail:
        signature = None
    formula = v3.Stmt('expr', (head,))
    return {**_pair(formula), 'signature': _pair(signature) if signature else None}


def is_design_text(text, ctx=None) -> bool:
    """Whether a display text is neither machine source nor a given declaration."""
    if not isinstance(text, str) or not text.strip():
        return True
    header = declaration_header(text)
    if header is not None and header['given']:
        return False
    if parseable_declaration(text, None) or parseable_expression(text):
        return False
    for parser in (notation.parse_definition, notation.parse_expr, notation.parse_value):
        try:
            parser(text, ctx) if parser is not notation.parse_value else parser(text)
            return False
        except (ValueError, TypeError):
            pass
    return True


def convert_text(machine_text, legend, ctx=None):
    """Convert a published machine definition, expression, value, or symbol."""
    if ctx is None:
        ctx = context_for(legend)
    kinds = _machine_kinds(machine_text)
    if kinds:
        ctx = {**ctx, 'kinds': {**ctx.get('kinds', {}),
                                **{name: references[0] for name, references in kinds.items()}}}
    tokens = [match.group() for match in notation._TOKEN.finditer(machine_text)]
    unsigiled_calls = {token for index, token in enumerate(tokens[:-1])
                       if tokens[index + 1] == '(' and (not index or tokens[index - 1] not in '@?~#')
                       and ctx.get('kinds', {}).get(token) in ('combinator', 'observation', 'object', 'bridge')}
    if unsigiled_calls:
        ctx = {**ctx, 'kinds': {**ctx['kinds'], **{name: 'operation' for name in unsigiled_calls}}}
    header = declaration_header(machine_text)
    if header is not None and header['given']:
        try:
            return _given_declaration(machine_text, legend, ctx)
        except UndeclaredAtom:
            raise
        except ConversionError:
            try:
                entry = legend.by_name(header['name'], header['kind'])
            except KeyError:
                raise UndeclaredAtom(header['name'], header['kind']) from None
            mark = legend.mark_expr(entry.atom.name, entry.atom.kind)
            if mark is None:
                mark = _mg(legend, entry.atom.name, entry.atom.kind)
            expression = _expr('bare', mark) if mark.tag == 'mg' else _group(mark)
            return {**_pair(v3.Stmt('expr', (expression,))), 'signature':
                    _pair(entry.signature) if entry.signature else None}
    placeholder_symbol = re.fullmatch(r'@([a-z][A-Za-z_0-9]*)\[[^]]*\]\(\.\.\.\)', machine_text)
    if placeholder_symbol:
        mark = _mg(legend, placeholder_symbol[1], 'combinator')
        return {**_pair(v3.Stmt('expr', (_expr('bare', mark),))), 'signature': None}
    placeholder = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)\(int\s*,\s*int\)', machine_text)
    if placeholder:
        try:
            mark = _mg(legend, placeholder[1], 'operation')
        except ConversionError:
            raise ConversionError(f'no legend entry for symbol {placeholder[1]!r}') from None
        return {**_pair(v3.Stmt('expr', (_expr('bare', mark),))),
                'signature': None}
    if ' = ' in machine_text and not re.match(r'^(?:op|obj|comb|obs|law|bridge|template)\s', machine_text):
        left, right = machine_text.split(' = ', 1)
        try:
            expr = _expr('bin', '==', _structured_expr(left, legend), _structured_expr(right, legend))
            return {**_pair(v3.Stmt('expr', (expr,))), 'signature': None}
        except UndeclaredAtom:
            raise
        except (ConversionError, v3.NotationError):
            pass
    sort_value = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)<value>', machine_text)
    if sort_value:
        try:
            legend.by_name(sort_value[1], 'object')
        except KeyError:
            pass
        else:
            return {**_pair(v3.Stmt('expr', (_sort(sort_value[1], legend),))),
                    'signature': None}
    internal = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*)\._[a-z][A-Za-z_0-9]*', machine_text)
    if internal:
        try:
            legend.by_name(internal[1], 'object')
        except KeyError:
            pass
        else:
            return {**_pair(v3.Stmt('expr', (_sort(internal[1], legend),))), 'signature': None}
    failures = []
    undeclared = None
    parsed_with_context = False
    for parser_index, parser in enumerate((lambda: notation.parse_definition(machine_text, ctx),
                   lambda: notation.parse_expr(machine_text, ctx),
                   lambda: notation.parse_definition(machine_text) if parseable_declaration(machine_text, None)
                   else None,
                   lambda: notation.parse_expr(machine_text) if parseable_expression(machine_text) else None,
                   lambda: notation.parse_value(machine_text))):
        try:
            parsed = parser()
            if parsed is None:
                continue
            if parser_index < 2:
                parsed_with_context = True
            if hasattr(parsed, 'kind') and hasattr(parsed, 'spec'):
                signature, formula = convert_definition(parsed, legend, ctx, machine_text)
                return {**_pair(formula), 'signature': _pair(signature) if signature else None}
            expr = (_Converter(legend, machine_text=machine_text).node(parsed) if isinstance(parsed, n.NODE_TYPES) else
                    convert_value(parsed, legend))
            return {**_pair(v3.Stmt('expr', (expr,))), 'signature': None}
        except UndeclaredAtom as error:
            if undeclared is None:
                undeclared = error
        except (notation.NotationError, ValueError, TypeError, KeyError) as exc:
            failures.append(str(exc))
    try:
        return {**_pair(_variant_declaration(machine_text, legend)), 'signature': None}
    except UndeclaredAtom as error:
        if undeclared is None:
            undeclared = error
    except (ConversionError, v3.NotationError) as exc:
        failures.append(str(exc))
    try:
        expr = convert_outcome(machine_text, legend)
        return {**_pair(v3.Stmt('expr', (expr,))), 'signature': None}
    except UndeclaredAtom as error:
        if undeclared is None:
            undeclared = error
    except (ValueError, TypeError) as exc:
        failures.append(str(exc))
    try:
        expr = _structured_expr(machine_text, legend)
        return {**_pair(v3.Stmt('expr', (expr,))), 'signature': None}
    except UndeclaredAtom as error:
        if undeclared is None:
            undeclared = error
    except (ValueError, TypeError) as exc:
        failures.append(str(exc))
    match = re.fullmatch(r'[@?#~]?([A-Za-z_][A-Za-z_0-9]*)(?:\.([A-Za-z_][A-Za-z_0-9]*))?(?:\[.*\](?:\(.*\))?|\{.*\}|<.*>|\(.*\))?', machine_text, re.DOTALL)
    # A stored symbol names an atom with placeholder parameters ('succ(...)', '?count{xs}');
    # text with values (digits, strings, nested cards or calls) is never collapsed to a mark.
    if match and (re.search(r'[0-9"\']', machine_text) or machine_text.count('<') > 1 or
                  machine_text.count('(') > 1 or machine_text.count('{') > 1):
        match = None
    if match and (machine_text[0] in '@?#~' or any(char in machine_text for char in '([{<')):
        try:
            if machine_text.endswith('<value>') and match[1] in ('Int', 'int', 'Bool', 'bool'):
                return {**_pair(v3.Stmt('expr', (_sort(match[1], legend),))),
                        'signature': None}
            sigil_kind = {'@': 'combinator', '?': 'observation',
                          '#': 'law', '~': 'bridge'}.get(machine_text[0])
            kind = sigil_kind or ('object' if machine_text[0].isupper() else
                                  _declared_kind(legend, match[1]))
            part = match[2] and legend._names.get((f'{match[1]}.{match[2]}', 'operation'))
            if match[2] and not part and match[2] not in ('make', match[1], match[1].lower()) and (
                    match[2] not in legend.by_name(match[1], 'object').atom.forms):
                raise KeyError(f'{match[1]}.{match[2]}')  # not a constructor: no object mark
            # Sort.part(...) names the dotted operation when one is declared (an unwrap, a
            # field read or a constructor), never the object itself.
            entry = part or legend.by_name(match[1], kind)
            expression = (legend.mark_expr(entry.atom.name, entry.atom.kind) or
                          _mg(legend, entry.atom.name, entry.atom.kind))
            return {**_pair(v3.Stmt('expr', (_expr('bare', expression) if expression.tag == 'mg'
                                            else _group(expression),))),
                    'signature': None}
        except KeyError:
            if undeclared is None:
                undeclared = UndeclaredAtom(match[1], kind)
        except (ValueError, TypeError) as exc:
            failures.append(str(exc))
    if undeclared is not None and (parsed_with_context or machine_text[:1] in '@?#~'):
        raise undeclared
    raise ConversionError(f'cannot convert {machine_text!r}: {"; ".join(failures)}')


_MENTION = re.compile(r'`([^`]+)`|(?<![A-Za-z0-9_])([@?#~])([A-Za-z_][A-Za-z_0-9]*)')


def _has_mark(node):
    if isinstance(node, v3.Mark):
        return True
    if isinstance(node, (tuple, list)):
        return any(_has_mark(item) for item in node)
    if is_dataclass(node):
        return any(_has_mark(getattr(node, field.name)) for field in fields(node))
    return False


def convert_prose(text, legend):
    """Replace only recognised sigiled atom names and parseable backtick formulas."""
    segments = []
    position = 0
    for match in _MENTION.finditer(text):
        candidate = (match[1] if match[1] is not None else match[2] + match[3])
        try:
            formula = convert_text(candidate, legend)
            if (not _has_mark(v3.parse(formula['display'])) and
                    not any(legend.binsign(name) for name in re.findall(
                        r'\b([a-z][A-Za-z0-9_]*)\s*\(', candidate))):
                continue
        except ConversionError:
            continue
        if match.start() > position:
            segments.append(['t', text[position:match.start()]])
        segments.append(['f', formula['display'], formula['ascii']])
        position = match.end()
    if not segments:
        return None
    if position < len(text):
        segments.append(['t', text[position:]])
    return segments
