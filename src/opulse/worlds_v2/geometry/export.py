"""Publish twelve exact, kernel-run geometry cards and their call trees."""

import json
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2.export_util import (
    body_sha256,
    finalize_export,
    parseable_expression,
    recursion_limit_at_least,
    source_matches,
    trace_json,
)

from . import hosts
from .story import (
    build_library,
    region_card,
    region_family,
    ring_card,
    small_region_family,
)
from .templates import INSTANCES

ROOT = Path(__file__).resolve().parents[4]
EXPORT_PATH = ROOT / "docs/assets/data/worlds_v2/geometry.json"
DESIGN_PATH = ROOT / "worlds/catalogue/depth/geometry.json"

NAMES = ("Ring", "twice_area", "translate", "orientation", "Region", "boundary_lattice",
         "interior_lattice", "isometry", "inside", "Signature", "congruent", "overlap_lattice")

def declaration_source(definition):
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (TypeError, ValueError):
        return None
    return source if source_matches(source, body_sha256(definition.body)) else None


def expression_value(value):
    return notation.print_value(value)


def card_symbol(definition):
    suffix = {"object": "<...>", "operation": "(...)"}
    if definition.kind in suffix:
        return definition.name + suffix[definition.kind]
    return {"combinator": "@", "observation": "?"}[definition.kind] + definition.name + (
        "[...]" if definition.kind == "combinator" else "{...}")


def encode(value):
    if isinstance(value, kernel.FnRef):
        return {"t": "fn", "v": value.name}
    if isinstance(value, tuple):
        return values.encode(values.Card("List", "items", tuple(as_value(item) for item in value)))
    return values.encode(as_value(value))


def as_value(value):
    if isinstance(value, tuple):
        return values.Card("List", "items", tuple(as_value(item) for item in value))
    if isinstance(value, values.Card):
        return values.Card(value.sort, value.tag, tuple(as_value(item) for item in value.fields))
    return value


def outcome_json(outcome):
    if isinstance(outcome, values.Ok):
        return values.encode_outcome(values.Ok(as_value(outcome.value)))
    return values.encode_outcome(outcome)


def coordinates(points):
    return tuple(vertex.fields for vertex in points)


def render(value):
    if isinstance(value, values.Card):
        if value.sort == "Point":
            return f"({value.fields[0]},{value.fields[1]})"
        if value.sort == "RegionPair":
            outer, holes = value.fields
            return "RegionPair<shape," + render(outer) + ",List<" + ",".join(render(hole) for hole in holes) + ">>"
        if value.sort == "Ring":
            return "Ring<" + ",".join(render(vertex) for vertex in value.fields[0]) + ">"
        if value.sort == "Region":
            outer, holes = value.fields[0].fields
            return "Region<" + render(outer) + ",List<" + ",".join(render(hole) for hole in holes) + ">>"
        if value.sort == "Signature":
            outer, holes = value.fields[0].fields[0].fields
            shapes = (coordinates(outer.fields[0]), tuple(coordinates(hole.fields[0]) for hole in holes))
            return repr(shapes).replace(" ", "")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def constructor_text(name, argument):
    if name == "Ring.make":
        return "Ring.make(Path<" + ",".join(render(vertex) for vertex in argument) + ">)"
    return name + "(" + render(argument) + ")"


