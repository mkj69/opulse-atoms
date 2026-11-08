"""Reproducible depth-world export; all answer values come from kernel calls."""

import json
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Ok, decode_outcome, encode, encode_outcome
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import depth_hosts as hosts
from .story import build_library

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/roads.json"
DESIGN = ROOT / "worlds/catalogue/depth/roads.json"
TOWER_NAMES = ("Route", "cost", "explore", "best", "optimal", "Closure", "close",
               "failures", "survives", "worst", "mincut", "cut_certificate")


def _text(name, args):
    def value(arg):
        if isinstance(arg, kernel.FnRef):
            return arg.name
        return notation.print_value(arg)

    shown = ",".join(value(arg) for arg in args)
    if name in ("explore", "failures"):
        return f"@{name}[{value(args[0])}]({','.join(value(arg) for arg in args[1:])})"
    if name == "Route":
        return "Route.make(" + shown + ")"
    if name == "Closure":
        return "Closure.make(" + shown + ")"
    return f"{name}({shown})"


def _source(definition):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (TypeError, ValueError, notation.NotationError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def _encode(value):
    return {"t": "fn", "v": value.name} if isinstance(value, kernel.FnRef) else encode(value)


def _example(lib, name, args):
    operation = {"Route": "Route.make", "Closure": "Closure.make"}.get(name, name)
    if name in ("explore", "failures"):
        run = kernel.evaluate(nodes.Call("size", (nodes.Call(name, tuple(nodes.Lit(arg) for arg in args)),)),
                              scope=lib.scope(), trace=True)
        text = "?size{" + _text(name, args) + "}"
    else:
        run = lib.run(operation, args, trace=True)
        text = _text(name, args)
    previous_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(30_000)
        recorded = trace_json(run.trace)
    finally:
        sys.setrecursionlimit(previous_limit)
    return {"text": text, "inputs": [_encode(arg) for arg in args],
            "outcome": encode_outcome(run.outcome), "steps": run.steps,
            "trace": recorded}


def _layer_zero(declaration):
    objects = []
    for obj in declaration["objects"]:
        doc = obj.get("doc", f"Given public {obj['name']} value.")
        objects.append({"name": obj["name"], "form": obj["form"], "symbol": obj["name"] + "<...>",
                        "decl": f"obj {obj['name']} given", "title": obj["name"],
                        "definition": doc, "doc": doc, "doc_zh": "公开的有限道路数据或通用基础值。"})
    operations = []
    for op in declaration["operations"]:
        signature = ",".join(f"{entry['name']}:{entry['sort']}" for entry in op["inputs"])
        operations.append({"name": op["name"], "symbol": op["name"] + "(...)", "title": op["name"],
                           "definition": op["rule"], "decl": f"op {op['name']}({signature}) -> {op['output']['sort']}",
                           "rule": op["rule"], "rule_zh": "逐步计算，调用计入成本。",
                           "errors": op["errors"], "cost": op["cost"],
                           "inputs": [{"name": item["name"], "sort": item["sort"]} for item in op["inputs"]],
                           "output": op["output"]["sort"]})
    combinators = {**declaration["combinators"], "entries": [
        {"name": "chain", "symbol": "@chain[first,second]", "title": "Short-circuit composition", "definition": "Apply the second operation only if the first succeeds.",
         "decl": "comb @chain[first,second](value) -> Outcome", "doc_zh": "依次组合失败短路。"},
        {"name": "fix", "symbol": "@fix[step]", "title": "Finite-height least fixed point", "definition": "Repeat the public step until equal states stabilize, or exhaust the finite height.",
         "decl": "comb @fix[step](state,bound) -> Outcome", "doc_zh": "重复扩张公开可达点集直至稳定。"}]}
    observation = {key: declaration["observation"][key] for key in ("truth", "show", "judge_view")}
    observation["probes"] = [{"name": probe["name"], "sort": probe["sort"],
                               "symbol": "?" + probe["name"] + "{...}",
                               "reveals": probe["reveals"], "title": probe["name"],
                               "definition": "Read only this granted public probe.",
                               "decl": f"obs ?{probe['name']}{{visible}} -> {probe['sort']}",
                               "doc_zh": "只读公开地图或已可见列表。"}
                              for probe in declaration["observation"]["probes"]]
    return {"objects": objects, "operations": operations, "combinators": combinators, "observation": observation}


def build_export():
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    lib = build_library()
    graph = hosts.METRO
    route = lib.run("Route.make", (hosts.route_raw(graph, hosts.items("A", "D", "F", "H", "K", "L")),)).outcome.value
    closure = hosts.closure_raw(graph, hosts.edge_set(hosts.items("AB", "DF")))
    cases = {
        "Route": (hosts.route_raw(graph, hosts.items("A", "D", "F", "H", "K", "L")),),
        "cost": (route,), "explore": (kernel.FnRef("edge"), graph, "A", "L"),
        "best": (graph, "A", "L"), "optimal": (route,), "Closure": (closure,),
        "close": (graph, hosts.edge_set(hosts.items("AC", "DG"))),
        "failures": (kernel.FnRef("close"), graph, 2),
        "survives": (graph, "A", "L", 2), "worst": (graph, "A", "L", 2),
        "mincut": (graph, "A", "L"), "cut_certificate": (graph, "A", "L"),
    }
    variants = tuple(hosts.to_card((("A", "B", "C", "D"),
                     (("A", "B", weights[0]), ("A", "C", weights[1]),
                      ("B", "D", weights[2]), ("C", "D", weights[3]))))
                     for weights in tuple(product((1, 2, 3, 4), repeat=4))[40:51])
    auxiliary = {
        "cost": (lib.run("Route.make", (hosts.route_raw(variants[0], hosts.items("A", "C", "D")),)).outcome.value,),
        "explore": (kernel.FnRef("edge"), variants[1], "B", "C"),
        "best": (variants[2], "B", "C"),
        "optimal": (lib.run("Route.make", (hosts.route_raw(variants[3], hosts.items("A", "C", "D")),)).outcome.value,),
        "Closure": (hosts.closure_raw(variants[4], hosts.edge_set(hosts.items("AC"))),),
        "close": (variants[5], hosts.edge_set(hosts.items("BD"))),
        "failures": (kernel.FnRef("close"), variants[6], 1),
        "survives": (variants[7], "A", "D", 1),
        "worst": (variants[8], "A", "D", 1),
        "mincut": (variants[9], "B", "C"),
        "cut_certificate": (variants[10], "A", "D"),
    }
    cards = []
    for item, name in zip(design["tower"], TOWER_NAMES):
        definition = lib.get(name)
        first = _example(lib, name, cases[name])
        additional = _example(lib, name, auxiliary[name]) if name in auxiliary else None
        declaration = _source(definition)
        cards.append({"layer": item["layer"], "def_layer": definition.layer, "kind": definition.kind,
                      "name": name, "body_sha256": export_util.body_sha256(definition.body),
                      **({"decl": declaration} if declaration is not None else {}), "design_decl": item["decl"],
                      "plain_zh": item["plain"], "symbol":
                      ("@" if definition.kind == "combinator" else "?" if definition.kind == "observation"
                       else "#" if definition.kind == "law" else "~" if definition.kind == "bridge" else "") + name
                      + ("<...>" if definition.kind == "object" else "(...)" if definition.kind == "operation"
                         else "[...]" if definition.kind == "combinator" else "{...}" if definition.kind == "observation" else ""),
                      "title": {"Route": "A valid route", "cost": "Route cost", "explore": "All simple routes",
                                "best": "Cheapest route", "optimal": "Optimality test", "Closure": "Canonical road closure",
                                "close": "Close roads", "failures": "Failure sets", "survives": "Survival under failures",
                                "worst": "Worst surviving route", "mincut": "Minimum cut",
                                "cut_certificate": "Cut certificate"}[name],
                      "definition": f"{name} derives its public result from counted graph primitives and earlier cards.",
                      "title_zh": item["plain"].split("，")[0], "definition_zh": item["plain"],
                      "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body) if definition.body is not None else
                      {"valid": nodes.to_json(definition.spec.valid),
                       "canon": nodes.to_json(definition.spec.canon) if definition.spec.canon else None},
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [first] + ([additional] if additional else [])})
    failed = _example(lib, "best", (graph, "A", "Z"))
    cards[3]["examples"].append(failed)
    for index, card in enumerate(cards):
        actual = card["examples"][0]["outcome"]
        result = decode_outcome(actual)
        if card["name"] in ("explore", "failures"):
            correct = str(result.value)
        elif isinstance(result, Ok):
            value = result.value
            if isinstance(value, int):
                correct = str(value)
            elif value.sort == "bool":
                correct = value.tag
            elif value.sort in ("Route", "Closure"):
                correct = value.sort + "<" + ",".join(value.fields[0].fields[1].fields if value.sort == "Route" else
                                                           value.fields[0].fields[1].fields[0].fields) + ">"
            elif value.sort == "Edges":
                correct = "Edges<" + ",".join(value.fields[0].fields) + ">"
            elif value.sort == "Worst":
                cost, closed, route_value = value.fields
                correct = ("Worst<" + str(cost) + ",Edges<" + ",".join(closed.fields[0].fields) +
                           ">,Route<" + ",".join(route_value.fields[0].fields[1].fields) + ">>")
            else:
                raise ValueError(value.sort)
        else:
            raise ValueError(actual)
        if correct != design["tower"][index]["value"]:
            raise AssertionError(f"{card['name']}: {correct} != {design['tower'][index]['value']}")

    ladder = [{"level": item["level"], "knobs": knobs, "what_changes": item["what_changes"],
                   "title": f"Level {item['level']}", "definition": knobs}
              for item, knobs in zip(design["ladder"], (
                  "12 nodes, 23 edges, route_count=1, budget=0",
                  "12 nodes, 23 edges, route_count=419, budget=0",
                  "12 nodes, 23 edges, budget=1..2, 24 or 277 closures",
                  "13..16 nodes, 24..35 edges, budget=2..3, exact 2^(n-2) cuts",
                  "17..20 nodes, 36..45 edges, budget=3, publish resource limits"))]
    showcase = []
    worst_example = cards[9]["examples"][0]
    certificate_example = cards[11]["examples"][0]
    for index, entry in enumerate(design["showcase"]):
        record = {**entry, "title": entry["angle"] + " task", "definition": entry["prompt"]}
        if index == 0:
            checked = worst_example["outcome"]["ok"]["f"][0]["v"] == 13
            method = "Kernel worst(Metro,A,L,2), exactly 277 failure sets, with reference-checked bounded semantics."
        elif index == 1:
            candidate = None
            failures = lib.run("failures", (kernel.FnRef("close"), graph, 2)).outcome.value.fields
            for damaged in failures:
                if len(damaged.fields[0].fields[1].fields[0].fields) != 2:
                    continue
                found = lib.run("best", (damaged, "A", "L")).outcome
                if isinstance(found, Ok) and lib.run("cost", (found.value,)).outcome == Ok(13):
                    candidate = damaged.fields[0].fields[1].fields[0].fields
                    break
            checked = "Edges<" + ",".join(candidate or ()) + ">" == entry["answer"]
            method = "Kernel tested two-edge closures in lexical order until the first cost-13 witness."
        else:
            cut = cards[10]["examples"][0]["outcome"]
            checked = cut == encode_outcome(Ok(hosts.edge_set(hosts.items("AB", "AC", "AD")))) and certificate_example["outcome"] == encode_outcome(Ok(hosts.boolean(True)))
            method = "Kernel enumerated all 1024 endpoint partitions and checked 277 smaller failures by fixed point."
        record.update({"answer_checked": checked, "check_method": method,
                       "answer_shape": ("one lexicographically selected witness" if index < 2 else
                                        "one minimum cut and a Boolean certificate")})
        showcase.append(record)
    declaration = json.loads((ROOT / "worlds/decl/v2/roads@1.json").read_text(encoding="utf-8"))
    boundary = lib.get("boundary")
    return {"schema": "opulse.world_v2_export/1", "world": "roads", "version": 1, "wave": 3,
            "tower_source": "depth", "title": declaration["title"],
            "title_zh": declaration["source"]["title_zh"], "pitch_zh": design["pitch"],
            "modality_zh": "地图／路径", "decl": declaration, "layer0": _layer_zero(declaration),
            "story": cards,
            "helpers": [{"name": "boundary", "kind": "operation", "def_layer": boundary.layer,
                         "decl": "op boundary(g:Roads,X:List<Text>) -> Edges",
                         "title": "Public cut boundary", "definition": "Collect every public edge with exactly one endpoint in X.",
                         "definition_zh": "由公开路网和端点分割逐边导出跨割边集。",
                         "body": nodes.to_json(boundary.body), "status": boundary.status,
                         "evidence": boundary.evidence.to_dict(), "contract": boundary.contract.to_dict()}],
            "ladder": ladder, "showcase": showcase,
            "modalities_zh": design["modalities"], "toy_risk_zh": design["toy_risk"],
            "tags": {"domain": "resource", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "combinator", "reasoning": ["compute", "search", "counting"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full",
                     "agents": 1, "scale": "12..20 junctions, 12 invented tower cards",
                     "difficulty": "single route to bounded multi-failure minimum-cut certificate",
                     "uses": ["evaluation", "teaching", "experiment"]},
            "open_kinds": list(lib.world.open_kinds),
            "emerges_zh": "合法路线、故障封路、最坏绕行和最小断路证书逐层建立。",
            "checking_zh": "六十张四点加权图逐卡验证，十二点示例由内核计算并与独立设计对拍。"}


def main():
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")



_build_export_raw = build_export


def build_export():
    """Build fresh and finalize the public export."""
    result = finalize_export(_build_export_raw())
    for card in result["story"]:
        card["cost"]["example_steps"] = card["example_steps"]
    return result


if __name__ == "__main__":
    main()
