"""Local law and bridge checks (docs/spec/atoms-v2.md, sections 3 and 9).

Keep the two pending core records and their evaluation adapter together here.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from functools import lru_cache
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.values import (
    Bottom,
    Card,
    Ok,
    Unknown,
    decode,
    decode_outcome,
    outcome_equal,
    truth,
)
from opulse.tasks_v2 import kernel_engine as engine
from opulse.tasks_v2 import library_defs


@dataclass(frozen=True)
class Evidence:
    method: str
    scope: tuple

    def __post_init__(self):
        if self.method not in ("exhaustive", "bounded", "sampled"):
            raise ValueError("invalid evidence method")


@dataclass(frozen=True)
class Law:
    name: str
    variables: tuple[tuple[str, str], ...]
    lhs: n.Node
    rhs: n.Node
    relation: str = "eq"
    scope: tuple[tuple[object, ...], ...] = ()
    evidence: Evidence | None = None

    def __post_init__(self):
        if self.relation not in ("eq", "le", "implies") or len({name for name, _ in self.variables}) != len(self.variables):
            raise ValueError("invalid law")
        if self.evidence is None and self.scope:
            object.__setattr__(self, "evidence", Evidence("bounded", self.scope))

    def __str__(self):
        params = ", ".join(f"{name}: {sort}" for name, sort in self.variables)
        return f"law #{self.name}: {self.relation}({print_node(self.lhs)}, {print_node(self.rhs)}) for {params}"


@dataclass(frozen=True)
class Bridge:
    name: str
    source_sort: str
    target_sort: str
    map: n.Node
    interface: tuple[tuple[str, str], ...]
    domain: n.Node
    scope: tuple[tuple[object, ...], ...] = ()
    source_world: str = "integer@1"
    target_world: str = "integer@1"
    evidence: Evidence | None = None

    def __post_init__(self):
        if self.evidence is None and self.scope:
            checked, _ = bridge_coverage(self)
            object.__setattr__(self, "evidence", Evidence("bounded", tuple(dict.fromkeys(
                row for _, row in checked))))

    def __str__(self):
        return f"bridge ~{self.name}: {self.source_sort} -> {self.target_sort}"

    def apply(self, value):
        return evaluate(self.map, {"x": value}, self.target_world)


def print_node(node):
    if not isinstance(node, (n.Var, n.Lit, n.Call)) or any(
        not isinstance(child, (n.Var, n.Lit, n.Call)) for child in n.walk(node)
    ):
        raise ValueError("ASCII printer accepts calls, variables, and literals")
    def text(item):
        if isinstance(item, n.Var):
            return item.name
        if isinstance(item, n.Lit):
            return display(item.value)
        return f"{item.fn}({', '.join(text(arg) for arg in item.args)})"

    return text(node)


def parse_node(text, variables):
    def convert(expr):
        if isinstance(expr, ast.Name) and expr.id in ("true", "false"):
            return n.Lit(expr.id == "true")
        if isinstance(expr, ast.Name) and expr.id in variables:
            return n.Var(expr.id)
        if isinstance(expr, ast.Constant) and type(expr.value) is int:
            return n.Lit(expr.value)
        if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.USub) and isinstance(expr.operand, ast.Constant) and type(expr.operand.value) is int:
            return n.Lit(-expr.operand.value)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and not expr.keywords:
            return n.Call(expr.func.id, tuple(convert(arg) for arg in expr.args))
        raise ValueError("invalid expression")
    return convert(ast.parse(text, mode="eval").body)


def parse_law(text, scope=()):
    import re

    match = re.fullmatch(r"law #([a-z][a-z_0-9]*): (eq|le|implies)\((.*)\) for (.*)", text)
    if match is None:
        raise ValueError("invalid law notation")
    name, relation, body, params = match.groups()
    fields = [re.fullmatch(r"([a-z][a-z_0-9]*): ([A-Za-z][A-Za-z0-9]*)", item)
              for item in params.split(", ")]
    if not fields or any(field is None for field in fields):
        raise ValueError("invalid law parameters")
    variables = tuple(field.groups() for field in fields)
    parsed = ast.parse(f"{relation}({body})", mode="eval").body
    if not isinstance(parsed, ast.Call) or len(parsed.args) != 2:
        raise ValueError("law needs two sides")
    variable_names = {item[0] for item in variables}
    return Law(name, variables, parse_node(ast.unparse(parsed.args[0]), variable_names),
               parse_node(ast.unparse(parsed.args[1]), variable_names), relation, tuple(scope))


def parse_bridge(text, prototype):
    import re

    match = re.fullmatch(r"bridge ~([a-z][a-z_0-9]*): ([A-Za-z][A-Za-z0-9]*) -> ([A-Za-z][A-Za-z0-9]*) = (.+)", text)
    if match is None or (match.group(2), match.group(3)) != (prototype.source_sort, prototype.target_sort):
        raise ValueError("invalid bridge notation")
    return Bridge(match.group(1), prototype.source_sort, prototype.target_sort,
                  parse_node(match.group(4), {"x"}), prototype.interface, prototype.domain,
                  prototype.scope, prototype.source_world, prototype.target_world)


def _fraction_canon(value):
    if isinstance(value, Card) and value.sort == "pair[int,int]" and len(value.fields) == 2:
        value = engine.fraction(*value.fields)
    return engine.canonical(value)


def _mul8(left, right):
    return (left * right) % 256


def _square8(value):
    return _mul8(value, value)


@lru_cache(maxsize=3)
def _scope(world):
    base = (kernel.DictScope() if world == "computer@1" else
            engine.scope(world, library_defs.records()[1]))
    extras = {
        "gcd": kernel.Atom("gcd", 2, math.gcd),
        "mod": kernel.Atom("mod", 2, lambda left, right: Bottom("zero") if right == 0 else left % right),
        "as_list": kernel.Atom("as_list", 1, lambda value: engine.list_items(value) if isinstance(value, Card) and value.sort == "ilist" else value),
        "pair_add_base": kernel.Atom("pair_add_base", 2, lambda left, right: Card("pair[int,int]", "pair", (left.fields[0] * right.fields[1] + right.fields[0] * left.fields[1], left.fields[1] * right.fields[1]))),
        "fraction_canon": kernel.Atom("fraction_canon", 1, _fraction_canon),
        "MUL": kernel.Atom("MUL", 2, _mul8),
        "square_mod256": kernel.Atom("square_mod256", 1, _square8),
        "mul_mod256": kernel.Atom("mul_mod256", 2, _mul8),
        "nonzero_den": kernel.Atom("nonzero_den", 1, lambda value: value.fields[1] != 0),
        "byte_domain": kernel.Atom("byte_domain", 1, lambda value: type(value) is int and 0 <= value <= 255),
        "increment": kernel.Atom("increment", 1, lambda value: value + 1),
    }
    definitions = {
        "invented_list_sum": kernel.Defn("invented_list_sum", ("x",), n.Call("isum", (n.Var("x"),))),
        "pair_add": kernel.Defn("pair_add", ("left", "right"),
                                n.Call("pair_add_base", (n.Var("left"), n.Var("right")))),
        "invented_square8": kernel.Defn("invented_square8", ("x",),
                                        n.Call("MUL", (n.Var("x"), n.Var("x")))),
    }
    return kernel.DictScope({**base.atoms, **extras}, {**base.defns, **definitions})


def evaluate(node, bindings=None, world="integer@1", fuel=20000):
    dialect = "atoms-v2" if world == "computer@1" else engine.world(world).dialect
    return kernel.evaluate(node, bindings or {}, _scope(world), kernel.Limits(fuel=fuel),
                           dialect=dialect).outcome


def law_instance(law, assignment):
    if len(assignment) != len(law.variables):
        raise ValueError("assignment arity")
    env = dict(zip((name for name, _ in law.variables), assignment))
    left, right = evaluate(law.lhs, env), evaluate(law.rhs, env)
    if isinstance(left, Unknown) or isinstance(right, Unknown):
        return False
    if law.relation == "eq":
        return outcome_equal(left, right)
    if not isinstance(left, Ok) or not isinstance(right, Ok):
        return False
    if law.relation == "le":
        return type(left.value) is int and type(right.value) is int and left.value <= right.value
    try:
        return not truth(left.value) or truth(right.value)
    except TypeError:
        return False


def check_law(law):
    return (bool(law.scope) and (law.evidence is None or all(row in law.evidence.scope for row in law.scope))
            and all(law_instance(law, assignment) for assignment in law.scope))


def nontrivial_law(law):
    """Reject equations valid even when every operation is uninterpreted."""
    names = set(n.references(law.lhs)) | set(n.references(law.rhs))
    calls = [node for side in (law.lhs, law.rhs) for node in n.walk(side) if isinstance(node, n.Call)]
    arities = {name: {len(call.args) for call in calls if call.fn == name} for name in names}
    if any(len(sizes) != 1 for sizes in arities.values()):
        return False
    atoms = [kernel.Atom(name, next(iter(sizes)), lambda *args, name=name: Card("term", name, args))
             for name, sizes in arities.items()]
    bindings = {name: Card("symbol", name) for name, _ in law.variables}
    left = kernel.evaluate(law.lhs, bindings, kernel.DictScope(atoms)).outcome
    right = kernel.evaluate(law.rhs, bindings, kernel.DictScope(atoms)).outcome
    return not isinstance(left, Unknown) and not isinstance(right, Unknown) and not outcome_equal(left, right)


def apply_law(law, term, bindings):
    """Replay one equation rewrite only for a checked assignment and matching term."""
    if law.relation != "eq" or (law.evidence is not None and law.evidence.method == "sampled") or not check_law(law):
        raise ValueError("law is not a checked equation")
    assignment = tuple(bindings[name] for name, _ in law.variables)
    if assignment not in law.scope:
        raise ValueError("outside checked scope")
    def substitute(node):
        if isinstance(node, n.Var):
            return n.Lit(bindings[node.name])
        if isinstance(node, n.Call):
            return n.Call(node.fn, tuple(substitute(arg) for arg in node.args))
        return node
    source, result = substitute(law.lhs), substitute(law.rhs)
    if term != source or not outcome_equal(evaluate(source), evaluate(result)):
        raise ValueError("rewrite does not replay")
    return result


def bridge_instance(bridge, pair, assignment):
    if pair not in bridge.interface:
        raise ValueError("undeclared interface")
    source_op, target_op = pair
    operation = _scope(bridge.source_world).resolve(source_op)
    target_operation = _scope(bridge.target_world).resolve(target_op)
    if operation is None or target_operation is None:
        return False
    arity = operation.arity if isinstance(operation, kernel.Atom) else len(operation.params)
    target_arity = (target_operation.arity if isinstance(target_operation, kernel.Atom)
                    else len(target_operation.params))
    if arity != target_arity:
        return False
    if len(assignment) != arity:
        return None
    for value in assignment:
        domain_result = evaluate(bridge.domain, {"x": value}, bridge.source_world)
        if isinstance(domain_result, Unknown):
            return False
        if not isinstance(domain_result, Ok):
            return False
        try:
            if not truth(domain_result.value):
                return None
        except TypeError:
            return False
    source = evaluate(n.Call(source_op, tuple(n.Lit(item) for item in assignment)), world=bridge.source_world)
    if isinstance(source, Unknown):
        return False
    translated_args = [bridge.apply(value) for value in assignment]
    if any(not isinstance(value, Ok) for value in translated_args):
        return False
    target = evaluate(n.Call(target_op, tuple(n.Lit(value.value) for value in translated_args)), world=bridge.target_world)
    translated_result = bridge.apply(source.value) if isinstance(source, Ok) else source
    return outcome_equal(target, translated_result)


def bridge_coverage(bridge):
    """Partition scope rows by whether each interface obligation was checked."""
    checked = []
    excluded = []
    for pair in bridge.interface:
        for row in bridge.scope:
            result = bridge_instance(bridge, pair, row)
            (excluded if result is None else checked).append((pair, row))
    return checked, excluded


def check_bridge(bridge):
    if not bridge.scope or not bridge.interface:
        return False
    checked, _ = bridge_coverage(bridge)
    if bridge.evidence is not None and any(row not in bridge.evidence.scope for _, row in checked):
        return False
    for pair in bridge.interface:
        results = [bridge_instance(bridge, candidate, row) for candidate, row in checked
                   if candidate == pair]
        if not any(result is True for result in results) or False in results:
            return False
    return True


def references():
    integer = tuple(product(range(-3, 4), repeat=2))
    variables = (("a", "Int"), ("b", "Int"))
    def call(name, *args):
        return n.Call(name, args)
    a, b = n.Var("a"), n.Var("b")
    laws = [Law(f"{op}_comm", variables, call(op, a, b), call(op, b, a), scope=integer,
                evidence=Evidence("bounded", integer)) for op in ("add", "mul", "sub")]
    laws += [Law(f"{op}_assoc", (("a", "Int"), ("b", "Int"), ("c", "Int")),
                 call(op, call(op, a, b), n.Var("c")), call(op, a, call(op, b, n.Var("c"))),
                 scope=tuple(product(range(-2, 3), repeat=3))) for op in ("add", "mul")]
    gcd_scope = tuple((left, right) for left, right in integer if right != 0)
    laws += [Law("gcd_step", variables, call("gcd", a, b), call("gcd", b, call("mod", a, b)), scope=gcd_scope)]
    frac = (engine.fraction(1, 2), engine.fraction(2, 3), engine.fraction(-1, 4))
    laws += [Law("frac_add_comm", (("a", "Frac"), ("b", "Frac")), call("frac_add", a, b),
                 call("frac_add", b, a), scope=tuple(product(frac, repeat=2))),
             Law("raw_frac_add_commutes_with_canon", (("a", "Frac"), ("b", "Frac")),
                 call("fraction_canon", call("raw_frac_add", a, b)), call("frac_add", a, b),
                 scope=tuple(product(frac, repeat=2)))]
    lists = tuple(engine.ilist(items) for items in ((), (1,), (-2, 3), (4, 0, 2)))
    for op, result in (("isum", "add"), ("ilen", "add")):
        laws.append(Law(f"{op}_append", (("a", "List"), ("b", "List")),
                        call(op, call("iappend", a, b)), call(result, call(op, a), call(op, b)),
                        scope=tuple(product(lists, repeat=2))))
    laws.append(Law("ilen_left_only", (("a", "List"), ("b", "List")),
                    call("ilen", call("iappend", a, b)), call("ilen", a),
                    scope=tuple(product(lists, repeat=2))))
    return {law.name: law for law in laws}


def bridges():
    raw = tuple(Card("pair[int,int]", "pair", fields) for fields in ((1, 2), (2, 4), (2, 0)))
    lists = (engine.ilist(()), engine.ilist((1, 2)), engine.ilist((-1, 3)))
    pairs = tuple(product(raw, repeat=2))
    result = {
        "pair_to_frac": Bridge("pair_to_frac", "Pair", "Frac", n.Call("fraction_canon", (n.Var("x"),)),
                               (("pair_add", "frac_add"),), n.Call("nonzero_den", (n.Var("x"),)), pairs),
        "ilist_to_list": Bridge("ilist_to_list", "IList", "List", n.Call("as_list", (n.Var("x"),)),
                                (("isum", "list_sum"), ("ilen", "list_length"), ("iappend", "list_append"),
                                 ("invented_list_sum", "list_sum")),
                                n.Lit(True), tuple((item,) for item in lists) + tuple(product(lists, repeat=2)),
                                target_world="lists@1"),
        "mul8": Bridge("mul8", "Byte", "Int", n.Var("x"),
                       (("MUL", "mul_mod256"), ("invented_square8", "square_mod256")),
                       n.Call("byte_domain", (n.Var("x"),)),
                       tuple((value,) for value in (0, 1, 2, 15, 255)) + tuple(product((0, 1, 2, 15, 255), repeat=2)),
                       source_world="computer@1"),
        "broken_mul8": Bridge("broken_mul8", "Byte", "Int", n.Call("increment", (n.Var("x"),)),
                              (("MUL", "mul_mod256"),), n.Call("byte_domain", (n.Var("x"),)),
                              tuple(product((0, 1, 2, 15), repeat=2)), source_world="computer@1"),
    }
    for name in ("pair_to_frac", "ilist_to_list"):
        original = result[name]
        result[f"broken_{name}"] = Bridge(f"broken_{name}", original.source_sort,
            original.target_sort, n.Var("x"), original.interface, original.domain,
            original.scope, original.source_world, original.target_world)
    return result


def pack(value):
    return engine.wire(value)


def outcome_wire(value):
    if isinstance(value, Ok) and isinstance(value.value, tuple):
        return engine.outcome_wire(Ok(Card("list[int]", "list", value.value)))
    return engine.outcome_wire(value)


def outcome_unwire(value):
    result = decode_outcome(value)
    if isinstance(result, Ok) and isinstance(result.value, Card) and result.value.sort == "list[int]":
        return Ok(result.value.fields)
    return result


def display(value):
    if isinstance(value, tuple):
        return "List<" + ", ".join(display(item) for item in value) + ">"
    if isinstance(value, Card) and value.sort == "pair[int,int]":
        return "Pair<" + ", ".join(display(item) for item in value.fields) + ">"
    return engine._notation(value)


def display_scope(rows):
    return "[" + ", ".join("(" + ", ".join(display(value) for value in row) + ")" for row in rows) + "]"


def compact_scope(variables, rows):
    """Describe finite product scopes without dumping serialized assignments."""
    parts = []
    for column, (name, _) in enumerate(variables):
        values = tuple(dict.fromkeys(row[column] for row in rows))
        if values and all(type(value) is int for value in values) and set(values) == set(range(min(values), max(values) + 1)):
            domain = f"{min(values)}..{max(values)}"
        else:
            domain = "{" + ", ".join(display(value) for value in values) + "}"
        parts.append(f"{name} in {domain}")
    return "; ".join(parts) + " (" + str(len(rows)) + " checked assignments)"


def definitions(*nodes, world="integer@1"):
    """Only explain operations referenced by this question."""
    names = set().union(*(n.references(node) for node in nodes))
    rules = {
        "add": "integer sum", "mul": "integer product", "sub": "integer difference",
        "gcd": "greatest common divisor", "mod": "remainder (nonzero divisor)",
        "frac_add": "canonical rational sum", "fraction_canon": "reduce fraction with positive denominator",
        "raw_frac_add": "add raw numerator/denominator fields", "iappend": "concatenate ILists",
        "isum": "sum IList items", "ilen": "count IList items", "as_list": "convert IList to native List",
        "pair_add": "raw rational sum of Pairs", "nonzero_den": "denominator is nonzero",
        "byte_domain": "integer from 0 through 255", "MUL": "multiply modulo 256",
        "mul_mod256": "multiply modulo 256", "square_mod256": "square modulo 256",
        "increment": "add one", "list_sum": "sum List items", "list_length": "count List items",
        "list_append": "concatenate Lists", "invented_list_sum": "sum IList items",
        "invented_square8": "square modulo 256",
    }
    return "Definitions: " + "; ".join(f"{name}(...) = {rules[name]}" for name in sorted(names)) + "."


def rewrite_at(law, term, path, bindings):
    """Replay a checked rewrite at a path of zero-based Call argument indices."""
    if not path:
        return apply_law(law, term, bindings)
    if not isinstance(term, n.Call) or not 0 <= path[0] < len(term.args):
        raise ValueError("invalid rewrite position")
    args = list(term.args)
    args[path[0]] = rewrite_at(law, args[path[0]], path[1:], bindings)
    return n.Call(term.fn, tuple(args))


def rewrite_expression(law, term, bindings):
    """Replay a checked equation whose variables stand for concrete expressions."""
    if law.relation != "eq" or (law.evidence is not None and law.evidence.method == "sampled") or not check_law(law):
        raise ValueError("law is not a checked equation")
    values = {name: evaluate(expression) for name, expression in bindings.items()}
    if any(not isinstance(value, Ok) for value in values.values()):
        raise ValueError("undefined binding")
    assignment = tuple(values[name].value for name, _ in law.variables)
    if assignment not in law.scope:
        raise ValueError("outside checked scope")

    def substitute(node):
        if isinstance(node, n.Var):
            return bindings[node.name]
        if isinstance(node, n.Call):
            return n.Call(node.fn, tuple(substitute(arg) for arg in node.args))
        return node

    source, target = substitute(law.lhs), substitute(law.rhs)
    if source != term or not outcome_equal(evaluate(source), evaluate(target)):
        raise ValueError("rewrite does not replay")
    return target


def unpack(value):
    return decode(value)


def task(kind, angle, seed, index, question, reference, scope, prompt, shape=None):
    from opulse.tasks_v2.task import (
        METHODS,
        Task,
        default_boundary,
        default_observation,
    )

    answer_shape = shape or {"compute": "value", "invert": "all_solutions", "decide": "verdict",
                             "describe": "choice", "induce": "definition", "create": "definition"}[angle]
    variant = "one_shot" if angle == "create" and index % 2 == 0 else "reusable" if angle == "create" else None
    world = question.get("source_world", "integer@1")
    return Task(f"{world}/{kind}/{angle}/{seed}/{index}", world, angle, kind, question["name"], variant,
                default_boundary(), default_observation(), answer_shape, "full_state", question,
                {"en": prompt}, reference, {"method": METHODS[answer_shape], "fuel": 20000,
                                                   "scope": scope},
                {"generator": f"tasks_v2.angles.{kind}", "seed": seed, "index": index})


def verdict(correct, reason=None, **detail):
    from opulse.tasks_v2.grade import Verdict

    return Verdict(correct, reason or ("correct" if correct else "mismatch"), detail)


def grade(task_record, answer):
    """One local entry point until the six-kind dispatcher is owned by core."""
    if task_record.kind == "law":
        from opulse.tasks_v2.angles import law

        return law.grade(task_record, answer)
    if task_record.kind == "bridge":
        from opulse.tasks_v2.angles import bridge

        return bridge.grade(task_record, answer)
    raise ValueError("expected law or bridge task")
