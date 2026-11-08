"""ASCII notation (docs/spec/atoms-v2.md, sections 4, 6 and 8; spec 0.4).

Programs use ``prog (x = init) entry L0 { L0: x := e; jump L1;
L1: halt x }``. Initializers are optional; semicolons separate instructions and
blocks. ``if c jump L1 else L2`` is a conditional terminator. This syntax
preserves block order and never confuses a block with an observation.

The compact declaration language records only the fields it displays. Printer
rejects non-representable metadata instead of silently dropping it. A refine
object's ``canon reduce`` is an interface operation named ``reduce``; its
construction edges are stored in ObjectSpec.extra['notation_fields'].
Generated object names cycle A0 through Z0, then A1 through Z1.
``parse_program`` accepts several declarations, optional layer suffixes, ``save NAME``,
and line comments beginning with ``#`` followed by whitespace or end of line;
``#name`` remains a law sigil. Unspecified layers use the provisional invented
layer 1 and ``spec.extra['layer_unspecified']`` until the library assigns a layer.
Lowercase card sorts print as ``code<...>`` (not a display-only alias); bare
lowercase identifiers remain variables in expressions, so zero-field lowercase
card literals use ``code<>`` in expressions; value positions (including card
fields) accept bare lowercase identifiers as zero-field cards.
Operation declarations also accept uppercase learner-assigned names (for
example ``MUL``); law sigils and variables keep their lowercase-only rule.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import replace

from opulse.atoms import nodes as n
from opulse.atoms.kernel import FnRef
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.values import Bottom, Card


class NotationError(ValueError):
    def __init__(self, message: str, column: int):
        self.column = column
        super().__init__(f"{message} at column {column}")


_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|-?\d+|[A-Za-z_][A-Za-z_0-9]*|->|:=|[^\s]', re.ASCII)
_RESERVED = frozenset((
    "if", "then", "else", "let", "in", "rec", "measure", "fuel", "legacy", "memo",
    "prog", "entry", "jump", "halt", "true", "false", "and", "or", "not",
    "where", "canon", "sealed", "given", "obj", "op", "comb", "obs", "test",
    "law", "bridge", "template", "for", "commutes", "by",
))
_INFIX = {"add": "+", "sub": "-", "mul": "*"}
_GLYPHS = frozenset("⊕⊗⊝⊞⊟⊠∧∨⊻⊼⊽¬∀∃∄∩∪⊂⊃∈∋∉⊎⊓⊔∑∏∐∫∮√∛∜∞∂∇∆"
                    "←→↑↓↔↕↖↗↘↙⇐⇒⇑⇓⇔↦↩↪↺↻⇄⇆⟲⇉"
                    "■□▲△▼▽◆◇●○★☆♠♣♥♦♤♧♡♢◉ΓΔΘΛΞΠΣΦΨΩ")
_SUBSCRIPT = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def generated_name(kind: str, index: int) -> str:
    if type(index) is not int or index < 0:
        raise ValueError("index must be a nonnegative integer")
    prefixes = {"object": "A", "operation": "f", "combinator": "@k", "observation": "?q",
                "law": "#r", "bridge": "~b"}
    if kind not in prefixes:
        raise ValueError("unknown atom kind")
    if kind == "object":
        return f"{chr(ord('A') + index % 26)}{index // 26}"
    return f"{prefixes[kind]}{index}"


def stored_name(display: str) -> str:
    """Remove the display-only atom-kind sigil from an ASCII name."""
    if not isinstance(display, str) or not display.isascii():
        raise ValueError("invalid ASCII name")
    name = display[1:] if display.startswith(("@", "?", "#", "~")) else display
    return _name(name)


def legacy_symbol_to_ascii(text: str) -> str:
    match = re.fullmatch(r"([^₀₁₂₃₄₅₆₇₈₉]+)([₀₁₂₃₄₅₆₇₈₉]+)", text)
    if not match or match[1] not in _GLYPHS:
        raise ValueError("not a legacy operation symbol")
    return "f" + match[2].translate(_SUBSCRIPT)


def is_valid_name(kind: str, text: str) -> bool:
    if not isinstance(text, str) or not text.isascii():
        return False
    if kind == "object":
        return bool(re.fullmatch(r"[A-Z][A-Za-z_0-9]*", text))
    if kind == "operation":
        return bool(re.fullmatch(r"[a-z][A-Za-z_0-9]*", text)) and text not in _RESERVED
    if kind in ("combinator", "observation", "law", "bridge"):
        sigil = {"combinator": "@", "observation": "?", "law": "#", "bridge": "~"}[kind]
        return is_valid_name("operation", text[1:] if text.startswith(sigil) else text)
    if kind == "template":
        return is_valid_name("object", text) or is_valid_name("operation", text)
    return False


def _ascii(text: str) -> str:
    if not text.isascii():
        raise ValueError("ASCII notation cannot represent Unicode")
    return text


def _name(text: str) -> str:
    _ascii(text)
    if not _IDENT.fullmatch(text) or text in _RESERVED:
        raise ValueError("invalid ASCII identifier")
    return text


def _context(ctx):
    if ctx is None:
        return {}, {}, {}
    if isinstance(ctx, Mapping):
        kinds = ctx.get("kinds", ctx if not {"kinds", "op_arity", "infix"}.intersection(ctx) else {})
        arities = ctx.get("op_arity", {})
        infix = ctx.get("infix", {})
    else:
        definitions = getattr(ctx, "definitions", {})
        if callable(definitions):
            definitions = definitions()
        kinds = {key: value.kind for key, value in definitions.items()}
        arities = {key: len(value.spec.op_params) for key, value in definitions.items()
                   if value.kind == "combinator"}
        world = getattr(ctx, "world", None)
        operations = getattr(world, "operations", ())
        kinds.update({op.name: "operation" for op in operations if op.name not in kinds})
        kinds.update({probe["name"]: "observation" for probe in getattr(world, "observation", {}).get("probes", ())
                      if probe["name"] not in kinds})
        infix = {key: symbol for key, symbol in _INFIX.items()
                 if any(getattr(operation, "name", None) == key for operation in operations)}
    if isinstance(infix, (set, frozenset)):
        infix = {key: _INFIX[key] for key in infix if key in _INFIX}
    if any(key not in _INFIX or symbol != _INFIX[key] for key, symbol in infix.items()):
        raise ValueError("only given add/sub/mul may be infix")
    return kinds, arities, infix


def _probes(ctx):
    if isinstance(ctx, Mapping):
        return set(ctx.get("probes", ()))
    return {probe["name"] for probe in getattr(getattr(ctx, "world", None), "observation", {}).get("probes", ())}


def print_value(value) -> str:
    if isinstance(value, Bottom):
        return "fail(" + print_value(value.reason) + ")"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return _ascii(json.dumps(value, ensure_ascii=True))
    if isinstance(value, FnRef):
        raise TypeError("operation references are only valid inside combinator slots")
    if isinstance(value, tuple):
        return "List<" + ", ".join(print_value(item) for item in value) + ">"
    if isinstance(value, Card):
        if value.sort == "bool" and value.tag in ("true", "false") and not value.fields:
            raise ValueError("bool cards are indistinguishable from host bools in ASCII")
        if value.sort == "List" and value.tag == "List":
            raise ValueError("List cards are indistinguishable from host tuples in ASCII")
        if not (is_valid_name("object", value.sort) or is_valid_name("operation", value.sort)):
            raise ValueError("invalid object sort")
        if value.tag != value.sort:
            return value.sort + "." + _name(value.tag) + "<" + ", ".join(map(print_value, value.fields)) + ">"
        return value.sort + "<" + ", ".join(map(print_value, value.fields)) + ">"
    raise TypeError(f"unsupported notation value: {type(value).__name__}")


class _Parser:
    def __init__(self, text: str, ctx=None):
        if not text.isascii():
            raise NotationError("non-ASCII input", next(index + 1 for index, char in enumerate(text) if not char.isascii()))
        self.text = text
        self.tokens = []
        pos = 0
        for match in _TOKEN.finditer(text):
            if text[pos:match.start()].strip():
                raise NotationError("invalid token", pos + 1)
            self.tokens.append((match.group(), match.start() + 1))
            pos = match.end()
        if text[pos:].strip():
            raise NotationError("invalid token", pos + 1)
        self.tokens.append(("", len(text) + 1))
        self.index = 0
        self.kinds, self.arities, self.infix = _context(ctx)
        self.observation_arities = ctx.get("observation_arity", {}) if isinstance(ctx, Mapping) else {}
        self.infer_observation_arity = ctx is None

    def peek(self):
        return self.tokens[self.index][0]

    def take(self):
        token = self.peek()
        self.index += 1
        return token

    def error(self, message):
        raise NotationError(message, self.tokens[self.index][1])

    def eat(self, token):
        if self.peek() == token:
            self.take()
            return True
        return False

    def need(self, token):
        if not self.eat(token):
            self.error(f"expected {token!r}")

    def name(self):
        token = self.peek()
        if not _IDENT.fullmatch(token) or token in _RESERVED:
            self.error("expected identifier")
        return self.take()

    def end(self):
        if self.peek():
            self.error("unexpected token")

    def value(self):
        token = self.peek()
        if token == "fail":
            self.take()
            self.need("(")
            reason = self.value()
            if not isinstance(reason, str):
                self.error("failure reason must be a string")
            self.need(")")
            return Bottom(reason)
        if re.fullmatch(r"-?\d+", token):
            return int(self.take())
        if token.startswith('"'):
            self.take()
            try:
                return json.loads(token)
            except (ValueError, json.JSONDecodeError):
                self.error("invalid string")
        if token in ("true", "false"):
            self.take()
            return token == "true"
        if token == "(":
            self.take()
            values = self.sequence(")", self.value)
            if not values:
                self.error("empty tuple is ambiguous")
            return tuple(values)
        name = self.name()
        if self.eat("."):
            tag = self.name()
        else:
            tag = name
        if not (is_valid_name("object", name) or is_valid_name("operation", name)):
            self.error("expected object value")
        if not self.eat("<"):
            return Card(name, tag)
        fields = self.sequence(">", self.value)
        if name == "List" and tag == name:
            return tuple(fields)
        return Card(name, tag, tuple(fields))

    def sequence(self, close, read):
        result = []
        if not self.eat(close):
            while True:
                result.append(read())
                if self.eat(close):
                    break
                self.need(",")
                if self.peek() == close:
                    self.error("trailing comma")
        return result

    def expr(self, precedence=0):
        if self.eat("if"):
            arms = []
            while True:
                cond = self.cond()
                self.need("then")
                body = self.expr()
                self.need("else")
                arms.append((cond, body))
                if not self.eat("if"):
                    break
            node = n.Case(tuple(arms), self.expr())
        elif self.eat("let"):
            name = self.name()
            self.need("=")
            value = self.expr()
            self.need("in")
            node = n.Let(name, value, self.expr())
        elif self.eat("rec"):
            memo = self.eat("memo")
            name = self.name()
            self.need("(")
            params = self.sequence(")", self.name)
            self.need("=")
            body = self.expr()
            self.need("measure")
            measure = self.take() if self.peek() in ("fuel", "legacy") else self.expr()
            self.need("in")
            self.need(name)
            self.need("(")
            args = self.sequence(")", self.expr)
            if len(args) != len(params):
                self.error("recursive argument count mismatch")
            node = n.Rec(name, tuple(params), body, tuple(args), measure, memo)
        elif self.eat("prog"):
            node = self.program()
        elif self.eat("("):
            node = self.expr()
            self.need(")")
        elif self.peek() in ("true", "false", "fail") or re.fullmatch(r"-?\d+|\"(?:\\.|[^\"\\])*\"", self.peek()):
            node = n.Lit(self.value())
        elif self.peek() in ("@", "?", "~"):
            kind = self.take()
            name = self.name()
            if kind == "@" and is_valid_name("object", name) and self.eat("."):
                self.need("fold")
                name += ".fold"
            displayed = kind + name
            atom_kind = {"@": "combinator", "?": "observation", "~": "bridge"}[kind]
            if not (kind == "@" and re.fullmatch(r"@[A-Z][A-Za-z_0-9]*\.fold", displayed)) and not is_valid_name(
                    atom_kind, displayed):
                self.error("invalid atom name")
            if self.kinds.get(name) != atom_kind:
                self.error("sigil does not match a declared kind")
            if kind == "@":
                self.need("[")
                refs = self.sequence("]", self.ref)
                if name in self.arities and self.arities[name] != len(refs):
                    self.error("wrong combinator operation arity")
                self.need("(")
                args = self.sequence(")", self.expr)
                node = n.Call(name, tuple(refs) + tuple(args))
            else:
                self.need("{" if kind == "?" else "(")
                args = self.sequence("}" if kind == "?" else ")", self.expr)
                if (not args or kind == "~" and len(args) != 1 or
                        kind == "?" and len(args) != self.observation_arities.get(
                            name, len(args) if self.infer_observation_arity else 1)):
                    self.error(f"{atom_kind} needs exactly one argument")
                node = n.Call(name, tuple(args))
        else:
            name = self.name()
            if self.eat("."):
                tag = self.name()
                self.need("<")
                fields = self.sequence(">", self.value)
                node = n.Lit(Card(name, tag, tuple(fields)))
            elif self.eat("<"):
                fields = self.sequence(">", self.value)
                node = n.Lit(tuple(fields) if name == "List" else Card(name, name, tuple(fields)))
            elif self.eat("("):
                if self.kinds.get(name) in ("combinator", "observation", "object", "bridge", "law"):
                    self.error("call notation does not match declared kind")
                node = n.Call(name, tuple(self.sequence(")", self.expr)))
            elif is_valid_name("object", name):
                node = n.Lit(Card(name, name))
            else:
                node = n.Var(name)
        inverse = {symbol: name for name, symbol in self.infix.items()}
        while self.peek() in inverse and (level := (2 if self.peek() == "*" else 1)) >= precedence:
            symbol = self.take()
            node = n.Call(inverse[symbol], (node, self.expr(level + 1)))
        return node

    def ref(self):
        if self.eat("$"):
            return n.Var(self.name())
        name = self.name()
        if not is_valid_name("operation", name) or self.kinds.get(name) in ("combinator", "observation", "object", "bridge", "law"):
            self.error("expected operation reference")
        return n.Lit(FnRef(name))

    def cond(self, precedence=0):
        if self.eat("not"):
            self.need("(")
            node = n.Not(self.cond())
            self.need(")")
        elif self.peek() == "(":
            start = self.index
            try:
                expression = self.expr()
                if expression == n.Lit(True):
                    self.index = start
                    raise NotationError("condition grouping", self.tokens[start][1])
                node = n.Test(expression)
            except NotationError:
                self.index = start
                self.need("(")
                node = self.cond()
                self.need(")")
        elif self.peek() == "true" and self.tokens[self.index + 1][0] not in self.infix.values():
            self.take()
            node = n.Always()
        elif self.eat("test"):
            self.need("(")
            node = n.Test(self.expr())
            self.need(")")
        else:
            node = n.Test(self.expr())
        return self.cond_tail(node, precedence)

    def cond_tail(self, node, precedence=0):
        while self.peek() in ("and", "or") and (level := (2 if self.peek() == "and" else 1)) >= precedence:
            token = self.take()
            right = self.cond(level + 1)
            node = n.And(node, right) if token == "and" else n.Or(node, right)
        return node

    def program(self):
        self.need("(")
        variables = self.sequence(")", self.initializer)
        self.need("entry")
        entry = self.name()
        self.need("{")
        blocks = []
        while not self.eat("}"):
            label = self.name()
            self.need(":")
            assigns = []
            while True:
                if self.eat("jump"):
                    end = n.Jump(self.name())
                elif self.eat("if"):
                    cond = self.cond()
                    self.need("jump")
                    then = self.name()
                    self.need("else")
                    end = n.CondJump(cond, then, self.name())
                elif self.eat("halt"):
                    end = n.Halt(self.expr())
                else:
                    name = self.name()
                    self.need(":=")
                    assigns.append((name, self.expr()))
                    self.need(";")
                    continue
                blocks.append((label, n.Block(tuple(assigns), end)))
                break
            if not self.eat("}"):
                self.need(";")
            else:
                break
        if not blocks or len({label for label, _ in blocks}) != len(blocks):
            self.error("program needs distinct blocks")
        return n.Blocks(tuple(variables), entry, tuple(blocks))

    def initializer(self):
        name = self.name()
        self.need("=")
        return name, self.expr()


def parse_value(text: str):
    parser = _Parser(text)
    value = parser.value()
    parser.end()
    return value


def parse_expr(text: str, ctx=None):
    parser = _Parser(text, ctx)
    if parser.peek() in ("not", "test"):
        condition = parser.cond()
        result = n.Case(((condition, n.Lit(True)),), n.Lit(False))
    else:
        result = parser.expr()
        if parser.peek() in ("and", "or"):
            condition = parser.cond_tail(n.Test(result))
            result = n.Case(((condition, n.Lit(True)),), n.Lit(False))
    parser.end()
    return result


def _cond(value, ctx, precedence=0):
    if isinstance(value, n.Always):
        text, level = "true", 4
    elif isinstance(value, n.Test):
        text, level = print_expr(value.expr, ctx), 4
        if isinstance(value.expr, n.Lit) and value.expr.value is True:
            text = "test(true)"
    elif isinstance(value, n.Not):
        text, level = "not(" + _cond(value.operand, ctx) + ")", 4
    elif isinstance(value, (n.And, n.Or)):
        level = 2 if isinstance(value, n.And) else 1
        text = _cond(value.left, ctx, level) + (" and " if level == 2 else " or ") + _cond(value.right, ctx, level + 1)
    else:
        raise TypeError("unknown condition")
    return "(" + text + ")" if level < precedence else text


def print_expr(node, ctx=None) -> str:
    kinds, arities, infix = _context(ctx)
    if isinstance(node, n.Lit):
        if (isinstance(node.value, Card) and not node.value.fields and
                node.value.tag == node.value.sort and is_valid_name("operation", node.value.sort)):
            return node.value.sort + "<>"
        return print_value(node.value)
    if isinstance(node, n.Var):
        if not is_valid_name("operation", node.name):
            raise ValueError("variables must use lowercase ASCII identifiers")
        return node.name
    if isinstance(node, n.Call):
        if not is_valid_name("operation", node.fn) and not (
                re.fullmatch(r"[A-Z][A-Za-z_0-9]*", node.fn) and
                kinds.get(node.fn) in (None, "operation")) and not (
                kinds.get(node.fn) == "combinator" and
                re.fullmatch(r"[A-Z][A-Za-z_0-9]*\.fold", node.fn)):
            raise ValueError("calls must store plain ASCII identifiers")
        if kinds.get(node.fn) == "combinator":
            arity = arities.get(node.fn)
            if arity is None:
                arity = next((index for index, arg in enumerate(node.args)
                              if not isinstance(arg, n.Lit) or not isinstance(arg.value, FnRef)), len(node.args))
            refs = node.args[:arity]
            if any(not isinstance(arg, n.Var) and
                   (not isinstance(arg, n.Lit) or not isinstance(arg.value, FnRef)) for arg in refs):
                raise ValueError("combinator slots must be operation references")
            if any(not is_valid_name("operation", arg.name if isinstance(arg, n.Var) else arg.value.name) or
                   kinds.get(arg.name if isinstance(arg, n.Var) else arg.value.name) in
                   ("combinator", "observation", "object") for arg in refs):
                raise ValueError("invalid combinator operation reference")
            displayed = "@" + node.fn
            if not is_valid_name("combinator", displayed) and not re.fullmatch(
                    r"@[A-Z][A-Za-z_0-9]*\.fold", displayed):
                raise ValueError("invalid combinator name")
            return _ascii(displayed) + "[" + ", ".join("$" + arg.name if isinstance(arg, n.Var)
                                                    else arg.value.name for arg in refs) + "](" + ", ".join(print_expr(arg, ctx) for arg in node.args[arity:]) + ")"
        if kinds.get(node.fn) in ("observation", "bridge"):
            atom_kind = kinds[node.fn]
            if not node.args or atom_kind == "bridge" and len(node.args) != 1:
                raise ValueError("observation needs inputs or bridge needs one argument")
            displayed = ("?" if atom_kind == "observation" else "~") + node.fn
            if not is_valid_name(atom_kind, displayed):
                raise ValueError("invalid atom name")
            opening, closing = ("{", "}") if atom_kind == "observation" else ("(", ")")
            return _ascii(displayed) + opening + ", ".join(print_expr(arg, ctx) for arg in node.args) + closing
        if node.fn in infix and len(node.args) == 2:
            level = 2 if node.fn == "mul" else 1
            def part(arg, side):
                if isinstance(arg, (n.Let, n.Case, n.Rec, n.Blocks)):
                    return "(" + print_expr(arg, ctx) + ")"
                if isinstance(arg, n.Call) and arg.fn in infix and len(arg.args) == 2:
                    child = 2 if arg.fn == "mul" else 1
                    if child < level or child == level and side == "right":
                        return "(" + print_expr(arg, ctx) + ")"
                return print_expr(arg, ctx)
            return part(node.args[0], "left") + " " + infix[node.fn] + " " + part(node.args[1], "right")
        if kinds.get(node.fn) in ("object", "law"):
            raise ValueError("object or law cannot be called as an operation")
        return node.fn + "(" + ", ".join(print_expr(arg, ctx) for arg in node.args) + ")"
    if isinstance(node, n.Let):
        return f"let {_name(node.name)} = {print_expr(node.value, ctx)} in {print_expr(node.body, ctx)}"
    if isinstance(node, n.Case):
        if not node.arms or node.default is None:
            raise ValueError("ASCII if requires arms and an else branch")
        def nested(value):
            text = print_expr(value, ctx)
            return "(" + text + ")" if isinstance(value, n.Case) else text
        return "if " + " else if ".join(_cond(cond, ctx) + " then " + nested(body) for cond, body in node.arms) + " else " + nested(node.default)
    if isinstance(node, n.Rec):
        measure = node.measure if isinstance(node.measure, str) else print_expr(node.measure, ctx)
        return ("rec " + ("memo " if node.memo else "") + _name(node.fn) + "(" + ", ".join(map(_name, node.params)) + ") = " + print_expr(node.body, ctx) + " measure " + measure + " in " + node.fn + "(" + ", ".join(print_expr(arg, ctx) for arg in node.args) + ")")
    if isinstance(node, n.Blocks):
        blocks = []
        for label, block in node.blocks:
            assigns = [_name(name) + " := " + print_expr(expr, ctx) for name, expr in block.assigns]
            end = block.end
            if isinstance(end, n.Jump):
                tail = "jump " + _name(end.target)
            elif isinstance(end, n.CondJump):
                tail = "if " + _cond(end.cond, ctx) + " jump " + _name(end.then) + " else " + _name(end.else_)
            else:
                tail = "halt " + print_expr(end.value, ctx)
            blocks.append(_name(label) + ": " + "; ".join([*assigns, tail]))
        return "prog (" + ", ".join(_name(name) + " = " + print_expr(expr, ctx) for name, expr in node.vars) + ") entry " + _name(node.entry) + " { " + "; ".join(blocks) + " }"
    raise TypeError(f"unsupported notation node: {type(node).__name__}")


def parse_step_annotation(text: str) -> str:
    """Read a derivation's ``by #law`` annotation as a stored law name."""
    parser = _Parser(text)
    parser.need("by")
    parser.need("#")
    name = parser.name()
    if not is_valid_name("law", name):
        parser.error("invalid law name")
    parser.end()
    return name


