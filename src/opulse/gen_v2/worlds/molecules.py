"""Short labelled bond graphs and public molecule views."""

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.molecules import hosts, world

TAGS = world_tags("molecules", world.decl())


def gen_world():
    graphs = [hosts.to_card(labels, bonds) for labels in (("C",), ("O",),
              ("C", "C"), ("C", "O"), ("O", "O"), ("C", "O", "C"), ("C", "C", "O"))
              for bonds in ((), ((0, 1),)) if len(labels) > 1 or not bonds]
    return catalogue("molecules", world,
                     {"int": tuple(range(-1, 9)), "str": ("C", "O", "H", "invalid"),
                      "bool": BOOL, "Graph": graphs, "AtomsView": [hosts.atoms(graph) for graph in graphs],
                      "List": [hosts.list_make(*values) for values in
                               ((), (0,), (1, 2), (2, 3, 4))],
                      "Pair": [hosts.pair_make(0, 1), hosts.pair_make(1, 2)],
                      "Triple": [Card("Triple", "triple", ("C", 0, 4)),
                                 Card("Triple", "triple", ("O", 1, 2))],
                      "Record": [hosts.record_make(graph, index, hosts.list_make())
                                 for index, graph in enumerate(graphs[:4])]},
                     truth_states=graphs * 2, max_steps=1400)
