"""Generated-library task bridge and honest four-kind route."""

import json
import sys
from types import SimpleNamespace

import pytest

from opulse.atoms import kernel, nodes
from opulse.gen_v2 import tasks_bridge
from opulse.gen_v2.base import Entry, Signature
from opulse.gen_v2.codec import decode_checkpoint_value, encode_checkpoint_value
from opulse.gen_v2.run import generate
from opulse.gen_v2.worlds import lists, toy_truth


def _path_state():
    entries = {
        "A1": Entry("A1", "object", 1, None, "obj.test", ()),
        "f2": Entry("f2", "operation", 2, Signature(("A1",), "int"), "op.test", ("A1.base",)),
        "k3": Entry("k3", "combinator", 3,
                    Signature(("A1",), "int", (Signature(("A1",), "int"),)),
                    "comb.test", (), meta={"slot_families": {"op": ("f2",)}}),
        "q4": Entry("q4", "observation", 4, Signature(("truth",), "int"),
                    "obs.test", ("A1.make", "k3")),
    }
    bodies = {"A1": None, "f2": nodes.Call("A1.base", (nodes.Var("x"),)),
              "k3": nodes.Call("op", (nodes.Var("x"),)),
              "q4": nodes.Call("k3", (nodes.Lit(kernel.FnRef("f2")),
                                        nodes.Call("A1.make", (nodes.Var("read_x"),))))}
    definitions = {name: SimpleNamespace(body=body, status="promoted",
                                           contract=SimpleNamespace(to_dict=lambda: {"guarantees": "checked"}),
                                           evidence=SimpleNamespace(to_dict=lambda: {"method": "bounded"}))
                   for name, body in bodies.items()}
    world = SimpleNamespace(name="fixture", version=1, truth_sort="truth", truth_states=(1, 2),
                            tags={"modalities": ["text", "image"]})
    sorts = {"A1": SimpleNamespace(values=(1, 2)), "int": SimpleNamespace(values=(0, 1))}
    return SimpleNamespace(entries=entries, library=SimpleNamespace(get=definitions.__getitem__),
                           world=world, sorts=sorts, requests={})


def test_four_kind_path_uses_promoted_evidence_and_real_links(monkeypatch):
    state = _path_state()
    monkeypatch.setattr(tasks_bridge, "print_declaration", lambda entry, state: entry.name)
    path = tasks_bridge.four_kinds_path(state)
    assert [row["name"] for row in path["steps"]] == ["A1", "f2", "k3", "q4"]
    assert path["links"][-1] == "observation uses combinator"
    assert all(row["evidence"]["method"] == "bounded" for row in path["steps"])
    assert json.dumps(path).isascii()

    state.entries["k3"].meta["slot_families"] = {"op": ("other",)}
    assert tasks_bridge.four_kinds_path(state) is None
    state.entries["k3"].meta["slot_families"] = {"op": ("f2",)}
    state.library.get("f2").status = "verified"
    assert tasks_bridge.four_kinds_path(state) is None
    state.library.get("f2").status = "promoted"
    state.library.get("q4").evidence = None
    assert tasks_bridge.four_kinds_path(state) is None


def test_task_world_and_export_use_hook_scope_and_sibling_path(monkeypatch, tmp_path):
    state = _path_state()
    calls = {}

    def from_library(library, **options):
        calls.update(options)
        assert library is state.library
        return "task-world"

    def generate_world(world, per_angle, seed):
        assert (world, per_angle, seed) == ("task-world", 2, 17)
        return [SimpleNamespace(to_dict=lambda: {"prompt": "ASCII"})]

    monkeypatch.setattr(tasks_bridge, "_task_hooks", lambda require_generator=True:
                        (from_library, generate_world if require_generator else None))
    monkeypatch.setattr(tasks_bridge, "print_declaration", lambda entry, state: entry.name)
    payload = tasks_bridge.export_tasks(state, tmp_path / "generated.json", 2, 17)
    assert payload == json.loads((tmp_path / "generated.tasks.json").read_text())
    assert payload["tasks"] == [{"prompt": "ASCII"}]
    assert payload["four_kinds_path"]["steps"][0]["name"] == "A1"
    assert calls["domains"]["int"] == (0, 1)
    assert calls["family"] == {"op": ("f2",)}
    assert calls["states"] == (1, 2)
    assert calls["modalities"] == {"text": True, "image": True}
    assert calls["from_value"](calls["to_value"](True)) is True
    assert calls["to_value"] is encode_checkpoint_value
    assert calls["from_value"] is decode_checkpoint_value


def test_task_world_uses_recorded_probe_values(monkeypatch):
    state = _path_state()
    state.requests["f2"] = SimpleNamespace(domain=((2,),))
    state.requests["k3"] = SimpleNamespace(domain=((1,), (2,)))
    monkeypatch.setattr(tasks_bridge, "_task_hooks", lambda require_generator=True:
                        (lambda library, **options: options, None))
    world = tasks_bridge.task_world(state)
    assert world["domains"]["A1"] == (2,)
    assert world["domains"]["int"] == (0, 1)


def test_shared_slot_family_never_expands_a_verified_family(monkeypatch):
    state = _path_state()
    state.entries["k5"] = Entry("k5", "combinator", 3, None, "comb.test", (),
                                meta={"slot_families": {"op": ("other",)}})
    monkeypatch.setattr(tasks_bridge, "_task_hooks", lambda require_generator=True:
                        (lambda library, **options: options, None))
    assert tasks_bridge.task_world(state)["family"] == {"op": ()}


def test_missing_task_hook_fails_without_writing(tmp_path, monkeypatch):
    state = _path_state()
    monkeypatch.setitem(sys.modules, "opulse.tasks_v2.hooks", None)
    with pytest.raises(RuntimeError, match="tasks branch"):
        tasks_bridge.export_tasks(state, tmp_path / "generated.json", 1, 0)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("adapter", (toy_truth, lists))
def test_real_generated_states_have_only_promoted_path_steps(adapter):
    kinds = ("object", "operation", "combinator", "observation")
    world = adapter.gen_world(kinds) if adapter is toy_truth else adapter.gen_world()
    state = generate(world, 8, 2, per_kind_min=0, layer_target=0, time_limit=5)
    assert state.entries
    path = tasks_bridge.four_kinds_path(state)
    if path is not None:
        assert [row["kind"] for row in path["steps"]] == list(kinds)
        assert all(state.library.get(row["name"]).status == "promoted" for row in path["steps"])


def test_four_kind_path_requires_the_observation_to_use_the_combinator(monkeypatch):
    # integration round 5: molecules reported J284 -> u327 -> k507 -> q583 although q583
    # used only the operation, not the combinator
    state = _path_state()
    monkeypatch.setattr(tasks_bridge, "print_declaration", lambda entry, state: entry.name)
    only_operation = nodes.Call("f2", (nodes.Call("A1.make", (nodes.Var("read_x"),)),))
    state.library.get("q4").body = only_operation
    state.entries["q4"] = Entry("q4", "observation", 4, Signature(("truth",), "int"),
                                "obs.test", ("A1.make", "f2"))
    assert tasks_bridge.four_kinds_path(state) is None
