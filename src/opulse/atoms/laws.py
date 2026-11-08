"""Law verification and scoped rewrite derivations (atoms-v2 spec 0.4, laws)."""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from opulse.atoms import kernel, nodes
from opulse.atoms.library import (
    DEFAULT_VERIFY_FUEL,
    PipelineError,
    VerifyResult,
    atoms_digest,
)
from opulse.atoms.spec import Definition, LawSpec, OperationSpec, _free_vars
from opulse.atoms.values import (
    Card,
    Ok,
    Unknown,
    decode,
    encode,
    outcome_equal,
    truth,
    value_equal,
)


class RewriteError(ValueError):
    """A rewrite is inapplicable, unverified, or fails layer-0 replay."""


@dataclass(frozen=True)
class RewriteStep:
    law: str
    path: tuple[int, ...]
    before: nodes.Node
    after: nodes.Node


@dataclass(frozen=True)
class Derivation:
    steps: tuple[RewriteStep, ...]
    charged_steps: int
    rewrite_steps: int = 0


def derivation_length(steps) -> int:
    """Number of promoted-law steps in a derivation, not layer-0 evaluation cost."""
    return len(steps.steps if isinstance(steps, Derivation) else steps)


def _sort(value):
    if isinstance(value, Card):
        return value.sort
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "str"
    return None


def _matches_sort(value, sort, world):
    actual = _sort(value)
    if sort in ("any", "unknown") or sort == actual:
        return True
    for obj in world.objects:
        if obj.name == sort and obj.form == "refine" and actual == obj.base:
            return True
        if obj.name == sort and obj.form == "given" and actual is None and value is not None:
            return True
    return False


def _scope_value(value):
    if type(value) is bool:
        return value
    if isinstance(value, (int, str, Card)):
        return json.dumps(encode(value), sort_keys=True)
    return value


def _read_scope_value(value):
    if isinstance(value, str):
        return decode(json.loads(value))
    return value


