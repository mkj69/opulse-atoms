"""Shared JSON and source-backed rule utilities (atoms-meta section 8)."""

import hashlib
import inspect
import json
import re
from dataclasses import replace

from opulse.atoms import nodes, notation
from opulse.atoms.kernel import FnRef
from opulse.atoms.spec import Cost, content_hash
from opulse.atoms.values import Bottom, Card, Ok, Unknown, encode

_META_START = re.compile(r"(?<![A-Za-z_0-9.])(Code|VN|World|[a-z][a-z_0-9]*)<", re.ASCII)


def _inside_strings(source):
    quoted = escaped = False
    inside = []
    for char in source:
        inside.append(quoted)
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
    return inside


def _meta_literals(source):
    """Parse embedded meta values, replacing only complete values with core literals (meta 8)."""
    from opulse.meta import notation as meta_notation

    if not source.isascii():
        raise ValueError("ASCII source required")
    literals = {}
    output = []
    cursor = 0
    inside = _inside_strings(source)
    while match := _META_START.search(source, cursor):
        if inside[match.start()]:
            output.append(source[cursor:match.end()])
            cursor = match.end()
            continue
        output.append(source[cursor:match.start()])
        stack = [">"]
        quoted = escaped = False
        end = match.end()
        pairs = {"<": ">", "(": ")", "[": "]", "{": "}"}
        while end < len(source) and stack:
            char = source[end]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in pairs:
                stack.append(pairs[char])
            elif char == stack[-1] and not (char == ">" and source[end - 1] == "-"):
                stack.pop()
            end += 1
        if stack:
            raise ValueError("unclosed meta value")
        if match.group(1) == "Code":
            while re.match(r"\s+where\s+", source[end:]):
                nested = []
                quoted = escaped = False
                end += re.match(r"\s+where\s+", source[end:]).end()
                while end < len(source):
                    char = source[end]
                    if quoted:
                        if escaped:
                            escaped = False
                        elif char == "\\":
                            escaped = True
                        elif char == '"':
                            quoted = False
                    elif char == '"':
                        quoted = True
                    elif char in pairs:
                        nested.append(pairs[char])
                    elif nested and char == nested[-1]:
                        nested.pop()
                    elif not nested and (char in ",)]};" or re.match(r"\s+where\s+", source[end:])):
                        break
                    end += 1
        text = source[match.start():end].strip()
        parser = {"Code": parse_meta_value, "VN": meta_notation.parse_vn,
                  "World": meta_notation.parse_world}.get(match.group(1))
        if parser is None:
            def parser(value):
                reader = meta_notation._Parser(value)
                result = reader.value()
                reader.finish()
                return result
        marker = f"__meta_literal_{len(literals)}__"
        while marker in source or marker in literals:
            marker = f"_{marker}_"
        literals[marker] = parser(text)
        output.append(notation.print_value(marker))
        cursor = end
    output.append(source[cursor:])
    return "".join(output), literals


def _restore(node, literals):
    def restore(part):
        if isinstance(part, nodes.Lit) and isinstance(part.value, str) and part.value in literals:
            value = literals[part.value]
            if isinstance(value, nodes.NODE_TYPES):
                value = _restore(value, literals)
            if isinstance(value, Card) and value.sort == "literal" and value.tag == "bool_card":
                value = value.fields[0]
            return nodes.Lit(value)
        return part

    return nodes.map_nodes(node, restore)


