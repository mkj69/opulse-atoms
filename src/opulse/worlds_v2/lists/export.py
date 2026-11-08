"""Generate the checked twelve-layer lists world and its bounded kernel traces."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json
from opulse.worlds_v2.lists import hosts, oracle
from opulse.worlds_v2.lists.story import build_library

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/lists.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/lists.json"
NAMES = ("NonEmpty", "fold", "reverse", "palindrome", "Run", "rle", "stable_merge",
         "sort", "merge_count", "inversions", "trace", "certificate")
ENGLISH = {
    "NonEmpty": ("Nonempty list", "Refines a public list if it contains at least one item."),
    "fold": ("Structural fold", "Combines each item with an accumulator using the supplied builder."),
    "reverse": ("List reversal", "Reverses a finite list by folding with cons."),
    "palindrome": ("Palindrome test", "Compares a public list with its reversal."),
    "Run": ("Positive run", "Refines a key and strictly positive count into a run."),
    "rle": ("Run-length encoding", "Groups consecutive equal list entries into positive runs."),
    "stable_merge": ("Stable merge", "Merges two lists using the supplied comparison operation."),
    "sort": ("Stable sort", "Recursively sorts a finite list by stable merging."),
    "merge_count": ("Cross-pair count", "Returns a merged list and the number of cross-pairs selected from the right."),
    "inversions": ("Inversion count", "Counts strictly descending pairs in a finite list."),
    "trace": ("Minimal swap trace", "Lists adjacent descending swaps that stably sort the input."),
    "certificate": ("Swap certificate", "Checks that a proposed swap trace sorts the list using exactly the inversion count."),
}


def _declaration(definition, lib):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    context = {"kinds": {item.name: item.kind for item in lib.definitions.values()}
               | {probe["name"]: "observation" for probe in lib.world.observation.get("probes", ())},
               "op_arity": {item.name: len(item.spec.op_params) for item in lib.definitions.values()
                            if item.kind == "combinator"}}
    try:
        source = notation.print_definition(written, context)
    except (TypeError, ValueError, notation.NotationError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def examples():
    def row(*items):
        return hosts.to_card(items)

    return (
        ((row(4, 1, 4),),),
        ((kernel.FnRef("cons"), row(4, 1, 2), hosts.NIL),),
        ((row(4, 1, 2),),),
        ((row(4, 1, 4),),),
        ((hosts.pair(4, 3),),),
        ((row(4, 4, 1, 1, 1, 4),),),
        ((kernel.FnRef("le"), row(1, 3, 3), row(2, 3, 5)),),
        ((row(4, 1, 4, 2, 1),),),
        ((kernel.FnRef("le"), row(1, 3, 3), row(2, 3, 5)),),
        ((row(4, 1, 4, 2, 1),),),
        ((row(3, 1, 2, 1),),),
        ((row(3, 1, 2, 1), row(0, 2, 1, 2)),),
    )


def extra_examples(lib):
    def row(*items):
        return hosts.to_card(items)

    certificate_input = row(2, 1, 3, 0)
    certificate_steps = lib.run("trace", (certificate_input,)).outcome.value
    return {
        "fold": ("", (kernel.FnRef("snoc"), row(2, -1), hosts.NIL)),
        "reverse": ("reverse(List<2, 4, -1>)", (row(2, 4, -1),)),
        "palindrome": ("?palindrome{List<2, 4, 2>}", (row(2, 4, 2),)),
        "Run": ("", (hosts.pair(2, 1),)),
        "rle": ("rle(List<2, 2, -1, -1>)", (row(2, 2, -1, -1),)),
        "stable_merge": ("", (kernel.FnRef("ge"), row(-1, 0), row(1, 1))),
        "sort": ("sort(List<5, 0, 4>)", (row(5, 0, 4),)),
        "merge_count": ("", (kernel.FnRef("ge"), row(0, 1), row(1, 1))),
        "inversions": ("?inversions{List<2, 5, 1>}", (row(2, 5, 1),)),
        "trace": ("trace(List<3, 2, 1>)", (row(3, 2, 1),)),
        "certificate": ("?certificate{List<2, 1, 3, 0>, " + oracle.reference.ascii_value(oracle.convert(certificate_steps)) + "}",
                        (certificate_input, certificate_steps)),
    }


def _example(lib, name, text, args):
    target = name + ".make" if name in ("NonEmpty", "Run") else name
    run = lib.run(target, args, trace=True)
    shown = [value.name if isinstance(value, kernel.FnRef) else notation.print_value(value) for value in args]
    if name in ("NonEmpty", "Run"):
        text = f"{target}({shown[0]})"
    elif name in ("fold", "stable_merge", "merge_count"):
        text = f"@{name}[{shown[0]}]({', '.join(shown[1:])})"
    elif name in ("palindrome", "inversions", "certificate"):
        text = f"?{name}{{{', '.join(shown)}}}"
    else:
        text = f"{name}({', '.join(shown)})"
    return {"text": text, "inputs": [{"t": "fn", "v": value.name} if isinstance(value, kernel.FnRef)
                                      else values.encode(value) for value in args],
            "outcome": values.encode_outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace)}


def _showcase(lib, design):
    first, second, third = design["showcase"]
    data_a = hosts.to_card(oracle.reference.DATA_A)
    inverse = hosts.to_card(oracle.reference.lexicographic_inverse(oracle.reference.INVERSE_TARGET, 73))
    data_c = hosts.to_card(oracle.reference.DATA_C)
    sorted_a = lib.run("sort", (data_a,)).outcome.value
    runs_a = lib.run("rle", (sorted_a,)).outcome.value
    count_a = lib.run("inversions", (data_a,)).outcome.value
    trace_a = lib.run("trace", (data_a,)).outcome.value
    computed_a = f"({count_a}, {oracle.reference.ascii_value(oracle.convert(runs_a))}, {hosts.length(trace_a)})"
    forward = lib.run("inversions", (data_c,)).outcome.value
    backward = lib.run("inversions", (lib.run("reverse", (data_c,)).outcome.value,)).outcome.value
    runs_c = hosts.from_card(lib.run("rle", (lib.run("sort", (data_c,)).outcome.value,)).outcome.value)
    equal_pairs = sum(run.fields[0].fields[1] * (run.fields[0].fields[1] - 1) // 2 for run in runs_c)
    computed_c = f"({str(forward + backward == 435).lower()}, {forward}, {backward}, {equal_pairs})"
    checks = (
        (computed_a, "Kernel inversions, sort, rle, and trace length"),
        (oracle.reference.ascii_value(oracle.convert(inverse)),
         "Kernel sort and inversions: " + str(lib.run("sort", (inverse,)).outcome.value == hosts.to_card(oracle.reference.INVERSE_TARGET)
                                                   and lib.run("inversions", (inverse,)).outcome.value == 73)
         + "; lexicographic minimality independently checked by depth reference"),
        (computed_c, "Kernel forward/reverse inversions and sorted rle multiplicities"),
    )
    result = []
    for task, (answer, method) in zip((first, second, third), checks):
        result.append({key + "_zh" if key in ("why_hard", "check") else key: value
                       for key, value in task.items()}
                      | {"answer_checked": answer == task["answer"], "check_method": method})
    return result


def build_export() -> dict:
    lib = build_library()
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    declaration = lib.world.to_dict()
    story = []
    for name, item, (args,) in zip(NAMES, design["tower"], examples()):
        definition = lib.get(name)
        card = {"layer": item["layer"], "def_layer": definition.layer, "kind": definition.kind,
                "name": name, "body_sha256": export_util.body_sha256(definition.body),
                "design_decl": item["decl"],
                "plain_zh": item["plain"],
                "title": ENGLISH[name][0], "definition": ENGLISH[name][1],
                "symbol": ("@" + name + "[" + ("cons" if name == "fold" else "le") + "]" if definition.kind == "combinator"
                           else "?" + name + "{...}" if definition.kind == "observation"
                           else name + "<...>" if definition.kind == "object" else name + "(...)"),
                "title_zh": item["plain"].split("，")[0], "definition_zh": item["plain"],
                "depends_on": list(definition.depends_on), "body": nodes.to_json(definition.body) if definition.body is not None else None,
                "status": definition.status, "evidence": definition.evidence.to_dict(),
                "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                "examples": [_example(lib, name, item["example"], args)]}
        source = _declaration(definition, lib)
        if source is not None:
            card["decl"] = source
        target = name + ".make" if name in ("NonEmpty", "Run") else name
        assert oracle.reference.ascii_value(oracle.convert(lib.run(target, args).outcome.value)) == item["value"] if name not in ("palindrome", "certificate") else lib.run(target, args).outcome.value == values.boolean(item["value"] == "true")
        story.append(card)
    story[0]["examples"].append(_example(lib, "NonEmpty", "", (hosts.NIL,)))
    extra_examples_map = extra_examples(lib)
    for card in story:
        if card["name"] in extra_examples_map:
            text, args = extra_examples_map[card["name"]]
            card["examples"].append(_example(lib, card["name"], text, args))
    layer0 = {"objects": [], "operations": [],
              "combinators": {key: declaration["combinators"][key] for key in ("nodes", "library", "recursion")},
              "observation": {key: declaration["observation"][key] for key in ("truth", "show", "judge_view")}
              | {"probes": [{"name": probe["name"], "sort": probe["sort"], "reveals": probe["reveals"],
                              "decl": "obs ?" + probe["name"] + "{xs: List<Int>} -> " + ("Int" if probe["name"] == "length" else "List<Int>") + " given",
                              "title": "Public " + probe["name"], "definition": "Reveals the public list " + probe["name"] + ".",
                              "doc_zh": "公开表长" if probe["name"] == "length" else "公开表项和顺序"}
                             for probe in declaration["observation"]["probes"]]}}
    object_lines = {"int": design["layer0"]["objects"][0],
                    "list": design["layer0"]["objects"][1],
                    "pair": design["layer0"]["objects"][2]}
    for item in declaration["objects"]:
        line = object_lines.get(item["name"], "")
        layer0["objects"].append({"name": item["name"], "form": item["form"], "symbol": item["name"] + "<...>",
                                  "decl": line.split(" — ")[0] if line else "obj " + item["name"] + " given",
                                  "doc": item.get("doc", ""), "title": item["name"] + " values",
                                  "definition": item.get("doc", "") or "Carries public values for list computations.",
                                  "doc_zh": line.split(" — ")[1] if " — " in line else "通用载体"})
    decl_lines = {line.split("(")[0].split(" ")[-1]: line for line in design["layer0"]["operations"]}
    for operation in declaration["operations"]:
        name = operation["name"]
        line = decl_lines.get(name, "")
        operation_decl = line.split(" — ")[0] if line else "op " + name + "(...) given"
        if name in ("lt", "le"):
            operation_decl = "op " + name + "(a: Int, b: Int) -> Bool = " + name + "(a, b) given"
        layer0["operations"].append({"name": name, "symbol": name + "(...)", "decl": operation_decl,
                                     "title": name + " primitive", "definition": operation["rule"],
                                     "doc_zh": line.split(" — ")[1] if " — " in line else "通用构造或访问原语",
                                     "rule": operation["rule"], "rule_zh": line.split(" — ")[1] if " — " in line else "通用原语",
                                     "errors": operation["errors"], "cost": operation["cost"],
                                     "inputs": [{"name": edge["name"], "sort": edge["sort"]} for edge in operation["inputs"]],
                                     "output": operation["output"]["sort"]})
    layer0["combinators"]["decl"] = design["layer0"]["combinators"][0].split(" — ")[0]
    layer0["combinators"]["doc_zh"] = design["layer0"]["combinators"][0].split(" — ")[1]
    layer0["combinators"]["title"] = "Sequential composition"
    layer0["combinators"]["definition"] = "Applies one operation and then a second operation."
    layer0["observation"]["title"] = "Public list probes"
    layer0["observation"]["definition"] = "Reveals only the items and length of a public immutable list."
    ladder = [{"level": entry["level"], "knobs_zh": entry["knobs"],
               "what_changes_zh": entry["what_changes"]} for entry in design["ladder"]]
    return {"schema": "opulse.world_v2_export/1", "world": "lists", "version": 2, "wave": 2,
            "title": declaration["title"], "title_zh": design["name"], "pitch_zh": design["pitch"],
            "modality_zh": "序列与递归", "decl": declaration, "layer0": layer0,
            "tower_source": "depth", "story": story, "ladder": ladder,
            "showcase": _showcase(lib, design), "modalities_zh": design["modalities"],
            "toy_risk_zh": design["toy_risk"],
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "tags": {"domain": "program", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "observation", "reasoning": ["compute", "counting", "equivalence"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full", "agents": 1,
                     "scale": "512-element lists, twelve definitions", "difficulty": "short folds to 512-element inversion counts",
                     "uses": ["rl-training", "evaluation", "interpretability", "teaching"]},
            "emerges_zh": "稳定归并、精确逆序计数和可逐步重放的最短交换证书。",
            "checking_zh": "长度至四、元素 -1..1 的全量有限输入；组合器在两个比较器上有界核验。"}


def main():
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    main()
