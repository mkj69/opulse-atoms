"""Copyable ASCII notation for atoms-v2 expressions and declarations."""

from __future__ import annotations

import json
import re

from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom, Card


def _display(name, state=None):
    if state is None and re.fullmatch(r"k[0-9]+", name):
        return "@" + name
    if state is None and re.fullmatch(r"l[0-9]+", name):
        return "#" + name
    if state is None and re.fullmatch(r"b[0-9]+", name):
        return "~" + name
    if state is None and re.fullmatch(r"q[0-9]+", name):
        return "?" + name
    if state is not None:
        entry = getattr(state, "entries", {}).get(name)
        kind = getattr(entry, "kind", None)
        if kind is None:
            for atom in getattr(getattr(state, "world", None), "atoms", ()):
                if atom.name == name:
                    kind = getattr(atom, "kind", None)
                    break
        if kind == "combinator":
            return "@" + name
        if kind == "observation":
            return "?" + name
        if kind == "law":
            return "#" + name
        if kind == "bridge":
            return "~" + name
    return name


def _infix(state):
    """Only declared, given arithmetic operations may use operator notation."""
    if state is None or not hasattr(state, "world"):
        return {}
    return {spec.extra["symbol"]: spec.name for spec in state.world.decl.operations
            if spec.extra.get("symbol") in ("+", "-", "*") and len(spec.inputs) == 2}


def _value(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, Bottom):
        return f"fail({json.dumps(value.reason, ensure_ascii=True)})"
    if isinstance(value, Card):
        fields = ", ".join(_value(field) for field in value.fields)
        if value.tag == "items":
            return f"{value.sort}<{fields}>"
        return f"{value.sort}<{value.tag}: {fields}>" if fields else f"{value.sort}<{value.tag}:>"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, int):
        return str(value)
    from opulse.atoms.kernel import FnRef
    from opulse.worlds.perm import Permutation

    if isinstance(value, FnRef):  # an operation passed as a value (function sorts, plugged slots)
        return "ref(" + json.dumps(value.name, ensure_ascii=True) + ")"
    if isinstance(value, Permutation):
        return "Perm<" + ", ".join(str(item) for item in value) + ">"
    if isinstance(value, tuple):  # host sequences of classic worlds: list[int] values, grid rows
        return "tuple(" + ", ".join(_value(item) for item in value) + ")"
    raise TypeError(f"no ASCII notation for {value!r}")


def _condition(cond, state):
    if isinstance(cond, n.Test):
        if isinstance(cond.expr, n.Call) and cond.expr.fn in ("always", "and", "or", "not", "test"):
            return "test(" + print_node(cond.expr, state) + ")"
        return _child(cond.expr, state)
    if isinstance(cond, n.Always):
        return "always()"
    if isinstance(cond, n.Not):
        return "not(" + _condition(cond.operand, state) + ")"
    if isinstance(cond, (n.And, n.Or)):
        name = "and" if isinstance(cond, n.And) else "or"
        return name + "(" + _condition(cond.left, state) + ", " + _condition(cond.right, state) + ")"
    raise TypeError(f"unsupported condition: {cond!r}")


def _child(node, state):
    text = print_node(node, state)
    return f"({text})" if isinstance(node, (n.Let, n.Case, n.Rec)) else text


