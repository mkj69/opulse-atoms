"""World declaration IO and locks (docs/spec/atoms-v2.md, sections 4–7, 12).

WorldFile will be converted to opulse.atoms.world.WorldDecl when that module lands.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

from opulse.tasks_v2.task import KINDS


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _host_source(reference: str) -> str:
    module_name, separator, qualname = reference.partition(":")
    if not separator or not module_name or not qualname:
        raise ValueError(f"invalid host reference {reference!r}")
    value = importlib.import_module(module_name)
    for part in qualname.split("."):
        value = getattr(value, part)
    if not callable(value):
        raise TypeError(f"host {reference!r} is not callable")
    return inspect.getsource(value)


def host_digest(reference: str) -> str:
    return hashlib.sha256(_host_source(reference).encode("utf-8")).hexdigest()


def nonnegative(value: int) -> bool:
    return value >= 0


def below_twelve(value: int) -> bool:
    return value < 12


def int_mod_twelve(value: int) -> int:
    return value % 12


@dataclass(frozen=True)
class Edge:
    sort: str
    enter: str
    name: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Edge:
        return cls(data["sort"], data["enter"], data.get("name"))

    def to_dict(self) -> dict:
        return {**({"name": self.name} if self.name is not None else {}),
                "sort": self.sort, "enter": self.enter}


@dataclass(frozen=True)
class ObjectDecl:
    name: str
    form: str
    base: str | None = None
    tags: dict | None = None
    group: list = field(default_factory=list)
    valid: object = None
    canon: object = None
    sealed: bool = False
    interface: list = field(default_factory=list)
    params: list = field(default_factory=list)
    equality: str = "canonical"
    canon_cost: str = "counted"
    body: object = None
    host: dict | None = None
    doc: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> ObjectDecl:
        return cls(**{key: value for key, value in data.items() if key != "kind"})

    def to_dict(self) -> dict:
        return {"kind": "object", **vars(self)}


@dataclass(frozen=True)
class OperationDecl:
    name: str
    symbol: str | None
    role: str
    inputs: tuple[Edge, ...]
    output: Edge
    rule: str
    errors: list[str]
    impl: dict | None
    cost: int
    strict: bool
    reads_params: list[str]

    @classmethod
    def from_dict(cls, data: dict) -> OperationDecl:
        return cls(data["name"], data.get("symbol"), data["role"],
                   tuple(Edge.from_dict(edge) for edge in data["inputs"]),
                   Edge.from_dict(data["output"]), data["rule"], data["errors"],
                   data["impl"], data["cost"], data["strict"], data["reads_params"])

    def to_dict(self) -> dict:
        return {"kind": "operation", "name": self.name, "symbol": self.symbol,
                "role": self.role, "inputs": [edge.to_dict() for edge in self.inputs],
                "output": self.output.to_dict(), "rule": self.rule,
                "errors": self.errors, "impl": self.impl, "cost": self.cost,
                "strict": self.strict, "reads_params": self.reads_params}


@dataclass(frozen=True)
class Probe:
    name: str
    sort: str
    reads: str
    reveals: list[str]
    impl: dict | None

    @classmethod
    def from_dict(cls, data: dict) -> Probe:
        return cls(**data)

    def to_dict(self) -> dict:
        return dict(vars(self))


@dataclass(frozen=True)
class WorldFile:
    schema: str
    world: str
    version: int
    dialect: str
    title: str
    source: dict
    params: dict
    constants: dict
    objects: tuple[ObjectDecl, ...]
    operations: tuple[OperationDecl, ...]
    combinators: dict
    observation: dict
    codec: dict
    lock: dict
    extra: dict = field(default_factory=dict)  # other top-level members (title_zh, open_kinds, tags), kept verbatim

    @classmethod
    def from_dict(cls, data: dict) -> WorldFile:
        known = {item.name for item in fields(cls)} - {"extra"}
        return cls(**{key: value for key, value in data.items() if key in known - {"objects", "operations"}},
                   objects=tuple(ObjectDecl.from_dict(item) for item in data["objects"]),
                   operations=tuple(OperationDecl.from_dict(item) for item in data["operations"]),
                   extra={key: value for key, value in data.items() if key not in known})

    def to_dict(self) -> dict:
        data = {key: value for key, value in vars(self).items() if key not in ("extra", "lock")}
        data.update(objects=[item.to_dict() for item in self.objects],
                    operations=[item.to_dict() for item in self.operations])
        return {**data, **self.extra, "lock": self.lock}

    @property
    def probes(self) -> tuple[Probe, ...]:
        return tuple(Probe.from_dict(item) for item in self.observation.get("probes", []))


def load(path: str | Path) -> WorldFile:
    return WorldFile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_all(directory: str | Path = "worlds/decl") -> list[WorldFile]:
    return [load(path) for path in sorted(Path(directory).glob("*.json"))]


def find(world: str, version: int, directory: str | Path = "worlds/decl") -> WorldFile:
    return load(Path(directory) / f"{world}@{version}.json")


def _host_entries(world_file: WorldFile):
    for operation in world_file.operations:
        if isinstance(operation.impl, dict) and "host" in operation.impl:
            yield operation.name, operation.impl
    for obj in world_file.objects:
        for field_name in ("valid", "canon"):
            value = getattr(obj, field_name)
            if isinstance(value, dict) and "host" in value:
                yield f"{obj.name}.{field_name}", value
    for probe in world_file.probes:
        if isinstance(probe.impl, dict) and "host" in probe.impl:
            yield f"probe.{probe.name}", probe.impl


def compute_lock(world_file: WorldFile) -> dict:
    from opulse.atoms.world import WorldDecl

    lock = {"host_digests": {name: host_digest(entry["host"]) for name, entry in _host_entries(world_file)},
            "constants_hash": _hash(world_file.constants)}
    # The core hash leaves out display-only members (title, docs, symbols), spec section 12.
    lock["world_hash"] = WorldDecl.from_dict({**world_file.to_dict(), "lock": dict(lock)}).world_hash()
    return lock


def write_locks(directory: str | Path = "worlds/decl") -> None:
    for path in sorted(Path(directory).glob("*.json")):
        data = load(path).to_dict()
        for operation in data["operations"]:
            implementation = operation.get("impl")
            if isinstance(implementation, dict) and "host" in implementation:
                implementation["digest"] = host_digest(implementation["host"])
        for obj in data["objects"]:
            for field_name in ("valid", "canon"):
                implementation = obj.get(field_name)
                if isinstance(implementation, dict) and "host" in implementation:
                    implementation["digest"] = host_digest(implementation["host"])
        for probe in data["observation"].get("probes", []):
            implementation = probe.get("impl")
            if isinstance(implementation, dict) and "host" in implementation:
                implementation["digest"] = host_digest(implementation["host"])
        data["lock"] = compute_lock(WorldFile.from_dict(data))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_ENTER = re.compile(r"(?:bottom|normalize|saturate\(-?\d+,-?\d+\)|fold\([a-zA-Z_][\w-]*\))\Z")
_NODE_NAMES = frozenset(("Var", "Lit", "Call", "Let", "Case", "Rec", "Blocks",
                         "Jump", "CondJump", "Halt", "Test", "And", "Or", "Not", "Always"))


def validate(world_file: WorldFile) -> list[str]:
    problems: list[str] = []
    if world_file.schema != "opulse.world/2":
        problems.append(f"schema: expected opulse.world/2, got {world_file.schema!r}")
    if world_file.dialect not in ("legacy-v1", "atoms-v2"):
        problems.append(f"dialect: unknown {world_file.dialect!r}")
    names = {obj.name for obj in world_file.objects}
    operations = {op.name for op in world_file.operations}
    probes = world_file.probes
    for label, values in (("object", [obj.name for obj in world_file.objects]),
                          ("operation", [op.name for op in world_file.operations]),
                          ("probe", [probe.name for probe in probes])):
        if len(values) != len(set(values)):
            problems.append(f"duplicate {label} name")

    def check_sort(sort: str, context: str, parameters: frozenset[str] = frozenset()) -> None:
        if sort in names or sort in parameters:
            return
        root = sort.split("[", 1)[0]
        matching = next((item for item in world_file.objects
                         if item.name.split("[", 1)[0] == root and item.params), None)
        if root not in names and matching is None:
            problems.append(f"{context}: unknown sort {sort!r}")
            return
        if "[" in sort:
            obj = next((item for item in world_file.objects if item.name == root), matching)
            arguments = sort[sort.index("[")+1:-1].split(",")
            if not obj.params or not sort.endswith("]") or len(arguments) != len(obj.params):
                problems.append(f"{context}: invalid static parameters {sort!r}")
            else:
                for argument, parameter in zip(arguments, obj.params):
                    if parameter.endswith(":int"):
                        if not (argument.isdigit() or argument in parameters or argument in world_file.params):
                            problems.append(f"{context}: static int parameter {argument!r} in {sort!r} is not an integer")
                    elif argument not in parameters:
                        check_sort(argument, context, parameters)

    for obj in world_file.objects:
        parameters = frozenset(param.split(":", 1)[0] for param in obj.params)
        if obj.form not in ("given", "compose", "refine", "constant"):
            problems.append(f"{obj.name}: unknown object form {obj.form!r}")
        if obj.form == "refine" and (not obj.base or obj.valid is None):
            problems.append(f"{obj.name}: refine needs base and valid")
        if obj.base:
            check_sort(obj.base, obj.name)
        for tag_fields in (obj.tags or {}).values():
            for sort in tag_fields.values():
                check_sort(sort, obj.name, parameters)
        if obj.sealed and (not obj.interface or any(name not in operations for name in obj.interface)):
            problems.append(f"{obj.name}: sealed interface must list declared operations")
    for op in world_file.operations:
        if op.role not in ("transform", "combine", "decide", "relate", "act"):
            problems.append(f"{op.name}: unknown role {op.role!r}")
        if not isinstance(op.rule, str) or not op.rule.strip():
            problems.append(f"{op.name}: rule must be non-empty")
        if len(set(op.errors)) != len(op.errors):
            problems.append(f"{op.name}: duplicate error reasons")
        if type(op.cost) is not int or op.cost <= 0:
            problems.append(f"{op.name}: cost must be a positive integer")
        for edge in (*op.inputs, op.output):
            check_sort(edge.sort, op.name)
            if not isinstance(edge.enter, str) or not _ENTER.fullmatch(edge.enter):
                problems.append(f"{op.name}: illegal enter {edge.enter!r}")
    open_kinds = world_file.extra.get("open_kinds")
    if open_kinds is not None and (not isinstance(open_kinds, list) or not open_kinds
                                   or set(open_kinds) - set(KINDS)):
        problems.append(f"open_kinds must be a non-empty subset of the six kinds, not {open_kinds!r}")
    truth = world_file.observation.get("truth")
    if truth is not None:
        check_sort(truth, "observation.truth")
    for probe in probes:
        check_sort(probe.sort, probe.name)
        if isinstance(probe.reads, str):
            check_sort(probe.reads, probe.name)
        else:
            problems.append(f"{probe.name}: reads must name a sort")
        if probe.reads != truth:
            problems.append(f"{probe.name}: reads must equal observation.truth")
    for node in world_file.combinators.get("nodes", []):
        if node not in _NODE_NAMES:
            problems.append(f"unknown combinator node {node!r}")
    for name, entry in _host_entries(world_file):
        try:
            actual = host_digest(entry["host"])
        except (AttributeError, ImportError, OSError, TypeError, ValueError) as error:
            problems.append(f"{name}: invalid host {entry['host']!r}: {error}")
            continue
        if entry.get("digest") != actual:
            problems.append(f"{name}: stale host digest")
    try:
        expected = compute_lock(world_file)
    except (AttributeError, ImportError, OSError, TypeError, ValueError) as error:
        problems.append(f"lock: invalid host: {error}")
    else:
        for key, value in expected.items():
            if world_file.lock.get(key) != value:
                problems.append(f"lock: stale {key}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or rewrite versioned world locks")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--lock", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--directory", default="worlds/decl")
    args = parser.parse_args()
    if args.lock:
        write_locks(args.directory)
        return 0
    problems = [f"{path}: {problem}" for path in sorted(Path(args.directory).glob("*.json"))
                for problem in validate(load(path))]
    for problem in problems:
        print(problem)
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
