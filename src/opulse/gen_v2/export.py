"""Deterministic per-world generator exports for the site and datasets."""

from __future__ import annotations

import json
from collections import Counter
from itertools import product
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.values import Card, decode
from opulse.gen_v2.base import KINDS, count_summary, signature_data
from opulse.gen_v2.codec import encode_outcome
from opulse.gen_v2.codec import encode_value as encode
from opulse.gen_v2.notation import print_declaration, print_node, tokens


def _has_host(data) -> bool:
    if isinstance(data, dict):
        return data.get("t") == "host" or any(_has_host(item) for item in data.values())
    if isinstance(data, list):
        return any(_has_host(item) for item in data)
    return False


def _legacy_value(value):
    """Legacy worlds use Python bools; the generator codec reads them back as bool cards."""
    if isinstance(value, Card) and value.sort == "bool" and value.tag in ("true", "false") and not value.fields:
        return value.tag == "true"
    if isinstance(value, tuple):
        return tuple(_legacy_value(item) for item in value)
    return value


def _published_form(value) -> bool:
    from opulse.atoms.golden import decode as decode_published

    try:
        decode_published(value)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    return True


def _check_world(state):
    state.library._sync_world(full=True)
    if state.world.decl.world_hash() != state.library.world.world_hash():
        raise ValueError("world declaration changed since generator verification")


def _encode_example(value, state, sort=None):
    from opulse.atoms.values import Bottom

    if isinstance(value, Bottom):
        return encode(value)
    if state.world.dialect == "legacy-v1":
        from opulse.gen_v2.legacy_import import encode_published_value

        return encode_published_value(state.world.name, value, sort)
    return encode(value)


def _encode_example_outcome(outcome, state, sort=None):
    from opulse.atoms.values import Ok

    if state.world.dialect == "legacy-v1" and isinstance(outcome, Ok):
        return {"ok": _encode_example(outcome.value, state, sort)}
    return encode_outcome(outcome)


def _selected(state, selection):
    names = None if selection is None else {item.name if hasattr(item, "name") else item for item in selection}
    return sorted((entry for entry in state.entries.values() if names is None or entry.name in names),
                  key=lambda entry: (entry.layer, entry.kind, entry.name))


def _graph(entries, state=None):
    if state is not None and len(entries) == len(state.entries):
        try:
            from opulse.gen_v2.curate import graph_stats

            return json.loads(json.dumps(graph_stats(state), sort_keys=True))  # JSON keys are strings
        except ImportError:
            pass
    return _graph_minimal(entries)


def _graph_minimal(entries):
    names = {entry.name for entry in entries}
    edges = [(entry.name, dep) for entry in entries for dep in entry.depends_on if dep in names]
    return {"nodes": len(entries), "edges": len(edges),
            "max_layer": max((entry.layer for entry in entries), default=0),
            "roots": sum(not any(dep in names for dep in entry.depends_on) for entry in entries),
            "reused": len({dependency for _, dependency in edges})}


def _example_rows(entry, state):
    if entry.kind != "combinator":
        yield from entry.examples
        return
    spec = state.library.get(entry.name).spec
    request = state.requests[entry.name]
    families = entry.meta["slot_families"]
    scope = state.library.scope()
    count = 0
    for assignment in product(*(families[slot] for slot in spec.op_params)):
        plugged = dict(zip(spec.op_params, assignment))
        for values in request.domain:
            if count >= 8:
                return
            arguments = iter(values)
            inputs = tuple(kernel.FnRef(plugged[param]) if param in plugged else next(arguments)
                           for param in spec.params)
            run = kernel.call(entry.name, inputs, scope, kernel.Limits(fuel=state.world.fuel),
                              dialect=state.world.dialect)
            yield inputs, run.outcome, run.steps
            count += 1