def print_node(node, state_or_names=None):
    """Print an expression using only ASCII; names are resolved from an optional GenState."""
    state = state_or_names
    if isinstance(node, n.Var):
        return node.name
    if isinstance(node, n.Lit):
        return _value(node.value)
    if isinstance(node, n.Call):
        args = node.args
        name = _display(node.fn, state)
        symbol = next((symbol for symbol, op in _infix(state).items() if op == node.fn), None)
        if symbol is not None and len(args) == 2:
            left, right = (_child(arg, state) for arg in args)
            if isinstance(args[0], n.Call) and args[0].fn in _infix(state).values():
                left = f"({left})"
            if isinstance(args[1], n.Call) and args[1].fn in _infix(state).values():
                right = f"({right})"
            return f"{left} {symbol} {right}"
        from opulse.atoms.kernel import FnRef

        slots = []
        while len(slots) < len(args) and isinstance(args[len(slots)], n.Lit) and isinstance(args[len(slots)].value, FnRef):
            slots.append(args[len(slots)].value.name)
        if name.startswith("@") or (slots and not name.startswith("?")):
            return name + "[" + ", ".join(slots) + "](" + ", ".join(_child(arg, state) for arg in args[len(slots):]) + ")"
        if name.startswith("?"):
            return name + "{" + ", ".join(_child(arg, state) for arg in args) + "}"
        return name + "(" + ", ".join(_child(arg, state) for arg in args) + ")"
    if isinstance(node, n.Let):
        return f"let {node.name} = {_child(node.value, state)} in {_child(node.body, state)}"
    if isinstance(node, n.Case):
        if not node.arms:
            return "case(" + (_child(node.default, state) if node.default is not None else "") + ")"
        parts = [f"{'if' if index == 0 else 'elif'} {_condition(cond, state)} then {_child(body, state)}"
                 for index, (cond, body) in enumerate(node.arms)]
        if node.default is not None:
            parts.append("else " + _child(node.default, state))
        return " ".join(parts)
    if isinstance(node, n.Rec):
        measure = node.measure if isinstance(node.measure, str) else _child(node.measure, state)
        memo = "[memo]" if node.memo else ""
        return (f"rec{memo} {node.fn}({', '.join(node.params)}) = {_child(node.body, state)} "
                f"measure {measure} in {node.fn}({', '.join(_child(arg, state) for arg in node.args)})")
    if isinstance(node, n.Blocks):
        return "blocks(" + json.dumps(n.to_json(node), sort_keys=True, ensure_ascii=True, separators=(",", ":")) + ")"
    raise TypeError(f"unsupported kernel node: {node!r}")


def _body(body, state):
    if isinstance(body, n.NODE_TYPES):
        return print_node(body, state)
    if body is None:
        return "none"
    return json.dumps(body, sort_keys=True, ensure_ascii=True)


def print_declaration(entry, state):
    """Print a given or invented definition with its kind-specific interface."""
    if entry.kind == "law":
        if hasattr(entry, "text"):
            return entry.text(state).encode("ascii").decode("ascii")
        spec = state.library.get(entry.name).spec
        variables = ", ".join(f"{name}: {sort}" for name, sort in spec.vars)
        return f"law #{entry.name}: {print_node(spec.statement, state)} for {variables}  L{entry.layer}"
    if entry.kind == "bridge":
        if hasattr(entry, "notation"):
            return entry.notation().encode("ascii").decode("ascii")
        spec = state.library.get(entry.name).spec
        return f"bridge ~{entry.name}: {spec.source} -> {spec.target}  L{entry.layer}"
    try:
        defn = state.library.get(entry.name)
    except KeyError:
        from opulse.atoms.spec import Definition

        declarations = (state.world.decl.objects if entry.kind == "object" else
                        state.world.decl.operations if entry.kind == "operation" else ())
        spec = next(item for item in declarations if item.name == entry.name)
        defn = Definition(entry.name, entry.kind, "given", 0, (), spec, None)
    spec = defn.spec
    suffix = "given" if defn.origin == "given" else f"L{defn.layer}"
    if defn.kind == "operation":
        names = spec.extra.get("input_names", [edge.name or f"arg{index}" for index, edge in enumerate(spec.inputs)])
        args = ", ".join(f"{name}: {edge.sort}" for name, edge in zip(names, spec.inputs))
        head = f"op {defn.name}({args}) -> {spec.output.sort}"
        detail = _body(defn.body, state)
    elif defn.kind == "object":
        head = f"obj {defn.name}"
        if spec.form == "compose":
            tags = []
            for tag, fields in spec.tags.items():
                pairs = fields.items() if isinstance(fields, dict) else fields
                tags.append(tag + "(" + ", ".join(f"{name}: {sort}" for name, sort in pairs) + ")")
            detail = "<" + " | ".join(tags) + ">"
        elif spec.form == "refine":
            detail = f"refine {spec.base} where {_body(spec.valid, state)}"
            if spec.canon is not None:
                detail += "; canon " + _body(spec.canon, state)
        elif spec.form == "constant":
            detail = _body(spec.body, state)
        else:
            detail = "primitive"
        if spec.sealed:
            detail += " sealed (" + ", ".join(spec.interface) + ")"
    elif defn.kind == "combinator":
        signature = entry.signature
        slots = []
        for index, name in enumerate(spec.op_params):
            slot = signature.op_inputs[index] if signature and index < len(signature.op_inputs) else None
            slots.append(name + ": " + (" -> ".join((*slot.inputs, slot.output)) if slot else "op"))
        params = [name for name in spec.params if name not in spec.op_params]
        args = ", ".join(f"{name}: {signature.inputs[index] if signature and index < len(signature.inputs) else 'value'}"
                         for index, name in enumerate(params))
        head = f"comb @{defn.name}[{', '.join(slots)}]({args}) -> {signature.output if signature else 'value'}"
        detail = _body(defn.body, state)
    elif defn.kind == "observation":
        signature = entry.signature
        inputs = signature.inputs if signature else ("state",)
        args = ", ".join(f"{'s' if len(inputs) == 1 else f'arg{index}'}: {sort}"
                         for index, sort in enumerate(inputs))
        head = f"obs ?{defn.name}{{{args}}}"
        detail = _body(defn.body, state)
    else:
        raise ValueError(defn.kind)
    result = f"{head} = {detail}  {suffix}"
    return result.encode("ascii").decode("ascii")


