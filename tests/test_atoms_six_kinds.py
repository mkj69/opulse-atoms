"""Laws, bridges and templates run the same library pipeline as the four layer-0 kinds (spec 19)."""

from dataclasses import replace

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import (
    BridgeSpec,
    Contract,
    Definition,
    Edge,
    LawSpec,
    OperationSpec,
)
from opulse.atoms.values import Bottom, Ok
from opulse.atoms.world import WorldDecl

OPS = (("add", 2, lambda a, b: a + b), ("mul", 2, lambda a, b: a * b), ("eq", 2, lambda a, b: a == b),
       ("neg", 1, lambda a: -a), ("le", 2, lambda a, b: a <= b), ("mod12", 1, lambda a: a % 12))


def library(open_kinds=("bridge", "combinator", "law", "object", "observation", "operation")):
    specs = tuple(OperationSpec(name, "combine" if arity == 2 else "transform",
                                tuple(Edge("int") for _ in range(arity)), Edge("bool" if name in ("eq", "le") else "int"),
                                name) for name, arity, _ in OPS)
    world = WorldDecl("ints", 1, "atoms-v2", {}, {}, (), specs,
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {}, open_kinds=open_kinds)
    return Library(world, [kernel.Atom(name, arity, fn) for name, arity, fn in OPS])


def law(name="mul_comm"):
    a, b = n.Var("a"), n.Var("b")
    statement = n.Call("eq", (n.Call("mul", (a, b)), n.Call("mul", (b, a))))
    return Definition(name, "law", "invented", 1, ("eq", "mul"), LawSpec(name, (("a", "int"), ("b", "int")), statement),
                      statement)


def test_law_pipeline_and_closed_kind():
    lib = library()
    lib.write(law())
    lib.check("mul_comm")
    lib.make_callable("mul_comm", [(2, 3)])
    domain = [(a, b) for a in range(-3, 4) for b in range(-3, 4)]
    lib.verify("mul_comm", VerifyRequest("exhaustive", domain, {"domain": "a, b in -3..3", "size": len(domain)}))
    assert lib.promote("mul_comm", Contract("multiplication commutes on -3..3")).status == "promoted"
    with pytest.raises(PipelineError, match="closed"):
        library(open_kinds=("operation",)).write(law())


def test_false_law_is_caught():
    lib = library()
    a, b = n.Var("a"), n.Var("b")
    statement = n.Call("le", (a, n.Call("add", (a, b))))
    lib.write(Definition("grows", "law", "invented", 1, ("add", "le"),
                         LawSpec("grows", (("a", "int"), ("b", "int")), statement), statement))
    lib.check("grows")
    lib.make_callable("grows", [(1, 1)])
    domain = [(a, b) for a in range(3) for b in range(-1, 2)]
    with pytest.raises(PipelineError):
        lib.verify("grows", VerifyRequest("exhaustive", domain, {"domain": "a in 0..2, b in -1..1", "size": 9}))


def test_partial_bridge_pipeline():
    lib = library()
    body = n.Call("mod12", (n.Var("x"),))
    domain = n.Call("le", (n.Lit(0), n.Var("x")))
    spec = BridgeSpec("to_hour", "int", "int", body, domain, (("neg", "neg"),))
    expansion = bridge_defn(spec).body  # a bridge's body is its map guarded by its domain
    lib.write(Definition("to_hour", "bridge", "invented", 1, ("le", "mod12"), spec, expansion))
    lib.check("to_hour")
    lib.make_callable("to_hour", [(14,)])
    assert lib.run("to_hour", (14,)).outcome == Ok(2)
    assert lib.run("to_hour", (-1,)).outcome == Bottom("outside_domain")


def test_template_is_open_with_the_kind_it_produces():
    from opulse.atoms.spec import TemplateSpec

    spec = TemplateSpec("Lift", (("k", "int"),), "operation", {"name": "$k"})
    template = Definition("Lift", "template", "invented", 1, (), spec, n.Lit(0))
    library().write(template)
    with pytest.raises(PipelineError, match="closed"):
        library(open_kinds=("law",)).write(replace(template))
