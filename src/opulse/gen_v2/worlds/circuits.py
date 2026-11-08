"""Generator probes for Boolean circuit DAGs."""

from itertools import product

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._common import build, world_tags
from opulse.worlds_v2.circuits import hosts, world

TAGS = world_tags("circuits", world.decl())


def gen_world():
    circuits = [hosts.deep_to_card(2, (), (output,)) for output in (0, 1)]
    circuits += [hosts.deep_to_card(2, (Card("gate", "not", (source,)),), (output,))
                 for source, output in product((0, 1), (0, 1, 2))]
    circuits += [hosts.deep_to_card(2, (Card("gate", "and", (left, right)),), (2,))
                 for left, right in product((0, 1), repeat=2)]
    circuits += [hosts.deep_to_card(2, (Card("gate", "not", (0,)),), (0, 2))]
    circuits += [hosts.deep_to_card(2, (), outputs)
                 for outputs in ((0, 1), (1, 0), (0, 0), (1, 1))]
    circuits += [hosts.deep_to_card(2, (Card("gate", "and", (left, right)),
                                       Card("gate", "not", (source,))), (output,))
                 for left, right in product((0, 1), repeat=2)
                 for source in (0, 2) for output in (0, 2, 3)]
    gates = [Card("gate", "not", (0,)), Card("gate", "not", (1,)),
             Card("gate", "and", (0, 1))]
    result = build("circuits", world.decl(), world.atoms(),
                 {"int": tuple(range(6)), "bit": (0, 1), "str": ("and", "not"),
                  "bool": (False, True), "tuple": ((), (0,), (1,), (0, 1)),
                  "bits": [Card("bits", "list", pair) for pair in product((0, 1), repeat=2)],
                  "gate": gates, "gates": [Card("gates", "list", ()),
                                            *(Card("gates", "list", (gate,)) for gate in gates)],
                  "ports": [Card("ports", "list", (index,)) for index in (0, 1, 2)],
                  "circuit": circuits,
                  "witness": [Card("witness", "none"), Card("witness", "first", (0, 0, 0, 1))]},
                 truth_states=circuits, finite_sorts=("bit",))
    result.sorts["circuit"].values = tuple(circuits[:32])
    return result
