"""Export the timestamped kitchen tower and its reproducible witnesses."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import depth_hosts as hosts
from .depth_story import build_library
from .world import example_expression

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/kitchen.json"
JUDGE_PATH = ROOT / "worlds/judge/kitchen.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/kitchen.json"


def encode_value(value):
    if isinstance(value, kernel.FnRef):
        return {"t": "fn", "v": value.name}
    if isinstance(value, tuple):
        return {"t": "List", "tag": "list", "f": [encode_value(item) for item in value]}
    if isinstance(value, values.Card):
        return {"t": value.sort, "tag": value.tag,
                "f": [encode_value(item) for item in value.fields]}
    return values.encode(value)


def encode_outcome(outcome):
    if isinstance(outcome, values.Ok):
        return {"ok": encode_value(outcome.value)}
    return values.encode_outcome(outcome)


def public_value(value):
    if isinstance(value, values.Card) and value.sort == "State":
        return {"t": "State", "stock": list(hosts.stock(value)),
                "busy": list(hosts.busy(value))}
    if isinstance(value, values.Card):
        return {"t": value.sort, "tag": value.tag,
                "f": [public_value(item) for item in value.fields]}
    if isinstance(value, tuple):
        return {"t": "List", "tag": "list",
                "f": [public_value(item) for item in value]}
    return encode_value(value)


def public_outcome(outcome):
    return {"ok": public_value(outcome.value)} if isinstance(outcome, values.Ok) else values.encode_outcome(outcome)


def public_trace(trace):
    def scrub(value):
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get("t") == "tuple" or "tag" in value:
            return {"redacted": "private kitchen data"}
        return {key: scrub(item) for key, item in value.items()}

    return scrub(trace_json(trace))


def literal(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, tuple):
        if any(isinstance(item, values.Card) and item.sort == "Plan" for item in value):
            return "cons(" + literal(value[0]) + ", " + literal(value[1:]) + ")"
        return "List<" + ", ".join(literal(item) for item in value) + ">"
    if isinstance(value, values.Card):
        if value.sort == "State":
            time, lots, jobs = value.fields
            if time == 0 and not jobs and all(item in hosts.ITEMS[:4] for item, _, _ in lots):
                return "state(" + ", ".join(str(number) for number in hosts.stock(value)[:4]) + ")"
            return "State<" + literal(time) + ", " + literal(lots) + ", " + literal(jobs) + ">"
        if value.sort in ("Plan", "Order"):
            record = value.fields[0].fields
            return ("make_plan(" + literal(record[0]) + ", " + literal(record[1]) + ")"
                    if value.sort == "Plan" else
                    "make_order(" + ", ".join(literal(part) for part in record) + ")")
        if value.sort == "Query":
            return "query(" + ", ".join(literal(part) for part in value.fields) + ")"
    return str(value)


def _example_inputs(library):
    stock = hosts.state(2, 1, 0, 0)
    full = hosts.state(4, 1, 2, 2)
    bread_slots = (("mix",), (), ("bake_bread",), (), ())
    dessert_slots = (("simmer", "whisk"), ("bake_cake", "mix"), (),
                     ("bake_bread",), (), ("plate",))
    bread = library.run("make_plan", (stock, bread_slots)).outcome.value
    dessert = library.run("make_plan", (full, dessert_slots)).outcome.value
    bread_order = library.run("make_order", (1, 0, 0, 5)).outcome.value
    dessert_order = library.run("make_order", (1, 0, 1, 6)).outcome.value
    reach_five = library.run("reach", (stock, 5)).outcome.value
    filtered = library.run("filter_plans", (kernel.FnRef("meets"), reach_five,
                                            bread_order)).outcome.value
    return {
        "slot": (("mix",), stock),
        "Plan": (stock, bread_slots),
        "peak": (dessert,),
        "reach": (stock, 1),
        "yield": (dessert,),
        "Order": (1, 0, 1, 6),
        "meets": (dessert, dessert_order),
        "filter_plans": (kernel.FnRef("meets"), reach_five, bread_order),
        "earliest": (hosts.query(hosts.state(2, 1, 0, 0),
                                 library.run("make_order", (1, 0, 0, 4)).outcome.value),),
        "score": (bread, bread_order),
        "best": (kernel.FnRef("score"), filtered, bread_order),
        "min_flour": (hosts.query(hosts.state(4, 1, 2, 2),
                                  library.run("make_order", (0, 0, 0, 0)).outcome.value),),
    }


def arguments(name, library):
    return _example_inputs(library)[name]


NAMES = ("slot", "Plan", "peak", "reach", "yield", "Order", "meets",
         "filter_plans", "earliest", "score", "best", "min_flour")
CALLS = {"Plan": "make_plan", "Order": "make_order"}
SYMBOLS = {"Plan": "Plan<...>", "Order": "Order<...>"}

def ascii_declaration(definition):
    written = replace(definition, status="written", evidence=None, contract=None,
                      id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (ValueError, TypeError, notation.NotationError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def learner_view(*arguments):
    def public(value):
        if isinstance(value, values.Card):
            if value.sort == "State":
                return {"stock": list(hosts.stock(value)), "busy": list(hosts.busy(value))}
            if value.sort == "Plan":
                start, slots, end = value.fields[0].fields
                return {"start": public(start), "slots": [list(slot) for slot in slots],
                        "end": public(end)}
            if value.sort == "Query":
                return {"state": public(value.fields[0]),
                        "order": encode_value(value.fields[1])}
        if isinstance(value, tuple):
            return [public(item) for item in value]
        return encode_value(value)
    return [public(arg) for arg in arguments]


def source_hash():
    parts = (DESIGN_PATH, ROOT / "worlds/decl/v2/kitchen@1.json",
             *(Path(__file__).with_name(name) for name in
               ("depth_hosts.py", "depth_adapter.py", "depth_story.py", "world.py", "export.py")))
    digest = hashlib.sha256()
    for path in parts:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_export():
    digest = source_hash()
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    library = build_library()
    declaration = json.loads((ROOT / "worlds/decl/v2/kitchen@1.json").read_text(encoding="utf-8"))
    example_inputs = _example_inputs(library)
    story = []
    for row, name in zip(design["tower"], NAMES):
        definition = library.get(name)
        inputs = example_inputs[name]
        expression = (nodes.Call(name, tuple(example_expression(item) for item in inputs))
                      if name in ("peak", "yield", "meets", "filter_plans", "score", "best") else None)
        run = library.run(CALLS.get(name, name), inputs, trace=True, expression=expression)
        if name in ("earliest", "min_flour") and isinstance(run.outcome, values.Unknown):
            raise RuntimeError(f"{name}: full example exhausted resources")
        text = ("@" + name + "[" + literal(inputs[0]) + "](" +
                ", ".join(literal(item) for item in inputs[1:]) + ")"
                if name in ("best", "filter_plans") else
                "slot(" + literal(inputs[0]) + ", " + literal(inputs[1]) + ")"
                if name == "slot" else
                name + "(" + literal(inputs[0]) + ")"
                if row["kind"] == "observation" else
                CALLS.get(name, name) + "(" + ", ".join(literal(item) for item in inputs) + ")")
        story.append({"layer": row["layer"], "def_layer": definition.layer,
                      "kind": row["kind"], "name": name,
                      "decl": ascii_declaration(definition),
                      "body_sha256": export_util.body_sha256(definition.body), "design_decl": row["decl"],
                      "plain_zh": row["plain"],
                      "symbol": SYMBOLS.get(name, (
                          "@" + name + "[...]" if row["kind"] == "combinator" else
                          "?" + name + "{...}" if row["kind"] == "observation" else
                          name + "(...)")),
                      "title": name.replace("_", " ").title(),
                      "definition": f"Derives {name} from timestamped stocks and checked schedules.",
                      "title_zh": row["plain"], "definition_zh": row["plain"],
                      "depends_on": list(definition.depends_on),
                      "body": nodes.to_json(definition.body) if definition.body else None,
                      "status": definition.status, "evidence": definition.evidence.to_dict(),
                      "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                      "examples": [{"text": text, "inputs": [encode_value(item) for item in inputs],
                                    "outcome": public_outcome(run.outcome), "steps": run.steps,
                                    "trace": public_trace(run.trace),
                                    "learner_view": learner_view(*inputs),
                                    "judge_view": [encode_value(item) for item in inputs]}]})
    failure = library.run("slot", (("bake_bread",), hosts.state(2, 1, 0, 0)), trace=True)
    story[0]["examples"].append({"text": 'slot(List<"bake_bread">, state(2, 1, 0, 0))',
                                 "inputs": [encode_value(("bake_bread",)),
                                            encode_value(hosts.state(2, 1, 0, 0))],
                                 "outcome": public_outcome(failure.outcome),
                                 "steps": failure.steps, "trace": public_trace(failure.trace),
                                 "learner_view": learner_view(hosts.state(2, 1, 0, 0)),
                                 "judge_view": encode_value(hosts.state(2, 1, 0, 0))})
    return {
        "schema": "opulse.world_v2_export/1", "world": "kitchen", "version": 1,
        "generator_hash": digest,
        "tower_source": "depth", "wave": 3, "title": declaration["title"],
        "title_zh": declaration["source"]["title_zh"], "pitch_zh": design["pitch"],
        "modality_zh": "Resource scheduling", "modalities_zh": design["modalities"],
        "tags": ["planning", "resources", "partial-observation", "search"],
        "open_kinds": sorted(library.world.open_kinds), "decl": declaration,
        "layer0": {"objects": [{"name": item["name"], "form": item["form"],
                                "symbol": item["name"], "title": item["name"],
                                "definition": item["doc"], "doc": item["doc"],
                                "doc_zh": next((line["plain"] for line in design["layer0"]["objects"]
                                                if line["decl"].split()[1].split("<")[0] == item["name"]), "")}
                               for item in declaration["objects"]],
                   "operations": [{"name": item["name"], "symbol": item["name"],
                                   "title": item["name"], "definition": item["rule"],
                                   "rule": item["rule"], "rule_zh": "", "errors": item["errors"],
                                   "cost": item["cost"],
                                   "inputs": [{"name": edge.get("name"), "sort": edge["sort"]}
                                              for edge in item["inputs"]],
                                   "output": item["output"]["sort"]}
                                  for item in declaration["operations"]],
                   "combinators": declaration["combinators"],
                   "observation": {"title": "Public kitchen probes",
                                   "definition": "Show aggregate stock and occupied stations without exposing dated lots.",
                                   "truth": declaration["observation"]["truth"],
                                   "show": declaration["observation"]["show"],
                                   "probes": [{"name": item["name"], "title": item["name"].title(),
                                               "definition": "Reveal " + ", ".join(item["reveals"]) + ".",
                                               "sort": item["sort"],
                                               "reveals": item["reveals"]}
                                              for item in declaration["observation"]["probes"]]}},
        "story": story,
        "ladder": design["ladder"], "showcase": design["showcase"],
        "emerges_zh": design["pitch"],
        "checking_zh": "Exact full-state frontier merging, prefix replay, and bounded finite witnesses."}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    data = _build_export_raw(*args, **kwargs)
    for row in data["story"]:
        if row.get("decl") is None:
            row.pop("decl", None)
    public = finalize_export(data)
    judge = {"world": "kitchen", "version": 1, "examples": {}}
    for row in public["story"]:
        for index, example in enumerate(row["examples"]):
            judge["examples"][f"{row['name']}:{index}"] = {
                "inputs": example.pop("inputs"),
                "judge_view": example.pop("judge_view"),
            }
    JUDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    JUDGE_PATH.write_text(json.dumps(judge, ensure_ascii=False, indent=1,
                                     sort_keys=True) + "\n", encoding="utf-8")
    return public


if __name__ == "__main__":
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), ensure_ascii=False, indent=1,
                                      sort_keys=True) + "\n", encoding="utf-8")
