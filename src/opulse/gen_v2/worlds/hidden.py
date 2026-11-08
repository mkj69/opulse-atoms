"""Private-card signaling: truth states are separate from receiver views."""

from fractions import Fraction
from itertools import product

from opulse.atoms.kernel import Atom
from opulse.atoms.values import FALSE, TRUE
from opulse.gen_v2.worlds._common import build, world_tags
from opulse.worlds_v2.hidden import hosts, world

TAGS = world_tags("hidden", world.decl())


def gen_world():
    histories = [(), *((((mode, lamp),)) for mode, lamp in product(hosts.MODES, hosts.LAMPS)),
                 (("A", "red"), ("B", "blue"))]
    states = [hosts.state(card, history) for card, history in product(hosts.CARDS, histories)]
    probabilities = [hosts.rational(Fraction(numerator, denominator))
                     for denominator in (1, 2, 3, 4) for numerator in range(denominator + 1)]
    views = [hosts.receiver(state) for state in states]
    return build("hidden", world.decl(), (*world.atoms(), Atom("receiver", 1, hosts.receiver,
                        kind="observation")),
                 {"int": tuple(range(7)), "str": (*hosts.CARDS, *hosts.LAMPS, *hosts.MODES),
                  "bool": (FALSE, TRUE), "Truth": states, "ReceiverView": views,
                  "Rational": probabilities,
                  "BeliefPair": [hosts.pair(value, hosts.rational(1 - hosts.fraction(value)))
                                 for value in probabilities],
                  "DistLamp": [hosts.channel(mode, card)
                                for mode, card in product(hosts.MODES, hosts.CARDS)],
                  "History": [state.fields[1] for state in states],
                  "Actions": [state.fields[2] for state in states]},
                 truth_states=states * 4,
                 granted_probes=("receiver",),
                 excluded_probes=("judge",))
