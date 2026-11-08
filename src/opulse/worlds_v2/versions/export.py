"""Reproducible depth catalogue export, with outcomes from the kernel."""

import json
from dataclasses import replace
from itertools import product
from pathlib import Path

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.spec import Cost
from opulse.atoms.values import Card, Ok, encode, encode_outcome
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json
from opulse.worlds_v2.versions import hosts
from opulse.worlds_v2.versions.story import (
    build_library,
    entrypoint,
    from_reference,
    invariant_laws,
    law_cases,
    reference,
    samples,
    to_reference,
)
from opulse.worlds_v2.versions.world import FILE, decl

OUTPUT = Path(__file__).resolve().parents[4] / "docs/assets/data/worlds_v2/versions.json"
DESIGN = Path(__file__).resolve().parents[4] / "worlds/catalogue/depth/versions.json"
LAW_LABELS = {
    "merge_idem": (
        "重复合并不变", "同一文档与自身合并仍得到该文档。",
    ),
    "merge_symmetric": (
        "合并对称性", "交换左右文档不改变有限域内的合并结果。",
    ),
}


def source_declaration(definition):
    digest = export_util.body_sha256(definition.body)
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (ValueError, TypeError, notation.NotationError):
        return {"body_sha256": digest}
    return {"body_sha256": digest, **({"decl": source} if export_util.source_matches(source, digest) else {})}


def to_codec(value):
    if isinstance(value, tuple):
        return Card("List", "items", tuple(to_codec(item) for item in value))
    if isinstance(value, Card):
        return Card(value.sort, value.tag, tuple(to_codec(item) for item in value.fields))
    return value


def encode_input(value):
    if isinstance(value, kernel.FnRef):
        return {"t": "fn", "v": value.name}
    return encode(to_codec(value))


def world_outcome(outcome):
    return encode_outcome(Ok(to_codec(outcome.value)) if isinstance(outcome, Ok) else outcome)


def render(value):
    return reference().display(to_reference(value, reference()))


def render_argument(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    return notation.print_value(value)


def expression(name, kind, args):
    if kind == "object":
        return f"{entrypoint(name)}({','.join(render_argument(arg) for arg in args)})"
    if kind == "observation":
        return f"{name}({','.join(render_argument(arg) for arg in args)})"
    if kind == "combinator":
        slots = 2
        return f"@{name}[{','.join(render_argument(arg) for arg in args[:slots])}]({','.join(render_argument(arg) for arg in args[slots:])})"
    if kind == "law":
        return f"{name}({','.join(render_argument(arg) for arg in args)})"
    return f"{name}({','.join(render_argument(arg) for arg in args)})"


def example(library, name, text, args, trace_nodes=60):
    run = library.run(entrypoint(name), args, trace=True)
    return {"text": text, "inputs": [encode_input(arg) for arg in args],
            "outcome": world_outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace, max_nodes=trace_nodes)}


