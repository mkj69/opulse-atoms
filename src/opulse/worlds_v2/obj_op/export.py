"""Rebuild the catalogue export from promoted kernel definitions and exact calls."""

import json
import re
from dataclasses import replace
from pathlib import Path

from opulse.atoms import nodes, notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import encode_outcome
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from .expressions import calls_in, display, run
from .story import build_library
from .world import decl

ROOT = Path(__file__).resolve().parents[4]
DESIGN_PATH = ROOT / "worlds/catalogue/depth/obj_op.json"
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/obj_op.json"
NAMES = ("Cycle", "join", "Plan", "compile", "Window", "first_hit", "Blackout", "clear_hit")


def case(library, source):
    result = run(library, source, trace=True)
    return {"text": source, "value": display(result.outcome), "outcome": encode_outcome(result.outcome),
            "steps": result.steps, "trace": trace_json(result.trace) if result.trace else None}


def definition_source(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, library)
    except (TypeError, ValueError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def build_export(library=None):
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    library = library or build_library()
    story = []
    for card, name in zip(design["tower"], NAMES):
        definition = library.get(name)
        source = definition_source(definition, library)
        example = case(library, card["example"])
        assert example["value"] == card["value"], (name, example["value"])
        story.append({"layer": card["layer"], "def_layer": definition.layer,
                      "kind": definition.kind, "name": name, "design_decl": card["decl"],
                      **({"decl": source} if source is not None else {}),
                      "body_sha256": export_util.body_sha256(definition.body),
                      "symbol": f"{name}<...>" if definition.kind == "object" else f"{name}(...)",
                      "title": name.replace("_", " ").title(), "title_zh": name,
                      "definition": f"Bounded idealized scheduling {name}.",
                      "definition_zh": card["plain"], "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body) if definition.body else None,
                      "valid": (nodes.to_json(definition.spec.valid) if definition.kind == "object" else None),
                      "canon": (nodes.to_json(definition.spec.canon) if definition.kind == "object"
                                and definition.spec.canon is not None else None),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [example]})
    showcases = []
    for card in design["showcase"]:
        outputs = []
        if card["angle"] == "Invert":
            pairs = ((98745, 444345), (530745, 357945), (185145, 271545))
            for phase9, phase13 in pairs:
                source = next(calls_in(card["prompt"]))
                source = re.sub(r"\br9\b", str(phase9), source)
                source = re.sub(r"\br13\b", str(phase13), source)
                outputs.append(case(library, source))
            answer = "; ".join(f"({phase9}, {phase13})" for phase9, phase13 in pairs)
        else:
            outputs = [case(library, source) for source in calls_in(card["prompt"])]
            answer = outputs[0]["value"] if card["angle"] == "Compute" else str(
                outputs[0]["value"] == outputs[1]["value"]).lower()
        assert answer == card["answer"], card["angle"]
        showcases.append({**card, "runs": outputs})
    source = decl()
    layer0 = {"objects": design["layer0"]["objects"],
              "operations": design["layer0"]["operations"],
              "combinators": {**source.combinators, "entries": design["layer0"]["combinators"]},
              "observation": {**source.observation, "entries": design["layer0"]["observations"]}}
    return finalize_export({"schema": "opulse.world_v2_export/1", "world": "obj_op", "version": 1,
                            "wave": 4, "tower_source": "depth",
                            "modality_zh": "理想化秒级周期调度与精确整数证书。",
                            "title": "Idealized periodic schedules and blackout windows",
                            "title_zh": design["name"], "pitch_zh": design["pitch"],
                            "emerges_zh": design["why_only_these"],
                            "checking_zh": "按核算内核重放八层样例及三道展示题；有限见证的有界核验不代表全域证明。",
                            "decl": source.to_dict(), "layer0": layer0,
                            "layer0_contract_zh": design["layer0"]["contract"],
                            "story": story, "ladder": design["ladder"], "showcase": showcases,
                            "open_kinds": list(source.open_kinds), "tags": design["tags"]})


if __name__ == "__main__":
    EXPORT_PATH.write_text(json.dumps(build_export(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
