"""Load the locked text world and expose only its given atoms."""

import json
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.world import WorldDecl

from . import hosts
from .adapter import TextLibrary


def decl() -> WorldDecl:
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/text@1.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atoms() -> list[Atom]:
    world = decl()
    result = [Atom(op.name, len(op.inputs), getattr(hosts, op.name), op.cost) for op in world.operations]
    result.extend(Atom(probe["name"], 1, getattr(hosts, probe["name"]), 1, "observation")
                  for probe in world.observation["probes"])
    return result


def new_library() -> TextLibrary:
    return TextLibrary(decl(), atoms())
