"""Quota-aware, dependency-closed catalogue selection and graph summaries."""

from __future__ import annotations

from collections import Counter

from opulse.gen_v2.base import KINDS
from opulse.gen_v2.interest import score_entries


def _quota(value, key):
    return max(0, int(value.get(key, 0) if isinstance(value, dict) else value))


def _ancestors(entries):
    cache = {}
    def closure(name):
        if name not in cache:
            seen = set()
            pending = [name]
            while pending:
                current = pending.pop()
                if current in seen or current not in entries:
                    continue
                seen.add(current)
                pending.extend(entries[current].depends_on)
            cache[name] = frozenset(seen)
        return cache[name]
    return closure


def curate(state, total, per_kind_min=0, per_layer_min=0) -> list[str]:
    """Select at most total entries, keeping all invented dependencies.

    Quotas are minimum targets, not reasons to break dependency closure or the
    total budget. Infeasible quotas are met as far as the budget permits.
    """
    if total <= 0:
        return []
    score_entries(state)
    entries = state.entries
    chosen = set()
    ranked = sorted(entries, key=lambda name: (-entries[name].interest["total"], name))
    closure_cache = {}

    def closure(name):
        if name not in closure_cache:
            visited = set()
            pending = [name]
            while pending:
                current = pending.pop()
                if current in visited or current not in entries:
                    continue
                visited.add(current)
                pending.extend(entries[current].depends_on)
            closure_cache[name] = visited
        return closure_cache[name]

    def add(name):
        required = closure(name) - chosen
        if len(chosen) + len(required) > total:
            return False
        chosen.update(required)
        return True

    kinds = [kind for kind in KINDS if any(entry.kind == kind for entry in entries.values())]
    layers = sorted({entry.layer for entry in entries.values()})
    quotas = [("kind", kind, _quota(per_kind_min, kind)) for kind in kinds]
    quotas += [("layer", layer, _quota(per_layer_min, layer)) for layer in layers]
    while True:
        unmet = [(axis, value, quota - sum(getattr(entries[name], axis) == value for name in chosen))
                 for axis, value, quota in quotas]
        unmet = [(axis, value, remaining) for axis, value, remaining in unmet if remaining > 0]
        if not unmet:
            break
        progressed = False
        for axis, value, _ in sorted(unmet, key=lambda item: (-item[2], str(item[1]))):
            options = [name for name in ranked if name not in chosen and getattr(entries[name], axis) == value
                       and len(closure(name) - chosen) <= total - len(chosen)]
            if options:
                best = min(options, key=lambda name: (len(closure(name) - chosen),
                                                       -entries[name].interest["total"], name))
                progressed |= add(best)
        if not progressed:
            break
    for name in ranked:
        add(name)
    return [name for name in entries if name in chosen]


def _why(state, entry):
    dependencies = [state.entries[name] for name in entry.depends_on if name in state.entries]
    cross = [dependency for dependency in dependencies if dependency.kind != entry.kind]
    parts = [f"layer {entry.layer}"]
    if cross:
        parts.append("uses " + ", ".join(
            {"combinator": "@", "observation": "?", "law": "#", "bridge": "~"}.get(dependency.kind, "")
            + dependency.name + " (" + dependency.kind + ")" for dependency in cross[:3]))
    if entry.interest.get("regularities"):
        parts.append(", ".join(entry.interest["regularities"]) + " on its probe scope")
    runs = len(state.library._steps.get(entry.name, ()))
    if runs:
        parts.append(f"{entry.steps_mean:.1f} layer-0 steps mean of {runs} verified runs on the probe scope".replace(".0 ", " "))
    else:
        parts.append(f"{entry.steps_mean:.1f} layer-0 steps on average (no verified runs recorded)".replace(".0 ", " "))
    dependents = entry.interest.get('distinct_dependents', 0)
    parts.append(f"{dependents} direct invented dependent{'' if dependents == 1 else 's'}")
    return "; ".join(parts)


