"""Task records (docs/spec/atoms-v2.md, sections 3, 7, 10 and 12).

Operation answer shapes: compute=value; invert=one_witness|all_solutions;
decide=verdict; describe=choice; induce=definition; create=definition.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

KINDS = ("object", "operation", "combinator", "observation", "law", "bridge")  # six kinds (common.md)
ANGLES = ("compute", "invert", "decide", "describe", "induce", "create")
SHAPES = {
    "compute": ("value",), "invert": ("one_witness", "all_solutions"),
    "decide": ("verdict",), "describe": ("choice",),
    "induce": ("definition",), "create": ("definition",),
}
METHODS = {"value": "exact_value", "one_witness": "witness",
           "all_solutions": "solution_set", "verdict": "verdict",
           "definition": "definition", "choice": "choice"}
CHANNELS = ("results", "errors", "renders", "traces", "steps", "memory")


def default_boundary() -> dict:
    return {"depth": None, "open_names": [], "keep_names": [], "open_paths": [],
            "kinds": list(KINDS)}


def default_observation() -> dict:
    return {"show": {"input": "values", "result": "value"}, "channels": list(CHANNELS)}


@dataclass(frozen=True)
class Task:
    id: str
    world: str
    angle: str
    kind: str
    family: str
    variant: str | None
    boundary: dict
    observation: dict
    answer_shape: str
    judge_view: str | dict
    question: dict
    prompt: dict
    reference: dict
    grader: dict
    source: dict
    schema: str = "opulse.task/2"
    modality: str = "text"
    open_kinds: list[str] = field(default_factory=lambda: list(KINDS))
    tags: dict | None = None

    def __post_init__(self) -> None:
        if self.schema != "opulse.task/2":
            raise ValueError("unknown task schema")
        if not all(isinstance(item, str) and item for item in (self.id, self.world, self.family)):
            raise ValueError("id, world and family are required")
        if self.angle not in ANGLES or self.kind not in KINDS:
            raise ValueError("illegal angle or kind")
        if self.modality not in ("text", "image", "audio"):
            raise ValueError("illegal modality")
        if (not isinstance(self.open_kinds, list) or len(set(map(repr, self.open_kinds))) != len(self.open_kinds)
                or any(kind not in KINDS for kind in self.open_kinds) or self.kind not in self.open_kinds):
            raise ValueError("invalid open kinds")
        if self.tags is not None and not isinstance(self.tags, dict):
            raise ValueError("invalid tags")
        if self.answer_shape not in SHAPES[self.angle]:
            raise ValueError("incompatible answer shape")
        if self.variant not in (("one_shot", "reusable") if self.angle == "create" else (None,)):
            raise ValueError("variant is only allowed for create")
        boundary = self.boundary
        if not isinstance(boundary, dict) or set(boundary) != set(default_boundary()):
            raise ValueError("invalid boundary")
        depth = boundary["depth"]
        if depth is not None and (type(depth) is not int or depth < 0):
            raise ValueError("invalid boundary depth")
        for key in ("open_names", "keep_names", "kinds"):
            values = boundary[key]
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or len(set(values)) != len(values):
                raise ValueError(f"invalid boundary {key}")
        if set(boundary["kinds"]) - set(KINDS) or set(boundary["open_names"]) & set(boundary["keep_names"]):
            raise ValueError("conflicting boundary")
        paths = boundary["open_paths"]
        if not isinstance(paths, list) or any(not isinstance(path, list) or any(type(part) is not int or part < 0 for part in path) for path in paths):
            raise ValueError("invalid boundary paths")
        obs = self.observation
        if not isinstance(obs, dict) or set(obs) != {"show", "channels"} or not isinstance(obs["show"], dict) or set(obs["show"]) != {"input", "result"}:
            raise ValueError("invalid observation")
        if obs["show"]["input"] not in ("values", "full_state", "hidden") or obs["show"]["result"] not in ("value", "full_state", "hidden"):
            raise ValueError("invalid observation show")
        if not isinstance(obs["channels"], list) or len(set(obs["channels"])) != len(obs["channels"]) or set(obs["channels"]) - set(CHANNELS):
            raise ValueError("invalid observation channels")
        if self.judge_view != "full_state" and (not isinstance(self.judge_view, dict) or set(self.judge_view) != {"contract_projection"} or not isinstance(self.judge_view["contract_projection"], list) or not self.judge_view["contract_projection"] or any(not isinstance(field, str) or not field for field in self.judge_view["contract_projection"]) or len(set(self.judge_view["contract_projection"])) != len(self.judge_view["contract_projection"])):
            raise ValueError("invalid judge view")
        if not isinstance(self.grader, dict) or self.grader.get("method") != METHODS[self.answer_shape] or type(self.grader.get("fuel")) is not int or self.grader["fuel"] < 1 or not isinstance(self.grader.get("scope"), dict):
            raise ValueError("invalid grader")
        if self.judge_view != "full_state" and self.kind == "operation" and self.world != "computer@1":
            raise ValueError("operation grader cannot apply a state projection")
        if not all(isinstance(value, dict) for value in (self.question, self.prompt, self.reference, self.source)) or not isinstance(self.prompt.get("en"), str):
            raise ValueError("invalid task payload")
        world_observation = self.source.get("world_observation")
        if world_observation is not None and (
            not isinstance(world_observation, dict)
            or not set(obs["channels"]).issubset(set(world_observation.get("channels", ())))
            or any(obs["show"][key] == "full_state"
                   and world_observation.get("show", {}).get(key) != "full_state"
                   for key in ("input", "result"))
        ):
            raise ValueError("task observation widens world declaration")

    def to_dict(self) -> dict:
        return deepcopy({key: getattr(self, key) for key in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        optional = {"modality", "open_kinds", "tags"}
        if not set(cls.__dataclass_fields__) - optional <= set(data) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError("task fields mismatch")
        return cls(**deepcopy(data))
