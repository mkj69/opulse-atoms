"""Behavioural interest on finite verification scopes (heuristics, not proofs).

Total score weights: novelty .25, regularity .10, reuse .15, compression .10,
depth .10, cost .05, kind-specific quality .25. All components lie in [0, 1].
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict

from opulse.atoms import kernel, nodes
from opulse.atoms.values import FALSE, TRUE, Bottom, Card, Ok


def _value(value):
    if value is True or (isinstance(value, Card) and value == TRUE):
        return ("bool", True)
    if value is False or (isinstance(value, Card) and value == FALSE):
        return ("bool", False)
    if isinstance(value, Card):
        return ("card", value.sort, value.tag, tuple(_value(item) for item in value.fields))
    if isinstance(value, (tuple, list)):
        return (type(value).__name__, tuple(_value(item) for item in value))
    if isinstance(value, dict):
        return ("dict", tuple(sorted((repr(key), _value(item)) for key, item in value.items())))
    return (type(value).__name__, repr(value))


def _object_key(outcome, introduced):
    key = _key(outcome)
    if not isinstance(outcome, Ok):
        return key
    def normalize(value):
        if isinstance(value, Card):
            return ("card", "self" if value.sort == introduced else value.sort, value.tag,
                    tuple(normalize(item) for item in value.fields))
        return _value(value)
    return ("ok", normalize(outcome.value))


def _key(outcome) -> object:
    if isinstance(outcome, Ok):
        return ("ok", _value(outcome.value))
    if isinstance(outcome, Bottom):
        return ("bottom",)
    return ("unknown",)


def _partition(keys):
    groups = {}
    return tuple(groups.setdefault(key, len(groups)) for key in keys)


def _freeze(value):
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value


def fingerprints_extra(state, candidate, results) -> dict:
    """Record raw and argument-permutation-canonical operation keys in candidate.meta.

    Only complete permutations of the actually sampled domain are considered.
    """
    signature = candidate.signature
    if candidate.defn.kind != "operation" or signature is None:
        return {}
    domain = {tuple(_value(arg) for arg in args): _key(outcome) for args, outcome, _ in results}
    def variant(order):
        return ("operation", tuple(signature.inputs[index] for index in order), signature.output,
                tuple(sorted(((tuple(args[index] for index in order), value)
                              for args, value in domain.items()), key=repr)))
    identity = variant(tuple(range(len(signature.inputs))))
    variants = [identity]
    if len(signature.inputs) <= 4 and len(domain) == len(results):
        for order in itertools.permutations(range(len(signature.inputs))):
            if order == tuple(range(len(order))):
                continue
            if {tuple(args[index] for index in order) for args in domain} == set(domain):
                variants.append(variant(order))
    canonical = min(variants, key=repr)
    extra = {"fingerprint_raw": identity, "fingerprint_canonical": canonical,
             "fingerprint_swapped": canonical != identity}
    candidate.meta.update(extra)
    return extra


def fingerprint(state, candidate, results) -> tuple:
    kind = candidate.defn.kind
    keys = tuple(_key(outcome) for _, outcome, _ in results)
    if kind == "operation":
        return fingerprints_extra(state, candidate, results)["fingerprint_canonical"]
    if kind == "law":
        from opulse.gen_v2.laws import LawRecord
        from opulse.gen_v2.laws import _key as law_key

        spec = candidate.defn.spec
        record = LawRecord(spec.name, spec.statement, spec.vars, candidate.defn.depends_on,
                           candidate.defn.layer)
        return ("law", law_key(record, state), tuple(tuple(_value(value) for value in args)
                                                     for args, _, _ in results))
    if kind == "bridge":
        spec = candidate.defn.spec
        return ("bridge", spec.source, spec.target, spec.interface,
                tuple((tuple(_value(value) for value in args), _key(outcome))
                      for args, outcome, _ in results))
    if kind == "object":
        spec = candidate.defn.spec
        keys = tuple(_object_key(outcome, spec.name) for _, outcome, _ in results)
        tags = tuple(sorted((tag, tuple(sort if sort != spec.name else "self"
                                       for _, sort in (fields.items() if isinstance(fields, dict) else fields)))
                            for tag, fields in (spec.tags or {}).items()))
        return (kind, spec.form, spec.base, len(set(keys) - {("bottom",)}), _partition(keys), tags, keys)
    if kind == "combinator":
        slots = len(candidate.defn.spec.op_params)
        families = candidate.meta.get("slot_families")
        if families:
            width = len(results) // math.prod(len(families[slot]) for slot in candidate.defn.spec.op_params)
            expanded = [(tuple(assignment) + tuple(results[offset + index][0]),
                         results[offset + index][1], results[offset + index][2])
                        for assignment_index, assignment in enumerate(itertools.product(
                            *(families[slot] for slot in candidate.defn.spec.op_params)))
                        for offset in (assignment_index * width,)
                        for index in range(width)]
        else:
            expanded = results
        candidate.meta["plug_behaviour"] = tuple((tuple(_value(arg) for arg in args[slots:]),
                                                  tuple(_value(arg) for arg in args[:slots]), _key(outcome))
                                                 for args, outcome, _ in expanded)
        return _permuted_fingerprint(candidate, expanded, slots)
    return _permuted_fingerprint(candidate, results, 0)


def _permuted_fingerprint(candidate, results, slots):
    """Canonicalize interchangeable inputs without discarding their value table."""
    signature = candidate.signature
    sorts = (tuple(signature.op_inputs[:slots]) + tuple(signature.inputs)) if signature else ()
    table = {tuple(_value(value) for value in args): _key(outcome)
             for args, outcome, _ in results}
    size = len(sorts)
    orders = [tuple(range(size))]
    if size <= 4 and len(table) == len(results) and all(len(args) == size for args in table):
        orders.extend(order for order in itertools.permutations(range(size))
                      if order != orders[0] and all(sorts[index] == sorts[position]
                                                    for position, index in enumerate(order)))

    def variant(order):
        rows = tuple(sorted(((tuple(args[index] for index in order), outcome)
                             for args, outcome in table.items()), key=repr))
        if slots:
            return ("combinator", sorts, signature.output if signature else None, rows)
        return ("observation", signature.output if signature else None,
                _partition(tuple(value for _, value in rows)), rows)

    raw = variant(orders[0])
    canonical = min((variant(order) for order in orders), key=repr)
    candidate.meta.update(fingerprint_raw=raw, fingerprint_canonical=canonical,
                          fingerprint_swapped=canonical != raw)
    return canonical


def _independent(results, index):
    outputs, inputs = defaultdict(set), defaultdict(set)
    for args, outcome, _ in results:
        if len(args) <= index:
            return False
        rest = tuple(_value(arg) for pos, arg in enumerate(args) if pos != index)
        outputs[rest].add(_key(outcome))
        inputs[rest].add(_value(args[index]))
    return any(len(values) > 1 for values in inputs.values()) and all(len(values) == 1 for values in outputs.values())


def degenerate(state, candidate, results) -> str | None:
    kind = candidate.defn.kind
    if kind == "law":
        return None
    if kind == "bridge":
        values = {_key(outcome) for _, outcome, _ in results}
        return "constant bridge map on the recorded scope" if len(results) > 1 and len(values) == 1 else None
    if kind in ("combinator", "observation"):
        canonical = candidate.meta.get("fingerprint_canonical")
        owner = state.fingerprints.get(canonical)
        if owner and state.entries[owner].meta.get("fingerprint_raw") is not None and (
                state.entries[owner].meta["fingerprint_raw"] != candidate.meta.get("fingerprint_raw")):
            return f"same as {owner} up to argument order"
    if kind == "object":
        spec = candidate.defn.spec
        if spec.form == "refine" and results and all(args and isinstance(outcome, Ok) and
                _value(args[0]) == _value(outcome.value) for args, outcome, _ in results):
            return "refinement accepts all probes with identity canon"
        if spec.form == "compose" and spec.tags and len(spec.tags) == 1:
            fields = next(iter(spec.tags.values()))
            fields = tuple(fields.items() if isinstance(fields, dict) else fields)
            if len(fields) == 1 and fields[0][1] != spec.name:
                return "one-field record only renames its field sort"
        return None
    outcomes = [outcome for _, outcome, _ in results]
    if outcomes and all(isinstance(outcome, Bottom) for outcome in outcomes):
        return "fails on every input"
    keys = {_key(outcome) for outcome in outcomes}
    if len(outcomes) > 1 and len(keys) == 1:
        return "constant on the scope"
    signature = candidate.signature
    if kind == "operation" and signature:
        for index, sort in enumerate(signature.inputs):
            if sort == signature.output and results and all(isinstance(outcome, Ok) and
                    _value(outcome.value) == _value(args[index]) for args, outcome, _ in results):
                return f"identity on argument {index + 1}"
            if _independent(results, index):
                return f"independent of argument {index + 1}"
        if results and len(results) <= 200:
            scope = state.library.scope()
            for name in state.world.signatures:
                if state.signature(name) != signature:
                    continue
                try:
                    same = all(_key(kernel.call(name, args, scope, dialect=state.world.dialect).outcome) ==
                               _key(outcome) for args, outcome, _ in results)
                except (TypeError, ValueError, KeyError, IndexError, AttributeError, RecursionError):
                    same = False  # the host rejects these values, so it is not the same atom
                if same:
                    return f"same as given atom {name}"
        extra = fingerprints_extra(state, candidate, results)
        owner = state.fingerprints.get(extra["fingerprint_canonical"])
        if owner and state.entries[owner].meta.get("fingerprint_raw") != extra["fingerprint_raw"]:
            return f"same as {owner} up to argument order"
    if kind == "combinator":
        spec = candidate.defn.spec
        if isinstance(candidate.defn.body, nodes.Call) and candidate.defn.body.fn in spec.op_params and all(
                isinstance(arg, nodes.Var) for arg in candidate.defn.body.args):
            return "single call of plugged operation"
        slots = len(spec.op_params)
        groups = defaultdict(list)
        if candidate.meta.get("slot_families"):
            for inputs, plugs, outcome in candidate.meta.get("plug_behaviour", ()):
                groups[inputs].append((plugs, outcome))
        else:
            for args, outcome, _ in results:
                groups[tuple(_value(value) for value in args[slots:])].append((tuple(args[:slots]), _key(outcome)))
        if slots and any(len({repr(slot) for slot, _ in group}) > 1 for group in groups.values()) and all(
                len({key for _, key in group}) == 1 for group in groups.values()):
            return "independent of plugged operation"
        if slots == 1 and results and all(args and isinstance(args[0], (str, kernel.FnRef)) for args, _, _ in results):
            scope = state.library.scope()
            try:
                if all(_key(kernel.call(args[0].name if isinstance(args[0], kernel.FnRef) else args[0],
                                        tuple(args[1:]), scope, dialect=state.world.dialect).outcome) == _key(outcome)
                       for args, outcome, _ in results):
                    return "equal to one call of plugged operation"
            except (KeyError, ValueError, TypeError, IndexError, AttributeError, RecursionError):
                pass
    if kind == "observation" and results:
        scope = state.library.scope()
        for probe in state.world.probes:
            try:
                if all(_key(kernel.call(probe, (args[0],), scope,
                                        dialect=state.world.dialect).outcome) == _key(outcome)
                       for args, outcome, _ in results):
                    return f"same as given probe {probe}"
            except (KeyError, ValueError, TypeError, IndexError, AttributeError, RecursionError):
                continue
    return None


def _entropy(keys):
    if len(keys) < 2:
        return 0.0
    counts = Counter(keys)
    return -sum((count / len(keys)) * math.log2(count / len(keys)) for count in counts.values()) / math.log2(len(keys))


def _regularity(entry):
    signature = entry.signature
    if entry.kind == "observation":
        partition = entry.fingerprint[-2] if len(entry.fingerprint) >= 4 else ()
        groups = Counter(partition)
        found = []
        if 1 < len(groups) < len(partition):
            found.append("nontrivial partition")
            if len(set(groups.values())) == 1:
                found.append("balanced partition")
        elif partition and len(groups) == len(partition) and len(partition) > 1:
            found.append("distinguishes every probed state")
        return min(1.0, len(found) / 3), tuple(found)
    if entry.kind != "operation" or not signature:
        return 0.0, ()
    raw = _freeze(entry.meta.get("fingerprint_raw", entry.fingerprint))
    if not raw or len(raw) < 4:
        return 0.0, ()
    table = dict(raw[-1])
    found = []
    if len(signature.inputs) == 2 and signature.inputs[0] == signature.inputs[1]:
        pairs = [(outcome, table[(args[1], args[0])]) for args, outcome in table.items()
                 if (args[1], args[0]) in table and args[0] != args[1]]
        if len(pairs) >= 2 and all(left == right for left, right in pairs):
            found.append("commutative")
        diagonal = [(args[0], outcome) for args, outcome in table.items() if args[0] == args[1]]
        if signature.output == signature.inputs[0] and len(diagonal) >= 2 and all(
                outcome == ("ok", value) for value, outcome in diagonal):
            found.append("idempotent")
    if len(signature.inputs) == 1 and signature.output == signature.inputs[0]:
        cycle = [(args[0], outcome[1]) for args, outcome in table.items()
                 if outcome[0] == "ok" and len(outcome) > 1]
        if len(cycle) >= 2 and all(table.get((output,)) == ("ok", value)
                                   for value, output in cycle):
            found.append("involution")
    if len(signature.inputs) == 1:
        points = sorted((int(args[0][1]), int(outcome[1][1])) for args, outcome in table.items()
                        if args[0][0] == "int" and outcome[0] == "ok" and outcome[1][0] == "int")
        if len(points) > 2 and all(left[1] <= right[1] for left, right in itertools.pairwise(points)):
            found.append("monotone")
        if len(points) > 3 and any(all(points[index][1] == points[index + period][1]
                                         for index in range(len(points) - period))
                                   for period in range(1, len(points) // 2 + 1)):
            found.append("periodic")
    if len(signature.inputs) == 2 and signature.inputs[0] == signature.inputs[1] == signature.output:
        points = sorted({arg for args in table for arg in args}, key=repr)
        triples = itertools.islice(itertools.product(points, repeat=3), 64)
        comparisons = []
        for first, second, third in triples:
            left = table.get((first, second))
            right = table.get((second, third))
            if left and right and left[0] == right[0] == "ok":
                lhs = table.get((left[1], third))
                rhs = table.get((first, right[1]))
                if lhs is not None and rhs is not None:
                    comparisons.append(lhs == rhs)
        if len(comparisons) >= 2 and all(comparisons):
            found.append("associative")
    return min(1.0, len(found) / 3), tuple(found)


def _unfolded_length(state, entry, own, estimates, scope_cache):
    """Inline small bodies, estimate larger ones, cap lengths at 1024 nodes."""
    try:
        record = state.library.get(entry.name)
    except (KeyError, AttributeError, ValueError):
        return own + sum(min(512, estimates.get(dep, state.entries[dep].length))
                         for dep in entry.depends_on if dep in state.entries)
    bodies = [record.body]
    if entry.kind == "object":
        bodies.extend((record.spec.valid, record.spec.canon))
    if entry.kind == "observation" and record.spec.memory:
        bodies.append(record.spec.memory.get("step"))
    estimated = 0
    for body in bodies:
        if not isinstance(body, nodes.NODE_TYPES):
            continue
        estimated += nodes.length(body)
        for part in nodes.walk(body):
            if isinstance(part, nodes.Call) and part.fn in estimates:
                estimated += max(0, estimates[part.fn] - 1)
                if estimated > 1024:
                    return 1024
    estimated = max(own, estimated)
    if estimated > 96:
        return min(1024, estimated)
    if not scope_cache:
        scope_cache.append(state.library.scope())
    try:
        return min(1024, max(own, sum(nodes.length(kernel.inline(body, scope_cache[0]))
                                       for body in bodies if isinstance(body, nodes.NODE_TYPES))))
    except (RecursionError, ValueError, TypeError, KeyError):
        return min(1024, estimated)


def score_entries(state) -> None:
    """Score admitted definitions with small exact and larger capped unfoldings."""
    entries = list(state.entries.values())
    dependents = Counter(dep for entry in entries for dep in dict.fromkeys(entry.depends_on)
                         if dep in state.entries)
    operation_entries = [entry for entry in entries if entry.kind == "operation"]
    operation_deps = {dep for entry in operation_entries for dep in entry.depends_on}
    operation_sorts = {sort for entry in operation_entries if entry.signature
                       for sort in (*entry.signature.inputs, entry.signature.output)}
    call_sites = Counter()
    for later in entries:
        try:
            body = state.library.get(later.name).body
        except (KeyError, ValueError, AttributeError):
            continue
        call_sites.update(part.fn for part in nodes.walk(body)
                          if isinstance(part, nodes.Call) and part.fn in state.entries)
    previous = defaultdict(list)
    estimates = {}
    scope_cache = []
    max_layer = max((entry.layer for entry in entries), default=1)
    for entry in entries:
        key = (entry.kind, entry.signature)
        raw = _freeze(entry.meta.get("fingerprint_raw", entry.fingerprint))
        raw = raw[-1] if raw else ()
        if not isinstance(raw, tuple):
            raw = (raw,)
        table = (tuple(value for _, value in raw)
                 if entry.kind in ("operation", "combinator", "observation") and isinstance(raw, tuple) and
                 all(isinstance(item, tuple) and len(item) == 2 for item in raw) else raw)
        distances = [sum(left != right for left, right in zip(table, earlier)) /
                     max(len(table), len(earlier), 1) for earlier in previous[key][-32:]]
        novelty = min(distances, default=1.0)
        previous[key].append(table)
        regularity, properties = _regularity(entry)
        used = dependents[entry.name]
        reuse_count = call_sites[entry.name] if call_sites[entry.name] else entry.reuse
        reuse = (reuse_count + used) / (1 + reuse_count + used)
        own = max(1, entry.length)
        unfolded = _unfolded_length(state, entry, own, estimates, scope_cache)
        estimates[entry.name] = unfolded
        compression = 1 - own / max(own, unfolded)
        depth = entry.layer / max_layer
        cost = 1 / (1 + max(0, entry.steps_mean) / max(1, state.world.max_steps))
        if entry.kind == "object":
            spec = state.library.get(entry.name).spec if entry.name in state.library.definitions else None
            quality = (float(bool(spec and spec.form == "refine" and spec.canon and
                                  not isinstance(spec.canon, nodes.Var))) +
                       float(bool(spec and (not spec.sealed or spec.interface))) +
                       float(entry.name in operation_sorts or entry.name in operation_deps or any(
                           dep.startswith(f"{entry.name}.") for dep in operation_deps))) / 3
        elif entry.kind == "combinator":
            by_inputs = defaultdict(set)
            for inputs, _, outcome in entry.meta.get("plug_behaviour", ()):
                by_inputs[_freeze(inputs)].add(_freeze(outcome))
            plug_variation = float(any(len(values) > 1 for values in by_inputs.values()))
            quality = (plug_variation + reuse) / 2
        elif entry.kind == "observation":
            quality = (_entropy(table) + float(len(set(table)) > 1) + reuse) / 3
        elif entry.kind == "law":
            quality = (float(bool(entry.depends_on)) + reuse) / 2
        elif entry.kind == "bridge":
            quality = (float(bool(state.library.get(entry.name).spec.interface)) + reuse) / 2
        else:
            quality = _entropy(table)
        total = (.25 * novelty + .10 * regularity + .15 * reuse + .10 * compression +
                 .10 * depth + .05 * cost + .25 * quality)
        entry.interest = {"novelty": novelty, "regularity": regularity, "reuse": reuse,
                          "compression": compression, "depth": depth, "cost": cost,
                          "quality": quality, "total": total, "regularities": properties,
                          "distinct_dependents": used, "call_sites": reuse_count,
                          "unfolded_length_estimate": unfolded, "steps_mean": entry.steps_mean,
                          "layer": entry.layer}
