"""Generate the locked public tasks declaration, independent of invented cards."""

import json

from opulse.atoms import nodes as n
from opulse.atoms.spec import CombinatorSpec, Edge, ObjectSpec, OperationSpec
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import WorldFile, compute_lock, host_digest

from .world import DECL_PATH

HOST = "opulse.worlds_v2.op_only.hosts:"


def declaration():
    objects = tuple(ObjectSpec(name, "given") for name in
                    ("Nat", "Bool", "List", "BitSet", "Edge", "Gates", "Rel", "Profile", "Switch",
                     "int", "bool", "any"))
    signatures = (
        ("id", ("Rel",), "Rel", "identity"),
        ("union", ("Rel", "Rel"), "Rel", "union"),
        ("compose", ("Rel", "Rel"), "Rel", "compose"),
        ("transpose", ("Rel",), "Rel", "transpose"),
        ("intersect", ("Rel", "Rel"), "Rel", "intersect"),
        ("subtract", ("Rel", "Rel"), "Rel", "subtract"),
        ("quotient", ("Rel", "Rel"), "Rel", "quotient"),
        ("braid", ("int", "int", "int", "Gates"), "Rel", "braid"),
        ("switch_net", ("int", "int", "int"), "Rel", "switch_net"),
        ("fix2_host", ("any", "Rel", "Rel"), "Rel", "fix2"),
        ("dag_fold_host", ("any", "Rel"), "Profile", "dag_fold"),
        ("set_profile", ("Profile", "int", "int", "int"), "Profile", "set_profile"),
        ("filter_edges", ("any", "Rel", "Profile", "Profile"), "Rel", "filter_edges"),
        ("source", ("Edge",), "int", "source"),
        ("target", ("Edge",), "int", "target"),
        ("depth_at", ("Profile", "int"), "int", "depth_at"),
        ("ways_at", ("Profile", "int"), "int", "ways_at"),
        ("add", ("int", "int"), "int", "add"),
        ("mul", ("int", "int"), "int", "mul"),
        ("eq", ("int", "int"), "bool", "eq"),
        ("lt", ("int", "int"), "bool", "lt"),
    )
    operations = tuple(OperationSpec(name, "transform", tuple(Edge(sort, name=f"arg{index}")
                       for index, sort in enumerate(inputs)), Edge(output),
                       f"Fixed public {name} operator; counted as a layer-zero call.",
                       impl={"host": HOST + host, "digest": host_digest(HOST + host)})
                       for name, inputs, output, host in signatures)
    probes = [{"name": name, "sort": sort, "reads": "Rel", "reveals": ["public_relation"],
               "impl": {"host": HOST + name, "digest": host_digest(HOST + name)}}
              for name, sort in (("has", "bool"), ("count", "int"),
                                 ("maxdepth", "int"), ("longest_count", "int"))]
    combinators = (
        CombinatorSpec("fix2", ("expand", "seed", "r"), ("expand",),
                       n.Call("fix2_host", (n.Var("expand"), n.Var("seed"), n.Var("r")))),
        CombinatorSpec("dag_fold", ("advance", "d"), ("advance",),
                       n.Call("dag_fold_host", (n.Var("advance"), n.Var("d")))),
        CombinatorSpec("each", ("predicate", "d", "forward", "backward"), ("predicate",),
                       n.Call("filter_edges", (n.Var("predicate"), n.Var("d"),
                                               n.Var("forward"), n.Var("backward")))),
    )
    world = WorldDecl("op_only", 1, "atoms-v2", {}, {}, objects, operations,
                      {"nodes": ["Var", "Lit", "Call", "Let", "Case"],
                       "library": [item.to_dict() for item in combinators], "recursion": "none"},
                      {"truth": "Rel", "probes": probes,
                       "capabilities": {"learner": {"probes": "all"}, "judge": {"probes": "all"}},
                       "show": [probe["name"] for probe in probes], "judge_view": "full"},
                      {},
                      {"title": "Relation Networks: Operations Only"}, ("operation",))
    data = {**world.to_dict(), "source": {"design": "op_only.json"}, "codec": {}}
    data = WorldFile.from_dict(data).to_dict()
    data["lock"] = compute_lock(WorldFile.from_dict(data))
    return data


def main():
    DECL_PATH.write_text(json.dumps(declaration(), ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")


if __name__ == "__main__":
    main()
