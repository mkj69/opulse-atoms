"""Adaptive, reproducible generation and JSON checkpoints.

Moves may opt into depth pressure by exposing ``builds_on_top = True``. A move that
exposes a writable ``bias`` receives a value between 0 and 1 after half the
admission target (or half the attempt cap); it can use that hint to prefer
dependencies at the highest available layer.
No hints are added to the world or the shared GenState class.
"""

from __future__ import annotations

import importlib
import json
import os
import random
import time
from collections import Counter
from copy import copy
from dataclasses import dataclass, field, replace
from pathlib import Path

from opulse.atoms.library import VerifyRequest
from opulse.atoms.spec import Definition
from opulse.gen_v2.admit import admit
from opulse.gen_v2.base import (
    Entry,
    GenState,
    Names,
    Rejection,
    Signature,
    Sort,
    kind_counts,
    signature_data,
    signature_from_data,
)
from opulse.gen_v2.codec import (
    decode_checkpoint_value,
    encode_checkpoint_value,
    require_restorable,
)
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.registry import discover_moves


@dataclass
class RunState(GenState):
    attempts: int = 0
    move_attempts: Counter = field(default_factory=Counter)
    move_successes: Counter = field(default_factory=Counter)


def _tuple_tree(value):
    """JSON lists back to tuples (and dicts to sorted item tuples) so fingerprints hash."""
    if isinstance(value, list):
        return tuple(_tuple_tree(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _tuple_tree(item)) for key, item in value.items()))
    return value


def _without_callables(value):
    if isinstance(value, dict):
        return {key: _without_callables(item) for key, item in value.items() if not callable(item)}
    if isinstance(value, (tuple, list)):
        return [_without_callables(item) for item in value if not callable(item)]
    return value


def _report(state, start, log):
    if log is None:
        return
    rejections = Counter(item.stage for item in state.rejections)
    log({"admitted": len(state.entries), "attempts": state.attempts,
         "counts": dict(kind_counts(state.entries.values())), "max_layer": state.max_layer(),
         "rate": round(len(state.entries) / max(time.monotonic() - start, 0.001), 2),
         "rejections": dict(rejections.most_common(5))})


def _run_world(world):
    """Keep dynamic recursion hints and probe-sort edits local to this run."""
    return replace(world, sorts={name: replace(sort) for name, sort in world.sorts.items()},
                   measures={name: list(pairs) for name, pairs in world.measures.items()},
                   bases={name: list(names) for name, names in world.bases.items()})


def generate(world, target: int, seed: int, per_kind_min: int = 50,
             time_limit: float | None = None, layer_target: int = 10,
             moves=None, log=None, state: RunState | None = None) -> GenState:
    """Run ``_generate`` on one big-stack thread so kernel calls skip the per-call thread hop
    (opulse.gen_v2.fast); same results."""
    from opulse.gen_v2 import fast

    return fast.deep(_generate, world, target, seed, per_kind_min, time_limit, layer_target,
                     moves, log, state)


