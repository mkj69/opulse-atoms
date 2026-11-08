"""Import a published legacy-v1 operator catalogue through the v2 admission pipeline.

The legacy adapter supplies the actual kernel bodies and host atoms. Published symbols are
display metadata only; imported kernel names and their references are ASCII.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import fields, is_dataclass, replace
from threading import Lock
from unittest.mock import patch

from opulse.atoms import golden, nodes, values
from opulse.atoms.check import check_definition
from opulse.atoms.legacy import scope_from_registry, scope_from_skills
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Definition, Edge, OperationSpec
from opulse.atoms.world import legacy_world_decl
from opulse.gen_v2.admit import admit, domain_request
from opulse.gen_v2.base import (
    Candidate,
    Entry,
    GenState,
    GenWorld,
    Rejection,
    Signature,
    Sort,
)
from opulse.gen_v2.library import GenLibrary

_CODEC_LOCK = Lock()
_IMPORT_REGISTRY = {}


def _import_token(state, candidate, published_record):
    record_hash = hashlib.sha256(json.dumps(published_record, sort_keys=True, default=str).encode()).hexdigest()
    identity = (state.world.name, candidate.meta["legacy"]["func_id"], record_hash)
    candidate.meta["_published_record_hash"] = record_hash
    token = object()
    _IMPORT_REGISTRY[token] = (id(state), candidate.defn.name, identity)
    return token


def _valid_import_token(token, state, candidate):
    registered = _IMPORT_REGISTRY.pop(token, None) if token is not None else None
    return bool(registered and registered[0] == id(state) and registered[1] == candidate.defn.name and
                registered[2][0] == state.world.name and
                registered[2][1] == candidate.meta.get("legacy", {}).get("func_id") and
                registered[2][2] == candidate.meta.get("_published_record_hash"))


def encode_published_value(world_name: str, value: object, sort: str | None = None) -> dict:
    """Encode with the same value codec used by the published classic world."""
    if world_name == "action":
        from opulse.worlds.action import encode

        return encode(value)
    if world_name == "perm":
        from opulse.worlds.perm import _value

        return _value(value)
    if world_name == "grid":
        from opulse.worlds.grid import encode_value

        return encode_value(value)
    if world_name == "pitch":
        from opulse.worlds.pitch import _value

        return _value(value, sort)
    from opulse.worlds.showcase import encode

    encoded = encode(value, sort)
    if sort == "entity" and encoded["t"] == "str":
        return {"t": "entity", "v": encoded["v"]}
    return encoded


def _rename_calls(node, names):
    if isinstance(node, nodes.Call):
        return replace(node, fn=names.get(node.fn, node.fn),
                       args=tuple(_rename_calls(arg, names) for arg in node.args))
    if isinstance(node, tuple):
        return tuple(_rename_calls(item, names) for item in node)
    if is_dataclass(node) and isinstance(node, nodes.NODE_TYPES):
        return replace(node, **{field.name: _rename_calls(getattr(node, field.name), names)
                                for field in fields(node)})
    return node


def _ascii_metadata(value, names):
    if isinstance(value, str):
        return names.get(value, value).encode("ascii", "backslashreplace").decode("ascii")
    if isinstance(value, dict):
        return {_ascii_metadata(key, names): _ascii_metadata(item, names)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ascii_metadata(item, names) for item in value]
    return value


def _admit_legacy(state: GenState, candidate: Candidate, published_record) -> Entry | Rejection:
    """Supply a world-context example codec while using the standard admission pipeline."""
    def encode_outcome(outcome):
        if isinstance(outcome, values.Ok):
            return {"ok": encode_published_value(state.world.name, outcome.value,
                                                   candidate.signature.output)}
        return values.encode_outcome(outcome)

    token = _import_token(state, candidate, published_record)
    try:
        with _CODEC_LOCK, patch("opulse.gen_v2.admit.encode_outcome", encode_outcome):
            return admit(state, candidate, _import_token=token)
    finally:
        _IMPORT_REGISTRY.pop(token, None)


class _LegacyLibrary(GenLibrary):
    def check(self, name: str, kind_checker=None) -> Definition:
        defn = self.get(name)
        problems = check_definition(defn, self.world, self.resolve)
        problems = [problem for problem in problems if "expected unknown, got" not in problem and
                    ", got unknown" not in problem and not
                    (self.world.world == "pitch" and "expected note, got int" in problem)]
        if problems:
            raise PipelineError(problems)
        return self._advance(name, "checked")


def _probe_values(world_json: dict, sorts: set[str]) -> dict[str, tuple]:
    """Small, ordered, world-specific domains, supplemented with published example inputs."""
    world = world_json["world"]
    defaults = {
        "int": ((0, 1, 3, 11, 27, 97, -2, -1, 2, -8, 12, 100) if world == "integer"
                else (0, 1, 3, 6, 9, 11, 2, 4, 5, 7, 8, 10) if world == "clock"
                else (-2, -1, 0, 1, 2, 3, -8, -4, -3, 4, 6, 12)),
        "hour": (0, 1, 2, 6, 11),
        "bool": (False, True), "str": (() if world == "rel" else ("", "a", "b", "ab", "ba", "aba")),
        "list": ((), (0,), (1,), (0, 1)), "note": (0, 1, 2, 7),
    }
    values = {sort: list(defaults.get(sort, ())) for sort in sorted(sorts)}
    for row in (*world_json["atoms"], *world_json["operators"]):
        for example in ([row["example"]] if row.get("example") else row.get("examples", ())):
            for param, encoded in zip(row["params"], example["inputs"]):
                sort = param["type"]
                if sort not in values or len(values[sort]) >= (12 if sort == "int" else 6):
                    continue
                value = golden.decode(encoded)
                if not any(value == existing for existing in values[sort]):
                    values[sort].append(value)
    return {sort: tuple(probes[:12 if sort == "int" else 6]) for sort, probes in values.items()}


def _ordered(operators, bodies):
    """Stable topological order; publication order is not dependency order."""
    def name(operator):
        return getattr(operator, "func_id", None) or operator.name

    by_name = {name(operator): operator for operator in operators}
    pending = set(by_name)
    while pending:
        ready = [operator for operator in operators if name(operator) in pending and
                 not (nodes.references(bodies[name(operator)].body) & pending - {name(operator)})]
        if not ready:
            raise ValueError(f"cyclic published operator dependencies: {sorted(pending)}")
        for operator in ready:
            pending.remove(name(operator))
            yield operator


def import_world(world_name: str, state: GenState | None = None) -> GenState:
    """Admit the main published seed of a classic world, recording every refusal in state.

    ``state`` may be a previously created, compatible, empty catalogue. Published and
    adapter layers are retained alongside the computed v2 dependency layer in metadata.
    """
    if world_name not in golden.WORLDS:
        raise ValueError(f"unknown classic world: {world_name}")
    world_json = json.loads((golden.DEFAULT_ROOT / f"{world_name}.json").read_text(encoding="utf-8"))
    reference = golden.CurrentEngine().load_published(world_json)
    if world_name == "action":
        scope, _ = scope_from_skills(reference)
        operators = list(reference.values())
        rows = {row["name"]: row for row in world_json["operators"]}
        canonical = {row["name"]: f"published_{index}"
                     for index, row in enumerate(world_json["operators"])}
    else:
        tools = reference.tools
        scope, _ = scope_from_registry(tools.registry, tools.settings.semantics.build(), tools.oracle.parser)
        operators = list(reference.ordered)
        rows = {operator.func_id: row for operator, row in zip(operators, world_json["operators"])}
        canonical = {}
    published_ids = {row["name"]: f"published_{index}"
                     for index, row in enumerate(world_json["operators"])}
    decl = legacy_world_decl(world_json)
    given = {atom.name: atom for atom in scope.atoms.values()}
    base_ops = ({} if world_name == "action" else
                {op.primitive_name: op.func_id for op in reference.tools.registry if op.definition is None})
    symbols = {row["name"]: published_ids[row["name"]] for row in world_json["operators"]}
    symbols.update({row.get("symbol", row["name"]): base_ops.get(row["name"], row["name"])
                    for row in world_json["atoms"]})
    signatures = {base_ops.get(row["name"], row["name"]):
                  Signature(tuple(param["type"] for param in row["params"]), row["result_type"])
                  for row in world_json["atoms"]}
    sorts = {obj.name for obj in decl.objects}
    for row in world_json["operators"]:
        sorts.add(row["result_type"])
        sorts.update(param["type"] for param in row["params"])
    probes = _probe_values(world_json, sorts)
    decl = replace(decl, combinators={**decl.combinators, "nodes": [*decl.combinators["nodes"], "Let"]})
    world = GenWorld(world_name, decl, tuple(given.values()), signatures,
                     {sort: Sort(sort, probes[sort]) for sort in sorted(sorts)},
                     frozenset({"operation"}), dialect="legacy-v1", fuel=20_000,
                     max_steps=20_000, max_scope=36,
                     title=world_json.get("title", world_name))
    if state is None:
        state = GenState(world, _LegacyLibrary(decl, world.atoms, world.dialect), dict(world.sorts))
    elif (state.world.name != world_name or state.world.dialect != "legacy-v1" or
          state.entries or state.rejections):
        raise ValueError("state must be an empty legacy catalogue for this world")
    else:
        world = state.world
    refusals = []
    state.legacy_refusals = refusals
    curated = set(world_json.get("curated", ()))
    for operator in _ordered(operators, scope.defns):
        source_name = operator.name if world_name == "action" else operator.func_id
        name = canonical.get(source_name, source_name)
        row = rows[source_name]
        source = scope.defns[source_name]
        body = replace(source, name=name, body=_rename_calls(source.body, canonical))
        dependencies = tuple(sorted(nodes.references(body.body)))
        published_layer = row["layer"]
        actual_layer = 1 + max((getattr(state.library.resolve(dep), "layer", 0)
                                for dep in dependencies if dep != name), default=0)
        rule = row.get("rule")
        spec = OperationSpec(name, "act" if world_name == "action" and row["result_type"] == "state"
                             else "decide" if row["result_type"] == "bool" else
                             "combine" if len(row["params"]) > 1 else "transform",
                             tuple(Edge(param["type"]) for param in row["params"]),
                             Edge(row["result_type"]),
                             rule if isinstance(rule, str) and rule.isascii() and rule else
                             f"Published legacy operation {name}",
                             extra={"input_names": list(body.params)})
        signature = Signature(tuple(param["type"] for param in row["params"]), row["result_type"])
        legacy = {"symbol": row.get("symbol", row["name"]), "func_id": name,
                  "interest": _ascii_metadata(row.get("interest"), symbols),
                  "featured": bool(row.get("featured")),
                  "curated": row["name"] in curated,
                  "uses": [published_ids.get(used, used) for used in row.get("uses", ())],
                  "definition_type": row.get("kind"),
                  "published_layer": published_layer,
                  "adapter_layer": body.layer, "computed_layer": actual_layer}
        candidate = Candidate(Definition(name, "operation", "invented", actual_layer,
                                         dependencies, spec, body.body), signature, "legacy.import",
                              request=domain_request(state, signature),
                              meta={"legacy": legacy, "legacy_keep": True})
        admitted = _admit_legacy(state, candidate, row)
        if isinstance(admitted, Rejection):
            refusals.append({"name": name, "symbol": legacy["symbol"],
                             "stage": admitted.stage, "reason": admitted.reason})
            state.library.add_atoms([replace(body, layer=actual_layer)])
    return state


def import_report(state: GenState) -> dict:
    """Summary with exact rejection stages and reasons for a completed import."""
    mismatches = [{"name": entry.name, "published_layer": entry.meta["legacy"]["published_layer"],
                   "adapter_layer": entry.meta["legacy"]["adapter_layer"], "computed_layer": entry.layer}
                  for entry in state.entries.values()
                  if entry.layer != entry.meta["legacy"]["adapter_layer"]]
    return {"world": state.world.name, "published": len(state.entries) + len(state.rejections),
            "admitted": len(state.entries),
            "refused": list(state.legacy_refusals),
            "layer_mismatches": mismatches,
            "layer_explanation": ("Legacy recursive layers measure the published operator's old unfolding depth; "
                                  "v2 layers are one plus the maximum dependency layer in the imported DAG."),
            "rejection_reasons": {f"{stage}: {reason}": count for (stage, reason), count in
                                  Counter((item.stage, item.reason) for item in state.rejections).items()}}
