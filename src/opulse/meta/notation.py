"""ASCII value notation (atoms-meta sections 2, 4 and 6).

EBNF (whitespace is insignificant)::

    code    = "Code<", ("op", params, ["->", edge] | "comb", params
            | "obs", "{", names, "}" | "obj"), "=", expr, ">", {where};
    params  = ["[", names, "]"], "(", [name, {",", name}], ")";
    edge    = name, ["!", name];
    where   = "where", ("#", hex, "=", code | "atom", name, "=", string);
    expr    = name | number | string | "&", name | value | name, "(", args, ")"
            | "let", name, "=", expr, "in", expr
            | "case", "{", {cond, "->", expr, ";"}, ["else", "->", expr], "}"
            | "rec", name, "(", names, ")", "=", expr, "measure",
              ("fuel" | "legacy" | expr), "on", "(", args, ")"
            | "blocks", "{", {"var", name, "=", expr, ";"},
              ["entry", name, ";"], {name, ":", {name, ":=", expr, ";"},
              ("goto", name | "if", cond, "goto", name, "else", name
              | "halt", expr), ["|"]}, "}";
    cond    = "always" | ["not"], cond | cond, ("and" | "or"), cond
            | "(", cond, ")" | ["test"], expr;
    value   = "true" | "false" | name, "<", name, [":", args], ">";

An instantiated template's unused provenance binding prints as
``let v0 = &"#<64-hex-template-hash>" in ...``; its template and arguments
follow in ``where`` clauses. The quoted hash is a literal operation reference,
not a call. Compact code omits signatures (operation edges default to ``int!bottom``),
atom digests and dependencies; its parser needs ``resolve`` for missing atoms
and dependencies. For portable exact source use ``signature=True, deps=True,
exact=True``. ``where atom`` lines preserve given-atom digests without a
resolver. Names outside the identifier alphabet are JSON-quoted.
"""

from __future__ import annotations

import json
import re

from opulse.atoms.values import FALSE, TRUE, Card
from opulse.meta import code as C
from opulse.meta.builder import world_value as W
from opulse.meta.vn import machine
from opulse.meta.vn.reference import State


class NotationError(ValueError):
    """A syntax or unresolved-reference error with a source location."""


_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9.]*\Z")
_TOKENS = re.compile(r'#[0-9a-f]{12,64}(?![A-Za-z_0-9])|"(?:\\.|[^"\\])*"|-?[0-9]+|[A-Za-z_][A-Za-z_0-9.]*|->|:=|[^\s]', re.ASCII)


def _name(text):
    return text if _IDENT.fullmatch(text) else json.dumps(text, ensure_ascii=True)


def _value(value):
    if value == TRUE:
        return "true"
    if value == FALSE:
        return "false"
    if isinstance(value, Card):
        return f"{_name(value.sort)}<{_name(value.tag)}" + (
            ": " + ", ".join(_value(field) for field in value.fields) if value.fields else "") + ">"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if type(value) is int:
        return str(value)
    raise ValueError(f"not a printable value: {value!r}")