def _tuple_digest(values):
    encoded = json.dumps([_scope_value(value) for value in values], sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def check_law(defn: Definition, lib) -> list[str]:
    """Check the boolean statement, typed variables, and every resolved call."""
    if not isinstance(defn.spec, LawSpec):
        return ["law needs a LawSpec"]
    spec = defn.spec
    problems = []
    if spec.name != defn.name:
        problems.append("law spec name must match its definition")
    known_sorts = {"int", "str", "bool", "any", "unknown"} | {obj.name for obj in lib.world.objects}
    bindings = dict(spec.vars)
    for name, sort in spec.vars:
        if not name.isidentifier() or sort not in known_sorts:
            problems.append(f"unknown law variable or sort: {name}: {sort}")

    operations = {op.name: op for op in lib.world.operations}
    scope = lib.scope()

    def infer(node):
        if isinstance(node, nodes.Var):
            if node.name not in bindings:
                problems.append(f"undeclared law variable: {node.name}")
            return bindings.get(node.name)
        if isinstance(node, nodes.Lit):
            return _sort(node.value)
        if not isinstance(node, nodes.Call):
            problems.append(f"law statement cannot contain {type(node).__name__}")
            return None
        sorts = tuple(infer(arg) for arg in node.args)
        target = scope.resolve(node.fn)
        if target is None:
            problems.append(f"unresolved law call: {node.fn}")
            return None
        arity = target.arity if isinstance(target, kernel.Atom) else len(target.params)
        if len(sorts) != arity:
            problems.append(f"{node.fn} expects {arity} arguments, got {len(sorts)}")
        op = operations.get(node.fn)
        if op is None:
            other = lib.records().get(node.fn)
            op = other.spec if other is not None and isinstance(other.spec, OperationSpec) else None
        if op is not None:
            for index, (actual, expected) in enumerate(zip(sorts, op.inputs)):
                if actual not in (None, "any", "unknown") and expected.sort not in ("any", "unknown", actual):
                    problems.append(f"{node.fn} argument {index + 1}: expected {expected.sort}, got {actual}")
            return op.output.sort
        return None

    if infer(spec.statement) not in ("bool", "any"):
        problems.append("law statement must have boolean sort")
    if defn.body != spec.statement:
        problems.append("law body must equal its statement")
    return list(dict.fromkeys(problems))


def make_law_callable(defn: Definition, lib, sample) -> Definition:
    """Smoke-test a checked law before verification (pending library kind dispatch)."""
    if defn.status != "checked" or not sample:
        raise ValueError("callable law requires checked status and samples")
    for values in sample:
        if len(values) != len(defn.spec.vars):
            raise ValueError("law sample has the wrong arity")
        run = kernel.evaluate(defn.spec.statement,
                              dict(zip((name for name, _ in defn.spec.vars), values)),
                              lib.scope(), kernel.Limits(fuel=DEFAULT_VERIFY_FUEL), dialect=lib.dialect)
        if isinstance(run.outcome, Unknown):
            raise PipelineError(f"law sample is unknown: {values!r}")
    return lib._advance(defn.name, "callable")


def verify_law(defn: Definition, lib, request) -> VerifyResult:
    """Evaluate every declared tuple; store exact scope witnesses for later replay."""
    problems = check_law(defn, lib)
    if problems:
        return VerifyResult(False, (), problems, [])
    spec = defn.spec
    if not request.domain or request.scope.get("size") != len(request.domain) or not request.scope.get("domain"):
        return VerifyResult(False, (), ["law scope must describe the exact domain"], [])
    request.scope.pop("values", None)
    if len(request.domain) > 10_000 and "predicate" not in request.scope:
        return VerifyResult(False, (), ["large law scope needs a predicate"], [])
    if "predicate" in request.scope:
        predicate = request.scope["predicate"]
        try:
            if isinstance(predicate, str):
                predicate = json.loads(predicate)
            if isinstance(predicate, dict):
                predicate = nodes.from_json(predicate)
        except (TypeError, ValueError, KeyError):
            return VerifyResult(False, (), ["invalid law scope predicate"], [])
        if not isinstance(predicate, nodes.NODE_TYPES):
            return VerifyResult(False, (), ["scope predicate must be a boolean node"], [])
        if set(nodes.references(predicate)) - {op.name for op in lib.world.operations}:
            return VerifyResult(False, (), ["scope predicate has unresolved calls"], [])
        if any(isinstance(item, nodes.Var) and item.name not in {name for name, _ in spec.vars}
               for item in nodes.walk(predicate)):
            return VerifyResult(False, (), ["scope predicate has undeclared variables"], [])
        request.scope["predicate"] = nodes.to_json(predicate)
    scope = lib.scope()
    steps = []
    for values in request.domain:
        if len(values) != len(spec.vars) or any(
                not _matches_sort(value, sort, lib.world)
                for value, (_, sort) in zip(values, spec.vars)):
            problems.append(f"invalid law tuple: {values!r}")
            break
        env = dict(zip((name for name, _ in spec.vars), values))
        if "predicate" in request.scope:
            guard = kernel.evaluate(predicate, env, scope, kernel.Limits(fuel=DEFAULT_VERIFY_FUEL), dialect=lib.dialect)
            try:
                inside = isinstance(guard.outcome, Ok) and truth(guard.outcome.value)
            except (TypeError, ValueError):
                inside = False
            if not inside:
                problems.append(f"law scope predicate excludes checked tuple: {values!r}")
                break
        run = kernel.evaluate(spec.statement, env, scope, kernel.Limits(fuel=DEFAULT_VERIFY_FUEL), dialect=lib.dialect)
        steps.append(run.steps)
        try:
            holds = isinstance(run.outcome, Ok) and truth(run.outcome.value)
        except (TypeError, ValueError):
            holds = False
        if not holds:
            problems.append(f"law counterexample {values!r}: {run.outcome!r}")
            break
    if problems:
        return VerifyResult(False, (), problems, steps)
    if len(request.domain) <= 10_000:
        request.scope["values"] = tuple(tuple(_scope_value(value) for value in values)
                                        for values in request.domain)
    else:
        try:
            request.scope["value_hashes"] = tuple(sorted({_tuple_digest(values) for values in request.domain}))
        except TypeError:
            return VerifyResult(False, (), ["large law scope needs serializable values"], steps)
    checks = ("holds", "equation") if spec.equation is not None else ("holds",)
    return VerifyResult(True, checks, [], steps)


def _same_node(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, nodes.Lit):
        return value_equal(left.value, right.value)
    if isinstance(left, nodes.Call):
        return (left.fn == right.fn and len(left.args) == len(right.args)
                and all(_same_node(arg, other) for arg, other in zip(left.args, right.args)))
    return left == right


def _match(pattern, expr, vars, bindings):
    if isinstance(pattern, nodes.Var) and pattern.name in vars:
        if pattern.name in bindings:
            return _same_node(bindings[pattern.name], expr)
        bindings[pattern.name] = expr
        return True
    if type(pattern) is not type(expr):
        return False
    if isinstance(pattern, nodes.Call):
        return (pattern.fn == expr.fn and len(pattern.args) == len(expr.args)
                and all(_match(left, right, vars, bindings) for left, right in zip(pattern.args, expr.args)))
    if isinstance(pattern, nodes.Let):
        return (pattern.name == expr.name and _match(pattern.value, expr.value, vars, bindings)
                and _match(pattern.body, expr.body, vars - {pattern.name}, bindings))
    if isinstance(pattern, nodes.Case):
        return (len(pattern.arms) == len(expr.arms) and
                all(left_cond == right_cond and _match(left_body, right_body, vars, bindings)
                    for (left_cond, left_body), (right_cond, right_body) in zip(pattern.arms, expr.arms))
                and (pattern.default is None and expr.default is None or
                     pattern.default is not None and expr.default is not None and
                     _match(pattern.default, expr.default, vars, bindings)))
    if isinstance(pattern, nodes.Rec):
        return (pattern.fn == expr.fn and pattern.params == expr.params and
                (pattern.measure == expr.measure if isinstance(pattern.measure, str) or
                 isinstance(expr.measure, str) else
                 _match(pattern.measure, expr.measure, vars - set(pattern.params) - {pattern.fn}, bindings))
                and pattern.memo == expr.memo and len(pattern.args) == len(expr.args)
                and all(_match(left, right, vars, bindings)
                        for left, right in zip(pattern.args, expr.args))
                and _match(pattern.body, expr.body, vars - set(pattern.params) - {pattern.fn}, bindings))
    return _same_node(pattern, expr)


def _substitute(node, bindings):
    if isinstance(node, nodes.Var) and node.name in bindings:
        return bindings[node.name]
    if isinstance(node, nodes.Call):
        return nodes.Call(node.fn, tuple(_substitute(arg, bindings) for arg in node.args))
    if isinstance(node, nodes.Let):
        if any(node.name in _free_vars(value) for name, value in bindings.items()
               if name in _free_vars(node.body)):
            raise RewriteError("law variable would capture a Let binding")
        return nodes.Let(node.name, _substitute(node.value, bindings),
                         _substitute(node.body, {key: value for key, value in bindings.items() if key != node.name}))
    if isinstance(node, nodes.Case):
        return nodes.Case(tuple((condition, _substitute(body, bindings)) for condition, body in node.arms),
                          _substitute(node.default, bindings) if node.default is not None else None)
    if isinstance(node, nodes.Rec):
        local = set(node.params) | {node.fn}
        measure = node.measure
        local_bindings = {key: value for key, value in bindings.items() if key not in local}
        captured = _free_vars(node.body) | (_free_vars(measure) if not isinstance(measure, str) else set())
        if any(_free_vars(value) & local for name, value in local_bindings.items() if name in captured):
            raise RewriteError("law variable would capture a Rec binding")
        return nodes.Rec(node.fn, node.params,
                         _substitute(node.body, local_bindings),
                         tuple(_substitute(arg, bindings) for arg in node.args),
                         _substitute(measure, local_bindings) if not isinstance(measure, str) else measure,
                         node.memo)
    return node


def _at(expr, path):
    current = expr
    for index in path:
        if type(index) is not int or index < 0:
            raise RewriteError(f"invalid rewrite path: {path!r}")
        if isinstance(current, nodes.Call) and index < len(current.args):
            current = current.args[index]
        elif isinstance(current, nodes.Let) and index in (0, 1):
            current = (current.value, current.body)[index]
        elif isinstance(current, nodes.Case) and index < len(current.arms):
            current = current.arms[index][1]
        elif isinstance(current, nodes.Case) and index == len(current.arms) and current.default is not None:
            current = current.default
        elif isinstance(current, nodes.Rec) and index <= len(current.args):
            current = current.args[index] if index < len(current.args) else current.body
        else:
            raise RewriteError(f"invalid rewrite path: {path!r}")
    return current


def _put(expr, path, new):
    if not path:
        return new
    index = path[0]
    _at(expr, path[:1])
    if isinstance(expr, nodes.Call):
        args = list(expr.args)
        args[index] = _put(args[index], path[1:], new)
        return nodes.Call(expr.fn, tuple(args))
    if isinstance(expr, nodes.Let):
        return (nodes.Let(expr.name, _put(expr.value, path[1:], new), expr.body) if index == 0
                else nodes.Let(expr.name, expr.value, _put(expr.body, path[1:], new)))
    if isinstance(expr, nodes.Case):
        if index == len(expr.arms):
            return nodes.Case(expr.arms, _put(expr.default, path[1:], new))
        arms = list(expr.arms)
        condition, body = arms[index]
        arms[index] = (condition, _put(body, path[1:], new))
        return nodes.Case(tuple(arms), expr.default)
    if isinstance(expr, nodes.Rec):
        if index == len(expr.args):
            return nodes.Rec(expr.fn, expr.params, _put(expr.body, path[1:], new),
                             expr.args, expr.measure, expr.memo)
        args = list(expr.args)
        args[index] = _put(args[index], path[1:], new)
        return nodes.Rec(expr.fn, expr.params, expr.body, tuple(args), expr.measure, expr.memo)
    raise RewriteError(f"invalid rewrite path: {path!r}")


def _prepare(law, lib):
    if isinstance(law, str):
        try:
            law = lib.get(law.lstrip("#"))
        except KeyError as error:
            raise RewriteError(f"unknown law: {law}") from error
    if law.kind != "law" or not isinstance(law.spec, LawSpec) or law.spec.equation is None:
        raise RewriteError("rewrite needs an equation law")
    if law.origin != "given" and law.status != "promoted":
        raise RewriteError("rewrite needs a promoted law")
    if law.origin == "given" and (law.layer != 0 or law.status != "promoted"):
        raise RewriteError("given law must be a promoted layer-0 axiom")
    if law.origin != "given":
        current = lib.get(law.name)
        if current != law or law.evidence is None or law.evidence.method == "sampled":
            raise RewriteError("law evidence is missing or stale")
        if (law.evidence.world_hash != lib.world.world_hash()
                or law.evidence.atoms_hash != atoms_digest(lib.atoms)
                or law.evidence.content_hash != lib.content_hash(law.name)
                or law.evidence.deps_hash != lib._deps_hash(law.name)):
            raise RewriteError("law evidence is stale")
        if not {"holds", "equation"} <= set(law.evidence.checks):
            raise RewriteError("law equation has not been verified")
    return law


def _rewrite(expr, law, direction, path):
    if direction not in ("ltr", "rtl"):
        raise RewriteError(f"invalid rewrite direction: {direction}")
    left, right = law.spec.equation
    pattern, replacement = (left, right) if direction == "ltr" else (right, left)
    bindings = {}
    if not _match(pattern, _at(expr, path), {name for name, _ in law.spec.vars}, bindings):
        raise RewriteError("law does not match the expression")
    if _free_vars(replacement) - bindings.keys():
        raise RewriteError("replacement has unbound law variables")
    return _put(expr, path, _substitute(replacement, bindings)), bindings


def rewrite(expr, law_defn, lib, direction="ltr", at=()):
    """Apply one promoted equation at a path through call arguments or structured nodes."""
    law = _prepare(law_defn, lib)
    return _rewrite(expr, law, direction, tuple(at))[0]


def _in_scope(law, bindings, lib, env, scope):
    if law.origin == "given":
        return True
    values = []
    for name, _ in law.spec.vars:
        if name not in bindings:
            return False
        outcome = kernel.evaluate(bindings[name], env, scope, kernel.Limits(fuel=DEFAULT_VERIFY_FUEL),
                                  dialect=lib.dialect).outcome
        if not isinstance(outcome, Ok):
            return False
        values.append(outcome.value)
    evidence_scope = law.evidence.scope
    if "values" in evidence_scope:
        return any(len(row) == len(values)
                   and all(value_equal(_read_scope_value(a), b) for a, b in zip(row, values))
                   for row in evidence_scope["values"])
    predicate = evidence_scope.get("predicate")
    if predicate is None:
        return False
    hashes = evidence_scope.get("value_hashes", ())
    try:
        digest = _tuple_digest(values)
    except TypeError:
        return False
    offset = bisect_left(hashes, digest)
    if offset >= len(hashes) or hashes[offset] != digest:
        return False
    guard = kernel.evaluate(nodes.from_json(json.loads(predicate)) if isinstance(predicate, str)
                            else nodes.from_json(predicate) if isinstance(predicate, dict) else predicate,
                            dict(zip((name for name, _ in law.spec.vars), values)), scope,
                            kernel.Limits(fuel=DEFAULT_VERIFY_FUEL), dialect=lib.dialect).outcome
    try:
        return isinstance(guard, Ok) and truth(guard.value)
    except (TypeError, ValueError):
        return False


def replay_rewrite(expr, new_expr, law, lib, env: Mapping[str, object], *, fuel=DEFAULT_VERIFY_FUEL) -> Derivation:
    """Validate one actual rewrite, its verified bindings, and layer-0 outcomes."""
    law = _prepare(law, lib)
    scope = lib.scope()
    candidates = [()]
    for path in candidates:
        subexpr = _at(expr, path)
        if isinstance(subexpr, nodes.Call):
            candidates.extend(path + (index,) for index in range(len(subexpr.args)))
        elif isinstance(subexpr, nodes.Let):
            candidates.extend((path + (0,), path + (1,)))
        elif isinstance(subexpr, nodes.Case):
            candidates.extend(path + (index,) for index in range(len(subexpr.arms) +
                              (subexpr.default is not None)))
        elif isinstance(subexpr, nodes.Rec):
            candidates.extend(path + (index,) for index in range(len(subexpr.args) + 1))
        local_env = dict(env)
        ancestor = expr
        for index in path:
            if isinstance(ancestor, nodes.Let) and index == 1:
                value = kernel.evaluate(ancestor.value, local_env, scope,
                                        kernel.Limits(fuel=fuel), dialect=lib.dialect).outcome
                if isinstance(value, Ok):
                    local_env[ancestor.name] = value.value
                else:
                    break
            if isinstance(ancestor, nodes.Rec) and index == len(ancestor.args):
                if ancestor.fn in nodes.references(ancestor.body):
                    break
                arguments = [kernel.evaluate(arg, local_env, scope, kernel.Limits(fuel=fuel),
                                             dialect=lib.dialect).outcome for arg in ancestor.args]
                if not all(isinstance(arg, Ok) for arg in arguments):
                    break
                local_env.update(zip(ancestor.params, (arg.value for arg in arguments)))
            ancestor = _at(ancestor, (index,))
        else:
            for direction in ("ltr", "rtl"):
                try:
                    expected, bindings = _rewrite(expr, law, direction, path)
                except RewriteError:
                    continue
                if _same_node(expected, new_expr) and _in_scope(law, bindings, lib, local_env, scope):
                    original = kernel.evaluate(expr, env, scope, kernel.Limits(fuel=fuel), dialect=lib.dialect)
                    final = kernel.evaluate(new_expr, env, scope, kernel.Limits(fuel=fuel), dialect=lib.dialect)
                    if not outcome_equal(original.outcome, final.outcome):
                        raise RewriteError("rewrite disagrees with layer-0 replay")
                    return Derivation((RewriteStep(law.name, path, expr, new_expr),), final.steps)
    raise RewriteError("rewrite is not a law step within its verified scope")
