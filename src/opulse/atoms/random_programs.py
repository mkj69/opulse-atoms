"""Small seeded kernel programs for property checks (spec section 11)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms import nodes as n

MODES = ("case", "let", "rec", "blocks", "higher_order", "dependency")


@dataclass(frozen=True)
class Program:
    scope: kernel.DictScope
    name: str
    args: tuple[int, ...]
    mode: str


def seeded_program(seed: int, mode: str) -> Program:
    """Build a reproducible, bounded integer-world program from a seed and a node family."""
    if mode not in MODES:
        raise ValueError(f"unknown program mode: {mode}")
    rng = random.Random(seed)
    atoms = [kernel.Atom("add", 2, lambda left, right: left + right),
             kernel.Atom("sub", 2, lambda left, right: left - right),
             kernel.Atom("div", 2, lambda left, right: kernel.Bottom("division_by_zero")
                         if right == 0 else left // right),
             kernel.Atom("positive", 1, lambda value: value > 0)]
    argument = rng.randint(-3, 5)
    constant = rng.randint(-3, 3)
    increment = rng.randint(1, 3)
    value = n.Var("value")
    add = lambda left, right: n.Call("add", (left, right))
    decrement = lambda item: n.Call("sub", (item, n.Lit(1)))
    definition = kernel.Defn("helper", ("value",), add(value, n.Lit(increment)))
    base = n.Call("helper", (value,))
    if mode == "case":
        body = n.Case(((n.And(n.Test(n.Call("positive", (value,))),
                              n.Not(n.Test(n.Call("positive", (n.Lit(constant),))))),
                        n.Call("div", (base, n.Lit(rng.choice((0, 1, 2)))))),),
                      n.Case(((n.Or(n.Test(n.Call("positive", (value,))), n.Always()), base),),
                             n.Lit(0)))
    elif mode == "let":
        body = n.Let("tmp", base,
                     n.Let("value", n.Lit(constant), add(n.Var("tmp"), n.Var("value"))))
    elif mode == "rec":
        body = n.Rec("count", ("remaining", "total"),
                     n.Case(((n.Test(n.Call("positive", (n.Var("remaining"),))),
                              n.Call("count", (decrement(n.Var("remaining")),
                                               add(n.Var("total"), n.Lit(increment))))),),
                            n.Var("total")),
                     (n.Lit(rng.randint(0, 4)), base),
                     n.Var("remaining") if rng.choice((True, False)) else "fuel")
    elif mode == "blocks":
        body = n.Blocks((("counter", n.Lit(rng.randint(0, 4))), ("result", base)), "loop",
                        (("loop", n.Block((), n.CondJump(
                            n.Test(n.Call("positive", (n.Var("counter"),))), "step", "end"))),
                         ("step", n.Block((("result", add(n.Var("result"), n.Lit(increment))),
                                            ("counter", decrement(n.Var("counter")))), n.Jump("loop"))),
                         ("end", n.Block((), n.Halt(n.Var("result"))))))
    elif mode == "higher_order":
        definition = kernel.Defn("apply", ("function", "value"),
                                 n.Call("function", (n.Var("value"),)), "combinator")
        body = n.Call("apply", (n.Lit(kernel.FnRef("helper")), value))
    else:
        body = add(base, n.Call("helper", (n.Lit(constant),)))
    definitions = [definition, kernel.Defn("subject", ("value",), body)]
    if mode == "higher_order":
        definitions.append(kernel.Defn("helper", ("value",), add(value, n.Lit(increment))))
    scope = kernel.DictScope(atoms, definitions)
    return Program(scope, "subject", (argument,), mode)


programs = st.builds(seeded_program, st.integers(min_value=0, max_value=100_000),
                     st.sampled_from(MODES))
