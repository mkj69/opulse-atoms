"""Substitutable combinators (spec sections 6.2 and 13.2). Lists use host tuples."""

from __future__ import annotations

from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import VerifyResult
from opulse.atoms.spec import CombinatorSpec
from opulse.atoms.values import Bottom, Ok, Unknown, outcome_equal, value_equal


def list_atoms() -> list[kernel.Atom]:
    """Host-tuple list primitives; operations, hence counted layer-0 steps."""
    return [kernel.Atom("is_empty", 1, lambda items: not items),
            kernel.Atom("head", 1, lambda items: items[0]),
            kernel.Atom("tail", 1, lambda items: items[1:]),
            kernel.Atom("list_length", 1, len),
            kernel.Atom("cons", 2, lambda head, tail: (head, *tail))]


def counter_atoms() -> list[kernel.Atom]:
    return [kernel.Atom("comb_inc", 1, lambda value: value + 1),
            kernel.Atom("comb_dec", 1, lambda value: value - 1),
            kernel.Atom("comb_sub", 2, lambda left, right: left - right),
            kernel.Atom("comb_positive", 1, lambda value: value > 0),
            kernel.Atom("comb_equal", 2, lambda left, right: left == right),
            kernel.Atom("comb_le", 2, lambda left, right: left <= right)]


def fix_atoms() -> list[kernel.Atom]:
    return [kernel.Atom("fix_equal", 2, value_equal)]


def fix_spec() -> CombinatorSpec:
    """The caller supplies a finite lattice height; zero iterations cannot certify stability."""
    body = n.Case(((n.Test(n.Call("comb_positive", (n.Var("remaining"),))),
                    n.Let("next_state", n.Call("step", (n.Var("state"),)),
                          n.Case(((n.Test(n.Call("fix_equal", (n.Var("state"),
                                                               n.Var("next_state")))),
                                   n.Var("next_state")),),
                                 n.Call("fix_local", (n.Var("next_state"),
                                                      n.Call("comb_dec", (n.Var("remaining"),))))))),),
                  n.Lit(Bottom("not_stable")))
    return CombinatorSpec("fix", ("step", "x", "height"), ("step",),
                          n.Rec("fix_local", ("state", "remaining"), body,
                                (n.Var("x"), n.Var("height")), n.Var("remaining")))


def memoized_spec(spec: CombinatorSpec, name: str | None = None) -> CombinatorSpec:
    """Produce a memo-enabled recursion scheme without changing its unfold/cost."""
    def transform(node):
        if isinstance(node, n.Rec):
            return n.Rec(node.fn, node.params, node.body, node.args, node.measure, memo=True)
        return node

    if not any(isinstance(item, n.Rec) for item in n.walk(spec.body)):
        raise ValueError("memoized combinator needs recursion")
    return CombinatorSpec(name or f"{spec.name}_memo", spec.params, spec.op_params,
                          n.map_nodes(spec.body, transform))


def turns_atoms() -> list[kernel.Atom]:
    """Schedule construction is a layer-0 operation; agent calls remain kernel calls."""
    def schedule(value, agents):
        if type(value) is int and value >= 0:
            return tuple(index % agents for index in range(value))
        if isinstance(value, tuple) and all(type(index) is int and 0 <= index < agents
                                             for index in value):
            return value
        return Bottom("invalid_schedule")

    def orders(value, agents):
        if not (isinstance(value, tuple) and len(value) == 2 and value[0] == "all"
                and type(value[1]) is int and value[1] >= 0):
            return Bottom("invalid_schedule")
        return tuple(order for length in range(value[1] + 1)
                     for order in product(range(agents), repeat=length))

    def unique(states):
        result = []
        for state in states:
            if not any(value_equal(state, previous) for previous in result):
                result.append(state)
        return tuple(result)

    return [kernel.Atom("turns_is_all", 1, lambda value: isinstance(value, tuple)
                        and len(value) == 2 and value[0] == "all"),
            kernel.Atom("turns_schedule", 2, schedule),
            kernel.Atom("turns_orders", 2, orders),
            kernel.Atom("turns_unique", 1, unique)]


