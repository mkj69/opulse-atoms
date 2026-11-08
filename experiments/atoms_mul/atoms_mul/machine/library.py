"""Persistent invented MASM definitions."""

import json
from dataclasses import asdict, dataclass

from opulse.atoms.nodes import to_json

from .check import calls
from .compile import compile_sub, format_sub, size


@dataclass
class Definition:
    name: str
    kind: str = "operation"
    origin: str = "invented"
    layer: int = 1
    depends_on: tuple = ()
    params: tuple = ("s",)
    body: dict | None = None
    evidence: dict | None = None
    cost: dict | None = None
    status: str = "callable"
    created_task: str = ""
    source: str | None = None


class Library:
    def __init__(self):
        self._entries = {}

    def names(self):
        return list(self._entries)

    def get(self, name):
        return self._entries.get(name)

    def listing(self):
        return "\n".join(entry.source if entry.source is not None else
                         f"sub {entry.name}:\n  # Blocks: " + json.dumps(entry.body, sort_keys=True) + "\nend"
                         for entry in self._entries.values())

    def add_from_program(self, program, names, task_id):
        defs = {sub.name: sub for sub in program.defs}
        added = []
        layers = {}

        def layer(name):
            if name in layers:
                return layers[name]
            dependencies = calls(defs[name])
            layers[name] = 1 + max((layer(dep) if dep in defs else self._entries[dep].layer
                                    for dep in dependencies if dep in defs or dep in self._entries),
                                   default=0)
            return layers[name]

        for name in names:
            sub = defs[name]
            operations = {"set": "write", "add": "add", "dec": "dec", "load": "load",
                          "store": "store", "mul": "mul", "jz": "is_zero", "jnz": "is_zero"}
            deps = set(calls(sub)) | {operations[line.op] for line in sub.lines if line.op in operations}
            if any(line.op in ("jmp", "jz", "jnz", "label") for line in sub.lines):
                deps.add("jump")
            entry = Definition(name=name, layer=layer(name), depends_on=tuple(sorted(deps)),
                               body=to_json(compile_sub(sub)), cost={"size": size(sub), "length": size(sub)},
                               created_task=task_id)
            self._entries[name] = entry
            entry.source = format_sub(sub)
            added.append(entry)
        return added

    def to_json(self):
        return [asdict(entry) for entry in self._entries.values()]

    @classmethod
    def from_json(cls, data):
        library = cls()
        for item in data:
            entry = Definition(**{**item, "depends_on": tuple(item["depends_on"]),
                                  "params": tuple(item["params"])})
            library._entries[entry.name] = entry
        return library
