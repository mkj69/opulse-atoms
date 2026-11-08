"""Execution reports and routine identities (docs/spec/atoms-meta.md, section 4.3)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.meta.vn import reference
from opulse.meta.vn.machine import from_card, run, to_card


@dataclass(frozen=True)
class Image:
    name: str
    identity: str
    bytes: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Report:
    fetched: frozenset[int]
    stores: tuple[tuple[int, int, int, int], ...]
    versions: tuple[Image, ...]
    self_modifying: bool
    writes_ahead: bool
    writes_behind: bool
    outcome: Ok | Bottom | Unknown


def _identity(n: int, payload: object) -> str:
    encoding = f"opulse.vn/1\n{n}\n{json.dumps(payload, separators=(',', ':'))}"
    return hashlib.sha256(encoding.encode("ascii")).hexdigest()


def routine_id(n: int, base: int, bytes: list[int] | tuple[int, ...]) -> str:
    if n not in reference.SIZES or type(base) is not int or not 0 <= base < n or any(
            type(byte) is not int or not 0 <= byte < 256 for byte in bytes):
        raise ValueError("invalid routine")
    return _identity(n, [base, list(bytes)])


def report(state: reference.State | object, fuel: int) -> Report:
    """Record instruction fetches and changed code images over a fuel-bounded run."""
    if not isinstance(state, reference.State):
        state = from_card(state)
    if type(fuel) is not int or fuel < 0:
        raise ValueError("invalid fuel")
    current = state
    events = []
    stores = []
    for index in range(fuel):
        if current.halted:
            break
        pc = current.pc
        fetched = (pc, (pc + 1) % len(current.mem))
        opcode, operand = (current.mem[address] for address in fetched)
        store = None
        if opcode == 3:
            address = operand % len(current.mem)
            store = (index + 1, address, current.mem[address], current.a)
            stores.append(store)
        events.append((fetched, store))
        try:
            current = reference.step(current)
        except reference.Illegal:
            break
    fetched_all = frozenset(address for addresses, _ in events for address in addresses)
    fetched_before = set()
    changed = []
    writes_ahead = writes_behind = False
    for index, (addresses, store) in enumerate(events):
        fetched_before.update(addresses)
        if store is None or store[2] == store[3] or store[1] not in fetched_all:
            continue
        writes_behind |= store[1] in fetched_before
        writes_ahead |= any(store[1] in later for later, _ in events[index + 1:])
        changed.append(store)
    memory = list(state.mem)

    def image(number: int) -> Image:
        pairs = tuple((address, memory[address]) for address in sorted(fetched_all))
        return Image(f"C_{number}", _identity(len(memory), pairs), pairs)

    versions = [image(0)]
    for _, address, _, value in changed:
        memory[address] = value
        versions.append(image(len(versions)))
    outcome = run(to_card(state), fuel).outcome
    return Report(fetched_all, tuple(stores), tuple(versions), len(versions) > 1,
                  writes_ahead, writes_behind, outcome)
