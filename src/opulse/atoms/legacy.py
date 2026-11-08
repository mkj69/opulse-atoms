"""Translate legacy definitions and robot skills (atoms-v2 spec section 13)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from operator import eq, ge, gt, le, lt, ne

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom, Defn, DictScope
from opulse.atoms.values import Bottom
from opulse.core.semantics import NAN, base_operation_name
from opulse.core.types import matches
from opulse.definition import ast
from opulse.definition.codegen import registry_resolver


@dataclass(frozen=True)
class LegacyInfo:
    operators: dict[str, object]
    names: dict[str, str]
    search_names: frozenset[str] = frozenset()
    conditional_names: frozenset[str] = frozenset()
    translate: Callable | None = None


def scope_from_registry(registry, semantics, parser) -> tuple[DictScope, LegacyInfo]:
    """Use the same host functions and symbol resolution as the reference interpreter."""
    operations = semantics.operations()
    resolve = registry_resolver(registry)
    atoms = [Atom("__legacy_nan", 0, lambda: NAN, cost=0),
             Atom("__legacy_enter", 0, lambda: True, cost=0)]
    comparisons = {"==": eq, "!=": ne, "<": lt, ">": gt, "<=": le, ">=": ge}
    for symbol, compare in comparisons.items():
        atoms.append(Atom(f"__legacy_compare_{symbol}", 2,
                          lambda left, right, fn=compare: NAN if left is NAN or right is NAN
                          else fn(left, right), cost=0))
    atoms.extend((Atom("__legacy_canon", 1, semantics.enter, cost=0),  # modular worlds: values enter as hours
                  Atom("__legacy_next", 1, lambda value: value + 1, cost=0),
                  Atom("__legacy_within", 2, lambda value, bound: value <= bound, cost=0)))

    def expression(expr):
        if isinstance(expr, ast.Var):
            return n.Var(expr.name)
        if isinstance(expr, (ast.Num, ast.Literal)):
            return n.Lit(semantics.enter(expr.value))
        if isinstance(expr, ast.NaN):
            return n.Call("__legacy_nan")
        if isinstance(expr, ast.Apply):
            return n.Call(resolve(expr).func_id, tuple(expression(arg) for arg in expr.args))
        if isinstance(expr, ast.Search):
            # The loop counts raw indices; the condition and the result see the entered value.
            index, raw = n.Var(expr.index), n.Var("__legacy_index")
            return n.Rec("__legacy_search", ("__legacy_index",),
                         n.Let(expr.index, n.Call("__legacy_canon", (raw,)),
                               n.Case(((condition(expr.condition), index),
                                       (n.Test(n.Call("__legacy_within", (raw, n.Lit(expr.bound - 1)))),
                                        n.Call("__legacy_search", (n.Call("__legacy_next", (raw,)),)))),
                                      n.Call("__legacy_nan"))),
                         (n.Lit(0),), "legacy")
        raise TypeError(f"unknown legacy expression {expr!r}")

    def condition(cond):
        if isinstance(cond, ast.Truth):
            return n.Test(expression(cond.expr))
        if isinstance(cond, ast.Compare):
            return n.Test(n.Call(f"__legacy_compare_{cond.op}",
                                 (expression(cond.left), expression(cond.right))))
        if isinstance(cond, ast.And):
            return n.And(condition(cond.left), condition(cond.right))
        if isinstance(cond, ast.Or):
            return n.Or(condition(cond.left), condition(cond.right))
        if isinstance(cond, ast.Not):
            return n.Not(condition(cond.operand))
        raise TypeError(f"unknown legacy condition {cond!r}")

    defns = []
    search_names = set()
    conditional_names = set()
    operators = {op.func_id: op for op in registry}
    for op in registry:
        if op.definition is None:
            name = base_operation_name(op.symbol, op.n_ary, op.unary_position)
            fn = operations[name] if name is not None else operations[op.primitive_name or op.func_id]
            atoms.append(Atom(op.func_id, op.n_ary, fn))
            continue
        parsed = parser.parse(op.definition)
        if any(branch.condition is not None for branch in parsed.branches):
            conditional_names.add(op.func_id)
        if any(isinstance(branch.expr, ast.Search) for branch in parsed.branches):
            search_names.add(op.func_id)
        params = tuple(arg.name for arg in parsed.lhs.args)
        if len(parsed.branches) == 1 and parsed.branches[0].condition is None:
            body = expression(parsed.branches[0].expr)
        else:
            body = n.Case(tuple((condition(branch.condition),
                                 n.Let("__legacy_branch", n.Call("__legacy_body"),
                                       expression(branch.expr)))
                                for branch in parsed.branches if branch.condition is not None),
                          next((n.Let("__legacy_branch", n.Call("__legacy_body"),
                                       expression(branch.expr)) for branch in parsed.branches
                                if branch.condition is None), None))
        if op.result_type != "int" or any(kind != "int" for kind in op.parameter_types):
            guard_name = f"__legacy_guard_{op.func_id}"
            kinds = op.parameter_types
            atoms.append(Atom(guard_name, len(params),
                              lambda *values, types=kinds: all(value is NAN or matches(value, kind)
                                                               for value, kind in zip(values, types)), cost=0))
            body = n.Case(((n.Test(n.Call(guard_name, tuple(n.Var(param) for param in params))), body),),
                          n.Call("__legacy_nan"))
        defns.append(Defn(op.func_id, params,
                          n.Let("__legacy_entry", n.Call("__legacy_enter"), body),
                          layer=(op.recursive_layer or 0) + 1))
    atoms.append(Atom("__legacy_body", 0, lambda: True, cost=0))
    return DictScope(atoms, defns), LegacyInfo(operators,
                                              {op.func_id: op.symbol for op in registry},
                                              frozenset(search_names), frozenset(conditional_names),
                                              expression)


def scope_from_skills(library) -> tuple[DictScope, LegacyInfo]:
    """Map robot actions to counted atoms and observations to free probes."""
    from opulse.core.primitives import CUSTOM
    from opulse.worlds.action import ACTION_RULES, OBS_RULES, apply_atom

    atoms = [Atom("__legacy_nan", 0, lambda: NAN, cost=0),
             Atom("__legacy_enter", 0, lambda: True, cost=0),
             Atom("__legacy_next", 1, lambda value: value + 1, cost=0),
             Atom("__legacy_less", 2, lambda value, bound: value < bound, cost=0),
             Atom("__legacy_robot_valid", 1, lambda state: state is not NAN, cost=0),
             Atom("__legacy_robot_equal", 2, lambda left, right: NAN if left is NAN else left == right,
                  cost=0)]

    def robot_atom(rule, state):
        result = apply_atom(rule, state)
        return Bottom("blocked") if rule == "forward" and result is NAN else result

    for name in (*ACTION_RULES, *OBS_RULES):
        atoms.append(Atom(name, 1, lambda state, rule=name: robot_atom(rule, state),
                          kind="observation" if name in OBS_RULES else "operation",
                          cost=0 if name in OBS_RULES else 1))
        if name in ACTION_RULES:
            atoms.append(Atom(f"__legacy_success_{name}", 1,
                              lambda state, rule=name: apply_atom(rule, state) is not NAN, cost=0))
    for name, primitive in CUSTOM.items():
        if primitive.parameter_types == ("state",) and name not in ACTION_RULES and name not in OBS_RULES:
            atoms.append(Atom(name, 1, lambda state, rule=name: apply_atom(rule, state),
                              kind="observation" if primitive.result_type != "state" else "operation",
                              cost=0 if primitive.result_type != "state" else 1))
            if primitive.result_type == "state":
                atoms.append(Atom(f"__legacy_success_{name}", 1,
                                  lambda state, rule=name: apply_atom(rule, state) is not NAN, cost=0))
    atoms.append(Atom("__legacy_robot_blocked", 0, lambda: Bottom("blocked"), cost=0))

    def action(ref, state):
        if ref in library:
            return n.Call(ref, (state,))
        return n.Case(((n.Test(n.Call(f"__legacy_success_{ref}", (state,))),
                        n.Call(ref, (state,))),), n.Call("__legacy_robot_blocked"))

    def probe(skill, state):
        return n.Test(n.Call("__legacy_robot_equal",
                             (n.Call(skill.guard, (state,)), n.Lit(skill.expected))))

    defns = []
    for skill in library.values():
        state = n.Var("state")
        if skill.kind == "composition":
            body = n.Let("after", action(skill.first, state),
                         n.Case(((n.Test(n.Call("__legacy_robot_valid", (n.Var("after"),))),
                                  action(skill.second, n.Var("after"))),), n.Var("after")))
        elif skill.kind == "branch":
            body = n.Case(((probe(skill, state), action(skill.first, state)),),
                          action(skill.second, state))
        else:
            index = n.Var("index")
            body = n.Rec("__legacy_repeat", ("current", "index"),
                         n.Case(((n.Test(n.Call("__legacy_robot_valid", (n.Var("current"),))),
                                  n.Case(((n.Test(n.Call("__legacy_less", (index, n.Lit(skill.bound)))),
                                  n.Case(((probe(skill, n.Var("current")), n.Var("current")),),
                                         n.Let("after", action(skill.first, n.Var("current")),
                                               n.Call("__legacy_repeat", (n.Var("after"),
                                                   n.Call("__legacy_next", (index,))))))),),
                                         n.Var("current"))),), n.Var("current")),
                         (state, n.Lit(0)), "legacy")
        body = n.Case(((n.Test(n.Call("__legacy_robot_valid", (state,))), body),),
                      n.Call("__legacy_nan"))
        defns.append(Defn(skill.name, ("state",),
                          n.Let("__legacy_entry", n.Call("__legacy_enter"), body),
                          layer=skill.layer + 1))
    return DictScope(atoms, defns), LegacyInfo({}, {name: name for name in library})


def legacy_definition_records(registry, scope: DictScope) -> list:
    """``opulse.definition/2`` records of a legacy registry (spec 13.1), translated by ``scope_from_registry``.

    Base operators become given layer-0 operations (status promoted, host body). Defined operators
    become invented operations whose body is the kernel translation; the old ``definition_type``
    and the original definition text travel in ``spec.extra`` and are never re-derived. Their
    status is ``callable``: published examples are not verification evidence.
    """
    from opulse.atoms.spec import Definition, Edge, OperationSpec

    records = []
    for op in registry:
        inputs = tuple(Edge(kind) for kind in op.parameter_types)
        role = "decide" if op.result_type == "bool" else "combine" if op.n_ary > 1 else "transform"
        extra = {"symbol": op.symbol, "definition_type": op.definition_type, "legacy_definition": op.definition}
        if op.definition is None:
            spec = OperationSpec(op.func_id, role, inputs, Edge(op.result_type), op.primitive_name or op.symbol,
                                 extra=extra)
            records.append(Definition(op.func_id, "operation", "given", 0, (), spec, {"host": op.func_id},
                                      status="promoted"))
            continue
        defn = scope.defns[op.func_id]
        extra["input_names"] = list(defn.params)
        spec = OperationSpec(op.func_id, role, inputs, Edge(op.result_type), op.definition, extra=extra)
        depends = tuple(sorted(n.references(defn.body)))  # includes the zero-cost dialect helpers
        records.append(Definition(op.func_id, "operation", "invented", (op.recursive_layer or 0) + 1,
                                  depends, spec, defn.body, status="callable"))
    return records
