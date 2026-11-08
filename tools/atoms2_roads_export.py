"""Export promoted roads definitions and actual Metro kernel runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from itertools import islice, product
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from opulse.atoms.kernel import FnRef
from opulse.atoms.values import Card, Ok, encode, encode_outcome
from opulse.worlds_v2.roads import depth_hosts as hosts
from opulse.worlds_v2.roads import story
from opulse.worlds_v2.roads.story import build_library, definitions
from tools.atoms2_core_source import printed_declaration, printed_label

OUTPUT = ROOT / "docs/assets/data/atoms2/roads_core.json"
DESIGN = ROOT / "docs/assets/data/atoms2/roads.json"
ASKED = ("A", "D", "F", "H", "K", "L")
TARGETS = ("Route", "cost", "explore", "best", "optimal", "close", "failures", "reachable",
           "survives", "mincut", "cut_certificate")
SMALL_NODES = ("A", "B", "C", "D")
SMALL_EDGES = (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))


def small_graph(weights):
    return hosts.to_card((SMALL_NODES, tuple((start, end, weight)
                                            for (start, end), weight in zip(SMALL_EDGES, weights))))


def partial_graph_scope(scope):
    match = re.search(r"4-node, 4-road graphs? with edge weights (\d+)\.\.(\d+)", scope["domain"])
    complete = re.search(r"^all (\d+) weightings \(each road weight (\d+)\.\.(\d+)\) of the fixed connected "
                         r"4-node, 4-road graph A-B, A-C, B-D, C-D;", scope["domain"])
    if complete:
        match = complete
    if not match or len(SMALL_NODES) != 4 or len(SMALL_EDGES) != 4:
        raise ValueError("Roads verification family differs from the fixed four-node topology")
    weights = range(int(complete[2] if complete else match[1]),
                    int(complete[3] if complete else match[2]) + 1)
    domain_total = len(weights) ** len(SMALL_EDGES)
    if (not weights or scope["size"] < 1 or scope["size"] > domain_total or
            complete and int(complete[1]) != domain_total or
            complete and scope["size"] != domain_total):
        raise ValueError("Roads verification count differs from the fixed weighting family")
    topology = f"one {len(SMALL_NODES)}-node topology"
    if scope["size"] == domain_total:
        return {**scope, "partial": False, "domain_total": domain_total, "topology": topology}
    return {**scope, "partial": True, "domain_total": domain_total, "topology": topology,
            "domain": f"first {scope['size']} of {domain_total} weightings of {topology}",
            "description": f"Partial check: {scope['size']} of {domain_total} weightings of {topology}. "
                           "The four fixed roads are AB, AC, BD and CD; each weight varies from "
                           f"{weights.start} to {weights.stop - 1}."}


def input_digest():
    paths = sorted((ROOT / "src/opulse/atoms").glob("*.py"))
    paths += sorted((ROOT / "src/opulse/worlds_v2/roads").glob("*.py"))
    paths += [DESIGN, Path(__file__), ROOT / "tools/atoms2_core_source.py", ROOT / "tools/atoms2_parse_status.py",
              ROOT / "worlds/catalogue/depth/roads.py"]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode("ascii") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def payload_digest(export):
    payload = {key: export[key] for key in ("schema", "inputs_sha256", "world", "map", "cards", "failing")}
    content = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("ascii")).hexdigest()


def selected_definitions():
    return [definition for definition in definitions() if definition.name in TARGETS]


def build_card_library():
    selected = tuple(definition for definition in definitions() if definition.name != "worst")
    with patch.object(story, "definitions", return_value=selected):
        return build_library()


def declaration(definition, design):
    printed = printed_declaration(definition)
    if printed["text"] is not None:
        return printed["text"], printed_label(printed)
    if definition.name not in design:
        if definition.name == "reachable":
            text = "op reachable(g: Roads, s: Text, target: Text) = "
            text += f"test target in the fixed point of reach_step on g from s L{definition.layer}"
            return text, f"Design summary (printer unavailable: {printed['reason']})"
        raise ValueError(f"no design summary for {definition.name}")
    text = design[definition.name]["declaration"]
    return text.rsplit(" L", 1)[0] + f" L{definition.layer}", f"Design summary (printer unavailable: {printed['reason']})"


def outside_checked_scope(scope, args):
    domain = scope["domain"]
    recorded = partial_graph_scope(scope)
    if recorded["domain_total"] != 4 ** len(SMALL_EDGES) or not domain.startswith((
            "all 256 weightings (each road weight 1..4) of the fixed connected 4-node, 4-road graph A-B, A-C, B-D, C-D;",
            "4-node, 4-road graphs with edge weights 1..4")):
        raise ValueError(f"Unknown roads verification domain: {domain}")

    def graphs(value):
        if isinstance(value, Card):
            if value.sort == "Roads":
                yield value
            for field in value.fields:
                yield from graphs(field)

    checked_graphs = {small_graph(weights)
                      for weights in islice(product((1, 2, 3, 4), repeat=len(SMALL_EDGES)), scope["size"])}
    if len(checked_graphs) != scope["size"]:
        raise ValueError("Roads verification graph count differs from recorded scope")
    found = [graph for arg in args for graph in graphs(arg)]
    if not found:
        raise ValueError("Roads example has no graph to compare with checked scope")
    return any(graph not in checked_graphs for graph in found)


def run_case(library, name, args, text, scope=None):
    run = library.run(name, args, trace=True)
    sources = []
    for index, arg in enumerate(args):
        if isinstance(arg, Card) and arg.sort == "Route" and arg.tag == "val":
            minted = library.run("Route.make", (arg.fields[0],))
            if minted.outcome != Ok(arg):
                raise ValueError("roads Route example must be constructed by Route.make")
            sources.append({"index": index, "target": "Route.make", "args": [encode(arg.fields[0])],
                            "outcome": encode_outcome(minted.outcome), "steps": minted.steps})
    return {"call": text, "target": name, "args": [encode(arg) for arg in args],
            **({"input_from": sources} if sources else {}),
            **({"outside_checked_scope": True} if scope is not None and outside_checked_scope(scope, args) else {}),
            "outcome": encode_outcome(run.outcome), "steps": run.steps,
            "trace": {"name": run.trace.name, "steps": run.trace.steps,
                      "children": [{"name": child.name, "steps": child.steps}
                                   for child in run.trace.children[:6]],
                      "remaining_children": max(0, len(run.trace.children) - 6)}}


def build_export(library=None):
    graph_data = json.loads(DESIGN.read_text())["graph"]
    expected_edges = tuple((identifier[0], identifier[1], weight)
                           for identifier, weight in graph_data["edges"].items())
    if tuple(graph_data["nodes"]) != hosts.METRO_NODES or expected_edges != hosts.METRO_EDGES:
        raise ValueError("browser Metro map differs from the core Metro map")
    if library is None:
        try:
            library = build_card_library()
        except Exception as error:
            raise RuntimeError(f"roads world code failed in build_library(): {error} (not stale UI data)") from error
    route_raw = hosts.route_raw(hosts.METRO, hosts.items(*ASKED))
    asked = library.run("Route.make", (route_raw,)).outcome
    if not isinstance(asked, Ok):
        raise TypeError("asked Metro route failed construction")
    invalid = hosts.route_raw(hosts.METRO, hosts.items("A", "E", "L"))
    samples = {
        "Route": ("Route.make", (route_raw,), "Route<Metro,A,D,F,H,K,L>"),
        "cost": ("cost", (asked.value,), "cost(Route<Metro,A,D,F,H,K,L>)"),
        "best": ("best", (hosts.METRO, "A", "L"), "best(Metro,A,L)"),
        "optimal": ("optimal", (asked.value,), "?optimal{Route<Metro,A,D,F,H,K,L>}"),
        "close": ("close", (hosts.METRO, hosts.edge_set(hosts.items("AB", "AD"))),
                  "close(Metro,Edges<AB,AD>)"),
        "failures": ("failures", (FnRef("close"), hosts.METRO, 2), "@failures[close](Metro,2)"),
        "reachable": ("reachable", (hosts.METRO, "A", "L"), "reachable(Metro,A,L)"),
        "survives": ("survives", (hosts.METRO, "A", "L", 2), "?survives{Metro,A,L,2}"),
        "mincut": ("mincut", (hosts.METRO, "A", "L"), "mincut(Metro,A,L)"),
        "cut_certificate": ("cut_certificate", (hosts.METRO, "A", "L"), "?cut_certificate{Metro,A,L}"),
    }
    samples["explore"] = ("explore", (FnRef("edge"), hosts.METRO, "A", "L"), "@explore[edge](Metro,A,L)")
    design = {item["name"].lstrip("?@"): item for item in json.loads(DESIGN.read_text())["tower"]}
    records = library.records()
    cards = []
    for definition in selected_definitions():
        record = records[definition.name]
        if record.status != "promoted" or record.evidence is None:
            raise ValueError(f"{definition.name} has no promoted evidence")
        invented = sorted({name.split(".")[0] for name in record.depends_on
                           if name.split(".")[0] in records and records[name.split(".")[0]].origin == "invented"})
        layer = 1 + max((records[name].layer for name in invented), default=0)
        if layer != record.layer:
            raise ValueError(f"{definition.name}: inconsistent dependency layer")
        source, label = declaration(record, design)
        card = {"name": record.name, "display_name": ("?" if record.kind == "observation" else
                "@" if record.kind == "combinator" else "") + record.name,
                "kind": record.kind, "declaration": source, "declaration_label": label,
                "dependencies": list(record.depends_on), "invented_dependencies": invented,
                "layer": layer, "status": record.status,
                "evidence": {"method": record.evidence.method, "scope": partial_graph_scope(record.evidence.scope),
                             "checks": list(record.evidence.checks), "content_hash": record.evidence.content_hash}}
        target, args, text = samples[definition.name]
        try:
            card["example"] = run_case(library, target, args, text, record.evidence.scope)
        except Exception as error:
            raise RuntimeError(f"roads world/core failed running {definition.name}: {error}") from error
        cards.append(card)
    failing = run_case(library, "Route.make", (invalid,), "Route<Metro,A,E,L>",
                       records["Route"].evidence.scope)
    if "bottom" not in failing["outcome"]:
        raise ValueError("missing-road route did not fail")
    result = {"schema": "opulse.roads_core/1", "inputs_sha256": input_digest(),
              "world": "roads", "map": "Metro", "cards": cards, "failing": failing}
    result["payload_sha256"] = payload_digest(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed export is stale")
    args = parser.parse_args()
    if args.check and OUTPUT.is_file():
        try:
            existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if (existing["schema"] == "opulse.roads_core/1" and
                    existing["inputs_sha256"] == input_digest() and
                    existing["payload_sha256"] == payload_digest(existing) and
                    [card["name"] for card in existing["cards"]] ==
                    [definition.name for definition in selected_definitions()] and
                    existing["failing"]["outcome"] == {"bottom": "invalid"}):
                return
        except (ValueError, KeyError, TypeError):
            pass
    from opulse.notation3.export import add_notation3

    content = json.dumps(add_notation3(build_export(), 'atoms2', source='atoms2/roads_core.json'),
                         sort_keys=True, ensure_ascii=True, indent=1) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
            parser.exit(1, f"stale generated data: {OUTPUT}\n")
    else:
        OUTPUT.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
