"""Small 3 by 3 card grids, including connected and separated patterns."""

from itertools import product

from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.pixels import hosts, world

TAGS = world_tags("pixels", world.decl())


def gen_world():
    points = [hosts.point(x_coord, y_coord) for x_coord, y_coord in product(range(3), repeat=2)]
    masks = [0, 511, *(1 << index for index in range(9)),
             *(3 << index for index in range(8)), 0b101010101, 0b010101010,
             0b000000101, 0b100000001, 0b001010100]
    grids = [hosts.to_card(tuple("".join("#" if mask & (1 << (3 * y + x)) else "."
                                     for x in range(3)) for y in range(3))) for mask in masks]
    lists = [hosts.list_of(*points[:length]) for length in range(5)]
    return catalogue("pixels", world,
                     {"int": tuple(range(-2, 13)), "bool": BOOL, "point": points,
                      "str": ("...", "###", ".#."), "grid": grids, "list": lists},
                     truth_states=grids,
                     measures={"list": [("tail", "length")]}, bases={"list": ["is_empty"]})
