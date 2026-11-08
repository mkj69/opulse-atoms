"""Generate the public twelve-layer pixel tower from the kernel."""

import json
import os
from dataclasses import replace
from pathlib import Path

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.spec import Cost
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.export_util import finalize_export
from opulse.worlds_v2.export_util import trace_json as shared_trace_json
from opulse.worlds_v2.pixels import hosts, story
from opulse.worlds_v2.pixels.world import decl

ROOT = Path(__file__).resolve().parents[4]
TITLES = ("四邻域岛数", "连通岛", "种子洪泛", "小岛扩张", "逐岛映射", "围闭暗洞",
          "规范形状", "八向变换", "八向签名", "欧拉数", "逐块等价", "逐格逆向搜索")
NAMES = ("islands", "Island", "flood", "grow", "map_components", "holes",
         "Shape", "dihedral", "signature", "euler", "equivalent", "scan_add")
PATH = ((0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (2, 1),
        (1, 1), (0, 1), (0, 2), (1, 2), (2, 2), (3, 2), (3, 3))


def trace_json(node):
    return shared_trace_json(node, max_nodes=32)


def _input(value):
    return {"t": "fn", "v": value.name} if isinstance(value, kernel.FnRef) else values.encode(value)


def _expression(name, args):
    return nodes.Call(name + ".make" if name in ("Island", "Shape") else name,
                      tuple(nodes.Lit(value) for value in args))


def _design_expression(index, asymmetric):
    a0, a1, b0 = (nodes.Call(name) for name in ("A0", "A1", "B0"))
    island = nodes.Call("Island.make", (a1,))
    shape = nodes.Call("Shape.make", (nodes.Call("Island.make", (nodes.Lit(asymmetric),)),))
    fn = lambda name: nodes.Lit(kernel.FnRef(name))
    return (
        nodes.Call("islands", (a0,)), island,
        nodes.Call("flood", (a0, nodes.Lit(hosts.point(8, 3)))),
        nodes.Call("grow", (island,)),
        nodes.Call("islands", (nodes.Call("map_components", (fn("grow"), a0)),)),
        nodes.Call("holes", (a0,)), nodes.Call("Shape.make", (island,)),
        nodes.Call("dihedral", (fn("identity"), shape)),
        nodes.Call("signature", (shape,)), nodes.Call("euler", (a0,)),
        nodes.Call("equivalent", (a0, b0)),
        nodes.Call("scan_add", (fn("euler"), a0, nodes.Lit(3))),
    )[index]


def _example(library, name, text, args, expression=None):
    expression = expression or _expression(name, args)
    try:
        source = notation.print_expr(expression)
        if notation.parse_expr(source) == expression:
            text = source
    except (TypeError, ValueError, notation.NotationError):
        pass
    result = kernel.evaluate(expression, scope=library.scope(), limits=kernel.Limits(fuel=4_000_000), trace=True)
    return {"text": text, "inputs": [_input(value) for value in args], "expression": nodes.to_json(expression),
            "outcome": values.encode_outcome(result.outcome), "steps": result.steps,
            "trace": trace_json(result.trace), "demonstrates": "Full kernel unfolding of the stated pixel construction."}


def _given(fragment):
    before, _, description = fragment.partition(" given")
    return before + " given", description.partition("—")[2].strip()


def _fresh(library, index, name):
    reference = story.oracle()
    image = hosts.to_card(reference.grid(4, 4, PATH[:index + 1]).rows)
    island = library.run("Island.make", (image,)).outcome.value
    if name in ("islands", "Island", "euler"):
        return (image,), "2x2-to-4x4 fresh connected input"
    if name == "flood":
        return (image, hosts.point(0, 0)), "fresh seed; flood constructs a validated Island"
    if name in ("grow", "Shape"):
        return (island,), "fresh Island constructed by the lower object layer"
    if name == "map_components":
        return (kernel.FnRef("grow"), image), "fresh grid: applies the lower flood and grow layers"
    if name == "holes":
        mapped = library.run("map_components", (kernel.FnRef("grow"), image)).outcome.value
        return (mapped,), "fresh grid computed by the lower @map_components[grow] layer"
    if name in ("dihedral", "signature"):
        shape = library.run("Shape.make", (island,)).outcome.value
        return ((kernel.FnRef("identity"), shape) if name == "dihedral" else (shape,)), \
            "fresh Shape constructed from the lower Island and cropping layers"
    if name == "equivalent":
        rotated = reference.grid(4, 4, {(3 - x_coord, y_coord) for x_coord, y_coord in PATH[:index + 1]})
        return (image, hosts.to_card(rotated.rows)), "fresh pair decided through the lower signature layer"
    return (kernel.FnRef("euler"), image, 1), "fresh inverse search delegated to the lower euler layer"


def _fresh_text(name, args, index):
    parts = [("Island<" + story.depth_encode(value.fields[0]) + ">")
             if isinstance(value, values.Card) and value.sort == "Island" else
             story.depth_encode(value) if not isinstance(value, kernel.FnRef) else value.name for value in args]
    if name == "islands":
        return f"?islands{{{parts[0]}}}"
    if name in ("Island", "Shape"):
        return f"{name}<{parts[0]}>"
    if name in ("holes", "signature"):
        return f"?{name}{{{parts[0]}}}"
    if name in ("map_components", "dihedral"):
        return f"@{name}[{parts[0]}]({', '.join(parts[1:])})"
    if name == "scan_add":
        return f"@scan_add[{parts[0]}]({parts[1]}, {parts[2]})"
    return f"{name}({', '.join(parts)})"


def _declaration(definition):
    digest = export_util.body_sha256(definition.body)
    written = replace(definition, status="written", evidence=None, contract=None, id=None, cost=Cost())
    try:
        source = notation.print_definition(written)
    except (TypeError, ValueError, notation.NotationError):
        return {"body_sha256": digest}
    return {"body_sha256": digest, **({"decl": source} if export_util.source_matches(source, digest) else {})}


def build_export(library=None):
    library = library or story.build_library()
    reference = story.oracle()
    design = json.loads((ROOT / "worlds/catalogue/depth/pixels.json").read_text(encoding="utf-8"))
    declaration = decl().to_dict()
    first, second, mirror = (hosts.to_card(getattr(reference, name).rows) for name in ("A0", "A1", "B0"))
    island_second = library.run("Island.make", (second,)).outcome.value
    asymmetric = hosts.to_card(("###", "#.."))
    asymmetric_island = library.run("Island.make", (asymmetric,)).outcome.value
    asymmetric_shape = library.run("Shape.make", (asymmetric_island,)).outcome.value
    args = ((first,), (second,), (first, hosts.point(8, 3)), (island_second,),
            (kernel.FnRef("grow"), first), (first,), (island_second,),
            (kernel.FnRef("identity"), asymmetric_shape), (asymmetric_shape,),
            (first,), (first, mirror), (kernel.FnRef("euler"), first, 3))
    entries = []
    for index, (card, name, inputs) in enumerate(zip(design["tower"], NAMES, args)):
        definition = library.get(name)
        expression = _design_expression(index, asymmetric)
        main = _example(library, name, card["example"], inputs, expression)
        actual = values.decode_outcome(main["outcome"])
        if not isinstance(actual, values.Ok) or story.depth_encode(actual.value) != card["value"]:
            raise ValueError(f"depth oracle mismatch: {name}: {actual!r} != {card['value']}")
        extra = []
        if name == "flood":
            extra.append(_example(library, name, "flood(A0, Pt<0, 0>)", (first, hosts.point(0, 0)),
                                  nodes.Call("flood", (nodes.Call("A0"), nodes.Lit(hosts.point(0, 0))))))
        fresh_inputs, derivation = _fresh(library, index, name)
        fresh = _example(library, name, _fresh_text(name, fresh_inputs, index), fresh_inputs)
        fresh["derivation"] = derivation
        extra.append(fresh)
        symbols = {"object": f"{name}<...>", "operation": f"{name}(...)",
                   "combinator": f"@{name}[f](...)", "observation": f"?{name}{{...}}"}
        entries.append({"layer": definition.layer, "design_layer": card["layer"],
                        "def_layer": definition.layer, "kind": card["kind"],
                        "name": name, "symbol": symbols[card["kind"]],
                        **_declaration(definition), "design_decl": card["decl"],
                        "plain_zh": card["plain"], "title_zh": TITLES[index],
                        "definition_zh": card["plain"], "depends_on": list(definition.depends_on),
                        "title": ("Count connected islands", "Construct a connected island", "Flood from a lit seed",
                                  "Grow a connected island", "Map over connected components", "Count enclosed holes",
                                  "Crop a canonical shape", "Enumerate dihedral images", "Compute a shape signature",
                                  "Compute Euler characteristic", "Compare component signatures",
                                  "Search for single-cell additions")[index],
                        "definition": ("Count four-neighbor lit components in a grid.",
                                       "Refine a nonempty connected grid into an island.",
                                       "Return the connected island containing a lit seed.",
                                       "Light clipped neighbors of every island pixel.",
                                       "Apply an operation to each island and merge its results.",
                                       "Count dark components enclosed by lit pixels.",
                                       "Crop a connected island to its minimal bounding rectangle.",
                                       "Apply an operation to every rotation and reflection of a shape.",
                                       "Find the lexicographically least transformed pattern.",
                                       "Subtract holes from the count of lit components.",
                                       "Compare multisets of component shape signatures.",
                                       "Find dark cells whose addition yields a target result.")[index],
                        "body": nodes.to_json(definition.body) if definition.body is not None else None,
                        "status": definition.status,
                        "evidence": definition.evidence.to_dict(), "contract": definition.contract.to_dict(),
                        "cost": definition.cost.to_dict(), "examples": [main, *extra]})

    compute_image = library.run("map_components", (kernel.FnRef("grow"), first)).outcome.value
    showcase = []
    for index, card in enumerate(design["showcase"]):
        if index == 0:
            result = library.run("euler", (compute_image,), fuel=4_000_000)
            outcome, steps = result.outcome, result.steps
        else:
            example = entries[11 if index == 1 else 10]["examples"][0]
            outcome, steps = values.decode_outcome(example["outcome"]), example["steps"]
        checked = isinstance(outcome, values.Ok) and story.depth_encode(outcome.value) == card["answer"]
        if not checked:
            raise ValueError(f"showcase oracle mismatch: {card['angle']}: {outcome!r}")
        showcase_english = (
            ("Nested component expansion requires a fresh Euler count after mapping.",
             "Run @map_components[grow] then euler and compare with the depth reference."),
            ("A single change can both join components and close a hole; all dark cells must be tested.",
             "Run @scan_add[euler] over A0 and verify every returned coordinate."),
            ("Equal areas and Euler numbers do not imply matching component shapes.",
             "Compare the multisets of normalized component signatures."),
        )
        showcase.append({key + "_zh" if key in ("why_hard", "check") else key: value
                         for key, value in card.items()} | {"why_hard": showcase_english[index][0],
                         "check": showcase_english[index][1], "answer_checked": True,
                         "check_method": "kernel evaluation compared to independent depth reference",
                         "steps": steps})

    layer0 = {"objects": [], "operations": [], "combinators": [], "observations": []}
    english = {
        "objects": (("Pixel point", "Represent an integer pixel coordinate."),
                    ("Rectangular grid", "Represent a nonempty rectangular binary image."),
                    ("Reference image A0", "Provide the first public pixel-grid constant."),
                    ("Reference image A1", "Provide the second public pixel-grid constant."),
                    ("Reference image B0", "Provide the third public pixel-grid constant.")),
        "operations": (("Light a pixel", "Set a pixel to lit within the grid bounds."),
                       ("Erase a pixel", "Clear a pixel within the grid bounds."),
                       ("Identity operation", "Return the supplied value unchanged.")),
        "combinators": (("Sequential composition", "Apply two operations in order and propagate failures."),),
        "observations": (("Read pixels", "Reveal the public pixel rows."),
                         ("Measure lit area", "Count the lit pixels in the public grid.")),
    }
    for category, source in (("objects", "objects"), ("operations", "operations"),
                             ("combinators", "combinators"), ("observations", "observations")):
        for index, fragment in enumerate(design["layer0"][source]):
            expression, description = _given(fragment)
            layer0[category].append({"decl": expression, "doc_zh": description,
                                     "title": english[category][index][0],
                                     "definition": english[category][index][1]})
    layer0["observation"] = {"truth": declaration["observation"]["truth"],
                              "probes": layer0.pop("observations"),
                              "show": declaration["observation"]["show"],
                              "judge_view": declaration["observation"]["judge_view"]}
    layer0["combinators"] = {**declaration["combinators"], "given": layer0["combinators"]}
    ladder_changes = (
        "Work on 8x8 grids with two or three components and no enclosed holes.",
        "Expand to 12x12 grids, up to six components, two holes, and one grow operation.",
        "Use 16x16 grids with nested holes and all eight shape orientations.",
        "Compose several transforms across 24x24 grids with up to six holes.",
        "Search over 600 dark cells on 32x32 grids with several nested calls.",
    )
    ladder = [{"level": item["level"], "knobs": item["knobs"],
               "what_changes": ladder_changes[index], "what_changes_zh": item["what_changes"]}
              for index, item in enumerate(design["ladder"])]
    fixtures = {name: {"ascii": name, "expression": nodes.to_json(nodes.Call(name)),
                       "rows": list(getattr(reference, name).rows),
                       "grid": story.depth_encode(hosts.to_card(getattr(reference, name).rows)),
                       "value": values.encode(hosts.to_card(getattr(reference, name).rows))}
                for name in ("A0", "A1", "B0")}
    return {"schema": "opulse.world_v2_export/1", "world": "pixels", "version": 1, "wave": 1,
            "title": declaration["title"], "title_zh": declaration["source"]["title_zh"],
            "pitch_zh": design["pitch"], "modality_zh": "文本格子图与二值图像",
            "decl": declaration, "layer0": layer0, "fixtures": fixtures,
            "tower_source": "depth", "story": entries,
            "evidence_fixture": {name: {"evidence": definition.evidence.to_dict(),
                                        "cost": definition.cost.to_dict()}
                                 for name, definition in library.definitions.items()
                                 if definition.origin == "invented"},
            "ladder": ladder, "showcase": showcase,
            "modalities_zh": design["modalities"], "toy_risk_zh": design["toy_risk"],
            "open_kinds": ["object", "operation", "combinator", "observation"],
            "tags": {"domain": "perception", "modalities": ["text", "image"],
                     "open_kinds": ["object", "operation", "combinator", "observation"],
                     "star_kind": "observation", "reasoning": ["geometry", "counting", "equivalence", "search"],
                     "state": "stateless", "outcomes": "deterministic", "visibility": "full",
                     "agents": 1, "scale": "1..32 by 1..32 grids; 12 tower definitions",
                     "difficulty": "8x8 components to 32x32 inverse pixel search",
                     "uses": ["evaluation", "teaching", "experiment"]},
            "emerges_zh": "从四邻域连通性逐层构造岛、形态、八向同构及逐格逆向搜索。",
            "checking_zh": "有限 2x2 域穷举与显式有界域检验，并对十二层原图算例逐项核对独立参考。"}


def main(library=None):
    path = ROOT / "docs/assets/data/worlds_v2/pixels.json"
    if library is None and os.environ.get("PIXELS_EVIDENCE_FIXTURE"):
        fixture = json.loads(Path(os.environ["PIXELS_EVIDENCE_FIXTURE"]).read_text(encoding="utf-8"))
        library = story.build_library(fixture)
    path.write_text(json.dumps(build_export(library), sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")



_build_export_raw = build_export


def build_export(*args, **kwargs):
    """The export after the shared last step (export_util.finalize_export)."""
    return finalize_export(_build_export_raw(*args, **kwargs))


if __name__ == "__main__":
    main()
