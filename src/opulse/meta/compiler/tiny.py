"""Static checker for tiny/1 (docs/spec/atoms-meta.md, section 5)."""

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Defn


def definition(value):
    """Accept a kernel definition or a (body, params) tiny definition."""
    if isinstance(value, Defn):
        return value.body, tuple(value.params)
    if isinstance(value, tuple) and len(value) == 2:
        return value[0], tuple(value[1])
    raise TypeError("tiny definitions must be Defn or (body, params)")


def check_tiny(body, params, known_defs=None) -> list[str]:
    """Return all discovered syntax and binding errors; recursion needs no machine stack."""
    defs = known_defs or {}
    errors = []
    visiting = set()
    checked = set()

    def expr(node, bound, loops, tail):
        if isinstance(node, n.Var):
            if node.name not in bound:
                errors.append(f"unbound variable {node.name}")
        elif isinstance(node, n.Lit):
            if type(node.value) is not int or not 0 <= node.value <= 255:
                errors.append("tiny literals must be integers in 0..255")
        elif isinstance(node, n.Call):
            if node.fn == "is_zero":
                errors.append("is_zero is allowed only inside a Test condition")
            elif node.fn in loops:
                if not tail:
                    errors.append("non-tail recursion: the machine has no stack")
                if len(node.args) != loops[node.fn]:
                    errors.append(f"{node.fn} expects {loops[node.fn]} arguments")
            elif node.fn in ("add", "sub"):
                if len(node.args) != 2:
                    errors.append(f"{node.fn} expects 2 arguments")
            elif node.fn in defs:
                dep_body, dep_params = definition(defs[node.fn])
                if len(node.args) != len(dep_params):
                    errors.append(f"{node.fn} expects {len(dep_params)} arguments")
                visit(node.fn, dep_body, dep_params)
            else:
                errors.append(f"unknown tiny operation {node.fn}")
            for arg in node.args:
                expr(arg, bound, loops, False)
        elif isinstance(node, n.Let):
            expr(node.value, bound, loops, False)
            expr(node.body, bound | {node.name}, loops, tail)
        elif isinstance(node, n.Case):
            for cond, arm in node.arms:
                condition(cond, bound, loops)
                expr(arm, bound, loops, tail)
            if node.default is not None:
                expr(node.default, bound, loops, tail)
        elif isinstance(node, n.Rec):
            if node.measure != "fuel":
                errors.append("tiny Rec must use measure fuel")
            if len(set(node.params)) != len(node.params) or node.fn in loops:
                errors.append("duplicate or shadowed recursive binding")
            if len(node.args) != len(node.params):
                errors.append(f"{node.fn} expects {len(node.params)} initial arguments")
            for arg in node.args:
                expr(arg, bound, loops, False)
            expr(node.body, bound | set(node.params), {**loops, node.fn: len(node.params)}, True)
        else:
            errors.append(f"unsupported tiny node {type(node).__name__}")

    def condition(cond, bound, loops):
        if isinstance(cond, n.Test):
            test = cond.expr
            if not isinstance(test, n.Call) or test.fn != "is_zero" or len(test.args) != 1:
                errors.append("Test must contain is_zero with one argument")
            else:
                expr(test.args[0], bound, loops, False)
        elif isinstance(cond, (n.And, n.Or)):
            condition(cond.left, bound, loops)
            condition(cond.right, bound, loops)
        elif isinstance(cond, n.Not):
            condition(cond.operand, bound, loops)
        elif not isinstance(cond, n.Always):
            errors.append(f"unsupported tiny condition {type(cond).__name__}")

    def visit(name, dep_body, dep_params):
        if name in visiting:
            errors.append(f"cyclic tiny definition {name}: the machine has no stack")
        elif name not in checked:
            visiting.add(name)
            if len(set(dep_params)) != len(dep_params):
                errors.append(f"duplicate parameters in {name}")
            expr(dep_body, set(dep_params), {}, True)
            visiting.remove(name)
            checked.add(name)

    if len(set(params)) != len(params):
        errors.append("duplicate parameters")
    expr(body, set(params), {}, True)
    return errors
