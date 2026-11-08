"""Export the twelve independently checked text inventions and their kernel traces."""

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from opulse.atoms import kernel, notation, values
from opulse.atoms import nodes as n
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from .story import TOWER, build_library, lex, oracle_value, reference_module, word

DESTINATION = Path(__file__).resolve().parents[4] / "docs/assets/data/worlds_v2/text.json"
DESIGN = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/text.json"


def render(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    if isinstance(value, values.Card):
        if value.sort == "Word":
            return f"Word<{render(value.fields[0])}>"
        if value.sort == "Lex":
            return "Lex<" + ", ".join(render(item) for item in value.fields[0].fields) + ">"
        if value.sort == "Parse":
            source, inner = value.fields[0].fields
            dictionary, words = inner.fields
            return f"Parse<Text<{render(source)}>, {render(dictionary)}, {render(words)}>"
        if value.sort == "Option" and value.tag == "none":
            return "None<>"
        if value.sort == "List":
            return "List<" + ", ".join(render(item) for item in value.fields) + ">"
        if value.sort in ("Span", "Pair"):
            return value.sort + "<" + ", ".join(render(item) for item in value.fields) + ">"
    if isinstance(value, str):
        return "'" + value.replace("'", "\\'") + "'"
    return str(value)


def expression(name, args):
    if name in ("Word", "Lex", "Parse"):
        target = f"{name}.make"
    else:
        target = name
    def argument(item):
        return f"Text<{render(item)}>" if type(item) is str and name != "Word" else render(item)

    if name in ("rewrite", "routes"):
        count = 1 if name == "rewrite" else 2
        return "@" + name + "[" + ", ".join(render(arg) for arg in args[:count]) + "](" + ", ".join(
            argument(arg) for arg in args[count:]) + ")"
    if name in ("starts", "parses", "best", "optimal_count"):
        return "?" + name + "{" + ", ".join(argument(arg) for arg in args) + "}"
    return target + "(" + ", ".join(argument(arg) for arg in args) + ")"


def source_declaration(definition):
    digest = export_util.body_sha256(definition.body)
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (ValueError, TypeError, notation.NotationError):
        return {"body_sha256": digest}
    return {"body_sha256": digest, **({"decl": source} if export_util.source_matches(source, digest) else {})}


def evaluated_expression(name, args):
    if name in ("Word.make", "Lex.make", "Parse.make"):
        return expression(name.split(".")[0], args)
    slots = {"rewrite": 1, "routes": 2}.get(name, 0)
    arguments = ", ".join(notation.print_value(arg) for arg in args[slots:])
    if slots:
        return f"@{name}[{', '.join(arg.name for arg in args[:slots])}]({arguments})"
    if name in ("starts", "parses", "best", "optimal_count"):
        return f"?{name}{{{arguments}}}"
    return f"{name}({arguments})"


def examples():
    from .hosts import pair, sequence

    dictionary = lex(("a", 2), ("aa", 3), ("ab", 4), ("b", 3))
    words = sequence(word("a"), word("b"))
    reference = reference_module()
    spans = oracle_value(reference.edges("aab", reference.lex(("a", 2), ("aa", 3), ("ab", 4), ("b", 3))))
    return (
        ("Word.make", ("ab",)),
        ("split", ("a  b",)),
        ("rewrite", (kernel.FnRef("identity"), words)),
        ("starts", ("a b",)),
        ("Lex.make", (sequence(pair(word("b"), 3), pair(word("ab"), 4), pair(word("a"), 2)),)),
        ("edges", ("aab", dictionary)),
        ("routes", (kernel.FnRef("keep_count"), kernel.FnRef("add"), spans, 3, 0, 1)),
        ("parses", ("aab", dictionary)),
        ("best", ("aab", dictionary)),
        ("optimal_count", ("aab", dictionary)),
        ("Parse.make", (pair("ab", pair(lex(("ab", 4)), sequence(word("ab")))),)),
        ("kth_optimal", ("aab", dictionary, 0)),
    )


def export_example(lib, name, args):
    run = lib.run(name, args, trace=True)
    return {"text": evaluated_expression(name, args),
            "inputs": [({"t": "fn", "v": arg.name} if isinstance(arg, kernel.FnRef)
                        else values.encode(arg)) for arg in args],
            "outcome": values.encode_outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace)}


def checked_showcase(lib, design):
    compute_text = "ab" * 12
    compute_lex = lex(("a", 2), ("aa", 3), ("aaa", 4), ("b", 2), ("ab", 4),
                      ("aba", 6), ("ba", 4), ("bab", 6))
    compute = {"parses": lib.run("parses", (compute_text, compute_lex)).outcome.value,
               "best": lib.run("best", (compute_text, compute_lex)).outcome.value,
               "optimal_count": lib.run("optimal_count", (compute_text, compute_lex)).outcome.value}
    inverse_text = "ab" * 6
    found = []
    for weight in range(1, 10):
        dictionary = lex(("a", 2), ("b", 3), ("ab", weight), ("aba", 4), ("bab", 5))
        if (lib.run("best", (inverse_text, dictionary)).outcome.value,
                lib.run("optimal_count", (inverse_text, dictionary)).outcome.value) == (18, 6):
            found.append(weight)
    inverse = "List<" + ", ".join(map(str, found)) + ">"
    decide_text = "ab" * 8
    before = lex(("a", 2), ("b", 3), ("ab", 4), ("aba", 4), ("bab", 5))
    after = lex(("a", 2), ("b", 3), ("ab", 4), ("aba", 4), ("bab", 5), ("abab", 7))
    old_best = lib.run("best", (decide_text, before)).outcome.value
    old_count = lib.run("optimal_count", (decide_text, before)).outcome.value
    new_best = lib.run("best", (decide_text, after)).outcome.value
    new_count = lib.run("optimal_count", (decide_text, after)).outcome.value
    decide = {"best_before": old_best, "optimal_before": old_count,
              "best_after": new_best, "optimal_after": new_count,
              "changes_optimal_count": old_count != new_count}
    results = (compute, inverse, decide)
    showcase = []
    for card, result in zip(design["showcase"], results):
        if result != card["answer"]:
            raise ValueError(f"showcase mismatch {card['angle']}: {result!r} != {card['answer']!r}")
        clean = {key: value for key, value in card.items() if key not in ("why_hard", "check")}
        showcase.append({**clean, "why_hard_zh": card["why_hard"], "check_zh": card["check"],
                         "answer_checked": True,
                         "check_method": "kernel execution of promoted best, parses, and optimal_count"})
    return showcase


