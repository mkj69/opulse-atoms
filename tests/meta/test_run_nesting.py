"""Nested run budgets: the run whose own deadline is hit reports out (atoms-meta 2.6)."""

from opulse.atoms import nodes as n
from opulse.atoms.values import Card, Ok
from opulse.meta import code, engine
from opulse.meta import gen_code as G


def resolve(name):
    return code.Resolved(digest=G.DIGESTS[name]) if name in G.DIGESTS else None


def chain(depth):
    """add(add(...add(x, 1)...), 1): exactly `depth` layer-0 steps."""
    body = n.Var("x")
    for _ in range(depth):
        body = n.Call("add", (body, n.Lit(1)))
    return code.make_code("operation", G.SIG, ("x",), body, resolve)


def test_innermost_run_owns_a_tie_and_binding_middle_budget_reports_out():
    inner = chain(6)  # needs 6 steps
    # middle: run(inner, [x], 10) inside an outer run with budget 5: the outer budget binds (5 < 10)
    middle_body = n.Call("run", (n.Lit(inner), n.Lit(code.lst((3,))), n.Lit(10)))
    middle = code.make_code("operation", code.sig_op((), ("result", "bottom")), (), middle_body, resolve)
    outer = engine.call("run", (middle, code.lst(), 5), G.scope())
    assert outer.outcome == Ok(Card("result", "out", (5,))) and outer.steps == 5
    # same, but the middle budget 4 binds inside an outer budget 100: the middle run is out(4), the outer ok
    middle_body = n.Call("run", (n.Lit(inner), n.Lit(code.lst((3,))), n.Lit(4)))
    middle = code.make_code("operation", code.sig_op((), ("result", "bottom")), (), middle_body, resolve)
    outer = engine.call("run", (middle, code.lst(), 100), G.scope())
    assert outer.outcome == Ok(Card("result", "ok", (Card("result", "out", (4,)),))) and outer.steps == 4
    # tie: both budgets are 4: the inner run owns the exhaustion, so the outer run still returns ok
    outer = engine.call("run", (middle, code.lst(), 4), G.scope())
    assert outer.outcome == Ok(Card("result", "ok", (Card("result", "out", (4,)),))) and outer.steps == 4
