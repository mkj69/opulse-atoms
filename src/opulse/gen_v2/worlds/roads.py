"""Public twelve-junction road graphs and their edge probes."""

from dataclasses import replace

from opulse.atoms.values import Bottom, Card
from opulse.gen_v2.base import Signature
from opulse.gen_v2.worlds._common import BOOL, build, world_tags
from opulse.worlds_v2.roads import depth_hosts, world

TAGS = world_tags("roads", world.decl())


def _public_map(context, graph):
    if not depth_hosts.valid_graph(graph):
        return Bottom("invalid_graph")
    return context.call("roads_from_parts", graph.fields)


def gen_world():
    public_graphs = [depth_hosts.METRO, *(depth_hosts.to_card((depth_hosts.METRO_NODES,
                     depth_hosts.METRO_EDGES[:length])) for length in range(1, 24))]
    atoms = tuple(replace(atom, fn=_public_map) if atom.name == "map_view" else atom
                  for atom in world.atoms())
    result = build("roads", world.decl(), atoms,
                     {"int": tuple(range(-2, 12)), "str": depth_hosts.METRO_NODES,
                      "bool": BOOL,
                      "Roads": public_graphs,
                      "List": [Card("List", "items", ()), Card("List", "items", (1,))]},
                     truth_states=public_graphs, granted_probes=("map_view",))
    observation = dict(result.decl.observation)
    observation["truth"] = "Roads"
    observation["probes"] = [dict(probe, reads="List" if probe["name"] == "size" else "Roads",
                                  sort="int" if probe["name"] == "size" else probe["sort"])
                             for probe in observation["probes"]]
    result.decl = replace(result.decl, observation=observation)
    result.signatures.update({probe["name"]: Signature((probe["reads"],), probe["sort"])
                              for probe in observation["probes"]})
    result.truth_sort = "Roads"
    return result
