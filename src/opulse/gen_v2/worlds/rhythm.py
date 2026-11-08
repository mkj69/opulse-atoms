"""Eight-beat event patterns with exact canonical probes."""

from itertools import product

from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.rhythm import hosts, world

TAGS = world_tags("rhythm", world.decl())


def gen_world():
    patterns = [hosts.to_card(events) for events in product((0, 1, 2), repeat=3)
                for events in (events + (0,) * 5,)]
    patterns += [hosts.to_card((0,) * index + (2,) + (0,) * (7 - index))
                 for index in range(8)]
    seeds = ((0, 1, 2, 0, 2, 1, 0, 2), (2, 0, 0, 1, 2, 0, 1, 0),
             (0, 2, 1, 2, 0, 1, 0, 2))
    truth_states = [hosts.to_card(seed[offset:] + seed[:offset])
                    for seed in seeds for offset in range(8)]
    patterns += truth_states
    result = build("rhythm", world.decl(), world.atoms(),
                   {"int": tuple(range(9)), "bool": BOOL, "rhythm": patterns,
                    "any": ((0,), (1,), (0, 1), (1, 2), (2, 0, 1)),
                    "list": ((), (0,), (1,), (0, 1), (1, 2), (2, 0, 1))},
                   truth_states=truth_states)
    result.sorts["rhythm"].values = (*truth_states, *patterns[:8])
    return result
