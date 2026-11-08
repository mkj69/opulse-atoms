"""Reference definitions (docs/spec/atoms-v2.md, sections 4, 6, 7 and 9)."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from itertools import product

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import (
    CombinatorSpec,
    Contract,
    Cost,
    Definition,
    Edge,
    Evidence,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
)
from opulse.atoms.values import Unknown, boolean, encode, outcome_equal
from opulse.tasks_v2 import kernel_engine as engine


def _call(name, *args):
    return n.Call(name, args)


def _var(name):
    return n.Var(name)


def _rec(name, body, *params, measure=None):
    return n.Rec(name, params, body, tuple(_var(param) for param in params),
                 measure if measure is not None else _call("size", _var(params[0])))


def _record(name, kind, spec, body, params, world, method, size, checks, verification_scope=None, layer=1):
    depends = tuple(sorted(n.references(body) - (set(spec.op_params) if kind == "combinator" else set())))
    evidence = Evidence(method, {"domain": world, "size": size, **(verification_scope or {})}, checks=tuple(checks),
                        world_hash=engine.world(world).lock["world_hash"])
    result = Definition(name, kind, "invented", layer, depends, spec, body, evidence,
                        Contract(f"{name} matches its unfold rule"), Cost(n.length(body)), "promoted",
                        f"{world}/{name}")
    if result.validate():
        raise ValueError(result.validate())
    return result, kernel.Defn(name, params, body, kind, layer)


@lru_cache(maxsize=1)
def records():
    fraction_spec = ObjectSpec("fraction", "refine", base="pair[int,int]",
                               valid=_call("fraction_valid", _var("x")),
                               canon=_call("fraction_canon", _var("x")), sealed=True,
                               interface=("make_fraction", "num", "den", "fraction_eq", "frac_add", "frac_mul"))
    entries = []
    entries.append(_record("fraction", "object", fraction_spec, _call("fraction_canon", _var("x")),
                           ("x",), "integer@1", "exhaustive", 600,
                           ("canon_total", "idempotent", "validity", "interface_respect", "unfold_equivalence"),
                           {"numerators": [-12, 12], "denominators": [-12, 12],
                            "exclude_zero_denominator": True, "interface_pairs": 360000}))
    for name, body, equality in (
        ("fraction_raw", _call("fraction_raw_base", _var("x")), "raw_fraction_eq"),
        ("fraction_positive", _call("fraction_positive_base", _var("x")), "positive_fraction_eq"),
    ):
        spec = ObjectSpec(name, "refine", base="pair[int,int]", valid=_call("fraction_valid", _var("x")),
                          canon=body, sealed=True, interface=(equality,))
        entries.append(_record(name, "object", spec, body, ("x",), "integer@1", "exhaustive", 600,
                               ("canon_total", "idempotent", "validity", "interface_respect", "unfold_equivalence"),
                               {"numerators": [-12, 12], "denominators": [-12, 12],
                                "exclude_zero_denominator": True}))
    ilist_spec = ObjectSpec("ilist", "compose", tags={"nil": [], "cons": [["head", "int"], ["tail", "ilist"]]},
                            group=("ilist",), sealed=True, interface=("nil", "cons", "ilen", "isum", "iappend"))
    entries.append(_record("ilist", "object", ilist_spec, _call("cons", _var("head"), _var("tail")),
                           ("head", "tail"), "integer@1", "bounded", 4, ("base_tag", "interface", "unfold_equivalence")))
    three_body = _call("natural_succ", _call("natural_succ", _call("natural_succ", n.Lit(0))))
    three_spec = ObjectSpec("three", "constant", body=three_body)
    entries.append(_record("three", "object", three_spec, three_body, (), "successor@1", "exhaustive", 1, ("unfold_equivalence",)))
    ilen = _rec("loop", n.Case(((n.Test(_call("is_nil", _var("xs"))), n.Lit(0)),),
                                 _call("add", n.Lit(1), _call("loop", _call("tail", _var("xs"))))), "xs")
    isum = _rec("loop", n.Case(((n.Test(_call("is_nil", _var("xs"))), n.Lit(0)),),
                                 _call("add", _call("head", _var("xs")), _call("loop", _call("tail", _var("xs"))))), "xs")
    iappend = _rec("loop", n.Case(((n.Test(_call("is_nil", _var("xs"))), _var("ys")),),
                                    _call("cons", _call("head", _var("xs")), _call("loop", _call("tail", _var("xs")), _var("ys")))), "xs", "ys")
    unary_family = ("neg", "reverse", "triangle", "popcount", "digitsum")
    compositions = tuple(kernel.Defn(f"compose_{first}_{second}", ("x",),
                                     _call(second, _call(first, _var("x"))))
                         for first, second in product(unary_family, repeat=2))
    operations = (
        kernel.Defn("neg_neg", ("x",), _call("neg", _call("neg", _var("x")))),
        kernel.Defn("neg_triangle", ("x",), _call("neg", _call("triangle", _var("x")))),
        kernel.Defn("MUL", ("a", "b"), n.Rec("loop", ("count", "acc"),
                    n.Case(((n.Test(_call("zero_test", _var("count"))), _var("acc")),),
                           _call("loop", _call("sub", _var("count"), n.Lit(1)),
                                 _call("add", _var("acc"), _var("a")))),
                    (_var("b"), n.Lit(0)), _var("count"))),
    )
    for name, body, params, sorts, method, size, layer in (
        ("ilen", ilen, ("xs",), ("ilist",), "bounded", 4, 2),
        ("isum", isum, ("xs",), ("ilist",), "bounded", 4, 2),
        ("iappend", iappend, ("xs", "ys"), ("ilist", "ilist"), "bounded", 4, 2),
        ("frac_add", _call("frac_add_base", _var("left"), _var("right")),
         ("left", "right"), ("fraction", "fraction"), "bounded", 9, 2),
        ("frac_mul", _call("frac_mul_base", _var("left"), _var("right")),
         ("left", "right"), ("fraction", "fraction"), "bounded", 9, 2),
    ):
        output = "int" if name in ("ilen", "isum") else sorts[0]
        spec = OperationSpec(name, "combine" if len(params) == 2 else "transform",
                             tuple(Edge(sort) for sort in sorts), Edge(output),
                             f"{name} evaluates its measured unfold rule.",
                             errors=("invalid",) if name.startswith("frac_") else ("invalid", "measure"),
                             impl={"body": body})
        if name.startswith("frac_"):
            examples = (engine.fraction(1, 2), engine.fraction(2, 4), engine.fraction(0, -3))
            arguments = product(examples, repeat=2)
        else:
            items = ((), (3,), (-1, 2), (1, 2, 3))
            arguments = ((engine.ilist(values), engine.ilist((4,))) if name == "iappend"
                         else (engine.ilist(values),) for values in items)
        verification_scope = {"args": [[encode(value) for value in args] for args in arguments]}
        entries.append(_record(name, "operation", spec, body, params, "integer@1", method, size,
                               ("reference_agreement", "unfold_equivalence"), verification_scope, layer=layer))
    front_body = n.Case(((n.Test(_call("front_wall", _var("state"))), n.Lit(boolean(False))),
                         (n.Test(_call("front_water", _var("state"))), n.Lit(boolean(False)))), n.Lit(boolean(True)))
    entries.append(_record("front_free", "observation", ObservationSpec("front_free", ("front_wall", "front_water"), front_body),
                           front_body, ("state",), "action@1", "bounded", 12,
                           ("dependencies", "probe_equivalence", "unfold_equivalence"),
                           {"states_seed": 4, "states_index": 0}))
    wall_body = n.Case(((n.Test(_call("front_wall", _var("state"))), n.Lit(boolean(True))),),
                       n.Lit(boolean(False)))
    entries.append(_record("front_wall_only", "observation",
                           ObservationSpec("front_wall_only", ("front_wall",), wall_body),
                           wall_body, ("state",), "action@1", "bounded", 12,
                           ("dependencies", "probe_equivalence", "unfold_equivalence"),
                           {"states_seed": 4, "states_index": 0}))
    water_body = n.Case(((n.Test(_call("front_water", _var("state"))), n.Lit(boolean(True))),),
                        n.Lit(boolean(False)))
    entries.append(_record("front_water_only", "observation",
                           ObservationSpec("front_water_only", ("front_water",), water_body),
                           water_body, ("state",), "action@1", "bounded", 12,
                           ("dependencies", "probe_equivalence", "unfold_equivalence"),
                           {"states_seed": 4, "states_index": 0}))
    blocked = n.Case(((n.Test(_call("front_wall", _var("state"))), _call("add", _var("memory"), n.Lit(1))),
                      (n.Test(_call("front_water", _var("state"))), _call("add", _var("memory"), n.Lit(1)))), n.Lit(0))
    entries.append(_record("blocked_count", "observation", ObservationSpec("blocked_count", ("front_wall", "front_water"),
                                                                           blocked, {"sort": "int", "init": n.Lit(0), "step": blocked}),
                           blocked, ("state", "memory"), "action@1", "bounded", 36,
                           ("dependencies", "memory", "probe_equivalence", "unfold_equivalence"),
                           {"states_seed": 4, "states_index": 0, "memories": [0, 1, 3]}))
    twice = _call("f", _call("f", _var("x")))
    seq = _call("g", _call("f", _var("x")))
    repeat = _rec("iterate", n.Case(((n.Test(_call("zero_test", _var("n"))), _var("x")),),
                                    _call("iterate", _call("sub", _var("n"), n.Lit(1)), _call("f", _var("x")))),
                  "n", "x", measure=_var("n"))
    fold = _rec("reduce", n.Case(((n.Test(_call("is_nil", _var("xs"))), _var("z")),),
                                  _call("f", _call("head", _var("xs")), _call("reduce", _call("tail", _var("xs"))))), "xs")
    for name, body, params, op_params in (
        ("twice", twice, ("f", "x"), ("f",)), ("seq", seq, ("f", "g", "x"), ("f", "g")),
        ("repeat", repeat, ("f", "n", "x"), ("f",)), ("fold", fold, ("f", "z", "xs"), ("f",))):
        spec = CombinatorSpec(name, params, op_params, body)
        family = ("add", "sub", "mul", "div", "mod") if name == "fold" else unary_family + tuple(
            definition.name for definition in compositions)
        inputs = tuple(range(20)) if name != "fold" else (
            engine.ilist(()), engine.ilist((1,)), engine.ilist((2, 3)), engine.ilist((-1, 0, 4)))
        verification_scope = {"family": list(family), "inputs": [encode(value) for value in inputs],
                              "fixed": {"n": 3} if name == "repeat" else
                              {"g": "neg"} if name == "seq" else {"z": 0} if name == "fold" else {}}
        entries.append(_record(name, "combinator", spec, body, params, "integer@1", "bounded",
                               len(family) * len(inputs), ("family_scope", "unfold_equivalence"), verification_scope))
    definitions = tuple(definition for _, definition in entries) + operations + compositions
    return tuple(_account(record, definitions) for record, _ in entries), definitions


def _account(record, definitions):
    """Measure the full layer-0 cost on the same finite inputs as the evidence."""
    if record.name in ("fraction", "fraction_raw", "fraction_positive"):
        arguments = ((engine.fraction(num, den),) for num in range(-12, 13)
                     for den in range(-12, 13) if den)
    elif record.name == "ilist":
        arguments = ((head, engine.ilist(tail)) for head, tail in
                     ((0, ()), (2, (3,)), (-1, (0, 4)), (3, (2, -1, 0))))
    elif record.name == "three":
        arguments = ((),)
    elif record.kind == "operation":
        from opulse.atoms.values import decode
        arguments = (tuple(decode(value) for value in args) for args in record.evidence.scope["args"])
    elif record.kind == "observation":
        from opulse.tasks_v2.angles.observation import states
        scope = record.evidence.scope
        arguments = ((state,) if record.name != "blocked_count" else (state, memory)
                     for state in states(scope["states_seed"], scope["states_index"])
                     for memory in scope.get("memories", (0,)))
    else:
        from opulse.atoms.values import decode
        scope = record.evidence.scope
        fixed = scope["fixed"]
        arguments = ((kernel.FnRef(function),
                      *((kernel.FnRef(fixed["g"]),) if "g" in fixed else
                        (fixed["n"],) if "n" in fixed else
                        (fixed["z"],) if "z" in fixed else ()), decode(value))
                     for function in scope["family"] for value in scope["inputs"])
    steps = []
    for args in arguments:
        result = engine.run(record.id.split("/")[0], _call(record.name, *(n.Lit(arg) for arg in args)), definitions)
        if isinstance(result.outcome, Unknown):
            raise TypeError(f"unknown cost for {record.name}")
        steps.append(result.steps)
    if len(steps) != record.evidence.scope["size"]:
        raise ValueError(f"incomplete recorded scope for {record.name}")
    return replace(record, cost=Cost(record.cost.length, {"min": min(steps), "max": max(steps),
                                                     "mean": sum(steps) / len(steps), "over": "evidence scope"}))


def verify_canon(valid, canon, interface, values):
    """Exhaustive refine and interface obligations over a finite representation scope."""
    try:
        valid_values = [value for value in values if valid(value)]
        canonical = {}
        for value in valid_values:
            result = canon(value)
            if result is None or not valid(result) or canon(result) != result:
                return False
            canonical[value] = result
        for operation in interface:
            observed = {}
            for value in valid_values:
                representative = canonical[value]
                result = operation(value)
                if representative in observed and observed[representative] != result:
                    return False
                observed[representative] = result
    except (ArithmeticError, TypeError, ValueError, RecursionError):
        return False
    return True


def verify_fraction_interface(values, scope=None):
    """Check every ordered pair and every interface argument position in the recorded scope."""
    scope = scope or engine.scope("integer@1", records()[1])
    values = tuple(values)
    canonical = tuple(engine.canonical(value) for value in values)
    try:
        constructor = scope.resolve("make_fraction").fn
        if any(constructor(*value.fields) != normal for value, normal in zip(values, canonical)):
            return False
        for name in ("num", "den"):
            operation = scope.resolve(name).fn
            if any(operation(value) != operation(normal) for value, normal in zip(values, canonical)):
                return False
        for name in ("fraction_eq", "frac_add_base", "frac_mul_base"):
            operation = scope.resolve(name).fn
            for left, normal_left in zip(values, canonical):
                for right, normal_right in zip(values, canonical):
                    if operation(left, right) != operation(normal_left, normal_right):
                        return False
    except (ArithmeticError, AttributeError, TypeError, ValueError):
        return False
    return True


def verify_observation(spec, granted, operations, states, eval_node, definitions=None):
    """Enforce the transitive no-act, granted-probe and equal-probe obligations."""
    allowed = set(granted)
    if set(spec.reads) - allowed:
        return False
    definitions = definitions or {}
    references = n.references(spec.body)
    if spec.memory:
        references |= n.references(spec.memory["step"]) | n.references(spec.memory["init"])
    pure = {"add", "zero_test", "not", "and", "or"}
    if references - set(spec.reads) - set(definitions) - pure:
        return False

    def expand(name, active):
        if name not in definitions:
            return True
        if name in active:
            return False
        nested = definitions[name]
        nested_refs = n.references(nested.body) | set(nested.reads)
        if nested.memory:
            nested_refs |= n.references(nested.memory["step"]) | n.references(nested.memory["init"])
        references.update(nested_refs)
        return all(expand(dependency, active | {name}) for dependency in nested_refs)

    if not all(expand(name, set()) for name in tuple(references)):
        return False
    if references - allowed - set(definitions) - pure:
        return False
    if any(operations.get(name) == "act" for name in references):
        return False
    effective_probes = references & allowed
    initial = 0 if spec.memory is None else eval_node(spec.memory["init"])
    memories = (initial, 1, 3) if isinstance(initial, int) else (initial,)
    for left, right in product(states, repeat=2):
        if all(eval_node(_call(probe, n.Lit(left))) == eval_node(_call(probe, n.Lit(right))) for probe in effective_probes):
            for memory in memories:
                if eval_node(spec.body, {"state": left, "memory": memory}) != eval_node(
                        spec.body, {"state": right, "memory": memory}):
                    return False
                if spec.memory and eval_node(spec.memory["step"], {"state": left, "memory": memory}) != eval_node(
                        spec.memory["step"], {"state": right, "memory": memory}):
                    return False
    return True


def verify_combinator(candidate, reference, family, inputs, world="integer@1", *,
                      params=("f", "x"), fixed=(), fuel=20000):
    scope = engine.scope(world, (*records()[1], kernel.Defn("candidate", params, candidate, "combinator"),
                                 kernel.Defn("reference", params, reference, "combinator")))
    limits = kernel.Limits(fuel=fuel)
    dialect = engine.world(world).dialect
    for function in family:
        for value in inputs:
            args = (kernel.FnRef(function), *fixed, value)
            left = kernel.call("candidate", args, scope, limits, dialect=dialect)
            right = kernel.call("reference", args, scope, limits, dialect=dialect)
            if (isinstance(left.outcome, Unknown) or isinstance(right.outcome, Unknown) or
                    not outcome_equal(left.outcome, right.outcome) or left.steps != right.steps):
                return False
    return True