def turns_spec(agents: int) -> CombinatorSpec:
    """Agents choose from private observations; shared apply owns the world state.

    ``apply(move, agent_index, state)`` is the only transition and runs at layer 0.
    """
    if type(agents) is not int or agents < 1:
        raise ValueError("turns needs at least one agent")
    operations = (*tuple(name for index in range(agents)
                         for name in (f"observe{index}", f"choose{index}")), "apply")
    branch = n.Lit(Bottom("invalid_schedule"))
    for index in reversed(range(agents)):
        branch = n.Case(((n.Test(n.Call("comb_equal", (n.Call("head", (n.Var("queue"),)),
                                                       n.Lit(index)))),
                          n.Call("turns_local", (n.Call("apply", (
                              n.Call(f"choose{index}", (
                                  n.Call(f"observe{index}", (n.Var("state"),)),)),
                              n.Lit(index), n.Var("state"))),
                                                 n.Call("tail", (n.Var("queue"),))))),), branch)
    play = n.Rec("turns_local", ("state", "queue"),
                 n.Case(((n.Test(n.Call("is_empty", (n.Var("queue"),))), n.Var("state")),), branch),
                 (n.Var("state"), n.Var("order")), n.Call("list_length", (n.Var("queue"),)))
    all_orders = n.Rec("turns_all", ("orders",),
                       n.Case(((n.Test(n.Call("is_empty", (n.Var("orders"),))), n.Lit(())),),
                              n.Let("order", n.Call("head", (n.Var("orders"),)),
                                    n.Call("cons", (play, n.Call("turns_all", (
                                        n.Call("tail", (n.Var("orders"),)),)))))),
                       (n.Call("turns_orders", (n.Var("schedule"), n.Lit(agents))),),
                       n.Call("list_length", (n.Var("orders"),)))
    body = n.Case(((n.Test(n.Call("turns_is_all", (n.Var("schedule"),))),
                    n.Call("turns_unique", (all_orders,))),),
                  n.Let("order", n.Call("turns_schedule", (n.Var("schedule"), n.Lit(agents))), play))
    return CombinatorSpec("turns", (*operations, "state", "schedule"), operations, body)


def repeat_spec(count: int) -> CombinatorSpec:
    if type(count) is not int or count < 0:
        raise ValueError("repeat count must be a non-negative static integer")
    body = n.Var("x")
    for _ in range(count):
        body = n.Call("f", (body,))
    return CombinatorSpec("repeat", ("f", "x"), ("f",), body)


def twice_via_repeat_spec() -> CombinatorSpec:
    """Forward an operation parameter to a second combinator."""
    return CombinatorSpec("twice_via_repeat", ("f", "x"), ("f",),
                          n.Call("repeat", (n.Var("f"), n.Var("x"))))


def repeat_until_spec(max_rounds: int, *, dialect: str = "atoms-v2",
                      on_exhaust: str = "bottom") -> CombinatorSpec:
    if type(max_rounds) is not int or max_rounds < 0:
        raise ValueError("max must be a non-negative static integer")
    if dialect not in ("atoms-v2", "legacy-v1") or on_exhaust != "bottom":
        raise ValueError("unsupported repeat_until dialect or exhaustion policy")
    body = n.Var("state") if dialect == "legacy-v1" else n.Lit(Bottom("exhausted"))
    for _ in range(max_rounds):
        body = n.Case(((n.Test(n.Call("stop", (n.Var("state"),))), n.Var("state")),),
                      n.Let("state", n.Call("body", (n.Var("state"),)), body))
    return CombinatorSpec("repeat_until", ("body", "stop", "state"), ("body", "stop"), body)


