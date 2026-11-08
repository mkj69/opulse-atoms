"""Regenerate the depth tower and its kernel-checked exhibit."""

import json
from copy import copy
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts
from .story import build_library, call, cycle, seq

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/permutation.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/permutation.json"


def render(value):
    if isinstance(value, values.Card):
        if value.sort == "bool":
            return value.tag
        if value.sort == "permutation":
            return "Perm<" + ",".join(map(str, value.fields)) + ">"
        if value.sort == "Cycle":
            return "Cycle<" + ",".join(map(str, value.fields[0].fields)) + ">"
        if value.sort == "Subgroup":
            return "Subgroup<" + render(value.fields[0]) + ">"
        if value.sort == "sequence":
            if all(isinstance(item, int) for item in value.fields):
                return "Cycle<" + ",".join(map(str, value.fields)) + ">"
            if value.fields and all(isinstance(item, values.Card) and item.sort == "sequence" for item in value.fields):
                return "List<" + ",".join(map(render, value.fields)) + ">"
            return "Set<" + ",".join(map(render, value.fields)) + ">"
    return str(value)


def sample_nodes(library):
    initial = nodes.Lit(hosts.I)
    rotation = nodes.Lit(hosts.R)
    reflection = nodes.Lit(hosts.S)
    quad = nodes.Lit(cycle(1, 2, 3, 4))
    moves = (nodes.Lit(kernel.FnRef("rotate_pair")), nodes.Lit(kernel.FnRef("swap34")))
    group = call("Subgroup.make", call("closure", nodes.Lit(kernel.FnRef("compose_r")),
                                        nodes.Lit(kernel.FnRef("compose_s")), initial))
    return [
        ("Cycle", call("Cycle.make", nodes.Lit(seq(1, 2, 3, 4))), (seq(1, 2, 3, 4),)),
        ("rotate", call("rotate", quad, initial), (cycle(1, 2, 3, 4), hosts.I)),
        ("power", call("power", nodes.Lit(kernel.FnRef("rotate_quad")), nodes.Lit(3), initial),
         (kernel.FnRef("rotate_quad"), 3, hosts.I)),
        ("cycles", call("cycles", reflection), (hosts.S,)),
        ("inverse", call("inverse", rotation), (hosts.R,)),
        ("sign", call("sign", reflection), (hosts.S,)),
        ("compose", call("compose", rotation, reflection), (hosts.R, hosts.S)),
        ("closure", call("closure", *moves, initial),
         (kernel.FnRef("rotate_pair"), kernel.FnRef("swap34"), hosts.I)),
        ("Subgroup", call("Subgroup.make", call("closure", nodes.Lit(kernel.FnRef("compose_s")),
                                                    nodes.Lit(kernel.FnRef("compose_s")), initial)),
         (kernel.FnRef("compose_s"), kernel.FnRef("compose_s"), hosts.I)),
        ("order", call("order", call("compose", rotation, reflection)), (hosts.R, hosts.S)),
        ("conjugate", call("conjugate", rotation, reflection), (hosts.R, hosts.S)),
        ("center", call("center", group), (kernel.FnRef("compose_r"), kernel.FnRef("compose_s"), hosts.I)),
    ]


def fresh_nodes():
    initial, rotation, reflection = (nodes.Lit(hosts.I), nodes.Lit(hosts.R), nodes.Lit(hosts.S))
    moved = call("rotate", call("Cycle.make", nodes.Lit(seq(1, 2, 3))), reflection)
    small_group = call("closure", nodes.Lit(kernel.FnRef("rotate_pair")),
                       nodes.Lit(kernel.FnRef("swap34")), initial)
    return {
        "Cycle": call("Cycle.make", nodes.Lit(seq(2, 4, 7))),
        "rotate": call("rotate", call("Cycle.make", nodes.Lit(seq(2, 4))), rotation),
        "power": call("power", nodes.Lit(kernel.FnRef("rotate_pair")), nodes.Lit(5), reflection),
        "cycles": call("cycles", moved),
        "inverse": call("inverse", moved),
        "sign": call("sign", call("compose", rotation, reflection)),
        "compose": call("compose", call("inverse", rotation), reflection),
        "closure": call("closure", nodes.Lit(kernel.FnRef("rotate_pair")),
                        nodes.Lit(kernel.FnRef("swap34")), call("swap", nodes.Lit(1), nodes.Lit(2), initial)),
        "Subgroup": call("Subgroup.make", small_group),
        "order": call("order", call("inverse", rotation)),
        "conjugate": call("conjugate", call("inverse", rotation), reflection),
        "center": call("center", call("Subgroup.make", small_group)),
    }


