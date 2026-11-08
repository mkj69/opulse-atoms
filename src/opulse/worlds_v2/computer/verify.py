"""Invented operation evidence and promotion (spec sections 8, 9 and 15).

MUL is exhaustive over the documented 65,536 initial states. The separate
seeded check exercises nonzero memory and flags but does not widen that scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from opulse.atoms.library import checked_scope
from opulse.atoms.nodes import (
    Block,
    Blocks,
    Call,
    CondJump,
    Halt,
    Jump,
    Lit,
    Test,
    Var,
    from_json,
    length,
    references,
    to_json,
)
from opulse.atoms.values import Ok

from . import machine
from .machine import REGISTERS, State, contract_projection
from .reference import atoms as reference_atoms
from .runner import run

DECLARATION = Path(__file__).resolve().parents[4] / "worlds/decl/computer@1.json"
ARTIFACT = Path(__file__).parent / "data/mul.definition.json"
DOT_ARTIFACT = Path(__file__).parent / "data/dot2.definition.json"
REFERENCE_MUL = reference_atoms()["mul"][1]


def mul_program() -> Blocks:
    """Reset output; test counter before each add; leave counter at zero."""
    state = Var("s")
    counter = REGISTERS[2]
    return Blocks((), "init", (
        ("init", Block((("s", Call("write", (state, Lit(REGISTERS[0]), Lit(0)))),), Jump("test"))),
        ("test", Block((), CondJump(Test(Call("is_zero", (state, Lit(counter)))), "done", "body"))),
        ("body", Block((("s", Call("add", (state, Lit(REGISTERS[0]), Lit(REGISTERS[1])))),
                        ("s", Call("dec", (state, Lit(counter))))), Jump("test"))),
        ("done", Block((), Halt(state))),
    ))


def copy_program() -> Blocks:
    state = Var("s")
    return Blocks((), "copy", (("copy", Block(
        (("s", Call("write", (state, Lit(REGISTERS[0]),
                              Call("read", (state, Lit(REGISTERS[1])))))),), Halt(state))),))


def _require(condition: bool) -> None:
    """Fail a verification check explicitly (asserts vanish under ``python -O``)."""
    if not condition:
        raise ValueError("verification check failed")


def step_formula(a: int, b: int) -> int:
    return 4 + 5 * b


def fast_mul(state: State) -> tuple[State, int]:
    """Closed form for a valid state, including exact layer-0 costs and flags."""
    a, b = state.regs[1:3]
    return (State(((a * b) & 255, a, 0, state.regs[3]), state.mem,
                  state.zero if b == 0 else True,
                  state.carry if b == 0 else False), step_formula(a, b))


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def world_hash() -> str:
    return json.loads(DECLARATION.read_text())["lock"]["world_hash"]


def deps_hash(names: list[str]) -> str:
    digests = json.loads(DECLARATION.read_text())["lock"]["host_digests"]
    return _hash({name: (_hash(json.loads(ARTIFACT.read_text())) if name == "MUL"
                         else digests.get(name, "Blocks/Jump")) for name in names})


def body_hash(body: dict, dependencies: list[str]) -> str:
    """Bind a serialized body to the current dependency identities."""
    return _hash({"body": body, "deps_hash": deps_hash(dependencies)})


def _checked_for(name: str, scope: dict) -> dict:
    from itertools import product

    if name == "MUL":
        domain = product(range(256), repeat=2)
    elif name == "COPY":
        domain = ((byte,) for byte in range(256))
    elif name == "DOT2":
        bound = scope.get("bound")
        if type(bound) is not int or not 1 <= bound <= 16:
            raise ValueError("invalid DOT2 bound")
        domain = product(range(bound), repeat=4)
    else:
        raise ValueError("unknown computer definition")
    return checked_scope(tuple(domain))


def _fields(state: State) -> dict:
    return {"r0": state.regs[0], "r1": state.regs[1], "r2": state.regs[2],
            "r3": state.regs[3], "mem": state.mem, "zero": state.zero, "carry": state.carry}


def _check(state: State, program: Blocks) -> tuple[State, int, set[str]]:
    actual = run(program, {"s": state}, record_trace=False)
    expected, steps = fast_mul(state)
    _require(isinstance(actual.outcome, Ok) and actual.outcome.value == expected)
    _require(actual.final_state == expected and actual.steps == steps)
    _require(expected.regs[0] == (state.regs[1] * state.regs[2]) & 255)
    _require(contract_projection(expected) == contract_projection(REFERENCE_MUL(state)))
    _require(expected.regs[1] == state.regs[1] and expected.regs[3] == state.regs[3])
    _require(expected.mem == state.mem)
    return expected, steps, {key for key, value in _fields(state).items() if _fields(expected)[key] != value}


def verify_mul(*, exhaustive: bool = True, seed: int = 709, samples: int = 128) -> dict:
    """Construct evidence; non-exhaustive mode is for quick tests, never promotion."""
    program = mul_program()
    changed: set[str] = set()
    total = 0
    minimum = 10**9
    maximum = 0
    pairs = ((a, b) for a in range(256) for b in range(256)) if exhaustive else (
        (a, b) for a in (0, 1, 255, 127) for b in (0, 1, 2, 3, 255))
    count = 0
    for a, b in pairs:
        _, steps, differences = _check(State((0, a, b, 0)), program)
        changed.update(differences)
        minimum = min(minimum, steps)
        maximum = max(maximum, steps)
        total += steps
        count += 1
    randomizer = random.Random(seed)
    for _ in range(samples):
        state = State(tuple(randomizer.randrange(256) for _ in range(4)),
                      randomizer.randbytes(256), bool(randomizer.getrandbits(1)),
                      bool(randomizer.getrandbits(1)))
        changed.update(_check(state, program)[2])
    dependencies = sorted(references(program)) + ["jump"]
    record = {
        "id": "computer@1/MUL", "name": "MUL", "kind": "operation",
        "origin": "invented", "layer": 1, "depends_on": dependencies,
        "spec": {"kind": "operation", "name": "MUL", "role": "act",
                 "inputs": [{"name": "s", "sort": "machine_state", "enter": "bottom"}],
                 "output": {"sort": "machine_state", "enter": "bottom"},
                 "rule": "Set r0 to (initial r1 * initial r2) mod 256 by repeated addition; consume r2.",
                 "errors": ["invalid"], "cost": None, "strict": True, "reads_params": []},
        "body": to_json(program),
        "evidence": {
            "method": "exhaustive" if exhaustive else "sampled",
            "scope": {"domain": "byte x byte", "size": count,
                      "checked": (_checked_for("MUL", {}) if exhaustive else
                                  checked_scope(tuple((first, second)
                                                      for first in (0, 1, 255, 127)
                                                      for second in (0, 1, 2, 3, 255)))),
                      "description": "(r1, r2) over all pairs; r0 = r3 = 0, mem zero, flags false; full machine state compared"
                      if exhaustive else "quick subset; not exhaustive"},
            "seed": None if exhaustive else seed,
            "checks": ["reference", "contract", "unfold_equivalence", "step_formula"],
            "world_hash": world_hash(), "deps_hash": deps_hash(dependencies),
            "content_hash": body_hash(to_json(program), dependencies),
            "extra": [{"method": "sampled", "seed": seed, "size": samples,
                       "description": "Random r0, r3, memory and flags; full state and steps compared"}],
        },
        "contract": {"guarantees": "r0 = initial r1 * initial r2 mod 256",
                     "may_change": sorted(changed), "keeps": ["r1", "r3", "mem"]},
        "cost": {"length": length(program),
                 "steps": {"min": minimum, "max": maximum, "mean": total / count,
                           "formula": "4 + 5 * initial_r2", "over": "verification scope"},
                 "reuse": 0},
        "status": "verified" if exhaustive else "callable",
    }
    return promote(record) if exhaustive else record


def promote(definition: dict) -> dict:
    evidence = definition.get("evidence")
    if (not evidence or evidence.get("method") not in ("exhaustive", "bounded")
            or evidence.get("world_hash") != world_hash()
            or evidence.get("deps_hash") != deps_hash(definition.get("depends_on", []))
            or evidence.get("content_hash") != body_hash(definition.get("body"), definition.get("depends_on", []))
            or evidence.get("failed_checks")
            or not {"reference", "contract", "unfold_equivalence", "step_formula"}.issubset(evidence.get("checks", ()))
            or not definition.get("contract") or definition.get("status") != "verified"):
        raise ValueError("insufficient evidence for promotion")
    program = from_json(definition["body"])
    _require(isinstance(program, Blocks))
    name = definition.get("name")
    scope = evidence["scope"]
    _require(scope.get("checked") == _checked_for(definition.get("name"), scope))
    extra = evidence.get("extra", ())
    seed = extra[0].get("seed") if name == "MUL" and extra else 709
    _require(type(seed) is int)
    randomizer = random.Random(seed)
    if name == "MUL":
        _require(evidence["method"] == "exhaustive" and scope["size"] == 65536
                 and sorted(definition["depends_on"]) == sorted(references(program) | {"jump"}))
        for first, second in [(0, 0), (255, 255), (3, 2)] + [
                (randomizer.randrange(256), randomizer.randrange(256)) for _ in range(8)]:
            _check(State((0, first, second, 0)), program)
        for _ in range(4):
            state = State(tuple(randomizer.randrange(256) for _ in range(4)),
                          randomizer.randbytes(256), bool(randomizer.getrandbits(1)),
                          bool(randomizer.getrandbits(1)))
            _check(state, program)
    elif name == "COPY":
        _require(evidence["method"] == "exhaustive" and scope["size"] == 256
                 and sorted(definition["depends_on"]) == sorted(references(program)))
        for byte in [0, 255] + [randomizer.randrange(256) for _ in range(8)]:
            state = State((0, byte, 0, 0))
            actual = run(program, {"s": state}, record_trace=False)
            expected = machine.write(state, REGISTERS[0], byte)
            _require(isinstance(actual.outcome, Ok) and actual.outcome.value == actual.final_state == expected
                     and actual.steps == 2)
    elif name == "DOT2":
        bound = scope["bound"]
        _require(evidence["method"] == "bounded" and type(bound) is int and 1 <= bound <= 16
                 and scope["size"] == bound ** 4
                 and sorted(definition["depends_on"]) == sorted(references(program)))
        for cells in [(0, 0, 0, 0), (bound - 1,) * 4] + [
                tuple(randomizer.randrange(bound) for _ in range(4)) for _ in range(8)]:
            _check_dot2(program, cells)
    else:
        raise ValueError("unknown computer definition")
    return {**definition, "status": "promoted"}


def core_definition(record: dict):
    """Adapt the original computer evidence shape to the core Definition schema."""
    from opulse.atoms.spec import Definition

    data = json.loads(json.dumps(record))
    data["schema"] = "opulse.definition/2"
    data["spec"].pop("kind", None)
    for edge in data["spec"]["inputs"]:
        edge.pop("name", None)
    if data["spec"].get("cost") is None:
        data["spec"]["cost"] = 1
    data["evidence"].pop("extra", None)
    data["depends_on"] = [name for name in data["depends_on"] if name != "jump"]
    return Definition.from_dict(data)


def derived_computer(record: dict):
    """Promote against the locked world; its host-object syntax predates core codecs."""
    from opulse.atoms.world import DerivedWorld, WorldDecl

    class LockedComputerWorld(WorldDecl):
        def world_hash(self) -> str:
            return world_hash()

    base = LockedComputerWorld("computer", 1, "atoms-v2", {}, {}, (), (),
                               {"nodes": ["Blocks"], "recursion": "measure"}, {}, {})
    definition = core_definition(record)
    if (not record.get("evidence") or record["evidence"].get("deps_hash") !=
            deps_hash(record.get("depends_on", []))):
        raise ValueError("stale dependency evidence")
    if record["evidence"]["scope"].get("checked") != _checked_for(record["name"],
                                                                   record["evidence"]["scope"]):
        raise ValueError("stale checked scope")
    return DerivedWorld.build(base, (definition,))


def verify_copy() -> dict:
    """A second invented operation: r0 := r1; exhaustive over all byte inputs."""
    program = copy_program()
    for byte in range(256):
        state = State((0, byte, 0, 0))
        result = run(program, {"s": state})
        _require(isinstance(result.outcome, Ok) and result.outcome.value.regs == (byte, byte, 0, 0))
        _require(result.steps == 2 and result.final_state == State((byte, byte, 0, 0)))
    return {"id": "computer@1/COPY", "name": "COPY", "kind": "operation",
            "origin": "invented", "layer": 1, "depends_on": ["read", "write"],
            "spec": {"kind": "operation", "name": "COPY", "role": "act",
                     "inputs": [{"name": "s", "sort": "machine_state", "enter": "bottom"}],
                     "output": {"sort": "machine_state", "enter": "bottom"},
                     "rule": "Set r0 to the old r1; preserve all other fields.",
                     "errors": ["invalid"], "cost": None, "strict": True, "reads_params": []},
            "body": to_json(program), "evidence": {"method": "exhaustive",
            "scope": {"domain": "byte", "size": 256,
                      "checked": _checked_for("COPY", {}),
                      "description": "r1 over all bytes; r0 = r2 = r3 = 0, mem zero, flags false; full state compared"}, "seed": None,
            "checks": ["reference", "contract", "unfold_equivalence", "step_formula"],
            "world_hash": world_hash(), "deps_hash": deps_hash(["read", "write"]),
            "content_hash": body_hash(to_json(program), ["read", "write"])},
            "contract": {"guarantees": "r0 = initial r1", "may_change": ["r0"],
                         "keeps": ["r1", "r2", "r3", "mem", "zero", "carry"]},
            "cost": {"length": length(program), "steps": {"min": 2, "max": 2, "mean": 2,
                      "over": "verification scope"}, "reuse": 0}, "status": "verified"}


def dot2_program() -> Blocks:
    """r0 := (mem[0]*mem[1] + mem[2]*mem[3]) mod 256."""
    state = Var("s")
    return Blocks((("saved", Lit(0)),), "dot", (("dot", Block((
        ("s", Call("load", (state, Lit(REGISTERS[1]), Lit(0)))),
        ("s", Call("load", (state, Lit(REGISTERS[2]), Lit(1)))),
        ("s", Call("MUL", (state,))),
        ("saved", Call("read", (state, Lit(REGISTERS[0])))),
        ("s", Call("write", (state, Lit(REGISTERS[3]), Var("saved")))),
        ("s", Call("load", (state, Lit(REGISTERS[1]), Lit(2)))),
        ("s", Call("load", (state, Lit(REGISTERS[2]), Lit(3)))),
        ("s", Call("MUL", (state,))),
        ("s", Call("add", (state, Lit(REGISTERS[0]), Lit(REGISTERS[3])))),
    ), Halt(state))),))


def _check_dot2(program: Blocks, cells: tuple[int, int, int, int]) -> int:
    from .kernel_scope import run_kernel

    initial = State(mem=bytes(cells) + bytes(252))
    actual = run_kernel(program, initial, defs={"MUL": mul_program()})
    _require(isinstance(actual.outcome, Ok))
    result = actual.outcome.value
    first, _ = fast_mul(machine.load(machine.load(initial, REGISTERS[1], 0), REGISTERS[2], 1))
    saved = machine.write(first, REGISTERS[3], machine.read(first, REGISTERS[0]))
    second, _ = fast_mul(machine.load(machine.load(saved, REGISTERS[1], 2), REGISTERS[2], 3))
    expected = machine.add(second, REGISTERS[0], REGISTERS[3])
    _require(result == actual.final_state == expected and result.regs[0] ==
             (cells[0] * cells[1] + cells[2] * cells[3]) % 256)
    _require(actual.steps == 15 + 5 * (cells[1] + cells[3]))
    return actual.steps


def verify_dot2(*, bound: int = 8) -> dict:
    """Bounded exhaustive verification on all four memory cells in [0, bound)."""
    from itertools import product

    if not 1 <= bound <= 16:
        raise ValueError("bound must be between 1 and 16")
    program = dot2_program()
    steps = []
    for cells in product(range(bound), repeat=4):
        steps.append(_check_dot2(program, cells))
    dependencies = sorted(references(program))
    return {
        "schema": "opulse.definition/2", "id": "computer@1/DOT2", "name": "DOT2",
        "kind": "operation", "origin": "invented", "layer": 2,
        "depends_on": dependencies,
        "spec": {"name": "DOT2", "role": "act",
                 "inputs": [{"sort": "machine_state", "enter": "bottom"}],
                 "output": {"sort": "machine_state", "enter": "bottom"},
                 "rule": "Set r0 to (mem[0]*mem[1] + mem[2]*mem[3]) mod 256.",
                 "errors": ["invalid"], "cost": 1, "strict": True, "reads_params": []},
        "body": to_json(program),
        "evidence": {"method": "bounded", "scope": {
            "domain": "mem[0:4] in [0, bound); all other bytes and registers zero",
            "size": bound ** 4, "bound": bound,
            "checked": _checked_for("DOT2", {"bound": bound}),
            "description": "Full final state and projected arithmetic checked for every four-tuple"},
            "seed": None, "checks": ["reference", "contract", "unfold_equivalence", "step_formula"],
            "world_hash": world_hash(), "deps_hash": deps_hash(dependencies),
            "content_hash": body_hash(to_json(program), dependencies)},
        "contract": {"guarantees": "r0 = (mem[0]*mem[1] + mem[2]*mem[3]) mod 256",
                     "may_change": ["r0", "r1", "r2", "r3", "zero", "carry"],
                     "keeps": ["mem"]},
        "cost": {"length": length(program), "steps": {
            "min": min(steps), "max": max(steps), "mean": sum(steps) / len(steps),
            "over": "verification scope"}, "reuse": 2},
        "status": "verified",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    definition = verify_mul()
    if args.write:
        ARTIFACT.write_text(json.dumps(definition, indent=2, ensure_ascii=False) + "\n")
    dot2 = verify_dot2()
    if args.write:
        DOT_ARTIFACT.write_text(json.dumps(dot2, indent=2, ensure_ascii=False) + "\n")
    print(f"MUL {definition['status']}: {definition['evidence']['scope']['size']} pairs; DOT2 {dot2['status']}")