def standard_combinators() -> tuple[CombinatorSpec, ...]:
    fold_body = n.Case(((n.Test(n.Call("is_empty", (n.Var("items"),))), n.Var("zero")),),
                       n.Call("f", (n.Call("head", (n.Var("items"),)),
                                    n.Call("fold_local", (n.Call("tail", (n.Var("items"),)),)))))
    map_body = n.Case(((n.Test(n.Call("is_empty", (n.Var("items"),))), n.Lit(())),),
                      n.Call("cons", (n.Call("f", (n.Call("head", (n.Var("items"),)),)),
                                      n.Call("map_local", (n.Call("tail", (n.Var("items"),)),)))))
    search_body = n.Case(((n.Test(n.Call("comb_le", (n.Var("index"), n.Var("bound")))),
                           n.Case(((n.Test(n.Call("p", (n.Var("index"),))), n.Var("index")),
                                   (n.Test(n.Call("comb_equal", (n.Var("index"), n.Var("bound")))),
                                    n.Lit(Bottom("not_found")))),
                                  n.Call("search_local", (n.Call("comb_inc", (n.Var("index"),)),)))),),
                         n.Lit(Bottom("not_found")))
    return (
        CombinatorSpec("seq", ("f", "g", "x"), ("f", "g"), n.Call("g", (n.Call("f", (n.Var("x"),)),))),
        CombinatorSpec("twice", ("f", "x"), ("f",), n.Call("f", (n.Call("f", (n.Var("x"),)),))),
        repeat_spec(2),
        twice_via_repeat_spec(),
        CombinatorSpec("fold", ("f", "zero", "items"), ("f",),
                       n.Rec("fold_local", ("items",), fold_body, (n.Var("items"),),
                             n.Call("list_length", (n.Var("items"),)))),
        CombinatorSpec("map", ("f", "items"), ("f",),
                       n.Rec("map_local", ("items",), map_body, (n.Var("items"),),
                             n.Call("list_length", (n.Var("items"),)))),
        fix_spec(),
        memoized_spec(CombinatorSpec("fold", ("f", "zero", "items"), ("f",),
                       n.Rec("fold_local", ("items",), fold_body, (n.Var("items"),),
                             n.Call("list_length", (n.Var("items"),))))),
        repeat_until_spec(3),
        CombinatorSpec("search", ("p", "bound"), ("p",),
                       n.Rec("search_local", ("index",), search_body, (n.Lit(0),),
                             n.Call("comb_sub", (n.Var("bound"), n.Var("index"))))),
    )


def combinator_defn(spec: CombinatorSpec) -> kernel.Defn:
    return kernel.Defn(spec.name, spec.params, spec.body, kind="combinator")


def instantiate(spec: CombinatorSpec, op_args: dict[str, str], value_args) -> n.Node:
    """Call the combinator with FnRefs, then unfold through the kernel."""
    if set(op_args) != set(spec.op_params):
        raise ValueError("operation arguments must match op_params")
    value_params = [param for param in spec.params if param not in spec.op_params]
    if isinstance(value_args, dict):
        values = value_args
    else:
        if len(value_args) != len(value_params):
            raise ValueError("wrong number of value arguments")
        values = dict(zip(value_params, value_args))
    args = tuple(n.Lit(kernel.FnRef(op_args[param])) if param in op_args else
                 values[param] if isinstance(values[param], n.NODE_TYPES) else n.Lit(values[param])
                 for param in spec.params)
    return kernel.inline(n.Call(spec.name, args), kernel.DictScope(defns=[combinator_defn(spec)]))


def check_combinator(defn, lib) -> list[str]:
    problems = []
    spec = defn.spec
    if defn.body != spec.body:
        problems.append("combinator body differs from its declared unfold body")
    if spec.unfold_rule != "substitute":
        problems.append("unfold rule must be substitute")
    if not set(spec.op_params) <= set(spec.params):
        problems.append("op_params must be declared parameters")
    if len(set(spec.params)) != len(spec.params):
        problems.append("combinator parameters must be distinct")
    if defn.name == "turns":
        for item in n.walk(defn.body):
            if not isinstance(item, n.Call) or not item.fn.startswith("choose") or not item.fn[6:].isdigit():
                continue
            observed = n.Call(f"observe{item.fn[6:]}", (n.Var("state"),))
            if item.args != (observed,):
                problems.append(f"{item.fn} must receive only its own observation")
    arities = {}
    definitions = getattr(lib, "records", lambda: getattr(lib, "definitions", {}))()
    standard = {item.name: item for item in standard_combinators()}

    def signature(name):
        target = definitions.get(name)
        if target is not None and isinstance(target.spec, CombinatorSpec):
            return target.spec
        return standard.get(name)

    allowed = set()
    fixed_ops = set()
    template_name = spec.extra.get("template", {}).get("name")
    for item in n.walk(defn.body):
        if not isinstance(item, n.Call):
            continue
        target = signature(item.fn)
        for param, arg in zip(target.params, item.args) if target is not None else ():
            if param not in target.op_params:
                continue
            if isinstance(arg, n.Var) and arg.name in spec.op_params:
                allowed.add(id(arg))
                continue
            if isinstance(arg, n.Lit) and isinstance(arg.value, kernel.FnRef):
                allowed.add(id(arg))
                fixed_ops.add(arg.value.name)
                continue
            problems.append(f"{item.fn}.{param} needs an operation reference")
    for item in n.walk(defn.body):
        if isinstance(item, n.Var) and item.name in spec.op_params and id(item) not in allowed:
            problems.append(f"operation parameter {item.name} cannot be stored as data")
        if (isinstance(item, n.Lit) and isinstance(item.value, kernel.FnRef)
                and id(item) not in allowed and item.value.name != template_name):
            problems.append("operation references cannot be stored as data")
        if isinstance(item, n.Call) and item.fn in spec.op_params:
            expected = arities.setdefault(item.fn, len(item.args))
            if len(item.args) != expected:
                problems.append(f"operation parameter {item.fn} needs arity {expected}")
    for name in fixed_ops - set(defn.depends_on):
        problems.append(f"fixed operation {name} missing from depends_on")
    return list(dict.fromkeys(problems))


