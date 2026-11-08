"""Generate the fixed public kernel declaration and its host lock."""

import json

from opulse.atoms import nodes as n
from opulse.atoms.spec import CombinatorSpec, Edge, ObjectSpec, OperationSpec
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import WorldFile, compute_lock, host_digest

from .world import DECL_PATH

HOST = "opulse.worlds_v2.obs_only.hosts:"

SIGNATURES = {
    "move": (["any", "any"], "int"),
    "emit": (["Fin64", "Fin100", "PublicConfig"], "Fin8"),
    "step": (["State", "Action", "PublicConfig"], "State"),
    "add": (["any", "any"], "any"),
    "mul": (["any", "any"], "any"),
    "div": (["any", "any"], "any"),
    "le": (["any", "any"], "any"),
    "eq": (["any", "any"], "any"),
    "at": (["any", "any"], "any"),
    "sum": (["any"], "any"),
    "sort_pairs": (["any"], "any"),
    "first": (["any", "any"], "any"),
    "len": (["any"], "int"),
    "inc": (["int"], "int"),
    "dec": (["int"], "int"),
    "empty": (["any"], "any"),
    "head": (["any"], "any"),
    "tail": (["any"], "any"),
    "trace_sum": (["int", "Action", "Fin8"], "int"),
    "remaining": (["Fin80", "int"], "int"),
    "index": (["any", "any"], "any"),
    "sub": (["any", "any"], "int"),
    "pair": (["any", "any"], "any"),
    "append": (["any", "any"], "any"),
    "put_add": (["any", "any", "any"], "any"),
    "zeros": (["int"], "any"),
    "range_values": (["int"], "any"),
    "intervals": (["int"], "any"),
    "slice_values": (["any", "int", "int"], "any"),
    "field": (["PublicConfig", "any"], "any"),
    "contains": (["any", "any"], "Bool"),
    "gt": (["any", "any"], "Bool"),
    "join": (["any", "any"], "Text"),
    "text": (["any"], "Text"),
    "fraction_text": (["Rational"], "Text"),
    "fail": (["any"], "any"),
    "frame_at": (["Trace", "any"], "Fin8"),
    "issued_at": (["Trace", "any"], "Action"),
    "prior_mass": (["PublicConfig", "any"], "Rational"),
    "protocol_mass": (["PublicConfig", "any", "Fin8"], "Rational"),
    "config_of": (["Trace"], "PublicConfig"),
}


def call(name, *args):
    return n.Call(name, args)


def var(name):
    return n.Var(name)


def branch(condition, yes, no):
    return n.Case(((n.Test(condition), yes),), no)


def combinators():
    chain = call("g", call("f", var("x")))
    fold = n.Rec("walk", ("result", "remaining"),
                 branch(call("empty", var("remaining")), var("result"),
                        call("walk", call("f", var("result"), call("head", var("remaining"))),
                             call("tail", var("remaining")))),
                 (var("initial"), var("items")), call("len", var("remaining")))
    trace_rec = n.Rec("scan", ("result", "current"),
                      branch(call("eq", var("current"), var("t")), var("result"),
                             call("scan", call("f", var("result"),
                                               call("issued_at", var("v"), var("current")),
                                               call("frame_at", var("v"), call("inc", var("current")))),
                                  call("inc", var("current")))),
                      (var("base"), n.Lit(0)), call("remaining", var("t"), var("current")))
    repeat = n.Rec("loop", ("result", "remaining"),
                   branch(call("eq", var("remaining"), n.Lit(0)), var("result"),
                          call("loop", call("f", var("result")), call("dec", var("remaining")))),
                   (var("x"), var("n")), var("remaining"))
    filter_vector = n.Rec("scan", ("weights", "current"),
                          branch(call("eq", var("current"), var("tick")), var("weights"),
                                 call("scan", call("advance", var("weights"),
                                                   call("issued_at", var("trace"), var("current")),
                                                   call("frame_at", var("trace"), call("inc", var("current"))),
                                                   var("config")), call("inc", var("current")))),
                          (var("initial"), n.Lit(0)), call("remaining", var("tick"), var("current")))
    return [
        CombinatorSpec("chain", ("f", "g", "x"), ("f", "g"), chain).to_dict(),
        CombinatorSpec("fold", ("f", "initial", "items"), ("f",), fold).to_dict(),
        CombinatorSpec("trace_rec", ("f", "base", "v", "t"), ("f",), trace_rec).to_dict(),
        CombinatorSpec("repeat", ("f", "x", "n"), ("f",), repeat).to_dict(),
        CombinatorSpec("filter_vector", ("trace", "tick", "config", "initial"), (),
                       filter_vector, extra={
                           "decl": "comb @filter_vector[advance](trace,tick,config,initial) given",
                       }).to_dict(),
    ]


def build():
    objects = tuple(ObjectSpec(name, "given", sealed=name in ("State", "Trace"),
                               interface={"State": ("step",),
                                          "Trace": ("frame_at", "issued_at", "config_of")}.get(name, ()))
                    for name in ("State", "Trace", "PublicConfig", "Vec64", "Cells", "Credible",
                                 "Interval", "Fin64", "Fin80", "Fin100", "Fin8", "Action", "Text",
                                 "Rational", "List", "Tuple", "Bool", "Labels", "int", "any"))
    operations = tuple(OperationSpec(
        name, "act" if name == "step" else "transform",
        tuple(Edge(sort, name=f"arg{index}") for index, sort in enumerate(inputs)),
        Edge(output), f"Fixed public primitive: {name}", errors=("invalid",),
        impl={"host": HOST + name, "digest": host_digest(HOST + name)})
        for name, (inputs, output) in SIGNATURES.items())
    probes = [{"name": name, "sort": sort, "reads": "State", "reveals": [f"public {name}"],
               "impl": {"host": HOST + name, "digest": host_digest(HOST + name)}}
              for name, sort in (("frame", "Fin8"), ("issued", "Action"),
                                 ("prior", "Rational"), ("protocol", "Rational"),
                                 ("public_config", "PublicConfig"))]
    world = WorldDecl("obs_only", 1, "atoms-v2", {},
                      {"size": 64, "max_actions": 80, "routes": ["RRRR", "RRR", "RR", "R", "S"]},
                      objects, operations,
                      {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                       "library": combinators(), "recursion": "measure"},
                      {"truth": "State", "probes": probes,
                       "capabilities": {"learner": {"probes": [probe["name"] for probe in probes]}},
                       "show": {"input": "history", "result": "public"}, "judge_view": "sealed"},
                      {}, {"title": "Blind Corridor: Invent Observations Only"}, ("observation",))
    data = {**world.to_dict(), "source": {"design": "obs_only.json"}, "codec": {}}
    data = WorldFile.from_dict(data).to_dict()
    data["lock"] = compute_lock(WorldFile.from_dict(data))
    return data


def main():
    DECL_PATH.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