def parse_meta_value(source):
    """Parse a core value, Code, VN, World or lowercase meta card (meta 8)."""
    from opulse.meta import notation as meta_notation

    if not source.isascii():
        raise ValueError("ASCII source required")
    if source.startswith("Code<") and "\nwhere origin " in source:
        from opulse.meta import code as code_values

        lines = source.splitlines()
        origins = [line for line in lines if line.startswith("where origin ")]
        if len(origins) != 1:
            raise ValueError("expected one origin clause")
        reader = meta_notation._Parser(origins[0][len("where origin "):])
        template = reader.value()
        reader.need("args")
        arguments = reader.value()
        reader.finish()
        card = meta_notation.parse_code("\n".join(line for line in lines if line != origins[0]))
        origin = Card("origin", "template", (template, arguments))
        card = Card("code", "def", (*card.fields[:4], code_values.lst(
            (*code_values.items(card.fields[4]), origin))))
        if origins[0] != ("where origin " + meta_notation._value(template) +
                          " args " + meta_notation._value(arguments)):
            raise ValueError("noncanonical code origin")
        return card
    for prefix, parser in (("Code<", meta_notation.parse_code), ("VN<", meta_notation.parse_vn),
                           ("World<", meta_notation.parse_world)):
        if source.startswith(prefix):
            return parser(source)
    try:
        return notation.parse_value(source)
    except (ValueError, TypeError):
        legacy = re.fullmatch(r"([a-z][a-z_0-9]*)\.([a-z][a-z_0-9]*)\((.*)\)", source, re.DOTALL)
        if legacy:
            args = parse_meta_expr("value(" + legacy.group(3) + ")").args
            if any(not isinstance(arg, nodes.Lit) for arg in args):
                raise ValueError("card field must be a value")
            return Card(legacy.group(1), legacy.group(2), tuple(arg.value for arg in args))
        parser = meta_notation._Parser(source)
        value = parser.value()
        parser.finish()
        if meta_notation._value(value) != source:
            raise ValueError("noncanonical meta value")
        return value


def parse_meta_expr(source, ctx=None):
    """Parse core expressions with exact Code/VN/World/meta-card literal leaves (meta 8)."""
    sanitized, literals = _meta_literals(source)
    inside = _inside_strings(sanitized)

    def boolean_card(match):
        if inside[match.start()]:
            return match.group(0)
        marker = f"__meta_bool_{len(literals)}__"
        while marker in source or marker in literals:
            marker = f"_{marker}_"
        literals[marker] = Card("bool", match.group(1))
        return notation.print_value(marker)

    sanitized = re.sub(r"(?<![A-Za-z_0-9.])bool\.(true|false)\(\)", boolean_card, sanitized)
    inside = _inside_strings(sanitized)

    def reference(match):
        if inside[match.start()]:
            return match.group(0)
        marker = f"__meta_ref_{len(literals)}__"
        while marker in source or marker in literals:
            marker = f"_{marker}_"
        literals[marker] = FnRef(match.group(1))
        return notation.print_value(marker)

    sanitized = re.sub(r"&([a-z][a-z_0-9]*)\b", reference, sanitized)
    return _restore(notation.parse_expr(sanitized, ctx), literals)


def parse_meta_object_call(source, name):
    """Parse all object-constructor arguments, including nested meta values (meta 8)."""
    if not source.startswith(name + "<") or not source.endswith(">"):
        raise ValueError("invalid object instance")
    args = parse_meta_expr("instance(" + source[len(name) + 1:-1] + ")").args
    if any(not isinstance(arg, nodes.Lit) for arg in args):
        raise ValueError("object argument must be a value")
    return tuple(arg.value for arg in args)