def showcase(library, design):
    ref = reference()
    base = hosts.base12()

    def patches(*triples):
        return from_reference(ref.patches(*(ref.Patch(*triple) for triple in triples)))

    branch = patches(("/a", "0", "R"), ("/d", "0", "D"), ("/h", "0", "H"), ("/j", "0", "J"))
    history = (
        patches(("/a", "0", "R"), ("/b", "0", "B")),
        patches(("/b", "B", "B2"), ("/e", "0", "E")),
        patches(("/f", "0", "F"), ("/g", "0", "G")),
        patches(("/d", "0", "X"), ("/i", "0", "I")),
        patches(("/k", "0", "K")),
    )
    onto = library.run("apply", (base, branch)).outcome.value
    slots = (kernel.FnRef("read"), kernel.FnRef("identity_doc"))
    computed = library.run("rebase", (*slots, base, onto, history)).outcome
    assert isinstance(computed, Ok) and render(computed.value) == design[0]["answer"]

    left = patches(("/a", "0", "X"), ("/c", "0", "C"), ("/e", "0", "E"), ("/g", "0", "G"))
    right = patches(("/a", "0", "Y"), ("/c", "0", "Z"), ("/e", "0", "Q"), ("/h", "0", "H"))
    left_doc = library.run("apply", (base, left)).outcome.value
    right_doc = library.run("apply", (base, right)).outcome.value
    merged = library.run("three_way", (*slots, base, left_doc, right_doc)).outcome.value
    paths = library.run("conflict_paths", (merged,)).outcome.value
    target = from_reference(ref.edit(ref.edit(ref.edit(ref.edit(ref.BASE, "/a", "Y"), "/e", "E"), "/g", "G"), "/h", "H"))
    winners = [from_reference(ref.Choices(tuple(zip(paths, sides))))
               for sides in product(("base", "left", "right"), repeat=len(paths))
               if library.run("resolve", (merged, from_reference(ref.Choices(tuple(zip(paths, sides)))))).outcome == Ok(target)]
    assert len(winners) == 1 and render(winners[0]) == design[1]["answer"]

    onto_patch = patches(("/b", "0", "X"), ("/h", "0", "H"))
    first = patches(("/b", "0", "X"), ("/c", "0", "C"))
    second = patches(("/b", "X", "Y"), ("/d", "0", "D"))
    onto_doc = library.run("apply", (base, onto_patch)).outcome.value
    replay = library.run("rebase", (*slots, base, onto_doc, (first, second))).outcome.value
    original = library.run("apply", (library.run("apply", (base, first)).outcome.value, second)).outcome.value
    one_shot = library.run("three_way", (*slots, base, onto_doc, original)).outcome.value
    left_delta = library.run("delta", (base, onto_doc)).outcome.value
    right_delta = library.run("delta", (base, original)).outcome.value
    commutes = library.run("commute", (base, left_delta, right_delta)).outcome.value
    decision = replay.fields[2] == 0 and bool(one_shot.fields[1]) and not commutes
    assert str(decision).lower() == design[2]["answer"]
    answers = (computed.value, winners[0], decision)
    methods = ("kernel rebase of five commits", "kernel enumeration of 27 resolve choices",
               "kernel rebase, three_way, delta and commute")
    return [{**{name + "_zh" if name in ("why_hard", "check") else name: value
                for name, value in entry.items()},
             "answer_checked": True, "answer_check_method": method,
             "answer_outcome": encode_input(answer)}
            for entry, answer, method in zip(design, answers, methods)]


