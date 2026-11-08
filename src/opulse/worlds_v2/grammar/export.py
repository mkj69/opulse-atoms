"""Publish the deep expression grammar with generated kernel evidence."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts
from .story import build_library, oracle

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/grammar.json"
JUDGE_PATH = ROOT / "worlds/judge/grammar.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/grammar.json"
NAMES = ("ExprTree", "split", "chart", "parse_count", "unrank", "ambiguous",
         "Ambiguity", "fold", "value_hist", "gap", "invert_gap")
TITLES = ("A Finished Tree", "Top-Level Splits", "Algebraic Chart", "Public Parse Count",
          "Ranked Parse", "Ambiguity Decision", "A Two-Tree Witness", "Tree Fold",
          "Value Multiplicities", "Semantic Gap", "Inverse Gap Search")
DEFINITIONS = (
    "Validate and seal a completed expression derivation while preserving its ordered tree.",
    "Return the binary operator positions that occur outside all parentheses.",
    "Fold every legal parse using five independently supplied algebra operations.",
    "Count parses from the public word without inspecting an author's derivation.",
    "Select a parse by its zero-based, split-first, left-major rank.",
    "Decide whether a public word has at least two parses.",
    "Seal two distinct trees whose public yields equal the same word.",
    "Interpret each leaf, binary node, and group through supplied operations.",
    "Count each arithmetic interpretation with its parse multiplicity.",
    "Subtract the minimum interpretation from the maximum.",
    "Search a finite, lexicographically ordered family for the first target gap.",
)


def format_value(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if value.sort == "bool":
        return value.tag
    if value.sort == "Word":
        return "Word<" + ",".join(map(str, value.fields)) + ">"
    if value.sort == "Draft":
        return "Draft<" + oracle().format_tree(hosts.from_card(value)) + ">"
    if value.sort == "ExprTree":
        return "ExprTree<" + oracle().format_tree(hosts.from_card(value.fields[0])) + ">"
    if value.sort == "List":
        return "List<" + ",".join(format_value(item) for item in value.fields) + ">"
    if value.sort == "Hist":
        return "Hist<" + ",".join("(" + str(pair.fields[0]) + "," + str(pair.fields[1]) + ")"
                                 for pair in value.fields) + ">"
    if value.sort in ("Witness", "Ambiguity"):
        fields = value.fields[0].fields if value.sort == "Ambiguity" else value.fields
        return value.sort + "<" + ",".join(format_value(item) for item in fields) + ">"
    if value.sort == "Pair":
        return "Pair<" + ",".join(format_value(item) for item in value.fields) + ">"
    raise ValueError(value)


def outcome_text(outcome):
    if isinstance(outcome, values.Ok):
        value = outcome.value
        if isinstance(value, values.Card) and value.sort == "ExprTree":
            return oracle().format_tree(hosts.from_card(value.fields[0]))
        if isinstance(value, values.Card) and value.sort == "Ambiguity":
            fields = value.fields[0].fields
            return "Ambiguity<" + ",".join(
                oracle().format_tree(hosts.from_card(item.fields[0])) if item.sort == "ExprTree" else format_value(item)
                for item in fields) + ">"
        return format_value(value)
    return "Bottom<" + outcome.reason + ">" if isinstance(outcome, values.Bottom) else "Unknown<" + outcome.resource + ">"


def _inputs(lib):
    sample = hosts.word(1, "+", 2, "*", 3)
    counted = hosts.word(1, "+", 1, "+", 1, "+", 1, "+", 1, "+", 1, "+", 1, "+", 1)
    left = lib.run("unrank", (sample, 0)).outcome.value
    right = lib.run("unrank", (sample, 1)).outcome.value
    return (
        ("ExprTree.make", (hosts.to_card(("num", 7)),)),
        ("split", (hosts.word(2, "+", "(", 3, "*", 2, ")"),)),
        ("chart", tuple(kernel.FnRef(item) for item in
                        ("one", "multiply", "identity", "combine_count", "zero")) +
         (hosts.word(1, "+", 2, "*", 3, "+", 1),)),
        ("parse_count", (counted,)),
        ("unrank", (sample, 1)),
        ("ambiguous", (sample,)),
        ("Ambiguity.make", (values.Card("Witness", "triple", (sample, left, right)),)),
        ("fold", tuple(kernel.FnRef(item) for item in ("identity", "arithmetic", "identity")) + (left,)),
        ("value_hist", (sample,)), ("gap", (sample,)), ("invert_gap", (37, 7, 3)),
    )


def _text(name, args):
    if name in ("chart", "fold"):
        count = 5 if name == "chart" else 3
        return "@" + name + "[" + ",".join(arg.name for arg in args[:count]) + "](" + \
            ",".join(notation.print_value(arg) for arg in args[count:]) + ")"
    if name in ("parse_count", "ambiguous", "value_hist"):
        return "?" + name + "{" + notation.print_value(args[0]) + "}"
    return name + "(" + ",".join(notation.print_value(arg) for arg in args) + ")"


_SEALED_SORTS = frozenset(("Draft", "ExprTree", "Witness", "Ambiguity"))


def _public_data(data):
    if isinstance(data, dict):
        if data.get("t") in _SEALED_SORTS:
            return {"sealed": True}
        if "elided_value" in data and data["elided_value"] in _SEALED_SORTS:
            return {"sealed": True}
        return {key: _public_data(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_public_data(value) for value in data]
    return data


def _public_text(lib, name, args):
    if name == "ExprTree.make":
        draft = args[0]
        return f"ExprTree.make(make_draft({notation.print_value(draft.tag)}," + \
            notation.print_value(hosts.list_new(*draft.fields)) + "))"
    if name == "Ambiguity.make":
        word = args[0].fields[0]
        word_text = notation.print_value(word)
        return (f"Ambiguity.make(witness(list3({word_text},"
                f"unrank({word_text},0),unrank({word_text},1))))")
    if name == "fold":
        tree = args[-1]
        word = hosts.yield_probe(tree.fields[0])
        rank = next(rank for rank in (0, 1) if lib.run("unrank", (word, rank)).outcome.value == tree)
        return "@fold[" + ",".join(arg.name for arg in args[:3]) + "](" + \
            f"unrank({notation.print_value(word)},{rank}))"
    return _text(name, args)


def _source(definition, lib):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    records = lib.records()
    context = {"kinds": {name: item.kind for name, item in records.items()},
               "op_arity": {name: len(item.spec.op_params) for name, item in records.items()
                            if item.kind == "combinator"}}
    try:
        source = notation.print_definition(written, context)
    except (ValueError, TypeError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def _public_expression(lib, name, args):
    if name == "ExprTree.make":
        draft = args[0]
        return nodes.Call(name, (nodes.Call("make_draft", (
            nodes.Lit(draft.tag), nodes.Lit(hosts.list_new(*draft.fields)))),))
    if name == "Ambiguity.make":
        word = args[0].fields[0]
        unrank = lambda rank: nodes.Call("unrank", (nodes.Lit(word), nodes.Lit(rank)))
        return nodes.Call(name, (nodes.Call("witness", (nodes.Call("list3", (
            nodes.Lit(word), unrank(0), unrank(1))),)),))
    if name == "fold":
        tree = args[-1]
        word = hosts.yield_probe(tree.fields[0])
        rank = next(rank for rank in (0, 1) if lib.run("unrank", (word, rank)).outcome.value == tree)
        return nodes.Call(name, tuple(nodes.Lit(arg) for arg in args[:3]) +
                          (nodes.Call("unrank", (nodes.Lit(word), nodes.Lit(rank))),))
    return None


def _example(lib, name, args, *, trace=True):
    run = lib.run(name, args, fuel=50_000_000, trace=trace,
                  expression=_public_expression(lib, name, args))
    if isinstance(run.outcome, values.Unknown):
        raise TypeError("example exhausted: " + name)
    result = {"text": _public_text(lib, name, args), "inputs": _public_data([values.encode(arg) for arg in args]),
              "outcome": values.encode_outcome(run.outcome), "steps": run.steps,
              "trace": trace_json(run.trace) if trace else None}
    judge = {"inputs": [values.encode(arg) for arg in args], "judge_view": {"full_state": [format_value(arg) for arg in args]},
             "trace": result["trace"], "outcome": result["outcome"]}
    result["outcome"] = _public_data(result["outcome"])
    result["trace"] = _public_data(result["trace"])
    public = next((arg for arg in args if isinstance(arg, values.Card) and arg.sort == "Word"), None)
    if public is None and name == "ExprTree.make":
        public = hosts.yield_probe(args[0])
    if public is None and name == "Ambiguity.make":
        public = args[0].fields[0]
    if public is None and name == "fold":
        public = hosts.yield_probe(args[-1].fields[0])
    result["learner_view"] = {"public_word": format_value(public) if isinstance(public, values.Card) else "none"}
    return result, run.outcome, judge


def _layer0(declaration, design):
    sections = {}
    for kind, items in (("objects", declaration["objects"]), ("operations", declaration["operations"])):
        result = []
        for item in items:
            match = next((line for line in design["layer0"][kind] if item["name"] in line.split(" ", 3)[1]), None)
            original = match or ("obj " if kind == "objects" else "op ") + item["name"] + " given"
            plain = original.split(" given", 1)[0] + " given"
            symbol = item["name"] + ("<>" if kind == "objects" else "(...)")
            base = {"name": item["name"], "symbol": symbol, "decl": plain,
                    "title": item["name"], "definition": item.get("doc", item.get("rule", "")),
                    "doc_zh": original.split("—", 1)[1].strip() if "—" in original else "通用有限结构操作。"}
            if kind == "objects":
                base["form"] = item["form"]
                base["doc"] = item.get("doc", "")
            else:
                base.update({"rule": item["rule"], "rule_zh": base["doc_zh"],
                             "errors": item["errors"], "cost": item["cost"],
                             "inputs": [{"name": edge["name"], "sort": edge["sort"]}
                                        for edge in item["inputs"]], "output": item["output"]["sort"]})
            result.append(base)
        sections[kind] = result
    sections["combinators"] = {**declaration["combinators"], "decl": [
        text.split(" given", 1)[0] + " given" for text in design["layer0"]["combinators"]],
        "title": "Given Composition", "definition": "Sequential and bounded structural composition.",
        "doc_zh": "顺序组合与严格递减的递归。"}
    sections["observation"] = {**declaration["observation"], "decl": [
        text.split(" given", 1)[0] + " given" for text in design["layer0"]["observations"]],
        "title": "Public Yield", "definition": "A finished derivation reveals only its token word.",
        "doc_zh": "仅公开合法完成树的词串。"}
    return sections


def build_export(*, include_judge=False):
    lib = build_library()
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    samples = _inputs(lib)
    story = []
    judge_examples = []
    for index, (name, card, (call_name, args)) in enumerate(zip(NAMES, design["tower"], samples)):
        definition = lib.get(name)
        example, outcome, judge = _example(lib, call_name, args)
        example["id"] = name
        judge_examples.append({"id": name, **judge})
        assert outcome_text(outcome) == card["value"], (name, outcome_text(outcome), card["value"])
        card_data = {"layer": card["layer"], "def_layer": definition.layer, "kind": definition.kind,
                     "name": name, "body_sha256": export_util.body_sha256(definition.body),
                     **({"decl": source} if (source := _source(definition, lib)) else {}),
                     "design_decl": card["decl"],
                     "plain_zh": card["plain"],
                     "symbol": ("@" if definition.kind == "combinator" else
                                "?" if definition.kind == "observation" else "") + name +
                               ("<>" if definition.kind == "object" else
                                "(...)" if definition.kind == "operation" else
                                "[...]" if definition.kind == "combinator" else "{...}"),
                     "title": TITLES[index], "definition": DEFINITIONS[index],
                     "title_zh": card["plain"].split("，")[0], "definition_zh": card["plain"],
                     "depends_on": list(definition.depends_on),
                     "body": nodes.to_json(definition.body) if definition.body is not None else None,
                     "status": definition.status, "evidence": definition.evidence.to_dict(),
                     "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                     "examples": [example]}
        story.append(card_data)
    failure, _, failure_judge = _example(lib, "unrank", (hosts.word(1), 5))
    failure["id"] = "unrank:failure"
    judge_examples.append({"id": "unrank:failure", **failure_judge})
    story[4]["examples"].append(failure)
    fresh_words = {2: hosts.word(3, "+", 1, "*", 2),
                   5: hosts.word(2, "*", 3, "+", 1),
                   6: hosts.word(3, "+", 2, "*", 1),
                   7: hosts.word(2, "+", 3, "*", 1),
                   8: hosts.word(2, "+", 1, "*", 3),
                   9: hosts.word(3, "+", 1, "*", 2)}
    for index, fresh in fresh_words.items():
        if index == 2:
            op_args = tuple(kernel.FnRef(item) for item in
                            ("one", "multiply", "identity", "combine_count", "zero"))
            name, args = "chart", op_args + (fresh,)
        elif index == 6:
            first = lib.run("unrank", (fresh, 0)).outcome.value
            second = lib.run("unrank", (fresh, 1)).outcome.value
            name, args = "Ambiguity.make", (values.Card("Witness", "triple", (fresh, first, second)),)
        elif index == 7:
            name, args = "fold", tuple(kernel.FnRef(item) for item in
                                        ("identity", "arithmetic", "identity")) + (
                                            lib.run("unrank", (fresh, 0)).outcome.value,)
        else:
            name, args = ("ambiguous" if index == 5 else "value_hist" if index == 8 else "gap"), (fresh,)
        extra, _, extra_judge = _example(lib, name, args)
        extra["id"] = name + ":extra"
        judge_examples.append({"id": name + ":extra", **extra_judge})
        story[index]["examples"].append(extra)
    long_word = hosts.word(2, "+", 2, "*", 2, "+", 2, "*", 2, "+", 2, "*", 2, "+", 2, "*", 2)
    decision_word = hosts.word(1, "+", 2, "*", 3, "+", 1, "*", 2, "+", 3, "*", 1)
    count = lib.run("parse_count", (long_word,), fuel=50_000_000).outcome.value
    hist = lib.run("value_hist", (long_word,), fuel=50_000_000).outcome.value
    keys = [entry.fields[0] for entry in hist.fields]
    first = f"Count<{count}>;Range<{min(keys)},{max(keys)}>;Gap<{max(keys)-min(keys)}>"
    inverse = lib.run("invert_gap", (94, 7, 3), fuel=50_000_000).outcome
    second = outcome_text(inverse)
    decision = lib.run("ambiguous", (decision_word,)).outcome.value
    gap = lib.run("gap", (decision_word,), fuel=50_000_000).outcome.value
    count = lib.run("parse_count", (decision_word,)).outcome.value
    hist = lib.run("value_hist", (decision_word,), fuel=50_000_000).outcome.value
    third = f"{str(decision.tag == 'true' and gap > 20).lower()};Count<{count}>;Gap<{gap}>;{format_value(hist)}"
    showcase = []
    for task, answer in zip(design["showcase"], (first, second, third)):
        assert task["answer"] == answer, (task["angle"], answer)
        showcase.append({"angle": task["angle"], "kinds_involved": task["kinds_involved"],
                         "prompt": task["prompt"], "answer": answer, "answer_checked": True,
                         "check_method": "kernel execution with all public parse alternatives",
                         "why_hard_zh": task["why_hard"], "check_zh": task["check"]})
    ladder = [{"level": item["level"], "knobs_zh": item["knobs"],
               "what_changes_zh": item["what_changes"]} for item in design["ladder"]]
    declaration = lib.world.to_dict()
    support = []
    published = {item['name'] for item in story}
    for name, definition in lib.records().items():
        if name not in published and definition.layer > 0:
            support.append({'name': name, 'kind': definition.kind,
                            'layer': definition.layer,
                            **({'decl': source} if (source := _source(definition, lib)) else {})})
    public = {"schema": "opulse.world_v2_export/1", "tower_source": "depth", "world": "grammar",
            "version": 1, "wave": 2, "title": declaration["title"], "title_zh": design["name"],
            "pitch_zh": design["pitch"], "modality_zh": "语言／结构", "decl": declaration,
            "layer0": _layer0(declaration, design), "story": story, "support": support,
            "ladder": ladder, "showcase": showcase, "modalities_zh": design["modalities"],
            "toy_risk_zh": design["toy_risk"],
            "tags": {"domain": "language", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "combinator", "reasoning": ["parsing", "counting", "search"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "partial",
                     "agents": 1, "scale": "48 tokens and 11 dependent cards",
                     "difficulty": "one digit to 12-digit inverse search",
                     "uses": ["evaluation", "teaching", "rl-training"]},
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "emerges_zh": "层层复用公开词串，精确找出多棵树及不同解释。",
            "checking_zh": "有界核执行和参考图表交叉核对。"}
    if include_judge:
        return public, {"world": "grammar", "version": 1, "examples": judge_examples}
    return public


def main():
    public, judge = build_export(include_judge=True)
    EXPORT_PATH.write_text(json.dumps(public, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                           encoding="utf-8")
    JUDGE_PATH.write_text(json.dumps(judge, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                          encoding="utf-8")



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    result = _build_export_raw(*args, **kwargs)
    if kwargs.get("include_judge"):
        public, judge = result
        return finalize_export(public), judge
    return finalize_export(result)


if __name__ == "__main__":
    main()
