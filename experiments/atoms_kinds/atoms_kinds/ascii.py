"""Small, replaceable ASCII-to-kernel adapter for the fraction experiment."""

import re
from dataclasses import replace

from opulse.atoms import nodes, notation
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.kernel import FnRef
from opulse.atoms.spec import (
    CombinatorSpec,
    Cost,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    OperationSpec,
)
from opulse.atoms.values import FALSE, TRUE, Card


class AsciiSyntaxError(ValueError):
    """A learner-visible error in the experiment-local ASCII language."""


TOKEN = re.compile(r"\s*(->|-?\d+|[A-Za-z_][\w.]*(?:\.[\w]+)*|[@?~{}(),:<>=\[\]])")
IDENT = re.compile(r"[A-Za-z_][\w.]*\Z")
OP = re.compile(r"op\s+([A-Za-z_][\w.]*)\((.*?)\)\s*->\s*(Int|Pair)\s*=\s*(.+)")
OBJ = re.compile(r"obj\s+([A-Za-z_][\w]*)\s*=\s*<num:\s*Int,\s*den:\s*Int>\s+where\s+(.+?)\s+canon\s+(.+?)\s+sealed\s*\(make,\s*num,\s*den\)")
COMB = re.compile(r"comb\s+@([A-Za-z_][\w]*)\[([A-Za-z_][\w]*):\s*(?:\(Int,\s*Int\)|Int)\s*->\s*Int\]\((.*?)\)\s*->\s*Int\s*=\s*(.+)")
LAW = re.compile(r"law\s+#([A-Za-z_][\w]*):\s*(.+)\s+for\s+(.+)")
BRIDGE = re.compile(r"bridge\s+~([A-Za-z_][\w]*):\s*Pair\s*->\s*Frac\s*=\s*(.+?)(?:\s+where\s+(.+?))?(?:\s+commutes\s*\((.+)\))?")


def signature(text):
    if not text.strip():
        return ()
    pairs = [part.strip().split(":") for part in text.split(",")]
    if any(len(pair) != 2 or not IDENT.fullmatch(pair[0].strip()) or pair[1].strip() != "Int"
           for pair in pairs):
        raise AsciiSyntaxError("expected name: Int parameters")
    names = tuple(pair[0].strip() for pair in pairs)
    if len(set(names)) != len(names):
        raise AsciiSyntaxError("duplicate parameter")
    return names


class Expression:
    def __init__(self, text):
        self.tokens = []
        position = 0
        while position < len(text):
            match = TOKEN.match(text, position)
            if match is None:
                raise AsciiSyntaxError(f"unexpected expression character at {position}")
            self.tokens.append(match.group(1))
            position = match.end()
        self.position = 0

    def take(self, token=None):
        if self.position >= len(self.tokens):
            raise AsciiSyntaxError("unexpected end of expression")
        value = self.tokens[self.position]
        if token is not None and value != token:
            raise AsciiSyntaxError(f"expected {token}, got {value}")
        self.position += 1
        return value

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def sequence(self, closing):
        values = []
        if self.peek() != closing:
            values.append(self.expr())
            while self.peek() == ",":
                self.take(",")
                values.append(self.expr())
        self.take(closing)
        return tuple(values)

    def expr(self):
        token = self.take()
        if token == "let":
            name = self.take()
            if not IDENT.fullmatch(name):
                raise AsciiSyntaxError("invalid let binding")
            self.take("=")
            value = self.expr()
            self.take("in")
            return nodes.Let(name, value, self.expr())
        if token == "if":
            condition = self.expr()
            self.take("then")
            branch = self.expr()
            self.take("else")
            return nodes.Case(((nodes.Test(condition), branch),), self.expr())
        if token == "(":
            value = self.expr()
            self.take(")")
            return value
        if re.fullmatch(r"-?\d+", token):
            return nodes.Lit(int(token))
        if token in ("true", "false"):
            return nodes.Lit(TRUE if token == "true" else FALSE)
        if token == "Pair" and self.peek() == "<":
            self.take("<")
            args = self.sequence(">")
            if len(args) != 2:
                raise AsciiSyntaxError("Pair needs two fields")
            return nodes.Call("Pair.pair", args)
        if token in ("@", "?", "~"):
            token += self.take()
        if not IDENT.fullmatch(token.lstrip("@?~")):
            raise AsciiSyntaxError(f"unexpected token {token}")
        if token.startswith("@") and self.peek() == "[":
            self.take("[")
            function = self.take()
            if not IDENT.fullmatch(function):
                raise AsciiSyntaxError("invalid combinator operation argument")
            self.take("]")
            self.take("(")
            return nodes.Call(token, (nodes.Lit(FnRef(function)), *self.sequence(")")))
        if self.peek() == "(":
            self.take("(")
            return nodes.Call(token, self.sequence(")"))
        if token.startswith("?") and self.peek() == "{":
            self.take("{")
            return nodes.Call(token[1:] if token == "?pair_num_probe" else token, self.sequence("}"))
        if token.startswith("~"):
            raise AsciiSyntaxError("bridge application requires (value)")
        return nodes.Var(token)