def _generate(world, target: int, seed: int, per_kind_min: int = 50,
              time_limit: float | None = None, layer_target: int = 10,
              moves=None, log=None, state: RunState | None = None) -> GenState:
    """Grow a library until target, open-kind quotas and depth are reached.

    Pass a state returned by ``load`` to resume with the same seed and attempt stream.
    ``log`` receives a progress dictionary every 25 admissions and on exit.
    A cap of 100 attempts per requested admission prevents infinite failed runs.
    """
    if target < 0 or per_kind_min < 0 or layer_target < 0:
        raise ValueError("targets must be non-negative")
    if state is None:
        world = _run_world(world)
        lib = GenLibrary(world.decl, world.atoms, world.dialect, world.extra_scope, world.signatures)
        state = RunState(world, lib, dict(world.sorts), seed=seed)
        state.names = Names(tuple(lib._definitions) + tuple(lib._extra_defns))
    elif state.seed != seed or state.world.decl.world_hash() != world.decl.world_hash():
        raise ValueError("resume world or seed differs from checkpoint")
    grouped = discover_moves() if moves is None else moves
    if not isinstance(grouped, dict):
        grouped_by_kind = {kind: [] for kind in sorted(world.open_kinds)}
        for move in grouped:
            grouped_by_kind.setdefault(move.kind, []).append(move)
        grouped = grouped_by_kind
    grouped = {kind: [copy(move) if hasattr(move, "bias") else move for move in options]
               for kind, options in grouped.items()}
    from opulse.gen_v2.base import KINDS

    kinds = [kind for kind in KINDS
             if kind in world.open_kinds and
             (kind != "observation" or world.probes or world.truth_sort or world.truth_states)
             and grouped.get(kind)]
    # Laws and bridges are conjectured alongside the definitions but carry no quota: a world
    # that opens them must not run until the safety limit waiting for law entries.
    quota_kinds = [kind for kind in kinds if kind not in ("law", "bridge")]
    start = time.monotonic()
    cap = max(200, 100 * max(target, per_kind_min * len(quota_kinds), 1))
    while kinds and state.attempts < cap:
        counts = kind_counts(state.entries.values())
        if (len(state.entries) >= target and all(counts[kind] >= per_kind_min for kind in quota_kinds)
                and state.max_layer() >= layer_target):
            break
        if time_limit is not None and time.monotonic() - start >= time_limit:
            break
        attempt = state.attempts
        state.attempts += 1
        rng = random.Random(f"{seed}:{attempt}")
        weights = []
        for kind in kinds:
            deficit = max(0, per_kind_min - counts[kind]) if kind in quota_kinds else 0
            weight = 1 + (6 * deficit / max(per_kind_min, 1))
            if kind == "object" and len(state.entries) < max(target // 4, 1):
                weight *= 2
            weights.append(weight)
        kind = rng.choices(kinds, weights=weights)[0]
        progress = max(attempt / cap, len(state.entries) / max(target, 1))
        pressure = (min(1.0, max(0.0, (progress - 0.5) * 2))
                    if state.max_layer(kind) < layer_target else 0.0)
        options = grouped[kind]
        move_weights = [(0.2 + (state.move_successes[move.name] + 1) /
                         (state.move_attempts[move.name] + 2)) *
                        (1 + 4 * pressure if getattr(move, "builds_on_top", False) else 1)
                        for move in options]
        move = rng.choices(options, weights=move_weights)[0]
        if hasattr(move, "bias"):
            move.bias = pressure
        state.move_attempts[move.name] += 1
        try:
            candidate = move(state, rng)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, RecursionError) as error:
            # A world host may reject an ill-typed probe value while a move explores; that is a
            # failed proposal, recorded like any refusal, not the end of the run.
            state.rejections.append(Rejection(move.name, move.kind, "move_error",
                                              f"{type(error).__name__}: {error}"[:300]))
            continue
        if candidate is None:
            continue
        result = admit(state, candidate)
        if isinstance(result, Entry):
            state.move_successes[move.name] += 1
            if len(state.entries) % 25 == 0:
                _report(state, start, log)
    _report(state, start, log)
    try:
        interest = importlib.import_module("opulse.gen_v2.interest")
    except ModuleNotFoundError as error:
        if error.name != "opulse.gen_v2.interest":
            raise
    else:
        if hasattr(interest, "score_entries"):
            interest.score_entries(state)
        if hasattr(interest, "curate"):
            interest.curate(state)
    return state


