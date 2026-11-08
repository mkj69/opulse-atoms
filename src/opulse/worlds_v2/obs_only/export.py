"""Publish the promoted story and checked design examples."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Ok
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import _outcome, _small, finalize_export, trace_json

from . import reference as ref
from .story import args_for, build_library
from .world import decl

ROOT = Path(__file__).resolve().parents[4]
DESIGN = ROOT / "worlds/catalogue/depth/obs_only.json"
EXPORT = ROOT / "docs/assets/data/worlds_v2/obs_only.json"


def design():
    return json.loads(DESIGN.read_text(encoding="utf-8"))


def definition_source(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, library)
    except (TypeError, ValueError):
        return None
    if export_util.source_matches(source, export_util.body_sha256(definition.body)):
        return source
    return None


def answer(library, case):
    query = case["query"]
    if query in ("invert_choice", "decide_safe", "partition"):
        trace = ref.trace_of(case["trace"])
        tick = case["tick"]
        config = ref.config_of(case)
        quantile = ref.Fraction(case["q"])
        cap = ref.Fraction(case["cap"])
        if query == "invert_choice":
            return ",".join(str(reading) for reading in range(8)
                            if library.run("status", (ref.Trace(trace.actions, trace.readings[:-1] + str(reading)),
                                                      tick, config)).outcome == Ok("POSSIBLE")
                            and library.run("choice", (ref.Trace(trace.actions, trace.readings[:-1] + str(reading)),
                                                      tick, quantile, cap, config)).outcome == Ok(case["target"]))
        if query == "decide_safe":
            return "true" if library.run("choice", (trace, tick, quantile, cap, config)).outcome != Ok("NONE") else "false"
        if library.run("status", (trace, tick, config)).outcome == Ok("IMPOSSIBLE"):
            return "IMPOSSIBLE"
        return "".join({"SAFE": "S", "UNSAFE": "U", "UNKNOWN": "?"}[
            library.run("certified", (trace, tick, quantile, route, cap, config)).outcome.value]
            for route in config.routes)
    definition = library.get(query)
    outcome = library.run(query, args_for(definition, case)).outcome
    assert isinstance(outcome, Ok), (case, outcome)
    value = outcome.value
    if query in ("weight", "belief", "exact_risk"):
        return ref.format_fraction(value)
    if query == "ranked":
        return ",".join(map(str, value))
    if query == "credible":
        return ",".join(map(str, value[0])) + "|" + ref.format_fraction(value[1])
    if query == "risk_interval":
        return ref.format_interval(value)
    return value


def build_export():
    source = design()
    library = build_library()
    declaration = decl().to_dict()
    story = []
    for row in source["tower"]:
        definition = library.get(row["check"]["query"])
        result = answer(library, row["check"])
        if result != row["value"]:
            raise AssertionError((definition.name, result, row["value"]))
        args = args_for(definition, row["check"])
        run = library.run(definition.name, args, trace=True)
        story.append({"layer": row["layer"], "kind": definition.kind, "name": definition.name,
                      "symbol": "?" + definition.name + "{...}", "design_decl": row["decl"],
                      "body_sha256": export_util.body_sha256(definition.body),
                      **({"decl": source_text} if (source_text := definition_source(definition, library)) else {}),
                      "title": definition.name.replace("_", " ").title(),
                      "definition_zh": row["plain"], "def_layer": definition.layer,
                      "depends_on": list(definition.depends_on), "body": definition.spec.to_dict()["body"],
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [{"text": row["example"], "inputs": [_small(arg) for arg in args],
                                    "outcome": _outcome(run.outcome), "steps": run.steps,
                                    "trace": trace_json(run.trace), "answer": result,
                                    "check": row["check"]}]})
    showcase = []
    for task in source["showcase"]:
        result = answer(library, task["check"])
        if result != task["answer"]:
            raise AssertionError((task["angle"], result, task["answer"]))
        showcase.append({**task, "answer_checked": True, "check_method": "promoted kernel observation"})
    for task in source["generated_cases"]:
        if answer(library, task["check"]) != task["value"]:
            raise AssertionError(task["example"])
    return finalize_export({"schema": "opulse.world_v2_export/1", "world": "obs_only", "version": 1,
                            "wave": 4, "modality_zh": "概率／公开日志", "emerges_zh": source["pitch"],
                            "checking_zh": "逐项在公开有限域上独立核验有理数与风险界。",
                            "title": declaration["title"], "title_zh": source["name"],
                            "pitch_zh": source["pitch"], "decl": declaration, "tower_source": "depth",
                            "layer0": {"objects": declaration["objects"], "operations": declaration["operations"],
                                       "combinators": declaration["combinators"],
                                       "observation": declaration["observation"]},
                            "story": story, "ladder": source["ladder"], "showcase": showcase,
                            "generated_cases": source["generated_cases"], "tags": source["tags"],
                            "open_kinds": source["open_kinds"]})


if __name__ == "__main__":
    EXPORT.write_text(json.dumps(build_export(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