_TOKEN = re.compile(r'\s*("(?:\\.|[^"\\])*"|-?\d+|[A-Za-z_][\w.]*|[@?~]|[^\s])', re.ASCII)


class _Parser:
    def __init__(self, text, state=None):
        self.tokens = _TOKEN.findall(text)
        self.index = 0
        self.infix = _infix(state)

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or expected is not None and token != expected:
            raise ValueError(f"expected {expected or 'term'}, got {token!r}")
        self.index += 1
        return token

    def sequence(self, end):
        items = []
        if self.peek() != end:
            while True:
                items.append(self.term())
                if self.peek() != ",":
                    break
                self.take(",")
        self.take(end)
        return tuple(items)

    def condition(self):
        if self.peek() == "test" and self.index + 1 < len(self.tokens) and self.tokens[self.index + 1] == "(":
            self.take("test")
            self.take("(")
            expr = self.term()
            self.take(")")
            return n.Test(expr)
        if self.peek() == "always" and self.index + 1 < len(self.tokens) and self.tokens[self.index + 1] == "(":
            self.take("always")
            self.take("(")
            self.take(")")
            return n.Always()
        if self.peek() in ("and", "or", "not") and self.index + 1 < len(self.tokens) and self.tokens[self.index + 1] == "(":
            name = self.take()
            self.take("(")
            first = self.condition()
            if name == "not":
                self.take(")")
                return n.Not(first)
            self.take(",")
            second = self.condition()
            self.take(")")
            return n.And(first, second) if name == "and" else n.Or(first, second)
        return n.Test(self.term())

    def term(self, minimum=0):
        left = self.primary()
        while self.peek() in self.infix and {"+": 1, "-": 1, "*": 2}[self.peek()] >= minimum:
            symbol = self.take()
            left = n.Call(self.infix[symbol], (left, self.term({"+": 1, "-": 1, "*": 2}[symbol] + 1)))
        return left

    def primary(self):
        token = self.take()
        if token == "(":
            node = self.term()
            self.take(")")
            return node
        if token == "let":
            name = self.take()
            self.take("=")
            value = self.term()
            self.take("in")
            return n.Let(name, value, self.term())
        if token == "if":
            arms = []
            while True:
                cond = self.condition()
                self.take("then")
                body = self.term()
                arms.append((cond, body))
                if self.peek() != "elif":
                    break
                self.take("elif")
            default = self.term() if self.peek() == "else" and self.take("else") else None
            return n.Case(tuple(arms), default)
        if token == "case":
            self.take("(")
            default = self.term() if self.peek() != ")" else None
            self.take(")")
            return n.Case((), default)
        if token == "rec":
            memo = False
            if self.peek() == "[":
                self.take("[")
                self.take("memo")
                self.take("]")
                memo = True
            name = self.take()
            self.take("(")
            params = []
            if self.peek() != ")":
                while True:
                    params.append(self.take())
                    if self.peek() != ",":
                        break
                    self.take(",")
            self.take(")")
            self.take("=")
            body = self.term()
            self.take("measure")
            measure = self.take() if self.peek() in ("fuel", "legacy") else self.term()
            self.take("in")
            self.take(name)
            self.take("(")
            return n.Rec(name, tuple(params), body, self.sequence(")"), measure, memo)
        if token == "blocks":
            self.take("(")
            start = self.index
            depth = 1
            while depth:
                current = self.take()
                depth += (current == "(") - (current == ")")
            return n.from_json(json.loads("".join(self.tokens[start:self.index - 1])))
        if token == "~":
            name = self.take()
            self.take("(")
            return n.Call("~" + name, self.sequence(")"))
        if token in ("@", "?"):
            name = self.take()
            if token == "?":
                self.take("{")
                return n.Call(name, self.sequence("}"))
            from opulse.atoms.kernel import FnRef

            self.take("[")
            slots = []
            if self.peek() != "]":
                while True:
                    slots.append(n.Lit(FnRef(self.take())))
                    if self.peek() != ",":
                        break
                    self.take(",")
            self.take("]")
            self.take("(")
            return n.Call(name, tuple(slots) + self.sequence(")"))
        if token == "true":
            return n.Lit(True)
        if token == "false":
            return n.Lit(False)
        if token[0] == '"':
            return n.Lit(json.loads(token))
        if re.fullmatch(r"-?\d+", token):
            return n.Lit(int(token))
        if token == "fail":
            self.take("(")
            reason = self.take()
            self.take(")")
            return n.Lit(Bottom(json.loads(reason) if reason.startswith('"') else reason))
        if token == "ref" and self.peek() == "(":
            from opulse.atoms.kernel import FnRef

            self.take("(")
            name = json.loads(self.take())
            self.take(")")
            return n.Lit(FnRef(name))
        if token == "tuple" and self.peek() == "(":
            self.take("(")
            items = self.sequence(")")
            if not all(isinstance(item, n.Lit) for item in items):
                raise ValueError("tuple elements must be literal values")
            return n.Lit(tuple(item.value for item in items))
        if self.peek() == "<":
            self.take("<")
            if self.peek() == ">" or self.index + 1 >= len(self.tokens) or self.tokens[self.index + 1] != ":":
                fields = self.sequence(">")
                if not all(isinstance(field, n.Lit) for field in fields):
                    raise ValueError("card fields must be literal values")
                if token == "Perm":
                    from opulse.worlds.perm import Permutation

                    return n.Lit(Permutation(tuple(field.value for field in fields)))
                return n.Lit(Card(token, "items", tuple(field.value for field in fields)))
            tag = self.take()
            self.take(":")
            fields = self.sequence(">")
            if not all(isinstance(field, n.Lit) for field in fields):
                raise ValueError("card fields must be literal values")
            return n.Lit(Card(token, tag, tuple(field.value for field in fields)))
        if self.peek() == "[":  # a call with operation slots, e.g. M11.fold[f, add](x)
            from opulse.atoms.kernel import FnRef

            self.take("[")
            slots = []
            while self.peek() != "]":
                slots.append(n.Lit(FnRef(self.take())))
                if self.peek() == ",":
                    self.take(",")
            self.take("]")
            self.take("(")
            return n.Call(token, tuple(slots) + self.sequence(")"))
        if self.peek() == "(":
            self.take("(")
            return n.Call(token, self.sequence(")"))
        return n.Var(token)


