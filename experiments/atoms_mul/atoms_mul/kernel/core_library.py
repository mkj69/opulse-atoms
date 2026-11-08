"""Mirror saved AML definitions through the atoms-v2 definition pipeline.

The experiment evaluator remains the authority for grading; this module records
the same definitions in the core library and checks their unfoldings.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from atoms_mul.mirror_order import dependency_order
from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library, PipelineError, exhaustive
from opulse.atoms.spec import Contract, Definition, Edge, OperationSpec
from opulse.atoms.world import WorldDecl

from . import ops
from .core_backend import compile_node
from .nodes import node_from_json

MUTUAL_RECURSION = "mutual recursion is not representable in atoms-v2/0.2"
DECLARATIONS = Path(__file__).resolve().parents[2] / "worlds" / "decl"
HOST_MODULE = "atoms_mul.kernel.ops"


def mirror_sort(sort: str) -> str:
    return "int" if sort.lower() == "nat" else sort.lower()


def mirror_world(group: str) -> WorldDecl:
    declaration = load_decl(group)
    return replace(declaration, operations=tuple(
        replace(operation,
                inputs=tuple(replace(edge, sort=mirror_sort(edge.sort)) for edge in operation.inputs),
                output=replace(operation.output, sort=mirror_sort(operation.output.sort)))
        for operation in declaration.operations))


def host_digest() -> str:
    """Digest pinning every host of the declarations: sha256 of ops.py."""
    return hashlib.sha256(Path(ops.__file__).read_bytes()).hexdigest()


def write_decls(directory: Path = DECLARATIONS) -> None:
    """Refresh host references and digests of the committed declarations."""
    digest = host_digest()
    for group in "ABC":
        path = directory / f"atoms_mul_{group}.json"
        data = json.loads(path.read_text())
        data["open_kinds"] = ["operation"]
        hosts = []
        for record in (*data["operations"], data["objects"][0]):
            impl = record["impl"] if "impl" in record else record["valid"]
            impl["host"] = f"{HOST_MODULE}:{impl['host'].rsplit(':', 1)[1]}"
            impl["digest"] = digest
            hosts.append(impl["host"])
        data["lock"]["host_digests"] = {host: digest for host in sorted(hosts)}
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def load_decl(group: str) -> WorldDecl:
    if group not in "ABC" or len(group) != 1:
        raise ValueError(f"unknown world group {group!r}")
    return WorldDecl.from_dict(json.loads((DECLARATIONS / f"atoms_mul_{group}.json").read_text()))


def atoms(group: str) -> list[kernel.Atom]:
    return [kernel.Atom(op.name, len(op.inputs), ops.HOSTS[op.name], cost=op.cost)
            for op in load_decl(group).operations]


def _entry(lookup, name):
    if isinstance(lookup, dict):
        return lookup.get(name)
    if hasattr(lookup, "defs"):
        return next((entry for entry in lookup.defs if entry.name == name), None)
    if hasattr(lookup, "get"):
        return lookup.get(name)
    return lookup(name) if callable(lookup) else None


def _calls(entry):
    from .check import calls

    body = entry.body if not isinstance(entry, dict) else entry["body"]
    if isinstance(body, nodes.NODE_TYPES):
        return nodes.references(body)
    return set(calls(node_from_json(body) if isinstance(body, dict) else body))


def _mutual(entry, lookup):
    name = entry.name if not isinstance(entry, dict) else entry["name"]
    pending = [(other, (name, other)) for other in _calls(entry) if other != name]
    while pending:
        current, path = pending.pop()
        target = _entry(lookup, current)
        if target is None:
            continue
        for child in _calls(target):
            if child == name:
                return True
            if child not in path:
                pending.append((child, (*path, child)))
    return False


def compile_definition(defn, program_or_library_lookup) -> Definition | None:
    """Compile a saved AML entry; return None for a mutual-recursion cycle."""
    if _mutual(defn, program_or_library_lookup):
        return None
    body = defn.body if not isinstance(defn, dict) else defn["body"]
    compiled = compile_node(node_from_json(body) if isinstance(body, dict) else body)
    name = defn.name if not isinstance(defn, dict) else defn["name"]
    params = tuple(defn.params if not isinstance(defn, dict) else defn["params"])
    sorts = tuple((defn.param_sorts if not isinstance(defn, dict) else defn.get("param_sorts", ()))
                  or ("Nat",) * len(params))
    result_sort = defn.result_sort if not isinstance(defn, dict) else defn.get("result_sort", "Nat")
    if name in _calls(defn):
        compiled = nodes.Rec(name, params, compiled,
                             tuple(nodes.Var(param) for param in params), "fuel")
    dependencies = tuple(sorted(nodes.references(compiled)))
    resolved = [_entry(program_or_library_lookup, name) for name in dependencies]
    layer = 1 + max((getattr(target, "layer", 1) for target in resolved if target is not None), default=0)
    spec = OperationSpec(name, "combine" if len(params) > 1 else "transform",
                         tuple(Edge(mirror_sort(sort), name=param) for param, sort in zip(params, sorts)),
                         Edge(mirror_sort(result_sort)),
                         f"AML definition {name}", extra={"input_names": list(params)})
    return Definition(name, "operation", "invented", layer, dependencies, spec, compiled)


class CoreMirror:
    def __init__(self, group: str):
        self.group = group
        self.library = Library(mirror_world(group), atoms(group))

    def mirror(self, entry_list) -> list[dict]:
        entries = list(entry_list)
        lookup = {}
        for item in entries:
            entry = item.get("definition", item.get("entry", item)) if isinstance(item, dict) else item
            name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
            if isinstance(name, str):
                lookup[name] = entry
        lookup.update({name: definition for name, definition in self.library.definitions.items()
                       if definition.origin == "invented"})
        reports = []
        compiled = []
        for item in entries:
            entry = item.get("definition", item.get("entry", item)) if isinstance(item, dict) else item
            name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
            report = {"name": name, "core_status": None, "problems": [],
                      "evidence": None, "contract": None, "cost": None}
            reports.append(report)
            try:
                if not isinstance(name, str):
                    raise PipelineError("saved definition needs a name")
                if self.group == "C":
                    raise PipelineError("saving definitions is not available in this world")
                if isinstance(entry, dict):
                    from .library import Definition as AmlDefinition

                    entry = AmlDefinition(**entry)
                definition = compile_definition(entry, lookup)
                if definition is None:
                    raise PipelineError(MUTUAL_RECURSION)
                self.library.write(definition)
                compiled.append(definition)
            except Exception as error:  # noqa: BLE001 - a mirror failure is reported, never raised
                report["problems"] = error.problems if isinstance(error, PipelineError) else [str(error)]
                compiled.append(None)
        for index in dependency_order(compiled):
            if compiled[index] is None:
                continue
            item = entries[index]
            entry = item.get("definition", item.get("entry", item)) if isinstance(item, dict) else item
            if isinstance(entry, dict):
                from .library import Definition as AmlDefinition

                entry = AmlDefinition(**entry)
            name = compiled[index].name
            report = reports[index]
            try:
                self.library.check(name)
                sample = [tuple(sample_index % 4 for _ in entry.params)
                          for sample_index in range(4)]
                self.library.make_callable(name, sample)
                self.library.account(name)
                marked = (item.get("mul_equivalent", False) if isinstance(item, dict) else
                          getattr(item, "mul_equivalent", False))
                if marked:
                    request = exhaustive((range(16), range(16)), "a, b in 0..15")
                    request = replace(request, reference=lambda a, b: a * b)
                    self.library.verify(name, request)
                    self.library.account(name)
                    self.library.promote(name, Contract("result = a * b for a, b in 0..15; no state",
                                                        keeps=("full_state",)))
            except Exception as error:  # noqa: BLE001 - a mirror failure is reported, never raised
                report["problems"] = error.problems if isinstance(error, PipelineError) else [str(error)]
            stored = self.library.definitions.get(name) if isinstance(name, str) else None
            if stored is not None and stored.origin == "invented":
                report.update(core_status=stored.status,
                              evidence=stored.evidence.to_dict() if stored.evidence else None,
                              contract=stored.contract.to_dict() if stored.contract else None,
                              cost=stored.cost.to_dict())
        return reports

    def derived_world(self):
        return self.library.derived_world()
