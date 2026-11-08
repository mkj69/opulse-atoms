"""Points, triangles, and coordinate probes on a finite plane."""

from dataclasses import replace
from itertools import product

from opulse.gen_v2.base import Signature
from opulse.gen_v2.worlds._catalogue import catalogue
from opulse.gen_v2.worlds._common import BOOL, world_tags
from opulse.worlds_v2.geometry import hosts, world

TAGS = world_tags("geometry", world.decl())


def gen_world():
    points = [hosts.point(x, y) for x, y in product(range(5), repeat=2)]
    paths = [tuple(points[index:index + length])
             for length in (2, 3, 4, 5) for index in range(0, 20, 2)]
    result = catalogue("geometry", world,
                     {"int": tuple(range(-4, 12)), "bool": BOOL, "Point": points,
                      "Path": paths,
                      "List": [tuple(points[:length]) for length in range(5)]},
                     truth_states=paths)
    observation = dict(result.decl.observation)
    observation["probes"] = [dict(probe, sort="List") if probe["name"] == "points" else probe
                             for probe in observation["probes"]]
    result.decl = replace(result.decl, observation=observation)
    result.signatures["points"] = Signature(("Path",), "List")
    return result