def _call_text(entry, inputs, op_count=0):
    if entry.kind == "combinator":
        slots = ", ".join(value.name for value in inputs[:op_count])
        values = ", ".join(print_node(nodes.Lit(value)) for value in inputs[op_count:])
        return f"@{entry.name}[{slots}]({values})"
    values = ", ".join(print_node(nodes.Lit(value)) for value in inputs)
    if entry.kind == "observation" and len(inputs) == 1:
        return f"?{entry.name}{{{values}}}"
    if entry.kind == "object":
        if len(inputs) == 1 and isinstance(inputs[0], Card) and inputs[0].sort == entry.name:
            return print_node(nodes.Lit(inputs[0]))
        return f"{entry.name}<{values}>"
    if entry.kind in ("law", "bridge"):
        return ("#" if entry.kind == "law" else "~") + entry.name + "(" + values + ")"
    return f"{entry.name}({values})"


def _examples(entry, state, dropped=None):
    examples = []
    for inputs, outcome, steps in _example_rows(entry, state):
        try:
            text_format = "notation"
            sorts = entry.signature.inputs if entry.signature else ()
            encoded = [_encode_example(item, state, sorts[index] if index < len(sorts) else None)
                       for index, item in enumerate(inputs)]
            if isinstance(outcome, dict) and state.world.dialect == "legacy-v1" and _has_host(outcome):
                # Stored examples use the generator codec; legacy host values (robot states) are
                # re-run here so the published value codec can encode them reproducibly.
                outcome = kernel.call(entry.name, tuple(inputs), state.library.scope(),
                                      kernel.Limits(fuel=state.world.fuel), dialect=state.world.dialect).outcome
            elif (isinstance(outcome, dict) and state.world.dialect == "legacy-v1" and "ok" in outcome
                  and not _published_form(outcome["ok"])):
                # Outcomes stored in the generator codec (e.g. grid values as tuples, bools as cards)
                # are re-encoded with the world's published codec; imported legacy outcomes are
                # already in that form.
                from opulse.atoms.values import Ok
                from opulse.gen_v2.codec import decode_value

                outcome = Ok(_legacy_value(decode_value(outcome["ok"])))
            result = outcome if isinstance(outcome, dict) else _encode_example_outcome(
                outcome, state, entry.signature.output if entry.signature else None)
            if any(item.get("t") == "host" for item in encoded) or (result and result.get("ok", {}).get("t") == "host"):
                raise TypeError("host value has no reproducible encoding")
            if entry.kind == "law":
                spec = state.library.get(entry.name).spec
                recipe = {"kind": "law", "name": entry.name, "inputs": encoded,
                          "vars": [name for name, _ in spec.vars]}
                text = print_node(spec.statement, state)
            elif entry.kind == "bridge":
                recipe = {"kind": "bridge", "name": entry.name, "inputs": encoded}
                text = _call_text(entry, inputs)
            elif entry.kind == "object":
                spec = state.library.get(entry.name).spec
                value = inputs[0] if spec.form == "compose" else None
                if spec.form == "refine":
                    replay_name, replay_inputs = f"{entry.name}.make", (inputs[0],)
                elif spec.form == "constant":
                    replay_name, replay_inputs = entry.name, ()
                else:
                    replay_name, replay_inputs = f"{entry.name}.{value.tag}", tuple(value.fields)
                recipe = {"kind": "call", "name": replay_name,
                          "inputs": [_encode_example(item, state) for item in replay_inputs]}
                text = f"{replay_name}(" + ", ".join(
                    print_node(nodes.Lit(item)) for item in replay_inputs) + ")"
            elif entry.kind == "observation":
                from opulse.gen_v2.kinds.observations import (
                    _history,
                    _probe_values,
                    _read_arguments,
                )

                spec = state.library.get(entry.name).spec
                scope = state.library.scope()
                arguments = _read_arguments(state, state.library.get(entry.name), scope)
                history = _history(inputs, spec.memory)
                reads = []
                probe_calls = []
                for truth_state in history:
                    values, _, error = _probe_values(state, spec.reads, truth_state, scope, arguments)
                    if error is not None:
                        break
                    reads.append({name: _encode_example(value, state) for name, value in values.items()})
                    probe_calls.append([
                        {"name": probe, "alias": alias,
                         "inputs": [_encode_example(truth_state, state),
                                    *(_encode_example(value, state) for value in fixed)],
                         "outcome": {"ok": _encode_example(values[alias], state)}}
                        for probe in spec.reads for fixed, alias in arguments[probe]])
                recipe = {"kind": "observation", "history": [_encode_example(value, state) for value in history],
                          "reads": reads, "probe_calls": probe_calls}
                text = _call_text(entry, inputs)
            elif state.world.dialect == "legacy-v1":
                from opulse.gen_v2.notation import _value

                try:
                    text = entry.name + "(" + ", ".join(_value(value) for value in inputs) + ")"
                except TypeError:
                    text = entry.name + "(" + ", ".join(
                        json.dumps(item, ensure_ascii=True, sort_keys=True) for item in encoded) + ")"
                    text_format = "legacy_json"
                recipe = {"kind": "call", "name": entry.name, "inputs": encoded}
            else:
                text = _call_text(entry, inputs, len(entry.signature.op_inputs) if entry.kind == "combinator" else 0)
                recipe = {"kind": "call", "name": entry.name, "inputs": encoded}
        except (TypeError, ValueError) as error:
            if state.world.dialect == "legacy-v1":
                raise ValueError(f"{state.world.name}/{entry.name}: unencodable example: {error}") from error
            if dropped is not None:
                dropped[f"{type(error).__name__}: {error}"] += 1
            continue
        if result is None:
            if state.world.dialect == "legacy-v1":
                raise ValueError(f"{state.world.name}/{entry.name}: example has no outcome")
            if dropped is not None:
                dropped["example has no outcome"] += 1
            continue
        examples.append({"text": text, "text_tokens": tokens(text, state),
                         "text_format": text_format, "copyable": text_format == "notation",
                         "inputs": encoded, "replay": recipe, "outcome": result, "steps": steps})
    return examples


