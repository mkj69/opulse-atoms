"""Load the locked declaration and its layer-zero atoms."""

import json
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.library import Library
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2.lists import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/lists@2.json"


def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def atoms() -> list[Atom]:
    implementations = {op.name: getattr(hosts, op.name) for op in decl().operations}
    return [Atom(op.name, len(op.inputs), implementations[op.name], cost=op.cost,
                 kind="observation" if op.name in ("items", "length") else "operation", strict=op.strict)
            for op in decl().operations]


class ListsLibrary(Library):
    def _params(self, defn):
        if defn.kind == "observation" and defn.origin == "invented":
            return ("xs", "steps") if defn.name == "certificate" else ("xs",)
        return super()._params(defn)

def new_library() -> Library:
    return ListsLibrary(decl(), atoms())
