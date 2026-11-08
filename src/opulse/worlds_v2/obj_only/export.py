"""Export the locked declaration and core-executed design examples."""

import json
from dataclasses import replace

from opulse.atoms import notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Ok, encode, encode_outcome
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts
from .story import NAMES, answer, build_library, design, example_raws, showcase_raw
from .world import DECL_PATH, ROOT

EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/obj_only.json"


def display(name, result):
    assert isinstance(result.outcome, Ok)
    assert result.outcome.value.sort == name
    return hosts.value(result.outcome.value)


def definition_source(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, library)
    except (TypeError, ValueError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def build_export():
    library = build_library()
    source = design()
    declaration = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    story = []
    for name, raw, row in zip(NAMES, example_raws(), source["tower"]):
        definition = library.get(name)
        text = definition_source(definition, library)
        run = library.run(f"{name}.make", (raw,), trace=True)
        shown = display(name, run)
        if shown != row["value"]:
            raise ValueError(f"design example disagrees with kernel: {name}")
        story.append({"name": name, "kind": definition.kind, "layer": row["layer"],
                      "def_layer": definition.layer, "design_decl": row["decl"],
                      **({"decl": text} if text is not None else {}),
                      "body_sha256": export_util.body_sha256(definition.body),
                      "definition_zh": row["plain"], "status": definition.status,
                      "depends_on": list(definition.depends_on), "spec": definition.spec.to_dict(),
                      "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                      "cost": definition.cost.to_dict(), "examples": [{"text": row["example"],
                      "input": encode(raw), "outcome": encode_outcome(run.outcome),
                      "value": shown, "steps": run.steps, "trace": trace_json(run.trace, max_nodes=32)}],
                      "symbol": name})
    showcase = []
    for index, task in enumerate(source["showcase"]):
        raw = showcase_raw(task)
        name = "SignCover" if index == 0 else "RootAtlas"
        result = library.run(f"{name}.make", (raw,))
        calculated = answer(result.outcome, task)
        if calculated != task["answer"]:
            raise ValueError(f"design showcase disagrees with kernel: {index}")
        showcase.append({**task, "answer_checked": True, "input": encode(raw),
                         "outcome": encode_outcome(result.outcome), "steps": result.steps})
    return finalize_export({
        "schema": "opulse.world_v2_export/1", "world": "obj_only", "version": 1,
        "title": declaration["title"], "title_zh": source["name"], "pitch_zh": source["pitch"],
        "wave": 4, "modality_zh": "精确算术／文字",
        "emerges_zh": "只发明封口对象，从规范有理数和稀疏式逐层构造可核验实根地图。",
        "checking_zh": "逐片重验伯恩斯坦界、导数、精确除法和无缝覆盖，并重放所有展示证书。",
        "decl": declaration, "layer0": {
            **{key: source["layer0"][key] for key in ("objects", "operations", "combinators")},
            "observation": source["layer0"]["observations"]},
        "layer0_contract_zh": source["layer0"]["contract"],
        "story": story, "tower_source": "depth",
        "ladder": source["ladder"], "showcase": showcase, "tags": source["tags"],
        "open_kinds": list(library.world.open_kinds), "experiment_hook_zh": source["experiment_hook"],
    })


def main():
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
