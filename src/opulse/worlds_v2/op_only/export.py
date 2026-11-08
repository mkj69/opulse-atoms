"""Replay design examples in the core and export the promoted world."""

import json
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Card, Ok, encode_outcome
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts, reference
from .story import build_library

ROOT = Path(__file__).resolve().parents[4]
DESIGN_PATH = ROOT / "worlds/catalogue/depth/op_only.json"
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/op_only.json"


def split_args(text):
    parts, start, depth = [], 0, 0
    for index, char in enumerate(text):
        if char in "(<{[":
            depth += 1
        elif char in ")>}]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def evaluator(library, trace=True):
    @lru_cache(maxsize=256)
    def parse(text):
        text = text.strip()
        if re.fullmatch(r"\d+", text):
            return nodes.Lit(int(text))
        if text.startswith("Rel<") and text.endswith(">"):
            args = split_args(text[4:-1])
            if args[-1].startswith("Switch<"):
                return nodes.Call("switch_net", (nodes.Lit(int(args[0])), nodes.Lit(int(args[1])),
                                                 nodes.Lit(int(args[2][7:-1]))))
            gates = tuple(int(item) for item in split_args(args[-1][6:-1]) if item)
            return nodes.Call("braid", (nodes.Lit(int(args[0])), nodes.Lit(int(args[1])),
                                        nodes.Lit(int(args[2])), nodes.Lit(Card("Gates", "Gates", gates))))
        if text.startswith("Profile<List<"):
            left, right = split_args(text[8:-1])
            return nodes.Lit(Card("Profile", "Profile", tuple(Card("List", "items", tuple(
                int(item) for item in split_args(part[5:-1]))) for part in (left, right))))
        if text.startswith("(") and text.endswith(")"):
            return nodes.Lit(Card("Edge", "Edge", tuple(int(item) for item in split_args(text[1:-1]))))
        match = re.fullmatch(r"\?([a-z_]+)\{(.*)\}|([a-z_]+)\((.*)\)", text)
        if match is None:
            raise ValueError(text)
        name = match[1] or match[3]
        arguments = split_args(match[2] if match[1] else match[4])
        return nodes.Call(name, tuple(parse(argument) for argument in arguments))

    @lru_cache(maxsize=256)
    def run(text):
        expression = parse(text)
        if not trace and isinstance(expression, nodes.Call) and not text.startswith("Rel<"):
            arguments = split_args(text[text.index("{") + 1:-1] if text.startswith("?")
                                   else text[text.index("(") + 1:-1])
            values = tuple(run(argument) for argument in arguments)
            values = tuple(value.outcome.value if hasattr(value, "outcome") and
                           isinstance(value.outcome, Ok) else value for value in values)
            return library.run(expression.fn, values)
        return (expression.value if isinstance(expression, nodes.Lit)
                else kernel.evaluate(expression, scope=library.scope(), trace=trace))

    return run


def display(result):
    value = result.outcome.value if hasattr(result, "outcome") else result
    if isinstance(value, Card) and value.sort == "Profile":
        profile = hosts.profile_value(value)
        return reference.formatted(reference.Profile(profile.depth, profile.ways))
    if isinstance(value, Card) and value.sort == "bool":
        return value.tag
    return str(value)


def definition_source(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, library)
    except (TypeError, ValueError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def build_export():
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    library = build_library()
    run = evaluator(library)
    cards = []
    for item in design["tower"]:
        name = item["decl"].split("(", 1)[0].split()[-1]
        definition = library.get(name)
        source = definition_source(definition, library)
        actual = run(item["example"])
        assert display(actual) == item["value"], item["example"]
        cards.append({"layer": item["layer"], "def_layer": definition.layer, "kind": "operation",
                      "name": name, "symbol": name + "(...)" , "design_decl": item["decl"],
                      **({"decl": source} if source is not None else {}),
                      "body_sha256": export_util.body_sha256(definition.body),
                      "title": name, "title_zh": item["plain"].split("，")[0],
                      "plain_zh": item["plain"], "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body), "status": definition.status,
                      "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                      "cost": definition.cost.to_dict(), "examples": [{"text": item["example"],
                          "outcome": encode_outcome(actual.outcome), "steps": actual.steps,
                          "trace": trace_json(actual.trace)}]})
    check_showcase = evaluator(library, trace=False)
    for showcase in design["showcase"]:
        for expression, expected in showcase["check"]:
            assert display(check_showcase(expression)) == expected, expression
    declaration = library.world.to_dict()
    return finalize_export({"schema": "opulse.world_v2_export/1", "world": "op_only", "version": 1,
                            "wave": 4, "tower_source": "depth",
                            "title": "Relation Networks: Operations Only",
                            "title_zh": design["name"], "modality_zh": "文本／关系图",
                            "emerges_zh": "从可达闭包到强连通商图，再到最长路公共边。",
                            "checking_zh": "有限输入逐卡验证；全部示例与大图证书独立复核。",
                            "decl": declaration,
                            "open_kinds": list(library.world.open_kinds), "tags": design["tags"],
                            "layer0": {"objects": [{"name": obj.name, "decl": f"obj {obj.name} given"}
                                                   for obj in library.world.objects],
                                       "operations": [{"name": op.name, "decl": f"op {op.name}(...) given"}
                                                      for op in library.world.operations],
                                       "combinators": [{"name": item["name"],
                                                        "symbol": "@" + item["name"] + "[...]"}
                                                       for item in declaration["combinators"]["library"]],
                                       "observation": [{"name": probe["name"],
                                                        "symbol": "?" + probe["name"] + "{...}"}
                                                       for probe in declaration["observation"]["probes"]]},
                            "story": cards,
                            "ladder": [{"layer": index, "description_zh": description}
                                       for index, description in enumerate(design["ladder"], start=1)],
                            "showcase": design["showcase"],
                            "pitch_zh": design["pitch"]})


def main():
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