def _spec_data(defn):
    """The core spec dict plus the declared tag order: JSON files are written with sorted keys,
    and the order of an object's tags decides its fold handler order."""
    spec = defn.to_dict()["spec"]
    tags = getattr(defn.spec, "tags", None)
    if isinstance(spec, dict) and isinstance(tags, dict) and tags:
        spec["tag_order"] = list(tags)
    return spec


def _entry(state, entry, dropped=None):
    defn = state.library.get(entry.name)
    signature = entry.signature
    interest = entry.interest
    featured = bool(interest.get("featured", entry.meta.get("featured", False)))
    entry_dropped = Counter()
    examples = _examples(entry, state, entry_dropped)
    if dropped is not None:
        dropped.update(entry_dropped)
    try:
        ascii_text = print_declaration(entry, state)
    except TypeError:
        if state.world.dialect != "legacy-v1":
            raise
        spec = defn.spec
        input_names = spec.extra.get("input_names", [f"arg{index}" for index in range(len(spec.inputs))])
        parameters = ", ".join(f"{name}: {edge.sort}" for name, edge in zip(input_names, spec.inputs))
        ascii_text = (f"op {entry.name}({parameters}) -> {spec.output.sort} = legacy_json(" +
                      json.dumps(nodes.to_json(defn.body), sort_keys=True, ensure_ascii=True) +
                      f")  L{entry.layer}")
    return {"name": entry.name, "display": {"combinator": "@", "observation": "?", "law": "#", "bridge": "~"}.get(entry.kind, "") + entry.name,
            "kind": entry.kind, "layer": entry.layer, "move": entry.move,
            "signature": signature_data(signature),
            "depends_on": list(entry.depends_on), "ascii": ascii_text,
            "tokens": tokens(ascii_text, state),
            "body": nodes.to_json(defn.body) if isinstance(defn.body, nodes.NODE_TYPES) else defn.body,
            "spec": _spec_data(defn),
            "status": defn.status,
            "evidence": defn.evidence.to_dict() if defn.evidence else None,
            "contract": defn.contract.to_dict() if defn.contract else None,
            "cost": defn.cost.to_dict(), "interest": interest,
            "examples": examples, "examples_dropped": dict(sorted(entry_dropped.items())),
            "featured": featured}


