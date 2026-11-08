"""World declarations and legacy adapter (docs/spec/atoms-v2.md, sections 12 and 13.1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from opulse.atoms import KINDS, LAYER0_KINDS
from opulse.atoms.nodes import NODE_NAMES

RECURSION_MODES = ("legacy", "measure", "fuel", "none")  # none: the world does not open Rec
BLOCK_ENDS = frozenset({"Jump", "CondJump", "Halt"})  # block terminators a world may list next to Blocks
from opulse.atoms.spec import Definition, Edge, ObjectSpec, OperationSpec, content_hash
from opulse.core.semantics import Semantics
from opulse.presets import PRESETS

DISPLAY_ONLY = frozenset({"title", "title_zh", "doc", "source", "symbol", "input_names"})
ALL_KINDS = frozenset(KINDS)  # the six kinds (spec 0.4)
# Default open kinds stay the four layer-0 kinds so declarations without open_kinds keep their hash;
# a world opens law and bridge explicitly.
DEFAULT_OPEN_KINDS = tuple(sorted(LAYER0_KINDS))


def _without_display(value):
    if isinstance(value, dict):
        return {name: item for name, item in value.items() if name not in DISPLAY_ONLY}
    return value


@dataclass(frozen=True)
class WorldDecl:
    world: str
    version: int
    dialect: str
    params: dict
    constants: dict
    objects: tuple[ObjectSpec, ...]
    operations: tuple[OperationSpec, ...]
    combinators: dict
    observation: dict
    lock: dict
    extra: dict = field(default_factory=dict)
    open_kinds: tuple[str, ...] = DEFAULT_OPEN_KINDS

    def __post_init__(self):
        if (not isinstance(self.open_kinds, (tuple, list, frozenset, set)) or
                any(not isinstance(kind, str) for kind in self.open_kinds) or
                not set(self.open_kinds) <= ALL_KINDS or len(self.open_kinds) != len(set(self.open_kinds))):
            raise ValueError("invalid open kinds")
        object.__setattr__(self, "open_kinds", tuple(sorted(self.open_kinds)))
        if self.dialect not in ("legacy-v1", "atoms-v2"):
            raise ValueError("invalid world dialect")
        if self.combinators.get("recursion") not in RECURSION_MODES:
            raise ValueError("invalid recursion mode")
        if self.combinators.get("recursion") == "none" and "Rec" in self.combinators.get("nodes", ()):
            raise ValueError("recursion none cannot open Rec")
        if not set(self.combinators.get("nodes", ())) <= set(NODE_NAMES) | BLOCK_ENDS:
            raise ValueError("invalid kernel node")

    def to_dict(self):
        return {**self.extra, "schema": "opulse.world/2", "world": self.world, "version": self.version,
                "dialect": self.dialect, "params": self.params, "constants": self.constants,
                "objects": [obj.to_dict() for obj in self.objects],
                "operations": [op.to_dict() for op in self.operations],
                "combinators": self.combinators, "observation": self.observation, "lock": self.lock,
                "open_kinds": list(self.open_kinds)}

    @classmethod
    def from_dict(cls, data):
        if data.get("schema") != "opulse.world/2":
            raise ValueError("invalid world schema")
        known = cls.__dataclass_fields__.keys() | {"schema"}
        extra = {name: value for name, value in data.items() if name not in known}
        return cls(data["world"], data["version"], data["dialect"], data["params"], data["constants"],
                   tuple(ObjectSpec.from_dict(obj) for obj in data["objects"]),
                   tuple(OperationSpec.from_dict(op) for op in data["operations"]),
                   data["combinators"], data["observation"], data["lock"], extra,
                   data.get("open_kinds", DEFAULT_OPEN_KINDS))

    def world_hash(self) -> str:
        data = self.to_dict()
        data["lock"] = {name: value for name, value in self.lock.items() if name != "world_hash"}
        data = _without_display(data)
        for kind in ("objects", "operations"):
            data[kind] = [_without_display(record) for record in data[kind]]
        observation = dict(data["observation"])
        observation["probes"] = [_without_display(record) for record in observation.get("probes", ())]
        data["observation"] = observation
        return content_hash(data)

    def opened_nodes(self) -> frozenset[str]:
        return frozenset(self.combinators["nodes"])


@dataclass(frozen=True)
class DerivedWorld:
    extends: str
    promoted: tuple[Definition, ...]
    open_kinds: tuple[str, ...] = DEFAULT_OPEN_KINDS

    def __post_init__(self):
        for definition in self.promoted:
            if definition.status != "promoted" or definition.evidence is None:
                raise ValueError(f"definition {definition.name} is not promoted")

    @classmethod
    def build(cls, base: WorldDecl, promoted: tuple[Definition, ...]) -> DerivedWorld:
        for definition in promoted:
            if definition.evidence is None or definition.evidence.world_hash != base.world_hash() or definition.validate():
                raise ValueError(f"definition {definition.name} is not promoted for this world")
        return cls(f"{base.world}@{base.version}", promoted, base.open_kinds)

    def scopes(self) -> dict:
        return {definition.name: definition.evidence.scope for definition in self.promoted}

    def to_dict(self):
        return {"extends": self.extends, "promoted": [definition.to_dict() for definition in self.promoted],
                "open_kinds": list(self.open_kinds)}


def legacy_world_decl(world_json: dict) -> WorldDecl:
    """Describe the published layer-0 atoms without changing their legacy semantics."""
    name = world_json["world"]
    atoms = world_json["atoms"]
    sorts = sorted({param["type"] for atom in atoms for param in atom["params"]} |
                   {atom["result_type"] for atom in atoms})
    objects = tuple(ObjectSpec(sort, "given") for sort in sorts)
    settings = world_json.get("settings", [])
    settings_values = ({item["key"]: item["value"] for item in settings}
                       if isinstance(settings, list) else settings)
    preset = settings_values.get("preset", name)
    preset_settings = PRESETS.get(preset, {}).get("settings", {})
    semantics_settings = {**preset_settings.get("semantics", {}),
                          **settings_values.get("semantics", {}),
                          **{key.removeprefix("semantics."): value for key, value in settings_values.items()
                             if key.startswith("semantics.")}}
    semantics = Semantics(**semantics_settings)
    enter = {"exact": "bottom", "legacy": "fold(legacy)", "modular": "normalize"}[semantics.mode]
    operations = []
    for atom in atoms:
        inputs = tuple(Edge(param["type"]) for param in atom["params"])
        result = atom["result_type"]
        role = ("act" if name == "action" and result == "state" else
                "decide" if result == "bool" else "combine" if len(inputs) > 1 else "transform")
        operations.append(OperationSpec(atom["name"], role, inputs, Edge(result, enter),
                                        atom.get("rule") or atom.get("plain") or atom["name"],
                                        extra={"symbol": atom.get("symbol"),
                                               "input_names": [param["name"] for param in atom["params"]]}))
    observation = {"truth": None, "probes": [], "capabilities": {}, "show": {}, "judge_view": "full_state"}
    library = []
    if name == "action":
        from opulse.worlds.action import OBS_RULES

        observation.update(truth="state", probes=[{"name": probe, "sort": result,
                                                     "reveals": [description[1]]}
                                                    for probe, description in OBS_RULES.items()
                                                    for result in (next(atom["result_type"] for atom in atoms
                                                                   if atom["name"] == probe),)],
                           show={"input": "full_state", "result": "full_state"})
        library.append("repeat_until")
    return WorldDecl(name, 1, "legacy-v1", {"settings": settings,
                                            "semantics": {"mode": semantics.mode, "bound": semantics.bound,
                                                          "modulus": semantics.modulus}},
                     {"domain": world_json.get("domain", [])}, objects, tuple(operations),
                     {"nodes": list(NODE_NAMES[:3]) + ["Case", "Rec"], "library": library,
                      "recursion": "legacy"}, observation,
                     {"legacy_atoms": [{"name": atom["name"], "arity": atom.get("arity"),
                                        "params": [param["type"] for param in atom["params"]],
                                        "plain": atom.get("plain")}
                                       for atom in atoms]}, open_kinds=("operation",))
