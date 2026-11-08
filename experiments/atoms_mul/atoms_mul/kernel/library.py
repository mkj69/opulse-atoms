from dataclasses import asdict, dataclass, field

from .check import calls
from .nodes import Def, format_def, node_from_json, size


@dataclass
class Definition:
    name: str
    kind: str = "operation"
    origin: str = "invented"
    layer: int = 1
    depends_on: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    body: dict = field(default_factory=dict)
    evidence: dict | None = None
    cost: dict = field(default_factory=dict)
    status: str = "callable"
    created_task: str = ""
    param_sorts: tuple[str, ...] = ()
    result_sort: str = "Nat"


class Library:
    def __init__(self):
        self._entries = {}

    def add_from_program(self, program, names, task_id):
        definitions = {definition.name: definition for definition in program.defs}
        requested = list(names)
        if len(set(requested)) != len(requested):
            raise ValueError("duplicate saved name")
        if any(name not in definitions or name in self._entries or name == "solve" for name in requested):
            raise ValueError("cannot save an unknown or existing definition")
        for name in requested:
            if set(calls(definitions[name].body)) & (set(definitions) - set(requested)):
                raise ValueError(f"cannot save {name}: calls an unsaved definition")

        dependencies = {name: set(calls(definitions[name].body)) for name in requested}
        layers = {}

        def reachable(name):
            visited, pending = set(), [name]
            while pending:
                current = pending.pop()
                if current not in visited:
                    visited.add(current)
                    pending.extend(dependencies[current] & set(requested) - visited)
            return visited

        components = {name: frozenset(candidate for candidate in requested
                                      if name in reachable(candidate) and candidate in reachable(name))
                      for name in requested}

        def layer(name):
            if name in layers:
                return layers[name]
            component = components[name]
            external = set().union(*(dependencies[member] for member in component)) - component
            result = 1 + max((layer(dep) if dep in definitions else self._entries[dep].layer
                              for dep in external if dep in definitions or dep in self._entries), default=0)
            layers.update({member: result for member in component})
            return result

        added = []
        for name in requested:
            definition = definitions[name]
            entry = Definition(name=name, kind="operation", origin="invented",
                               layer=layer(name),
                               depends_on=tuple(sorted(dependencies[name])),
                               params=definition.params, body=definition.body.to_json(),
                               param_sorts=definition.param_sorts, result_sort=definition.result_sort,
                               evidence=None, cost={"size": size(definition),
                                     "length": size(definition) - 1 - len(definition.params)}, status="callable",
                               created_task=task_id)
            self._entries[name] = entry
            added.append(entry)
        return added

    def get(self, name):
        return self._entries.get(name)

    def names(self):
        return list(self._entries)

    def listing(self):
        return "\n".join(format_def(Def(entry.name, entry.params, node_from_json(entry.body),
                                        entry.param_sorts, entry.result_sort)) + f" L{entry.layer}"
                         for entry in self._entries.values())

    def to_json(self):
        return [asdict(entry) for entry in self._entries.values()]

    @classmethod
    def from_json(cls, data):
        library = cls()
        for item in data:
            entry = Definition(**{**item, "params": tuple(item["params"]),
                                  "param_sorts": tuple(item.get("param_sorts", ("Nat",) * len(item["params"]))),
                                  "depends_on": tuple(item["depends_on"])})
            if entry.name in library._entries:
                raise ValueError(f"duplicate library definition {entry.name}")
            library._entries[entry.name] = entry
        return library