def verify_combinator(defn, lib, request):
    problems = check_combinator(defn, lib)
    fixed_ops = tuple(sorted({item.value.name for item in n.walk(defn.body)
                              if isinstance(item, n.Lit) and isinstance(item.value, kernel.FnRef)}))
    scope_record = dict(request.scope)
    if fixed_ops:
        scope_record["fixed_ops"] = list(fixed_ops)
    if defn.name == "fix" and not scope_record.get("finite_height"):
        problems.append("fix scope must declare a finite lattice height")
    if request.method not in ("bounded", "sampled"):
        problems.append("combinator evidence cannot be exhaustive over all operations")
    family = request.extra.get("op_family", ())
    declared = scope_record.get("op_family", ())
    if (not family or isinstance(family, dict) != isinstance(declared, dict)
            or isinstance(family, dict) and (set(family) != set(defn.spec.op_params)
                                                or any(not names or not set(names) <= set(declared.get(param, ()))
                                                       for param, names in family.items()))
            or not isinstance(family, dict) and not set(family) <= set(declared)):
        problems.append("scope must list the operation family")
    if not request.domain:
        problems.append("combinator evidence needs input tuples")
    steps = []
    checks = []
    if not problems:
        scope = lib.scope().extend([kernel.Defn(defn.name, defn.spec.params, defn.body,
                                                kind="combinator")])
        choices = (tuple(family[param] for param in defn.spec.op_params) if isinstance(family, dict)
                   else (family,) * len(defn.spec.op_params))
        for names in product(*choices):
            assignment = dict(zip(defn.spec.op_params, names))
            for op_param, name in assignment.items():
                target = scope.resolve(name)
                def arities_for(body, parameter, visited=frozenset()):
                    arities = {len(item.args) for item in n.walk(body)
                               if isinstance(item, n.Call) and item.fn == parameter}
                    for item in n.walk(body):
                        if not isinstance(item, n.Call) or item.fn in visited:
                            continue
                        dependency = lib.records().get(item.fn) if hasattr(lib, "records") else None
                        forwarded = dependency.spec if dependency is not None else next(
                            (spec for spec in standard_combinators() if spec.name == item.fn), None)
                        if isinstance(forwarded, CombinatorSpec):
                            for index, arg in enumerate(item.args):
                                if isinstance(arg, n.Var) and arg.name == parameter:
                                    arities |= arities_for(forwarded.body, forwarded.params[index],
                                                           visited | {item.fn})
                    return arities

                arities = arities_for(defn.body, op_param)
                if target is None or any((target.arity if isinstance(target, kernel.Atom)
                                          else len(target.params)) != arity for arity in arities):
                    problems.append(f"operation {name} has wrong arity for {op_param}")
            if problems:
                break
            for inputs in request.domain:
                args = tuple(kernel.FnRef(assignment[param]) if param in assignment else
                             inputs[[value for value in defn.spec.params if value not in assignment].index(param)]
                             for param in defn.spec.params)
                actual = kernel.call(defn.name, args, scope, dialect=lib.dialect)
                unfolded = kernel.evaluate(instantiate(defn.spec, assignment, inputs), scope=scope,
                                           dialect=lib.dialect)
                steps.append(actual.steps)
                if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps:
                    problems.append(f"unfold_equivalence mismatch: {names!r}, {inputs!r}")
                if request.reference is not None:
                    expected = (request.reference(assignment, inputs) if callable(request.reference)
                                else lib.run(request.reference, (assignment, inputs)).outcome)
                    if not outcome_equal(actual.outcome, expected if isinstance(expected, (Ok, Bottom, Unknown))
                                         else Ok(expected)):
                        problems.append(f"reference mismatch: {names!r}, {inputs!r}")
                if problems:
                    break
            if problems:
                break
        if not any(item.startswith("unfold_equivalence") for item in problems):
            checks.append("unfold_equivalence")
        if request.reference is not None and not any(item.startswith("reference") for item in problems):
            checks.append("reference")
    return VerifyResult(not problems, tuple(checks), problems, steps)
