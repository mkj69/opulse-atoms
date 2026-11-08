"""Locked world declaration and its given kernel primitives."""

import importlib
import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.library import Library
from opulse.atoms.world import WorldDecl

ROOT = Path(__file__).resolve().parents[4]
DECL_PATH = ROOT / "worlds/decl/v2/obj_only@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def new_library():
    source = decl()
    atoms = []
    for operation in source.operations:
        module, name = operation.impl["host"].split(":")
        atoms.append(kernel.Atom(operation.name, len(operation.inputs),
                                 getattr(importlib.import_module(module), name), operation.cost,
                                 strict=operation.name != "is_ok"))
    for probe in source.observation["probes"]:
        module, name = probe["impl"]["host"].split(":")
        atoms.append(kernel.Atom(probe["name"], 1, getattr(importlib.import_module(module), name),
                                 kind="observation", strict=probe["name"] != "accepted"))
    return Library(source, atoms)