def _expr(card, exact):
    tag, fields = card.tag, card.fields
    if tag == "var":
        return _name(fields[0])
    if tag == "lit":
        value = fields[0]
        return _show_code(value, True, True, True, True) if isinstance(value, Card) and value.sort == "code" else _value(value)
    if tag == "fn":
        return "&" + _name(fields[0])
    if tag == "call":
        name = fields[0]
        if re.fullmatch(r"#[0-9a-f]{64}", name) and not exact:
            name = name[:13]
        return (name if re.fullmatch(r"#[0-9a-f]{12,64}", name) else _name(name)) + "(" + ", ".join(
            _expr(arg, exact) for arg in C.items(fields[1])) + ")"
    if tag == "let":
        return f"let {_name(fields[0])} = {_expr(fields[1], exact)} in {_expr(fields[2], exact)}"
    if tag == "case":
        arms = [f"{_cond(arm.fields[0], exact)} -> {_expr(arm.fields[1], exact)}"
                for arm in C.items(fields[0])]
        if fields[1].tag == "some":
            arms.append("else -> " + _expr(fields[1].fields[0], exact))
        return "case { " + "; ".join(arms) + " }"
    if tag == "rec":
        measure = fields[4]
        rendered = measure.tag if measure.tag != "node" else _expr(measure.fields[0], exact)
        return (f"rec {'memo ' if len(fields) == 6 else ''}{_name(fields[0])}(" +
                ", ".join(map(_name, C.items(fields[1]))) +
                f") = {_expr(fields[2], exact)} measure {rendered} on (" +
                ", ".join(_expr(arg, exact) for arg in C.items(fields[3])) + ")")
    if tag == "blocks":
        parts = [f"var {_name(b.fields[0])} = {_expr(b.fields[1], exact)};" for b in C.items(fields[0])]
        blocks = C.items(fields[2])
        if not blocks or fields[1] != blocks[0].fields[0]:
            parts.append(f"entry {_name(fields[1])};")
        for block in blocks:
            label, assigns, end = block.fields
            assignment = " ".join(f"{_name(b.fields[0])} := {_expr(b.fields[1], exact)};"
                                  for b in C.items(assigns))
            if end.tag == "jump":
                terminal = "goto " + _name(end.fields[0])
            elif end.tag == "cjump":
                terminal = (f"if {_cond(end.fields[0], exact)} goto {_name(end.fields[1])} "
                            f"else {_name(end.fields[2])}")
            else:
                terminal = "halt " + _expr(end.fields[0], exact)
            parts.append(f"{_name(label)}: " + (assignment + " " if assignment else "") + terminal)
        prefix = " ".join(parts[:-len(blocks)])
        return "blocks { " + (prefix + " " if prefix else "") + " | ".join(parts[-len(blocks):]) + " }"
    raise ValueError(f"unknown expression {card!r}")


def _cond(card, exact, precedence=0):
    tag, fields = card.tag, card.fields
    if tag == "test":
        return _expr(fields[0], exact)
    if tag == "always":
        return "always"
    if tag == "not":
        result = "not " + _cond(fields[0], exact, 3)
        strength = 3
    else:
        strength = 2 if tag == "and" else 1
        result = (_cond(fields[0], exact, strength) + f" {tag} " +
                  _cond(fields[1], exact, strength + 1))
    return f"({result})" if strength < precedence else result


def _show_code(card, signature, deps, exact, nested=False):
    kind, sig, body, atoms, dependencies = card.fields
    if kind == "operation":
        ins, output = sig.fields
        params = [f"x{index}" + (": " + _name(edge.fields[0]) +
                  ("!" + _name(edge.fields[1]) if edge.fields[1] != "bottom" else "") if signature else "")
                  for index, edge in enumerate(C.items(ins))]
        header = "op (" + ", ".join(params) + ")"
        if signature:
            header += " -> " + _name(output.fields[0]) + (
                "!" + _name(output.fields[1]) if output.fields[1] != "bottom" else "")
    elif kind == "combinator":
        operator_positions = C.items(sig.fields[1])
        operators = set(operator_positions)
        header = ("comb [" + ", ".join(f"x{index}" for index in operator_positions)
                  + "] (" + ", ".join(f"x{index}" for index in range(sig.fields[0]) if index not in operators) + ")")
    elif kind == "observation":
        header = "obs {" + ", ".join(map(_name, C.items(sig.fields[0]))) + "}"
    elif kind == "law":
        header = "law #? (" + ", ".join(f"x{index}: {_name(pair.fields[1])}"
                                               for index, pair in enumerate(C.items(sig.fields[0]))) + ")"
    elif kind == "bridge":
        source, target, interface, domain = sig.fields
        header = "bridge ~? " + _name(source) + " -> " + _name(target)
        if C.items(interface):
            header += " interface {" + ", ".join(_name(pair.fields[0]) + ": " + _name(pair.fields[1])
                                                   for pair in C.items(interface)) + "}"
        if domain.tag == "some":
            header += " domain " + _body_expr(domain.fields[0], exact)
    elif kind == "template":
        header = "template [" + ", ".join(_name(pair.fields[0]) + ": " + _name(pair.fields[1])
                                               for pair in C.items(sig.fields[0])) + "] -> " + _name(sig.fields[1])
    else:
        header = "obj"
    result = "Code<" + header + " = " + (_value(body) if kind == "template" else _body_expr(body, exact))
    clauses = []
    if deps:
        for dependency in C.items(dependencies):
            if dependency.sort == "origin":
                template, arguments = dependency.fields
                clauses.append("where origin " + _value(template) + " args " + _value(arguments))
                continue
            clauses.append("where #" + C.code_hash(dependency) + " = " +
                           _show_code(dependency, True, True, True, True))
        for atom in C.items(atoms):
            clauses.append("where atom " + _name(atom.fields[0]) + " = " + _value(atom.fields[1]))
    if nested:
        return result + (" " + " ".join(clauses) if clauses else "") + ">"
    return result + ">" + ("\n" + "\n".join(clauses) if clauses else "")