def print_step_annotation(name: str) -> str:
    if not is_valid_name("law", name) or stored_name(name) != name:
        raise ValueError("invalid stored law name")
    return "by #" + name


def _definition_refs(body, spec) -> tuple[str, ...]:
    excluded = set(spec.op_params) if isinstance(spec, CombinatorSpec) else set()
    references = n.references(body) - excluded if isinstance(body, n.NODE_TYPES) else set()
    if isinstance(spec, ObjectSpec) and spec.extra.get("notation_instantiation"):
        references.add(spec.extra["notation_instantiation"].split("[", 1)[0])
    return tuple(sorted(references))


def _template_pattern(body: str, params: tuple[tuple[str, str], ...]) -> str:
    names = {name for name, _ in params}
    refine_canon = re.search(r"\brefine\s+[A-Za-z_][A-Za-z_0-9]*\s+(canon)\s*\(", body)

    def substitute(match):
        if refine_canon and match.start() == refine_canon.start(1):
            return match.group()
        return "$" + match.group() if match.group() in names else match.group()
    return _TOKEN.sub(substitute, body)


def _template_spec_pattern(body: str, params: tuple[tuple[str, str], ...], produces: str) -> dict:
    names = {name for name, _ in params}
    if produces == "object":
        match = re.fullmatch(r"refine\s+([A-Za-z_][A-Za-z_0-9]*)\s+canon\(\s*([A-Za-z_][A-Za-z_0-9]*)\s*\)", body)
        if match is None:
            raise ValueError("unsupported object template pattern")
        base, canon = match.groups()
        return {"form": "refine", "base": "$" + base if base in names else base,
                "valid": n.to_json(n.Lit(True)),
                "canon": n.to_json(n.Call("$" + canon if canon in names else canon, (n.Var("x"),)))}

    expression = parse_expr(body)

    def placeholders(value):
        if isinstance(value, dict):
            return {key: ("$" + item if key in ("name", "fn") and item in names else placeholders(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [placeholders(item) for item in value]
        return value

    expression_pattern = placeholders(n.to_json(expression))
    if produces == "operation":
        return {"role": "transform", "inputs": [{"sort": "int"}], "output": {"sort": "int"},
                "rule": _template_pattern(body, params), "input_names": ["arg0"],
                "definition_body": expression_pattern}
    if produces == "combinator":
        op_params = ["$" + name for name, kind in params if kind == "operation"]
        return {"params": [*op_params, "x"], "op_params": op_params,
                "body": expression_pattern}
    return {"reads": ["$" + name for name, kind in params if kind == "observation"],
            "subject": "x", "body": expression_pattern}


def print_definition(defn: Definition, ctx=None) -> str:
    """Print the representable declaration subset; reject metadata that would be lost."""
    if defn.spec.extra.get("layer_unspecified") is True:
        if defn.layer != 1 or defn.origin != "invented":
            raise ValueError("unspecified layer must be provisional L1")
        spec = replace(defn.spec, extra={key: value for key, value in defn.spec.extra.items()
                                          if key != "layer_unspecified"})
        return print_definition(replace(defn, spec=spec), ctx).removesuffix(" L1")
    if (defn.status != "written" or defn.evidence is not None or defn.contract is not None or
            defn.id is not None or defn.cost.length or defn.cost.steps is not None or defn.cost.reuse):
        raise ValueError("verification metadata has no compact ASCII declaration")
    if not (is_valid_name(defn.kind, defn.name) or defn.kind == "operation" and
            re.fullmatch(r"[A-Z][A-Za-z_0-9]*", defn.name)) or stored_name(defn.name) != defn.name:
        raise ValueError("invalid declaration name")
    if any(stored_name(name) != name for name in defn.depends_on):
        raise ValueError("dependencies must use stored names")
    suffix = "given" if defn.origin == "given" and defn.layer == 0 else f"L{defn.layer}"
    if defn.origin != ("given" if defn.layer == 0 else "invented"):
        raise ValueError("origin/layer mismatch")
    template = defn.spec.extra.get("template") if defn.kind == "object" else None
    if template is not None:
        if (defn.spec.extra.keys() != {"template"} or defn.spec.name != defn.name or
                defn.body is not None or not isinstance(template, dict) or
                not isinstance(template.get("args"), dict)):
            raise ValueError("unsupported template instantiation metadata")
        template_name = _name(template["name"])
        args = []
        for value in template["args"].values():
            if not isinstance(value, str):
                raise TypeError("template argument has no compact ASCII representation")
            parser = _Parser(value)
            args.append(_template_argument(parser))
            parser.end()
        if (not args or not defn.depends_on or defn.depends_on[0] != template_name or
                len(set(defn.depends_on)) != len(defn.depends_on) or
                not set(defn.depends_on[1:]) <= set(args)):
            raise ValueError("unsupported template instantiation dependencies")
        return _ascii(f"obj {defn.name} = {template_name}[{', '.join(args)}] {suffix}")
    if defn.depends_on != _definition_refs(defn.body, defn.spec):
        raise ValueError("dependencies cannot be represented in their current order")
    kinds, arities, infix = _context(ctx)
    kinds = dict(kinds)
    if defn.kind == "observation":
        kinds.update({name: "observation" for name in defn.spec.reads if name not in kinds})
    kinds[defn.name] = defn.kind
    body_ctx = {"kinds": kinds, "op_arity": arities, "infix": infix}
    if defn.kind == "law":
        spec = defn.spec
        if spec.name != defn.name or spec.statement != defn.body or spec.extra or not spec.vars:
            raise ValueError("unsupported law metadata")
        variables = ", ".join(f"{_name(name)}: {_name(sort)}" for name, sort in spec.vars)
        result = f"law #{defn.name}: {print_expr(defn.body, body_ctx)} for {variables}"
    elif defn.kind == "bridge":
        spec = defn.spec
        if spec.name != defn.name or spec.map != defn.body or spec.extra:
            raise ValueError("unsupported bridge metadata")
        result = (f"bridge ~{defn.name}: {_bridge_sort_text(spec.source)} -> {_bridge_sort_text(spec.target)}"
                  f" = {print_expr(defn.body, body_ctx)}")
        if spec.domain is not None:
            result += " where " + print_expr(spec.domain, body_ctx)
        if spec.interface:
            result += " commutes (" + ", ".join(f"{_name(source)} -> {_name(target)}"
                                                 for source, target in spec.interface) + ")"
    elif defn.kind == "template":
        spec = defn.spec
        if (spec.name != defn.name or spec.extra or not isinstance(defn.body, str) or
                spec.pattern != _template_spec_pattern(defn.body, spec.params, spec.produces) or
                not defn.body.strip() or not spec.params):
            raise ValueError("unsupported template metadata")
        keyword = {"object": "obj", "operation": "op", "combinator": "comb",
                   "observation": "obs"}.get(spec.produces)
        if keyword is None:
            raise ValueError("unsupported template result kind")
        if not is_valid_name(spec.produces, defn.name):
            raise ValueError("template name disagrees with produced kind")
        display_kinds = {"sort": "obj", "operation": "op", "combinator": "comb",
                         "observation": "obs"}
        params = ", ".join(f"{_template_param_name(name)}: {_template_sort(display_kinds.get(sort, sort))}"
                           for name, sort in spec.params)
        sigil = {"combinator": "@", "observation": "?"}.get(spec.produces, "")
        result = f"template {keyword} {sigil}{defn.name}[{params}] = {_ascii(defn.body)}"
    elif defn.kind == "operation":
        spec = defn.spec
        if (spec.name != defn.name or spec.role != "transform" or spec.rule != "ASCII definition" or
                spec.errors or spec.impl or spec.cost != 1 or not spec.strict or spec.reads_params or spec.extra or
                spec.output.name is not None or any(edge.enter != "bottom" for edge in (*spec.inputs, spec.output))):
            raise ValueError("operation metadata has no compact ASCII declaration")
        if defn.body is None:
            raise ValueError("operation needs a body")
        params = ", ".join(f"{edge.name}: {edge.sort}" for edge in spec.inputs)
        if any(edge.name is None for edge in spec.inputs):
            raise ValueError("operation inputs need names")
        result = f"op {defn.name}({params}) -> {spec.output.sort} = {print_expr(defn.body, body_ctx)}"
    elif defn.kind == "combinator":
        spec = defn.spec
        if spec.name != defn.name or spec.unfold_rule != "substitute" or spec.body != defn.body or len(spec.params) != len(set(spec.params)) or set(spec.op_params) - set(spec.params):
            raise ValueError("unsupported combinator signature")
        ops = ", ".join(f"{name}: A -> A" for name in spec.op_params)
        args = ", ".join(f"{name}: A" for name in spec.params if name not in spec.op_params)
        result = f"comb @{defn.name}[{ops}]({args}) -> A = {print_expr(defn.body, body_ctx)}"
    elif defn.kind == "observation":
        spec = defn.spec
        extra = getattr(spec, "extra", {})
        if (spec.name != defn.name or spec.memory is not None or spec.body != defn.body or
                extra.keys() - {"subject", "inputs", "notation_inputs", "notation_result", "layer_unspecified"} or
                any(stored_name(name) != name for name in spec.reads)):
            raise ValueError("unsupported observation signature")
        subject = extra.get("subject", "s")
        _name(subject)
        inputs = tuple(extra.get("inputs", extra.get("notation_inputs", ())))
        if inputs and (inputs[0][0] != subject or any(not isinstance(pair, (tuple, list)) or len(pair) != 2
                                                      for pair in inputs)):
            raise ValueError("invalid observation input metadata")
        signature = ", ".join(f"{_name(name)}: {_name(sort)}" for name, sort in inputs) if inputs else subject
        result_sort = " -> " + _name(extra["notation_result"]) if "notation_result" in extra else ""
        if (isinstance(defn.body, n.Case) and len(defn.body.arms) == 1 and
                defn.body.arms[0][1] == n.Lit(True) and defn.body.default == n.Lit(False) and
                (isinstance(defn.body.arms[0][0], n.Not) or
                 isinstance(defn.body.arms[0][0], (n.And, n.Or)) and
                 not any(isinstance(part, n.Always) for part in n.walk(defn.body.arms[0][0])))):
            body_text = _cond(defn.body.arms[0][0], body_ctx)
        else:
            body_text = print_expr(defn.body, body_ctx)
        result = f"obs ?{defn.name}{{{signature}}}{result_sort} = {body_text}"
    elif defn.kind == "object":
        spec = defn.spec
        if spec.name != defn.name or spec.group or spec.params or spec.equality != "canonical" or spec.canon_cost != "counted" or spec.extra.keys() - {"notation_fields", "notation_instantiation"}:
            raise ValueError("unsupported object metadata")
        if "notation_instantiation" in spec.extra:
            invocation = spec.extra["notation_instantiation"]
            if spec.form != "constant" or spec.body != invocation or defn.body != invocation:
                raise ValueError("unsupported template instantiation")
            result = f"obj {defn.name} = {invocation}"
            return _ascii(result + " " + suffix)
        if spec.form == "compose":
            if spec.sealed or spec.interface or spec.valid or spec.canon or defn.body is not None:
                raise ValueError("unsupported compose metadata")
            tags = []
            for tag, fields in spec.tags.items():
                if isinstance(fields, dict):
                    raise TypeError("mapping tag fields need the schema representation")
                tags.append(tag + ("<" + ", ".join(f"{key}: {sort}" for key, sort in fields) + ">" if fields else ""))
            result = f"obj {defn.name} = " + " | ".join(tags)
        elif spec.form == "refine":
            fields = spec.extra.get("notation_fields")
            if not fields or spec.base != "Record" or spec.valid != defn.body or spec.canon is not None and not isinstance(spec.canon, n.Call):
                raise ValueError("unsupported refine metadata")
            result = f"obj {defn.name} = <" + ", ".join(f"{key}: {sort}" for key, sort in fields) + "> where " + print_expr(spec.valid, body_ctx)
            if spec.canon is not None:
                if spec.canon.args:
                    raise ValueError("canon must name an operation, not an application")
                result += " canon " + spec.canon.fn
            if spec.sealed:
                result += " sealed (" + ", ".join(spec.interface) + ")"
            elif spec.interface:
                raise ValueError("unsealed interface has no compact syntax")
        elif spec.form == "constant":
            if spec.sealed or spec.interface or spec.valid or spec.canon or spec.base or spec.tags or spec.body != defn.body:
                raise ValueError("unsupported constant metadata")
            result = f"obj {defn.name} = ({print_expr(defn.body, body_ctx)})"
        else:
            raise ValueError("given object forms need an explicit schema")
    return _ascii(result + " " + suffix)


def _typed(parser, arrow=False):
    name = parser.name()
    parser.need(":")
    sort = parser.name()
    if arrow:
        parser.need("->")
        result = parser.name()
        if sort != "A" or result != "A":
            parser.error("compact combinator signatures use A -> A")
    elif not is_valid_name("object", sort) and not is_valid_name("operation", sort):
        parser.error("expected sort")
    return name, sort


def _template_argument(parser):
    name = parser.name()
    if parser.eat("<"):
        if not is_valid_name("object", name):
            parser.error("expected object sort")
        args = parser.sequence(">", lambda: _template_argument(parser))
        return name + "<" + ", ".join(args) + ">"
    return name


def _template_sort(sort):
    if sort in ("obj", "op", "comb", "obs", "law", "bridge"):
        return sort
    return _name(sort)


def _template_param_name(name):
    if not _IDENT.fullmatch(_ascii(name)):
        raise ValueError("invalid template parameter")
    return name


def _template_parameter(parser):
    name = parser.take()
    if not _IDENT.fullmatch(name):
        parser.error("expected template parameter")
    parser.need(":")
    sort = parser.take()
    if not sort or sort != _template_sort(sort):
        parser.error("expected parameter kind or sort")
    return name, sort


def _template_body(parser):
    start = parser.tokens[parser.index][1] - 1
    if not parser.peek():
        parser.error("expected template body")
    starters = {"obj", "op", "comb", "obs", "law", "bridge", "template", "save"}

    def next_item():
        position = parser.tokens[parser.index][1] - 1
        line_start = parser.text.rfind("\n", 0, position) + 1
        return (position > start and parser.peek() in starters and
                not parser.text[line_start:position].strip())

    while parser.peek() and (getattr(parser, "program_mode", False) or parser.tokens[parser.index + 1][0]) and not (
            getattr(parser, "program_mode", False) and (re.fullmatch(r"L[1-9]\d*", parser.peek()) or next_item())):
        parser.take()
    end = parser.tokens[parser.index][1] - 1
    body = parser.text[start:end].strip()
    if not body:
        parser.error("expected template body")
    return body


def _bridge_sort_text(sort: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*(?:@[0-9]+:[A-Za-z_][A-Za-z_0-9]*)?", sort):
        raise ValueError("invalid bridge sort")
    return sort


def _bridge_sort(parser: _Parser) -> str:
    name = parser.name()
    if parser.eat("@"):
        version = parser.take()
        if not version.isdigit():
            parser.error("expected world version")
        parser.need(":")
        name += "@" + version + ":" + parser.name()
    return name


def _parse_definition(text: str, ctx=None, *, parser=None) -> Definition:
    program_mode = parser is not None
    if parser is None:
        parser = _Parser(text, ctx)
    kind_token = parser.take()
    produces = None
    if kind_token == "template":
        produces = {"obj": "object", "op": "operation", "comb": "combinator",
                    "obs": "observation"}.get(parser.take())
        if produces is None:
            parser.error("expected template result kind")
    kind = "template" if produces else {"obj": "object", "op": "operation", "comb": "combinator",
                                           "obs": "observation", "law": "law", "bridge": "bridge"}.get(kind_token)
    if kind is None:
        raise NotationError("expected definition kind", 1)
    prefix = {"combinator": "@", "observation": "?", "law": "#", "bridge": "~"}.get(produces or kind, "")
    if prefix:
        parser.need(prefix)
    name = parser.name()
    if not is_valid_name(produces or kind, name) and not (kind == "operation" and
                                                          re.fullmatch(r"[A-Z][A-Za-z_0-9]*", name)):
        parser.error("invalid definition name")
    parser.kinds = dict(parser.kinds)
    if parser.kinds.get(name, produces or kind) != (produces or kind):
        parser.error("definition kind disagrees with context")
    parser.kinds[name] = produces or kind
    if ctx is None:
        for index, (token, _) in enumerate(parser.tokens[:-1]):
            if token in ("@", "?", "~"):
                referenced = parser.tokens[index + 1][0]
                referenced_kind = {"@": "combinator", "?": "observation", "~": "bridge"}[token]
                if parser.kinds.get(referenced, referenced_kind) != referenced_kind:
                    parser.error("conflicting sigils for the same name")
                parser.kinds[referenced] = referenced_kind
    if kind == "law":
        parser.need(":")
        body = parser.expr()
        parser.need("for")
        variables = [_typed(parser)]
        while parser.eat(","):
            variables.append(_typed(parser))
        spec = LawSpec(name, tuple(variables), body)
    elif kind == "bridge":
        parser.need(":")
        source = _bridge_sort(parser)
        parser.need("->")
        target = _bridge_sort(parser)
        parser.need("=")
        body = parser.expr()
        domain = parser.expr() if parser.eat("where") else None
        interface = []
        if parser.eat("commutes"):
            parser.need("(")
            def pair():
                left = parser.name()
                parser.need("->")
                return left, parser.name()
            interface = parser.sequence(")", pair)
            if not interface:
                parser.error("commutes needs operation pairs")
        spec = BridgeSpec(name, source, target, body, domain, tuple(interface))
    elif kind == "template":
        parser.need("[")
        parameters = parser.sequence("]", lambda: _template_parameter(parser))
        if not parameters or len({key for key, _ in parameters}) != len(parameters):
            parser.error("template needs distinct parameters")
        parser.need("=")
        body = _template_body(parser)
        kinds = {"obj": "sort", "op": "operation", "comb": "combinator",
                 "obs": "observation", "law": "law", "bridge": "bridge"}
        parameters = tuple((param, kinds.get(sort, sort)) for param, sort in parameters)
        try:
            pattern = _template_spec_pattern(body, parameters, produces)
        except ValueError as error:
            parser.error(str(error))
        spec = TemplateSpec(name, parameters, produces, pattern)
    elif kind == "operation":
        parser.need("(")
        params = parser.sequence(")", lambda: _typed(parser))
        parser.need("->")
        output = parser.name()
        if not is_valid_name("object", output) and not is_valid_name("operation", output):
            parser.error("expected output sort")
        parser.need("=")
        body = parser.expr()
        spec = OperationSpec(name, "transform", tuple(Edge(sort, name=param) for param, sort in params), Edge(output), "ASCII definition")
    elif kind == "combinator":
        parser.need("[")
        op_params = parser.sequence("]", lambda: _typed(parser, arrow=True))
        parser.need("(")
        params = parser.sequence(")", lambda: _typed(parser))
        if any(sort != "A" for _, sort in params):
            parser.error("compact combinator signatures use A")
        parser.need("->")
        if parser.name() != "A":
            parser.error("compact combinator signatures use A")
        parser.need("=")
        body = parser.expr()
        spec = CombinatorSpec(name, tuple(key for key, _ in (*op_params, *params)), tuple(key for key, _ in op_params), body)
    elif kind == "observation":
        parser.need("{")
        observed = parser.name()
        input_sorts = []
        if parser.eat(":"):
            input_sorts.append((observed, parser.name()))
            while parser.eat(","):
                input_sorts.append(_typed(parser))
        parser.need("}")
        parser.observation_arities = dict(parser.observation_arities)
        parser.observation_arities[name] = len(input_sorts) if input_sorts else 1
        result_sort = parser.name() if parser.eat("->") else None
        parser.need("=")
        if parser.peek() in ("not", "test"):
            condition = parser.cond()
            body = n.Case(((condition, n.Lit(True)),), n.Lit(False))
        else:
            body = parser.expr()
            if parser.peek() in ("and", "or"):
                condition = parser.cond_tail(n.Test(body))
                body = n.Case(((condition, n.Lit(True)),), n.Lit(False))
        probes = _probes(ctx)
        if ctx is None:
            probes = {parser.tokens[index + 1][0] for index, (token, _) in enumerate(parser.tokens[:-1])
                      if token == "?" and parser.tokens[index + 1][0] != name}
        reads = tuple(sorted({part.fn for part in n.walk(body) if isinstance(part, n.Call) and part.fn in probes}))
        extra = {"subject": observed}
        world = getattr(ctx, "world", ctx)
        truth = getattr(world, "observation", {}).get("truth") if world is not None else None
        if input_sorts:
            # A lone subject of the truth sort is a typed private observation: the sort is display only.
            private = len(input_sorts) == 1 and input_sorts[0][1] == truth
            extra["notation_inputs" if private else "inputs"] = tuple(input_sorts)
        if result_sort is not None:
            extra["notation_result"] = result_sort
        spec = ObservationSpec(name, reads, body, extra=extra)
    elif kind == "object":
        parser.need("=")
        if (is_valid_name("object", parser.peek()) and
                parser.tokens[parser.index + 1][0] == "["):
            template_name = parser.name()
            parser.need("[")
            arguments = parser.sequence("]", lambda: _template_argument(parser))
            if not arguments:
                parser.error("template needs arguments")
            body = template_name + "[" + ", ".join(arguments) + "]"
            spec = ObjectSpec(name, "constant", body=body, extra={"notation_instantiation": body})
        elif parser.eat("<"):
            fields = parser.sequence(">", lambda: _typed(parser))
            parser.need("where")
            valid = parser.expr()
            canon = None
            if parser.eat("canon"):
                canon = n.Call(parser.name())
            interface = ()
            if parser.eat("sealed"):
                parser.need("(")
                interface = tuple(parser.sequence(")", parser.name))
                if not interface:
                    parser.error("sealed object needs an interface")
            body = valid
            spec = ObjectSpec(name, "refine", base="Record", valid=valid, canon=canon,
                              sealed=bool(interface), interface=interface, extra={"notation_fields": fields})
        elif parser.peek() and re.fullmatch(r"[A-Z][A-Za-z_0-9]*", parser.peek()):
            tags = {}
            while True:
                tag = parser.name()
                if tag in tags:
                    parser.error("duplicate tag")
                if parser.eat("<"):
                    tags[tag] = [list(field) for field in parser.sequence(">", lambda: _typed(parser))]
                else:
                    tags[tag] = []
                if not parser.eat("|"):
                    break
            body = None
            spec = ObjectSpec(name, "compose", tags=tags)
        else:
            body = parser.expr()
            spec = ObjectSpec(name, "constant", body=body)
    if kind == "operation" and len({key for key, _ in params}) != len(params):
        parser.error("duplicate parameter")
    if kind == "combinator" and len({key for key, _ in (*op_params, *params)}) != len(op_params) + len(params):
        parser.error("duplicate parameter")
    suffix = parser.peek()
    if suffix == "given":
        parser.take()
        origin, layer = "given", 0
    elif re.fullmatch(r"L\d+", suffix) and int(suffix[1:]) > 0:
        parser.take()
        origin, layer = "invented", int(suffix[1:])
    elif program_mode and suffix in ("", "obj", "op", "comb", "obs", "law", "bridge", "template", "save"):
        origin, layer = "invented", 1
        spec.extra["layer_unspecified"] = True
    else:
        parser.error("expected given or L<n>")
    if not program_mode:
        parser.end()
    depends_on = _definition_refs(body, spec)
    if kind == "object" and spec.extra.get("notation_instantiation") and hasattr(ctx, "records"):
        from opulse.atoms.templates import instantiate

        template = ctx.records().get(template_name)
        if template is None:
            parser.error(f"unknown template {template_name}")
        if len(arguments) != len(template.spec.params):
            parser.error("template argument count mismatch")
        values = dict(zip((param for param, _ in template.spec.params), arguments))
        instance = instantiate(template, values, name, lib=ctx)
        if origin != "invented" or layer < instance.layer:
            parser.error("template instance layer must cover its dependencies")
        return replace(instance, layer=layer)
    return Definition(name, kind, origin, layer, depends_on, spec, body)


def parse_definition(text: str, ctx=None) -> Definition:
    try:
        return _parse_definition(text, ctx)
    except NotationError:
        raise
    except (ValueError, TypeError) as exc:
        raise NotationError(str(exc), len(text) + 1) from exc


def parse_program(text: str, ctx=None) -> list[Definition | str]:
    """Read declarations and ``save NAME`` statements; saves are returned as written strings."""
    def strip_comment(match):
        token = match.group()
        return token if token.startswith('"') else " " * len(token)

    clean = re.sub(r'"(?:\\.|[^"\\])*"|#(?=[ \t]|$)[^\n]*', strip_comment, text, flags=re.MULTILINE)
    parser = _Parser(clean, ctx)
    parser.program_mode = True
    items = []
    while parser.peek():
        if parser.eat("save"):
            items.append("save " + parser.name())
            continue
        try:
            definition = _parse_definition(clean, ctx, parser=parser)
        except (ValueError, TypeError) as exc:
            if isinstance(exc, NotationError):
                raise
            raise NotationError(str(exc), parser.tokens[parser.index][1]) from exc
        items.append(definition)
        parser.kinds[definition.name] = definition.kind
    return items
