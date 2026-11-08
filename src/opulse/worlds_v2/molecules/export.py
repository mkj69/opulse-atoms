"""Recompute and export the twelve-layer valence graph world."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts
from .story import TOWER, build_library

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/molecules.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/molecules.json"
TITLES = ("Canonical molecule", "Saturate valences", "Finish a skeleton", "Molecular formula",
          "Cycle rank", "Enumerate isomers", "Hydroxyl count", "Screen molecules",
          "Feature profile", "Compute a profile", "Partition by probe", "Ambiguity witness")
DESCRIPTIONS = (
    "Refine a connected graph by its smallest element-preserving numbered code.",
    "Attach hydrogen at every free valence before constructing a canonical molecule.",
    "Apply a graph transformation and then saturate its result.",
    "Count carbon, hydrogen and oxygen from the granted atoms probe.",
    "Compute edges minus heavy atoms plus one from the granted atoms probe.",
    "Enumerate bounded valence-safe skeletons and canonicalize every distinct isomer.",
    "Count oxygen sites with both attached hydrogen and a carbon neighbor.",
    "Retain molecules whose chosen probe equals the target.",
    "Construct an immutable four-field molecular feature profile.",
    "Combine three observations and a heavy-carbon branching count.",
    "Group canonical molecular codes by a chosen probe.",
    "Return the largest collision, its minimal tied profile, and two distinct codes.")


def display(value):
    if isinstance(value, values.Card):
        if value.sort == "Molecule":
            return hosts.graph_key(value.fields[0])
        if value.sort == "Graph":
            return hosts.graph_key(value)
        if value.sort == "Profile":
            return list(value.fields)
        if value.sort == "Record":
            return {"profile": display(value.fields[0]), "count": value.fields[1],
                    "witness": display(value.fields[2])}
        if value.sort == "List":
            return [display(item) for item in value.fields]
        if value.sort == "Pair":
            return [display(item) for item in value.fields]
    return value


def expression(name, args):
    def write(value):
        if isinstance(value, kernel.FnRef):
            return value.name
        return notation.print_value(value)

    if name in ("finish", "screen", "partition"):
        return f"@{name}[{write(args[0])}](" + ",".join(write(item) for item in args[1:]) + ")"
    return f"{name}(" + ",".join(write(item) for item in args) + ")"


def source_decl(definition, lib):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, lib)
    except (TypeError, ValueError, notation.NotationError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def example(lib, name, args):
    result = lib.run(name, args, trace=True)
    if not isinstance(result.outcome, values.Ok):
        raise TypeError(f"{name}: {result.outcome!r}")
    return {"text": expression(name, args),
            "inputs": [values.encode(arg) for arg in args],
            "outcome": values.encode_outcome(result.outcome), "steps": result.steps,
            "trace": trace_json(result.trace, max_nodes=75)}, result.outcome.value


def _build_export_raw(lib=None) -> dict:
    lib = lib or build_library()
    spec = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    declaration = lib.world.to_dict()
    carbon = hosts.to_card(("C",))
    carbon_one_h = hosts.to_card(("C",), hydrogen=(1,))
    ethanol = hosts.to_card(("C", "C", "O"), ((0, 1), (1, 2)))
    ether = hosts.to_card(("C", "C", "O"), ((0, 2), (1, 2)))
    methanol = hosts.to_card(("C", "O"), ((0, 1),))
    finished_ethanol = lib.run("finish", (kernel.FnRef("identity"), ethanol)).outcome.value
    reversed_ethanol = hosts.to_card(("O", "C", "C"), ((0, 1), (1, 2)))
    finished_reversed = lib.run("finish", (kernel.FnRef("identity"), reversed_ethanol)).outcome.value
    finished_ether = lib.run("finish", (kernel.FnRef("identity"), ether)).outcome.value
    finished_methanol = lib.run("finish", (kernel.FnRef("identity"), methanol)).outcome.value
    carbon_ring = hosts.to_card(("C", "C", "C"), ((0, 1), (0, 2), (1, 2)))
    finished_ring = lib.run("finish", (kernel.FnRef("identity"), carbon_ring)).outcome.value
    isomers = lib.run("candidates", (5, 1, 5)).outcome.value
    groups = lib.run("partition", (kernel.FnRef("profile"), isomers)).outcome.value
    wanted = values.Card("Profile", "profile", ("C5H12O1", 0, 1, 1))
    small_set = hosts.list_make(finished_ethanol, finished_ether, finished_methanol)
    hydroxyl_isomers = lib.run("screen", (kernel.FnRef("oh_count"), 1, isomers)).outcome.value
    design_values = {
        5: lib.run("count", (isomers,)).outcome.value,
        7: lib.run("count", (hydroxyl_isomers,)).outcome.value,
        10: display(lib.run("group_sizes", (groups,)).outcome.value),
    }
    actual_examples = (
        ("Molecule.make", (carbon,)), ("saturate", (carbon_one_h,)),
        ("finish", (kernel.FnRef("identity"), ethanol)), ("formula", (finished_ether,)),
        ("cycle_rank", (lib.run("Molecule.make", (hosts.to_card(("O",)),)).outcome.value,)),
        ("candidates", (3, 1, 3)), ("oh_count", (finished_methanol,)),
        ("screen", (kernel.FnRef("oh_count"), 0, small_set)),
        ("Profile.profile", tuple(wanted.fields)), ("profile", (finished_reversed,)),
        ("partition", (kernel.FnRef("profile"), small_set)), ("ambiguity", (groups,)))
    story = []
    for index, (name, (runner, args), card) in enumerate(zip(TOWER, actual_examples, spec["tower"])):
        definition = lib.get(name)
        shown, outcome = example(lib, runner, args)
        checked_value = design_values.get(index, display(outcome))
        if checked_value != card["value"]:
            raise ValueError(f"depth card {index + 1}: {checked_value!r} != {card['value']!r}")
        symbol = (name + "<...>" if definition.kind == "object" else
                  "@" + name + "[...]" if definition.kind == "combinator" else
                  "?" + name + "{...}" if definition.kind == "observation" else name + "(...)")
        story.append({"layer": index + 1, "def_layer": definition.layer, "kind": definition.kind,
                      "name": name, "decl": source_decl(definition, lib),
                      "body_sha256": export_util.body_sha256(definition.body), "design_decl": card["decl"],
                      "plain_zh": card["plain"],
                      "symbol": symbol, "title": TITLES[index], "definition": DESCRIPTIONS[index],
                      "title_zh": card["plain"].split("，")[0], "definition_zh": card["plain"],
                      "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body), "status": definition.status,
                      "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                      "cost": definition.cost.to_dict(), "examples": [shown],
                      **({"design_value": checked_value} if index in design_values else {})})
    failure, _ = example_failure(lib, hosts.to_card(("C", "C")))
    story[1]["examples"].append(failure)
    shown, _ = example(lib, "profile", (finished_ring,))
    story[9]["examples"].append(shown)

    filtered = lib.run("screen", (kernel.FnRef("formula"), "C5H12O1", isomers)).outcome.value
    compute_groups = lib.run("partition", (kernel.FnRef("profile"), filtered)).outcome.value
    compute = display(lib.run("ambiguity", (compute_groups,)).outcome.value)
    inverse_group = next(item.fields[1].fields for item in groups.fields if item.fields[0] == wanted)
    inverse = {"code": inverse_group[0], "multiplicity": len(inverse_group)}
    ring = lib.run("candidates", (4, 1, 5)).outcome.value
    ring_ethers = lib.run("screen", (kernel.FnRef("oh_count"), 0, ring)).outcome.value
    transfer = {"exists": bool(ring_ethers.fields), "count": len(ring_ethers.fields),
                "witness": display(ring_ethers.fields[0]) if ring_ethers.fields else None}
    answers = (compute, inverse, transfer)
    for task, answer in zip(spec["showcase"], answers):
        if task["answer"] != answer:
            raise ValueError(f"showcase {task['angle']}: {answer!r}")
    showcase = [{**{key + "_zh" if key in ("why_hard", "check") else key: value
                    for key, value in task.items()}, "answer_checked": True, "answer_check_method":
                 "kernel candidates/finish/screen/partition/ambiguity over the stated finite bound"}
                for task in spec["showcase"]]

    def description(item, name):
        declaration_text, chinese = item.split(" given — ", 1)
        return {"name": name, "decl": declaration_text + " given", "title": name.replace("_", " ").title(),
                "definition": declaration_text.split(" — ")[0] + ".", "doc_zh": chinese}

    objects = [description(item, item.split(" = ")[0].split()[-1])
               for item in spec["layer0"]["objects"]]
    for entry in objects:
        source = next(item for item in declaration["objects"] if item["name"] == entry["name"])
        entry.update(form="given", symbol=entry["name"] + "<...>", doc=source["doc"],
                     definition=source["doc"])
    operations = []
    for item in spec["layer0"]["operations"]:
        name = item.split("(")[0].split()[-1]
        entry = description(item, name)
        op = next(op for op in declaration["operations"] if op["name"] == name)
        entry.update(symbol=name + "(...)" if name not in {"atoms", "count", "group_sizes"}
                     else "?" + name + "{...}", rule=op["rule"], rule_zh=entry["doc_zh"],
                     errors=op["errors"], cost=op["cost"],
                     inputs=[{"name": edge.get("name"), "sort": edge["sort"]} for edge in op["inputs"]],
                     output=op["output"]["sort"], definition=op["rule"])
        operations.append(entry)
    probes = [description(item, item.split("{")[0].split()[-1].lstrip("?"))
              for item in spec["layer0"]["observations"]]
    for entry in probes:
        probe = next(probe for probe in declaration["observation"]["probes"] if probe["name"] == entry["name"])
        english = {"atoms": "Reveal numbered labels, attached hydrogen, free valences, and bonds.",
                   "count": "Reveal the exact length of a finite list.",
                   "group_sizes": "Reveal sorted group keys and their sizes."}
        entry.update(symbol="?" + entry["name"] + "{...}", sort=probe["sort"],
                     reveals=probe["reveals"], definition=english[entry["name"]])
    return {"schema": "opulse.world_v2_export/1", "world": "molecules", "version": 1,
            "wave": 2, "title": declaration["title"], "title_zh": "价键工坊",
            "pitch_zh": spec["pitch"], "modality_zh": "结构与拼装",
            "tower_source": "depth", "decl": declaration,
            "layer0": {"objects": objects, "operations": operations,
                       "combinators": {**{key: declaration["combinators"][key]
                                            for key in ("nodes", "library", "recursion")},
                                       "given": {**description(spec["layer0"]["combinators"][0], "chain"),
                                                 "symbol": "@chain[first,second]",
                                                 "definition": "Apply two graph transformations in order, propagating a failure.",
                                                 "unfold_rule": declaration["combinators"]["given_rules"]["chain"]}},
                       "observation": {"truth": "Graph", "probes": probes,
                                       "show": declaration["observation"]["show"],
                                       "judge_view": declaration["observation"]["judge_view"]}},
            "story": story,
            "ladder": [{"level": item["level"], "knobs": item["knobs"],
                        "what_changes_zh": item["what_changes"]} for item in spec["ladder"]],
            "showcase": showcase,
            "modalities_zh": "价键图、符号结构、分子式和轮廓表格",
            "toy_risk_zh": "仅有单键和有限价数；不模拟电子结构、反应或稳定性。",
            "tags": {"domain": "math", "modalities": ["text"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "object", "reasoning": ["compute", "search", "counting", "equivalence"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full",
                     "agents": 1, "scale": "up to 8 heavy and 32 total atoms; 12 invented tower cards",
                     "difficulty": "one heavy atom through six-heavy-atom inverse isomer searches",
                     "uses": ["evaluation", "teaching", "experiment"]},
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "emerges_zh": spec["pitch"], "checking_zh": "有界穷举、逐步计数并用独立参考实现核对。"}


def example_failure(lib, graph):
    result = lib.run("saturate", (graph,), trace=True)
    if not isinstance(result.outcome, values.Bottom):
        raise TypeError("expected a kernel failure")
    return {"text": expression("saturate", (graph,)), "inputs": [values.encode(graph)],
            "outcome": values.encode_outcome(result.outcome), "steps": result.steps,
            "trace": trace_json(result.trace, max_nodes=75)}, result.outcome



def build_export(lib=None):
    """The export after the shared last step (export_util.finalize_export)."""
    data = _build_export_raw(lib)
    for row in data["story"]:
        if row.get("decl") is None:
            row.pop("decl", None)
    return finalize_export(data)


if __name__ == "__main__":
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, indent=1,
                                      ensure_ascii=False) + "\n", encoding="utf-8")
