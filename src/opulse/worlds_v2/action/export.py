"""Publish the locked, sealed 12-by-10 maze and the kernel-checked tower."""

import json
import re
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.atoms.values import Card, Ok
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export, trace_json

from . import hosts
from .story import build_library, example_inputs
from .world import decl

ROOT = Path(__file__).resolve().parents[4]
DESIGN = ROOT / "worlds/catalogue/depth/action.json"


def display(value):
    if isinstance(value, Card):
        if value.sort == "Bot":
            world, x, y, direction, steps, turns = value.fields
            return {"maze": world.fields[0], "x": x, "y": y, "dir": hosts.LETTERS[direction],
                    "steps": steps, "turns": turns}
        if value.sort == "Scan":
            return {"x": value.fields[0], "y": value.fields[1], "faces": list(value.fields[2].fields)}
        if value.sort == "Known":
            return [[*entry.fields[0].fields, entry.fields[1]] for entry in value.fields[1].fields]
        if value.sort == "Stats":
            scans, moves, turns, probes, pose = value.fields
            return {"scans": scans, "moves": moves, "turns": turns, "probes": probes,
                    "last_pose": list(pose.fields)}
        if value.sort == "Pair":
            return [display(item) for item in value.fields]
        if value.sort == "List":
            return [display(item) for item in value.fields]
        if value.sort in ("Pos", "Pose"):
            return list(value.fields)
        if value.sort == "bool":
            return value.tag == "true"
    return value


def literal(value):
    if isinstance(value, kernel.FnRef):
        return value.name
    if isinstance(value, Card):
        if value.sort == "Survey":
            return "Survey<sealed:action-explore>"
        if value.sort == "bool":
            return value.tag
        if value.sort == "Maze":
            return "Maze<" + str(value.fields[0]) + ">"
        if value.sort == "Bot":
            maze, x, y, direction, steps, turns = value.fields
            return f"Bot<{maze.fields[0]},{x},{y},{hosts.LETTERS[direction]},{steps},{turns}>"
    return notation.print_value(value)


def expression(name, args):
    arguments = list(map(literal, args))
    if name == "Atlas" and args and isinstance(args[0], Card) and args[0].sort == "Survey":
        survey_bot = args[0].fields[0]
        arguments = [expression("explore", (kernel.FnRef("scan_default"),
            kernel.FnRef("safe_step"), kernel.FnRef("route_known"),
            hosts.start(survey_bot.fields[0])))]
    if name in ("Scan", "Known", "Atlas"):
        name = name + "." + name.lower()
    if name in ("scan", "follow", "explore"):
        slot_count = {"scan": 2, "follow": 1, "explore": 3}[name]
        return "@" + name + "[" + ",".join(arguments[:slot_count]) + "](" + ",".join(arguments[slot_count:]) + ")"
    if name in ("front_clear", "frontier"):
        return name + "(" + ",".join(arguments) + ")"
    return name + "(" + ",".join(arguments) + ")"


def probe_calls(trace):
    pending = [trace]
    count = 0
    while pending:
        current = pending.pop()
        count += current.name in ("front_wall", "front_water") and current.given
        pending.extend(current.children)
    return count


def seal_trace(trace, fixture_id):
    if isinstance(trace, dict):
        if trace.get("t") in ("Survey", "Atlas", "Known"):
            return {"sealed_fixture": fixture_id}
        return {key: seal_trace(value, fixture_id) for key, value in trace.items()}
    if isinstance(trace, list):
        return [seal_trace(value, fixture_id) for value in trace]
    return trace


def design_decl(text):
    declaration, separator, explanation = text.partition(" — ")
    if not separator:
        raise ValueError("missing layer-zero design description")
    return declaration, explanation


def source_decl(definition):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (ValueError, TypeError):
        return None
    return source if export_util.source_matches(source, export_util.body_sha256(definition.body)) else None


