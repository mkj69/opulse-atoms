"""Build the computer@2 depth export from checked kernel executions."""

import hashlib
import json
from copy import copy
from pathlib import Path

from opulse.atoms import kernel, nodes
from opulse.atoms.values import Bottom, Card, Ok, encode, encode_outcome

from . import hosts
from .story import TOWER, build_library, vector, vector_fields, wide_fields

META = Path(__file__).with_name("metadata.json")
OUTPUT = Path(__file__).resolve().parents[4] / "docs/assets/data/worlds_v2/computer.json"
GRADING = Path(__file__).with_name("data") / "showcase_grading.json"
TRACE_NODES = 150
VALUE_CHARS = 1500


def _trace_value(value):
    if isinstance(value, Card) and value.sort == "Machine":
        return "Machine<sealed>"
    if isinstance(value, kernel.FnRef):
        return {"fn": value.name}
    if isinstance(value, tuple):
        return {"t": "tuple", "v": [_trace_value(item) for item in value]}
    try:
        return encode(value)
    except (TypeError, ValueError):
        return {"repr": repr(value)}


def _small(value):
    data = _trace_value(value)
    size = len(json.dumps(data, ensure_ascii=False))
    if size <= VALUE_CHARS:
        return data
    return {"elided_value": data.get("t", "value") if isinstance(data, dict) else "value", "chars": size}


def _trace_outcome(outcome):
    return {"ok": _small(outcome.value)} if isinstance(outcome, Ok) else encode_outcome(outcome)


def _trace_size(node):
    return 1 + sum(_trace_size(child) for child in node.children)


def trace_json(node, max_nodes=TRACE_NODES):
    """Encode a call tree breadth-first, preserving exact steps and elision counts."""
    budget = [max_nodes]

    def visit(current, keep_children):
        data = {"name": current.name, "kind": current.kind, "layer": current.layer,
                "given": current.given, "inputs": [_small(item) for item in current.inputs],
                "outcome": _trace_outcome(current.outcome), "steps": current.steps, "children": []}
        if current.children and not keep_children:
            data["elided"] = _trace_size(current) - 1
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
                data["elided"] = data.get("elided", 0) + _trace_size(child)
                continue
            data["children"].append(child_data)
            queue.append((child, child_data))
    return root


def portable(value):
    if isinstance(value, kernel.FnRef):
        return {"t": "fn", "v": value.name}
    return encode(hosts.to_card(value))


def outcome_json(outcome):
    return {"ok": portable(outcome.value)} if isinstance(outcome, Ok) else (
        {"bottom": outcome.reason} if hasattr(outcome, "reason") else {"unknown": outcome.resource})


