"""World declaration and promotion tests for atoms-v2."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from opulse.atoms.library import checked_scope
from opulse.atoms.nodes import Call, Lit
from opulse.atoms.spec import Contract, Definition, Edge, Evidence, OperationSpec
from opulse.atoms.world import DISPLAY_ONLY, DerivedWorld, WorldDecl, legacy_world_decl

WORLD_DIR = Path(__file__).resolve().parents[1] / "docs/assets/data/worlds"


CHECKED = checked_scope([(value,) for value in range(50)])


def test_published_legacy_worlds():
    paths = [path for path in WORLD_DIR.glob("*.json") if path.name != "index.json"]
    assert len(paths) == 12
    for path in paths:
        published = json.loads(path.read_text())
        world = legacy_world_decl(published)
        assert world.version == 1 and world.dialect == "legacy-v1"
        assert len(world.operations) == len(published["atoms"])
        assert len(world.objects) == len({a["result_type"] for a in published["atoms"]} |
                                         {p["type"] for a in published["atoms"] for p in a["params"]})
        assert world.opened_nodes() == {"Var", "Lit", "Call", "Case", "Rec"}
        assert WorldDecl.from_dict(json.loads(json.dumps(world.to_dict()))) == world
        assert world.world_hash() == WorldDecl.from_dict(world.to_dict()).world_hash()
        changed = dict(published)
        changed["atoms"] = [dict(atom) for atom in published["atoms"]]
        changed["atoms"][0]["rule"] = "a different rule"
        assert world.world_hash() != legacy_world_decl(changed).world_hash()
        changed["atoms"][0]["symbol"] = "different symbol"
        changed["atoms"][0]["rule"] = published["atoms"][0]["rule"]
        assert world.world_hash() == legacy_world_decl(changed).world_hash()
        changed["atoms"][0]["params"] = [dict(param, name="renamed")
                                          for param in published["atoms"][0]["params"]]
        assert world.world_hash() == legacy_world_decl(changed).world_hash()
        assert world.operations[0].extra == {
            "symbol": published["atoms"][0]["symbol"],
            "input_names": [param["name"] for param in published["atoms"][0]["params"]]}
        assert world.params["semantics"] == {
            "mode": "modular" if world.world == "clock" else "exact",
            "bound": 2**31 - 1, "modulus": 12 if world.world == "clock" else None}
        assert {op.output.enter for op in world.operations} == {
            "normalize" if world.world == "clock" else "bottom"}
        assert world.world_hash() == replace(world, lock={**world.lock, "world_hash": "self-reference"}).world_hash()
        if world.world == "action":
            assert {probe["name"] for probe in world.observation["probes"]} == {
                "front_wall", "front_water", "front_colour", "holding", "held_colour", "front_height"}
            assert world.observation["truth"] == "state"
            assert world.combinators["library"] == ["repeat_until"]
        else:
            assert world.observation["truth"] is None


def test_derived_world_requires_matching_promotion():
    world = legacy_world_decl(json.loads((WORLD_DIR / "integer.json").read_text()))
    spec = OperationSpec("double", "transform", (Edge("int"),), Edge("int"), "twice")
    definition = Definition("double", "operation", "invented", 1, (), spec, Lit(2),
                            Evidence("bounded", {"domain": "int", "size": 50, "checked": CHECKED},
                                     world_hash=world.world_hash()),
                            Contract("returns two"), status="promoted")
    derived = DerivedWorld.build(world, (definition,))
    assert derived.extends == "integer@1"
    assert derived.open_kinds == ("operation",)
    assert derived.scopes() == {"double": {"domain": "int", "size": 50, "checked": CHECKED}}
    assert DerivedWorld("integer@1", (replace(definition, evidence=replace(definition.evidence,
                                                                            world_hash="different")),)).extends == "integer@1"
    for invalid in (replace(definition, status="verified"),
                    replace(definition, evidence=None),
                    replace(definition, evidence=replace(definition.evidence, world_hash="different")),
                    replace(definition, evidence=replace(definition.evidence, method="sampled", seed=2)),
                    replace(definition, contract=None),
                    replace(definition, body=Call("add"))):
        with pytest.raises(ValueError):
            DerivedWorld.build(world, (invalid,))
    for invalid in (replace(definition, status="verified"), replace(definition, evidence=None)):
        with pytest.raises(ValueError):
            DerivedWorld("integer@1", (invalid,))


def test_legacy_semantics_settings_override_preset():
    published = json.loads((WORLD_DIR / "integer.json").read_text())
    published["settings"].append({"key": "semantics.mode", "value": "legacy"})
    legacy = legacy_world_decl(published)
    assert legacy.params["semantics"]["mode"] == "legacy"
    assert {op.output.enter for op in legacy.operations} == {"fold(legacy)"}
    published["settings"].append({"key": "semantics.bound", "value": 127})
    assert legacy_world_decl(published).params["semantics"]["bound"] == 127
    published["settings"] = {"semantics": {"mode": "exact", "bound": 63}}
    assert legacy_world_decl(published).params["semantics"]["bound"] == 63


def test_world_extra_round_trip_and_hash_rules():
    world = legacy_world_decl(json.loads((WORLD_DIR / "action.json").read_text()))
    data = world.to_dict()
    data.update(title="Action", title_zh="Action", source="publisher", codec={"state": "v2"})
    data["objects"][0].update(host="module:object", doc="display")
    data["operations"][0].update(symbol="ACTION", input_names=["state"], impl={"table": {}})
    data["observation"]["probes"][0].update(impl="module:probe", doc="display")
    recovered = WorldDecl.from_dict(json.loads(json.dumps(data)))
    assert recovered.to_dict() == data
    assert recovered.extra == {"title": "Action", "title_zh": "Action", "source": "publisher",
                               "codec": {"state": "v2"}}
    assert recovered.objects[0].extra == {"host": "module:object", "doc": "display"}
    assert recovered.operations[0].impl == {"table": {}}
    assert recovered.observation["probes"][0]["impl"] == "module:probe"
    assert set(DISPLAY_ONLY) == {"title", "title_zh", "doc", "source", "symbol", "input_names"}
    for path, key, value in ((data, "title", "renamed"), (data, "title_zh", "renamed"),
                             (data, "source", "renamed"), (data["objects"][0], "doc", "renamed"),
                             (data["operations"][0], "symbol", "renamed"),
                             (data["operations"][0], "input_names", ["renamed"]),
                             (data["observation"]["probes"][0], "doc", "renamed")):
        changed = json.loads(json.dumps(data))
        if path is data:
            target = changed
        elif path is data["objects"][0]:
            target = changed["objects"][0]
        elif path is data["operations"][0]:
            target = changed["operations"][0]
        else:
            target = changed["observation"]["probes"][0]
        target[key] = value
        assert WorldDecl.from_dict(changed).world_hash() == recovered.world_hash()
    for target, key, value in (("world", "codec", {"state": "v3"}),
                               ("object", "host", "another:object"),
                               ("operation", "impl", {"table": {"x": 1}}),
                               ("probe", "impl", "another:probe")):
        changed = json.loads(json.dumps(data))
        record = {"world": changed, "object": changed["objects"][0],
                  "operation": changed["operations"][0],
                  "probe": changed["observation"]["probes"][0]}[target]
        record[key] = value
        assert WorldDecl.from_dict(changed).world_hash() != recovered.world_hash()


def test_world_dialect_and_combinator_validation():
    world = legacy_world_decl(json.loads((WORLD_DIR / "integer.json").read_text()))
    for recursion in ("legacy", "measure", "fuel"):
        assert replace(world, combinators={**world.combinators, "recursion": recursion}).opened_nodes()
    for change in ({"dialect": "unknown"}, {"combinators": {**world.combinators, "recursion": "unknown"}},
                   {"combinators": {**world.combinators, "nodes": ["NotAKernelNode"]}}):
        with pytest.raises(ValueError):
            replace(world, **change)


def test_machine_style_declaration_loads():
    from opulse.atoms.spec import ObjectSpec

    reg = ObjectSpec("reg", "compose", tags={"r0": {}, "r1": {}})
    machine = ObjectSpec("machine_state", "compose", tags={"machine": {"regs": "array[4,byte]", "zero": "bool"}})
    data = {"schema": "opulse.world/2", "world": "m", "version": 1, "dialect": "atoms-v2", "params": {},
            "constants": {}, "objects": [reg.to_dict(), machine.to_dict()], "operations": [],
            "combinators": {"nodes": ["Var", "Lit", "Call", "Blocks", "Jump", "CondJump", "Halt"],
                            "library": [], "recursion": "none"},
            "observation": {}, "lock": {}}
    world = WorldDecl.from_dict(data)
    assert world.to_dict() == {**data, "open_kinds": ["combinator", "object", "observation", "operation"]}
    with pytest.raises(ValueError):
        WorldDecl.from_dict({**data, "combinators": {**data["combinators"], "nodes": ["Rec"]}})


def test_open_kinds_canonical_validation_and_world_hash():
    world = legacy_world_decl(json.loads((WORLD_DIR / "integer.json").read_text()))
    assert world.open_kinds == ("operation",)
    opened = replace(world, open_kinds=["observation", "operation"])
    assert opened.to_dict()["open_kinds"] == ["observation", "operation"]
    assert WorldDecl.from_dict(opened.to_dict()).extra == world.extra
    assert opened.world_hash() != world.world_hash()
    absent = {key: value for key, value in opened.to_dict().items() if key != "open_kinds"}
    assert WorldDecl.from_dict(absent).open_kinds == ("combinator", "object", "observation", "operation")
    for invalid in (["unknown"], ["operation", "operation"], "operation"):
        with pytest.raises(ValueError, match="open kinds"):
            replace(world, open_kinds=invalid)