def show_code(card: Card, signature=False, deps=False, exact=False) -> str:
    """Print a code value; ``signature=True, deps=True, exact=True`` is self-contained."""
    return _show_code(card, signature, deps, exact)


def _body_expr(body, exact):
    from opulse.atoms.notation import parse_expr, print_expr

    node = C.decode_node(body)
    try:
        printed = print_expr(node)
        if C.encode_node(parse_expr(printed)) == body:
            return printed
    except (TypeError, ValueError):
        pass
    return _expr(body, exact)


class _Parser:
    def __init__(self, text):
        if not text.isascii():
            raise NotationError("line 1, column 1: ASCII source required")
        self.text = text
        self.tokens = []
        end = 0
        for match in _TOKENS.finditer(text):
            if text[end:match.start()].strip():
                self.error_at(end, "invalid character")
            self.tokens.append((match.group(), match.start()))
            end = match.end()
        if text[end:].strip():
            self.error_at(end, "invalid character")
        self.index = 0

    def error_at(self, offset, message):
        line = self.text.count("\n", 0, offset) + 1
        column = offset - self.text.rfind("\n", 0, offset)
        raise NotationError(f"line {line}, column {column}: {message}")

    def error(self, message):
        self.error_at(self.tokens[self.index][1] if self.index < len(self.tokens) else len(self.text), message)

    def peek(self):
        return self.tokens[self.index][0] if self.index < len(self.tokens) else ""

    def take(self):
        if not self.peek():
            self.error("unexpected end of input")
        token = self.peek()
        self.index += 1
        return token

    def eat(self, token):
        if self.peek() == token:
            self.index += 1
            return True
        return False

    def need(self, token):
        if not self.eat(token):
            self.error(f"expected {token!r}")

    def name(self):
        token = self.peek()
        if token.startswith('"'):
            self.take()
            try:
                return json.loads(token)
            except ValueError:
                self.error("invalid string")
        if _IDENT.fullmatch(token):
            return self.take()
        self.error("expected name")

    def number(self):
        token = self.peek()
        if re.fullmatch(r"-?[0-9]+", token):
            self.take()
            return int(token)
        self.error("expected integer")

    def sequence(self, open_token, close_token, item):
        self.need(open_token)
        output = []
        if not self.eat(close_token):
            output.append(item())
            while self.eat(","):
                output.append(item())
            self.need(close_token)
        return output

    def body_expr(self):
        from opulse.atoms.notation import parse_expr

        depth = 0
        for end in range(self.index, len(self.tokens)):
            token = self.tokens[end][0]
            if token == "<":
                depth += 1
            elif token == ">":
                if depth == 0:
                    break
                depth -= 1
            elif token == "where" and depth == 0:
                break
        else:
            return self.expr()
        text = self.text[self.tokens[self.index][1]:self.tokens[end][1]].strip()
        try:
            node = parse_expr(text)
            if _body_expr(C.encode_node(node), True) == text:
                self.index = end
                return C.encode_node(node)
        except (ValueError, TypeError, C.CodeError):
            pass
        return self.expr()

    def domain_expr(self):
        from opulse.atoms.notation import parse_expr

        for end in range(self.index + 1, len(self.tokens)):
            if self.tokens[end][0] != "=":
                continue
            text = self.text[self.tokens[self.index][1]:self.tokens[end][1]].strip()
            try:
                node = parse_expr(text)
                card = C.encode_node(node)
                if _body_expr(card, True) == text:
                    self.index = end
                    return card
            except (TypeError, ValueError, C.CodeError):
                pass
        return self.expr()

    def value(self):
        token = self.peek()
        if token == "true":
            self.take()
            return TRUE
        if token == "false":
            self.take()
            return FALSE
        if token.startswith('"') and (self.index + 1 == len(self.tokens) or
                                      self.tokens[self.index + 1][0] != "<"):
            return self.name()
        if re.fullmatch(r"-?[0-9]+", token):
            return self.number()
        if token == "Code":
            return self.code(nested=True)
        sort = self.name()
        self.need("<")
        tag = self.name()
        fields = []
        if self.eat(":"):
            fields.append(self.value())
            while self.eat(","):
                fields.append(self.value())
        self.need(">")
        if sort == "expr" and tag == "rec" and len(fields) == 6 and fields[5] == TRUE:
            fields[5] = True
        return Card(sort, tag, tuple(fields))

    def expr(self):
        token = self.peek()
        if token == "let":
            self.take()
            name = self.name()
            self.need("=")
            value = self.expr()
            self.need("in")
            return Card("expr", "let", (name, value, self.expr()))
        if token == "case":
            self.take()
            self.need("{")
            arms = []
            default = Card("opt", "none")
            while self.peek() not in ("}", "else", ""):
                cond = self.cond()
                self.need("->")
                arms.append(Card("arm", "arm", (cond, self.expr())))
                if not self.eat(";"):
                    break
            if self.eat("else"):
                self.need("->")
                default = Card("opt", "some", (self.expr(),))
            self.need("}")
            return Card("expr", "case", (C.lst(arms), default))
        if token == "rec":
            self.take()
            memo = self.eat("memo")
            fn = self.name()
            params = self.sequence("(", ")", self.name)
            self.need("=")
            body = self.expr()
            self.need("measure")
            measure = Card("measure", self.take()) if self.peek() in ("fuel", "legacy") else Card(
                "measure", "node", (self.expr(),))
            self.need("on")
            args = self.sequence("(", ")", self.expr)
            return Card("expr", "rec", (fn, C.lst(params), body, C.lst(args), measure) +
                        ((True,) if memo else ()))
        if token == "blocks":
            return self.blocks()
        if self.eat("&"):
            return Card("expr", "fn", (self.reference(),))
        if token == "Code" or token in ("true", "false") or (
                token.startswith('"') and (self.index + 1 == len(self.tokens) or
                                            self.tokens[self.index + 1][0] not in ("<", "("))) or re.fullmatch(r"-?[0-9]+", token):
            return Card("expr", "lit", (self.value(),))
        name = self.reference()
        if self.peek() == "(":
            return Card("expr", "call", (name, C.lst(self.sequence("(", ")", self.expr))))
        if self.peek() == "<":
            self.need("<")
            tag = self.name()
            fields = []
            if self.eat(":"):
                fields = [self.value()]
                while self.eat(","):
                    fields.append(self.value())
            self.need(">")
            return Card("expr", "lit", (Card(name, tag, tuple(fields)),))
        return Card("expr", "var", (name,))

    def reference(self):
        if self.peek().startswith("#"):
            return self.take()
        return self.name()

    def cond(self, minimum=1):
        if self.eat("not"):
            left = Card("cond", "not", (self.cond(3),))
        elif self.eat("always"):
            left = Card("cond", "always")
        elif self.eat("("):
            left = self.cond()
            self.need(")")
        else:
            self.eat("test")
            left = Card("cond", "test", (self.expr(),))
        while self.peek() in ("and", "or") and (2 if self.peek() == "and" else 1) >= minimum:
            operator = self.take()
            left = Card("cond", operator, (left, self.cond((2 if operator == "and" else 1) + 1)))
        return left

    def blocks(self):
        self.need("blocks")
        self.need("{")
        variables = []
        while self.eat("var"):
            name = self.name()
            self.need("=")
            variables.append(Card("bind", "bind", (name, self.expr())))
            self.need(";")
        entry = None
        if self.eat("entry"):
            entry = self.name()
            self.need(";")
        blocks = []
        while self.peek() != "}":
            label = self.name()
            self.need(":")
            assignments = []
            while self.peek() not in ("goto", "if", "halt", ""):
                name = self.name()
                self.need(":=")
                assignments.append(Card("bind", "bind", (name, self.expr())))
                self.need(";")
            if self.eat("goto"):
                end = Card("end", "jump", (self.name(),))
            elif self.eat("if"):
                cond = self.cond()
                self.need("goto")
                then = self.name()
                self.need("else")
                end = Card("end", "cjump", (cond, then, self.name()))
            else:
                self.need("halt")
                end = Card("end", "halt", (self.expr(),))
            blocks.append(Card("block", "block", (label, C.lst(assignments), end)))
            if not self.eat("|"):
                break
        self.need("}")
        if not blocks:
            self.error("blocks need a labelled block")
        return Card("expr", "blocks", (C.lst(variables), entry or blocks[0].fields[0], C.lst(blocks)))

    def edge(self):
        sort = self.name()
        return (sort, self.name() if self.eat("!") else "bottom")

    def code(self, resolve=None, signature=None, nested=False):
        self.need("Code")
        self.need("<")
        kind = self.take()
        if kind == "op":
            self.need("(")
            edges = []
            if self.peek() != ")":
                while True:
                    self.name()
                    edges.append(self.edge() if self.eat(":") else None)
                    if not self.eat(","):
                        break
            self.need(")")
            output = self.edge() if self.eat("->") else None
            sig = C.sig_op([edge or ("int", "bottom") for edge in edges], output or ("int", "bottom"))
            if signature is not None and output is None and not any(edges):
                sig = signature
            kind = "operation"
        elif kind == "comb":
            operators = self.sequence("[", "]", self.name)
            values = self.sequence("(", ")", self.name)
            names = operators + values
            positions = [int(name[1:]) for name in names if re.fullmatch(r"x[0-9]+", name)]
            if sorted(positions) != list(range(len(names))):
                self.error("invalid combinator parameters")
            sig = C.sig_comb(len(names), [int(name[1:]) for name in operators])
            kind = "combinator"
        elif kind == "obs":
            sig = C.sig_obs(self.sequence("{", "}", self.name))
            kind = "observation"
        elif kind == "law":
            self.need("#")
            self.need("?")
            def law_var():
                name = self.name()
                self.need(":")
                return name, self.name()
            sig = C.sig_law(self.sequence("(", ")", law_var))
            kind = "law"
        elif kind == "bridge":
            self.need("~")
            self.need("?")
            source = self.name()
            self.need("->")
            target = self.name()
            interface = []
            if self.eat("interface"):
                def interface_pair():
                    source_op = self.name()
                    self.need(":")
                    return source_op, self.name()
                interface = self.sequence("{", "}", interface_pair)
            domain = self.domain_expr() if self.eat("domain") else None
            sig = C.sig_bridge(source, target, interface, C.decode_node(domain) if domain else None)
            kind = "bridge"
        elif kind == "template":
            def parameter():
                name = self.name()
                self.need(":")
                return name, self.name()
            params = self.sequence("[", "]", parameter)
            self.need("->")
            sig = C.sig_template(params, self.name())
            kind = "template"
        elif kind == "obj":
            sig = C.sig_const()
            kind = "object"
        else:
            self.error("unknown code kind")
        self.need("=")
        body = self.value() if kind == "template" else self.body_expr()
        deps = {}
        atom_digests = {}
        if not nested:
            self.need(">")
        while self.eat("where"):
            if self.eat("origin"):
                template = self.value()
                self.need("args")
                origin = Card("origin", "template", (template, self.value()))
                deps["origin"] = origin
            elif self.eat("atom"):
                name = self.name()
                self.need("=")
                digest = self.value()
                if not isinstance(digest, str) or name in atom_digests:
                    self.error("invalid atom digest")
                atom_digests[name] = digest
            else:
                hash_token = self.take()
                if not re.fullmatch(r"#[0-9a-f]{12,64}", hash_token):
                    self.error("invalid dependency hash")
                self.need("=")
                dep = self.code(resolve, nested=True)
                digest = C.code_hash(dep)
                if not digest.startswith(hash_token[1:]) or hash_token in deps:
                    self.error("dependency hash mismatch")
                deps[hash_token] = dep
        if nested:
            self.need(">")
        def lookup(name):
            if name.startswith("#") and name not in atom_digests:
                matches = [dep for prefix, dep in deps.items() if dep.sort == "code" and
                           (prefix == name or C.code_hash(dep).startswith(name[1:]))]
                if len(matches) == 1:
                    return C.Resolved(code=matches[0])
                if resolve is not None and not callable(resolve):
                    matches = [value for key, value in resolve.items() if isinstance(key, str) and
                               key.startswith(name) and len(key) == 65]
                    if len(matches) == 1:
                        value = matches[0]
                        return value if isinstance(value, C.Resolved) else C.Resolved(code=value)
            if name in atom_digests:
                return C.Resolved(digest=atom_digests[name])
            value = resolve(name) if callable(resolve) else resolve.get(name) if resolve else None
            if isinstance(value, C.Resolved):
                return value
            if isinstance(value, Card):
                return C.Resolved(code=value)
            if isinstance(value, str):
                return C.Resolved(digest=value)
            return None
        try:
            canonical_body = self.expand_hashes(body, deps, lookup)
            card = C.make_code(kind, sig, tuple(f"x{i}" for i in range(C.sig_arity(sig))),
                               canonical_body if kind == "template" else C.decode_node(canonical_body), lookup)
            if "origin" in deps:
                card = Card("code", "def", (*card.fields[:4], C.lst((*C.items(card.fields[4]), deps["origin"]))))
        except (C.CodeError, KeyError, ValueError) as exc:
            self.error(str(exc))
        return card

    def expand_hashes(self, value, deps, lookup):
        if not isinstance(value, Card):
            return value
        if (value.sort == "expr" and value.tag in ("call", "fn") and
                re.fullmatch(r"#[0-9a-f]{12,64}", value.fields[0]) and
                lookup(value.fields[0]) is not None and lookup(value.fields[0]).code is not None):
            prefix = value.fields[0][1:]
            matches = [C.code_hash(dep) for dep in deps.values()
                       if dep.sort == "code" and C.code_hash(dep).startswith(prefix)]
            if not matches:
                resolved = lookup(value.fields[0])
                if resolved is not None and resolved.code is not None:
                    digest = C.code_hash(resolved.code)
                    if digest.startswith(prefix):
                        matches = [digest]
            if len(matches) != 1:
                self.error("unresolved or ambiguous dependency hash")
            return Card(value.sort, value.tag, ("#" + matches[0],) +
                        tuple(self.expand_hashes(field, deps, lookup) for field in value.fields[1:]))
        return Card(value.sort, value.tag, tuple(self.expand_hashes(field, deps, lookup) for field in value.fields))

    def finish(self):
        if self.peek():
            self.error("unexpected token")


