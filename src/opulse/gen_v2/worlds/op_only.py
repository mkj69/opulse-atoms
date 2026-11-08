"""Finite public relations for the operation-only world."""

from dataclasses import replace

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.op_only import algorithms, hosts, world

TAGS = world_tags("op_only", world.decl())


def gen_world():
    relations = [hosts.pack(algorithms.Rel(4, (row, 0, 0, 0))) for row in range(16)]
    relations += [hosts.pack(algorithms.Rel(4, (0, row, 0, 0))) for row in range(16)]
    profiles = [hosts.pack_profile(algorithms.Profile([0, 1, 2, 3], [1, 1, 1, 1])),
                hosts.pack_profile(algorithms.Profile([0, 2, 3, 4], [1, 2, 1, 2]))]
    edges = [Card("Edge", "Edge", (source, target))
             for source in range(4) for target in range(4)]
    declaration = world.decl()
    observation = dict(declaration.observation)
    observation["probes"] = [dict(probe, reads="Profile") if probe["name"] in
                             ("maxdepth", "longest_count") else probe
                             for probe in observation["probes"]]
    declaration = replace(declaration, observation=observation)
    return build("op_only", declaration, world.new_library().atoms,
                 {"Rel": relations, "Profile": profiles, "Edge": edges,
                  "Gates": (Card("Gates", "Gates", ()), Card("Gates", "Gates", (0,))),
                  "int": tuple(range(-1, 12)), "bool": BOOL,
                  "any": (0, 1, 2, "union", "compose")},
                 truth_states=relations, probe_inputs={"has": ("Edge",)})
