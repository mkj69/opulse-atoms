"""Descriptive, separately promoted overlapping-recursion cost tower."""

import csv
import math
import random
import sys

from atoms_mul.kernel.core_library import mirror_sort

from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.atoms.values import Ok
from opulse.atoms.world import WorldDecl

from .memo import compare_runs, memo_scope
from .pipeline import promote_tower

SOURCE = """op choose(n: Nat, k: Nat) -> Nat = if eq(k, 0) then 1 else if eq(k, n) then 1 else add(choose(pred(n), pred(k)), choose(pred(n), k))
op paths(n: Nat, k: Nat) -> Nat = choose(n, k)"""
SEED = 20261105
HEADER = ("id", "n", "k", "outcome", "steps", "plain_work", "memo_work", "memo_hits")


def cost_inputs():
    """Twelve seeded interior Pascal cells, with overlapping recursive subcalls."""
    inputs = [(n, k) for n in range(6, 9) for k in range(2, n - 1)]
    random.Random(SEED).shuffle(inputs)
    return inputs


def build_cost_tower():
    """Parse, verify and promote the separate AML source on its recorded domain."""
    given = (("eq", 2, lambda left, right: left == right, "bool", "decide"),
             ("pred", 1, lambda value: value - 1, "nat", "transform"),
             ("add", 2, lambda left, right: left + right, "nat", "combine"))
    world = WorldDecl("boundary_pascal_cost", 1, "atoms-v2", {}, {},
                      (ObjectSpec("nat", "given"),),
                      tuple(OperationSpec(name, role, (Edge("int"),) * arity,
                                          Edge(mirror_sort(output)), name)
                            for name, arity, _, output, role in given),
                      {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("operation",))
    library = Library(world, [kernel.Atom(name, arity, fn)
                              for name, arity, fn, _, _ in given])
    domains = {"choose": [(n, k) for n in range(9) for k in range(n + 1)],
               "paths": cost_inputs()}
    return promote_tower(
        library, SOURCE, domains, {name: math.comb for name in domains},
        {"choose": "all 0 <= k <= n <= 8",
         "paths": "listed interior Pascal cells, 6 <= n <= 8 and 2 <= k <= n-2"},
        {name: f"binomial coefficient on the recorded {name} cells" for name in domains},
        memoized=("choose",),
    )


def memo_hits(frame):
    """Count physical cache hits, excluding subtrees replayed by a hit."""
    if frame is None:
        return 0
    if frame.memo_hit:
        return 1
    return sum(memo_hits(child) for child in frame.children)


def cost_rows(library, inputs=None):
    """Check charged unfolding and record distinct physical work per item."""
    plain = library.scope()
    cached = memo_scope(plain)
    rows = []
    for index, args in enumerate(cost_inputs() if inputs is None else inputs):
        ordinary, memoized = compare_runs(plain, cached, args, trace=True, name="paths")
        if ordinary.outcome != Ok(math.comb(*args)):
            raise ValueError(f"Pascal reference differs at {args!r}")
        rows.append((index, *args, f"Ok({ordinary.outcome.value})", ordinary.steps,
                     ordinary.work, memoized.work, memo_hits(memoized.trace)))
    if inputs is None and sum(row[6] < row[5] for row in rows) < 10:
        raise ValueError("memo work must improve on at least 10 of 12 items")
    return rows


def main():
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(cost_rows(build_cost_tower()))


if __name__ == "__main__":
    main()