def parse_code(text, resolve=None, signature=None) -> Card:
    """Parse code; ``resolve`` maps names to digests or ``Resolved`` records."""
    parser = _Parser(text)
    result = parser.code(resolve, signature)
    parser.finish()
    return result


def show_vn(state_card: Card, compact=False) -> str:
    """Print a vn/1 state (spec 4.1); compact memory has an explicit size."""
    state = machine.from_card(state_card)
    memory = list(state.mem)
    if compact:
        while memory and memory[-1] == 0:
            memory.pop()
    contents = ", ".join(map(str, memory))
    mem = f"Mem<{len(state.mem)}: {contents}>" if compact else f"Mem<{contents}>"
    return f"VN<pc={state.pc}, a={state.a}, halted={str(state.halted).lower()}, mem={mem}>"


def parse_vn(text) -> Card:
    parser = _Parser(text)
    parser.need("VN")
    parser.need("<")
    fields = {}
    while True:
        name = parser.name()
        if name in fields:
            parser.error("duplicate vn field")
        parser.need("=")
        if name == "mem":
            parser.need("Mem")
            parser.need("<")
            prefix = parser.number() if re.fullmatch(r"[0-9]+", parser.peek()) and (
                parser.index + 1 < len(parser.tokens) and parser.tokens[parser.index + 1][0] == ":") else None
            if prefix is not None:
                parser.need(":")
            values = []
            if parser.peek() != ">":
                values.append(parser.number())
                while parser.eat(","):
                    values.append(parser.number())
            parser.need(">")
            if prefix is not None:
                if len(values) > prefix:
                    parser.error("memory exceeds size")
                values += [0] * (prefix - len(values))
            fields[name] = tuple(values)
        elif name == "halted":
            flag = parser.take()
            if flag not in ("true", "false"):
                parser.error("expected boolean")
            fields[name] = flag == "true"
        elif name in ("pc", "a"):
            fields[name] = parser.number()
        else:
            parser.error("unknown vn field")
        if not parser.eat(","):
            break
    parser.need(">")
    parser.finish()
    if set(fields) != {"pc", "a", "halted", "mem"}:
        parser.error("missing vn field")
    try:
        return machine.to_card(State(fields["pc"], fields["a"], fields["mem"], fields["halted"]))
    except ValueError as exc:
        parser.error(str(exc))


