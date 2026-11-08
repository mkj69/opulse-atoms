"""Declaration and given atoms for the pixel world."""

import importlib
import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.pixels.adapter import PixelsLibrary


def decl():
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/pixels@1.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atoms():
    world = decl()
    result = []
    for operation in world.operations:
        module_name, name = operation.impl["host"].split(":")
        result.append(kernel.Atom(operation.name, len(operation.inputs), getattr(importlib.import_module(module_name), name),
                                  cost=operation.cost, strict=operation.strict))
    for probe in world.observation["probes"]:
        module_name, name = probe["impl"]["host"].split(":")
        result.append(kernel.Atom(probe["name"], 1, getattr(importlib.import_module(module_name), name),
                                  cost=1, kind="observation"))
    return result


def new_library():
    return PixelsLibrary(decl(), atoms())
