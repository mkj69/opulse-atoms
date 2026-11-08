"""Construct the checked-in declaration from its fixed layer-zero operation table."""

import json
from pathlib import Path

from opulse.atoms import nodes as n
from opulse.atoms.spec import CombinatorSpec
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import WorldFile, compute_lock, host_digest

PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/comb_only@1.json"

SIGNATURES = {
    "weight": ("Plan,int", "int"), "adjacent": ("Plan,int", "Set"),
    "start": ("Plan", "State"), "take": ("State,int", "State"),
    "ban": ("State,int", "State"), "priority": ("Plan,Set,int", "Tuple"),
    "degree": ("Plan,int,Set", "int"), "add": ("int,int", "int"),
    "identity": ("unknown", "unknown"), "union": ("Set,Set", "Set"),
    "popcount": ("Set", "int"), "drop_lowest": ("Set", "Set"),
    "split_mid": ("List", "Pair"), "head": ("List", "unknown"),
    "tail": ("List", "List"), "append": ("List,unknown", "List"),
    "concat": ("List,List", "List"), "all_vertices": ("Plan", "Set"),
    "ascending": ("Set", "List"), "member": ("unknown,List", "bool"),
    "intersect": ("Set,Set", "Set"), "empty": ("List", "bool"),
    "singleton_list": ("List", "bool"), "le": ("int,int", "bool"),
    "lt": ("unknown,unknown", "bool"), "eq": ("unknown,unknown", "bool"),
    "difference": ("Set,Set", "Set"), "lowest": ("Set", "int"),
    "singleton": ("int", "Set"), "length": ("List", "int"),
    "first": ("Pair", "unknown"), "second": ("Pair", "unknown"),
    "pair": ("unknown,unknown", "Pair"), "available": ("State", "Set"),
    "chosen": ("State", "List"), "score": ("State", "int"),
    "legal": ("State", "bool"), "plan": ("State", "Plan"),
    "state_group": ("State,Set", "State"), "join_state": ("State,State", "State"),
    "done": ("State", "State"), "non_decreasing": ("", "unknown"),
    "empty_frontier": ("", "unknown"), "outside_universe": ("", "unknown"),
    "decrement": ("int", "int"), "resource": ("", "unknown"),
    "nonzero": ("Set", "bool"),
}


def build():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    data["source"] = {"catalogue": "worlds/catalogue/depth/comb_only.json"}
    data["codec"] = {}
    data["observation"]["truth"] = "State"
    data["observation"]["show"] = ["score", "chosen", "legal", "available"]
    for probe in data["observation"]["probes"]:
        probe["reveals"] = [probe["reveals"]] if isinstance(probe["reveals"], str) else probe["reveals"]
        probe["impl"] = None
    existing = {item["name"] for item in data["objects"]}
    data["objects"].extend({"kind": "object", "name": name, "form": "given", "doc": description}
                           for name, description in (
                               ("Nat", "Finite nonnegative integer literal."),
                               ("Int", "Finite signed integer literal."),
                               ("Bool", "Fixed boolean truth value.")) if name not in existing)
    def var(name):
        return n.Var(name)

    def call(name, *arguments):
        return n.Call(name, arguments)

    def choose(condition, yes, no):
        return n.Case(((n.Test(condition), yes),), no)

    data["combinators"]["library"] = [
        CombinatorSpec("case", ("yes", "no", "test", "x"), ("yes", "no", "test"),
                       choose(call("test", var("x")), call("yes", var("x")),
                              call("no", var("x")))).to_dict(),
        CombinatorSpec("jump", ("step", "guard", "x", "fuel"), ("step", "guard"),
                       n.Rec("loop", ("state", "remaining"),
                             choose(call("guard", var("state")),
                                    choose(call("le", var("remaining"), n.Lit(0)),
                                           call("resource"),
                                           call("loop", call("step", var("state")),
                                                call("decrement", var("remaining")))),
                                    var("state")),
                             (var("x"), var("fuel")), var("remaining"))).to_dict(),
    ]
    data["operations"] = [
        {"kind": "operation", "name": name, "role": "transform",
         "inputs": [{"name": f"arg{index}", "sort": sort, "enter": "bottom"}
                    for index, sort in enumerate(inputs.split(",") if inputs else ())],
         "output": {"sort": output, "enter": "bottom"},
         "rule": f"Fixed public local primitive {name}.", "errors": ["range", "unavailable"],
         "impl": {"host": f"opulse.worlds_v2.comb_only.hosts:{name}",
                  "digest": host_digest(f"opulse.worlds_v2.comb_only.hosts:{name}")},
         "cost": 1, "strict": True, "reads_params": []}
        for name, (inputs, output) in SIGNATURES.items()
    ]
    data = WorldDecl.from_dict(data).to_dict()
    data["lock"] = compute_lock(WorldFile.from_dict(data))
    return data


def main():
    PATH.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
