"""Export the verified ten-card circuit tower and its finite examples."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, notation, values
from opulse.atoms import nodes as n
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.circuits import deep, hosts
from opulse.worlds_v2.circuits.story import build_depth_library
from opulse.worlds_v2.circuits.world import DECL_PATH
from opulse.worlds_v2.export_util import finalize_export

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/circuits.json"
JUDGE_PATH = ROOT / "worlds/judge/circuits.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/circuits.json"
TOWER = (("or2", "operation", "OR circuit"), ("pair_graph", "combinator", "parallel pairing"),
         ("Xor", "object", "XOR circuit"), ("truth_table", "observation", "truth table"),
         ("full_adder", "operation", "full adder"), ("ripple", "combinator", "carry chain"),
         ("Adder8", "object", "eight-bit adder"), ("multiply4", "operation", "four-bit product"),
         ("first_diff", "observation", "first difference"),
         ("equiv", "combinator", "finite equivalence"))


def _bits(*bits):
    return hosts.bit_list(bits)


def _number(number, width):
    return tuple((number >> index) & 1 for index in range(width))


def _run(lib, name, args, *, trace=True):
    return lib.run(name, args, trace=trace)


def _text(node):
    if isinstance(node, n.Var):
        return node.name
    if isinstance(node, n.Call):
        if node.fn in ("pair_graph", "ripple", "equiv"):
            slots = {"pair_graph": 2, "ripple": 1, "equiv": 2}[node.fn]
            operations = node.args[:slots]
            if all(isinstance(arg, n.Lit) and isinstance(arg.value, kernel.FnRef)
                   for arg in operations):
                names = ",".join(arg.value.name for arg in operations)
                return f"@{node.fn}[{names}]({','.join(_text(arg) for arg in node.args[slots:])})"
        if node.fn in ("out_pin", "truth_table", "first_diff"):
            return f"?{node.fn}{{{','.join(_text(arg) for arg in node.args)}}}"
        if node.fn in ("xor_comm", "adder_correct", "mult_comm"):
            return f"#{node.fn}({','.join(_text(arg) for arg in node.args)})"
        return f"{node.fn}({','.join(_text(arg) for arg in node.args)})"
    if isinstance(node, n.Lit):
        item = node.value
        if isinstance(item, kernel.FnRef):
            return f"FnRef<{item.name}>"
        return notation.print_value(item)
    raise TypeError(f"unsupported example expression: {node!r}")


def _source(definition):
    written = replace(definition, status="written", evidence=None, contract=None, id=None,
                      cost=Cost())
    try:
        source = notation.print_definition(written)
    except (ValueError, TypeError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def _example(lib, name, expression, inputs):
    def evaluate(node):
        if isinstance(node, n.Lit):
            return node.value, None
        arguments = tuple(evaluate(arg) for arg in node.args)
        run = lib.run(node.fn, tuple(value for value, _ in arguments), trace=True)
        children = [trace for _, trace in arguments if trace is not None]
        trace = replace(run.trace, steps=run.steps + sum(child.steps for child in children),
                        children=[*children, *run.trace.children])
        return run.outcome.value if isinstance(run.outcome, values.Ok) else run.outcome, trace

    result, trace = evaluate(expression)
    outcome = (result if isinstance(result, (values.Bottom, values.Unknown)) else values.Ok(result))
    text = _text(expression)
    try:
        printed = notation.print_expr(expression)
        if notation.parse_expr(printed) == expression:
            text = printed
    except (ValueError, TypeError, notation.NotationError):
        pass
    return {"text": text, "inputs": [n.to_json(n.Lit(item))["value"] for item in inputs],
            "outcome": values.encode_outcome(outcome), "steps": trace.steps,
            "trace": _large_trace(trace, include_children=name in
                                  ("xor_comm", "adder_correct", "mult_comm"))}


def _public_value(item):
    if isinstance(item, dict):
        if item.get("t") in ("circuit", "gates", "gate", "ports"):
            return {"sealed": item["t"]}
        return {key: _public_value(value) for key, value in item.items() if key != "judge_view"}
    if isinstance(item, list):
        return [_public_value(value) for value in item]
    return item


def _large_trace(root, *, include_children=False):
    visible = [replace(child, children=[]) for child in root.children] if include_children else []
    trace = export_util.trace_json(replace(root, children=visible))
    pending, elided = ([descendant for child in root.children for descendant in child.children]
                       if include_children else list(root.children)), 0
    while pending:
        current = pending.pop()
        elided += 1
        pending.extend(current.children)
    trace["elided"] = elided
    return trace


def build_export() -> dict:
    lib = build_depth_library()
    source = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    declaration = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    bits_01, bits_10 = _bits(0, 1), _bits(1, 0)
    pairs = _bits(*_number(13, 4), *_number(5, 4))
    adder_input = _bits(*_number(200, 8), *_number(100, 8))
    product_input = _bits(*_number(13, 4), *_number(11, 4))
    adder = _run(lib, "adder8_graph", ()).outcome.value
    cut = _run(lib, "cut_add8", ()).outcome.value
    product = _run(lib, "multiply4", ()).outcome.value
    swapped = _run(lib, "multiply4_swap", ()).outcome.value
    xor = _run(lib, "xor_graph", ()).outcome.value
    diagrams = (
        (lib.run("or2", ()).outcome.value,),
        (lib.run("pair_graph", (kernel.FnRef("and2"),
                                 kernel.FnRef("or2"), 2)).outcome.value,),
        (xor,), (xor,), (lib.run("full_adder", ()).outcome.value,),
        (lib.run("ripple", (kernel.FnRef("full_adder"), 4)).outcome.value,),
        (adder,), (product,), (adder, cut), (product, swapped))
    expressions = (
        (deep.call("out_pin", deep.call("or2"), deep.lit(bits_01), deep.lit(0)), [bits_01]),
        (deep.call("out_pin", deep.call("pair_graph", deep.lit(kernel.FnRef("and2")),
                                       deep.lit(kernel.FnRef("or2")),
                                       deep.lit(2)), deep.lit(bits_10), deep.lit(1)),
         [kernel.FnRef("and2"), kernel.FnRef("or2"), bits_10]),
        (deep.call("out_pin", deep.xor_graph(), deep.lit(bits_10), deep.lit(0)), [bits_10]),
        (deep.call("truth_table", deep.xor_graph()), []),
        (deep.call("out_pin", deep.call("full_adder"), deep.lit(_bits(1, 1, 1)), deep.lit(1)),
         [_bits(1, 1, 1)]),
        (deep.call("out_pin", deep.call("ripple", deep.lit(kernel.FnRef("full_adder")), deep.lit(4)),
                   deep.lit(pairs), deep.lit(4)), [kernel.FnRef("full_adder"), pairs]),
        (deep.call("out_pin", deep.adder8_graph(), deep.lit(adder_input), deep.lit(8)),
         [adder_input]),
        (deep.call("out_pin", deep.call("multiply4"), deep.lit(product_input), deep.lit(7)),
         [product_input]),
        (deep.call("first_diff", deep.adder8_graph(), deep.call("cut_add8")), []),
        (deep.call("equiv", deep.lit(kernel.FnRef("multiply4")),
                   deep.lit(kernel.FnRef("multiply4_swap")), deep.lit(8)),
         [kernel.FnRef("multiply4"), kernel.FnRef("multiply4_swap")]),
    )
    story = []
    for layer, ((name, kind, title), design, (expression, inputs)) in enumerate(
            zip(TOWER, source["tower"], expressions), 1):
        definition = lib.get(name)
        if definition.kind != kind:
            raise ValueError(f"wrong tower kind for {name}")
        if name == "equiv":
            run = _run(lib, "equiv", (kernel.FnRef("multiply4"),
                                       kernel.FnRef("multiply4_swap"), 8))
            example = {"text": _text(expression), "inputs": [n.to_json(n.Lit(item))["value"]
                         for item in inputs], "outcome": values.encode_outcome(run.outcome),
                       "steps": run.steps, "trace": _large_trace(run.trace)}
        else:
            example = _example(lib, name, expression, inputs)
        example["learner_view"] = {"granted_probes": ["out_pin"],
                                   "observed_outcome": example["outcome"]}
        example["judge_view"] = {"full_state": [values.encode(circuit)
                                                  for circuit in diagrams[layer - 1]]}
        if name == "first_diff":
            failure = _example(lib, name, deep.call("first_diff", deep.adder8_graph(),
                deep.call("and2")), [])
            failure["learner_view"] = {"granted_probes": ["out_pin"],
                                       "observed_outcome": failure["outcome"]}
            failure["judge_view"] = {"full_state": [values.encode(adder),
                                                      values.encode(hosts.deep_and2())]}
            story_failure = failure
        story.append({"layer": definition.layer, "design_layer": layer,
                      "def_layer": definition.layer, "kind": kind,
                      "name": name, "title": title,
                      "definition": f"{title} assembled from typed AND/NOT circuits and verified by the kernel.",
                      "body_sha256": export_util.body_sha256(definition.body),
                      **({"decl": source_text} if (source_text := _source(definition)) else {}),
                      "design_decl": design["decl"],
                      "plain_zh": design["plain"],
                      "symbol": (f"@{name}[...]" if kind == "combinator" else
                                 f"?{name}{{...}}" if kind == "observation" else
                                 f"{name}<...>" if kind == "object" else f"{name}(...)"),
                      "title_zh": design["plain"], "definition_zh": design["plain"],
                      "depends_on": list(definition.depends_on), "body": n.to_json(definition.body),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [example]})
    story[8]["examples"].append(story_failure)
    for item, design in zip(story, source["tower"]):
        outcome = item["examples"][0]["outcome"]
        if "ok" not in outcome:
            raise ValueError(f"tower example failed: {item['name']}: {outcome}")
        result = values.decode(outcome["ok"])
        rendered = (f"List<{','.join(map(str, result.fields))}>" if item["name"] == "truth_table"
                    else f"Witness<{','.join(map(str, result.fields))}>" if item["name"] == "first_diff"
                    else result)
        if rendered != design["value"]:
            raise ValueError(f"wrong design value: {item['name']}: {rendered} != {design['value']}")

    fresh = _example(lib, "Xor",
        deep.call("out_pin", deep.xor_graph(), deep.lit(bits_01), deep.lit(0)),
        [bits_01])
    fresh["learner_view"] = {"granted_probes": ["out_pin"],
                              "observed_outcome": fresh["outcome"]}
    fresh["judge_view"] = {"full_state": [values.encode(xor)]}
    story[2]["examples"].append(fresh)

    laws = []
    for name, operands, title_zh, definition_zh in (
        ("xor_comm", (0, 1),
         "异或交换律", "交换两个输入，异或结果不变。"),
        ("adder_correct", (13, 5),
         "加法器正确性", "有限输入上的电路输出等于整数之和。"),
        ("mult_comm", (13, 11),
         "乘法电路交换律", "交换两个输入，乘法电路结果不变。"),
    ):
        definition = lib.get(name)
        example = _example(lib, name, deep.call(name, *(deep.lit(value) for value in operands)),
                           operands)
        example["learner_view"] = {"granted_probes": ["out_pin"],
                                   "observed_outcome": example["outcome"]}
        laws.append({"name": name, "kind": "law", "symbol": f"#{name}", "layer": len(story) + len(laws) + 1,
                     "def_layer": definition.layer, "title": name.replace("_", " ").capitalize(),
                     "title_zh": title_zh, "definition_zh": definition_zh,
                     "definition": f"Bounded invariant over {definition.evidence.scope['size']} operand pairs.",
                     "depends_on": list(definition.depends_on), "status": definition.status,
                     "body": n.to_json(definition.body),
                     "body_sha256": export_util.body_sha256(definition.body),
                     **({"decl": source_text} if (source_text := _source(definition)) else {}),
                     "design_decl": f"Bounded invariant over {definition.evidence.scope['size']} operand pairs.",
                     "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                     "cost": definition.cost.to_dict(), "examples": [example]})

    def read_outputs(graph, inputs, count):
        return tuple(_run(lib, "out_pin", (graph, inputs, pin)).outcome.value for pin in range(count))

    product_bits = read_outputs(product, product_input, 8)
    product_number = sum(bit << index for index, bit in enumerate(product_bits))
    total_bits = read_outputs(adder, _bits(*product_bits, *_number(91, 8)), 9)
    compute = f"Result<{product_number},{sum(bit << i for i, bit in enumerate(total_bits[:8]))},{total_bits[8]}>"
    inverted = [(left, right) for left in range(16) for right in range(16)
                if sum(bit << index for index, bit in enumerate(read_outputs(
                    product, _bits(*_number(left, 4), *_number(right, 4)), 8))) == 90]
    invert = "List<" + ",".join(f"Pair<{left},{right}>" for left, right in inverted) + ">"
    decision = values.decode_outcome(story[9]["examples"][0]["outcome"]).value
    witness = values.decode_outcome(story[8]["examples"][0]["outcome"]).value
    decide = f"Result<{decision},Witness<{','.join(map(str, witness.fields))}>>"
    for item, answer in zip(source["showcase"], (compute, invert, decide)):
        if answer != item["answer"]:
            raise ValueError(f"showcase mismatch: {answer}")
    showcase = [{"angle": task["angle"], "kinds_involved": task["kinds_involved"],
                 "prompt": task["prompt"].replace("0<=x,y<16", "le(0,x), le(0,y), lt(x,16), lt(y,16)"),
                 "answer": task["answer"], "why_hard_zh": task["why_hard"],
                 "check_zh": task["check"], "answer_checked": True,
                 "check_method": "kernel execution over typed AND/NOT DAGs and all stated input rows"}
                for task in source["showcase"]]
    objects_zh = {"bit": source["layer0"]["objects"][0],
                  "bits": source["layer0"]["objects"][1],
                  "circuit": source["layer0"]["objects"][2]}
    judge = {"world": "circuits", "version": 1, "examples": []}
    for row in story:
        for index, example in enumerate(row["examples"]):
            judge["examples"].append({"id": f"{row['name']}:{index}", "inputs": example["inputs"],
                                      "judge_view": example["judge_view"]})
    for row, graph in zip(laws, (xor, diagrams[5][0], product)):
        judge["examples"].append({"id": f"{row['name']}:0", "inputs": row["examples"][0]["inputs"],
                                  "judge_view": {"full_state": [values.encode(graph)]}})
    JUDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    JUDGE_PATH.write_text(json.dumps(judge, sort_keys=True, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
    story.extend(laws)
    story = _public_value(story)
    laws = _public_value(laws)
    return {"schema": "opulse.world_v2_export/1", "world": "circuits", "version": 1,
            "wave": 1, "tower_source": "depth", "title": declaration["title"],
            "title_zh": source["name"], "pitch_zh": source["pitch"],
            "modality_zh": source["modalities"]["text"],
            "modalities_zh": source["modalities"], "toy_risk_zh": source["toy_risk"],
            "decl": declaration,
            "layer0": {
                "objects": [{"name": obj["name"], "form": obj["form"],
                             "symbol": obj["name"].capitalize() + "<...>",
                             "title": obj["name"].capitalize(),
                             "definition": obj.get("doc", "") or f"A given {obj['name']} circuit value.",
                             "doc": obj.get("doc", ""),
                             "doc_zh": objects_zh.get(obj["name"], "")}
                            for obj in declaration["objects"]],
                "operations": [{"name": op["name"], "symbol": op["name"] + "(...)",
                                "title": op["name"].replace("_", " ").capitalize(),
                                "definition": op["rule"] or f"Given {op['name']} operation.",
                                "rule": op["rule"],
                                "rule_zh": "", "errors": op["errors"], "cost": op["cost"],
                                "inputs": [{"name": edge["name"], "sort": edge["sort"]}
                                           for edge in op["inputs"]], "output": op["output"]["sort"]}
                               for op in declaration["operations"]],
                "combinators": {key: declaration["combinators"][key]
                                for key in ("nodes", "library", "recursion", "unfold_rules")}
                               | {"title": "Circuit combinators", "definition": "Unfold circuit graph composition through kernel nodes."},
                "observation": {key: declaration["observation"][key]
                                for key in ("truth", "show", "judge_view")}
                               | {"title": "Circuit observations", "definition": "Read only granted output pins.",
                                  "probes": [{"name": probe["name"], "sort": probe["sort"],
                                              "title": probe["name"].replace("_", " ").capitalize(),
                                              "definition": "Reads one authorized output pin.",
                                              "reveals": probe["reveals"]}
                                             for probe in declaration["observation"]["probes"]]}},
            "story": story, "laws": laws,
            "support": [{"name": definition.name, "kind": definition.kind,
                         "def_layer": definition.layer}
                        for definition in lib.definitions.values()
                        if definition.layer > 0 and definition.name not in
                        {item['name'] for item in (*story, *laws)}],
            "ladder": [{"level": step["level"], "knobs_zh": step["knobs"],
                        "what_changes_zh": step["what_changes"]} for step in source["ladder"]],
            "showcase": showcase,
            "tags": {"domain": "logic", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation", "law"],
                     "star_kind": "combinator", "reasoning": ["compute", "search", "equivalence"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "partial",
                     "agents": 1, "scale": "16 pins; 1024 gates; ten definitions",
                     "difficulty": "four truth rows to 65536 possible input rows",
                     "uses": ["evaluation", "teaching", "experiment"]},
            "open_kinds": ["object", "operation", "combinator", "observation", "law"],
            "emerges_zh": source["pitch"], "checking_zh": source["toy_risk"]}


def main():
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))



if __name__ == "__main__":
    main()
