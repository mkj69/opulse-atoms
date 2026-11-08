"""Locked computer@2 declaration and layer-zero kernel atoms."""

import json
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.world import WorldDecl

from . import hosts


def decl():
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/computer@2.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atoms():
    world = decl()
    result = [Atom(item.name, len(item.inputs), getattr(hosts, item.impl["host"].split(":")[-1]), item.cost)
              for item in world.operations]
    result.extend(Atom(item["name"], 2 if item["name"] == "?mem" else 1,
                       getattr(hosts, item["impl"]["host"].split(":")[-1]),
                       kind="observation") for item in world.observation["probes"])
    return result


def new_library():
    from .adapter import ComputerLibrary

    return ComputerLibrary(decl(), atoms())