def expression(text):
    if ("Pair<" not in text and "@" not in text and
            not re.search(r"\b(?:true|false)\b|\b[A-Za-z_]\w*\.", text)):
        try:
            return notation.parse_expr(text)
        except notation.NotationError as error:
            raise AsciiSyntaxError(str(error)) from error
    parser = Expression(text.strip())
    result = parser.expr()
    if parser.peek() is not None:
        raise AsciiSyntaxError(f"unexpected token {parser.peek()}")
    return result


def rename(node, mapping):
    if isinstance(node, nodes.Var):
        return nodes.Var(mapping.get(node.name, node.name))
    if isinstance(node, nodes.Call):
        return nodes.Call(node.fn, tuple(rename(arg, mapping) for arg in node.args))
    if isinstance(node, nodes.Let):
        return nodes.Let(node.name, rename(node.value, mapping),
                         rename(node.body, {name: value for name, value in mapping.items() if name != node.name}))
    if isinstance(node, nodes.Case):
        return nodes.Case(tuple((nodes.Test(rename(test.expr, mapping)), rename(body, mapping))
                                for test, body in node.arms),
                          rename(node.default, mapping) if node.default is not None else None)
    return node


def _compile(text):
    definitions, saved, solve = [], [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        suffix = re.search(r"\s+L(\d+)\Z", line)
        layer = int(suffix.group(1)) if suffix else 0
        if suffix and layer == 0:
            raise AsciiSyntaxError("invented layer must be positive")
        if suffix:
            line = line[:suffix.start()]
        if line.startswith("save "):
            name = line[5:].strip()
            if not re.fullmatch(r"[@#?~]?[A-Za-z_][\w.]*", name):
                raise AsciiSyntaxError("invalid save name")
            saved.append(name)
            continue
        if match := OP.fullmatch(line):
            name, params, output, body_text = match.groups()
            names = signature(params)
            if "Pair<" not in body_text and "@" not in body_text and "?" not in body_text and "~" not in body_text and not re.search(r"\b[A-Za-z_]\w*\.", body_text):
                core_line = re.sub(r"\bInt\b", "int", line) + f" L{layer or 1}"
                body = notation.parse_definition(core_line).body
            else:
                body = expression(body_text)
            if name == "solve":
                if solve is not None:
                    raise AsciiSyntaxError("duplicate solve")
                solve = (names, output, rename(body, {name: f"arg{index}" for index, name in enumerate(names)}))
                continue
            spec = OperationSpec(name, "transform", tuple(Edge("int") for _ in names),
                                 Edge("int" if output == "Int" else "Pair"),
                                 "learner operation", extra={"input_names": list(names)})
            definitions.append(Definition(name, "operation", "invented", layer,
                                          tuple(sorted(nodes.references(body))), spec, body))
        elif match := OBJ.fullmatch(line):
            name, condition, canon = match.groups()
            spec = ObjectSpec(name, "refine", base="Pair", valid=expression(condition),
                              canon=expression(canon), sealed=True,
                              interface=(f"{name}.make", f"{name}.num", f"{name}.den"))
            references = nodes.references(spec.valid) | nodes.references(spec.canon)
            definitions.append(Definition(name, "object", "invented", layer,
                                          tuple(sorted(references)), spec, None))
        elif match := COMB.fullmatch(line):
            name, function, params, body_text = match.groups()
            names = signature(params)
            body = expression(body_text)
            spec = CombinatorSpec(f"@{name}", (function, *names), (function,), body)
            definitions.append(Definition(f"@{name}", "combinator", "invented", layer,
                                          tuple(sorted(nodes.references(body) - {function})), spec, body))
        elif match := LAW.fullmatch(line):
            name, statement_text, params = match.groups()
            names = signature(params)
            parsed = notation.parse_definition(
                f"law #{name}: {statement_text} for " +
                ", ".join(f"{item}: int" for item in names) + f" L{layer or 1}")
            spec = replace(parsed.spec, name=f"#{name}")
            definitions.append(replace(parsed, name=f"#{name}", layer=layer, spec=spec))
        elif line.startswith("obs "):
            declaration, body_text = line.split(" = ", 1)
            parsed = notation.parse_definition(
                (declaration + " = 0" if "Pair." in body_text else line) + f" L{layer or 1}")
            body = expression(body_text) if "Pair." in body_text else parsed.body
            definitions.append(replace(parsed, name=f"?{parsed.name}", layer=layer,
                                       body=body, depends_on=tuple(sorted(nodes.references(body))),
                                       spec=replace(parsed.spec, name=f"?{parsed.name}",
                                                    body=body,
                                                    reads=tuple(sorted(set(parsed.spec.reads) |
                                                                       ({"pair_num_probe"} & nodes.references(body)))),
                                                    extra={**parsed.spec.extra,
                                                           "inputs": [[parsed.spec.subject, "Pair"]]})))
        elif match := BRIDGE.fullmatch(line):
            name, body_text, domain_text, interface_text = match.groups()
            pairs = tuple((source.strip(), target.strip()) for source, target in
                          (piece.split("->") for piece in interface_text.split(","))) if interface_text else ()
            parsed = notation.parse_definition(f"bridge ~{name}: Pair -> Frac = x L{layer or 1}")
            body = expression(body_text)
            domain = expression(domain_text) if domain_text else None
            spec = replace(parsed.spec, name=f"~{name}", target="fractions@1:Frac",
                           map=body, domain=domain, interface=pairs)
            bridge_body = bridge_defn(spec).body
            definitions.append(replace(parsed, name=f"~{name}", layer=layer,
                                       depends_on=tuple(sorted(nodes.references(bridge_body))),
                                       spec=spec, body=bridge_body))
        else:
            raise AsciiSyntaxError("expected op, obj, comb, law, obs, bridge or save declaration")
    if solve is None:
        raise AsciiSyntaxError("missing op solve")
    if len(set(saved)) != len(saved) or set(saved) - {item.name for item in definitions}:
        raise AsciiSyntaxError("save must name each new definition at most once")
    if set(saved) != {item.name for item in definitions}:
        raise AsciiSyntaxError("each new definition requires save NAME")
    if len({item.name for item in definitions}) != len(definitions):
        raise AsciiSyntaxError("duplicate definition")
    return tuple(definitions), solve


def parse(text):
    """Compile learner text; never leak implementation exceptions to a learner."""
    try:
        if not isinstance(text, str):
            raise AsciiSyntaxError("expected ASCII text")
        if not text.isascii():
            raise AsciiSyntaxError("only ASCII notation is supported")
        return _compile(text)
    except AsciiSyntaxError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError) as error:
        raise AsciiSyntaxError(str(error)) from error


