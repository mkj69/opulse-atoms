"""Generator probes for immutable edit histories."""

from itertools import product

from opulse.atoms.values import Card
from opulse.gen_v2.worlds._common import build, world_tags
from opulse.worlds_v2.versions import hosts, world

TAGS = world_tags("versions", world.decl())


def gen_world():
    root = hosts.base12()
    edits = [hosts.edit(root, path, text) for path, text in product(hosts.PATHS, ("1", "2"))]
    versions = [hosts.history(), *(hosts.fork(hosts.history(), 0, path, text)
                  for path, text in product(hosts.PATHS, ("1", "2")))]
    return build("versions", world.decl(), world.atoms(),
                 {"str": (*hosts.PATHS, "0", "1", "2", hosts.GONE),
                  "bool": (False, True), "int": tuple(range(14)),
                  "Doc": (root, *edits), "History": versions,
                  "Any": (root, *versions), "Path": hosts.PATHS,
                  "Text": ("0", "1", "2"), "Base12": (root, edits[0]),
                  "Version": [version.fields[-1] for version in versions],
                  "List": [Card("List", "items", ()), Card("List", "items", (root,))]},
                 truth_states=(root, *edits, *versions[1:]))
