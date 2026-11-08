"""Atom digests are pure functions of the code: no absolute path or memory address enters them.

The core atoms_digest hashes each atom's code, closure cell reprs and defaults. A module object
or an object with a default repr in a closure puts a file path or an address into the hash, so
the same commit gives different evidence hashes in different checkouts or processes.
"""

import re
from pathlib import Path
from types import CodeType

import pytest

from opulse.meta.vn import machine
from opulse.meta.worlds.builder import hosts as builder_hosts
from opulse.meta.worlds.code import hosts as code_hosts
from opulse.meta.worlds.compiler.world import make_library

ROOT = str(Path(__file__).resolve().parents[2])
ADDRESS = re.compile(r"at 0x[0-9a-f]+")


def _code_value(code: CodeType):
    return (code.co_code.hex(), tuple(_code_value(item) if isinstance(item, CodeType) else repr(item)
                                      for item in code.co_consts), code.co_names)


def _digest_inputs(atom) -> list[str]:
    fn = atom.fn
    parts = [repr(cell.cell_contents) for cell in (getattr(fn, "__closure__", None) or ())]
    if hasattr(fn, "__code__"):
        parts.append(repr(_code_value(fn.__code__)))
    parts.append(repr(getattr(fn, "__defaults__", None)))
    return parts


@pytest.mark.parametrize("world, atoms", [
    ("builder", lambda: builder_hosts.atoms()),
    ("code", lambda: code_hosts.atoms()),
    ("compiler", lambda: make_library().atoms),
    ("vonneumann", lambda: machine.atoms(32)),
])
def test_atom_digest_inputs_hold_no_path_or_address(world, atoms):
    for atom in atoms():
        for part in _digest_inputs(atom):
            assert ROOT not in part, (world, atom.name, part[:200])
            assert not ADDRESS.search(part), (world, atom.name, part[:200])