def examples(library):
    from worlds.catalogue.depth import geometry as reference

    small, reference_region, reflected, _, shifted = reference.fixtures()
    small_ring = ring_card(small)
    region = region_card(reference_region)
    reflected_region = region_card(reflected)
    shifted_region = region_card(shifted)
    tiny = region_card(reference.Region(reference.Ring((2, 2), (6, 2), (6, 6), (2, 6))))
    slots = (kernel.FnRef("shift_x"), kernel.FnRef("shift_y"))
    cases = (
        ("Ring.make", (small_ring.fields[0],), constructor_text("Ring.make", small_ring.fields[0])),
        ("twice_area", (small_ring,), "twice_area(" + expression_value(small_ring) + ")"),
        ("translate", (*slots, small_ring), "@translate[shift_x,shift_y](Ring<(0,0),(4,0),(0,4)>)"),
        ("orientation", (small_ring,), "orientation(" + expression_value(small_ring) + ")"),
        ("Region.make", (region.fields[0],), constructor_text("Region.make", region.fields[0])),
        ("boundary_lattice", (region,), "boundary_lattice(" + expression_value(region) + ")"),
        ("interior_lattice", (region,), "interior_lattice(" + expression_value(region) + ")"),
        ("isometry", (kernel.FnRef("flip_q1_shift"), region),
         "@isometry[flip_q1_shift](" + render(region) + ")"),
        ("inside", ((region, hosts.point(8, 6)),),
         "inside(" + expression_value((region, hosts.point(8, 6))) + ")"),
        ("Signature.make", (tiny,), constructor_text("Signature.make", tiny)),
        ("congruent", (region, reflected_region),
         "congruent(" + expression_value(region) + "," + expression_value(reflected_region) + ")"),
        ("overlap_lattice", ((region, shifted_region),),
         "overlap_lattice(" + expression_value((region, shifted_region)) + ")"),
    )
    for name, args, text in cases:
        run = library.run(name, args, trace=True)
        yield name, args, text, run


def fresh_examples(library):
    from worlds.catalogue.depth import geometry as reference

    reversed_ring = ring_card(reference.Ring((2, 2), (2, 6), (6, 2)))
    translated_ring = ring_card(reference.Ring((2, 2), (6, 2), (2, 6)))
    shifted_ring = ring_card(reference.Ring((1, 1), (5, 1), (1, 5)))
    regions = tuple(region_card(item) for item in region_family())
    tiny_regions = tuple(region_card(item) for item in small_region_family())
    return (
        ("twice_area", (shifted_ring,), "twice_area(" + expression_value(shifted_ring) + ")"),
        ("translate", (kernel.FnRef("shift_y"), kernel.FnRef("shift_x"), translated_ring),
         "@translate[shift_y,shift_x](" + render(translated_ring) + ")"),
        ("orientation", (reversed_ring,), "orientation(" + expression_value(reversed_ring) + ")"),
        ("Region.make", (regions[0].fields[0],), constructor_text("Region.make", regions[0].fields[0])),
        ("boundary_lattice", (regions[1],), "boundary_lattice(" + expression_value(regions[1]) + ")"),
        ("interior_lattice", (regions[2],), "interior_lattice(" + expression_value(regions[2]) + ")"),
        ("isometry", (kernel.FnRef("shift_x"), regions[3]),
         "@isometry[shift_x](" + render(regions[3]) + ")"),
        ("inside", ((regions[4], hosts.point(4, 5)),),
         "inside(" + expression_value((regions[4], hosts.point(4, 5))) + ")"),
        ("Signature.make", (tiny_regions[5],), constructor_text("Signature.make", tiny_regions[5])),
        ("congruent", (regions[6], regions[7]),
         "congruent(" + expression_value(regions[6]) + "," + expression_value(regions[7]) + ")"),
        ("overlap_lattice", ((regions[8], regions[9]),),
         "overlap_lattice(" + expression_value((regions[8], regions[9])) + ")"),
    )


