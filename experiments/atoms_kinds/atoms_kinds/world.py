"""Identical public Pair and integer semantics in every open-kind arm."""

import hashlib
import math
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.library import Library
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Bottom, Card
from opulse.atoms.world import WorldDecl

GROUPS = {"K1": ("operation",), "K2": ("object", "operation"),
          "K3": ("combinator", "object", "operation"),
          "K4": ("combinator", "law", "object", "operation"),
          "K5": ("combinator", "law", "object", "observation", "operation"),
          "K6": ("bridge", "combinator", "law", "object", "observation", "operation")}

GIVEN_RULES = (
    "op add(a: Int, b: Int) -> Int given   # a + b; error: none",
    "op sub(a: Int, b: Int) -> Int given   # a - b; error: none",
    "op mul(a: Int, b: Int) -> Int given   # a * b; error: none",
    "op div(a: Int, b: Int) -> Int given   # quotient rounded toward zero (div(-7, 3) = -2); error: division by zero -> Bottom(div_zero)",
    "op mod(a: Int, b: Int) -> Int given   # Python remainder, sign follows b (mod(-7, 3) = 2); error: division by zero -> Bottom(div_zero)",
    "op gcd(a: Int, b: Int) -> Int given   # nonnegative greatest common divisor (gcd(-7, -3) = 1; gcd(0, 0) = 0); error: none",
    "op eq(a: Int, b: Int) -> Bool given   # true iff a equals b; error: none",
    "op lt(a: Int, b: Int) -> Bool given   # true iff a is less than b; error: none",
    "All integers are unbounded; no overflow. Negative mod divisors use Python's floor-division remainder.",
)


def integer_add(left, right):
    return left + right


def integer_sub(left, right):
    return left - right


def integer_mul(left, right):
    return left * right


def integer_div(left, right):
    return Bottom("div_zero") if right == 0 else abs(left) // abs(right) * (-1 if (left < 0) != (right < 0) else 1)


def integer_mod(left, right):
    return Bottom("div_zero") if right == 0 else left % right


def integer_gcd(left, right):
    return math.gcd(left, right)


def integer_eq(left, right):
    return left == right


def integer_lt(left, right):
    return left < right


def pair_num_probe(pair):
    if (not isinstance(pair, Card) or pair.sort != "Pair" or pair.tag != "pair" or
            len(pair.fields) != 2 or any(type(field) is not int for field in pair.fields)):
        return Bottom("invalid")
    return pair.fields[0]


def integer_atoms():
    functions = {"add": integer_add, "sub": integer_sub, "mul": integer_mul,
                 "div": integer_div, "mod": integer_mod, "gcd": integer_gcd,
                 "eq": integer_eq, "lt": integer_lt}
    return tuple(Atom(name, 2, fn) for name, fn in functions.items())


def make_world(group):
    if group not in GROUPS:
        raise ValueError(f"unknown group: {group}")
    integer = Edge("int")
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    operations = tuple(OperationSpec(atom.name, "decide" if atom.name in ("eq", "lt") else "combine",
                                     (integer, integer), Edge("bool") if atom.name in ("eq", "lt") else integer,
                                     f"integer {atom.name}", impl={"host": f"atoms_kinds.world:{atom.fn.__name__}",
                                                                   "digest": digest}) for atom in integer_atoms())
    operations += (OperationSpec("Pair.pair", "combine", (integer, integer), Edge("Pair"),
                                 "construct Pair<num, den>"),
                   OperationSpec("Pair.num", "transform", (Edge("Pair"),), integer,
                                 "read numerator"),
                   OperationSpec("Pair.den", "transform", (Edge("Pair"),), integer,
                                 "read denominator"),
                   OperationSpec("pair_num_probe", "transform", (Edge("Pair"),), integer,
                                 "observe the public numerator", impl={"host": "atoms_kinds.world:pair_num_probe",
                                                                  "digest": digest}))
    world = WorldDecl("fractions", 1, "atoms-v2", {}, {},
                      (ObjectSpec("int", "given"), ObjectSpec("bool", "given"),
                       ObjectSpec("Pair", "compose", tags={"pair": [["num", "int"], ["den", "int"]]})),
                      operations, {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                                   "library": [], "recursion": "fuel"},
                      {"truth": None, "probes": [{"name": "pair_num_probe", "sort": "int"}],
                       "show": {"input": "values", "result": "value"},
                       "judge_view": "full_state"}, {}, open_kinds=GROUPS[group])
    return world


def make_library(group):
    return Library(make_world(group), (*integer_atoms(), Atom("pair_num_probe", 1, pair_num_probe,
                                                             kind="observation")))
