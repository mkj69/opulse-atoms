"""Finite probes for the timestamped kitchen and its public stock observations."""

from itertools import product

from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.kitchen import depth_hosts, world

TAGS = world_tags("kitchen", world.decl())


def gen_world():
    states = [depth_hosts.state(*amounts) for amounts in product(range(3), repeat=4)]
    lists = [(), ("flour",), ("flour", "water"), ("mix", "tick")]
    lots = [("flour", 0, 2), ("water", 0, 1), ("egg", 0, 1)]
    recipes = tuple(depth_hosts.RECIPES)
    queries = [(state, ("mix", "tick")) for state in states[:4]]
    return catalogue("kitchen", world,
                     {"int": tuple(range(-2, 14)), "str": (*depth_hosts.ITEMS, *recipes),
                      "bool": BOOL, "State": states, "List": lists,
                      "Lot": (*lots, 0, 1), "Job": (("mix", 2), ("whisk", 1)),
                      "Query": queries, "Recipe": recipes},
                     truth_states=(*states[24:48], *states[:16]),
                     measures={"List": [("tail", "length")]}, bases={"List": ["empty"]})
