"""Generate the locked depth declaration from its layer-zero interfaces."""

import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/kitchen@1.json"
HOST = "opulse.worlds_v2.kitchen.depth_hosts:"


def build():
    from .depth_story import seq_spec

    def obj(name, description):
        return {"kind": "object", "name": name, "form": "given", "base": None,
                "tags": None, "group": [], "valid": None, "canon": None,
                "sealed": False, "interface": [], "params": [],
                "equality": "canonical", "canon_cost": "counted", "body": None,
                "host": None, "doc": description}

    def edge(sort, name=None):
        return {"sort": sort, "enter": "bottom", **({"name": name} if name else {})}

    def op(name, arguments, output, rule, errors=(), role="transform"):
        return {"kind": "operation", "name": name, "symbol": name, "role": role,
                "inputs": [edge(sort, arg) for arg, sort in arguments],
                "output": edge(output), "rule": rule, "errors": list(errors),
                "impl": {"host": HOST + name, "digest": ""}, "cost": 1,
                "strict": True, "reads_params": []}

    objects = [obj(name, description) for name, description in (
        ("int", "Integral quantities and clock ticks."), ("str", "Item and station identifiers."),
        ("bool", "Boolean tests."), ("List", "Immutable ordered sequences."),
        ("Lot", "Item, birth time, and positive quantity."),
        ("Job", "Recipe and future finish time on one station."),
        ("State", "Clock, ten dated item lots, and in-flight jobs; raw inputs are 0..8."),
        ("Query", "An initial state paired with an order."),
        ("Recipe", "One of six fixed station-bound recipes."))]
    operations = [op("state", ((name, "int") for name in ("flour", "water", "egg", "milk")),
                     "State", "Construct a four-raw-material initial state within 0..8.", ("invalid",), "combine")]
    for name, rule in (
        ("mix", "Start mixer for two ticks, consuming two flour and one water."),
        ("whisk", "Start mixer for one tick, consuming flour, egg, and milk."),
        ("bake_bread", "Start oven for three ticks, consuming fresh dough."),
        ("bake_cake", "Start oven for two ticks, consuming fresh batter."),
        ("simmer", "Start hob for two ticks, consuming egg and milk."),
        ("plate", "Start bench for one tick, consuming cake and fresh custard.")):
        operations.append(op(name, (("state", "State"),), "State", rule,
                             ("invalid", "stock", "station"), "act"))
    operations.append(op("tick", (("state", "State"),), "State",
                         "Advance one tick, completing jobs and discarding expired lots.",
                         ("invalid", "horizon"), "act"))
    primitives = (
        ("empty", (("items", "List"),), "bool", "Test whether a sequence is empty."),
        ("head", (("items", "List"),), "str", "Get the first element of a nonempty sequence."),
        ("tail", (("items", "List"),), "List", "Get all but the first element."),
        ("cons", (("item", "Lot"), ("items", "List")), "List", "Prepend an element."),
        ("append", (("items", "List"), ("item", "Lot")), "List", "Append an element."),
        ("length", (("items", "List"),), "int", "Count sequence elements."),
        ("item", (("items", "List"), ("index", "int")), "Lot", "Index into a sequence."),
        ("field", (("value", "Lot"), ("index", "int")), "Lot", "Read a declared object's field."),
        ("eq", (("left", "str"), ("right", "str")), "bool", "Compare structural values."),
        ("lt", (("left", "int"), ("right", "int")), "bool", "Compare integers."),
        ("le", (("left", "int"), ("right", "int")), "bool", "Compare integers inclusively."),
        ("add", (("left", "int"), ("right", "int")), "int", "Add two integers."),
        ("sub", (("left", "int"), ("right", "int")), "int", "Subtract two integers."),
        ("mul", (("left", "int"), ("right", "int")), "int", "Multiply two integers."),
        ("seq_pair", (("left", "Lot"), ("right", "Lot")), "List", "Construct an ordered pair."),
        ("seq_triple", (("a", "Lot"), ("b", "Lot"), ("c", "Lot")), "List", "Construct an ordered triple."),
        ("query", (("state", "State"), ("order", "Lot")), "Query", "Pair a state and an order."),
        ("increasing", (("items", "List"),), "bool", "Check that sequence elements are strictly increasing."),
    )
    operations.extend(op(name, args, output, rule, ("invalid",)) for name, args, output, rule in primitives)
    optional = op("optional", (("outcome", "Lot"),), "List",
                  "Convert an Ok result to a singleton sequence and a Bottom result to empty.")
    optional["strict"] = False
    operations.append(optional)
    probes = [{"name": name, "sort": "List", "reads": "State", "reveals": [reveal],
               "impl": {"host": HOST + name, "digest": ""}}
              for name, reveal in (("stock", "ten public item totals"), ("busy", "occupied stations"))]
    return {"schema": "opulse.world/2", "world": "kitchen", "version": 1,
            "dialect": "atoms-v2", "title": "Timed Kitchen and Verifiable Schedules",
            "source": {"catalogue": "worlds/catalogue/depth/kitchen.json",
                       "title_zh": "限时厨房与可证排程"},
            "params": {"raw_max": 8, "deadline_max": 12, "items": 10, "stations": 4},
            "constants": {}, "objects": objects, "operations": operations,
            "combinators": {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"],
                            "library": [{**seq_spec().to_dict(),
                                         "title": "Strict recipe sequence",
                                         "definition": "Execute named starts in order, stopping on the first failure."}],
                            "recursion": "measure"},
            "observation": {"truth": "State", "probes": probes,
                            "capabilities": {"learner": {"probes": ["stock", "busy"]},
                                             "judge": {"probes": "all"}},
                            "show": "stock and busy only",
                            "judge_view": "complete dated lots and in-flight jobs"},
            "codec": {"name": "opulse.value/2", "host": HOST + "to_card"}, "lock": {}}


if __name__ == "__main__":
    PATH.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