def parse_term(text, state_or_names=None):
    """Parse an ASCII expression; reject trailing or malformed input."""
    parser = _Parser(text, state_or_names)
    term = parser.term()
    if parser.peek() is not None:
        raise ValueError(f"unexpected token: {parser.peek()!r}")
    return term


def parse_declaration(text, state_or_names=None):
    """Read a declaration's typed head, independent of the body syntax."""
    law = re.fullmatch(r"law\s+#([A-Za-z_]\w*):\s*(.*?)\s+for\s+(.+?)\s{2}L(\d+)",
                       text, re.ASCII | re.DOTALL)
    if law:
        params = []
        for part in law[3].split(","):
            field = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*:\s*([A-Za-z_][\w.]*)\s*", part, re.ASCII)
            if field is None:
                raise ValueError("invalid law parameter")
            params.append((field[1], field[2]))
        statement = parse_term(law[2], state_or_names)
        return {"name": law[1], "kind": "law", "params": params, "op_params": [],
                "output": "bool", "layer": int(law[4]), "statement": statement}
    bridge = re.fullmatch(r"bridge\s+~([A-Za-z_]\w*):\s*([\w.]+)\s*->\s*([\w.]+)\s{2}L(\d+)(?:\s{2}(forget_failure_reasons))?",
                          text, re.ASCII)
    if bridge:
        return {"name": bridge[1], "kind": "bridge", "params": [], "op_params": [],
                "output": bridge[3], "source": bridge[2], "target": bridge[3],
                "layer": int(bridge[4]), "forget_failure_reasons": bool(bridge[5])}
    match = re.fullmatch(r"(op|obj|comb|obs)\s+([@?]?[A-Za-z_][\w.]*)\s*(.*?)\s{2}(L\d+|given)", text, re.ASCII | re.DOTALL)
    if match is None:
        raise ValueError("invalid ASCII declaration")
    prefix, decorated_name, content, suffix = match.groups()
    kind = {"op": "operation", "obj": "object", "comb": "combinator", "obs": "observation"}[prefix]
    expected = {"object": "", "operation": "", "combinator": "@", "observation": "?"}[kind]
    if decorated_name[:1] in ("@", "?") and decorated_name[:1] != expected or expected and not decorated_name.startswith(expected):
        raise ValueError("invalid declaration sigil")
    name = decorated_name.lstrip("@?")
    params = []
    op_params = []
    output = None

    def typed(items):
        if not items.strip():
            return []
        result = []
        for item in items.split(","):
            field = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*:\s*(.*?)\s*", item, re.ASCII)
            if field is None:
                raise ValueError("invalid typed parameter")
            result.append((field[1], field[2]))
        return result

    if kind == "operation":
        head = re.match(r"\(([^)]*)\)\s*->\s*([\w.]+)\s*=\s*", content, re.ASCII)
        if head is None:
            raise ValueError("invalid operation head")
        params, output = typed(head[1]), head[2]
    elif kind == "combinator":
        head = re.match(r"\[([^]]*)\]\(([^)]*)\)\s*->\s*([\w.]+)\s*=\s*", content, re.ASCII)
        if head is None:
            raise ValueError("invalid combinator head")
        op_params, params, output = typed(head[1]), typed(head[2]), head[3]
    elif kind == "observation":
        head = re.match(r"\{([^}]*)\}\s*=\s*", content, re.ASCII)
        if head is None:
            raise ValueError("invalid observation head")
        params = typed(head[1])
    else:
        if not content.startswith("= "):
            raise ValueError("invalid object head")
        body = content[2:]
        if body.startswith("<"):
            tag = re.match(r"<[^<(]+\(([^)]*)\)", body, re.ASCII)
            if tag:
                params = typed(tag[1])
        output = name
    return {"name": name, "kind": kind, "params": params, "op_params": op_params,
            "output": output, "layer": 0 if suffix == "given" else int(suffix[1:])}