@lru_cache(maxsize=1)
def build_export() -> dict:
    lib = build_library()
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    declaration = json.loads((Path(__file__).resolve().parents[4] /
                              "worlds/decl/v2/text@1.json").read_text(encoding="utf-8"))
    story = []
    for index, (card, (name, args)) in enumerate(zip(design["tower"], examples()), 1):
        definition = lib.get(TOWER[index - 1])
        example = export_example(lib, name, args)
        card_examples = [example]
        if index in (4, 8, 9, 10):
            text, dictionary = (("b a", None) if index == 4 else
                                ("a", lex(("a", 2))) if index == 8 else
                                ("b", lex(("b", 3))) if index == 9 else
                                ("", lex(("a", 2), ("b", 3))))
            card_examples.append(export_example(lib, name, (text,) if dictionary is None else
                                                (text, dictionary)))
        if index == 12:
            example["failure"] = False
            failure = export_example(lib, name, ("", lex(("b", 1)), 1))
            failure["failure"] = True
            card_examples.append(failure)
        expected = card["value"]
        outcome = values.decode_outcome(example["outcome"])
        actual = (("Text<" + render(outcome.value) + ">" if index == 3 else
                   outcome.value if isinstance(expected, int) else render(outcome.value))
                  if isinstance(outcome, values.Ok) else repr(outcome))
        if actual != expected:
            raise ValueError(f"tower layer {index}: {actual!r} != {expected!r}")
        symbol = (f"{definition.name}<...>" if definition.kind == "object" else
                  f"@{definition.name}[{', '.join(definition.spec.op_params)}]" if definition.kind == "combinator" else
                  f"?{definition.name}{{...}}" if definition.kind == "observation" else
                  f"{definition.name}(...)")
        cost = {**definition.cost.to_dict(), "steps_scope": "verification family; see evidence.scope"}
        story.append({"layer": index, "def_layer": definition.layer, "kind": definition.kind,
                      "name": definition.name, "symbol": symbol, **source_declaration(definition),
                      "design_decl": card["decl"],
                      "plain_zh": card["plain"], "title": f"Weighted text layer {index}",
                      "definition": f"Construct {definition.name} from the public weighted lattice.",
                      "title_zh": card["plain"].split("，")[0], "definition_zh": card["plain"],
                      "depends_on": list(definition.depends_on),
                      "body": n.to_json(definition.body) if isinstance(definition.body, n.NODE_TYPES) else None,
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": cost,
                      "examples": card_examples})
    layer0 = {}
    for kind in ("objects", "operations", "combinators", "observations"):
        entries = [{"decl": line.split(" — ")[0], "title": line.split(" = ")[0],
                    "definition": line.split(" = ")[-1].split(" given")[0],
                    "doc_zh": line.split(" — ", 1)[1]} for line in design["layer0"][kind]]
        if kind == "combinators":
            layer0[kind] = {**declaration["combinators"], "entries": entries}
        elif kind == "observations":
            layer0["observation"] = {**declaration["observation"], "entries": entries}
        else:
            layer0[kind] = entries
    ladder = [{"level": item["level"], "knobs_zh": item["knobs"],
               "what_changes_zh": item["what_changes"]} for item in design["ladder"]]
    return {"schema": "opulse.world_v2_export/1", "world": "text", "version": 1, "wave": 3,
            "title": declaration["title"], "title_zh": design["name"], "pitch_zh": design["pitch"],
            "modality_zh": "文字/阅读", "modalities_zh": design["modalities"],
            "toy_risk_zh": design["toy_risk"], "decl": declaration, "tower_source": "depth",
            "open_kinds": list(lib.world.open_kinds), "story": story, "layer0": layer0,
            "ladder": ladder, "showcase": checked_showcase(lib, design),
            "tags": {"domain": "language", "modalities": ["text", "image"],
                     "open_kinds": list(lib.world.open_kinds), "star_kind": "combinator",
                     "reasoning": ["compute", "counting", "parsing", "inference"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full",
                     "agents": "1", "scale": "64 codepoints, 16 dictionary words, 12 tower cards",
                     "difficulty": "from elementary splitting to ranked optimal parses",
                     "uses": ["rl-training", "evaluation", "teaching"]},
            "emerges_zh": "公开码点生成全部重叠词边，再按代数折叠计数和取最优证书。",
            "checking_zh": "在有界输入族上用独立参考实现逐层检查；长文本的任务答案由内核动态规划重算。"}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(json.dumps(build_export(), ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                           encoding="utf-8")
