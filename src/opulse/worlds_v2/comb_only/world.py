"""Locked declaration and registration of counted layer-zero operations."""

import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.library import Library
from opulse.atoms.values import Bottom
from opulse.atoms.world import WorldDecl

from . import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/comb_only@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def new_library():
    world = decl()
    def given(function):
        def apply(*arguments):
            try:
                return function(*(hosts.from_notation(argument) for argument in arguments))
            except ValueError as error:
                if str(error) == "Bottom(range)":
                    return Bottom("range")
                raise

        return apply

    atoms = [kernel.Atom(operation.name, len(operation.inputs),
                         given(getattr(hosts, operation.impl["host"].split(":")[1])),
                         cost=operation.cost, kind="observation" if operation.name in
                         {"score", "chosen", "legal", "available"} else "operation")
             for operation in world.operations]
    return Library(world, atoms)