def parse_meta_definition(source):
    """Parse core declaration heads with lowercase/qualified sorts and meta leaves (meta 8)."""
    if not source.isascii():
        raise ValueError("ASCII source required")
    role = None
    if source.startswith("op "):
        match = re.match(r"(op [a-z][A-Za-z_0-9]*\([^\n]*?\) -> [A-Za-z_0-9@:]+)"
                         r" role (transform|combine|decide|relate|act)(?= = )", source)
        if match:
            role = match.group(2)
            source = source[:match.end(1)] + source[match.end(2):]
    renamed = re.match(r"obj ([a-z][a-z_0-9]*)\b", source)
    if renamed:
        source = source[:renamed.start(1)] + "MetaObject" + source[renamed.end(1):]
    sanitized, literals = _meta_literals(source)
    sort_names = {}
    if sanitized.startswith("law "):
        body, separator, typed = sanitized.rpartition(" for ")
        prefix = body + separator
    else:
        typed, separator, body = sanitized.partition(" = ")
        prefix = ""

    def qualify(match):
        sort = match.group(2)
        raised = "M" + re.sub(r"\W", "_", sort)
        sort_names[raised] = sort
        return match.group(1) + raised

    typed = re.sub(r"(:\s*|->\s*)([a-z][a-z_0-9]*@[0-9]+:[a-z][a-z_0-9]*)(?=\s|[!,)\]]|$)",
                   qualify, typed)

    def lift(match):
        sort = match.group(2)
        if sanitized.startswith("template "):
            return match.group(0)
        if sort in ("int", "str", "bool", "A") or sort[0].isupper():
            return match.group(0)
        raised = "M" + sort
        sort_names[raised] = sort
        return match.group(1) + raised

    typed = re.sub(r"(:\s*|->\s*)([a-z][a-z_0-9]*)(?=\s|[!,)\]]|$)", lift, typed)
    sanitized = prefix + typed if prefix else typed + separator + body
    try:
        definition = notation.parse_definition(sanitized)
    except notation.NotationError:
        from opulse.meta import code as C
        from opulse.meta import notation as meta_notation

        if not re.match(r"(?:op|obj|comb|obs|bridge)\b", sanitized):
            raise
        head, separator, tail = sanitized.partition(" = ")
        if not separator:
            raise
        match = re.fullmatch(r"(.*) (given|L[1-9][0-9]*)", tail, re.DOTALL)
        if match is None:
            raise
        body_text = match.group(1)
        trailer = ""
        if head.startswith("bridge ") and " commutes " in body_text:
            body_text, trailer = body_text.rsplit(" commutes ", 1)
            trailer = " commutes " + trailer
        wrapped = body_text.startswith("(") and body_text.endswith(")") and head.startswith("obj ")
        memo_names = set(re.findall(r"\brec memo ([a-z][a-z_0-9]*)\(", body_text))
        parse_body = re.sub(r"\brec memo ([a-z][a-z_0-9]*)\(", r"rec \1(", body_text)
        reader = meta_notation._Parser(parse_body[1:-1] if wrapped else parse_body)
        parsed_body = reader.expr()
        reader.finish()
        fallback_body = C.decode_node(parsed_body)
        if memo_names:
            fallback_body = nodes.map_nodes(
                fallback_body, lambda part: replace(part, memo=True)
                if isinstance(part, nodes.Rec) and part.fn in memo_names else part)
        marker = "__meta_definition_body__"
        while marker in source or marker in literals:
            marker = f"_{marker}_"
        sanitized = head + " = " + notation.print_value(marker) + trailer + " " + match.group(2)
        if wrapped:
            sanitized = head + " = (" + notation.print_value(marker) + ")" + trailer + " " + match.group(2)
        definition = notation.parse_definition(sanitized)
        literals[marker] = fallback_body
    spec = definition.spec
    if renamed:
        spec = replace(spec, name=renamed.group(1))
        definition = replace(definition, name=renamed.group(1))
    if definition.kind == "operation":
        spec = replace(spec, role=role or spec.role,
                       inputs=tuple(replace(edge, sort=sort_names.get(edge.sort, edge.sort))
                                          for edge in spec.inputs),
                       output=replace(spec.output, sort=sort_names.get(spec.output.sort, spec.output.sort)))
    elif definition.kind == "law":
        spec = replace(spec, vars=tuple((name, sort_names.get(sort, sort)) for name, sort in spec.vars))
    elif definition.kind == "bridge":
        spec = replace(spec, source=sort_names.get(spec.source, spec.source),
                       target=sort_names.get(spec.target, spec.target))
    body = _restore(definition.body, literals) if isinstance(definition.body, nodes.NODE_TYPES) else definition.body
    if isinstance(body, nodes.Lit) and isinstance(body.value, nodes.NODE_TYPES):
        body = body.value
    if definition.kind in ("combinator", "observation") or (
            definition.kind == "object" and getattr(spec, "form", None) == "constant"):
        spec = replace(spec, body=body)
    elif definition.kind == "bridge":
        spec = replace(spec, map=body)
    elif definition.kind == "law":
        spec = replace(spec, statement=body)
    return replace(definition, spec=spec, body=body)


def host_rule(fn):
    return {"host": f"{fn.__module__}:{fn.__qualname__}",
            "digest": hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()}


def value_json(value):
    return {"fn": value.name} if isinstance(value, FnRef) else encode(value)


