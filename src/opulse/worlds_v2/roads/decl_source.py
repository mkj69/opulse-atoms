"""Deterministic source for the depth declaration and its generic primitives."""

import json
from pathlib import Path

from opulse.atoms.combinators import fix_spec

from . import depth_combinators, depth_hosts

PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/roads@1.json"

PRIMITIVES = {
    "items": ((), "List"), "empty": (("List",), "bool"),
    "head": (("List",), "unknown"), "tail": (("List",), "List"),
    "cons": (("unknown", "List"), "List"), "append": (("List", "List"), "List"),
    "contains": (("unknown", "List"), "bool"), "eq": (("unknown", "unknown"), "bool"),
    "lt": (("unknown", "unknown"), "bool"), "add": (("int", "int"), "int"),
    "sub": (("int", "int"), "int"), "reverse": (("List",), "List"),
    "graph_nodes": (("Roads",), "List"), "graph_edges": (("Roads",), "List"),
    "road_nodes": (("Roads",), "List"),
    "road_edge": (("Roads", "Text", "Text"), "int"),
    "edge_id": (("Edge",), "Text"), "edge_set": (("List",), "Edges"),
    "route_raw": (("Roads", "List"), "RouteRaw"),
    "closure_raw": (("Roads", "Edges"), "ClosureRaw"),
    "worst_record": (("Int", "Edges", "unknown"), "Worst"),
    "no_route": ((), "unknown"), "disconnected": ((), "Worst"),
    "invalid_terminals": ((), "unknown"), "invalid_budget": ((), "unknown"),
    "distinct": (("List",), "bool"), "subset": (("List", "List"), "bool"),
    "pair_before": (("List", "List"), "bool"),
    "RouteRaw.graph": (("RouteRaw",), "Roads"),
    "RouteRaw.vertices": (("RouteRaw",), "List"),
    "ClosureRaw.base": (("ClosureRaw",), "Roads"),
    "ClosureRaw.closed_edges": (("ClosureRaw",), "Edges"),
    "road_fields": (("Edge",), "List"),
    "Edges.edge_ids": (("Edges",), "List"),
    "sort_frontier": (("List",), "List"),
    "sort_texts": (("List",), "List"), "reach_state": (("Roads", "List"), "Reach"),
    "reach_graph": (("Reach",), "Roads"), "reach_seen": (("Reach",), "List"),
    "sort_edge_sets": (("List",), "List"), "defined": (("unknown",), "bool"),
    "capture": (("unknown",), "Lift"), "is_value": (("Lift",), "bool"),
    "unlift": (("Lift",), "unknown"),
    "roads_from_parts": (("List", "List"), "Roads"),
    "comb_positive": (("int",), "bool"), "comb_dec": (("int",), "int"),
    "fix_equal": (("unknown", "unknown"), "bool"),
}


def build():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    data["constants"]["metro_edges"] = [list(road) for road in depth_hosts.METRO_EDGES]
    data.pop("open_kinds", None)
    data["operations"] = [operation for operation in data["operations"] if operation["name"] not in
                          ("node_partitions", "valid_vertices", "closure_valid", "sort_closed", "edge_ids")]
    existing = {op["name"] for op in data["operations"]}
    for name, (inputs, output) in PRIMITIVES.items():
        if name in existing:
            continue
        data["operations"].append({
            "kind": "operation", "name": name, "role": "transform",
            "inputs": [{"name": f"arg{index}", "sort": sort, "enter": "bottom"}
                       for index, sort in enumerate(inputs)],
            "output": {"sort": output, "enter": "bottom"},
            "rule": f"Public constructor, accessor, comparison or finite-list primitive: {name}.",
            "errors": ["invalid"],
            "impl": {"host": f"opulse.worlds_v2.roads.depth_hosts:{name}", "digest": "0" * 64},
            "cost": 1, "strict": True, "reads_params": []})
    for operation in data["operations"]:
        if operation["name"] in ("road_nodes", "road_edge"):
            operation["impl"]["host"] = "opulse.worlds_v2.roads.depth_hosts:" + {
                "road_nodes": "graph_nodes", "road_edge": "edge"}[operation["name"]]
        if operation["name"] in ("edge", "size"):
            operation["output"]["sort"] = "int"
        if operation["name"] == "edge":
            operation["inputs"][1]["sort"] = operation["inputs"][2]["sort"] = "unknown"
        for field in (*operation["inputs"], operation["output"]):
            if field["sort"] in ("Int", "Bool"):
                field["sort"] = field["sort"].lower()
        if operation["name"] in ("defined", "capture"):
            operation["strict"] = False
        if operation["name"] == "worst_record":
            operation["inputs"][2]["sort"] = "unknown"
        if operation["name"] == "no_route":
            operation["output"]["sort"] = "unknown"
    data["objects"] = [obj for obj in data["objects"] if obj["name"] not in ("RouteRaw", "ClosureRaw")]
    data["objects"].extend({"kind": "object", "name": name, "form": "given", "doc": "Generic primitive value sort."}
                           for name in ("unknown", "int", "bool", "str", "Reach", "Lift", "public_graph", "RouteRaw", "ClosureRaw")
                           if name not in {obj["name"] for obj in data["objects"]})
    data["objects"] = [obj for obj in data["objects"] if obj["name"] not in ("Route", "Closure")]
    for probe in data["observation"]["probes"]:
        probe["reads"] = "public_graph"
    data["combinators"]["recursion"] = "fuel"
    data["combinators"]["library"] = [spec.to_dict() for spec in
                                       (depth_combinators.chain_spec(), fix_spec())]
    for operation in data["operations"]:
        if operation["name"] in ("RouteRaw.graph", "RouteRaw.vertices", "ClosureRaw.base", "ClosureRaw.closed_edges", "Edges.edge_ids"):
            operation["impl"]["host"] = "opulse.worlds_v2.roads.depth_hosts:" + {
                "RouteRaw.graph": "raw_graph", "RouteRaw.vertices": "raw_vertices",
                "ClosureRaw.base": "raw_base", "ClosureRaw.closed_edges": "raw_closed",
                "Edges.edge_ids": "edge_set_ids"}[operation["name"]]
    data["lock"] = {}
    return data


def main():
    PATH.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
