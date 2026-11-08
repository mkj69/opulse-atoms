"""Connect a verified generated library to tasks and same-world kind paths."""

from __future__ import annotations

import json
from pathlib import Path

from opulse.atoms import nodes
from opulse.gen_v2.codec import decode_checkpoint_value, encode_checkpoint_value
from opulse.gen_v2.notation import print_declaration


def _task_hooks(require_generator=True):
    try:
        from opulse.tasks_v2.hooks import from_library
        if require_generator:
            from opulse.tasks_v2.generic import generate_world
        else:
            generate_world = None
    except ModuleNotFoundError as error:
        if error.name not in ("opulse.tasks_v2.generic", "opulse.tasks_v2.hooks"):
            raise
        raise RuntimeError(f"generated-library tasks require {error.name} "
                           "from the tasks branch") from error
    return from_library, generate_world


def task_world(state):
    """Adapt probe domains and recorded operation families for the task hook."""
    from_library, _ = _task_hooks(False)
    requested = {}
    for name, request in state.requests.items():
        entry = state.entries.get(name)
        if entry is None or entry.signature is None:
            continue
        by_sort = {}
        for arguments in request.domain:
            for sort, value in zip(entry.signature.inputs, arguments):
                values = by_sort.setdefault(sort, [])
                if not any(type(value) is type(other) and value == other for other in values):
                    values.append(value)
        for sort, values in by_sort.items():
            if sort in requested:
                requested[sort] = [old for old in requested[sort]
                                   if any(type(old) is type(value) and old == value for value in values)]
            else:
                requested[sort] = values
    domains = {name: tuple(value for value in sort.values
                           if any(type(value) is type(other) and value == other
                                  for other in requested[name])) if name in requested
               else tuple(sort.values) for name, sort in state.sorts.items()}
    family = {}
    for entry in state.entries.values():
        if entry.kind != "combinator":
            continue
        for slot, names in entry.meta.get("slot_families", {}).items():
            if slot in family:
                family[slot].intersection_update(names)
            else:
                family[slot] = set(names)
    truth_sort = state.world.truth_sort
    states = domains[truth_sort] if truth_sort in domains else tuple(state.world.truth_states)
    states = tuple(value for value in state.world.truth_states
                   if any(type(value) is type(other) and value == other for other in states))
    return from_library(
        state.library,
        domains=domains,
        family={slot: tuple(sorted(names)) for slot, names in sorted(family.items())},
        states=states,
        modalities={name: True for name in state.world.tags.get("modalities", ("text",))},
        to_value=encode_checkpoint_value,
        from_value=decode_checkpoint_value,
    )


def _references(state, entry):
    """Include operation arguments in combinators and calls to object members."""
    result = set(entry.depends_on)
    defn = state.library.get(entry.name)
    if isinstance(defn.body, nodes.NODE_TYPES):
        result.update(nodes.operation_literals(defn.body))
    return result


def _mentions_object(state, entry, object_name):
    signature = entry.signature
    return (signature is not None and object_name in (*signature.inputs, signature.output)
            or any(name == object_name or name.startswith(object_name + ".")
                   for name in _references(state, entry)))


def _verified(state, entry):
    defn = state.library.get(entry.name)
    return defn.status == "promoted" and defn.evidence is not None and defn.contract is not None


def four_kinds_path(state):
    """Find a real object -> operation -> combinator -> observation route, or None.

    A combinator's verified slot family is a valid use of an operation even if its
    body calls the slot by parameter name rather than naming the operation directly.
    The observation must use the selected combinator (possibly through another admitted
    dependency), so every step depends on the one before it.
    """
    entries = state.entries
    promoted = {name: entry for name, entry in entries.items()
                if entry.kind in {"object", "operation", "combinator", "observation"}
                and _verified(state, entry)}

    reference_cache = {name: _references(state, entry) for name, entry in promoted.items()}
    closure_cache = {}

    def closure(name, active=frozenset()):
        if name in closure_cache:
            return closure_cache[name]
        if name in active:
            return set()
        references = reference_cache[name]
        result = set(references)
        for dependency in references:
            if dependency in promoted:
                result.update(closure(dependency, active | {name}))
        closure_cache[name] = result
        return result

    def uses(name, target):
        return target in closure(name)

    objects = [entry for entry in promoted.values() if entry.kind == "object"]
    operations = [entry for entry in promoted.values() if entry.kind == "operation"]
    combinators = [entry for entry in promoted.values() if entry.kind == "combinator"]
    observations = [entry for entry in promoted.values() if entry.kind == "observation"]
    operations_by_object = {operation.name: [obj for obj in objects
                                              if _mentions_object(state, operation, obj.name)]
                            for operation in operations}
    best = None
    best_rank = None
    for combinator in combinators:
        families = combinator.meta.get("slot_families", {})
        eligible = [operation for operation in operations if operations_by_object[operation.name]
                    and (uses(combinator.name, operation.name) or
                         any(operation.name in names for names in families.values()))]
        if not eligible:
            continue
        for observation in observations:
            # A path is a dependency chain: the observation must use the combinator itself
            # (an observation that only uses the operation does not depend on the combinator).
            if not uses(observation.name, combinator.name):
                continue
            for operation in eligible:
                for obj in operations_by_object[operation.name]:
                    path = (obj, operation, combinator, observation)
                    rank = (sum(step.layer for step in path), tuple(step.name for step in path))
                    if best_rank is None or rank > best_rank:
                        best, best_rank = path, rank
    if best is None:
        return None
    path = best
    rows = []
    for entry in path:
        defn = state.library.get(entry.name)
        rows.append({"kind": entry.kind, "name": entry.name, "layer": entry.layer,
                     "ascii": print_declaration(entry, state),
                     "depends_on": list(entry.depends_on), "status": defn.status,
                     "evidence": defn.evidence.to_dict(),
                     "contract": defn.contract.to_dict()})
    return {"schema": "opulse.gen_v2.four-kinds-path/1", "world": state.world.name,
            "version": state.world.version, "steps": rows,
            "links": ["operation uses object", "combinator accepts operation in verified family"
                      if any(path[1].name in names for names in
                             path[2].meta.get("slot_families", {}).values())
                      else "combinator calls operation",
                      "observation uses combinator"]}


def _json_tasks(value):
    if hasattr(value, "to_dict"):
        return _json_tasks(value.to_dict())
    if isinstance(value, dict):
        return {key: _json_tasks(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_tasks(item) for item in value]
    return value


def export_tasks(state, path, per_angle, seed):
    """Write tasks next to the generator export, with an honest optional path."""
    if per_angle < 1:
        raise ValueError("per_angle must be positive")
    _, generate_world = _task_hooks()
    generated = generate_world(task_world(state), per_angle, seed)
    payload = {"schema": "opulse.gen_v2.tasks/1", "world": state.world.name,
               "version": state.world.version, "seed": seed,
               "per_angle": per_angle, "tasks": _json_tasks(generated),
               "four_kinds_path": four_kinds_path(state)}
    output = Path(path).with_suffix(".tasks.json")
    output.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                      encoding="utf-8")
    return payload
