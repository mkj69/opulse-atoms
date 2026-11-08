"""Load the declaration and make its given atoms available to the kernel."""

import json
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library
from opulse.atoms.spec import CombinatorSpec, Definition
from opulse.atoms.values import Bottom, Card
from opulse.atoms.world import WorldDecl

from . import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/permutation@1.json"


def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms() -> list[kernel.Atom]:
    world = decl()
    given = [kernel.Atom(op.name, len(op.inputs), getattr(hosts, op.impl["host"].split(":")[-1]), op.cost)
             for op in world.operations]
    return given + [kernel.Atom(probe["name"], 1, getattr(hosts, probe["name"]), 1, "observation")
                    for probe in world.observation["probes"]]


def then_spec():
    body = nodes.Call("g", (nodes.Call("f", (nodes.Var("source"),)),))
    return CombinatorSpec("then", ("f", "g", "source"), ("f", "g"), body)


class PermutationLibrary(Library):
    def run(self, name, args, fuel=None, trace=False):
        def valid_input(value):
            if isinstance(value, Card):
                if value.sort == "permutation":
                    return hosts.valid_permutation(value)
                if value.sort == "Cycle":
                    return hosts.valid_cycle(value)
                if value.sort == "Subgroup":
                    return hosts.valid_subgroup(value)
                if value.sort == "sequence":
                    return value.tag == "items" and all(valid_input(item) for item in value.fields)
                return value.sort == "bool" and value.tag in ("true", "false") and not value.fields
            return True

        if not all(valid_input(arg) for arg in args):
            return kernel.Run(Bottom("invalid"), 0, 0, None)
        return super().run(name, args, fuel=fuel, trace=trace)

def new_library() -> Library:
    library = PermutationLibrary(decl(), atoms())
    spec = then_spec()
    library._definitions["then"] = Definition("then", "combinator", "given", 0, (), spec, spec.body,
                                              status="promoted")
    return library
