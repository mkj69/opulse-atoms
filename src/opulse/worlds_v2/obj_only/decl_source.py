"""Produce the locked layer-zero declaration for the object-only world."""

import json

from opulse.atoms import nodes
from opulse.atoms.spec import Edge, ObjectSpec, OperationSpec
from opulse.tasks_v2.decl import WorldFile, compute_lock, host_digest

from .given_combinators import specifications
from .world import DECL_PATH

HOSTS = "opulse.worlds_v2.obj_only.hosts:"
PRIMITIVES = {
    "add": (("int", "int"), "int", "add"),
    "sub": (("int", "int"), "int", "sub"),
    "mul": (("int", "int"), "int", "mul"),
    "neg": (("int",), "int", "neg"),
    "gcd": (("int", "int"), "int", "integer_gcd"),
    "div_exact": (("int", "int"), "int", "div_exact"),
    "pow": (("int", "int"), "int", "power"),
    "binom": (("int", "int"), "int", "binom"),
    "lt": (("int", "int"), "bool", "lt"),
    "eq": (("raw", "raw"), "bool", "eq"),
    "is_empty": (("list",), "bool", "is_empty"),
    "head": (("list",), "raw", "head"),
    "tail": (("list",), "list", "tail"),
    "list_length": (("list",), "int", "list_length"),
    "cons": (("raw", "list"), "list", "cons"),
    "bounded_count": (("int",), "bool", "bounded_count"),
    "sort": (("list",), "list", "sort"),
    "read": (("unknown", "str"), "unknown", "read"),
    "make_record": (("str", "str", "list"), "raw", "make_record"),
    "field": (("unknown", "int"), "unknown", "field"),
    "tag": (("unknown",), "str", "tag"),
    "field_count": (("unknown",), "int", "field_count"),
    "rat_parse": (("unknown",), "pair", "rat_parse"),
    "rat_format": (("pair",), "str", "rat_format"),
    "rat_add": (("pair", "pair"), "pair", "rat_add"),
    "rat_mul": (("pair", "pair"), "pair", "rat_mul"),
    "rat_div": (("pair", "pair"), "pair", "rat_div"),
    "rat_pow": (("pair", "int"), "pair", "rat_pow"),
    "rat_lt": (("pair", "pair"), "bool", "rat_lt"),
    "rat_eq": (("pair", "pair"), "bool", "rat_eq"),
    "is_ok": (("unknown",), "bool", "is_ok"),
}


def build():
    operations = []
    for name, (inputs, output, host) in PRIMITIVES.items():
        operations.append(OperationSpec(name, "transform", tuple(Edge(sort, name=f"arg{index}")
                                               for index, sort in enumerate(inputs)), Edge(output),
                                        "Validate and normalize a public finite object representation.",
                                        impl={"host": HOSTS + host, "digest": host_digest(HOSTS + host)}).to_dict())
    data = {
        "schema": "opulse.world/2", "world": "obj_only", "version": 1, "dialect": "atoms-v2",
        "title": "Exact polynomial root atlases from sealed representations",
        "source": {"title_zh": "表示锻造所：精确多项式根地图"},
        "params": {}, "constants": {"max_degree": 256, "max_subdivision_depth": 20},
        "objects": [ObjectSpec(name, "given", extra={"doc": description}).to_dict() for name, description in
                    (("int", "Signed exact integer"), ("bool", "Boolean"),
                     ("str", "Public exact rational spelling"), ("raw", "Finite public certificate tree"),
                     ("list", "Finite sequence"), ("pair", "Finite pair"),
                     ("unknown", "Opaque public value"))],
        "operations": operations,
        "combinators": {"nodes": list(nodes.NODE_NAMES), "recursion": "measure",
                        "library": [item.to_dict() for item in specifications()]},
        "observation": {"truth": "unknown", "probes": [
            {"name": name, "sort": output, "reads": "unknown", "reveals": [name],
             "impl": {"host": HOSTS + name, "digest": host_digest(HOSTS + name)}}
            for name, output in (("value", "str"), ("accepted", "bool"))],
                        "capabilities": {}, "show": {},
                        "judge_view": "full_state"},
        "codec": {}, "open_kinds": ["object"], "lock": {},
    }
    data["lock"] = compute_lock(WorldFile.from_dict(data))
    return data


def main():
    DECL_PATH.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
