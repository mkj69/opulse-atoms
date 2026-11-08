"""The locked finite channel and its capability-scoped atoms."""

import json
from pathlib import Path

from opulse.atoms import nodes as n
from opulse.atoms.kernel import Atom
from opulse.atoms.world import WorldDecl

from . import hosts


def bind_body():
    def call(name, *args):
        return n.Call(name, args)

    def test(node):
        return n.Test(node)

    def choose(condition, yes, no):
        return n.Case(((test(condition), yes),), no)

    def var(name):
        return n.Var(name)

    weighted = call("branch", call("branch_value", var("item")),
                    call("mul", var("weight"), call("branch_weight", var("item"))))
    existing = call("head", var("acc"))
    merged = call("branch", call("branch_value", existing),
                  call("add", call("branch_weight", existing), call("branch_weight", var("entry"))))
    merge = n.Rec("merge", ("acc", "entry"), choose(call("empty", var("acc")),
                   call("prepend", var("entry"), var("acc")),
                   choose(call("eq", call("branch_value", existing), call("branch_value", var("entry"))),
                          call("prepend", merged, call("tail", var("acc"))),
                          call("prepend", existing, call("merge", call("tail", var("acc")), var("entry"))))),
                  (var("output"), weighted), call("size", var("acc")))
    inner = n.Rec("fold_mapped", ("items", "output"),
                  choose(call("empty", var("items")), var("output"),
                         n.Let("item", call("head", var("items")),
                               call("fold_mapped", call("tail", var("items")), merge))),
                  (call("dist_items", call("f", call("branch_value", call("head", var("entries"))))),
                   var("output")), call("size", var("items")))
    outer = choose(call("empty", var("entries")), call("dist_make", var("output")),
                   n.Let("weight", call("branch_weight", call("head", var("entries"))),
                         call("fold", call("tail", var("entries")), inner)))
    return n.Rec("fold", ("entries", "output"), outer,
                 (call("dist_items", var("distribution")), n.Lit(hosts.Card("Branches", "list"))),
                 call("size", var("entries")))


def decl():
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/hidden@1.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atoms():
    world = decl()
    return [Atom(op.name, len(op.inputs), getattr(hosts, op.impl["host"].split(":")[1]), op.cost)
            for op in world.operations]


def new_library():
    from .adapter import HiddenLibrary

    return HiddenLibrary(decl(), atoms())
