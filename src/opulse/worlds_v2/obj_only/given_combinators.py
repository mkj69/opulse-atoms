"""Fixed finite-list control forms, supplied at layer zero rather than invented."""

from opulse.atoms import nodes as n
from opulse.atoms.spec import CombinatorSpec
from opulse.atoms.values import Bottom


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def choose(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def fold_spec(name="fold"):
    body = n.Rec("fold_items", ("rest", "acc"),
                 choose(call("is_empty", var("rest")), var("acc"),
                        call("fold_items", call("tail", var("rest")),
                             call("f", var("acc"), call("head", var("rest"))))),
                 (var("xs"), var("init")), call("list_length", var("rest")))
    return CombinatorSpec(name, ("f", "init", "xs"), ("f",), body)


def map_spec():
    body = n.Rec("map_items", ("rest",),
                 choose(call("is_empty", var("rest")), n.Lit(()),
                        call("cons", call("f", call("head", var("rest"))),
                             call("map_items", call("tail", var("rest"))))),
                 (var("xs"),), call("list_length", var("rest")))
    return CombinatorSpec("map", ("f", "xs"), ("f",), body)


def bounded_spec():
    loop = n.Rec("bounded_loop", ("remaining", "current"),
                 choose(call("eq", var("remaining"), n.Lit(0)), var("current"),
                        call("bounded_loop", call("sub", var("remaining"), n.Lit(1)),
                             call("f", var("current")))),
                 (var("n"), var("x")), var("remaining"))
    return CombinatorSpec("bounded", ("f", "x", "n"), ("f",),
                          choose(call("bounded_count", var("n")), loop, n.Lit(Bottom("depth_limit"))))


def branch_spec():
    return CombinatorSpec("branch", ("t", "f", "g", "x"), ("t", "f", "g"),
                          choose(call("t", var("x")), call("f", var("x")), call("g", var("x"))))


def specifications():
    return (map_spec(), fold_spec(), fold_spec("structural"), branch_spec(), bounded_spec())
