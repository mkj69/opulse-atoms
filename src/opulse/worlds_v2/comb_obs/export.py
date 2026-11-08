"""Reproducible kernel-backed warehouse catalogue export."""

import json
import re
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Ok
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import reference as ref
from .story import NAMES, SLOTS, build_library
from .world import decl

ROOT = Path(__file__).resolve().parents[4]
DESIGN = ROOT / "worlds/catalogue/depth/comb_obs.json"
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/comb_obs.json"
LADDER_ENGLISH = (
    "1 / Compute: Use @chart at one start in the 64x64 warehouse; calculate energy, log counts and the initially known area without reading the sealed map.",
    "2 / Decide: Use ?frontier and ?route_len to distinguish no local information gain from an unknown goal route; neither proves the goal unreachable.",
    "3 / Invert: Identify candidate seeds from two scan-log signatures for the same goal, allowing multiple matches only within the given candidates.",
    "4 / Compute: Use @explore to find known routes to three orders, accounting for scans, depot returns, charging and energy.",
    "5 / Create / Decide: Optimize cargo groups and depot charging for orders weighing 2/1/1; compare inventory, return reserves and action traces with ?audit.",
)
SHOWCASE_DIFFICULTY = (
    "Requires 278 active scans and optimal grouping: (A,C) and (B) on separate sorties; exploration changes actual charging costs.",
    "Requires full adaptive traces on four sealed terrains; compare only authorized logs, reserves and scanned-map signatures.",
    "Both runs deliver all orders, but differ in known maps, return reserves and real costs; success alone is not audit equivalence.",
)
LAYER_ZERO_ENGLISH = {
    "combinators": (
        "Sequentially apply f and g to the same run.",
        "Repeat f a bounded number of times, propagating failures and actual costs.",
        "Stable BFS over known free cells in N,W,E,S order; return None if no known route exists.",
    ),
    "observations": (
        "Read the authorized current position.",
        "Read the authorized remaining energy.",
        "Read only cells revealed by this run's scans.",
        "Read the authorized goal of order A.",
        "Read authorized order locations and weights, not hidden terrain.",
        "Read onboard, delivered and current payload weight.",
        "Read only this run's action log.",
    ),
}
EXPRESSION = re.compile(
    r"(?:(?:\?(?P<observer>\w+)\{))?@(?P<controller>\w+)\[(?P<slots>[^]]+)\]"
    r"\(Run<(?P<seed>\d+),\s*(?P<x>\d+),\s*(?P<y>\d+)>\)\}?"
)


def definition_source(definition):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (TypeError, ValueError):
        return None
    if export_util.source_matches(source, export_util.body_sha256(definition.body)):
        return source
    return None


def evaluate(expression, library, *, trace=False):
    match = EXPRESSION.fullmatch(expression)
    if match is None:
        raise ValueError(f"invalid ASCII expression: {expression}")
    values = match.groupdict()
    name = values["controller"]
    slots = tuple(values["slots"].split(","))
    if slots != SLOTS[name]:
        raise ValueError("unbound combinator slots")
    state = ref.Run(int(values["seed"]), (int(values["x"]), int(values["y"])))
    if state.goal == ref.HOME or not ref.in_bounds(state.goal) or not ref.terrain(state.seed, state.goal):
        raise ValueError("invalid scenario goal")
    args = tuple(kernel.FnRef(slot) for slot in slots) + (state,)
    if name in ("walk", "explore"):
        args += (state.goal,)
    result = library.run(name, args, fuel=5_000_000, trace=trace)
    if not isinstance(result.outcome, Ok):
        raise TypeError(f"kernel returned non-value: {result.outcome!r}")
    if values["observer"]:
        result = library.run(values["observer"], (result.outcome.value,), fuel=5_000_000, trace=trace)
        if not isinstance(result.outcome, Ok):
            raise TypeError(f"kernel observation returned non-value: {result.outcome!r}")
        return result.outcome.value, result
    return ref.summary(result.outcome.value), result


def build_export():
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    library = build_library()
    declaration = decl().to_dict()

    answers = {}

    def answer(expression):
        if expression not in answers:
            answers[expression] = evaluate(expression, library)[0]
        return answers[expression]

    story = []
    for entry, name in zip(design["tower"], NAMES):
        value, run = evaluate(entry["example"], library, trace=True)
        assert value == entry["value"], name
        answers[entry["example"]] = value
        definition = library.get(name)
        story.append({"name": name, "layer": entry["layer"], "def_layer": definition.layer,
                      "kind": definition.kind, "symbol": ("@" if definition.kind == "combinator" else "?")
                      + name + ("[...]" if definition.kind == "combinator" else "{...}"),
                      "design_decl": entry["decl"], "plain_zh": entry["plain"],
                      "body_sha256": export_util.body_sha256(definition.body),
                      **({"decl": source_text} if (source_text := definition_source(definition)) else {}),
                      "body": nodes.to_json(definition.body), "depends_on": list(definition.depends_on),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [{"text": entry["example"], "value": value, "outcome": {"ok": value},
                                    "steps": run.steps,
                                    "trace": trace_json(run.trace, max_nodes=40)}]})
    showcase = []
    for task in design["showcase"]:
        check = task["check"]
        if task["angle"] == "Invert":
            actual = [seed for seed in check["candidates"]
                      if answer(check["template"].replace("SEED", str(seed))) == check["expected"]]
        elif task["angle"] == "Decide":
            actual = answer(check["left"]) == answer(check["right"])
        else:
            actual = answer(check["expression"])
        assert actual == task["answer"], task["angle"]
        showcase.append({**task, "why_hard_zh": task["why_hard"],
                         "why_hard": SHOWCASE_DIFFICULTY[len(showcase)],
                         "answer_checked": True, "check_method": "exact kernel evaluation"})
    layer0 = {
        "objects": [{"name": obj["name"], "symbol": obj["name"] + "<...>",
                     "form": obj["form"], "definition": obj["doc"]} for obj in declaration["objects"]],
        "operations": [{"name": op["name"], "symbol": op["name"] + "(...)" ,
                        "rule": op["rule"], "cost": op["cost"]} for op in declaration["operations"]],
        "combinators": [{"decl": text.split(" given ")[0] + " given",
                         "definition": LAYER_ZERO_ENGLISH["combinators"][index],
                         "definition_zh": text.split(" given — ", 1)[1]}
                        for index, text in enumerate(design["layer0"]["combinators"])],
        "observation": [{"decl": text.split(" given ")[0] + " given",
                         "definition": LAYER_ZERO_ENGLISH["observations"][index],
                         "definition_zh": text.split(" given — ", 1)[1]}
                        for index, text in enumerate(design["layer0"]["observations"])],
    }
    return finalize_export({"schema": "opulse.world_v2_export/1", "world": "comb_obs",
                            "version": 1, "wave": 4, "tower_source": "depth",
                            "title": declaration["title"], "title_zh": design["name"],
                            "pitch_zh": design["pitch"], "modality_zh": design["modalities"]["text"],
                            "emerges_zh": design["why_only_these"],
                            "checking_zh": "由内核重算全部展示实例与有限核验证书。",
                            "decl": declaration, "layer0": layer0,
                            "story": story, "showcase": showcase,
                            "ladder": [{"text": text, "text_zh": design["ladder"][index]}
                                       for index, text in enumerate(LADDER_ENGLISH)],
                            "open_kinds": design["open_kinds"], "tags": design["tags"]})


def main():
    EXPORT_PATH.write_text(json.dumps(build_export(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
