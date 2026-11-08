"""Public declaration and given host registration."""

import importlib
import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.library import Library
from opulse.atoms.world import WorldDecl

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/op_only@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def new_library():
    source = decl()
    atoms = []
    for operation in source.operations:
        module, name = operation.impl["host"].split(":")
        atoms.append(kernel.Atom(operation.name, len(operation.inputs),
                                 getattr(importlib.import_module(module), name), operation.cost,
                                 metered=operation.name in ("fix2_host", "dag_fold_host", "filter_edges")))
    for probe in source.observation["probes"]:
        module, name = probe["impl"]["host"].split(":")
        arity = 2 if name == "has" else 1
        atoms.append(kernel.Atom(name, arity, getattr(importlib.import_module(module), name),
                                 kind="observation"))
    return Library(source, atoms)