def display(node):
    try:
        return notation.print_expr(node)
    except (ValueError, TypeError):
        pass
    if isinstance(node, nodes.Var):
        return node.name
    if isinstance(node, nodes.Lit):
        if isinstance(node.value, FnRef):
            return node.value.name
        if isinstance(node.value, Card) and node.value.sort == "bool":
            return node.value.tag
        return str(node.value)
    if isinstance(node, nodes.Call):
        if node.fn == "pair_num_probe":
            return f"?pair_num_probe{{{', '.join(display(arg) for arg in node.args)}}}"
        if node.fn.startswith("?") or node.fn.startswith("~"):
            return f"{node.fn}{{{', '.join(display(arg) for arg in node.args)}}}" if node.fn.startswith("?") else f"{node.fn}({', '.join(display(arg) for arg in node.args)})"
        if node.fn == "Pair.pair":
            return f"Pair<{', '.join(display(arg) for arg in node.args)}>"
        if node.fn.startswith("@") and node.args and isinstance(node.args[0], nodes.Lit) and isinstance(node.args[0].value, FnRef):
            return f"{node.fn}[{display(node.args[0])}]({', '.join(display(arg) for arg in node.args[1:])})"
        return f"{node.fn}({', '.join(display(arg) for arg in node.args)})"
    if isinstance(node, nodes.Let):
        return f"let {node.name} = {display(node.value)} in {display(node.body)}"
    if isinstance(node, nodes.Case) and len(node.arms) == 1 and node.default is not None:
        condition, branch = node.arms[0]
        return f"if {display(condition.expr)} then {display(branch)} else {display(node.default)}"
    raise AsciiSyntaxError("node cannot be rendered in learner subset")


