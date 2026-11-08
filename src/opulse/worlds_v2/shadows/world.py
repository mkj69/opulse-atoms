"""World declaration and layer-zero atoms."""

import json
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.world import WorldDecl

from . import deep_hosts as hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/shadows@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms():
    definition = decl()
    operations = [Atom(op.name, len(op.inputs), getattr(hosts, op.name), cost=op.cost,
                       kind="observation" if op.name in ("top", "side", "front", "diag", "anti") else "operation")
                  for op in definition.operations]
    return operations


def new_library():
    from .deep_adapter import ShadowsLibrary

    return ShadowsLibrary(decl(), atoms())
