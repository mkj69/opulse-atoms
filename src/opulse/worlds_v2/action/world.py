"""Locked layer-zero declaration and kernel atoms."""

import json
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.world import WorldDecl

from . import hosts
from .adapter import ActionLibrary


def decl():
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/action@2.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atoms():
    world = decl()
    result = [Atom(op.name, len(op.inputs), getattr(hosts, op.name), op.cost) for op in world.operations]
    result.extend(Atom(probe["name"], 1, getattr(hosts, probe["name"]), 1, "observation")
                  for probe in world.observation["probes"])
    return result


def new_library():
    return ActionLibrary(decl(), atoms())
