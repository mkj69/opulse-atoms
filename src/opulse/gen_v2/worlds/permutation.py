"""Three-card permutations and finite cycles."""

from itertools import permutations

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.permutation import hosts, world

TAGS = world_tags("permutation", world.decl())


def gen_world():
    sequences = [hosts.EMPTY, *(Card("sequence", "items", row) for length in range(1, 4)
                                for row in permutations((1, 2, 3), length))]
    cycles = [Card("cycle", "positions", row) for length in (2, 3)
              for row in permutations((1, 2, 3), length) if row[0] == min(row)]
    states = [hosts.I, hosts.R, hosts.S]
    states += [hosts.swap(first, second, hosts.I)
               for first, second in permutations(range(1, 10), 2)][:30]
    sequences.extend(Card("sequence", "items", state.fields) for state in states[:8])
    return catalogue("permutation", world,
                     {"int": tuple(range(14)), "bool": BOOL, "str": ("I", "R", "S"),
                      "permutation": states,
                      "cycle": cycles, "sequence": sequences},
                     truth_states=states,
                     measures={"sequence": [("tail", "length")]}, bases={"sequence": ["empty"]})
