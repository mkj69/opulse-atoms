"""Generate the explicit layer-zero declaration (before locking it)."""

import json
from pathlib import Path

from opulse.tasks_v2.decl import host_digest

from . import hosts

PATH = Path(__file__).resolve().parents[4] / "worlds/decl/v2/dice@1.json"
PREFIX = "opulse.worlds_v2.dice.hosts:"


def reference(name):
    host = PREFIX + name
    return {"host": host, "digest": host_digest(host)}


def object_spec(name, doc, **extra):
    return {"kind": "object", "name": name, "form": extra.pop("form", "given"),
            "base": extra.pop("base", None), "tags": extra.pop("tags", None), "group": [],
            "valid": extra.pop("valid", None), "canon": extra.pop("canon", None),
            "sealed": extra.pop("sealed", False), "interface": extra.pop("interface", []),
            "params": extra.pop("params", []), "equality": "canonical", "canon_cost": "counted",
            "body": None, "host": None, "doc": doc, **extra}


def operation(name, inputs, output, role="transform", errors=("invalid",)):
    return {"kind": "operation", "name": name, "symbol": f"{name}({','.join(inputs)})",
            "role": role, "inputs": [{"name": f"arg{index}", "sort": sort, "enter": "bottom"}
                                      for index, sort in enumerate(inputs)],
            "output": {"sort": output, "enter": "bottom"}, "rule": RULES.get(name, "Generic constructor, accessor, finite-list or exact-arithmetic primitive."),
            "errors": list(errors), "impl": reference(name), "cost": 1, "strict": True, "reads_params": []}


RULES = {
    "roll": "Normalize the six positive integer die weights, without sampling.",
    "pure": "One-point probability distribution for any hashable value.",
    "jump": "Move -1 for 2..6, +1 for 7..9, +2 for 10..12; clip to 0..goal.",
    "mass": "Sum exact rational mass selected by an event range or finite set.",
}


def build():
    from .story import bind_spec

    objects = [object_spec("int", "Integer and bounded natural positions."),
               object_spec("bool", "Truth value."),
               object_spec("value", "Generic finite constructor/accessor value."),
               object_spec("fraction", "Canonical rational.", form="compose", tags={"rational": {"num": "int", "den": "int"}}),
               object_spec("die", "Six strictly positive integer face weights."),
               object_spec("Fair", "Named fair six-faced die, weights 1,1,1,1,1,1."),
               object_spec("Tilt", "Named tilted six-faced die, weights 1,1,1,1,2,6."),
               object_spec("dist", "Finite canonical normalized rational distribution.", sealed=True, interface=["roll", "pure", "mass", "entries", "make_dist"]),
               object_spec("state", "Position and persistent hidden die index 0 or 1.", form="compose", tags={"position_die": {"position": "int", "die": "int"}}),
               object_spec("weighted", "Generic weighted entry.", form="compose", tags={"entry": {"value": "value", "num": "int", "den": "int"}})]
    signatures = [
        ("roll", ["die"], "dist"), ("pure", ["value"], "dist"),
        ("jump", ["int", "int", "int"], "int"), ("mass", ["dist", "value"], "fraction"),
        ("entries", ["dist"], "value"), ("item", ["weighted"], "value"),
        ("weight", ["weighted"], "fraction"), ("field", ["value", "int"], "value"),
        ("pair", ["value", "value"], "value"), ("state", ["int", "int"], "state"),
        ("die", ["int"] * 6, "die"), ("event", ["int", "int"], "value"),
        ("belief", ["fraction", "fraction"], "value"), ("walk", ["value", "int"], "value"),
        ("make_entry", ["value", "fraction"], "weighted"), ("make_dist", ["value"], "dist"),
        ("multiply", ["fraction", "fraction"], "fraction"),
        ("add", ["fraction", "fraction"], "fraction"),
        ("divide", ["fraction", "fraction"], "fraction"),
        ("subtract", ["fraction", "fraction"], "fraction"),
        ("nth", ["value", "int"], "value"),
        ("replace_at", ["value", "int", "value"], "value"),
        ("int_add", ["int", "int"], "int"), ("int_sub", ["int", "int"], "int"),
        ("int_mul_fraction", ["int", "fraction"], "fraction"),
        ("equal", ["value", "value"], "bool"), ("less_equal", ["int", "int"], "bool"),
        ("is_empty", ["value"], "bool"), ("head", ["value"], "value"),
        ("tail", ["value"], "value"), ("cons", ["value", "value"], "value"),
        ("length", ["value"], "int"), ("intersect", ["value", "value"], "value")]
    operations = [operation(name, inputs, output, "decide" if name in ("mass", "equal", "less_equal") else "transform",
                            ("invalid", "domain") if name in ("jump", "divide", "event", "belief", "walk", "state") else ("invalid",))
                  for name, inputs, output in signatures]
    observation = {"truth": "dist", "probes": [{"name": "mass", "sort": "fraction", "reads": "dist", "reveals": ["event_mass"], "impl": reference("mass")}],
                   "capabilities": {"learner": {"channels": ["results", "errors", "renders", "traces", "steps"], "probes": "all"}},
                   "show": {"input": "distribution", "result": "fraction"}, "judge_view": "full_state"}
    return {"schema": "opulse.world/2", "world": "dice", "version": 1, "dialect": "atoms-v2", "title": "Hidden Dice and Absorbing Walk", "source": {"title_zh": "暗骰与吸收游走"},
            "params": {}, "constants": {"Fair": {"weights": list(hosts.FAIR.fields)}, "Tilt": {"weights": list(hosts.TILT.fields)}},
            "objects": objects, "operations": operations, "combinators": {"nodes": ["Var", "Lit", "Call", "Let", "Case", "Rec"], "library": [bind_spec().to_dict()], "recursion": "measure"},
            "observation": observation, "codec": {}, "lock": {}}


if __name__ == "__main__":
    PATH.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
