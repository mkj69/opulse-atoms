"""Rebuild six legacy world declarations (atoms-v2 specification sections 4-7, 13)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from opulse.tasks_v2.decl import WorldFile, compute_lock, host_digest

ROOT = Path(__file__).resolve().parents[1]
WORLDS = ("lists", "perm", "rel", "grid", "pitch", "action")
BASE = {"add", "sub", "mod", "neg"}
ERRORS = {
    "mod": ["div_zero"],
    "list_head": ["empty"], "list_at": ["invalid"],
    "swap": ["invalid"], "perm_compose": ["invalid"], "perm_apply": ["invalid"],
    "rel_parent": ["missing"], "rel_colleague": ["missing"],
    "rel_neighbour": ["missing"],
    "grid_recolour": ["invalid"], "grid_overlay": ["shape"],
    "grid_count": ["invalid"], "grid_fill": ["invalid"],
    "pitch_transpose": ["invalid"], "pitch_octave_up": ["invalid"],
    "pitch_octave_down": ["invalid"], "pitch_invert": ["invalid"],
    "pitch_scale_step": ["invalid"], "pitch_major_triad": ["invalid"],
    "pitch_minor_triad": ["invalid"], "pitch_repeat": ["invalid"],
    "forward": ["blocked"], "pick": ["blocked"], "place": ["blocked"],
    "craft": ["blocked"], "front_colour": ["invalid"],
    "held_colour": ["invalid"], "front_height": ["invalid"],
}
REPRESENTATIONS = {
    "int": ("Python int", "opulse.core.semantics:Semantics.operations"),
    "str": ("Python str", "opulse.core.types:matches"),
    "bool": ("Python bool", "opulse.core.types:matches"),
    "list[int]": ("tuple[int, ...]", "opulse.core.types:matches"),
    "perm[n]": ("Permutation", "opulse.worlds.perm:Permutation"),
    "person": ("Python str", "opulse.worlds.rel:load_table"),
    "colour": ("Python int", "opulse.worlds.grid:valid_grid"),
    "grid": ("tuple[tuple[int, ...], ...]", "opulse.worlds.grid:grid"),
    "note": ("Python int", "opulse.worlds.pitch:_note"),
    "melody": ("tuple[tuple[int, int], ...]", "opulse.worlds.pitch:_melody"),
    "robot_state": ("State", "opulse.worlds.action:State.from_dict"),
    "direction": ("Direction", "opulse.worlds.action:Direction"),
    "item": ("Python str or None", "opulse.worlds.action:State.to_dict"),
    "skill": ("Skill", "opulse.worlds.action:Skill.from_record"),
}


def legacy_tags(world: str) -> dict[str, str]:
    published = ROOT / "docs/assets/data/worlds"
    paths = [published / f"{world}.json", *sorted((published / world).rglob("*.json"))]
    tags: set[str] = set()

    def scan(value: object) -> None:
        if isinstance(value, dict):
            if "t" in value:
                tags.add(value["t"])
            for child in value.values():
                scan(child)
        elif isinstance(value, list):
            for child in value:
                scan(child)

    for path in paths:
        scan(json.loads(path.read_text(encoding="utf-8")))
    special = {"list": "list[int]", "perm": "perm[n]", "entity": "person",
               "state": "robot_state", "nan": "Bottom"}
    return {tag: special.get(tag, "colour" if tag == "colour" and world == "action" else tag)
            for tag in sorted(tags)}


def object_spec(name: str, *, base: str | None = None, valid: str | None = None,
                sealed: bool = False, interface: list[str] | None = None,
                params: list[str] | None = None,
                doc: str = "A given legacy world value.") -> dict:
    representation, codec = REPRESENTATIONS[name]
    return {"kind": "object", "name": name, "form": "refine" if base else "given",
            "base": base, "tags": None, "group": [],
            "valid": {"host": valid, "digest": host_digest(valid)} if valid else None,
            "canon": None, "sealed": sealed, "interface": interface or [], "params": params or [],
            "equality": "canonical", "canon_cost": "counted", "body": None,
            "host": {"repr": representation, "codec": codec}, "doc": doc}


def objects(world: str) -> list[dict]:
    common = [object_spec("int"), object_spec("bool")]
    if world == "lists":
        return common + [object_spec("list[int]", doc="An immutable sequence of integers, possibly empty.")]
    if world == "perm":
        return common + [object_spec("perm[n]", params=["n:int"],
                                     doc="A permutation of n cards, represented by destination positions.")]
    if world == "rel":
        return common + [object_spec("str"), object_spec("person", base="str", valid="opulse.tasks_v2.hosts:valid_person",
                                     doc="A name belonging to constants.names in this version's relation table.")]
    if world == "grid":
        return common + [object_spec("colour", base="int", valid="opulse.tasks_v2.hosts:valid_colour",
                                     doc="A palette integer from 0 through 9."),
                         object_spec("grid", valid="opulse.worlds.grid:valid_grid",
                                     doc="A rectangular grid of colours with 1 to 10 rows and columns.")]
    if world == "pitch":
        return common + [object_spec("note", base="int", valid="opulse.tasks_v2.hosts:valid_note",
                                     doc="A MIDI pitch from 0 through 127."),
                         object_spec("melody", doc="An ordered sequence of MIDI pitches and positive beat durations.")]
    return common + [object_spec("robot_state", sealed=True,
                                 interface=["forward", "turn_left", "turn_right", "pick", "place", "craft",
                                            "front_wall", "front_water", "front_colour", "holding",
                                            "held_colour", "front_height"],
                                 doc="The full map, blocks, tools, bridges, and robot state."),
                     object_spec("direction", doc="One of N, E, S, or W."),
                     object_spec("colour", doc="One of R, B, Y, G, P, or O.") |
                     {"host": {"repr": "Colour", "codec": "opulse.worlds.action:Colour"}},
                     object_spec("item", doc="An optional block colour or bridge kit."),
                     object_spec("skill", doc="A published legacy robot skill record.")]


def declaration(world: str) -> dict:
    path = f"docs/assets/data/worlds/{world}.json"
    published = json.loads((ROOT / path).read_text(encoding="utf-8"))
    settings = {entry["key"]: entry["value"] for entry in published["settings"]}
    params = {key: value for key, value in settings.items() if key != "preset"}
    if world != "action":
        params.update({"integer_mode": "exact", "integer_bound": 2147483647})
    if world == "perm":
        params["n"] = settings["cards"]
    if world == "pitch":
        params.update({"key": "C", "scale": "major"})
    params.update({"width": 8, "height": 8, "max_height": 4} if world == "action" else {})
    constants = {"names": published["context"]["entities"],
                 "relations": published["context"]["relations"]} if world == "rel" else {}
    if world == "pitch":
        constants = {"key": "C", "scale": "major"}
    if world == "action":
        constants = {"colours": ["R", "B", "Y", "G", "P", "O"],
                     "directions": ["N", "E", "S", "W"]}
    from opulse.core.presets import register_preset
    from opulse.core.primitives import CUSTOM
    from opulse.core.semantics import Semantics
    if world == "action":
        from opulse.worlds.action import register_action_atoms
        register_action_atoms()
    else:
        register_preset(world)
    base_functions = Semantics().operations()
    operations = []
    for atom in published["atoms"]:
        name = atom["name"]
        function = base_functions[name] if name in BASE else CUSTOM[name].compute
        if name in BASE:
            host = "opulse.core.semantics:Semantics.operations"
        elif inspect.isbuiltin(function):
            host = "opulse.core.presets:register_preset"
        else:
            qualname = function.__qualname__.split(".<locals>.", 1)[0]
            host = f"{function.__module__}:{qualname}"
        def sort(value: str) -> str:
            return {"str": "person", "state": "robot_state", "perm[5]": "perm[n]",
                    }.get(value, value) if world in ("rel", "action", "perm") else value
        output = sort(atom["result_type"])
        role = ("act" if world == "action" and output == "robot_state" else
                "decide" if output == "bool" or world == "action" and name in (
                    "front_colour", "held_colour", "front_height") else
                "transform" if world == "rel" and name.startswith("rel_") else
                "combine" if atom["arity"] == 2 else "transform")
        inputs = [{"name": param["name"], "sort": sort(param["type"]),
                   "enter": "fold(make_note)" if world == "pitch" and param["type"] == "note"
                   else "bottom"} for param in atom["params"]]
        errors = list(ERRORS.get(name, []))
        if name in BASE or output == "int" and world != "action":
            errors.append("overflow")
        if (world == "pitch" and any(param["sort"] == "note" for param in inputs)
                and "invalid" not in errors):
            errors.append("invalid")
        operations.append({"kind": "operation", "name": name, "symbol": atom["symbol"],
                           "role": role, "inputs": inputs,
                           "output": {"sort": output, "enter": "bottom"},
                           "rule": atom["rule"], "errors": errors,
                           "impl": {"host": host, "digest": host_digest(host)},
                           "cost": 1, "strict": True,
                           "reads_params": ["key", "scale"] if name == "pitch_scale_step" else
                           ["n"] if world == "perm" and name == "swap" else []})
    probes = ([{"name": op["name"], "sort": op["output"]["sort"],
                "reads": "robot_state", "reveals": [op["rule"]], "impl": op["impl"]}
               for op in operations if op["name"] in (
                   "front_wall", "front_water", "front_colour", "holding", "held_colour", "front_height")]
              if world == "action" else [])
    library = ["repeat_until"] if world == "action" else (["search"] if
        any("search" in str(operator.get("definition", "")).lower() for operator in published["operators"])
        else [])
    combinators = {"nodes": ["Var", "Lit", "Call", "Case", "Rec"],
                   "library": library, "recursion": "legacy"}
    if world == "action":
        combinators["nodes"] = ["Var", "Lit", "Call", "Case", "Rec"]
        combinators["notes"] = ("Legacy repeat_until(body, stop, max) checks stop before each body; "
                                "max=0 returns the input; after max iterations return the last state "
                                "without checking stop again. An illegal forward is Bottom(blocked).")
    observation = {"truth": "robot_state" if world == "action" else None,
                   "probes": probes,
                   "capabilities": {"learner": {"channels": ["results", "errors", "renders", "traces", "steps", "memory"],
                                                "probes": "all"}},
                   "show": {"input": "full_state", "result": "full_state"} if world == "action" else
                   {"input": "values", "result": "value"}, "judge_view": "full_state"}
    aliases = ({"swap": "The packed int pair is first * n + second, with n=5."} if world == "perm"
               else {"grid_recolour": "The packed int code is source * 10 + target (0..99)."}
               if world == "grid" else {})
    data = {"schema": "opulse.world/2", "world": world, "version": 1,
            "dialect": "legacy-v1", "title": published["title"],
            "source": {"published": path, "settings": settings}, "params": params,
            "constants": constants, "objects": objects(world), "operations": operations,
            "combinators": combinators, "observation": observation,
            "codec": {"legacy_tags": legacy_tags(world), "aliases": aliases}}
    data["lock"] = compute_lock(WorldFile.from_dict({**data, "lock": {}}))
    return data


if __name__ == "__main__":
    for world_name in WORLDS:
        output = ROOT / f"worlds/decl/{world_name}@1.json"
        output.write_text(json.dumps(declaration(world_name), ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(output.relative_to(ROOT))