def _priority(entry, state):
    dependencies = [state.entries[name] for name in entry.depends_on if name in state.entries]
    kinds = {dependency.kind for dependency in dependencies if dependency.kind != entry.kind}
    affordable = entry.steps_mean <= state.world.max_steps * .75
    return (entry.layer >= max(3, state.max_layer() // 2), bool(kinds),
            bool(entry.interest.get("regularities")), affordable,
            entry.layer, entry.interest["total"])


def _diverse(state, candidates, limit):
    entries = state.entries
    closure = _ancestors(entries)
    selected = []
    moves, signatures, fingerprints, dependencies = set(), set(), set(), set()
    while candidates and len(selected) < limit:
        def ranking(name):
            entry = entries[name]
            subtree = closure(name)
            priority = _priority(entry, state)
            diversity = (int(entry.move not in moves) + int(entry.signature not in signatures) +
                         int(entry.fingerprint not in fingerprints) +
                         int(not dependencies.intersection(subtree - {name})))
            return (*priority[:4], diversity, *priority[4:], -len(subtree), name)
        name = max(candidates, key=ranking)
        candidates.remove(name)
        entry = entries[name]
        selected.append(name)
        moves.add(entry.move)
        signatures.add(entry.signature)
        fingerprints.add(entry.fingerprint)
        dependencies.update(closure(name))
    return selected


def featured(state, kind, k) -> list[dict]:
    """Diverse deep definitions of one kind, each with a measured explanation."""
    if k <= 0:
        return []
    score_entries(state)
    choices = [name for name, entry in state.entries.items() if entry.kind == kind]
    return [{"name": name, "why": _why(state, state.entries[name])}
            for name in _diverse(state, choices, k)]


def mark_featured(state, names, k=5) -> list[str]:
    """Mark up to k diverse deep definitions per kind among names as featured, with the measured
    reason; returns the marked names in order."""
    score_entries(state)
    marked = []
    for kind in KINDS:
        choices = [name for name in names if name in state.entries and state.entries[name].kind == kind]
        for name in _diverse(state, choices, k):
            entry = state.entries[name]
            entry.interest["featured"] = True
            entry.interest["featured_why"] = _why(state, entry)
            marked.append(name)
    return marked


def showcase(state, n=16) -> list[dict]:
    """Up to n invented definitions, dependency closed, covering open kinds when feasible.

    The deepest affordable chain is the spine. Remaining slots prefer missing kinds,
    then different moves, signatures and dependency subtrees.
    """
    if n <= 0 or not state.entries:
        return []
    score_entries(state)
    entries = state.entries
    closure = _ancestors(entries)
    eligible = [name for name in entries if len(closure(name)) <= n]
    if not eligible:
        return []
    kinds = set(state.world.open_kinds) & {entries[name].kind for name in eligible}
    ranked = sorted(eligible, key=lambda name: (entries[name].layer, -len(closure(name)),
                                                entries[name].interest["total"], name), reverse=True)

    def cover(spine):
        selected = set(closure(spine))
        for kind in KINDS:
            if kind not in kinds or any(entries[name].kind == kind for name in selected):
                continue
            options = [name for name in eligible if entries[name].kind == kind and
                       len(selected | closure(name)) <= n]
            if not options:
                return None
            candidate = max(options, key=lambda name: (-len(closure(name) - selected),
                                                       _priority(entries[name], state), name))
            selected.update(closure(candidate))
        return selected

    chosen = next((covered for spine in ranked if (covered := cover(spine)) is not None),
                  set(closure(ranked[0])))
    remaining = [name for name in eligible if name not in chosen]
    remaining.sort(key=lambda name: _priority(entries[name], state), reverse=True)
    for name in _diverse(state, remaining[:max(n * 8, 32)], n):
        required = closure(name)
        if len(chosen | required) <= n:
            chosen.update(required)
        if len(chosen) == n:
            break
    return [{"name": name, "why": _why(state, entries[name])} for name in
            sorted(chosen, key=lambda name: (entries[name].layer, name))]


def graph_stats(state) -> dict:
    """Report invented-to-invented graph structure in linear time."""
    entries = state.entries
    by_kind = Counter(entry.kind for entry in entries.values())
    by_layer = Counter(entry.layer for entry in entries.values())
    deps = {name: tuple(dep for dep in entry.depends_on if dep in entries)
            for name, entry in entries.items()}
    outdegree = Counter(dep for dependencies in deps.values() for dep in dict.fromkeys(dependencies))
    depths = {}
    for name in sorted(entries, key=lambda item: entries[item].layer):
        depths[name] = 1 + max((depths.get(dep, 0) for dep in deps[name]), default=0)
    count = len(entries)
    sole = [dependencies[0] for dependencies in deps.values() if len(dependencies) == 1]
    layers = dict(sorted(by_layer.items()))
    return {"counts_per_kind": {kind: by_kind[kind] for kind in KINDS},
            "counts_per_layer": layers, "max_layer": max(layers, default=0),
            "depth_distribution": dict(sorted(Counter(depths.values()).items())),
            "width_per_layer": layers.copy(), "longest_dependency_chain": max(depths.values(), default=0),
            "mean_fan_in": sum(map(len, deps.values())) / count if count else 0.0,
            "mean_fan_out": sum(outdegree.values()) / count if count else 0.0,
            "multi_dependency_share": sum(len(group) >= 2 for group in deps.values()) / count if count else 0.0,
            "chain_likeness": sum(outdegree[dep] == 1 for dep in sole) / count if count else 0.0}


def dedup_report(state) -> dict:
    """Summarize observed duplicate rejections and registered behaviour keys."""
    reasons = Counter(rejection.reason for rejection in state.rejections if rejection.stage == "duplicate"
                      or (rejection.stage == "degenerate" and "same as" in rejection.reason))
    attempted = len(state.entries) + len(state.rejections)
    return {"admitted": len(state.entries), "attempted": attempted,
            "duplicates": sum(reasons.values()), "duplicate_rate": sum(reasons.values()) / attempted if attempted else 0.0,
            "reasons": dict(sorted(reasons.items())), "unique_fingerprints": len(state.fingerprints)}
