import json
from dataclasses import dataclass
from pathlib import Path

from .ops import MAX_NAT  # noqa: F401 - re-exported


@dataclass(frozen=True)
class OpSpec:
    name: str
    inputs: tuple[str, ...]
    output: str
    rule: str
    errors: str
    cost: int = 1

    def to_json(self):
        return {"name": self.name, "inputs": list(self.inputs), "output": self.output,
                "rule": self.rule, "errors": self.errors, "cost": self.cost}


SPECS = (
    OpSpec("add", ("nat", "nat"), "nat", "a + b", "overflow if > 1000000000"),
    OpSpec("sub", ("nat", "nat"), "nat", "a - b", "negative if a < b"),
    OpSpec("succ", ("nat",), "nat", "a + 1", "overflow if > 1000000000"),
    OpSpec("pred", ("nat",), "nat", "a - 1", "negative if a = 0"),
    OpSpec("is_zero", ("nat",), "bool", "a = 0", "none"),
    OpSpec("eq", ("nat", "nat"), "bool", "a = b", "none"),
    OpSpec("lt", ("nat", "nat"), "bool", "a < b", "none"),
    OpSpec("mul", ("nat", "nat"), "nat", "a * b", "overflow if > 1000000000"),
)


@dataclass(frozen=True)
class World:
    name: str
    group: str
    operations: dict[str, OpSpec]
    library_enabled: bool

    def to_json(self):
        return {"world": self.name, "version": 1, "objects": ["nat", "bool"],
                "open_kinds": ["operation"],
                "operations": [op.to_json() for op in self.operations.values()],
                "combinators": ["var", "lit", "call", "let", "if", "rec"],
                "observation": "inputs_results_errors_steps", "library": self.library_enabled}


def load_world(group: str) -> World:
    if group not in ("A", "B", "C"):
        raise ValueError(f"unknown world group {group!r}")
    operations = SPECS if group == "A" else SPECS[:-1]
    return World(f"atoms_mul_{group}", group, {spec.name: spec for spec in operations}, group != "C")


def write_worlds(dir):
    directory = Path(dir)
    directory.mkdir(parents=True, exist_ok=True)
    for group in "ABC":
        (directory / f"{group}.json").write_text(
            json.dumps(load_world(group).to_json(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
