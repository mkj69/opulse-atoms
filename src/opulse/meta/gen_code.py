"""Seeded canonical programs for meta invariant checks (atoms-meta section 8)."""

from __future__ import annotations

import random

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Edge, OperationSpec
from opulse.atoms.values import boolean
from opulse.meta import arith, code, engine
from opulse.meta.export_util import host_rule


def is_zero(value):
    return boolean(arith.is_zero(value))


def lt(left, right):
    return boolean(arith.lt(left, right))


_FUNCTIONS = {"add": (2, arith.add), "sub": (2, arith.sub), "mul": (2, arith.mul),
              "div": (2, arith.div), "is_zero": (1, is_zero), "lt": (2, lt)}
SPECS = tuple(OperationSpec(
    name, "decide" if name in ("is_zero", "lt") else "combine",
    tuple(Edge("int") for _ in range(arity)),
    Edge("bool" if name in ("is_zero", "lt") else "int"),
    f"Integer {name}.", ("div_zero",) if name == "div" else (),
    host_rule(function))
    for name, (arity, function) in _FUNCTIONS.items())
SPECS += tuple(OperationSpec(name, "transform", (Edge("code"), Edge("list")) +
                             ((Edge("int"),) if name == "run" else ()),
                             Edge("result" if name == "run" else "int"),
                             f"Metered {name}.", cost=0)
               for name in ("eval", "run"))
DIGESTS = {spec.name: code.atom_digest(spec) for spec in SPECS}
ATOMS = tuple(kernel.Atom(name, arity, function)
              for name, (arity, function) in _FUNCTIONS.items())
SIG = code.sig_op((("int", "bottom"),), ("int", "bottom"))
RESULT_SIG = code.sig_op((("int", "bottom"),), ("result", "bottom"))


def scope() -> kernel.DictScope:
    """Small integer world with the two metered code operations."""
    return kernel.DictScope((*ATOMS, engine.eval_atom(ATOMS, DIGESTS),
                             engine.run_atom(ATOMS, DIGESTS)))


def _resolve(dependencies=()):
    by_name = {name: value for name, value in dependencies}
    return lambda name: (code.Resolved(code=by_name[name]) if name in by_name else
                         code.Resolved(digest=DIGESTS[name]) if name in DIGESTS else None)


def random_code(rng: random.Random, depth: int):
    """Build a canonical operation, including hashed dependencies (spec 2.2)."""
    if depth < 0:
        raise ValueError("depth must be nonnegative")
    number = rng.randrange(-3, 4)
    dependency = code.make_code("operation", SIG, ("item",),
                                n.Call(rng.choice(("add", "sub", "mul")),
                                       (n.Var("item"), n.Lit(number))), _resolve())
    nested = code.make_code("operation", SIG, ("item",),
                            n.Call("add", (n.Var("item"), n.Lit(number))), _resolve())
    dependence = "#" + code.code_hash(dependency)

    def expression(level, top=False):
        value = n.Var("x")
        if level == 0:
            return rng.choice((n.Call(dependence, (value,)),
                               n.Call("div", (value, n.Lit(rng.randrange(3)))),
                               n.Call("eval", (n.Lit(nested), n.Lit(code.lst((number,)))))))
        choice = rng.randrange(6 if top else 5)
        if choice == 0:
            return n.Let("temporary", expression(level - 1),
                         n.Call("add", (n.Var("temporary"), n.Lit(number))))
        if choice == 1:
            conditions = (n.Test(n.Call("is_zero", (value,))),
                          n.And(n.Test(n.Call("lt", (value, n.Lit(2)))),
                                n.Not(n.Test(n.Call("is_zero", (value,))))),
                          n.Or(n.Test(n.Call("is_zero", (value,))),
                               n.Test(n.Call("lt", (value, n.Lit(2))))))
            return n.Case(((rng.choice(conditions), expression(level - 1)),),
                          n.Call(dependence, (value,)))
        if choice == 2:
            return n.Rec("loop", ("counter", "acc"),
                         n.Case(((n.Test(n.Call("is_zero", (n.Var("counter"),))),
                                  n.Var("acc")),),
                                n.Call("loop", (n.Call("sub", (n.Var("counter"), n.Lit(1))),
                                                n.Call("add", (n.Var("acc"), n.Lit(1)))))),
                         (value, n.Lit(number)), "fuel")
        if choice == 5:
            return n.Call("run", (n.Lit(nested), n.Lit(code.lst((number,))),
                                  n.Lit(rng.randrange(3, 7))))
        if choice == 3:
            return n.Call("eval", (n.Lit(nested), n.Lit(code.lst((number,)))))
        return n.Call(dependence, (expression(level - 1),))

    answer = expression(min(depth, 3), True)
    body = n.Let("marker", n.Lit(number),
                 n.Let("source", n.Call(dependence, (n.Var("x"),)),
                       n.Let("answer", answer, n.Var("answer"))))
    signature = RESULT_SIG if isinstance(answer, n.Call) and answer.fn == "run" else SIG
    return code.make_code("operation", signature, ("x",), body,
                          _resolve(((dependence, dependency),)))


def random_args(rng: random.Random, program):
    """Small nonnegative values bound fuel-recursive loops (spec 2.5)."""
    return tuple(rng.randrange(5) for _ in range(code.sig_arity(program.fields[1])))
