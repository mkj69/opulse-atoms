"""Declaration and fixed layer-zero kernel registrations."""

import importlib
import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.library import Library
from opulse.atoms.world import WorldDecl

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/obs_only@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms(config=None):
    source = decl()
    result = []
    from .hosts import guarded

    for operation in source.operations:
        module, attribute = operation.impl["host"].split(":")
        function = getattr(importlib.import_module(module), attribute)
        if operation.name == "config_of" and config is not None:
            function = lambda trace: config
        result.append(kernel.Atom(operation.name, len(operation.inputs), guarded(function), operation.cost))
    for probe in source.observation["probes"]:
        module, attribute = probe["impl"]["host"].split(":")
        function = getattr(importlib.import_module(module), attribute)
        if probe["name"] == "public_config" and config is not None:
            function = lambda trace: config
        result.append(kernel.Atom(probe["name"], {
            "frame": 2, "issued": 2, "prior": 2, "protocol": 3, "public_config": 1,
        }[probe["name"]], guarded(function), kind="observation"))
    return result


def new_library(config=None):
    return Library(decl(), atoms(config))
