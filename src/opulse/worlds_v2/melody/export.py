"""Generate the depth-world cards from promoted definitions and kernel traces."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import adapter, hosts
from .story import NAMES, build_library, kernel_value, oracle, score

ROOT = Path(__file__).resolve().parents[4]
DEPTH = ROOT / "worlds/catalogue/depth/melody.json"
TITLES = ("Relative motif", "Transposition-invariant match", "Bounded scan",
          "Rhythmic intervals", "Realize a motif", "Extract a motif", "Ordered score",
          "Exact cover counting", "Public cover count", "Optimal cover",
          "Checked performance", "Cover report")

def source_declaration(definition):
    written = replace(definition, status="written", evidence=None, contract=None,
                      id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (ValueError, TypeError, notation.NotationError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def render(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    if isinstance(value, values.Card):
        if value.sort == "Melody":
            return "Melody<" + ",".join(f"({pitch},{duration})" for pitch, duration in value.fields) + ">"
        if value.sort == "Motif":
            return "Motif<" + ",".join(f"({offset},{duration})" for offset, duration in value.fields[0]) + ">"
        if value.sort == "Score":
            source, library = value.fields[0]
            return "Score<" + ",".join((render(source), *(render(item) for item in library))) + ">"
        if value.sort == "bool":
            return value.tag
    if isinstance(value, tuple):
        return "List<" + ",".join(render(item) for item in value) + ">"
    if type(value) is bool:
        return "true" if value else "false"
    if value is None or value == "NONE":
        return "None"
    return str(value)


def encode(value):
    if isinstance(value, kernel.FnRef):
        return {"t": "fn", "v": value.name}
    if isinstance(value, tuple):
        return values.encode(values.Card("List", "items", tuple(as_value(item) for item in value)))
    return values.encode(as_value(value))


def as_value(value):
    if isinstance(value, tuple):
        return values.Card("List", "items", tuple(as_value(item) for item in value))
    if type(value) is bool:
        return values.boolean(value)
    if value == "NONE":
        return "None"
    if isinstance(value, values.Card) and value.sort == "Score":
        return values.Card("Score", "val", (as_value(value.fields[0]),))
    if isinstance(value, values.Card) and value.sort == "Motif":
        return values.Card("Motif", "val", (as_value(value.fields[0]),))
    if isinstance(value, values.Card) and value.sort == "Melody":
        return values.Card("Melody", "events", tuple(as_value(item) for item in value.fields))
    return value


def outcome(value):
    if isinstance(value, values.Ok):
        return values.encode_outcome(values.Ok(as_value(value.value)))
    return values.encode_outcome(value)


def run_example(lib, name, args, text):
    if name in ("Motif", "Score"):
        run = lib.run(name + ".make", args, trace=True)
    elif name in ("intervals", "cover_count", "cover_report"):
        run = adapter.run_observation(lib, name, args[0], trace=True)
    else:
        run = lib.run(name, args, trace=True)
    return {"text": text, "inputs": [encode(item) for item in args],
            "outcome": outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace, max_nodes=40)}


def _examples(reference):
    alpha, beta, gamma, delta, epsilon, zeta, source, full, sparse = reference.cases()
    alpha, beta, gamma, delta, epsilon, zeta, source, full, sparse = (
        kernel_value(value) for value in (alpha, beta, gamma, delta, epsilon, zeta, source, full, sparse))
    full_plan = kernel_value(reference.best_cover(reference.cases()[-2]))
    return ((alpha.fields[0],), (source, alpha, 0), (kernel.FnRef("occurs"), source, alpha),
            (hosts.slice_events(source, 0, 5),), (gamma, 67), (source, 3, 4),
            (full.fields[0],), (kernel.FnRef("occurs"), full), (full,), (full,),
            (kernel.FnRef("realize"), full, full_plan), (full,)), (full, sparse)


def _fresh_examples(lib, reference):
    alpha, beta, gamma, *_ = reference.cases()
    alpha, beta, gamma = (kernel_value(item) for item in (alpha, beta, gamma))
    melodies = [hosts.melody(*((root + offset, duration) for offset, duration in alpha.fields[0]))
                for root in range(62, 72)]
    scores = [score(source, (alpha, beta)) for source in melodies]
    plan = lib.run("best_cover", (scores[9],)).outcome.value
    return ((beta.fields[0],), (melodies[0], alpha, 0),
            (kernel.FnRef("occurs"), melodies[1], alpha),
            (melodies[2],), (gamma, 66), (melodies[3], 0, 3),
            (scores[4].fields[0],), (kernel.FnRef("occurs"), scores[5]),
            (scores[6],), (scores[7],),
            (kernel.FnRef("realize"), scores[9], plan), (scores[8],))


def expression(name, args):
    if name in ("Motif", "Score"):
        return f"{name}.make({notation.print_value(args[0])})"
    if name in ("intervals", "cover_count", "cover_report"):
        return f"?{name}{{{notation.print_value(args[0])}}}"
    if name in ("scan", "count_covers"):
        return f"@{name}[{args[0].name}]({', '.join(notation.print_value(item) for item in args[1:])})"
    if name == "perform":
        return f"@perform[{args[0].name}]({', '.join(notation.print_value(item) for item in args[1:])})"
    return f"{name}({', '.join(notation.print_value(item) for item in args)})"


def build_export():
    design = json.loads(DEPTH.read_text(encoding="utf-8"))
    reference = oracle()
    lib = build_library()
    example_args, (full, sparse) = _examples(reference)
    fresh_args = _fresh_examples(lib, reference)
    entries = []
    for title, template, name, args in zip(TITLES, design["tower"], NAMES, example_args):
        definition = lib.get(name)
        example = run_example(lib, name, args, expression(name, args))
        if render_result(example["outcome"]) != template["value"]:
            raise ValueError(f"design mismatch for {name}: {render_result(example['outcome'])}")
        symbols = {"object": f"{name}<...>", "operation": f"{name}(...)",
                   "combinator": f"@{name}[...]", "observation": f"?{name}{{...}}"}
        cost = definition.cost.to_dict()
        cost["steps"]["over"] = "verification family"
        entries.append({"layer": template["layer"], "def_layer": definition.layer,
                        "kind": definition.kind, "name": name, "symbol": symbols[definition.kind],
                        "decl": source_declaration(definition), "body_sha256": export_util.body_sha256(definition.body),
                        "design_decl": template["decl"],
                        "plain_zh": template["plain"],
                        "title": title, "definition": f"{title} is derived from counted kernel calls and public probes.",
                        "title_zh": template["plain"].split("，")[0],
                        "definition_zh": template["plain"],
                        "depends_on": list(definition.depends_on),
                        "body": nodes.to_json(definition.body), "status": definition.status,
                        "evidence": definition.evidence.to_dict(),
                        "contract": definition.contract.to_dict(),
                        "cost": cost,
                        "examples": [example, run_example(lib, name, fresh_args[template["layer"] - 1],
                                                         expression(name, fresh_args[template["layer"] - 1]))]})
    failure_args = (full, ((0, 60),))
    failure = run_example(lib, "perform", (kernel.FnRef("realize"), *failure_args),
                          expression("perform", (kernel.FnRef("realize"), *failure_args)))
    if "bottom" not in failure["outcome"]:
        raise ValueError("missing kernel failure")
    entries[10]["examples"].append(failure)
    showcases = []
    for template, name, case in zip(design["showcase"], ("cover_report", "best_cover", "cover_report"),
                                    (full, full, sparse)):
        result = (adapter.run_observation(lib, name, case) if name == "cover_report"
                  else lib.run(name, (case,)))
        checked = render(result.outcome.value) == template["answer"] if isinstance(result.outcome, values.Ok) else False
        if not checked:
            raise ValueError(f"showcase mismatch: {template['angle']}")
        template = dict(template)
        template["check_zh"] = template.pop("check")
        template["why_hard_zh"] = template.pop("why_hard")
        showcases.append({**template, "answer_checked": checked, "check_method": "kernel execution versus independent depth oracle"})
    objects = []
    operations = []
    combinators = []
    observations = []
    for source in design["layer0"]["objects"]:
        decl, doc = source.split(" — ", 1)
        name = decl.split("<")[0].split()[1]
        objects.append({"name": name, "form": "given", "decl": decl,
                        "symbol": name.capitalize() + "<...>", "title": "Given value sort",
                        "definition": "A canonical primitive sort for ordered pitch and duration data.", "doc_zh": doc})
    for source in design["layer0"]["operations"]:
        decl, doc = source.split(" — ", 1)
        name = decl.split("(")[0].split()[1]
        operation = next(op for op in lib.world.operations if op.name == name)
        operations.append({"name": name, "decl": decl, "symbol": f"{name}(...)", "title": name,
                           "definition": operation.rule,
                           "doc_zh": doc, "cost": operation.cost,
                           **({"cost_rule": lib.world.extra["atom_cost_rules"][name]}
                              if name in lib.world.extra.get("atom_cost_rules", {}) else {})})
    for source in design["layer0"]["combinators"]:
        decl, doc = source.split(" — ", 1)
        combinators.append({"name": "map_notes", "decl": decl, "symbol": "@map_notes[note_shift]",
                            "title": "Map indexed notes", "definition": "Apply a typed operation to each indexed note.",
                            "doc_zh": doc})
    for source in design["layer0"]["observations"]:
        decl, doc = source.split(" — ", 1)
        observations.append({"name": decl.split("{")[0].split("?")[1], "decl": decl,
                             "symbol": "?" + decl.split("{")[0].split("?")[1] + "{...}", "title": "Public probe",
                             "definition": "Read exact granted event or beat values.", "doc_zh": doc})
    declaration = json.loads((ROOT / "worlds/decl/v2/melody@1.json").read_text(encoding="utf-8"))
    return {"schema": "opulse.world_v2_export/1", "world": "melody", "version": 1,
            "wave": 3, "title": declaration["title"], "title_zh": design["name"],
            "pitch_zh": design["pitch"], "modality_zh": "音乐／音高",
            "decl": declaration, "tower_source": "depth",
            "layer0": {"objects": objects, "operations": operations,
                       "combinators": {"nodes": declaration["combinators"]["nodes"],
                                       "library": combinators, "recursion": "measure"},
                       "observation": {"truth": "public", "probes": observations,
                                       "show": declaration["observation"]["show"],
                                       "judge_view": "full_state"}},
            "story": entries, "ladder": [{"level": item["level"], "knobs_zh": item["knobs"],
                                            "what_changes_zh": item["what_changes"]}
                                           for item in design["ladder"]], "showcase": showcases,
            "modalities_zh": design["modalities"], "toy_risk_zh": design["toy_risk"],
            "tags": {"domain": "music", "modalities": ["text", "image", "audio"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "combinator", "reasoning": ["compute", "search", "counting", "planning"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full",
                     "agents": 1, "scale": "64 events and 12 motifs; 12 definitions",
                     "difficulty": "four notes to exact 64-note covers", "uses": ["evaluation", "teaching"]},
            "open_kinds": list(lib.world.open_kinds),
            "emerges_zh": "以逐音音高和拍长为基础，经相对动机和有界扫描推出精确覆盖。",
            "checking_zh": "核验完整事件与独立参考的等值，音频预览不参与判定。"}


def render_result(encoded):
    if "ok" not in encoded:
        return "Bottom(" + encoded.get("bottom", encoded.get("unknown", "unknown")) + ")"
    return render_encoded(encoded["ok"])


def render_encoded(encoded):
    kind = encoded["t"]
    if kind == "List":
        return "List<" + ",".join(render_encoded(item) for item in encoded["f"]) + ">"
    if kind == "Motif":
        return "Motif<" + ",".join("(" + ",".join(render_encoded(field) for field in note["f"]) + ")"
                                    for note in encoded["f"][0]["f"]) + ">"
    if kind == "Melody":
        return "Melody<" + ",".join("(" + ",".join(render_encoded(field) for field in note["f"]) + ")"
                                     for note in encoded["f"]) + ">"
    if kind == "Score":
        source, motifs = encoded["f"][0]["f"]
        return "Score<" + ",".join((render_encoded(source), *(render_encoded(item) for item in motifs["f"]))) + ">"
    if kind == "bool":
        return encoded["tag"]
    return str(encoded["v"])



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    data = _build_export_raw(*args, **kwargs)
    for row in data["story"]:
        if row.get("decl") is None:
            row.pop("decl", None)
    return finalize_export(data)


if __name__ == "__main__":
    path = ROOT / "docs/assets/data/worlds_v2/melody.json"
    path.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
