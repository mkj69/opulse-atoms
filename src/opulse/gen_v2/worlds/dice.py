"""Finite exact dice distributions and their public mass probe."""

from fractions import Fraction
from itertools import product

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.dice import hosts, world

TAGS = world_tags("dice", world.decl())


def gen_world():
    dice = [hosts.FAIR, hosts.TILT, *(hosts.die(*(1 if index != face else 2 for index in range(6)))
                                      for face in range(6))]
    pairs = [hosts.pair(left, right) for left, right in product(range(1, 7), repeat=2)]
    fractions = [hosts.to_card(Fraction(numerator, denominator))
                 for denominator in (1, 2, 3, 6) for numerator in range(denominator + 1)]
    distributions = [hosts.roll(hosts.FAIR), *(hosts.distribution(((die, Fraction(1)),)) for die in dice),
                     *(hosts.distribution(((pair, Fraction(1)),)) for pair in pairs[:20])]
    entries = [Card("weighted", "entry", (item, 1, 1)) for item in (*dice, *pairs[:8])]
    values = [(), *((face,) for face in range(1, 7)),
              *((pair,) for pair in pairs[:12]),
              *(hosts.event(index, index + 2) for index in range(2, 9))]
    result = build("dice", world.decl(), world.atoms(),
                   {"int": tuple(range(9)), "bool": BOOL, "die": dice,
                    "fraction": fractions, "weighted": entries, "dist": distributions,
                    "value": values, "Fair": (hosts.FAIR, hosts.TILT),
                    "Tilt": (hosts.TILT, hosts.FAIR), "state": [hosts.state(index, hidden)
                        for index, hidden in product((0, 1, 2), (0, 1))]},
                   truth_states=distributions[:24],
                   max_steps=4000)
    return result