def render(definition):
    suffix = " given" if definition.origin == "given" else f" L{definition.layer}" if definition.layer else ""
    if definition.kind == "operation":
        try:
            spec = replace(definition.spec, role="transform", rule="ASCII definition", extra={},
                           inputs=tuple(replace(edge, name=name) for edge, name in zip(
                               definition.spec.inputs, definition.spec.extra.get("input_names", ()))))
            canonical = replace(definition, spec=spec, status="written", evidence=None,
                                contract=None, cost=Cost(), id=None)
            return notation.print_definition(canonical).replace(": int", ": Int").replace("-> int", "-> Int")
        except (ValueError, TypeError):
            pass
        names = definition.spec.extra.get("input_names", [f"arg{index}" for index in range(len(definition.spec.inputs))])
        params = ", ".join(f"{name}: Int" for name in names)
        return f"op {definition.name}({params}) -> {definition.spec.output.sort.title()} = {display(definition.body)}{suffix}"
    if definition.kind == "object":
        spec = definition.spec
        return (f"obj {definition.name} = <num: Int, den: Int> where {display(spec.valid)} "
                f"canon {display(spec.canon)} sealed (make, num, den){suffix}")
    if definition.kind == "combinator":
        function, *names = definition.spec.params
        params = ", ".join(f"{name}: Int" for name in names)
        parameter_sort = "(Int, Int)" if len(names) == 2 else "Int"
        return (f"comb {definition.name}[{function}: {parameter_sort} -> Int]({params}) "
                f"-> Int = {display(definition.body)}{suffix}")
    if definition.kind == "law" and isinstance(definition.spec, LawSpec):
        canonical = replace(definition, name=definition.name.removeprefix("#"),
                            layer=definition.layer or 1,
                            spec=replace(definition.spec, name=definition.name.removeprefix("#")),
                            status="written", evidence=None, contract=None, cost=Cost(), id=None)
        return notation.print_definition(canonical).replace(": int", ": Int")
    if definition.kind == "observation":
        return (f"obs {definition.name}{{{definition.spec.subject}}} = "
                f"{display(definition.body)}{suffix}")
    if definition.kind == "bridge":
        spec = definition.spec
        pairs = ", ".join(f"{source} -> {target}" for source, target in spec.interface)
        return (f"bridge {definition.name}: Pair -> Frac = {display(spec.map)}"
                f"{' where ' + display(spec.domain) if spec.domain is not None else ''}"
                f"{' commutes (' + pairs + ')' if pairs else ''}{suffix}")
    raise AsciiSyntaxError("unsupported definition kind")
