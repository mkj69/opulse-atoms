"""Evidence tied to exact routine bytes and world hashes (atoms-meta 4.3)."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from itertools import product

from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import Ok, outcome_equal
from opulse.meta.vn import machine, reference
from opulse.meta.vn.report import routine_id


@dataclass(frozen=True)
class Routine:
    base: int
    code: tuple[int, ...]


@dataclass(frozen=True)
class RoutineDomain:
    """An enumerated product with a declared state builder (atoms-meta 8)."""

    name: str
    axes: tuple[tuple[int, ...], ...]
    build: object

    @classmethod
    def product(cls, name, axes, build):
        return cls(name, tuple(tuple(axis) for axis in axes), build)

    def enumerate(self):
        if not self.axes or any(not axis or len(set(axis)) != len(axis) for axis in self.axes):
            raise ValueError("invalid domain axes")
        return tuple(self.build(values) for values in product(*self.axes))


def _changed_stores(state, fuel):
    changed = set()
    for _ in range(fuel):
        if state.halted:
            break
        if state.mem[state.pc] == 3:
            address = state.mem[(state.pc + 1) % len(state.mem)] % len(state.mem)
            if state.mem[address] != state.a:
                changed.add(address)
        state = reference.step(state)
    return changed


class RoutineLedger:
    def __init__(self, world):
        self.world_hash = world.world_hash()
        self.n = world.params["n"]
        self._records = {}

    def identity(self, routine):
        return routine_id(self.n, routine.base, routine.code)

    def record(self, routine):
        return deepcopy(self._records.get((self.identity(routine), self.world_hash)))

    def verify(self, routine, domain, reference_result, *, method="exhaustive", fuel=100,
               claimed_size=None, reset=None, reset_addresses=(), description=None):
        """Compare entire final states and exact instruction counts for every input."""
        if not isinstance(domain, RoutineDomain):
            raise TypeError("routine needs a declared domain generator")
        if method not in ("exhaustive", "bounded"):
            raise ValueError("routine needs an exhaustive or bounded product")
        scope = domain.enumerate()
        if claimed_size is not None and claimed_size != len(scope):
            raise ValueError("claimed size differs from enumerated size")
        if len(set(scope)) != len(scope):
            raise ValueError("domain generates duplicate starting states")
        if reset is not None and (not reset_addresses or any(type(address) is not int or
                address < 0 or address >= self.n for address in reset_addresses)):
            raise ValueError("invalid reset addresses")
        changed = set()
        for initial in scope:
            if not isinstance(initial, reference.State) or len(initial.mem) != self.n or \
                    tuple(initial.mem[routine.base:routine.base + len(routine.code)]) != routine.code:
                raise ValueError("scope state does not contain the routine")
            actual = machine.run(machine.to_card(initial), fuel)
            expected = reference_result(initial, fuel)
            if not isinstance(actual.outcome, Ok) or not isinstance(expected[0], reference.State) or \
                    not outcome_equal(actual.outcome, Ok(machine.to_card(expected[0]))) or actual.steps != expected[1]:
                raise ValueError("routine counterexample: full final state or steps differ")
            changed.update(_changed_stores(initial, fuel))
            if len(expected) != 2:
                raise ValueError("second call must be derived from a declared reset")
            if reset is not None:
                second_start = reset(expected[0])
                if not isinstance(second_start, reference.State) or \
                        second_start.pc != routine.base or second_start.a != 0 or second_start.halted or \
                        any(second_start.mem[address] != expected[0].mem[address]
                            for address in range(self.n) if address not in reset_addresses) or \
                        tuple(second_start.mem[routine.base:routine.base + len(routine.code)]) != routine.code:
                    raise ValueError("second call changes undeclared bytes or routine identity")
                second_status, second_final, second_steps = reference.run(second_start, fuel)
                if second_status != "ok" or not outcome_equal(machine.run(machine.to_card(second_start), fuel).outcome,
                                     Ok(machine.to_card(second_final))) or \
                        machine.run(machine.to_card(second_start), fuel).steps != second_steps:
                    raise ValueError("second call full final state or steps differ")
                changed.update(_changed_stores(second_start, fuel))
        fingerprint = sha256(json.dumps(sorted((state.pc, state.a, state.mem, state.halted)
                                               for state in scope)).encode("ascii")).hexdigest()
        evidence = Evidence(method, {"domain": {"product_axes": [list(axis) for axis in domain.axes]},
                                     "size": len(scope), "fuel": fuel,
                                     "inputs_sha256": fingerprint, "reset_addresses": list(reset_addresses)},
                            checks=("full_state", "steps") + (("consecutive_calls",) if reset else ()),
                            world_hash=self.world_hash, atoms_hash=machine.atoms_hash(self.n))
        key = (self.identity(routine), self.world_hash)
        if key in self._records:
            raise ValueError("routine evidence is immutable")
        self._records[key] = (deepcopy(evidence), frozenset(changed), None)
        return deepcopy(evidence)

    def promote(self, routine, contract):
        key = (self.identity(routine), self.world_hash)
        if key not in self._records or self._records[key][2] is not None:
            raise ValueError("routine needs unpromoted evidence")
        evidence, changed, _ = self._records[key]
        if evidence.atoms_hash != machine.atoms_hash(self.n):
            raise ValueError("routine atoms hash changed")
        if not isinstance(contract, Contract) or any(type(item) is not str or not item.isdecimal()
                                                     for item in contract.may_change) or \
                not changed <= {int(item) for item in contract.may_change}:
            raise ValueError("contract omits a changed address")
        self._records[key] = (evidence, changed, contract)
        return deepcopy(self._records[key])
