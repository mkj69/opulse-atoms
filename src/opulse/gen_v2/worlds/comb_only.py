"""Finite graph plans and states for combinator invention."""

from itertools import product

from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.comb_only import hosts, world

TAGS = world_tags("comb_only", world.decl())


def gen_world():
    plans = [hosts.Plan(seed, blocks, width)
             for seed, blocks, width in product((1, 7, 23, 41), (1, 2), (3, 4))]
    states = [hosts.start(plan) for plan in plans]
    states += [hosts.take(state, vertex) for state in states[:8] for vertex in (0, 1)]
    lists = [(), (0,), (1,), (0, 1), (1, 2), (0, 1, 2)]
    return build("comb_only", world.decl(), world.new_library().atoms,
                 {"Plan": plans, "State": states,
                  "Set": (0, 1, 2, 3, 7, 15, 31, 63), "List": lists,
                  "Pair": ((0, 1), (2, 3), (1, 4)),
                  "Tuple": ((1, 2, 3), (2, 4, 1)),
                  "Option": (None, 0, 1), "Outcome": (0, 1),
                  "unknown": (0, 1, 2, 3, (0, 1)),
                  "int": tuple(range(-1, 13)), "bool": BOOL,
                  "Nat": tuple(range(8)), "Int": tuple(range(-3, 5)), "Bool": BOOL},
                 truth_states=states, max_steps=900)
