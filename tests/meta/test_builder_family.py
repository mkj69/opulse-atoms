"""Recorded modular template and cross-world bridge evidence."""

from opulse.atoms import bridges, kernel
from opulse.atoms.values import Card, Ok
from opulse.meta import engine
from opulse.meta.builder import world_value as V
from opulse.meta.builder.wf import wf
from opulse.meta.worlds.builder import family, story


def test_zn_family_each_member_has_own_scope_and_world_evidence():
    lib, members = family.creation()
    template = lib.get("Zn")
    assert template.status == "promoted"
    assert template.evidence.checks == ("family",)
    assert template.evidence.scope["family"] == [{"n": size} for size in range(3, 8)]
    assert template.evidence.scope["size"] == 5
    assert len(members) == 5
    expected_steps = (165, 284, 437, 624, 845)
    for size, member in enumerate(members, 3):
        stored = lib.get(member.name)
        assert stored.status == "promoted" and stored.evidence.scope["size"] == 1
        assert stored.evidence.checks == ("unfold_equivalence", "reference", "constant", "world_interface")
        assert "Zn" in stored.depends_on
        run = lib.run(member.name, (), trace=True)
        assert run.outcome == Ok(family.modular_world(size))
        assert run.trace.steps == run.steps == expected_steps[size - 3]
        assert wf(run.outcome.value) == Card("report", "ok")
        assert V.world_hash(run.outcome.value) == V.world_hash(family.modular_world(size))


def test_bridge_commutes_through_both_built_worlds():
    context = story.bridge_context()
    source_world = story.z5()
    target = story.z5xbool()
    from opulse.meta.worlds.builder import hosts

    dispatch = kernel.DictScope(hosts.atoms())
    for left in range(5):
        for right in range(5):
            args = (story.z(left), story.z(right))
            source = engine.call("call_in", (source_world, "add5", story.C.lst(args)), dispatch)
            assert source.outcome == Ok(story.z((left + right) % 5)) and source.steps == 2
            mapped = [engine.call("call_in", (target, "embed", story.C.lst((arg,))), dispatch)
                      for arg in args]
            assert [(item.outcome, item.steps) for item in mapped] == [
                (Ok(2 * left), 2), (Ok(2 * right), 2)]
            target_run = engine.call("call_in", (target, "add_pair",
                                                      story.C.lst(tuple(item.outcome.value for item in mapped))),
                                     dispatch)
            assert target_run.outcome == Ok(2 * ((left + right) % 5)) and target_run.steps == 2
    spec = next(definition.spec for definition in story.definitions() if definition.name == "embed_z5")
    assert bridges.check_bridge(next(definition for definition in story.definitions()
                                     if definition.name == "embed_z5"), context) == []
    assert spec.interface == (("add5", "add_pair"),)
