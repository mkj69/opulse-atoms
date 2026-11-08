"""Legacy operation ASCII codec (docs/spec/atoms-v2.md, sections 3 and 12).

Published symbol families use preferred letters: diamond/heart=f,
spade/club=g, square=h, triangle=i/j (up/down), lozenge=k,
circle=l, star=m, small diamond/spade=n, heart/club=o. When families
share a number, the later family takes the next unused letter for that
number. Names are stable per published world.
Branches use ``case condition -> value; ...; else -> value`` and recursion is
an ordinary call to the same ASCII name. ``search(i, bound, condition)`` is
the legacy bounded-search form.
"""

from __future__ import annotations

import ast as pyast
import json
import re
from functools import lru_cache
from pathlib import Path

from opulse.atoms.notation import generated_name, legacy_symbol_to_ascii
from opulse.definition import ast
from opulse.tasks_v2 import engine

_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_FAMILIES = "♦♡♠♣■□▲△▼▽◆◇○●★☆♢♤♥♧"
_LETTERS = "ffgghhiijjkkllmmnnoo"
_ATOM_NAMES = {"reverse": "rev", "triangle": "tri", "popcount": "pop",
               "digitsum": "dsum", "list_cons": "cons", "list_head": "head",
               "list_tail": "tail", "list_length": "length", "list_append": "append",
               "list_sum": "sum", "list_at": "at", "list_equal": "equal",
               "str_concat": "concat", "str_length": "length", "str_reverse": "rev",
               "str_first": "first", "str_drop": "drop", "str_upper": "upper",
               "str_lower": "lower", "str_equal": "equal"}
_COMPARE = {"<": "lt", "<=": "le", ">": "gt", ">=": "ge", "==": "eq", "!=": "ne"}


@lru_cache(maxsize=4)
def names(world: str) -> tuple[dict[str, str], dict[tuple[str, int, str | None], str]]:
    """Map published operator symbols and primitive roles to unique ASCII names."""
    path = Path(__file__).resolve().parents[3] / "docs/assets/data/worlds" / f"{world.split('@')[0]}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    operators = {}
    used = set()
    for row in data["operators"]:
        symbol = row["name"]
        family, number = symbol[0], symbol[1:].translate(_SUBSCRIPTS)
        preferred = _LETTERS[_FAMILIES.index(family)]
        letter = next(letter for letter in (preferred, *"fghijklmnopqrstuvwxyz")
                      if f"{letter}{number}" not in used)
        candidate = f"{letter}{number}"
        try:
            core_name = legacy_symbol_to_ascii(symbol)
        except ValueError:
            core_name = None
        operators[symbol] = (generated_name("operation", int(number)) if core_name == candidate
                             else candidate)
        used.add(operators[symbol])
    primitives = {}
    for op in engine._base(world)[1]:
        symbol, arity = op.symbol, op.n_ary
        position = op.unary_position
        row = next((item for item in data["atoms"] if item["symbol"] == symbol
                    and item["arity"] == arity), None)
        if row is None:
            row = next(item for item in data["atoms"] if item["symbol"] == symbol and item["arity"] == arity)
        name = _ATOM_NAMES.get(row["name"], row["name"])
        primitives[(symbol, arity, position)] = name
    return operators, primitives


def _atom_name(world: str, node: ast.Apply) -> str:
    operators, primitives = names(world)
    if node.symbol in operators:
        return operators[node.symbol]
    name = primitives.get((node.symbol, node.n_ary, node.unary_position))
    if name is None:
        name = next((value for (symbol, arity, _), value in primitives.items()
                     if symbol == node.symbol and arity == node.n_ary), None)
    if name is None:
        raise ValueError(f"unknown operation {node.symbol!r}")
    return name


def _expr(world: str, node) -> str:
    if isinstance(node, ast.Var):
        return node.name
    if isinstance(node, ast.Num):
        return str(node.value)
    if isinstance(node, ast.NaN):
        return "NaN"
    if isinstance(node, ast.Literal):
        if isinstance(node.value, (list, tuple)):
            return "List<" + ", ".join(_expr(world, ast.negate(item)) for item in node.value) + ">"
        return json.dumps(node.value, ensure_ascii=True)
    if isinstance(node, ast.Search):
        return f"search({node.index}, {node.bound}, {_condition(world, node.condition)})"
    args = [_expr(world, arg) for arg in node.args]
    name = _atom_name(world, node)
    return f"{name}({', '.join(args)})"


