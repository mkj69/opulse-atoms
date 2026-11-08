"""Generic layer-zero combinators used for finite warehouse control."""

from opulse.atoms import nodes as n
from opulse.atoms.spec import CombinatorSpec


def given_combinators():
    state = n.Var("state")
    count = n.Var("count")
    seq = CombinatorSpec("seq", ("first", "second", "state"), ("first", "second"),
                         n.Call("second", (n.Call("first", (state,)),)))
    repeat = CombinatorSpec("repeat", ("step", "count", "state"), ("step",),
                            n.Rec("repeat_loop", ("remaining", "value"),
                                  n.Case(((n.Test(n.Call("budget_empty", (n.Var("remaining"),))),
                                           n.Var("value")),),
                                         n.Call("repeat_loop", (n.Call("decrement", (n.Var("remaining"),)),
                                                                n.Call("step", (n.Var("value"),))))),
                                  (count, state), n.Var("remaining")))
    start, target, known = n.Var("start"), n.Var("target"), n.Var("known")
    frontier, parents = n.Var("frontier"), n.Var("parents")
    expanded = n.Call("graph_expand", (frontier, parents, known))
    advance = n.Let("expanded", expanded,
                    n.Case(((n.Test(n.Call("empty", (n.Call("graph_frontier", (n.Var("expanded"),)),))),
                             n.Call("graph_path", (n.Call("graph_parents", (n.Var("expanded"),)),
                                                   start, target))),),
                           n.Call("search_loop", (n.Call("graph_frontier", (n.Var("expanded"),)),
                                                  n.Call("graph_parents", (n.Var("expanded"),))))))
    search_loop = n.Case(((n.Test(n.Call("map_has", (parents, target))),
                           n.Call("graph_path", (parents, start, target))),
                          (n.Test(n.Call("empty", (frontier,))), n.Call("none"))), advance)
    known_endpoints = n.And(n.Test(n.Call("map_get", (known, start))),
                            n.Test(n.Call("map_get", (known, target))))
    body = n.Case(((known_endpoints,
                    n.Rec("search_loop", ("frontier", "parents"), search_loop,
                          (n.Call("prepend", (start, n.Lit(()))), n.Call("singleton", (start,))),
                          n.Call("sub", (n.Lit(4097), n.Call("size", (parents,)))))),), n.Call("none"))
    search = CombinatorSpec("search", ("neighbors", "valid", "start", "target", "known"),
                            ("neighbors", "valid"), body)
    return seq, repeat, search
