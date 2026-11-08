"""Reproducible catalogue export from promoted kernel definitions and design cases."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Ok
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts
from .story import build_library
from .world import DECL_PATH

ROOT = Path(__file__).resolve().parents[4]
DESIGN_PATH = ROOT / "worlds/catalogue/depth/comb_only.json"
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/comb_only.json"
NAMES = ("map", "fold", "until", "closure", "divide", "components", "branch", "opt")


def definition_source(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, library)
    except (TypeError, ValueError):
        return None
    if export_util.source_matches(source, export_util.body_sha256(definition.body)):
        return source
    return None


def examples():
    plan = hosts.Plan(23, 10, 12)
    return (
        (kernel.FnRef("weight"), plan, (0, 1, 2)),
        (kernel.FnRef("add"), 0, (4, 7, 9)),
        (kernel.FnRef("drop_lowest"), kernel.FnRef("popcount"), 15),
        (kernel.FnRef("adjacent"), plan, 1),
        (kernel.FnRef("identity"), kernel.FnRef("add"), (1, 2, 3, 4, 5), 0),
        (kernel.FnRef("adjacent"), hosts.Plan(23, 2, 4)),
        (kernel.FnRef("priority"), hosts.start(plan)),
        (kernel.FnRef("priority"), hosts.start(plan)),
    )


def visible(name, value):
    if name == "until":
        return list(hosts.vertices(value))
    if name == "closure":
        return list(hosts.vertices(value))
    if name == "components":
        return [list(hosts.vertices(group)) for group in value]
    if name == "branch":
        return [[state.earned, state.available.bit_count()] for state in value]
    if name == "opt":
        return value.earned
    return list(value) if isinstance(value, tuple) else value


def build_export():
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    declaration = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    library = build_library()
    cards = []
    solution = None
    for name, row, arguments in zip(NAMES, design["tower"], examples(), strict=True):
        definition = library.get(name)
        run = library.run(name, arguments, fuel=10_000_000, trace=name != "opt")
        assert isinstance(run.outcome, Ok) and visible(name, run.outcome.value) == row["value"], name
        if name == "opt":
            solution = run.outcome.value
        # The shown text is evaluated as written (e.g. ?score{@opt[...](start(...))} or the start(...) call),
        # so its outcome, steps and trace are one evaluation.
        shown = kernel.evaluate(notation.parse_expr(row["example"], library), scope=library.scope(),
                                limits=kernel.Limits(fuel=10_000_000), trace=name != "opt")
        assert isinstance(shown.outcome, Ok), name
        example = {"text": row["example"], "inputs": [hosts.encode_value(arg) for arg in arguments],
                   "outcome": {"ok": hosts.encode_value(shown.outcome.value)},
                   "steps": shown.steps,
                   "trace": trace_json(shown.trace) if shown.trace is not None else
                   {"name": name, "kind": "combinator", "steps": shown.steps, "elided": "large exact search"}}
        cards.append({"name": name, "kind": "combinator", "layer": row["layer"],
                      "symbol": "@" + name + "[...]", "title": name.capitalize(),
                      "title_zh": row["plain"].split("；")[0],
                      "definition": "Measured kernel control over fixed public operations.",
                      "definition_zh": row["plain"], "design_decl": row["decl"],
                      "body_sha256": export_util.body_sha256(definition.body),
                      **({"decl": source_text} if (source_text := definition_source(definition, library)) else {}),
                      "depends_on": list(definition.depends_on), "body": nodes.to_json(definition.body),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [example]})
    layer_zero = {
        "objects": [{"name": item["name"], "symbol": item["name"] + "<...>",
                     "decl": "obj " + item["name"] + " given", "definition": item.get("doc", "Finite given value.")}
                    for item in declaration["objects"]],
        "operations": [{"name": item["name"], "symbol": item["name"] + "(...)" if item["name"] not in
                        {"score", "chosen", "legal", "available"} else "?" + item["name"] + "{...}",
                        "decl": "op " + item["name"] + "(...) given", "definition": item["rule"],
                        "cost": item["cost"]} for item in declaration["operations"]],
        "combinators": {**declaration["combinators"], "entries": [
            {"name": "case", "symbol": "@case[yes,no,test](x)", "definition": "Fixed short-circuit choice."},
            {"name": "jump", "symbol": "@jump[step,guard](x,fuel)",
             "definition": "Fixed fuel-bounded machine jump."}]},
        "observation": declaration["observation"],
    }
    showcase = []
    for index, entry in enumerate(design["showcase"]):
        if index == 0:
            answer = {"score": solution.earned, "chosen": list(hosts.vertices(solution.chosen))}
            checked = library.run("legal", (solution,)).outcome == Ok(True)
        elif index == 1:
            from .reference import independent_oracle

            answer = [candidate for candidate in range(41)
                      if independent_oracle(hosts.Plan(23, 10, 12, 0, candidate))[0] == entry["target"]]
            checked = True
        else:
            bridge = hosts.Plan(23, 10, 12, bridges=((0, 13), (26, 39), (49, 62)))
            result = library.run("opt", (kernel.FnRef("priority"), hosts.start(bridge)), fuel=10_000_000).outcome
            assert isinstance(result, Ok)
            answer = result.value.earned >= entry["target"]
            checked = result.value.earned == 753 and library.run("legal", (result.value,)).outcome == Ok(True)
        assert checked and answer == entry["answer"], entry["angle"]
        showcase.append({**entry, "answer_checked": checked})
    return finalize_export({"schema": "opulse.world_v2_export/1", "world": "comb_only", "version": 1,
                            "wave": 4, "tower_source": "depth", "title": declaration["title"],
                            "title_zh": design["name"], "pitch_zh": design["pitch"],
                            "modality_zh": "冲突工单", "decl": declaration, "layer0": layer_zero,
                            "story": cards, "ladder": design["ladder"], "showcase": showcase,
                            "tags": {"domain": "resource", "modalities": ["text"],
                                     "open_kinds": ["combinator"], "star_kind": "combinator",
                                     "reasoning": ["search", "planning", "counting"], "state": "stateless",
                                     "outcomes": "deterministic", "visibility": "full", "agents": 1,
                                     "scale": "120 vertices, 8 invented combinators", "difficulty": "exact independent set",
                                     "uses": ["evaluation", "teaching", "experiment"]},
                            "open_kinds": list(library.world.open_kinds),
                            "emerges_zh": "以八层组合方式构造精确冲突工单调度。",
                            "checking_zh": "内核运行公开案例，与独立子集动态规划逐一核对。"})


def main():
    EXPORT_PATH.write_text(json.dumps(build_export(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
