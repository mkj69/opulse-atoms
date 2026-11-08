"""Finite records and rational pairs for object invention."""

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.obj_only import hosts, world

TAGS = world_tags("obj_only", world.decl())


def gen_world():
    records = [hosts.polynomial(((0, index), (1, 1))) for index in range(24)]
    records += [hosts.interval(index, index + 1) for index in range(8)]
    objects = [Card("SparsePoly", "val", (record,)) for record in records[:24]]
    pairs = [(index, denominator) for index in range(-2, 4) for denominator in (1, 2)]
    return build("obj_only", world.decl(), world.new_library().atoms,
                 {"int": tuple(range(-3, 13)), "bool": BOOL,
                  "str": ("", "0", "1", "2", "raw", "term", "1/2"),
                  "raw": records, "pair": pairs,
                  "list": ((), (0,), (1,), (1, 2), (Card("raw", "term", (0, "1")),)),
                  "unknown": objects},
                 truth_states=objects)