def expression_text(expression):
    if isinstance(expression, nodes.Lit):
        value = expression.value
        if isinstance(value, kernel.FnRef):
            return value.name
        return notation.print_value(value)
    if isinstance(expression, nodes.Call):
        args = [expression_text(arg) for arg in expression.args]
        if expression.fn in ("power", "closure"):
            slots = 1 if expression.fn == "power" else 2
            return "@" + expression.fn + "[" + ",".join(args[:slots]) + "](" + ",".join(args[slots:]) + ")"
        return expression.fn + "(" + ",".join(args) + ")"
    raise TypeError(expression)


def declaration_source(definition):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (TypeError, ValueError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def _example(library, expression, inputs, text):
    def run_expression(node):
        if isinstance(node, nodes.Lit):
            return kernel.Run(values.Ok(node.value), 0, 0, None)
        arguments = [run_expression(arg) for arg in node.args]
        failed = next((arg for arg in arguments if not isinstance(arg.outcome, values.Ok)), None)
        if failed is not None:
            return failed
        result = library.run(node.fn, tuple(arg.outcome.value for arg in arguments), trace=True)
        steps = result.steps + sum(arg.steps for arg in arguments)
        trace = copy(result.trace)
        trace.children = [arg.trace for arg in arguments if arg.trace is not None] + trace.children
        trace.steps = steps
        return kernel.Run(result.outcome, steps, result.jumps + sum(arg.jumps for arg in arguments), trace)

    run = run_expression(expression)
    if isinstance(run.outcome, values.Unknown):
        raise TypeError(f"evaluation did not finish: {text}: {run.outcome}")
    return {"text": text, "inputs": [values.encode(item) for item in inputs],
            "outcome": values.encode_outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace, max_nodes=20)}, run