def _condition(world: str, node) -> str:
    if isinstance(node, ast.Compare):
        return f"{_COMPARE[node.op]}({_expr(world, node.left)}, {_expr(world, node.right)})"
    if isinstance(node, (ast.And, ast.Or)):
        return f"({_condition(world, node.left)}) {'and' if isinstance(node, ast.And) else 'or'} ({_condition(world, node.right)})"
    if isinstance(node, ast.Not):
        return f"not ({_condition(world, node.operand)})"
    return _expr(world, node.expr)


def to_ascii_definition(world: str, text: str, definitions: dict[str, str] | None = None) -> str:
    """Render a published legacy definition as a typed ASCII operation rule."""
    parsed = engine._oracle(world, definitions or {}).parser.parse(text)
    head = _expr(world, parsed.lhs)
    if len(parsed.branches) == 1 and parsed.branches[0].condition is None:
        body = _expr(world, parsed.branches[0].expr)
    else:
        body = "case " + "; ".join(
            (f"{_condition(world, branch.condition)} -> " if branch.condition else "else -> ")
            + _expr(world, branch.expr) for branch in parsed.branches)
    return f"op {head} = {body}"


def to_ascii_expression(world: str, text: str, definitions: dict[str, str] | None = None) -> str:
    return _expr(world, engine._oracle(world, definitions or {}).parser.parse_expr(text))


def parse_ascii_expression(world: str, text: str) -> str:
    """Translate an ASCII expression to the published engine's notation."""
    return ast.render_expr(_parse_node(world, text), engine._oracle(world, {}).parser.symbols)


def _parse_node(world: str, source: str, *, condition: bool = False):
    operators, primitives = names(world)
    reverse = {name: symbol for symbol, name in operators.items()}
    atom_reverse = {(name, arity): (symbol, position)
                    for (symbol, arity, position), name in primitives.items()}
    for symbol, name in operators.items():
        row = next(row for row in engine._published(world)["operators"] if row["name"] == symbol)
        head = row["definition"].split("=", 1)[0].strip()
        if len(row["params"]) == 1:
            position = "prefix" if head.startswith(symbol) else "postfix"
            atom_reverse[(name, 1)] = (symbol, position)
    source = re.sub(r"List<([^<>]*)>", r"[\1]", source)
    tree = pyast.parse(source, mode="eval").body

    def convert(node, test=False):
        if isinstance(node, pyast.Name):
            if node.id == "NaN":
                return ast.NaN()
            if node.id in ("true", "false"):
                return ast.Literal(node.id == "true")
            return ast.Var(node.id)
        if isinstance(node, pyast.Constant):
            if type(node.value) is int:
                return ast.negate(node.value)
            return ast.Literal(node.value)
        if isinstance(node, pyast.List):
            values = [(-pyast.literal_eval(item.args[0]) if isinstance(item, pyast.Call)
                       and isinstance(item.func, pyast.Name) and item.func.id == "neg"
                       and len(item.args) == 1 else pyast.literal_eval(item)) for item in node.elts]
            return ast.Literal(values)
        if isinstance(node, pyast.UnaryOp) and isinstance(node.op, pyast.USub):
            value = convert(node.operand)
            return ast.negate(-value.value) if isinstance(value, ast.Num) else ast.Apply("-", (value,), "prefix")
        if isinstance(node, pyast.UnaryOp) and isinstance(node.op, pyast.Not) and test:
            return ast.Not(convert(node.operand, True))
        if isinstance(node, pyast.BinOp):
            symbol = {pyast.Add: "+", pyast.Sub: "-", pyast.Mult: "*"}.get(type(node.op))
            if symbol is not None:
                return ast.Apply(symbol, (convert(node.left), convert(node.right)))
        if isinstance(node, pyast.Call) and isinstance(node.func, pyast.Name) and not node.keywords:
            name = node.func.id
            if name == "search" and len(node.args) == 3:
                return ast.Search(node.args[0].id, pyast.literal_eval(node.args[1]), convert(node.args[2], True))
            if name in _COMPARE.values() and len(node.args) == 2:
                return ast.Compare(convert(node.args[0]), next(op for op, word in _COMPARE.items() if word == name), convert(node.args[1]))
            args = tuple(convert(arg) for arg in node.args)
            if (name, len(args)) not in atom_reverse and name in reverse:
                return ast.Apply(reverse[name], args)
            if (name, len(args)) not in atom_reverse:
                raise ValueError(f"unknown ASCII operation {name!r}")
            symbol, position = atom_reverse[(name, len(args))]
            return ast.Apply(symbol, args, position if len(args) == 1 else None)
        if isinstance(node, pyast.BoolOp) and test:
            parts = [convert(value, True) for value in node.values]
            for part in parts[1:]:
                result = ast.And(parts[0], part) if isinstance(node.op, pyast.And) else ast.Or(parts[0], part)
                parts[0] = result
            return parts[0]
        raise ValueError(f"unsupported ASCII expression: {source!r}")

    result = convert(tree, condition)
    return ast.Truth(result) if condition and not isinstance(result, (ast.Compare, ast.And, ast.Or, ast.Not, ast.Truth)) else result


