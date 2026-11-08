"""Small voxel bodies and distinct public projection probes."""

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.shadows import deep_hosts as hosts
from opulse.worlds_v2.shadows import world

TAGS = world_tags("shadows", world.decl())


def gen_world():
    bodies = [hosts.to_card(tuple((index // 48, (index // 6) % 8, index % 6)
                            for index in range(384) if mask & (1 << index)))
              for mask in (0, 255, *range(1, 32), 51, 85, 170)]
    lists = [Card("List", "items", tuple(bodies[:length])) for length in range(5)]
    return catalogue("shadows", world,
                     {"int": tuple(range(-1, 17)), "bool": BOOL, "Volume": bodies,
                      "Mask": [hosts.mask(), hosts.mask(hosts.cell(0, 0, 0))],
                      "List": lists, "Set": [Card("Set", "items", ()),
                                              Card("Set", "items", (hosts.cell(0, 0, 0),))]},
                     truth_states=bodies, max_steps=1400)