def build_export() -> dict:
    library = build_library()
    declaration = json.loads((ROOT / "worlds/decl/v2/permutation@1.json").read_text(encoding="utf-8"))
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    story = []
    fresh = fresh_nodes()
    for source, (name, expression, inputs) in zip(design["tower"], sample_nodes(library)):
        definition = library.get(name)
        example, run = _example(library, expression, inputs, expression_text(expression))
        assert isinstance(run.outcome, values.Ok) and render(run.outcome.value) == source["value"], (name, run.outcome, source["value"])
        second = fresh[name]
        fresh_values = tuple(node.value for node in nodes.walk(second) if isinstance(node, nodes.Lit)
                             and not isinstance(node.value, values.Bottom))
        fresh_example, fresh_run = _example(library, second, fresh_values, expression_text(second))
        assert isinstance(fresh_run.outcome, values.Ok), (name, fresh_run.outcome)
        display_layer = definition.layer if name == "center" else source["layer"]
        symbol = (f"{name}<...>" if definition.kind == "object" else
                  f"@{name}[f]" if name == "power" else
                  f"@{name}[f,g]" if name == "closure" else
                  f"?{name}{{...}}" if definition.kind == "observation" else
                  f"{name}(...)")
        story.append({"layer": display_layer, "def_layer": definition.layer,
                      "kind": definition.kind, "name": name, "symbol": symbol,
                      "title": name.replace("_", " ").title(), "definition": definition.spec.rule if definition.kind == "operation" else
                      f"Build {name} from previously available twelve-card primitives.",
                      "body_sha256": export_util.body_sha256(definition.body),
                      **({"decl": source_text} if (source_text := declaration_source(definition)) else {}),
                      "design_decl": source["decl"],
                      "plain_zh": source["plain"],
                      "title_zh": source["plain"].split("，")[0], "definition_zh": source["plain"],
                      "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body) if definition.body is not None else None,
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [example, fresh_example]})
    failure, failed = _example(library, call("closure", nodes.Lit(kernel.FnRef("reset")),
                                                   nodes.Lit(kernel.FnRef("rotate_pair")), nodes.Lit(hosts.I)),
                               (kernel.FnRef("reset"), kernel.FnRef("rotate_pair"), hosts.I),
                               expression_text(call("closure", nodes.Lit(kernel.FnRef("reset")),
                                                    nodes.Lit(kernel.FnRef("rotate_pair")), nodes.Lit(hosts.I))))
    assert failed.outcome == values.Bottom("not_bijective")
    story[7]["examples"].append(failure)
    group_result = library.run("closure", (kernel.FnRef("compose_r"), kernel.FnRef("compose_s"), hosts.I))
    assert isinstance(group_result.outcome, values.Ok)
    members = group_result.outcome.value.fields
    invert = []
    for member in members:
        fixed = library.run("conjugate", (hosts.S, member)).outcome
        order = library.run("order", (member,)).outcome
        sign = library.run("sign", (member,)).outcome
        if fixed == values.Ok(hosts.S) and order == values.Ok(2) and sign == values.Ok("odd"):
            invert.append(member)
    center_expression = sample_nodes(library)[-1][1]
    _, center_run = _example(library, center_expression, (), expression_text(center_expression))
    half_turn = library.run("power", (kernel.FnRef("compose_r"), 6, hosts.I)).outcome
    assert isinstance(center_run.outcome, values.Ok) and isinstance(half_turn, values.Ok)
    decide = center_run.outcome.value.fields == tuple(sorted((hosts.I, half_turn.value), key=lambda item: item.fields))
    fifth = library.run("power", (kernel.FnRef("compose_r"), 5, hosts.I)).outcome
    conjugated = library.run("conjugate", (hosts.S, fifth.value)).outcome
    product = library.run("compose", (hosts.S, conjugated.value)).outcome
    computed = library.run("order", (product.value,)).outcome
    results = ("Set<" + ",".join(map(render, invert)) + ">", "true" if decide else "false", render(computed.value))
    showcase = []
    for source, actual in zip(design["showcase"], results):
        assert actual == source["answer"], (source["angle"], actual, source["answer"])
        showcase.append({**source, "answer_checked": True, "answer_check_method": "kernel exhaustive 24-member subgroup" if source["angle"] == "Invert" else
                         "kernel-composed operations and observations"})
    return {"schema": "opulse.world_v2_export/1", "world": "permutation", "version": 1,
            "wave": 2, "tower_source": "depth", "title": declaration["title"], "title_zh": design["name"],
            "pitch_zh": design["pitch"], "modality_zh": design["modalities"]["text"],
            "modalities_zh": design["modalities"], "toy_risk_zh": design["toy_risk"],
            "decl": declaration,
            "layer0": {"objects": [{"name": item["name"], "form": item["form"],
                                    "symbol": "Perm<...>" if item["name"] == "permutation" else
                                    "Perm<" + ",".join(map(str, getattr(hosts, item["name"]).fields)) + ">",
                                    "decl": source.split(" given")[0], "title": item["name"],
                                    "definition": item.get("doc", "A given card object."),
                                    "doc": item.get("doc"), "doc_zh": source.split(" — ")[-1]}
                                   for item, source in zip((next(obj for obj in declaration["objects"] if obj["name"] == name)
                                                            for name in ("permutation", "I", "R", "S")),
                                                           design["layer0"]["objects"])],
                       "operations": [{"name": item["name"], "symbol": f"{item['name']}(...)",
                                       **({"decl": design["layer0"]["operations"][0].split(" given")[0]}
                                          if item["name"] == "swap" else {}),
                                       "title": item["name"], "definition": item["rule"],
                                       "rule": item["rule"], "rule_zh": "交换十二位置上的两张牌。" if item["name"] == "swap" else "通用有限列表或整数原语。",
                                       "errors": item["errors"], "cost": item["cost"],
                                       "inputs": [{"name": edge.get("name"), "sort": edge["sort"]} for edge in item["inputs"]],
                                       "output": item["output"]["sort"]} for item in declaration["operations"]],
                       "combinators": {**{key: declaration["combinators"][key] for key in ("nodes", "recursion")},
                                       "library": [{**comb, "symbol": "@then[f,g]", "title": "Then", "definition":
                                                    "Apply the first operation, then the second operation."}
                                                   for comb in declaration["combinators"]["library"]]},
                       "observation": {key: declaration["observation"][key] for key in ("truth", "show", "judge_view")}
                       | {"probes": [{"name": probe["name"], "symbol": f"?{probe['name']}{{...}}",
                                       "sort": probe["sort"], "reveals": probe["reveals"],
                                       "decl": design["layer0"]["observations"][0].split(" given")[0],
                                       "title": "Cards", "definition": "Read every currently visible card position."}
                                      for probe in declaration["observation"]["probes"]]}},
            "story": story, "ladder": design["ladder"], "showcase": showcase,
            "tags": {"domain": "math", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "combinator", "reasoning": ["compute", "search", "counting", "equivalence"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full", "agents": "1",
                     "scale": "12 cards, up to 4096 generated members, 12 tower cards",
                     "difficulty": "4 active cards through a 12-card dihedral group",
                     "uses": ["evaluation", "teaching", "experiment"]},
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "emerges_zh": "十二张牌的置换群、轨道闭包与群中心从可见交换中推导。",
            "checking_zh": "有限四位置族与十二张牌的二面体群用独立参考实现交叉核对。"}


def main():
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    main()