def invert_isometries(library, source, target):
    from .story import call, lit, var

    def outer_points(region):
        return region.fields[0].fields[0].fields[0]

    matches = []
    target_min_x = min(point.fields[0] for point in outer_points(target))
    target_min_y = min(point.fields[1] for point in outer_points(target))
    for reflected in (False, True):
        for quarter in range(4):
            initial = tuple(library.run("flip", (point,)).outcome.value if reflected else point
                            for point in outer_points(source))
            rotated = tuple(library.run("turn", (point, quarter)).outcome.value for point in initial)
            dx = target_min_x - min(point.fields[0] for point in rotated)
            dy = target_min_y - min(point.fields[1] for point in rotated)
            if not (-32 <= dx <= 32 and -32 <= dy <= 32):
                continue
            point = var("p")
            body = call("move", call("turn", call("flip", point) if reflected else point, lit(quarter)),
                        lit(dx), lit(dy))
            scope = library.scope().extend((kernel.Defn("candidate", ("p",), body, "operation", 1),))
            candidate = kernel.call("isometry", (kernel.FnRef("candidate"), source), scope).outcome
            if isinstance(candidate, values.Ok) and candidate.value == target:
                matches.append((reflected, quarter, dx, dy))
    return tuple(matches)


def _build_export_unscoped(library=None) -> dict:
    if library is None:
        library = build_library()
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    declaration = json.loads((ROOT / "worlds/decl/v2/geometry@1.json").read_text(encoding="utf-8"))
    story = []
    for card, (name, args, text, run) in zip(design["tower"], examples(library)):
        definition = library.get(NAMES[card["layer"] - 1])
        if isinstance(run.outcome, values.Ok) and render(run.outcome.value) != card["value"]:
            raise ValueError(f"depth value mismatch on {name}: {render(run.outcome.value)} != {card['value']}")
        story.append({
            "layer": card["layer"], "def_layer": definition.layer, "kind": definition.kind,
            "name": definition.name, "symbol": card_symbol(definition),
            "body_sha256": body_sha256(definition.body), "design_decl": card["decl"],
            **({"decl": source} if (source := declaration_source(definition)) else {}),
            "title": f"Card {card['layer']}: {definition.name} (definition layer {definition.layer})",
            "definition": definition.spec.rule if definition.kind == "operation" else
            f"Define {definition.name} using its recorded geometric dependencies.",
            "plain_zh": card["plain"], "title_zh": card["plain"].split("，", 1)[0][:24],
            "definition_zh": card["plain"], "depends_on": list(definition.depends_on),
            "body": nodes.to_json(definition.body) if definition.body else
            {"valid": nodes.to_json(definition.spec.valid) if definition.spec.valid else None,
             "canon": nodes.to_json(definition.spec.canon) if definition.spec.canon else None},
            "status": definition.status, "evidence": definition.evidence.to_dict(),
            "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
            "examples": [{"text": text, "inputs": [encode(item) for item in args],
                          "outcome": outcome_json(run.outcome), "steps": run.steps,
                          "trace": trace_json(run.trace, max_nodes=32)}],
        })
    sample = story[0]["examples"]
    failure = library.run("Ring.make", ((hosts.point(0, 0), hosts.point(2, 2),
                                           hosts.point(0, 2), hosts.point(2, 0)),), trace=True)
    sample.append({"text": constructor_text("Ring.make", (hosts.point(0, 0), hosts.point(2, 2),
                                                         hosts.point(0, 2), hosts.point(2, 0))),
                   "inputs": [encode((hosts.point(0, 0), hosts.point(2, 2),
                                       hosts.point(0, 2), hosts.point(2, 0)))],
                   "outcome": outcome_json(failure.outcome), "steps": failure.steps,
                   "trace": trace_json(failure.trace, max_nodes=32)})
    for card, (name, args, text) in zip(story[1:], fresh_examples(library)):
        run = library.run(name, args, trace=True)
        if not isinstance(run.outcome, values.Ok):
            raise TypeError(f"fresh example failed: {name}: {run.outcome!r}")
        card["examples"].append({"text": text, "inputs": [encode(item) for item in args],
                                 "outcome": outcome_json(run.outcome), "steps": run.steps,
                                 "trace": trace_json(run.trace, max_nodes=24)})
    layer0 = {
        "objects": [{"name": item["name"], "form": item["form"], "symbol": item["name"] + "<...>",
                     "decl": next((entry for entry in design["layer0"]["objects"]
                                   if entry.startswith(f"obj {item['name']}")), f"obj {item['name']} given").split(" — ")[0],
                     "doc": item.get("doc", ""), "title": item["name"], "definition": item.get("doc", ""),
                     "doc_zh": next((entry.split(" — ", 1)[1] for entry in design["layer0"]["objects"]
                                     if entry.startswith(f"obj {item['name']}")),
                                    "有界整数几何基元。")} for item in declaration["objects"]],
        "operations": [{"name": op["name"], "symbol": op["name"] + "(...)", "rule": op["rule"],
                        "title": op["name"], "definition": op["rule"],
                        "decl": next((entry for entry in design["layer0"]["operations"]
                                      if entry.startswith(f"op {op['name']}(")),
                                     f"op {op['name']}(...) given").split(" — ")[0],
                        "rule_zh": next((entry.split(" — ", 1)[1] for entry in design["layer0"]["operations"]
                                         if entry.startswith(f"op {op['name']}(")),
                                        "精确基元或通用结构运算。"),
                        "errors": op["errors"], "cost": op["cost"],
                        "inputs": [{"name": field["name"], "sort": field["sort"]} for field in op["inputs"]],
                        "output": op["output"]["sort"]} for op in declaration["operations"]],
        "combinators": {**declaration["combinators"],
                        "decl": [entry.split(" — ", 1)[0] for entry in design["layer0"]["combinators"]],
                        "entries": [{"name": "then", "symbol": "@then[f,g]",
                                     "decl": design["layer0"]["combinators"][0].split(" — ", 1)[0],
                                     "title": "Sequential point actions",
                                     "definition": "Apply the first point operation, then the second, propagating failure.",
                                     "title_zh": "依次执行两次点操作",
                                     "doc_zh": design["layer0"]["combinators"][0].split(" — ", 1)[1]}]},
        "observation": {"truth": declaration["observation"]["truth"],
                        "probes": [{"name": probe["name"], "symbol": "?" + probe["name"] + "{...}",
                                    "sort": probe["sort"],
                                    "reveals": probe["reveals"], "title": "Public lattice points",
                                    "definition": "Reveal only the coordinates available through points.",
                                    "decl": design["layer0"]["observations"][0].split(" — ")[0],
                                    "doc_zh": design["layer0"]["observations"][0].split(" — ", 1)[1]}
                                   for probe in declaration["observation"]["probes"]],
                        "show": declaration["observation"]["show"],
                        "judge_view": declaration["observation"]["judge_view"]},
    }
    from worlds.catalogue.depth import geometry as reference
    cases = (region_card(reference.Region(reference.Ring((4, 3), (7, 3), (4, 5)))),)
    template_rows = []
    for name in ("Canon", *INSTANCES):
        definition = library.get(name)
        symbol = "Canon[T,group]" if name == "Canon" else name + "<...>"
        design_decl = f"Canonical geometry template {name}."
        row = {"name": name, "kind": definition.kind, "symbol": symbol,
               "body_sha256": body_sha256(definition.body),
               "design_decl": design_decl, "design_text": design_decl,
               **({"decl": source} if (source := declaration_source(definition)) else {}),
               "depends_on": list(definition.depends_on), "def_layer": definition.layer,
               "status": definition.status, "evidence": definition.evidence.to_dict(),
               "contract": definition.contract.to_dict(), "cost": definition.cost.to_dict(),
               "spec": definition.spec.to_dict(), "examples": []}
        if name != "Canon":
            arguments = (cases[0],)
            text = constructor_text(name + ".make", cases[0])
            run = library.run(name + ".make", arguments, trace=True)
            row["examples"].append({"text": text, "ascii": text,
                                    "inputs": [encode(arg) for arg in arguments],
                                    "outcome": outcome_json(run.outcome), "steps": run.steps,
                                    "trace": trace_json(run.trace, max_nodes=24)})
            row["example_steps"] = {"min": run.steps, "max": run.steps}
        for example in row["examples"]:
            if not parseable_expression(example["text"]):
                example.pop("ascii", None)
        template_rows.append(row)
    source = region_card(reference.fixtures()[1])
    def checked(name, arguments):
        result = library.run(name, arguments).outcome
        if not isinstance(result, values.Ok):
            raise TypeError(f"showcase {name} failed: {result!r}")
        return result.value

    reflected = checked("isometry", (kernel.FnRef("flip_q1_shift"), source))
    turned = checked("isometry", (kernel.FnRef("half_shift"), source))
    shifted = checked("isometry", (kernel.FnRef("shift_xy"), source))
    interior = checked("interior_lattice", (source,))
    boundary = checked("boundary_lattice", (source,))
    overlap_shift = checked("overlap_lattice", ((source, shifted),))
    overlap_variants = checked("overlap_lattice", ((reflected, turned),))
    first_answer = f"({interior},{boundary},{overlap_shift},{overlap_variants})"
    decision = (checked("congruent", (source, reflected)),
                checked("congruent", (source, turned)), overlap_variants,
                overlap_shift == overlap_variants)
    decision_answer = "(" + ",".join(render(item) for item in decision) + ")"
    inverse_answer = "(" + ",".join("(" + ",".join(render(part) for part in match) + ")"
                                    for match in invert_isometries(library, source, reflected)) + ",)"
    if (first_answer != design["showcase"][0]["answer"] or
            inverse_answer != design["showcase"][1]["answer"] or
            decision_answer != design["showcase"][2]["answer"]):
        raise ValueError("kernel showcase answer differs from depth reference")
    showcase = []
    for index, task in enumerate(design["showcase"]):
        showcase.append({"angle": task["angle"], "kinds_involved": task["kinds_involved"],
                         "prompt": task["prompt"], "answer": task["answer"],
                         "why_hard_zh": task["why_hard"], "check_zh": task["check"],
                         "answer_checked": True,
                         "check_method": "kernel replay of tower operations and observations" if index != 1 else
                         "kernel checks all eight D4 transforms at the only bounding-box-aligned displacement"})
    return {"schema": "opulse.world_v2_export/1", "world": "geometry", "version": 1,
            "wave": 3, "title": declaration["title"], "title_zh": design["name"],
            "pitch_zh": design["pitch"], "modality_zh": "向量几何", "decl": declaration,
            "layer0": layer0, "tower_source": "depth", "story": story,
            "ladder": [{"level": item["level"], "knobs": f"bounded geometry level {item['level']}",
                        "knobs_zh": item["knobs"], "what_changes": f"Level {item['level']} adds geometry constraints.",
                        "what_changes_zh": item["what_changes"]} for item in design["ladder"]],
            "showcase": showcase, "templates": template_rows,
            "modalities_zh": {f"{name}_zh": text for name, text in design["modalities"].items()
                              if text is not None},
            "toy_risk_zh": design["toy_risk"],
            "tags": {"domain": "math", "modalities": ["text", "image"],
                     "open_kinds": list(library.world.open_kinds), "star_kind": "object",
                     "reasoning": ["geometry", "compute", "counting", "equivalence", "search"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full",
                     "agents": 1, "scale": "33x33 grid; 24 edges, four holes, twelve depth cards",
                     "difficulty": "single ring through multihole isometry and lattice overlap",
                     "uses": ["rl-training", "evaluation"]},
            "open_kinds": list(library.world.open_kinds), "emerges_zh": design["pitch"],
            "checking_zh": "逐个有限几何输入做精确参照核对，并检查内核证明。"}



def _build_export_raw(library=None) -> dict:
    """Build the export with a raised recursion limit that is restored afterwards."""
    with recursion_limit_at_least(10000):
        return _build_export_unscoped(library)


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_PATH.write_text(json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")
