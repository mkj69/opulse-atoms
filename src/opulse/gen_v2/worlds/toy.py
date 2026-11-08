"""A small atoms-v2 integer world for generator tests (not a published world).

int and bool; add, sub, mul, neg, inc, dec, lt, eq, is_zero, abs, max. All four kinds open,
recursion with measures (``abs`` is the measure; ``dec`` towards zero for naturals).
"""

from __future__ import annotations

from opulse.atoms import kernel
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.world import WorldDecl
from opulse.gen_v2.base import GenWorld, Signature, Sort

DEFAULT_KINDS = ("object", "operation", "combinator", "observation")

_OPS = {
    "add": (("int", "int"), "int", lambda a, b: a + b, "a + b"),
    "sub": (("int", "int"), "int", lambda a, b: a - b, "a - b"),
    "mul": (("int", "int"), "int", lambda a, b: a * b, "a * b"),
    "neg": (("int",), "int", lambda a: -a, "-a"),
    "inc": (("int",), "int", lambda a: a + 1, "a + 1"),
    "dec": (("int",), "int", lambda a: a - 1, "a - 1"),
    "absv": (("int",), "int", abs, "|a|"),
    "maxv": (("int", "int"), "int", max, "the larger of a and b"),
    "lt": (("int", "int"), "bool", lambda a, b: a < b, "a < b"),
    "eq": (("int", "int"), "bool", lambda a, b: a == b, "a = b"),
    "is_zero": (("int",), "bool", lambda a: a == 0, "a = 0"),
    "is_pos": (("int",), "bool", lambda a: a > 0, "a > 0"),
}


def decl(open_kinds=DEFAULT_KINDS) -> WorldDecl:
    operations = tuple(
        OperationSpec(name, "decide" if out == "bool" else "combine" if len(ins) > 1 else "transform",
                      tuple(Edge(sort) for sort in ins), Edge(out), rule)
        for name, (ins, out, _, rule) in _OPS.items())
    return WorldDecl("toy", 1, "atoms-v2", {}, {},
                     (ObjectSpec("int", "given"), ObjectSpec("bool", "given")), operations,
                     {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"], "library": [],
                      "recursion": "measure"},
                     {"truth": None, "probes": [], "show": {}, "judge_view": "full_state"},
                     {}, open_kinds=tuple(open_kinds))


def gen_world(open_kinds=DEFAULT_KINDS) -> GenWorld:
    atoms = [kernel.Atom(name, len(ins), fn) for name, (ins, _, fn, _) in _OPS.items()]
    signatures = {name: Signature(ins, out) for name, (ins, out, _, _) in _OPS.items()}
    sorts = {"int": Sort("int", tuple(range(-3, 9))), "bool": Sort("bool", (False, True))}
    return GenWorld("toy", decl(open_kinds), atoms, signatures, sorts, frozenset(open_kinds),
                    measures={"int": [("dec", "absv")]}, bases={"int": ["is_zero", "is_pos"]},
                    max_scope=150, title="Toy integers")
