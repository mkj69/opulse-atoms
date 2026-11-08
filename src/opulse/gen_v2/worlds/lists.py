"""Generator probes for finite lists and their nonempty refinement."""

from itertools import product

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.lists import hosts, world

TAGS = world_tags("lists", world.decl())


def gen_world():
    items = (0, 1, 2, 3)
    lists = [hosts.to_card(seq) for size in range(4) for seq in product(items, repeat=size)]
    nonempty = [Card("nonempty", "cons", value.fields) for value in lists if value != hosts.NIL]
    return build("lists", world.decl(), world.atoms(),
                 {"int": (-2, -1, *items, 3), "bool": BOOL, "list": lists,
                  "nonempty": nonempty, "pair": [hosts.run(0, 1), hosts.run(1, 2)],
                  "run": [hosts.run(0, 1), hosts.run(1, 2)]},
                 measures={"list": [("tail", "length")]}, bases={"list": ["is_empty"]})