def notation(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    if isinstance(value, Card):
        if value.sort == "Machine":
            return "s"
        if value.sort == "Vec":
            start, length = vector_fields(value)
            return f"Vec<start={start},len={length}>"
        if value.sort == "Wide":
            lo, mid, hi = wide_fields(value)
            return f"Wide<lo={lo},mid={mid},hi={hi}>"
        return f"{value.sort}<{','.join(notation(item) for item in value.fields)}>"
    return str(value) if type(value) is not bool else str(value).lower()


def example_cases():
    first = [17, 29, 43, 61, 79, 101, 127, 149]
    second = [13, 23, 37, 41, 53, 67, 71, 83]
    common = hosts.state(changes={**dict(enumerate(first, 16)), **dict(enumerate(second, 64))})
    left, right = vector(16, 8), vector(64, 8)
    return {
        "@while_b": (kernel.FnRef("mul_tick"), hosts.state((5, 3, 4, 91), pc=77, fill=7)),
        "mul_into": (hosts.state((5, 13, 20, 91), pc=77),),
        "Vec": (hosts.vec(16, 8),),
        "?at": (hosts.state(changes=dict(enumerate(first, 16))), 18),
        "dot_step": (hosts.state(changes={16: 17, 64: 13, 255: 9}), 16, 64),
        "@zip_fold": (kernel.FnRef("dot_step"),
                      hosts.state(changes={**dict(enumerate(first, 16)),
                                           **dict(enumerate(second, 64)), 255: 9}), left, right),
        "dot": (common, left, right),
        "mul_carry": (201, 173),
        "Wide": (hosts.wide(198, 145, 0),),
        "wide_dot": (common, left, right),
        "?dot_wrap": (hosts.state(changes={16: 201, 64: 173}), vector(16, 1), vector(64, 1)),
    }


def visible(name, result):
    if name in ("@while_b", "mul_into"):
        return [hosts.out(result), hosts.b(result), hosts.pc(result), hosts.z(result)]
    if name == "Vec":
        return list(vector_fields(result))
    if name in ("dot_step", "@zip_fold", "dot"):
        return [hosts.d(result), hosts.fields(result)[1][255], hosts.pc(result)]
    if name in ("Wide", "wide_dot"):
        return list(wide_fields(result))
    return result


def checked_run(lib, name, args):
    result = lib.run(name, args)
    assert isinstance(result.outcome, Ok), (name, result.outcome)
    return result.outcome.value


def showcase(lib, metadata):
    result = []
    grading = []
    first = [17, 29, 43, 61, 79, 101, 127, 149, 163, 181, 197, 211, 223, 229, 241, 253]
    second = [13, 23, 37, 41, 53, 67, 71, 83, 97, 103, 109, 113, 131, 137, 139, 151]
    state = hosts.state(changes={**dict(enumerate(first, 16)), **dict(enumerate(second, 64))})
    x, y = vector(16, 16), vector(64, 16)
    compute = {"wide": list(wide_fields(checked_run(lib, "wide_dot", (state, x, y)))),
               "dot": hosts.d(checked_run(lib, "dot", (state, x, y))),
               "wrap": checked_run(lib, "?dot_wrap", (state, x, y))}
    grading.append({"angle": "Compute", "answer": compute, "machines": [portable(state)]})
    result.append({"angle": metadata[0]["angle"], "prompt": metadata[0]["prompt"],
                   "why_hard_zh": metadata[0]["why_hard_zh"], "check_zh": metadata[0]["check_zh"],
                   "answer": compute, "answer_checked": True,
                   "check_method": "Kernel executions of wide_dot, dot and ?dot_wrap over the full machine."})

    changes = {**dict(enumerate([4, 0, 13, 7, 19, 23, 5, 11], 32)),
               **dict(enumerate([17, 29, 9, 0, 6, 12, 27, 3], 40))}
    x, y = vector(32, 8), vector(40, 8)
    base = list(wide_fields(checked_run(lib, "wide_dot", (hosts.state(changes=changes), x, y))))
    changes[33] = 1
    delta_x = list(wide_fields(checked_run(lib, "wide_dot", (hosts.state(changes=changes), x, y))))
    changes[33] = 0
    changes[43] = 1
    delta_y = list(wide_fields(checked_run(lib, "wide_dot", (hosts.state(changes=changes), x, y))))

    def integer(triple):
        return triple[0] + 256 * triple[1] + 65536 * triple[2]

    solutions = []
    for unknown_x in range(32):
        for unknown_y in range(32):
            if (integer(base) + unknown_x * (integer(delta_x) - integer(base)) +
                    unknown_y * (integer(delta_y) - integer(base))) != 1369:
                continue
            changes[33], changes[43] = unknown_x, unknown_y
            observed = list(wide_fields(checked_run(lib, "wide_dot", (hosts.state(changes=changes), x, y))))
            if integer(observed) == 1369:
                solutions.append([unknown_x, unknown_y])
    grading.append({"angle": "Invert", "answer": solutions,
                    "machines": [portable(hosts.state(changes=changes))]})
    result.append({**metadata[1], "answer": solutions, "answer_checked": True,
                   "check_method": "Three kernel wide_dot runs derive independent byte coefficients; "
                                   "all 1024 pairs are filtered by the exact affine equation and "
                                   "every surviving answer is rechecked by kernel wide_dot."})

    first = [21, 33, 47, 58, 69, 72, 85, 96, 107, 118, 129, 140]
    second = [119, 108, 97, 86, 75, 64, 53, 42, 31, 20, 9, 254]
    changes = {**dict(enumerate(first, 80)), **dict(enumerate(second, 120))}
    state = hosts.state(changes=changes)
    changes[91] = 12
    altered = hosts.state(changes=changes)
    x, y = vector(80, 12), vector(120, 12)
    modular = [hosts.d(checked_run(lib, "dot", (machine, x, y))) for machine in (state, altered)]
    exact = [list(wide_fields(checked_run(lib, "wide_dot", (machine, x, y))))
             for machine in (state, altered)]
    decide = {"same_modular": modular[0] == modular[1], "same_wide": exact[0] == exact[1],
              "modular": modular, "wide": exact}
    allowed = tuple(range(80, 92)) + tuple(range(120, 132))
    grants = {"probes": ["?d", "?out"], "memory_probe": "?at",
              "memory_ranges": [[80, 91], [120, 131]]}
    prompt = ("Sealed machines M and N have Vec<80,12> and Vec<120,12>. "
              "The only granted probes are ?d and ?out; ?at is limited to cells "
              "80..91 and 120..131. M yields List<21,33,47,58,69,72,85,96,107,118,129,140> "
              "and List<119,108,97,86,75,64,53,42,31,20,9,254> there. "
              "N has the same granted cells except ?at{N,91}=12. "
              "Decide whether ?d{dot(M,x,y)} equals ?d{dot(N,x,y)} and whether "
              "wide_dot(M,x,y) equals wide_dot(N,x,y); report both dot bytes and Wide triples.")
    grading.append({"angle": "Decide", "answer": decide,
                    "machines": [portable(state), portable(altered)]})
    play_library = copy(lib)
    play_library.agent = "play"
    result.append({"angle": metadata[2]["angle"], "prompt": prompt,
                   "why_hard_zh": metadata[2]["why_hard_zh"], "check_zh": metadata[2]["check_zh"],
                   "answer": decide, "answer_checked": True,
                   "check_method": "Two kernel dot and two kernel wide_dot runs on independent full states.",
                   "grants": grants,
                   "learner_view": {"machines": [
                       {"label": label, "cells": {str(index): checked_run(play_library, "?at", (machine, index))
                                                 for index in allowed},
                        "?d": checked_run(lib, "?d", (machine,)),
                        "?out": checked_run(lib, "?out", (machine,))}
                       for label, machine in (("M", state), ("N", altered))]}})
    return result, grading


def build_export(*, with_grading=False):
    meta = json.loads(META.read_text(encoding="utf-8"))
    lib = build_library()
    world = lib.world.to_dict()
    cases = example_cases()
    story = []
    for index, name in enumerate(TOWER):
        definition = lib.get(name)
        name_to_run = f"{name}.make" if name in ("Vec", "Wide") else name
        args = cases[name]
        run = lib.run(name_to_run, args, trace=True)
        assert isinstance(run.outcome, Ok), (name, run.outcome)
        assert visible(name, run.outcome.value) == meta["tower"][index]["reference_value"]
        expression = (f"{name_to_run}[{notation(args[0])}]({','.join(notation(arg) for arg in args[1:])})"
                      if name.startswith("@") else
                      f"{name_to_run}({','.join(notation(arg) for arg in args)})")
        example = {"text": expression, "inputs": [_small(value) for value in args],
                   "outcome": _trace_outcome(run.outcome), "steps": run.steps, "trace": trace_json(run.trace),
                   "learner_view": {"input": "s:Machine<sealed>",
                                    "result": visible(name, run.outcome.value)} }
        source = meta["tower"][index]
        story.append({"layer": index + 1, "def_layer": definition.layer, "kind": definition.kind,
                      "name": name, "symbol": name, "decl": source["decl"],
                      "title": f"{name} in the byte-machine tower",
                      "definition": f"Unfold {name} into layer-zero machine actions and checks.",
                      "plain_zh": source["plain_zh"], "title_zh": source["plain_zh"].split("，")[0],
                      "definition_zh": source["plain_zh"], "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body) if definition.body else None,
                      "status": definition.status,
                      "evidence": definition.evidence.to_dict() if definition.evidence else None,
                      "contract": definition.contract.to_dict() if definition.contract else None,
                      "cost": definition.cost.to_dict(),
                      "examples": [example]})
    failure_args = (kernel.FnRef("dot_step"), cases["dot"][0], vector(16, 2), vector(64, 1))
    failed = lib.run("@zip_fold", failure_args, trace=True)
    assert failed.outcome == Bottom("zip_length_mismatch")
    failure_text = (f"@zip_fold[dot_step]({notation(failure_args[1])},"
                    f"{notation(failure_args[2])},{notation(failure_args[3])})")
    story[5]["examples"].append({"text": failure_text,
                                  "inputs": [_small(item) for item in failure_args],
                                  "outcome": outcome_json(failed.outcome), "steps": failed.steps,
                                  "trace": trace_json(failed.trace),
                                  "learner_view": {"input": "s:Machine<sealed>",
                                                   "result": "zip_length_mismatch"}})
    layer0 = {"objects": [], "operations": [], "combinators": [], "observations": []}
    for category, entries in meta["layer0"].items():
        for entry in entries:
            declaration = entry["decl"]
            name = declaration.split()[1].split("(")[0].split("[")[0].split("{")[0]
            layer0[category].append({"name": name, "decl": declaration,
                                     "title": f"Given {name}", "definition": f"Layer-zero {name} interface.",
                                     "doc_zh": entry["doc_zh"]})
    layer0["combinators"] = {**world["combinators"], "entries": layer0["combinators"]}
    layer0["observation"] = {**world["observation"], "probes": [
        {**probe, **layer0["observations"][index]} for index, probe in enumerate(world["observation"]["probes"])]}
    public_showcase, grading = showcase(lib, meta["showcase"])
    grading_bytes = (json.dumps({"schema": "opulse.computer2.grading/1", "showcase": grading},
                               sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode("utf-8")
    export = {"schema": "opulse.world_v2_export/1", "world": "computer", "version": 2,
            "wave": 2, "title": "Deep Eight-Bit Computer", "title_zh": meta["title_zh"],
            "pitch_zh": meta["pitch_zh"], "tower_source": "depth", "decl": world,
            "layer0": layer0, "story": story, "ladder": meta["ladder"],
            "showcase": public_showcase, "grading_sha256": hashlib.sha256(grading_bytes).hexdigest(),
            "modalities_zh": meta["modalities_zh"],
            "toy_risk_zh": meta["toy_risk_zh"], "tags": world["tags"],
            "open_kinds": world["open_kinds"],
            "fuel_note": {"cap": None, "termination": "@while_b uses decreasing B, not fuel 256.",
                          "worst_case_steps": {"@while_b": 2046, "mul_into": 2046,
                                               "dot_32": 70681, "wide_dot_32": 119255},
                          "context": "@while_b uses mul_tick (the generic body has no fixed worst-case step count); 32 terms, both Vec ranges contain 255 in every cell."}}
    return (export, grading_bytes) if with_grading else export


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    public, grading_bytes = build_export(with_grading=True)
    GRADING.parent.mkdir(parents=True, exist_ok=True)
    GRADING.write_bytes(grading_bytes)
    OUTPUT.write_text(json.dumps(public, sort_keys=True, indent=1, ensure_ascii=True) + "\n",
                      encoding="utf-8")
