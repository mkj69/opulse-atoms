"""Finite warehouse runs and public probes for combinators and observations."""

from itertools import product

from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.comb_obs import hosts, reference, world

TAGS = world_tags("comb_obs", world.decl())


def gen_world():
    runs = [reference.Run(seed, goal)
            for seed, goal in product(range(8), ((3, 3), (4, 4), (5, 5)))]
    paths = [(), ((2, 2),), ((2, 2), (3, 2)), ((3, 3), (4, 4))]
    return build("comb_obs", world.decl(), world.atoms(),
                 {"sealed_terrain": runs, "Run": runs,
                  "Cell": (hosts.HOME, (3, 2), (2, 3), (3, 3)),
                  "Path": paths, "List": ([], [0], [1], [0, 1]),
                  "Map": ({}, {(2, 2): True}, {"A": ((3, 3), 2)}),
                  "Cargo": ((set(), set(), 0), ({"A"}, set(), 2)),
                  "Event": (("scan", hosts.HOME), ("move", (3, 2))),
                  "Int": tuple(range(8)), "int": tuple(range(-2, 12)),
                  "Text": ("", "A", "B"), "str": ("", "A", "B"),
                  "Bool": BOOL, "bool": BOOL, "Option": (None, 0, 1),
                  "any": (0, 1, 2, (), (0,), hosts.HOME)},
                 truth_states=runs, max_steps=1200)
