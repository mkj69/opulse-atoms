"""Read-only adapters for the twelve published legacy-v1 worlds."""

import json
from collections import defaultdict
from dataclasses import replace

from opulse.atoms.golden import DEFAULT_ROOT, WORLDS, CurrentEngine, decode
from opulse.atoms.legacy import scope_from_registry, scope_from_skills
from opulse.atoms.world import legacy_world_decl
from opulse.gen_v2.worlds._common import build, world_tags

# Binary legacy counters require a literal step, not a unary GenWorld measure.
# Each entry is (binary_step, literal_argument, base_test); a missing base_test
# means legacy's implicit integer-zero check. The generator lead can move these
# hints into GenWorld when it supports binary counter templates.
COUNTERS = {
    "integer": {"int": [("sub", 1, None)]},
    "clock": {"int": [("sub", 1, None)]},
    "bits": {"int": [("shift_right", 1, None)]},
    "strings": {"int": [("sub", 1, None)]},
    "lists": {"int": [("sub", 1, None)]},
    "logic": {"int": [("sub", 1, None)]},
    "perm": {"int": [("sub", 1, None)]},
    "rel": {"int": [("sub", 1, None)]},
    "grid": {"int": [("sub", 1, None)]},
    "pitch": {"int": [("sub", 1, None)]},
}

TAGS = {name: {**world_tags(name), "open_kinds": ["operation"],
               "star_kind": "operation"} for name in WORLDS}


def _robot_states():
    from opulse.worlds.action import COLOURS, DIRECTIONS, VECTORS, Direction, State

    result = []
    for facing in DIRECTIONS:
        dx, dy = VECTORS[facing]
        front = (1 + dx, 1 + dy)
        index = front[1] * 3 + front[0]
        right = (1 - dy, 1 + dx)
        right_index = right[1] * 3 + right[0]
        for situation_index, situation in enumerate(("wall", "water", "blocks", "floor")):
            for height in range(4):
                terrain = [list("...") for _ in range(3)]
                if situation == "wall":
                    terrain[front[1]][front[0]] = "#"
                elif situation == "water":
                    terrain[front[1]][front[0]] = "~"
                stacks = [()] * 9
                if situation == "blocks":
                    stacks[index] = (COLOURS[height],) * height
                stacks[right_index] = (COLOURS[(height + 1) % len(COLOURS)],) * height
                held = COLOURS[(height + situation_index) % len(COLOURS)] if height % 2 else None
                result.append(State(3, 3, 4, tuple("".join(row) for row in terrain),
                                    tuple(stacks), ("",) * 9, (), (1, 1),
                                    Direction(facing), held))
    return result


def _published_values(data):
    values = defaultdict(list)
    for row in (*data["atoms"], *data["operators"]):
        examples = (row.get("example"),) if row in data["atoms"] else row.get("examples", ())
        for example in examples:
            if not example:
                continue
            for item in example["inputs"]:
                values[{"perm": "perm[5]", "entity": "str", "list": "list[int]"}.get(item["t"], item["t"])].append(decode(item))
    values["int"].extend(range(12) if data["world"] == "clock" else range(9))
    values["bool"].extend((False, True))
    if data["world"] == "action":
        from opulse.worlds.action import COLOURS, Colour

        values["colour"].extend(Colour(colour) for colour in COLOURS)
    return values


def gen_world(name):
    """Load layer-zero primitive implementations, never regenerated operators."""
    if name not in WORLDS:
        raise ValueError(f"unknown classic world {name!r}")
    data = json.loads((DEFAULT_ROOT / f"{name}.json").read_text(encoding="utf-8"))
    original = legacy_world_decl(data)
    decl = replace(original, open_kinds=("operation",), extra={**original.extra, "open_kinds": ["operation"]})
    if name == "action":
        scope, _ = scope_from_skills({})
        atoms = [scope.atoms[op.name] for op in decl.operations]
        values = _published_values(data)
        states = _robot_states()
        values["state"] = states
        world = build(name, decl, atoms, values, truth_states=states,
                      max_scope=100, max_steps=250)
        world.sorts["state"].values = tuple(states[16 * direction + offset]
                                             for direction in range(4)
                                             for offset in (0, 1, 6, 7, 8, 9, 10, 11))
        return world

    state = CurrentEngine().load_published(data)
    tools = state.tools
    scope, _ = scope_from_registry(tools.registry, tools.settings.semantics.build(), tools.oracle.parser)
    primitive = {op.primitive_name: scope.atoms[op.func_id]
                 for op in tools.registry if op.definition is None and op.primitive_name}
    atoms = [replace(primitive[op.name], name=op.name) for op in decl.operations]
    measures = {"list[int]": [("list_tail", "list_length")]} if name == "lists" else {}
    world = build(name, decl, atoms, _published_values(data), measures=measures,
                  max_scope=120, max_steps=250)
    world.counters = {sort: list(steps) for sort, steps in COUNTERS.get(name, {}).items()}
    return world