def build_export():
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    declaration = decl()
    library = build_library()
    story = []
    for design_card, (name, args) in zip(design["tower"], ((name, values[0]) for name, values in samples().items())):
        definition = library.get(name)
        witness = example(library, name, expression(name, definition.kind, args), args)
        assert isinstance(result := library.run(entrypoint(name), args).outcome, Ok)
        assert render(result.value) == design_card["value"], name
        from opulse.worlds_v2.versions.story import verification_cases
        fresh = next(item for item in verification_cases(name, samples()[name]) if item != args)
        extra = example(library, name, expression(name, definition.kind, fresh), fresh, trace_nodes=12)
        story.append({"layer": design_card["layer"], "def_layer": definition.layer,
                      "kind": definition.kind, "name": name,
                      **source_declaration(definition),
                      "design_decl": design_card["decl"],
                      "title": name.replace("_", " ").title(),
                      "definition": design_card["decl"].split(" = ", 1)[-1].split(" L", 1)[0].rstrip(".") + ".",
                      "plain_zh": design_card["plain"], "symbol": (
                          name.capitalize() + "<" + name + ">" if definition.kind == "object" else
                          "@" + name + "[read,identity_doc]" if definition.kind == "combinator" else
                          "?" + name + "{}" if definition.kind == "observation" else name + "(...)"),
                      "title_zh": design_card["plain"].split("，")[0],
                      "definition_zh": design_card["plain"],
                      "depends_on": list(definition.depends_on), "body": nodes.to_json(definition.body),
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [witness, extra]})
    bad = from_reference(reference().patches(reference().Patch("/a", "wrong", "x")))
    story[3]["examples"].append(example(library, "apply", expression("apply", "operation", (hosts.base12(), bad)),
                                         (hosts.base12(), bad)))
    assert story[3]["examples"][-1]["outcome"] == {"bottom": "guard"}
    laws = []
    for law in invariant_laws():
        definition = library.get(law.name)
        arguments = law_cases(law.name)[0]
        title_zh, definition_zh = LAW_LABELS[law.name]
        laws.append({"layer": len(story) + len(laws) + 1,
                     "kind": "law", "name": law.name, "symbol": "#" + law.name,
                     **source_declaration(definition),
                     "design_decl": "The invariant holds on its bounded witness family.",
                     "title": law.name.replace("_", " ").title(),
                     "definition": "The invariant holds on its bounded witness family.",
                     "title_zh": title_zh, "definition_zh": definition_zh,
                     "def_layer": definition.layer, "depends_on": list(definition.depends_on),
                     "body": nodes.to_json(definition.body), "status": definition.status,
                     "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                     "cost": definition.cost.to_dict(),
                     "examples": [example(library, law.name,
                                          expression(law.name, "law", arguments), arguments)]})
    data = json.loads(FILE.read_text(encoding="utf-8"))
    return {"schema": "opulse.world_v2_export/1", "world": "versions", "version": 1,
            "wave": 1, "tower_source": "depth", "title": declaration.extra["title"],
            "title_zh": design["name"], "pitch_zh": design["pitch"],
            "modality_zh": "协作文本状态",
            "modalities_zh": {name + "_zh": value for name, value in design["modalities"].items()},
            "toy_risk_zh": design["toy_risk"], "open_kinds": ["object", "operation", "combinator", "observation"],
            "tags": {"domain": "social", "modalities": ["text"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "combinator", "reasoning": ["compute", "strategy", "equivalence"],
                     "state": "stateful", "outcomes": "deterministic", "visibility": "full",
                     "agents": "2+", "scale": "12 paths; 12 invented cards; 5-24 commits",
                     "difficulty": "from one guarded patch to multi-branch replay",
                     "uses": ["rl-training", "evaluation", "teaching", "interpretability"]},
            "decl": data,
            "layer0": {"objects": [{"name": obj.name, "form": obj.form, "symbol": obj.name + "<>",
                                    "title": obj.name + " Object",
                                    "definition": obj.extra.get("doc", f"A given {obj.name} value.").rstrip(".") + ".",
                                    "decl": obj.extra.get("doc", f"obj {obj.name}<> given"),
                                    "doc": obj.extra.get("doc", ""),
                                    "doc_zh": next((line.split(" — ", 1)[1] for line in design["layer0"]["objects"]
                                                    if line.startswith(f"obj {obj.name}<") and " — " in line), "")}
                                   for obj in declaration.objects],
                       "operations": [{"name": op.name, "symbol": op.name + "(...)",
                                       "title": op.name.replace("_", " ").title() + " Operation",
                                       "definition": op.rule.rstrip(".") + ".",
                                       "decl": next((line.split(" — ", 1)[0] for line in design["layer0"]["operations"]
                                                     if line.startswith(f"op {op.name}(")),
                                                    f"op {op.name}(...) given"),
                                       "rule": op.rule,
                                       "doc_zh": next((line.split(" — ", 1)[1] for line in design["layer0"]["operations"]
                                                       if line.startswith(f"op {op.name}(") and " — " in line), ""),
                                       "errors": list(op.errors),
                                       "cost": op.cost, "inputs": [{"name": edge.name, "sort": edge.sort}
                                                                  for edge in op.inputs], "output": op.output.sort}
                                      for op in declaration.operations],
                       "combinators": {**declaration.combinators,
                                       "title": "Fix Combinator",
                                       "definition": "Bind a named binary operation to a document and explicit arguments.",
                                       "decl": design["layer0"]["combinators"][0].split(" — ", 1)[0],
                                       "doc_zh": design["layer0"]["combinators"][0].split(" — ", 1)[1]},
                       "observation": {"title": "Public Version Observations",
                                       "definition": "Read public document contents and version ancestry through granted probes.",
                                       "truth": declaration.observation["truth"],
                                       "probes": [{"name": item["name"], "sort": item["sort"],
                                                   "title": item["name"].replace("_", " ").title() + " Observation",
                                                   "symbol": "?" + item["name"] + "{}",
                                                   "definition": f"Read the granted public {item['name']} view.",
                                                   "reveals": item["reveals"], "decl":
                                                   next((line.split(" — ", 1)[0] for line in design["layer0"]["observations"]
                                                         if line.startswith(f"obs ?{item['name']}{{")), ""),
                                                   "doc_zh": next((line.split(" — ", 1)[1]
                                                                   for line in design["layer0"]["observations"]
                                                                   if line.startswith(f"obs ?{item['name']}{{")
                                                                   and " — " in line), "")}
                                                  for item in declaration.observation["probes"]],
                                       "show": declaration.observation["show"],
                                       "judge_view": declaration.observation["judge_view"]}},
            "story": story + laws,
            "ladder": [{**{"what_changes_zh" if name == "what_changes" else name: value
                           for name, value in level.items()}} for level in design["ladder"]],
            "showcase": showcase(library, design["showcase"]),
            "emerges_zh": "有条件补丁、逐路径合并和显式变基停点。",
            "checking_zh": "逐步计费的公开核执行和独立参考实现对照。"}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return json.loads(json.dumps(finalize_export(_build_export_raw(*args, **kwargs)), ensure_ascii=False))


if __name__ == "__main__":
    OUTPUT.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
