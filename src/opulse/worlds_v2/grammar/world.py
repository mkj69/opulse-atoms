"""Locked grammar declaration and its layer-zero kernel scope."""

import json
from pathlib import Path

from opulse.atoms.kernel import Atom
from opulse.atoms.world import WorldDecl

from . import hosts
from .adapter import GrammarLibrary


def decl() -> WorldDecl:
    path = Path(__file__).resolve().parents[4] / "worlds/decl/v2/grammar@1.json"
    return WorldDecl.from_dict(json.loads(path.read_text(encoding="utf-8")))


def atoms() -> list[Atom]:
    declaration = decl()
    operations = [Atom(operation.name, len(operation.inputs), getattr(hosts, operation.name), operation.cost)
                  for operation in declaration.operations]
    return operations + [Atom(probe["name"], 1, getattr(hosts, probe["name"]), 1, "observation")
                         for probe in declaration.observation["probes"]]


def new_library() -> GrammarLibrary:
    return GrammarLibrary(decl(), atoms())