def _trace_node(node, state):
    signature = state.signature(node.name) if node.name else None
    sorts = signature.inputs if signature else ()
    return {"name": node.name, "kind": node.kind, "layer": node.layer, "given": node.given,
            "inputs": [_encode_example(value, state, sorts[index] if index < len(sorts) else None)
                       for index, value in enumerate(node.inputs)],
            "outcome": _encode_example_outcome(node.outcome, state, signature.output if signature else None),
            "steps": node.steps, "children": [_trace_node(child, state) for child in node.children]}


def _decode_example(value, state):
    if value["t"] == "bottom":
        from opulse.atoms.values import Bottom

        return Bottom(value["v"])
    if state.world.dialect == "legacy-v1":
        from opulse.atoms.golden import decode as decode_published

        return decode_published(value)
    if value["t"] == "fn":
        return kernel.FnRef(value["v"])
    if value["t"] == "tuple":
        return tuple(_decode_example(item, state) for item in value["v"])
    if "tag" in value:  # cards may hold a Bottom field (a failed component inside a record)
        return Card(value["t"], value["tag"], tuple(_decode_example(item, state) for item in value.get("f", ())))
    return decode(value)


def export_story(state, names=None) -> list[dict]:
    """Export showcase definitions with call trees (value leaves for non-callable kinds)."""
    _check_world(state)
    if names is None:
        names = [entry.name for entry in _selected(state, None)
                 if entry.interest.get("featured", entry.meta.get("featured", False))]
    scope = state.library.scope()
    stories = []
    for entry in _selected(state, names):
        row = _entry(state, entry)
        examples = []
        for example in row["examples"]:
            try:
                args = tuple(_decode_example(value, state) for value in example["inputs"])
            except ValueError:
                args = None
            trace = None
            if args is not None and entry.kind == "observation" and not state.library.get(entry.name).spec.memory:
                from opulse.gen_v2.kinds.observations import _expand, _probe_values

                try:
                    values, _, error = _probe_values(state, state.library.get(entry.name).spec.reads,
                                                      args[0], scope)
                except (TypeError, KeyError) as problem:  # probes with fixed arguments: no plain read
                    values, error = {}, problem
                if error is None:
                    body = _expand(state.library.get(entry.name).body, state, scope, (args[0],), {})
                    run = kernel.evaluate(body, {**values, "__truth": args[0]}, scope,  # fixed-argument reads
                                          kernel.Limits(fuel=state.world.fuel, max_nodes=512),
                                          trace=True, dialect=state.world.dialect)
                    trace = run.trace
            elif args is not None and entry.kind not in ("object", "observation") and scope.resolve(entry.name) is not None:
                run = kernel.call(entry.name, args, scope,
                                  kernel.Limits(fuel=state.world.fuel, max_nodes=512),
                                  trace=True, dialect=state.world.dialect)
                trace = run.trace
            rendered = _trace_node(trace.children[0], state) if trace and trace.children else None
            if entry.kind == "observation" and trace:
                rendered = {"name": entry.name, "kind": "observation", "layer": entry.layer, "given": False,
                            "inputs": example["inputs"], "outcome": example["outcome"],
                            "steps": example["steps"], "children": [_trace_node(child, state) for child in trace.children]}
            if rendered is None:
                rendered = {"name": entry.name, "kind": entry.kind, "layer": entry.layer, "given": False,
                            "inputs": example["inputs"], "outcome": example["outcome"],
                            "steps": example["steps"], "children": []}
            examples.append({"text": example["text"], "inputs": example["inputs"], "replay": example["replay"],
                             "outcome": example["outcome"], "steps": example["steps"],
                             "trace": rendered})
        stories.append({key: row[key] for key in ("layer", "kind", "name", "depends_on", "body",
                                                 "status", "evidence", "contract", "cost")}
                       | {"symbol": row["display"], "examples": examples,
                          "examples_dropped": row["examples_dropped"]})
    return stories


