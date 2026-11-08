"""Generated publication of the bounded tomography tower."""

import json
import re
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, notation, values
from opulse.atoms import nodes as n
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import trace_json

from . import deep_hosts as hosts
from .story import build_library, public_mask, source
from .world import decl

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT / "docs/assets/data/worlds_v2/shadows.json"
JUDGE_OUTPUT = ROOT / "worlds/judge/shadows.json"
DESIGN = ROOT / "worlds/catalogue/depth/shadows.json"


def render(value):
    if isinstance(value, (int, str)):
        return str(value)
    if value.sort == "bool":
        return value.tag
    if value.sort in ("Cell", "Pair"):
        return "(" + ",".join(map(str, value.fields)) + ")"
    if value.sort in ("Volume", "Mask"):
        return value.sort + "<" + ",".join(render(cell) for cell in hosts._cells(value)) + ">"
    if value.sort == "Set":
        return "Set<" + ",".join(map(render, value.fields)) + ">"
    if value.sort == "Views":
        top, side, area = value.fields[0].fields
        return ("Views<Top<" + ",".join(map(render, top.fields)) + ">,Side<" +
                ",".join(map(render, side.fields)) + ">," + str(area) + ">")
    if value.sort == "Candidates":
        return "Candidates<" + str(len(value.fields[0].fields[2].fields)) + ">"
    return value.sort + "<" + ",".join(map(render, value.fields)) + ">"


def expression(name, *args):
    return n.Call(name, tuple(n.Lit(value) if not isinstance(value, n.NODE_TYPES) else value for value in args))


def encoded(value):
    return {"t": "fn", "v": value.name} if isinstance(value, kernel.FnRef) else values.encode(value)


def ascii_declaration(definition, library):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source_text = notation.print_definition(written, library)
    except (ValueError, TypeError):
        return None
    return source_text if export_util.source_matches(source_text, export_util.body_sha256(definition.body)) else None


def ascii_example(expr, secret, public):
    def show(node):
        if isinstance(node, n.Lit):
            if isinstance(node.value, kernel.FnRef):
                return node.value.name
            if node.value == secret:
                return "s"
            if node.value == public:
                return "m" if public == public_mask() else "n"
            return notation.print_value(node.value)
        if isinstance(node, n.Call):
            if node.fn == "Views.make":
                return None
            args = [show(arg) for arg in node.args]
            if any(arg is None for arg in args):
                return None
            return node.fn + "(" + ", ".join(args) + ")"
        raise TypeError(node)

    return show(expr)


def examples():
    secret = source()
    public = public_mask()
    views_raw = hosts.views_record(hosts.top(secret), hosts.side(secret), 8)
    views = values.Card("Views", "val", (views_raw,))
    capture = expression("capture", kernel.FnRef("top"), kernel.FnRef("side"), secret)
    pool = expression("candidates", public, capture)
    return (
        ("ink", expression("ink", secret), (secret,), "?ink{S}"),
        ("Views", expression("Views.make", expression("views_record", expression("top", secret),
                    expression("side", secret), expression("ink", secret))), (secret,),
         "Views.make(views_record(?top{S},?side{S},?ink{S}))"),
        ("capture", capture, (kernel.FnRef("top"), kernel.FnRef("side"), secret), "@capture[top,side](S)"),
        ("matches", expression("matches", secret, capture), (secret, views), "matches(S,@capture[top,side](S))"),
        ("Candidates", pool, (public, views), "candidates(M,@capture[top,side](S))"),
        ("retain", expression("retain", kernel.FnRef("top"), pool, expression("top", secret)),
         (kernel.FnRef("top"), public, views, hosts.top(secret)), "@retain[top](candidates(M,@capture[top,side](S)),?top{S})"),
        ("forced", expression("forced", pool), (public, views), "?forced{candidates(M,@capture[top,side](S))}"),
        ("least", expression("least", pool), (public, views), "least(candidates(M,@capture[top,side](S)))"),
        ("ambiguity", expression("ambiguity", pool), (public, views), "?ambiguity{candidates(M,@capture[top,side](S))}"),
        ("add_view", expression("ambiguity", expression("add_view", kernel.FnRef("diag"), pool,
                                                     expression("diag", secret))),
         (kernel.FnRef("diag"), public, views, hosts.diag(secret)),
         "?ambiguity{@add_view[diag](candidates(M,@capture[top,side](S)),?diag{S})}"),
        ("best_probe", expression("best_probe", pool), (public, views),
         "best_probe(candidates(M,@capture[top,side](S)))"),
        ("plan", expression("plan", kernel.FnRef("front"), kernel.FnRef("diag"),
                            kernel.FnRef("anti"), pool), (public, views),
         "@plan[front,diag,anti](candidates(M,@capture[top,side](S)))"),
    )