def sample_for(lib, name, samples, completed_survey=None):
    if name == "make_atlas":
        return (completed_survey,) if completed_survey is not None else (
            lib.run("explore", samples["explore"], fuel=2_000_000).outcome.value,)
    bot = samples["safe_step"][0]
    origin = samples["make_known"][0]
    scan = lib.run("scan", samples["scan"]).outcome.value.fields[1]
    initial = lib.run("make_known", (origin,)).outcome.value
    merged = lib.run("merge_scan", (initial, scan)).outcome.value
    route = Card("List", "items", (Card("Pos", "pos", (2, 1)), Card("Pos", "pos", (2, 2))))
    explore = samples["explore"]
    return {
        "front_clear": (bot,),
        "safe_step": (bot,),
        "Scan": samples["Scan"], "sense": samples["sense"],
        "scan": samples["scan"], "make_known": (origin,),
        "Known": samples["Known"], "Atlas": (completed_survey,) if completed_survey else samples["Atlas"],
        "merge_scan": (initial, scan), "frontier": (merged,),
        "route_known": (merged, origin, Card("Pos", "pos", (2, 1))),
        "follow": (kernel.FnRef("safe_step"), samples["explore"][-1], route),
        "explore": explore,
    }[name]


def build_export(lib=None):
    world = decl()
    if lib is None:
        lib = build_library()
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    samples = example_inputs()
    names = ("front_clear", "safe_step", "Scan", "sense", "scan", "Known",
             "merge_scan", "frontier", "route_known", "follow", "explore", "Atlas")
    entries = []
    completed_survey = None
    measured_probes = None
    judge_examples = {}
    for card, name in zip(design["tower"], names):
        definition = lib.get(name)
        args = sample_for(lib, name, samples, completed_survey)
        if name == "Atlas":
            nested = nodes.Call("explore", tuple(nodes.Lit(arg) for arg in samples["explore"]))
            run = lib.run("Atlas.atlas", (nested,), fuel=2_000_000, trace=True)
            args = (run.outcome.value.fields[0],) if isinstance(run.outcome, Ok) else args
        else:
            run = lib.run(name + "." + name.lower() if definition.kind == "object" else name,
                          args, fuel=2_000_000, trace=True)
        outcome = run.outcome
        if name == "explore" and isinstance(outcome, Ok):
            completed_survey = outcome.value
        shown = display(outcome.value) if isinstance(outcome, Ok) else {"bottom": outcome.reason}
        if name == "safe_step" and isinstance(outcome, Ok):
            shown = display(hosts.pose(outcome.value))
        if name == "explore" and isinstance(outcome, Ok):
            shown = display(hosts.stats(outcome.value))
            measured_probes = shown["probes"]
            if shown["probes"] != probe_calls(run.trace):
                raise ValueError(f"measured probes {shown['probes']} disagree with kernel call trace {probe_calls(run.trace)}")
        if name == "Atlas" and isinstance(outcome, Ok):
            shown = display(lib.run("frontier", (outcome.value.fields[0].fields[1],)).outcome.value)
        if shown != card["value"] and not (name == "explore" and
                                            {key: value for key, value in shown.items() if key != "probes"}
                                            == {key: value for key, value in card["value"].items() if key != "probes"}):
            raise ValueError(f"depth example mismatch on {name}: {str(shown)[:120]} != {str(card['value'])[:120]}")
        visible_bot = next((arg for arg in args if isinstance(arg, Card) and arg.sort == "Bot"),
                           samples["explore"][-1])
        maze_id = visible_bot.fields[0].fields[0]
        view = {"granted": ["front_wall", "front_water", "pose", "odometer", "stats"],
                "front_wall": display(hosts.front_wall(visible_bot)),
                "front_water": display(hosts.front_water(visible_bot)),
                "pose": display(hosts.pose(visible_bot))}
        example_id = f"action-{card['layer']}"
        expression_args = samples["explore"] if name == "Atlas" else args
        example = {"id": example_id, "text": expression(name, args),
                   "inputs": [values.encode(arg) for arg in expression_args],
                   "outcome": values.encode_outcome(outcome), "steps": run.steps,
                   "trace": trace_json(run.trace, max_nodes=32), "learner_view": view}
        judge_examples[example_id] = {"inputs": example["inputs"],
                                     "judge_view": {"maze": maze_id, "map": list(hosts.MAPS[maze_id]),
                                                    "value": shown}}
        if name == "Atlas":
            judge_examples[example_id]["replay_input"] = {
                "name": "explore", "inputs": [values.encode(arg) for arg in samples["explore"]]}
        if name in ("explore", "Atlas"):
            example["outcome"] = seal_trace(example["outcome"], example_id)
            example["trace"] = seal_trace(example["trace"], example_id)
            if name == "explore":
                example["learner_view"]["stats"] = shown
        entries.append({"layer": card["layer"], "def_layer": definition.layer, "kind": definition.kind,
                        "name": name, "body_sha256": export_util.body_sha256(definition.body),
                        "design_decl": card["decl"], **({"decl": source} if (source := source_decl(definition)) else {}),
                        "plain_zh": card["plain"],
                        "title": name.replace("_", " ").title(),
                        "definition": {
                            "front_clear": "True only when neither front probe reports an obstacle.",
                            "safe_step": "Move forward on a clear reading; otherwise fail as blocked.",
                            "Scan": "Record a position and four measured neighboring tile labels.",
                            "sense": "Classify the front tile as wall, water, or free space.",
                            "scan": "Turn and sense four times, returning the restored pose and a four-face Scan.",
                            "Known": "Hold the discovered tile labels and scanned positions around an origin.",
                            "merge_scan": "Add a measured Scan to Known, rejecting conflicting tile labels.",
                            "frontier": "List known free positions that have not yet been scanned.",
                            "route_known": "Find a shortest route using only discovered free cells.",
                            "follow": "Apply a supplied movement action along a list of adjacent positions.",
                            "explore": "Scan reachable frontiers and follow known routes until none remain.",
                            "Atlas": "Seal a complete survey of the reachable maze into an Atlas.",
                        }[name],
                        "symbol": ({"Scan": "Scan<x,y,faces>", "Known": "Known<start,tiles,scanned>",
                                    "Atlas": "Atlas<survey>"}[name] if definition.kind == "object"
                                   else "@" + name + "[" + ",".join(definition.spec.op_params) + "](" +
                                   ",".join(param for param in definition.spec.params
                                            if param not in definition.spec.op_params) + ")"
                                   if definition.kind == "combinator"
                                   else "?" + name + "{" + ",".join(definition.spec.reads) + "}"
                                   if definition.kind == "observation"
                                   else name + "(" + ",".join(definition.spec.extra["input_names"]) + ")"),
                        "title_zh": card["plain"].split("，")[0], "definition_zh": card["plain"],
                        "depends_on": list(definition.depends_on), "body": nodes.to_json(definition.body),
                        "status": definition.status, "evidence": definition.evidence.to_dict(),
                        "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
                        "examples": [example]})
    failure_bot = hosts.turn_left(hosts.start(hosts.maze("M1")))
    failure = lib.run("safe_step", (failure_bot,), trace=True)
    failure_example = {
        "id": "action-2-blocked",
        "text": expression("safe_step", (failure_bot,)), "inputs": [values.encode(failure_bot)],
        "outcome": values.encode_outcome(failure.outcome), "steps": failure.steps,
        "trace": trace_json(failure.trace),
        "learner_view": {"pose": display(hosts.pose(failure_bot)),
                          "front_wall": display(hosts.front_wall(failure_bot)),
                          "front_water": display(hosts.front_water(failure_bot))}}
    entries[1]["examples"].append(failure_example)
    judge_examples["action-2-blocked"] = {"inputs": failure_example["inputs"],
                                           "judge_view": {"maze": "M1", "map": list(hosts.MAPS["M1"]),
                                                          "outcome": failure_example["outcome"]}}
    showcase = []
    atlas = lib.run("make_atlas", (completed_survey,)).outcome.value
    known = atlas.fields[0].fields[1]
    route = lib.run("route_known", (known, known.fields[0], Card("Pos", "pos", (10, 8))),
                    fuel=2_000_000)
    paths = route.outcome.value.fields if isinstance(route.outcome, Ok) else ()
    def directions(path):
        previous = (1, 1)
        answer = []
        for point in path:
            position = point.fields
            delta = (position[0] - previous[0], position[1] - previous[1])
            answer.append(hosts.LETTERS[hosts.DIRS.index(delta)])
            previous = position
        return "".join(answer)
    stats = hosts.stats(atlas.fields[0])
    terrain = [entry.fields[1] for entry in known.fields[1].fields]
    compute = {"length": len(paths), "directions": directions(paths),
               "scans": stats.fields[0], "moves": stats.fields[1],
               "wall": terrain.count("#"), "water": terrain.count("~")}
    origins = sorted((point.fields for point in known.fields[2].fields), key=lambda item: (item[1], item[0]))
    matches = []
    for position in origins:
        candidate = lib.run("route_known", (known, known.fields[0], Card("Pos", "pos", position)),
                            fuel=2_000_000).outcome
        if isinstance(candidate, Ok) and len(candidate.value.fields) == 14:
            matches.append((position, candidate.value.fields))
    invert = {"first": list(matches[0][0]) if matches else None, "count": len(matches),
              "directions": directions(matches[0][1]) if matches else None}
    trace = []
    position = (1, 1)
    for letter in "EWESSEESEESEEEESSS":
        dx, dy = hosts.DIRS[hosts.LETTERS.index(letter)]
        position = (position[0] + dx, position[1] + dy)
        trace.append(position)
    free = {point.fields[0].fields for point in known.fields[1].fields if point.fields[1] == "."}
    legal = all(point in free for point in trace)
    decide = {"legal": legal, "reaches_goal": position == (10, 8),
              "optimal": legal and position == (10, 8) and len(trace) == len(paths),
              "shortest_length": len(paths)}
    for task, key in zip(design["showcase"], ("compute", "invert", "decide")):
        derived = {"compute": compute, "invert": invert, "decide": decide}[key]
        showcase.append({**task, "fixture_id": "M1", "answer_checked": task["answer"] == derived,
                         "check_method": "Kernel route_known on the sensed Atlas; structural path/counter reduction"})
    designed = {}
    for category in ("objects", "operations", "combinators", "observations"):
        for text in design["layer0"][category]:
            declaration, explanation = design_decl(text)
            match = re.match(r"(?:obj|op|comb|obs)\s+([@?]?[A-Za-z_][\w]*)", declaration)
            if match:
                designed[match.group(1).lstrip("@?")] = declaration, explanation
    objects = [{"name": obj.name, "form": obj.form, "def_layer": 0,
                "symbol": obj.name + "<value>",
                **({"decl": designed[obj.name][0]} if obj.name in designed else {}),
                "title": obj.name, "definition": obj.extra.get("doc") or f"Given {obj.name} value.",
                "doc": obj.extra.get("doc", ""),
                "doc_zh": designed.get(obj.name, ("", "公开结构值。"))[1]}
               for obj in world.objects]
    operations = [{"name": op.name, "def_layer": 0,
                   "symbol": op.name + "(" + ",".join(edge.name for edge in op.inputs) + ")",
                   "title": op.name.replace("_", " ").title(),
                   "definition": ("Return counts from the recorded exploration run, including actual kernel front-probe calls."
                                  if op.name == "stats" else op.rule),
                   **({"decl": designed[op.name][0]} if op.name in designed else {}),
                   "rule": ("Report measured front-probe calls from the authorized exploration run."
                            if op.name == "stats" else op.rule),
                   "rule_zh": ("从探索执行记录中精确统计实际调用的前方墙和水探针次数。" if op.name == "stats"
                               else designed.get(op.name, ("", "通用结构或整数原语。"))[1]),
                   "errors": list(op.errors), "cost": op.cost,
                   "inputs": [{"name": edge.name, "sort": edge.sort} for edge in op.inputs],
                   "output": op.output.sort} for op in world.operations]
    _build_export_raw.judge_data = {"schema": "opulse.world_v2_judge/1", "world": "action",
                               "fixtures": {name: {"id": name, "map": list(hosts.MAPS[name]),
                                                   "start": [1, 1, "E"]} for name in ("M1", "M2", "M3")},
                               "verification_fixtures": {name: {"id": name, "map": list(rows),
                                                                "start": [1, 1, "E"]}
                                                         for name, rows in hosts.MAPS.items()
                                                         if name.startswith("E")},
                               "examples": judge_examples}
    ladder = [dict(level) for level in design["ladder"]]
    ladder[2]["what_changes"] = ("实际探索走 70 步、转 283 次；内核记录了 "
                                  f"{measured_probes} 次布尔探针调用，并核验全局最短路。")
    return {"schema": "opulse.world_v2_export/1", "world": "action", "version": 2, "wave": 1,
            "templates": [{"name": "Count", "def_layer": lib.get("Count").layer,
                           "symbol": "?Count[probe]",
                           "definition": "Count true readings from one granted probe across visited states.",
                           "pattern": lib.get("Count").spec.to_dict(),
                           "instances": [{"name": name, "def_layer": lib.get(name).layer,
                                          "symbol": "?" + name + "{history}",
                                          "spec": lib.get(name).spec.to_dict(),
                                          "depends_on": list(lib.get(name).depends_on)}
                                         for name in ("count_front_wall", "count_front_water")]}],
            "title": "Sealed Maze Robot", "title_zh": design["name"], "pitch_zh": design["pitch"],
            "modality_zh": "身体与行动", "decl": world.to_dict(), "tower_source": "depth",
            "layer0": {"objects": objects, "operations": operations,
                       "combinators": {"nodes": world.combinators["nodes"],
                                       "library": [{**item, "def_layer": 0,
                                                    "symbol": "@" + item["name"] + "[" +
                                                    ",".join(item["op_params"]) + "](" +
                                                    ",".join(param for param in item["params"]
                                                             if param not in item["op_params"]) + ")"}
                                                   for item in world.combinators["library"]],
                                       "recursion": world.combinators["recursion"],
                                       "def_layer": 0,
                                       "symbol": "@seq[first,second](bot)",
                                       "decl": designed["seq"][0], "doc_zh": designed["seq"][1],
                                       "title": "Sequential Actions", "definition": "Composes two robot actions in order."},
                       "observation": {"truth": world.observation["truth"],
                                       "probes": [{**{key: probe[key] for key in ("name", "sort", "reveals")},
                                                   "def_layer": 0,
                                                   "symbol": "?" + probe["name"] + "{bot}",
                                                   "decl": designed[probe["name"]][0],
                                                   "title": probe["name"].replace("_", " ").title(),
                                                   "definition": f"Reports the granted {probe['name'].replace('_', ' ')} reading.",
                                                   "doc_zh": designed[probe["name"]][1]}
                                                  for probe in world.observation["probes"]],
                                       "show": world.observation["show"],
                                       "judge_view": world.observation["judge_view"]}},
            "story": entries, "support": [{"name": "scan_default", "kind": "operation",
                                            "def_layer": lib.get("scan_default").layer}],
            "ladder": ladder, "showcase": showcase,
            "modalities_zh": design["modalities"],
            "toy_risk_zh": design["toy_risk"],
            "tags": {"domain": "agent", "modalities": ["text"], "open_kinds":
                     ["object", "operation", "combinator", "observation"], "star_kind": "combinator",
                     "reasoning": ["planning", "search", "inference"], "state": "stateful",
                     "outcomes": "deterministic", "visibility": "partial", "agents": 1,
                     "scale": "12x10 grid; 12 tower definitions", "difficulty": "single scan to atlas and shortest path",
                     "uses": ["rl-training", "evaluation", "teaching"]},
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "emerges_zh": "四向实测、信念图与动作组合产生完整地图和最短路。",
            "checking_zh": "对拍独立参考实现；只能沿已观测自由格规划。"}



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    destination = ROOT / "docs/assets/data/worlds_v2/action.json"
    destination.write_text(json.dumps(build_export(), sort_keys=True, indent=1,
                                      ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "worlds/judge/action.json").write_text(json.dumps(_build_export_raw.judge_data,
        sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
