from opulse.gen_v2.base import Entry, GenState
from opulse.gen_v2.curate import curate, dedup_report, featured, graph_stats, showcase
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.worlds.toy import gen_world


def state():
    world = gen_world()
    state = GenState(world, GenLibrary(world.decl, world.atoms), dict(world.sorts))
    for name, kind, layer, deps in (
        ("A1", "object", 1, ()), ("f2", "operation", 2, ("A1",)),
        ("k3", "combinator", 3, ("A1", "f2")),
        ("q4", "observation", 4, ("k3",)), ("f5", "operation", 3, ("f2",))
    ):
        state.entries[name] = Entry(name, kind, layer, None, "test", deps, (kind, name), 1, 2, 4)
    return state


def test_graph_stats_hand_built():
    stats = graph_stats(state())
    assert stats["counts_per_kind"] == {"object": 1, "operation": 2, "combinator": 1,
                                        "observation": 1, "law": 0, "bridge": 0}
    assert stats["counts_per_layer"] == {1: 1, 2: 1, 3: 2, 4: 1}
    assert stats["max_layer"] == 4
    assert stats["longest_dependency_chain"] == 4
    assert stats["depth_distribution"] == {1: 1, 2: 1, 3: 2, 4: 1}
    assert stats["mean_fan_in"] == stats["mean_fan_out"] == 1
    assert stats["multi_dependency_share"] == 0.2
    assert stats["chain_likeness"] == 0.2


def test_curate_closure_quotas_featured_and_dedup():
    world = state()
    chosen = curate(world, 5, per_kind_min=1, per_layer_min=1)
    assert set(chosen) == {"A1", "f2", "k3", "q4", "f5"}
    constrained = curate(world, 4, per_kind_min=1, per_layer_min=1)
    assert set(constrained) == {"A1", "f2", "k3", "q4"}
    assert len(featured(world, "operation", 1)) == 1
    assert all(set(world.entries[name].depends_on) <= set(constrained) for name in constrained)
    assert dedup_report(world)["duplicates"] == 0


def test_featured_measured_reasons_and_diverse_moves():
    world = state()
    for index in range(6, 12):
        name = f"f{index}"
        world.entries[name] = Entry(name, "operation", 4 + index, None,
                                    "alternate" if index % 2 else "repeat", ("A1", "k3"),
                                    ("operation", index), 2, 3, 5)
    picks = featured(world, "operation", 2)
    assert len(picks) == 2
    assert len({world.entries[item["name"]].move for item in picks}) == 2
    for pick in picks:
        entry = world.entries[pick["name"]]
        assert f"layer {entry.layer}" in pick["why"]
        assert "A1 (object)" in pick["why"]
        assert "@k3 (combinator)" in pick["why"]
        assert "2 layer-0 steps on average" in pick["why"]


def test_showcase_spine_closure_and_all_open_kinds():
    world = state()
    picks = showcase(world, 5)
    names = {item["name"] for item in picks}
    assert names == set(world.entries)
    assert {world.entries[name].kind for name in names} == set(world.world.open_kinds)
    assert max(world.entries[name].layer for name in names) == 4
    assert all(set(world.entries[name].depends_on) <= names for name in names)
    assert all("layer" in item["why"] and "layer-0 steps" in item["why"] for item in picks)
    assert len(showcase(world, 3)) <= 3
    assert showcase(world, 0) == []


def test_showcase_prefers_kind_coverage_over_unaffordable_top_chain():
    world = state()
    previous = "f5"
    for layer in range(4, 11):
        name = f"h{layer}"
        world.entries[name] = Entry(name, "operation", layer, None, "chain", (previous,),
                                    ("operation", layer), 2, 2, 3)
        previous = name
    chosen = showcase(world, 5)
    assert len(chosen) == 5
    assert {world.entries[item["name"]].kind for item in chosen} == set(world.world.open_kinds)
    assert all(set(world.entries[item["name"]].depends_on) <= {pick["name"] for pick in chosen}
               for item in chosen)