def _templates_payload(state) -> dict:
    """Template records (generator-side until core template records exist) with ASCII text."""
    from opulse.gen_v2 import templates

    return templates.template_export_payload(state)


def _templates_md(state) -> str:
    from opulse.gen_v2 import templates

    return templates.template_summary_md(state) if templates.templates_for(state) else ""


def _payload(state, selection=None):
    _check_world(state)
    entries = _selected(state, selection)
    rejected = Counter(item.stage for item in state.rejections)
    by_move = Counter(item.move for item in state.rejections)
    dropped = Counter()
    exported = [_entry(state, entry, dropped) for entry in entries]
    return {"schema": "opulse.gen_v2/1", "world": state.world.name, "title": state.world.title,
            "tags": dict(getattr(state.world, "tags", {}) or {}),
            "version": state.world.decl.version, "open_kinds": sorted(state.world.open_kinds),
            "seed": state.seed, "counts": count_summary(entries), "graph": _graph(entries, state),
            "entries": exported, "examples_dropped": {reason: count for reason, count in sorted(dropped.items())},
            "rejections_summary": {"stage": dict(sorted(rejected.items())), "by_move": dict(sorted(by_move.items()))},
            **_templates_payload(state)}


def export(state, path, selection=None) -> dict:
    """Write the full, reproducible opulse.gen_v2/1 JSON and return its data."""
    data = _payload(state, selection)
    Path(path).write_text(json.dumps(data, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return data


def export_summary_md(state) -> str:
    """Short English overview of generated counts, depths and featured atoms."""
    data = _payload(state)
    counts = data["counts"]
    lines = [f"# {data['world']} generator summary", "", "## Counts by kind",
             *[f"- {kind}: {counts['per_kind'][kind]}" for kind in KINDS], "", "## Depth distribution",
             *[f"- L{layer}: {count}" for layer, count in counts["per_layer"].items()], ""]
    for kind in KINDS:
        featured = [item for item in data["entries"] if item["kind"] == kind and item["featured"]]
        lines += [f"## Featured {kind}s", *[f"- `{item['ascii']}`" for item in featured[:5]], ""]
    section = _templates_md(state)
    if section:
        lines += [section, ""]
    return "\n".join(lines)


def export_compact(state, path, max_entries=100, selection=None) -> dict:
    """Write a site-friendly subset without body trees or bulky specs."""
    data = _payload(state, selection)
    data["entries"] = [{key: value for key, value in item.items() if key not in ("body", "spec")}
                       for item in data["entries"][:max_entries]]
    data["examples_dropped"] = dict(sorted(sum((Counter(item["examples_dropped"])
                                                  for item in data["entries"]), Counter()).items()))
    data["counts"] = count_summary(_selected(state, [item["name"] for item in data["entries"]]))
    data["graph"] = _graph(_selected(state, [item["name"] for item in data["entries"]]))
    Path(path).write_text(json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return data


def export_jsonl(state, path, selection=None) -> int:
    """Write one complete definition per line, ordered by layer, kind, name."""
    entries = [_entry(state, entry) for entry in _selected(state, selection)]
    Path(path).write_text("".join(json.dumps(item, sort_keys=True, ensure_ascii=True) + "\n" for item in entries),
                          encoding="utf-8")
    return len(entries)