def compact_enumerations(value, limit=32):
    """Publish long enumerations by count and content hash (meta 8)."""
    if isinstance(value, dict):
        return {key: compact_enumerations(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > limit:
            return {"count": len(value), "sha256": content_hash(list(value))}
        return [compact_enumerations(item, limit) for item in value]
    return value


def outcome_json(outcome):
    if isinstance(outcome, Ok):
        return {"kind": "Ok", "value": value_json(outcome.value)}
    if isinstance(outcome, Bottom):
        return {"kind": "Bottom", "reason": outcome.reason}
    return {"kind": "Unknown", "resource": outcome.resource}


def trace_json(frame):
    if frame is None:
        return None
    return {"name": frame.name, "kind": frame.kind, "layer": frame.layer, "given": frame.given,
            "path": list(frame.path), "inputs": [value_json(value) for value in frame.inputs],
            "outcome": outcome_json(frame.outcome), "steps": frame.steps,
            "children": [trace_json(child) for child in frame.children]}


def input_hash(args):
    values = [value_json(arg) for arg in args]
    return hashlib.sha256(json.dumps(
        values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ascii_definition(defn, library):
    """Return (declaration, reason); compact source omits pipeline metadata (meta 8)."""
    source = replace(defn, status="written", evidence=None, contract=None, cost=Cost(), id=None)
    try:
        return notation.print_definition(source, library), None
    except (TypeError, ValueError) as exc:
        try:
            spec = source.spec
            replacements = {}

            def raised(sort):
                if sort in ("int", "str", "bool", "A") or sort[0].isupper():
                    return sort
                marker = "MetaSort" + str(len(replacements))
                replacements[marker] = sort
                return marker

            if source.kind == "operation":
                spec = replace(spec, inputs=tuple(replace(edge, sort=raised(edge.sort))
                                                  for edge in spec.inputs),
                               output=replace(spec.output, sort=raised(spec.output.sort)))
            elif source.kind == "law":
                spec = replace(spec, vars=tuple((name, raised(sort)) for name, sort in spec.vars))
            elif source.kind == "bridge":
                spec = replace(spec, source=raised(spec.source), target=raised(spec.target))
            elif source.kind == "object" and source.name[0].islower():
                replacements["MetaObject"] = source.name
                spec = replace(spec, name="MetaObject")
                source = replace(source, name="MetaObject")

            original_body = source.body
            if isinstance(original_body, nodes.NODE_TYPES):
                def literal(part):
                    if isinstance(part, nodes.Lit) and isinstance(part.value, Card):
                        marker = "__meta_body_" + str(len(replacements)) + "__"
                        while marker in repr(original_body) or notation.print_value(marker) in replacements:
                            marker = "_" + marker
                        replacements[notation.print_value(marker)] = (
                            f"literal<bool_card: {part.value.tag}>"
                            if part.value.sort == "bool" and part.value.tag in ("true", "false")
                            else _ascii_value(part.value))
                        return nodes.Lit(marker)
                    return part

                body = nodes.map_nodes(original_body, literal)
                if body != original_body:
                    spec = replace(spec, body=body) if source.kind in ("object", "combinator", "observation") else spec
                    if source.kind == "law":
                        spec = replace(spec, statement=body)
                    elif source.kind == "bridge":
                        spec = replace(spec, map=body)
                    source = replace(source, body=body)
            printed = notation.print_definition(replace(source, spec=spec), library)
            printed = re.sub(r'"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*',
                             lambda match: replacements.get(match.group(), match.group()), printed)
            parsed = parse_meta_definition(printed)
            if parsed.kind == defn.kind and parsed.name == defn.name and parsed.body == defn.body:
                return printed, None
        except (ValueError, TypeError):
            pass
        if (source.kind == "operation" and isinstance(source.body, nodes.Let) and
                source.body.name.startswith("_template_ref_")):
            from opulse.meta import code as meta_code
            from opulse.meta import notation as meta_notation

            spec = source.spec
            parameters = [edge.name or f"arg{index}" for index, edge in enumerate(spec.inputs)]
            head = (f"op {source.name}(" + ", ".join(
                f"{name}: {edge.sort}" for name, edge in zip(parameters, spec.inputs)) +
                f") -> {spec.output.sort}")
            if spec.role != "transform":
                head += f" role {spec.role}"
            text = (head + " = " + meta_notation._expr(meta_code.encode_node(source.body), True) +
                    f" L{source.layer}")
            try:
                parsed = parse_meta_definition(text)
                if parsed.kind == defn.kind and parsed.name == defn.name and parsed.body == defn.body:
                    return text, None
            except (TypeError, ValueError):
                pass
        return None, str(exc)


def _ascii_value(value):
    if isinstance(value, Card) and value.sort == "bool" and value in (Card("bool", "true"),
                                                                          Card("bool", "false")):
        return f"bool.{value.tag}()"
    if isinstance(value, Card) and value.sort == "code":
        from opulse.meta.notation import show_code

        return show_code(value, signature=True, deps=True, exact=True)
    if isinstance(value, Card) and value.sort == "vn":
        from opulse.meta.notation import show_vn

        return show_vn(value)
    if isinstance(value, Card) and value.sort == "world":
        from opulse.meta.notation import show_world

        return show_world(value)
    if isinstance(value, Card) and value.sort != "bool" and not notation.is_valid_name(
            "object", value.sort):
        from opulse.meta.notation import _value

        return _value(value)
    return notation.print_value(value)


def ascii_example(entry_name, kind, inputs, outcome):
    """Render an instance and its exact outcome in ASCII (meta 8)."""
    if isinstance(outcome, Ok):
        result = _ascii_value(outcome.value)
    elif isinstance(outcome, Bottom):
        result = notation.print_value(outcome)
    elif isinstance(outcome, Unknown):
        result = f"Unknown<{notation.print_value(outcome.resource)}>"
    else:
        raise TypeError("expected an Outcome")
    name = notation.stored_name(entry_name)
    if kind == "combinator":
        refs = []
        args = []
        for value in inputs:
            (refs if isinstance(value, FnRef) else args).append(
                value.name if isinstance(value, FnRef) else _ascii_value(value))
        call = f"@{name}[{', '.join(refs)}]({', '.join(args)})"
    elif kind == "observation":
        if len(inputs) != 1:
            raise ValueError("observation needs exactly one subject")
        call = f"?{name}{{{_ascii_value(inputs[0])}}}"
    elif kind == "bridge":
        if len(inputs) != 1:
            raise ValueError("bridge needs exactly one argument")
        call = f"~{name}({_ascii_value(inputs[0])})"
    elif kind == "law":
        call = f"#{name}({', '.join(map(_ascii_value, inputs))})"
    elif kind == "template":
        call = f"{name}[{', '.join(map(_ascii_value, inputs))}]"
    elif kind == "object":
        call = f"{name}<{', '.join(map(_ascii_value, inputs))}>"
    elif kind == "operation":
        call = f"{name}({', '.join(map(_ascii_value, inputs))})"
    else:
        raise ValueError(f"unsupported kind: {kind}")
    return f"{call} = {result}"


def outside_scope(frame, lib, definitions=None, check=None):
    """Check a call and all promoted callees against their enumerated input tuples (spec 9).

    ``check(definition, inputs)`` replaces the default input-hash test for worlds with other scope forms.
    """
    if frame is None:
        return False
    if definitions is None:
        definitions = lib.definitions
    definition = definitions.get(frame.name)
    if definition is not None and definition.origin == "invented" and definition.status == "promoted":
        if check is not None:
            if check(definition, frame.inputs):
                return True
        else:
            inputs = frame.inputs
            if definition.kind == "combinator" and input_hash(inputs) not in definition.evidence.scope.get(
                    "input_hashes", ()):
                family = definition.evidence.scope.get("op_family", ())
                op_params = definition.spec.op_params
                if any(not isinstance(inputs[definition.spec.params.index(param)], FnRef) or
                       inputs[definition.spec.params.index(param)].name not in family
                       for param in op_params):
                    return True
                inputs = tuple(arg for index, arg in enumerate(inputs)
                               if definition.spec.params[index] not in op_params)
            if input_hash(inputs) not in definition.evidence.scope.get("input_hashes", ()):
                return True
    return any(outside_scope(child, lib, definitions, check) for child in frame.children)