def save(state: GenState, path: str | Path) -> None:
    """Save a checkpoint; values require the opulse.value/2 codec."""
    if state.world.decl.world_hash() != state.library.world.world_hash():
        raise ValueError("world declaration changed since generator verification")
    data = {"schema": "opulse.gen-v2.checkpoint/1", "world_hash": state.world.decl.world_hash(),
            "seed": state.seed, "attempts": getattr(state, "attempts", 0),
            "object_pending_name": getattr(state, "_object_pending_name", None),
            "move_attempts": dict(getattr(state, "move_attempts", {})),
            "move_successes": dict(getattr(state, "move_successes", {})),
            "library": state.library.to_dict(),
            "names": {"counter": state.names.counter, "taken": sorted(state.names.taken)},
            "sorts": {name: {"values": [encode_checkpoint_value(value) for value in sort.values],
                              "origin": sort.origin, "defined_by": sort.defined_by,
                              "constructors": sort.constructors, "accessors": sort.accessors,
                              "testers": sort.testers, "sealed": sort.sealed,
                              "interface": sort.interface, "base": sort.base, "doc": sort.doc,
                              "finite": sort.finite}
                      for name, sort in state.sorts.items()},
            "extra_signatures": {name: signature_data(sig) for name, sig in state.extra_signatures.items()},
            "requests": {name: {"method": request.method,
                                "domain": [encode_args(args) for args in request.domain],
                                "scope": request.scope, "seed": request.seed,
                                "reference": request.reference if isinstance(request.reference, str) else None,
                                "reference_unavailable": request.reference is not None and
                                not isinstance(request.reference, str) and
                                not request.extra.get("self_reference", False),
                                "extra": {key: _without_callables(value) for key, value in request.extra.items()
                                          if key not in ("table", "precomputed", "precomputed_scope") and
                                          not callable(value)}}
                         for name, request in state.requests.items()},
            "entries": [{"name": entry.name, "kind": entry.kind, "layer": entry.layer,
                         "signature": signature_data(entry.signature), "move": entry.move,
                         "depends_on": entry.depends_on, "fingerprint": entry.fingerprint,
                         "steps_mean": entry.steps_mean, "steps_max": entry.steps_max,
                         "length": entry.length, "reuse": entry.reuse,
                         "interest": entry.interest,
                         "examples": [[encode_args(args), outcome, steps] for args, outcome, steps in entry.examples],
                         "meta": entry.meta} for entry in state.entries.values()],
            "rejections": [vars(item) for item in state.rejections],
            "templates": _templates().templates_to_json(state)}
    for item in data["sorts"].values():
        if item["origin"] != "given":
            require_restorable(item["values"])
    for item in data["entries"]:
        require_restorable(item["examples"])
    for item in data["requests"].values():
        require_restorable(item["domain"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=True, default=_json_default), encoding="utf-8")
    os.replace(temporary, path)


def _templates():
    from opulse.gen_v2 import templates

    return templates


def _json_default(value):
    """Entry meta may hold records (signatures, template arguments): store them readably."""
    if isinstance(value, Signature):
        return signature_data(value)
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    return repr(value)


def encode_args(args):
    return [encode_checkpoint_value(value) for value in args]