_PART = re.compile(r'\s+|"(?:\\.|[^"\\])*"|(?:@|\?|\#|~)?[A-Za-z_][\w.]*|-?\d+|->|.', re.ASCII | re.DOTALL)
_KEYWORDS = {"op", "obj", "comb", "obs", "law", "bridge", "for", "if", "then", "elif", "else", "let", "in",
             "rec", "measure", "memo", "case", "tuple", "ref", "test", "refine", "where", "canon", "sealed", "given",
             "fail", "true", "false"}


def tokens(node_or_declaration, state):
    """Return lossless display tokens for an expression or declaration."""
    if isinstance(node_or_declaration, n.NODE_TYPES):
        text = print_node(node_or_declaration, state)
    elif isinstance(node_or_declaration, str):
        text = node_or_declaration
    else:
        text = print_declaration(node_or_declaration, state)
    given_names = {atom.name for atom in state.world.atoms}
    given_names.update(spec.name for spec in state.world.decl.objects)
    given_names.update(spec.name for spec in state.world.decl.operations)
    symbols = _infix(state)
    result = []
    for part in _PART.findall(text):
        name = part.lstrip("@?#~")
        entry = state.entries.get(name)
        if entry is not None:
            kind = entry.kind
        elif name in given_names:
            kind = "object" if name in {spec.name for spec in state.world.decl.objects} else "operation"
        elif part in symbols:
            name = symbols[part]
            kind = "operation"
        elif part.startswith("#"):
            kind = "law"
        elif part.startswith("~"):
            kind = "bridge"
        elif part.startswith("@"):
            kind = "combinator"
        elif part.startswith("?"):
            kind = "observation"
        elif name in state.sorts or name[:1].isupper() and re.fullmatch(r"[A-Z]\d+", name):
            kind = "object"
        elif part in ("true", "false"):
            kind = "value"
        elif part in _KEYWORDS or re.fullmatch(r"L\d+", part):
            kind = "keyword"
        elif part.startswith('"') or re.fullmatch(r"-?\d+", part):
            kind = "value"
        elif re.fullmatch(r"[A-Za-z_][\w.]*", part, re.ASCII):
            kind = "var"
        else:
            kind = "punct"
        token = {"text": part, "kind": kind, "given": name in given_names and entry is None}
        if kind in ("object", "operation", "combinator", "observation", "law", "bridge"):
            token["name"] = name
            if entry is not None:
                token["layer"] = entry.layer
            elif name in given_names:
                token["layer"] = 0
        result.append(token)
    return result
