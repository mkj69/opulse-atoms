"""Generate the deep DFA world from real kernel executions."""

import json
import sys
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.atoms.values import Card
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts
from .story import build_library, make_pair
from .world import DECL_PATH, decl

DESIGN = DECL_PATH.parents[2] / "catalogue/depth/automata.json"

def ascii_definition(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written, library)
    except (TypeError, ValueError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def ascii_expression(expression, design_text):
    try:
        text = notation.print_expr(expression)
        if notation.parse_expr(text) == expression:
            return text
    except (TypeError, ValueError):
        pass
    if isinstance(expression, nodes.Call) and expression.fn == "Pair.pair" and design_text.endswith(">"):
        return f"{design_text} [generated Pair.pair]"
    return design_text


def expr(name, *arguments):
    return nodes.Call(name, tuple(arguments))


def literal(value):
    return nodes.Lit(value)


def expressions():
    machines = hosts.depth_examples()
    def machine(name):
        return literal(machines[name])
    def combine(left, right, mode="and"):
        return expr("combine", left, right, literal(mode))
    mod7, mod5, no_bb = machine("mod7_a"), machine("mod5_a"), machine("no_bb")
    product = combine(mod7, no_bb)
    large = combine(combine(mod7, mod5), no_bb)
    target = combine(product, combine(mod5, machine("ends_a"), "or"), "left_not_right")
    step = literal(kernel.FnRef("step"))
    trimmed = expr("Trim.base", expr("Trim.make", product))
    return {
        "Pair": make_pair(mod7, no_bb),
        "sync": expr("sync", step, step, make_pair(mod7, no_bb),
                     literal(hosts.make_row(6, 0)), literal("a")),
        "combine": expr("accept", product, literal("aaaaaaa")),
        "empty_language": expr("empty_language", combine(mod7, machine("never_accept"))),
        "Trim": expr("size", trimmed),
        "refine": expr("distinct_count", expr("refine", step, trimmed)),
        "minimize": expr("size", expr("minimize", product)),
        "equivalent": expr("equivalent", combine(mod7, mod5), machine("mod35_a")),
        "separate": expr("separate", target, machine("never_accept")),
        "included": expr("included", large, machine("mod35_a")),
    }


def example(expression, text, library):
    text = ascii_expression(expression, text)
    sys.setrecursionlimit(max(50000, sys.getrecursionlimit()))
    if isinstance(expression, nodes.Call) and all(isinstance(arg, nodes.Lit) for arg in expression.args):
        run = library.run(expression.fn, tuple(arg.value for arg in expression.args), trace=True)
    else:
        run = kernel.evaluate(expression, scope=library.scope(), trace=True)
    if run.trace is None:
        raise ValueError(f"no kernel call for {text}")
    return {"text": text, "expression": nodes.to_json(expression),
            "inputs": [nodes.to_json(literal(arg))["value"] for arg in run.trace.inputs],
            "outcome": values.encode_outcome(run.outcome), "steps": run.steps,
            "trace": trace_json(run.trace, max_nodes=18)}


def extra_examples():
    machines = hosts.depth_examples()
    def machine(name):
        return literal(machines[name])
    def combine(left, right, mode):
        return expr("combine", left, right, literal(mode))
    step = literal(kernel.FnRef("step"))
    return {
        "Pair": (make_pair(machine("ends_a"), machine("even_len")),
                 "Pair<EndsA<>,EvenLen<>>"),
        "sync": (expr("sync", step, step, make_pair(machine("ends_a"), machine("even_len")),
                      literal(hosts.make_row(0, 0)), literal("a")),
                 "@sync[step,step](Pair<EndsA<>,EvenLen<>>,(0,0),'a')"),
        "combine": (expr("accept", combine(machine("seen_b"), machine("ends_a"), "and"), literal("ba")),
                    "?accept{combine(SeenB<>,EndsA<>,'and'),'ba'}"),
        "empty_language": (expr("empty_language", combine(machine("ends_a"), machine("even_len"), "and")),
                           "?empty{combine(EndsA<>,EvenLen<>,'and')}"),
        "Trim": (expr("size", expr("Trim.base", expr("Trim.make",
                        combine(machine("ends_a"), machine("no_bb"), "and")))),
                 "?size{Trim<combine(EndsA<>,NoBB<>,'and')>}"),
        "refine": (expr("distinct_count", expr("refine", step,
                        expr("Trim.base", expr("Trim.make", combine(machine("even_len"),
                                                                  machine("no_bb"), "and"))))),
                   "distinct_count(@refine[step](Trim<combine(EvenLen<>,NoBB<>,'and')>))"),
        "minimize": (expr("size", expr("minimize", combine(machine("ends_a"),
                                                             machine("even_len"), "and"))),
                     "?size{minimize(combine(EndsA<>,EvenLen<>,'and'))}"),
        "equivalent": (expr("equivalent", combine(machine("even_len"), machine("never_accept"), "and"),
                            machine("never_accept")),
                       "?equivalent{combine(EvenLen<>,NeverAccept<>,'and'),NeverAccept<>}"),
        "separate": (expr("separate", machine("ends_a"), machine("never_accept")),
                     "separate(EndsA<>,NeverAccept<>)"),
        "included": (expr("included", combine(machine("ends_a"), machine("even_len"), "and"),
                          machine("ends_a")),
                     "?included{combine(EndsA<>,EvenLen<>,'and'),EndsA<>}"),
    }


def showcase(library, design):
    machine = hosts.depth_examples()
    def combine(left, right, mode="and"):
        return library.run("combine", (left, right, mode)).outcome.value
    large = combine(combine(machine["mod7_a"], machine["mod5_a"]), machine["no_bb"])
    challenge_machine = combine(
        combine(combine(machine["mod7_a"], machine["mod5_b"]), machine["seen_b"]),
        combine(machine["no_bb"], machine["ends_a"]))
    queries = (("minimize", (large,)),
               ("separate", (challenge_machine, machine["never_accept"])),
               ("equivalent", (library.run("minimize", (
                   combine(machine["mod7_a"], machine["mod5_a"]),)).outcome.value,
                               machine["mod35_a"])))
    results = []
    for task, (name, arguments) in zip(design["showcase"], queries):
        run = library.run(name, arguments)
        answer = str(hosts.count(run.outcome.value)) if name == "minimize" else (
            run.outcome.value.tag if isinstance(run.outcome.value, Card) else str(run.outcome.value))
        if answer != task["answer"]:
            raise ValueError(f"showcase answer mismatch: {answer} != {task['answer']}")
        results.append({**task, "answer_checked": True, "check_method": "kernel graph construction and traversal",
                        "kernel_steps": run.steps})
    return results


def _build_export_raw():
    library = build_library()
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    world = decl()
    expression_by_name, extras = expressions(), extra_examples()
    mapping = {"Pair": "Pair", "sync": "sync", "combine": "combine", "empty_language": "empty_language",
               "Trim": "Trim", "refine": "refine", "minimize": "minimize", "equivalent": "equivalent",
               "separate": "separate", "included": "included"}
    story = []
    for source, name in zip(design["tower"], mapping):
        definition = library.get(name)
        primary = example(expression_by_name[name], source["example"], library)
        additional = example(*extras[name], library)
        failures = []
        if name == "sync":
            machines = hosts.depth_examples()
            pair = make_pair(literal(machines["mod7_a"]), literal(machines["no_bb"]))
            failing = expr("sync", literal(kernel.FnRef("step")), literal(kernel.FnRef("step")),
                           pair, literal(hosts.make_row(0, 0)), literal("c"))
            failures.append(example(failing, "@sync[step,step](Pair<Mod7A<>,NoBB<>>,(0,0),'c')", library))
        symbols = {"Pair": "Pair<A,B>", "sync": "@sync[move_left,move_right](pair,states,symbol)",
                   "combine": "combine(left,right,mode)", "empty_language": "?empty_language{machine}",
                   "Trim": "Trim<machine>", "refine": "@refine[move](machine)",
                   "minimize": "minimize(machine)", "equivalent": "?equivalent{left,right}",
                   "separate": "separate(left,right)", "included": "?included{left,right}"}
        story.append({"layer": source["layer"], "def_layer": definition.layer, "kind": source["kind"],
                      "name": name, "symbol": symbols[name],
                      "body_sha256": export_util.body_sha256(definition.body),
                      **({"decl": source_text} if (source_text := ascii_definition(definition, library)) else {}),
                      "design_decl": source["decl"],
                      "title": name.replace("_", " ").title(),
                      "definition": f"Construct the {name} DFA abstraction through kernel calls.",
                      "title_zh": source["plain"].split("，", 1)[0], "definition_zh": source["plain"],
                      "plain_zh": source["plain"], "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body), "status": definition.status,
                      "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                      "cost": definition.cost.to_dict(),
                      "cost_scope": "verified finite family; displayed examples use example_steps",
                      "examples": [primary, additional, *failures]})
    objects = []
    for item in design["layer0"]["objects"]:
        name = item["decl"].split("<", 1)[0].split(" ", 1)[1]
        objects.append({"name": name, "form": "given", "symbol": f"{name}<>", "decl": item["decl"],
                        "title": name, "definition": "A complete DFA over the binary alphabet.",
                        "doc": "Complete DFA with dense states.", "doc_zh": item["plain"]})
    operations = []
    for item in design["layer0"]["operations"]:
        name = item["decl"].split("(", 1)[0].split(" ", 1)[1]
        operation = next(op for op in world.operations if op.name == name)
        arguments = ",".join(edge.name or f"arg{index}" for index, edge in enumerate(operation.inputs))
        operations.append({"name": name, "symbol": f"{name}({arguments})", "decl": item["decl"], "title": name,
                           "definition": operation.rule, "doc_zh": item["plain"],
                           "rule": operation.rule, "rule_zh": item["plain"], "errors": list(operation.errors),
                           "cost": operation.cost, "inputs": [edge.to_dict() for edge in operation.inputs],
                           "output": operation.output.sort})
    layer0 = {"objects": objects, "operations": operations,
            "combinators": [{**{key: value for key, value in item.items() if key != "plain"},
                             "symbol": "@fold[move](q,w)",
                             "title": "Finite word fold", "definition": "Fold a step over every symbol.",
                             "doc_zh": item["plain"]} for item in design["layer0"]["combinators"]],
            "observation": {"truth": world.observation["truth"],
                              "probes": [{**{key: value for key, value in item.items() if key != "plain"},
                                          "symbol": ("?accept{A,w}" if item["decl"].startswith("obs ?accept")
                                                     else "?size{A}"),
                                          "title": "Public DFA probe",
                                          "definition": "Read a public DFA result.", "doc_zh": item["plain"]}
                                         for item in design["layer0"]["observations"]] +
                              [{"name": probe["name"],
                                "symbol": {"step": "?step{A,q,c}", "final": "?final{A,q}"}.get(
                                    probe["name"], f"?{probe['name']}{{A}}"),
                                "title": f"Public {probe['name']} probe",
                                "definition": "Read an explicitly public DFA structural field.",
                                "doc_zh": design["layer0"]["observations"][0]["plain"],
                                "sort": probe["sort"]}
                               for probe in world.observation["probes"] if probe["name"] not in ("accept", "size")],
                              "show": world.observation["show"], "judge_view": world.observation["judge_view"]}}
    tags = {"domain": "language", "modalities": ["text", "image"],
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "star_kind": "operation", "reasoning": ["compute", "search", "equivalence"],
            "state": "stateful", "outcomes": "deterministic", "visibility": "full",
            "agents": 1, "scale": "up to 20000 product states; 10 tower definitions",
            "difficulty": "2-state products to bounded 20000-state DFA graphs",
            "uses": ["evaluation", "teaching", "experiment"]}
    ladder = [{("what_changes_zh" if key == "what_changes" else key): value
               for key, value in level.items()} for level in design["ladder"]]
    tasks = [{("why_hard_zh" if key == "why_hard" else "check_zh" if key == "check" else key): value
              for key, value in task.items()} for task in showcase(library, design)]
    return {"schema": "opulse.world_v2_export/1", "world": "automata", "version": 1, "wave": 2,
            "title": "Finite binary DFA language laboratory", "title_zh": design["name"],
            "pitch_zh": design["pitch"], "modality_zh": design["modalities"]["text"],
            "decl": json.loads(DECL_PATH.read_text(encoding="utf-8")), "layer0": layer0,
            "story": story, "tower_source": "depth", "ladder": ladder,
            "showcase": tasks, "modalities_zh": design["modalities"],
            "toy_risk_zh": design["toy_risk"], "tags": tags,
            "open_kinds": tags["open_kinds"], "emerges_zh": design["pitch"],
            "checking_zh": design["showcase"][0]["check"]}



def build_export():
    """Build and finalize an independently evaluated export."""
    return finalize_export(_build_export_raw())


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[4] / "docs/assets/data/worlds_v2/automata.json"
    destination.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")