def parse_ascii_definition(world: str, text: str) -> str:
    """Translate an ASCII rule to the legacy definition accepted by engine.parse_definition.

    Legacy operator strings pass through unchanged for backwards compatibility.
    """
    if not text.startswith("op "):
        return text
    match = re.fullmatch(r"op\s+([a-z][a-z0-9]*)\(([^()]*)\)\s*=\s*(.*?)(?:\s+L\d+)?", text.strip(), re.DOTALL)
    if match is None:
        raise ValueError("invalid ASCII operation definition")
    name, params, body = match.groups()
    symbol = {value: key for key, value in names(world)[0].items()}.get(name)
    if symbol is None:
        raise ValueError(f"unknown ASCII operator {name!r}")
    args = tuple(ast.Var(param.strip()) for param in params.split(",") if param.strip())
    row = next(row for row in engine._published(world)["operators"] if row["name"] == symbol)
    head = row["definition"].split("=", 1)[0].strip()
    position = ("prefix" if head.startswith(symbol) else "postfix") if len(args) == 1 else None
    lhs = ast.Apply(symbol, args, position)
    branches = []
    if body.startswith("case "):
        for arm in body[5:].split("; "):
            condition, separator, value = arm.partition(" -> ")
            if not separator:
                raise ValueError("invalid ASCII case arm")
            branches.append(ast.Branch(_parse_node(world, value), None if condition == "else"
                                       else _parse_node(world, condition, condition=True), condition == "else"))
    else:
        branches.append(ast.Branch(_parse_node(world, body)))
    return ast.render_definition(ast.Definition(lhs, tuple(branches)), engine._base(world)[0].symbols)


def grade_ascii(task, answer):
    """Grade a legacy operation task with either ASCII or legacy definition input."""
    from opulse.tasks_v2.grade import grade

    if task.answer_shape == "definition" and isinstance(answer, str):
        try:
            answer = parse_ascii_definition(task.world, answer)
        except (ValueError, SyntaxError, KeyError, AttributeError) as exc:
            from opulse.tasks_v2.grade import Verdict

            return Verdict(False, "invalid_definition", {"error": str(exc)})
    return grade(task, answer)


def ascii_text(world: str, text: str) -> str:
    """Translate a legacy prompt fragment, preserving ordinary English prose."""
    operators, _ = names(world)
    for symbol in sorted(operators, key=len, reverse=True):
        text = text.replace(symbol, operators[symbol])
    comparison = {**_COMPARE, "≥": "ge", "≤": "le"}
    operand = r"(?<!\w)(?:-?\d+|[a-z])(?!\w)"
    chain = re.compile(rf"({operand})\s*(≥|≤|>=|<=|>|<)\s*({operand})\s*(≥|≤|>=|<=|>|<)\s*({operand})")
    text = chain.sub(lambda match: f"( {comparison[match.group(2)]}({match.group(1)}, {match.group(3)})"
                     f" and {comparison[match.group(4)]}({match.group(3)}, {match.group(5)}) )", text)
    pair = re.compile(rf"({operand})\s*(≥|≤|>=|<=|==|!=|>|<)\s*({operand})")
    text = pair.sub(lambda match: f"{comparison[match.group(2)]}({match.group(1)}, {match.group(3)})", text)
    text = re.sub(r"\b([a-z])\s+([f-z]\d+)\s+([a-z])\b",
                  lambda match: f"{match.group(2)}({match.group(1)}, {match.group(3)})", text)
    text = re.sub(r"(?<!\w)\[(-?\d+(?:,\s*-?\d+)*)?\]", lambda match:
                  f"List<{match.group(1) or ''}>", text)
    for symbol, name in {"≥": "ge", "≤": "le", "∈": "in", "∅": "empty",
                         "⊞": "append", "⊕": "concat", "⌃": "head", "⌄": "tail",
                         "ℒ": "length", "Σ": "sum", "⊙": "at", "≍": "equal",
                         "ℓ": "length", "↶": "rev", "⌑": "first", "⇥": "drop",
                         "⇧": "upper", "⇩": "lower", "≡": "equal", "⊲": "cons"}.items():
        text = text.replace(symbol, name)
    text = text.replace("length le ", "length up to ")
    return text
