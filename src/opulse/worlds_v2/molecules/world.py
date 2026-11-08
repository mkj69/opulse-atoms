"""Locked layer-zero declaration and executable given atoms."""

import json
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.spec import CombinatorSpec
from opulse.atoms.world import WorldDecl

from . import hosts

DECL_PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/molecules@1.json"


def decl() -> WorldDecl:
    return WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))


def chain_spec() -> CombinatorSpec:
    return CombinatorSpec.from_dict(decl().combinators["given_rules"]["chain"])


def atoms() -> list[Atom]:
    declaration = decl()
    probes = {probe["name"] for probe in declaration.observation["probes"]}
    return [Atom(op.name, len(op.inputs), getattr(hosts, op.name), cost=op.cost,
                 kind="observation" if op.name in probes else "operation", strict=op.strict)
            for op in declaration.operations]


def new_library():
    from .adapter import MoleculeLibrary

    return MoleculeLibrary(decl(), atoms())