def show_world(world_card: Card) -> str:
    """Print every field of a builder world, including rows and tags (spec 6.1)."""
    if world_card.sort != "world" or world_card.tag != "world" or len(world_card.fields) not in (10, 11):
        raise ValueError("not a world value")
    name, version, sorts, ops, nodes, recursion, probes, view, kinds, tags = world_card.fields[:10]
    lines = [f"World<{_name(name)}@{version}"]
    for sort in C.items(sorts):
        if sort.tag == "enum":
            lines.append("  sort " + _name(sort.fields[0]) + " = enum {" +
                         ", ".join(map(_name, C.items(sort.fields[1]))) + "};")
        else:
            lines.append(f"  sort {_name(sort.fields[0])} = range({sort.fields[1]}, {sort.fields[2]});")
    for op in C.items(ops):
        if op.tag == "body":
            lines.append("  body " + _name(op.fields[0]) + " = " +
                         show_code(op.fields[1], signature=True, deps=True, exact=True).replace("\n", "\n  ") + ";")
            continue
        op_name, role, inputs, output, errors, rows, cost = op.fields
        lines.append("  table " + _name(op_name) + " role " + _name(role) + " (" +
                     ", ".join(map(_name, C.items(inputs))) + ") -> " + _name(output) +
                     " errors {" + ", ".join(map(_name, C.items(errors))) + f"}} cost {cost} {{")
        for row in C.items(rows):
            args, cell = row.fields
            output_text = _value(cell.fields[0]) if cell.tag == "val" else "err(" + _name(cell.fields[0]) + ")"
            lines.append("    " + _name(op_name) + "(" + ", ".join(map(_value, C.items(args))) + ") = " + output_text + ";")
        lines.append("  }")
    for label, values in (("nodes", nodes), ("probes", probes), ("open_kinds", kinds)):
        lines.append("  " + label + " {" + ", ".join(map(_name, C.items(values))) + "};")
    lines.extend(("  recursion " + _name(recursion) + ";", "  judge_view " + _name(view) + ";"))
    for tag in C.items(tags):
        lines.append("  tag " + _name(tag.fields[0]) + " = " + _value(tag.fields[1]) + ";")
    if len(world_card.fields) == 11:
        lines.append("  laws {")
        for law in C.items(world_card.fields[10]):
            lines.append("    #" + _name(law.fields[0]) + " = " +
                         show_code(law.fields[1], signature=True, deps=True, exact=True).replace("\n", "\n    ") + ";")
        lines.append("  };")
    return "\n".join(lines + [">"])


