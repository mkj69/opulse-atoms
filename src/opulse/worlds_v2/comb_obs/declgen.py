"""Generate the warehouse layer-zero declaration and its host lock."""

import json

from opulse.tasks_v2.decl import WorldFile, compute_lock, host_digest

from .combinators import given_combinators
from .world import DECL_PATH

HOST = "opulse.worlds_v2.comb_obs.hosts:"
PHYSICAL = {"scan", "move", "charge", "pick", "deliver"}
GENERIC = {
    "neighbors": (1, "Path"), "square": (2, "Path"),
    "map_get": (2, "any"), "map_has": (2, "Bool"), "map_missing_any": (2, "Bool"),
    "keys": (1, "Path"), "singleton": (1, "Map"),
    "graph_expand": (3, "any"), "graph_frontier": (1, "Path"),
    "graph_parents": (1, "Map"), "graph_path": (3, "Path"),
    "parent_distance": (3, "Int"),
    "empty": (1, "Bool"), "head": (1, "any"), "tail": (1, "Path"),
    "size": (1, "Int"), "item": (2, "any"), "field": (2, "any"),
    "pack": (2, "any"), "prepend": (2, "Path"), "difference": (2, "Path"),
    "batches": (1, "Path"), "less": (2, "Bool"), "equal": (2, "Bool"),
    "add": (2, "Int"), "sub": (2, "Int"), "mul": (2, "Int"), "mod": (2, "Int"),
    "cell_delta": (2, "Cell"), "manhattan": (2, "Int"),
    "sorted_items": (1, "Path"), "sort": (1, "Path"), "to_list": (1, "List"),
    "select_min": (2, "any"), "pair_first": (1, "any"), "pair_second": (1, "any"),
    "tuple4": (4, "any"), "is_none": (1, "Bool"),
    "none": (0, "any"), "empty_set": (0, "any"), "tuple8": (8, "any"),
    "decrement": (1, "Int"), "budget_empty": (1, "Bool"),
    "all_in": (2, "Bool"), "member": (2, "Bool"),
    "set_add": (2, "any"), "set_remove": (2, "any"), "append": (2, "Path"),
    "list9": (9, "List"), "min_list": (1, "Int"),
}


def build():
    data = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    for sort in ("any", "bool"):
        if not any(obj["name"] == sort for obj in data["objects"]):
            data["objects"].append({"kind": "object", "name": sort, "form": "given",
                                    "doc": "Generic finite data value."})
    for obj in data["objects"]:
        obj.setdefault("host", None)
    data["operations"] = [operation for operation in data["operations"]
                          if operation["name"] in PHYSICAL]
    for operation in data["operations"]:
        operation.setdefault("symbol", None)
    for name, (arity, output) in GENERIC.items():
        data["operations"].append({
            "name": name, "kind": "operation", "role": "transform", "symbol": None,
            "inputs": [{"sort": "any", "name": f"arg{index}", "enter": "bottom"}
                       for index in range(arity)],
            "output": {"sort": {"Int": "int", "Bool": "bool"}.get(output, output),
                       "enter": "bottom"},
            "rule": "Generic finite operation on explicitly supplied values.",
            "errors": ["invalid"], "impl": {"host": HOST + name},
            "cost": 1, "strict": True, "reads_params": [],
        })
    data["combinators"]["library"] = [spec.to_dict() for spec in given_combinators()]
    for operation in data["operations"]:
        implementation = operation["impl"]
        implementation["digest"] = host_digest(implementation["host"])
    for probe in data["observation"]["probes"]:
        probe["impl"]["digest"] = host_digest(probe["impl"]["host"])
    data["lock"] = compute_lock(WorldFile.from_dict(data))
    return data


def main():
    DECL_PATH.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
