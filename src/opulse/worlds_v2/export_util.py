"""Shared helpers for the world exports (docs/assets/data/worlds_v2/<world>.json)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

from opulse.atoms import kernel, nodes
from opulse.atoms.library import atoms_digest, checked_scope
from opulse.atoms.values import Ok, encode, encode_outcome

TRACE_NODES = 150  # call-tree nodes kept per example; the rest is summarised as "elided"
VALUE_CHARS = 1500  # trace inputs/outcomes larger than this (as JSON) are summarised


def bound_evidence(lib, name, evidence, domain=None):
    """Bind locally verified evidence to the definition, the atoms and the checked domain being stored.

    `domain` is the exact sequence of input tuples the local verifier checked; the core records its digest as
    scope["checked"] and invalidates evidence without it (core 4e6ec807).
    """
    scope = dict(evidence.scope)
    if domain is not None:
        scope["checked"] = checked_scope(tuple(tuple(row) for row in domain))
    return replace(evidence, scope=scope, world_hash=evidence.world_hash or lib.world.world_hash(),
                   deps_hash=evidence.deps_hash or lib._deps_hash(name),
                   content_hash=lib.content_hash(name), atoms_hash=atoms_digest(lib.atoms))


def _value(value):
    if isinstance(value, kernel.FnRef):
        return {"fn": value.name}
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [_value(item) for item in value]}
    try:
        return encode(value)
    except (TypeError, ValueError):
        return {"repr": repr(value)}


def _small(value):
    data = _value(value)
    size = len(json.dumps(data, ensure_ascii=False))
    if size <= VALUE_CHARS:
        return data
    return {"elided_value": data.get("t", "value") if isinstance(data, dict) else "value", "chars": size}


def _outcome(outcome):
    return {"ok": _small(outcome.value)} if isinstance(outcome, Ok) else encode_outcome(outcome)


def _size(node) -> int:
    count, stack = 0, [node]
    while stack:  # iterative: kernel traces of deep recursions exceed Python's recursion limit
        current = stack.pop()
        count += 1
        stack.extend(current.children)
    return count


def trace_json(node, max_nodes: int = TRACE_NODES) -> dict:
    """The kernel call tree as JSON, breadth-first up to max_nodes nodes.

    A node whose children were cut carries "elided": the number of call nodes left out below it.
    Steps are always the exact values of the full tree. Trace values longer than VALUE_CHARS are replaced by
    {"elided_value": <sort>, "chars": n}; example inputs and results outside the trace stay complete.
    """
    budget = [max_nodes]

    def visit(current, keep_children):
        data = {"name": current.name, "kind": current.kind, "layer": current.layer, "given": current.given,
                "inputs": [_small(item) for item in current.inputs], "outcome": _outcome(current.outcome),
                "steps": current.steps, "children": []}
        if current.children and not keep_children:
            data["elided"] = _size(current) - 1
        return data

    root = visit(node, True)
    budget[0] -= 1
    queue = [(node, root)]
    while queue:
        current, data = queue.pop(0)
        if "elided" in data:
            continue
        for child in current.children:
            keep = budget[0] > 0
            budget[0] -= 1
            child_data = visit(child, keep and budget[0] > len(child.children))
            if not keep:
                data["elided"] = data.get("elided", 0) + _size(child)
                continue
            data["children"].append(child_data)
            queue.append((child, child_data))
    return root


_CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")


def normalize_zh(value, key: str = ""):
    """Keep Chinese text only in *_zh members: a member whose string holds Chinese gets the suffix _zh.

    Inside a *_zh mapping every member is Chinese by definition and gets the suffix too, so that every key
    that holds Chinese text ends with _zh (the docs checks rely on it).
    """
    if isinstance(value, dict):
        result = {}
        for name, item in value.items():
            if name == "decl":  # the declaration file is stored verbatim
                result[name] = item
                continue
            item = normalize_zh(item, name)
            chinese = _has_cjk(item)
            if chinese and not name.endswith("_zh") and (key.endswith("_zh") or isinstance(item, str)):
                name = f"{name}_zh"
            result[name] = item
        return result
    if isinstance(value, list):
        return [normalize_zh(item, key) for item in value]
    return value


def _has_cjk(value) -> bool:
    if isinstance(value, str):
        return bool(_CJK.search(value))
    if isinstance(value, dict):
        return any(_has_cjk(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_cjk(item) for item in value)
    return False


def finalize_export(data: dict) -> dict:
    """Shared last step of every world export.

    - Chinese text only in *_zh members (normalize_zh);
    - `world_hash`: the core hash (WorldDecl.world_hash) that every evidence record carries; the declaration's
      lock.world_hash is the tasks file hash and differs by design;
    - `design_text` on every story row (the design declaration, possibly prose) and `ascii` only where that text is
      runnable source accepted by the core parser whose parsed body is the real body: the exporter records
      `body_sha256` (body_sha256 of the stored definition) and a row without it, or whose `decl` parses to another
      body, publishes no `ascii`; such a `decl` is not the definition and is dropped (rows: with L<n> = def_layer;
      examples: the evaluated expression);
    - `example_steps`: min/max layer-0 steps over the shown examples (cost.steps covers the verification family).
    """
    from opulse.atoms.world import WorldDecl

    data = normalize_zh(data)
    if isinstance(data.get("decl"), dict):
        data["world_hash"] = WorldDecl.from_dict(data["decl"]).world_hash()
    for row in data.get("story", ()):
        if "design_layer" in row:  # one convention: layer = design row, def_layer = computed dependency layer
            row["def_layer"] = row["layer"]
            row["layer"] = row.pop("design_layer")
        row.pop("ascii", None)
        source = parseable_declaration(row.get("decl"), row.get("def_layer"))
        if source is not None and not source_matches(source, row.get("body_sha256")):
            row.pop("decl")  # parseable text with another body: never publish it as the definition
            source = None
        row["design_text"] = row.get("design_decl") or row.get("decl") or row.get("symbol") or row.get("name")
        if source is not None:
            row["ascii"] = source
        steps = []
        for example in row.get("examples", ()):
            example.pop("ascii", None)
            if parseable_expression(example.get("text")):
                example["ascii"] = example["text"]
            if type(example.get("steps")) is int:
                steps.append(example["steps"])
        if steps:
            row["example_steps"] = {"min": min(steps), "max": max(steps)}
    for items in (data.get("layer0") or {}).values():
        for item in items if isinstance(items, list) else ():
            if isinstance(item, dict):
                item.pop("ascii", None)
                source = parseable_declaration(item.get("decl"), None)
                if source is not None:
                    item["ascii"] = source
    from opulse.notation3.export import add_notation3

    return add_notation3(data, 'worlds_v2') if data.get('world') else data


_LAYER = re.compile(r"\s(?:L\d+|given)\s*$")


def parseable_declaration(text, def_layer):
    """The declaration as runnable ASCII source, or None when it is design prose the core parser rejects.

    A parseable declaration carries the computed dependency layer (review R11-W-2): its trailing L<n> is
    replaced by def_layer when one is known.
    """
    from opulse.atoms import notation

    if not isinstance(text, str) or not text.strip():
        return None
    if def_layer is not None and _LAYER.search(text) and not text.rstrip().endswith(" given"):
        text = _LAYER.sub(f" L{def_layer}", text)
    try:
        notation.parse_definition(text)
    except notation.NotationError:  # design prose stays design_text only
        return None
    return text


def body_sha256(body) -> str:
    """Digest of a definition body (the kernel node tree), used to bind published ASCII to the real body."""
    if isinstance(body, nodes.NODE_TYPES) or body is None or isinstance(body, (str, int, tuple)):
        data = nodes.to_json(body)
    else:
        data = {"repr": repr(body)}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _declared_binders(definition):
    """Names an operation, combinator or observation declaration binds for its body (None: no check)."""
    from opulse.atoms.spec import CombinatorSpec, ObservationSpec, OperationSpec

    spec = definition.spec
    if isinstance(spec, OperationSpec):
        return {edge.name for edge in spec.inputs if edge.name}
    if isinstance(spec, CombinatorSpec):
        return set(spec.params) | set(spec.op_params)
    if isinstance(spec, ObservationSpec):
        subject = (spec.extra or {}).get("subject")
        return {subject} if isinstance(subject, str) else set()
    return None


def source_matches(text, digest) -> bool:
    """True when the ASCII declaration parses to a definition whose body has the given digest and whose
    header binds every variable of that body (a printed header with another parameter name is not the
    definition)."""
    from opulse.atoms import notation
    from opulse.atoms.spec import _free_vars

    if not digest or not isinstance(text, str):
        return False
    try:
        parsed = notation.parse_definition(text)
    except notation.NotationError:
        return False
    if body_sha256(parsed.body) != digest:
        return False
    binders = _declared_binders(parsed)
    return binders is None or not isinstance(parsed.body, nodes.NODE_TYPES) or \
        not _free_vars(parsed.body, frozenset(binders))


def parseable_expression(text) -> bool:
    from opulse.atoms import notation

    if not isinstance(text, str) or not text.strip():
        return False
    try:
        notation.parse_expr(text)
    except notation.NotationError:
        return False
    return True