def parse_world(text) -> Card:
    parser = _Parser(text)
    parser.need("World")
    parser.need("<")
    name = parser.name()
    parser.need("@")
    version = parser.number()
    sorts, ops, tags, laws = [], [], [], []
    attributes = {}
    while parser.peek() != ">":
        label = parser.take()
        if label == "sort":
            sort_name = parser.name()
            parser.need("=")
            if parser.eat("enum"):
                sorts.append(W.enum(sort_name, parser.sequence("{", "}", parser.name)))
            else:
                parser.need("range")
                pair = parser.sequence("(", ")", parser.number)
                if len(pair) != 2:
                    parser.error("range needs two bounds")
                sorts.append(W.range_sort(sort_name, *pair))
            parser.need(";")
        elif label == "table":
            op_name = parser.name()
            parser.need("role")
            role = parser.name()
            inputs = parser.sequence("(", ")", parser.name)
            parser.need("->")
            output = parser.name()
            parser.need("errors")
            errors = parser.sequence("{", "}", parser.name)
            parser.need("cost")
            cost = parser.number()
            parser.need("{")
            rows = []
            while parser.peek() != "}":
                if parser.name() != op_name:
                    parser.error("row operation mismatch")
                args = parser.sequence("(", ")", parser.value)
                parser.need("=")
                if parser.eat("err"):
                    parser.need("(")
                    cell = W.err(parser.name())
                    parser.need(")")
                else:
                    cell = W.val(parser.value())
                parser.need(";")
                rows.append(W.row(args, cell))
            parser.need("}")
            ops.append(W.table(op_name, role, inputs, output, errors, rows, cost))
        elif label == "body":
            op_name = parser.name()
            parser.need("=")
            ops.append(W.body(op_name, parser.code()))
            parser.need(";")
        elif label in ("nodes", "probes", "open_kinds"):
            if label in attributes:
                parser.error("duplicate world field")
            attributes[label] = parser.sequence("{", "}", parser.name)
            parser.need(";")
        elif label in ("recursion", "judge_view"):
            if label in attributes:
                parser.error("duplicate world field")
            attributes[label] = parser.name()
            parser.need(";")
        elif label == "tag":
            tag_name = parser.name()
            parser.need("=")
            tags.append(W.tag(tag_name, parser.value()))
            parser.need(";")
        elif label == "laws":
            if "laws" in attributes:
                parser.error("duplicate world field")
            attributes["laws"] = True
            parser.need("{")
            while parser.peek() != "}":
                parser.need("#")
                law_name = parser.name()
                parser.need("=")
                laws.append(W.law(law_name, parser.code()))
                if not parser.eat(";") and parser.peek() != "}":
                    parser.need(",")
            parser.need("}")
            parser.need(";")
        else:
            parser.error("unknown world field")
    parser.need(">")
    parser.finish()
    if set(attributes) - {"laws"} != {"nodes", "probes", "open_kinds", "recursion", "judge_view"}:
        parser.error("missing world field")
    if "laws" in attributes and not laws:
        parser.error("empty laws field")
    return W.world(name, version, sorts, ops, attributes["nodes"], attributes["recursion"],
                   attributes["probes"], attributes["judge_view"], attributes["open_kinds"], tags, laws)
