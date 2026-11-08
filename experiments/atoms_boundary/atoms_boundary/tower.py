"""One AML source for the promoted tower and the learner-facing text."""

from itertools import product

from atoms_mul.kernel import format_def, parse_program
from atoms_mul.kernel.core_library import mirror_sort

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import Library
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.world import WorldDecl

from .pipeline import promote_tower

SOURCE = """op mul(a: Nat, b: Nat) -> Nat = if is_zero(b) then 0 else add(a, mul(a, pred(b)))
op dot2(a: Nat, b: Nat, c: Nat, d: Nat) -> Nat = add(mul(a, b), mul(c, d))
op dot3(a: Nat, b: Nat, c: Nat, d: Nat, e: Nat, f: Nat) -> Nat = add(add(mul(a, b), mul(c, d)), mul(e, f))
op square(x: Nat) -> Nat = mul(x, x)
op score(a: Nat, b: Nat, c: Nat) -> Nat = add(add(dot3(a, b, b, c, c, a), dot2(a, c, b, b)), square(b))"""

GIVEN = """op add(a: Nat, b: Nat) -> Nat given
op pred(a: Nat) -> Nat given
op eq(a: Nat, b: Nat) -> Bool given
op is_zero(a: Nat) -> Bool given"""


def definitions_text(library):
    return GIVEN + "\n" + "\n".join(
        f"{format_def(entry)} L{library.get(entry.name).layer}"
        for entry in parse_program(SOURCE).defs
    )


def build_tower():
    given = (("add", 2, lambda a, b: a + b, "nat", "combine"),
             ("pred", 1, lambda a: a - 1, "nat", "transform"),
             ("eq", 2, lambda a, b: a == b, "bool", "decide"),
             ("is_zero", 1, lambda a: a == 0, "bool", "decide"))
    world = WorldDecl("boundary_nat", 1, "atoms-v2", {}, {}, (ObjectSpec("nat", "given"),),
                      tuple(OperationSpec(name, role, (Edge("int"),) * arity, Edge(mirror_sort(output)), name)
                            for name, arity, _, output, role in given),
                      {"nodes": list(n.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("operation",))
    library = Library(world, [kernel.Atom(name, arity, fn) for name, arity, fn, _, _ in given])

    integers = range(5)
    triples = list(product(integers, repeat=3))
    domains = {
        "mul": list(product(integers, repeat=2)),
        "dot2": list(product(integers, repeat=4)),
        "dot3": [(a, b, b, c, c, a) for a, b, c in triples],
        "square": [(value,) for value in integers],
        "score": triples,
    }
    references = {
        "mul": lambda a, b: a * b,
        "dot2": lambda a, b, c, d: a * b + c * d,
        "dot3": lambda a, b, c, d, e, f: a * b + c * d + e * f,
        "square": lambda value: value * value,
        "score": lambda a, b, c: a * b + b * c + 2 * a * c + 2 * b * b,
    }
    return promote_tower(
        library, SOURCE, domains, references,
        {name: f"listed {name} tuples with entries in 0..4" for name in domains},
        {name: f"exact {name} value on listed tuples" for name in domains},
    )
