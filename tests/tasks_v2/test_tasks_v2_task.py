"""Task schema and settings invariants."""

from dataclasses import replace

import pytest

from opulse.tasks_v2.angles.operation import generate
from opulse.tasks_v2.task import KINDS, Task, default_boundary, default_observation


def test_round_trip_and_copy():
    task = generate("integer", "compute")
    data = task.to_dict()
    assert Task.from_dict(data).to_dict() == data
    data["boundary"]["kinds"].clear()
    assert task.boundary["kinds"]


@pytest.mark.parametrize("changes", [
    {"schema": "bad"}, {"id": ""}, {"world": ""}, {"family": ""},
    {"angle": "other"}, {"kind": "other"}, {"answer_shape": "definition"},
    {"variant": "reusable"}, {"judge_view": {"contract_projection": []}},
    {"judge_view": {"contract_projection": ["r0"]}},
    {"grader": {"method": "witness", "fuel": 100, "scope": {}}},
    {"grader": {"method": "exact_value", "fuel": 0, "scope": {}}},
    {"prompt": {}},
])
def test_invalid_record(changes):
    with pytest.raises(ValueError):
        replace(generate("integer", "compute"), **changes)


@pytest.mark.parametrize("changes", [
    {"depth": -1}, {"depth": True}, {"kinds": ["other"]},
    {"open_names": ["◇"], "keep_names": ["◇"]},
    {"open_paths": [[-1]]}, {"open_paths": ["bad"]},
])
def test_invalid_boundary(changes):
    boundary = default_boundary()
    boundary.update(changes)
    with pytest.raises(ValueError):
        generate("integer", "compute", boundary=boundary)


@pytest.mark.parametrize("changes", [
    {"channels": ["other"]}, {"channels": ["results", "results"]},
    {"show": {"input": "bad", "result": "value"}},
])
def test_invalid_observation(changes):
    observation = default_observation()
    observation.update(changes)
    with pytest.raises(ValueError):
        generate("integer", "compute", observation=observation)


def test_create_variant_and_extra_fields():
    assert generate("integer", "create", variant="reusable").question["reuse_tasks"]
    with pytest.raises(ValueError):
        generate("integer", "create", variant="nope")
    with pytest.raises(ValueError):
        Task.from_dict({**generate("integer", "compute").to_dict(), "extra": 1})
    normal = generate("integer", "compute")
    with pytest.raises(ValueError):
        replace(normal, source={**normal.source, "world_observation": {"channels": ["results"]}})


def test_legacy_defaults_and_new_fields():
    data = generate("integer", "compute").to_dict()
    assert data["modality"] == "text" and data["open_kinds"] == ["operation"] and data["tags"] is None
    for field in ("modality", "open_kinds", "tags"):
        data.pop(field)
    loaded = Task.from_dict(data)
    assert loaded.modality == "text" and loaded.open_kinds == list(KINDS)  # six kinds (common.md)
    assert loaded.tags is None
    assert replace(loaded, tags={"domain": "math"}).to_dict()["tags"] == {"domain": "math"}


@pytest.mark.parametrize("changes", [
    {"modality": "video"}, {"open_kinds": []}, {"open_kinds": ["object"]},
    {"open_kinds": ["operation", "operation"]}, {"open_kinds": ["operation", "wrong"]},
    {"open_kinds": "operation"}, {"tags": []},
])
def test_invalid_new_fields(changes):
    with pytest.raises(ValueError):
        replace(generate("integer", "compute"), **changes)


def test_six_kinds_accepted():
    assert KINDS == ("object", "operation", "combinator", "observation", "law", "bridge")
    data = generate("integer", "compute").to_dict()
    for kind in ("law", "bridge"):
        assert Task.from_dict({**data, "kind": kind, "open_kinds": [kind]}).kind == kind
    with pytest.raises(ValueError):
        Task.from_dict({**data, "kind": "tactic"})
