"""Locked declaration and registered layer-zero atoms."""

import importlib
import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.library import Library
from opulse.atoms.world import WorldDecl

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/comb_obs@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms():
    world = decl()
    result = []
    for operation in world.operations:
        module, name = operation.impl["host"].split(":")
        result.append(kernel.Atom(operation.name, len(operation.inputs),
                                  getattr(importlib.import_module(module), name), operation.cost))
    for probe in world.observation["probes"]:
        module, name = probe["impl"]["host"].split(":")
        result.append(kernel.Atom(probe["name"], 1, getattr(importlib.import_module(module), name),
                                  kind="observation"))
    return result


def new_library():
    return Library(decl(), atoms())