def run_expression(library, expr):
    if isinstance(expr, n.Lit):
        return expr.value, 0, ()
    if not isinstance(expr, n.Call):
        raise TypeError(expr)
    args = []
    children = []
    steps = 0
    for arg in expr.args:
        value, cost, traces = run_expression(library, arg)
        args.append(value)
        steps += cost
        children.extend(traces)
    run = library.run(expr.fn, tuple(args), trace=True)
    if children and run.trace is not None:
        run.trace = replace(run.trace, steps=run.steps + steps,
                            children=[*children, *run.trace.children])
    return run.outcome.value if isinstance(run.outcome, values.Ok) else run.outcome, steps + run.steps, (run.trace,)


def public_data(value):
    if isinstance(value, dict):
        if value.get("t") == "Volume":
            return {"sealed": "Volume"}
        return {key: public_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [public_data(item) for item in value]
    return value


def bounded_trace(root):
    pending = [(root, 0)]
    nodes = 0
    deep = False
    while pending:
        current, depth = pending.pop()
        nodes += 1
        deep |= depth > 90
        pending.extend((child, depth + 1) for child in current.children)
    if deep:
        result = trace_json(replace(root, children=[]), max_nodes=8)
        result["elided"] = nodes - 1
        return result
    return trace_json(root, max_nodes=8)


def example(library, expr, inputs, text, secret, granted=(), public=None):
    text = ascii_example(expr, secret, public or public_mask()) or text
    agent = library.agent
    library.agent = ("learner_all" if "front" in granted else
                     "learner_diag" if "diag" in granted else
                     "learner_anti" if "anti" in granted else "learner")
    try:
        value, steps, traces = run_expression(library, expr)
    finally:
        library.agent = agent
    outcome = value if isinstance(value, (values.Bottom, values.Unknown)) else values.Ok(value)
    full_inputs = [encoded(item) for item in inputs]
    judge = {"inputs": full_inputs, "outcome": values.encode_outcome(outcome),
             "judge_view": {"volume": render(secret), "mask": render(public or public_mask())}}
    shown = {"text": text, "inputs": public_data(full_inputs),
             "outcome": public_data(values.encode_outcome(outcome)), "steps": steps,
             "trace": public_data(bounded_trace(traces[0])),
             "learner_view": {name: render(getattr(hosts, name)(secret))
                              for name in ("top", "side", *granted)}}
    return shown, judge


def fresh_example_for(secret, public):
    raw = hosts.views_record(hosts.top(secret), hosts.side(secret), 4)
    visible = values.Card("Views", "val", (raw,))
    captured = expression("capture", kernel.FnRef("top"), kernel.FnRef("side"), secret)
    pool = expression("candidates", public, captured)
    return (
        ("Views", expression("Views.make", expression("views_record", expression("top", secret),
                       expression("side", secret), expression("ink", secret))), (secret,),
         "Views.make(views_record(?top{T},?side{T},?ink{T}))"),
        ("capture", captured, (kernel.FnRef("top"), kernel.FnRef("side"), secret), "@capture[top,side](T)"),
        ("matches", expression("matches", secret, captured), (secret, visible),
         "matches(T,@capture[top,side](T))"),
        ("Candidates", pool, (public, visible), "candidates(N,@capture[top,side](T))"),
        ("retain", expression("retain", kernel.FnRef("side"), pool, expression("side", secret)),
         (kernel.FnRef("side"), public, visible),
         "@retain[side](candidates(N,@capture[top,side](T)),?side{T})"),
        ("forced", expression("forced", pool), (public, visible),
         "?forced{candidates(N,@capture[top,side](T))}"),
        ("least", expression("least", pool), (public, visible),
         "least(candidates(N,@capture[top,side](T)))"),
        ("ambiguity", expression("ambiguity", pool), (public, visible),
         "?ambiguity{candidates(N,@capture[top,side](T))}"),
        ("add_view", expression("ambiguity", expression("add_view", kernel.FnRef("anti"), pool,
                                                     expression("anti", secret))),
         (kernel.FnRef("anti"), public, visible),
         "?ambiguity{@add_view[anti](candidates(N,@capture[top,side](T)),?anti{T})}"),
        ("best_probe", expression("best_probe", pool), (public, visible),
         "best_probe(candidates(N,@capture[top,side](T)))"),
        ("plan", expression("plan", kernel.FnRef("front"), kernel.FnRef("diag"),
                            kernel.FnRef("anti"), pool), (public, visible),
         "@plan[front,diag,anti](candidates(N,@capture[top,side](T)))"),
    )


def fresh_examples():
    public = hosts.mask(*(hosts.cell(x, row, z) for x in (1, 2) for row in (0, 2) for z in (1, 2)))
    local = tuple(hosts.cell(x, 0, z) for x in (1, 2) for z in (1, 2))
    patterns = [tuple(item for index, item in enumerate(local) if bits & (1 << index))
                for bits in range(16) if {item.fields[0] for index, item in enumerate(local)
                                          if bits & (1 << index)} == {1, 2} and
                {item.fields[2] for index, item in enumerate(local) if bits & (1 << index)} == {1, 2}]
    entries = []
    fixtures = []
    for index in range(11):
        first, second = patterns[index // len(patterns)], patterns[index % len(patterns)]
        secret = hosts.volume(*first, *(hosts.cell(item.fields[0], 2, item.fields[2]) for item in second))
        label = f"T{index + 2}"
        name, expr, inputs, text = fresh_example_for(secret, public)[index]
        entries.append((name, expr, inputs, re.sub(r"\bT\b", label, text), secret))
        fixtures.append((label, secret))
    return public, tuple(entries), tuple(fixtures)


def showcase(library, source_data, secret, pool):
    result = []
    agent = library.agent
    for task in source_data["showcase"]:
        library.agent = {"Compute": "learner", "Invert": "learner_anti",
                         "Decide": "learner_all"}[task["angle"]]
        if task["angle"] == "Compute":
            answer = "Tuple<" + str(library.run("ambiguity", (pool,)).outcome.value) + "," + render(
                library.run("least", (pool,)).outcome.value) + ">"
        elif task["angle"] == "Invert":
            filtered = library.run("add_view", (kernel.FnRef("anti"), pool, hosts.anti(secret))).outcome.value
            count = library.run("ambiguity", (filtered,)).outcome.value
            answer = render(hosts.pool_volumes(hosts.pool_raw(filtered)).fields[0]) if count == 1 else "nonunique"
        else:
            choice = library.run("best_probe", (pool,)).outcome.value
            plan = library.run("plan", (kernel.FnRef("front"), kernel.FnRef("diag"),
                                        kernel.FnRef("anti"), pool)).outcome.value
            front = library.run("add_view", (kernel.FnRef("front"), pool, hosts.front(secret))).outcome.value
            after_front = library.run("ambiguity", (front,)).outcome.value
            diagonal = library.run("add_view", (kernel.FnRef("diag"), pool, hosts.diag(secret))).outcome.value
            both = library.run("add_view", (kernel.FnRef("front"), diagonal, hosts.front(secret))).outcome.value
            after_both = library.run("ambiguity", (both,)).outcome.value
            answer = f"Tuple<{render(choice)},{render(plan)},{after_front},{after_both},{str(choice.fields[1] == 1).lower()}>"
        result.append({**{key: value for key, value in task.items() if key not in ("why_hard", "check")},
                       "why_hard_zh": task["why_hard"], "check_zh": task["check"],
                       "answer_checked": answer == task["answer"],
                       "check_method": "kernel calls on invented tower cards and all authorized probe partitions"})
    library.agent = agent
    return result


def seal_showcases(showcases):
    if not all(task["answer_checked"] for task in showcases):
        raise ValueError("showcase answer differs from computed tower result")
    for task in showcases:
        if task["angle"] == "Invert":
            task["answer"] = "sealed"


def build_export(library=None):
    library = library if library is not None else build_library()
    definition = decl().to_dict()
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    secret = source()
    story = []
    judge_examples = []
    symbols = {"ink": "?ink{v}", "Views": "Views<Top,Side,area>",
               "capture": "@capture[top,side]", "matches": "matches(v,w)",
               "Candidates": "Candidates<mask,views>", "retain": "@retain[probe]",
               "forced": "?forced{c}", "least": "least(c)",
               "ambiguity": "?ambiguity{c}", "add_view": "@add_view[probe]",
               "best_probe": "best_probe(c)", "plan": "@plan[front,diag,anti]"}
    for (name, expr, inputs, text), card in zip(examples(), design["tower"]):
        item = library.get(name)
        run, private = example(library, expr, inputs, text, secret,
                      ("front", "diag", "anti") if name in ("best_probe", "plan") else
                      ("diag",) if name == "add_view" else ())
        run["id"] = f"{name}:0"
        story.append({"layer": card["layer"], "def_layer": item.layer, "kind": item.kind, "name": name,
                      "body_sha256": export_util.body_sha256(item.body),
                      "design_decl": card["decl"],
                      **({"decl": source_text} if (source_text := ascii_declaration(item, library)) else {}),
                      "symbol": symbols[name], "title": name.replace("_", " ").title(),
                      "definition": "Compute " + name.replace("_", " ") + " from granted projections and earlier cards.",
                      "plain_zh": card["plain"], "title_zh": card["plain"].split("，")[0],
                      "definition_zh": card["plain"], "depends_on": list(item.depends_on),
                      "body": n.to_json(item.body) if isinstance(item.body, n.NODE_TYPES) else None,
                      "status": item.status, "evidence": item.evidence.to_dict(),
                      "contract": item.contract.to_dict(), "cost": item.cost.to_dict(), "examples": [run]})
        judge_examples.append({"id": f"{name}:0", **private})
    fresh_mask, additions, _ = fresh_examples()
    for card, (name, expr, inputs, text, fresh_secret) in zip(story[1:], additions):
        granted = ("front", "diag", "anti") if name in ("best_probe", "plan") else ("anti",) if name == "add_view" else ()
        shown, private = example(library, expr, inputs, text, fresh_secret, granted, fresh_mask)
        shown["id"] = f"{name}:1"
        card["examples"].append(shown)
        judge_examples.append({"id": f"{name}:1", **private})
    impossible = values.Card("Views", "val", (hosts.views_record(
        values.Card("Set", "items", (hosts.pair(7, 7),)), values.Card("Set", "items"), 1),))
    failure = expression("least", expression("candidates", public_mask(), impossible))
    shown, private = example(library, failure, (public_mask(), impossible),
        "least(candidates(M,Views<Top<(7,7)>,Side<>,1>))", secret)
    shown["id"] = "least:2"
    story[7]["examples"].append(shown)
    judge_examples.append({"id": "least:2", **private})
    views = values.Card("Views", "val", (hosts.views_record(hosts.top(secret), hosts.side(secret), 8),))
    pool = library.run("candidates", (public_mask(), views)).outcome.value
    layer0 = {"objects": [{"name": obj["name"], "form": obj["form"], "symbol": obj["name"],
                            "decl": "obj " + obj["name"] + " given", "title": obj["name"],
                            "definition": obj["doc"], "doc": obj["doc"], "doc_zh": "公开的规范值。"}
                           for obj in definition["objects"]] +
                          [{"name": name, "form": "given", "symbol": name,
                            "decl": "obj " + name + " = " + render(value) + " given", "title": name,
                            "definition": "Public test fixture in the eight by eight by six workspace.",
                            "doc": "Public finite fixture.", "doc_zh": "公开测试夹具。"}
                           for name, value in (("M", public_mask()), ("N", fresh_mask))],
              "operations": [{"name": op["name"], "symbol": op["symbol"],
                               "decl": "op " + op["symbol"] + " given", "title": op["name"],
                               "definition": op["rule"], "doc_zh": "公开的有限规则。",
                               "rule": op["rule"], "rule_zh": "", "errors": op["errors"],
                               "cost": op["cost"], "inputs": op["inputs"],
                               "output": op["output"]["sort"]} for op in definition["operations"]],
              "combinators": {**definition["combinators"], "entries": [{
                  "name": "pipe", "decl": "comb @pipe[f,g](v) given", "title": "Sequential Pipe",
                  "definition": "Apply f and then g without inspecting future results.",
                  "doc_zh": "按顺序调用两个操作。"}]},
              "observation": {**definition["observation"], "probes": [
                  {**probe, "decl": "obs ?" + probe["name"] + "{v:Volume}->Set given",
                   "title": probe["name"].title() + " Projection",
                   "definition": "Reveal only the authorized " + probe["name"] + " shadow.",
                   "doc_zh": "只公开获准的投影。"}
                  for probe in definition["observation"]["probes"]]}}
    showcases = showcase(library, design, secret, pool)
    judge_showcases = [{"id": item["angle"], "answer": item["answer"],
                        "judge_view": {"volume": render(secret), "mask": render(public_mask())}}
                       for item in showcases]
    seal_showcases(showcases)
    JUDGE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JUDGE_OUTPUT.write_text(json.dumps({"world": "shadows", "examples": judge_examples,
                                       "showcase": judge_showcases}, sort_keys=True, indent=1) + "\n",
                            encoding="utf-8")
    return {"schema": "opulse.world_v2_export/1", "tower_source": "depth", "world": "shadows",
            "version": 1, "wave": 1, "title": definition["title"],
            "title_zh": definition["source"]["title_zh"], "pitch_zh": design["pitch"],
            "modality_zh": "文字与图像", "modalities_zh": {
                name + "_zh": value for name, value in design["modalities"].items()},
            "toy_risk_zh": design["toy_risk"], "decl": definition, "layer0": layer0,
            "story": story, "ladder": [{**{key: value for key, value in item.items() if key != "what_changes"},
                                      "what_changes_zh": item["what_changes"]} for item in design["ladder"]],
            "showcase": showcases,
            "tags": {"domain": "perception", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "observation", "reasoning": ["geometry", "inference", "search", "planning"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "partial",
                     "agents": 1, "scale": "8x8x6 grid; 12 tower cards; 200000 candidates",
                     "difficulty": "From one shadow to bounded adaptive tomography",
                     "uses": ["evaluation", "teaching", "experiment"]},
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "emerges_zh": design["pitch"], "checking_zh": "核内展开与独立逐切片参考校验。"}
