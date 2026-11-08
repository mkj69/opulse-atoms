"""Version declaration and counted host atoms."""

import json
from pathlib import Path

from opulse.atoms import kernel
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.versions import hosts

FILE = Path(__file__).resolve().parents[4] / "worlds/decl/v2/versions@1.json"


def decl():
    return WorldDecl.from_dict(json.loads(FILE.read_text(encoding="utf-8")))


def atoms():
    declaration = decl()
    result = [kernel.Atom(op.name, len(op.inputs), getattr(hosts, op.name), cost=op.cost,
                          kind="observation" if op.name in ("read", "read_version") else "operation")
              for op in declaration.operations]
    return result + [kernel.catch_atom()]


def new_library():
    from opulse.worlds_v2.versions.adapter import VersionsLibrary

    return VersionsLibrary(decl(), atoms())