def load(world, path: str | Path, *, target_worlds=None) -> RunState:
    """Restore a checkpoint for the exact same world declaration and given atoms.

    Object operations and witnesses are rebuilt from the stored object specs and bodies.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in data["sorts"].values():
        if item["origin"] != "given":
            require_restorable(item["values"])
    for item in data["entries"]:
        require_restorable(item["examples"])
    for item in data.get("requests", {}).values():
        require_restorable(item["domain"])
    if data.get("schema") != "opulse.gen-v2.checkpoint/1" or data.get("world_hash") != world.decl.world_hash():
        raise ValueError("checkpoint schema or world hash differs")
    lib = GenLibrary(world.decl, world.atoms, world.dialect, world.extra_scope, world.signatures)
    for target in (target_worlds or ()):
        target_library = (target.library if isinstance(target, GenState) else
                          GenLibrary(target.decl, target.atoms, target.dialect,
                                     target.extra_scope, target.signatures))
        lib.attach_world(f"{target_library.world.world}@{target_library.world.version}", target_library)
    stored = data["library"]
    missing_targets = {record["spec"]["target"].rsplit(":", 1)[0]
                       for record in stored["definitions"] if record["kind"] == "bridge"
                       and ":" in record["spec"]["target"]} - set(lib._attached_worlds)
    if missing_targets:
        raise ValueError(f"bridge target worlds must be attached: {sorted(missing_targets)}")
    for record in stored["definitions"]:
        defn = Definition.from_dict(record)
        if defn.validate() or lib.has_name(defn.name):
            raise ValueError(f"invalid stored definition: {defn.name}")
        lib._definitions[defn.name] = defn
    lib._steps = {name: list(steps) for name, steps in stored.get("steps", {}).items()}
    from opulse.atoms import nodes
    lib._solutions = [nodes.from_json(node) for node in stored.get("solutions", ())]
    sorts = {}
    for name, item in data["sorts"].items():
        values = (world.sorts[name].values if item["origin"] == "given" and name in world.sorts
                  else tuple(decode_checkpoint_value(value) for value in item["values"]))
        sorts[name] = Sort(name, values, item["origin"], item["defined_by"],
                           tuple(item["constructors"]), tuple(item["accessors"]),
                           tuple(item["testers"]), item["sealed"], tuple(item["interface"]),
                           item["base"], item["doc"], item.get("finite", False))
    state = RunState(_run_world(world), lib, sorts, seed=data["seed"], attempts=data.get("attempts", 0))
    state.move_attempts = Counter(data.get("move_attempts", {}))
    state.move_successes = Counter(data.get("move_successes", {}))
    state.names = Names(data["names"]["taken"])
    state.names.counter = data["names"]["counter"]
    state.extra_signatures = {name: signature_from_data(sig) for name, sig in data["extra_signatures"].items()}
    for item in data["entries"]:
        entry = Entry(item["name"], item["kind"], item["layer"], signature_from_data(item["signature"]),
                      item["move"], tuple(item["depends_on"]), _tuple_tree(item["fingerprint"]),
                      item["steps_mean"], item["steps_max"], item["length"], item["reuse"],
                      item["interest"], [(tuple(decode_checkpoint_value(value) for value in args), outcome, steps)
                                          for args, outcome, steps in item["examples"]], item["meta"])
        state.entries[entry.name] = entry
        state.fingerprints[entry.fingerprint] = entry.name
    state.rejections = [Rejection(**item) for item in data["rejections"]]
    if data.get("object_pending_name") is not None:
        state._object_pending_name = tuple(data["object_pending_name"])
    _templates().templates_from_json(state, data.get("templates") or [])
    state.requests = {name: VerifyRequest(item["method"],
                          tuple(tuple(decode_checkpoint_value(value) for value in args) for args in item["domain"]),
                          item["scope"], item["seed"], item["reference"],
                          {**item.get("extra", {}), **({"reference_unavailable": True} if
                                                         item.get("reference_unavailable") else {})})
                      for name, item in data.get("requests", {}).items()}
    # Restore the same object helpers as admission, including folds and refinements.
    from opulse.atoms import kernel, nodes
    from opulse.gen_v2.kinds.objects import object_atoms

    for defn in lib._definitions.values():
        if defn.origin == "invented" and defn.kind == "object" and isinstance(defn.body, nodes.NODE_TYPES):
            for item in object_atoms(defn.spec, state)[0]:
                if item.name == defn.name:
                    continue
                if isinstance(item, kernel.Atom):
                    lib._extra_atoms[item.name] = item
                else:
                    lib._extra_defns[item.name] = item
            lib._extra_defns[defn.name] = kernel.Defn(defn.name, (), defn.body, kind="object", layer=defn.layer)
    from opulse.gen_v2.moves.object import _register_recursive_hints

    _register_recursive_hints(state)
    lib._dirty = True
    return state


__all__ = ["RunState", "generate", "load", "save"]
