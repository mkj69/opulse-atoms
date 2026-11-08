"""Regression checks for VN digest, observation, and export scope commitments."""

import json
import random
from dataclasses import replace

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.boundary import Boundary
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.laws import RewriteError, replay_rewrite, rewrite
from opulse.atoms.library import PipelineError, VerifyRequest, atoms_digest
from opulse.atoms.spec import Contract, Definition, LawSpec, ObjectSpec, ObservationSpec
from opulse.atoms.values import FALSE, Bottom, Ok
from opulse.meta.export_util import value_json
from opulse.meta.vn import machine, reference
from opulse.meta.worlds.vonneumann import world as world_module
from opulse.meta.worlds.vonneumann.export import build_export
from opulse.meta.worlds.vonneumann.routines import RoutineDomain, RoutineLedger
from opulse.meta.worlds.vonneumann.story import (
    RELOCATED,
    RESTORE,
    SMALL,
    SUM,
    VNLibrary,
    initial,
    relocation_start,
)


def test_world_helper_replacement_invalidates_law(monkeypatch):
    lib = VNLibrary(world_module.declaration(), machine.atoms(32))
    body = nodes.Call("eq", (nodes.Var("a"), nodes.Var("a")))
    law = Definition("reflexive", "law", "invented", 1, ("eq",),
                     LawSpec("reflexive", (("a", "int"),), body), body)
    lib.write(law)
    lib.check(law.name)
    lib.make_callable(law.name, [(1,)])
    lib.verify(law.name, VerifyRequest("exhaustive", ((1,),), {"domain": "one", "size": 1}))
    lib.account(law.name)
    before_world, before_atoms = lib.world.world_hash(), atoms_digest(lib.atoms)
    assert lib.run("eq", (1, 1)).outcome == Ok(world_module.boolean(True))
    monkeypatch.setattr(world_module, "boolean", lambda value: FALSE)
    assert lib.run("eq", (1, 1)).outcome == Ok(FALSE)
    assert world_module.declaration().world_hash() != before_world
    assert atoms_digest(lib.atoms) != before_atoms
    assert lib.get(law.name).status == "callable" and lib.get(law.name).evidence is None
    with pytest.raises(PipelineError, match="promote requires verified status"):
        lib.promote(law.name, Contract("reflexivity"))


def test_live_state_method_invalidates_routine(monkeypatch):
    ledger = RoutineLedger(world_module.declaration())
    domain = RoutineDomain.product("one pair", ((1,), (2,)),
                                   lambda values: relocation_start(*values))
    proof = ledger.verify(SMALL, domain, lambda state, fuel: reference.run(state, fuel)[1:])
    state = machine.to_card(relocation_start(1, 2))
    assert machine.from_card(machine.poke(state, 7, 29)).a == 0
    monkeypatch.setattr(reference.State, "__post_init__",
                        lambda self: object.__setattr__(self, "a", 7))
    assert machine.from_card(machine.poke(state, 7, 29)).a == 7
    assert machine.atoms_hash(32) != proof.atoms_hash
    assert world_module.declaration().world_hash() != ledger.world_hash
    with pytest.raises(ValueError, match="routine atoms hash changed"):
        ledger.promote(SMALL, Contract("two bytes", ()))


def test_live_state_method_invalidates_library_evidence(monkeypatch):
    lib = VNLibrary(world_module.declaration(), machine.atoms(32))
    body = nodes.Lit(7)
    definition = Definition("seven", "object", "invented", 1, (),
                            ObjectSpec("seven", "constant", body=body), body)
    lib.write(definition)
    lib.check(definition.name)
    lib.make_callable(definition.name, [()])
    lib.verify(definition.name, VerifyRequest("bounded", ((),),
                                              {"domain": "one constant", "size": 1},
                                              extra={"values": [7]}))
    lib.account(definition.name)
    old_hash = atoms_digest(lib.atoms)
    monkeypatch.setattr(reference.State, "__post_init__",
                        lambda self: object.__setattr__(self, "a", 7))
    assert atoms_digest(lib.atoms) != old_hash
    assert lib.get(definition.name).status == "callable" and lib.get(definition.name).evidence is None
    with pytest.raises(PipelineError, match="promote requires verified status"):
        lib.promote(definition.name, Contract("returns seven"))


def test_world_module_source_and_world_atom_cost_are_committed(monkeypatch):
    lib = VNLibrary(world_module.declaration(), machine.atoms(32))
    before_world, before_atoms = lib.world.world_hash(), atoms_digest(lib.atoms)
    bare_atom = (kernel.Atom("step", 1, machine.step, 1),)
    bare_digest = atoms_digest(bare_atom)
    original = machine.inspect.getsource

    def modified_source(value):
        source = original(value)
        return source + "\n# changed world atom module\n" if value is world_module else source

    monkeypatch.setattr(machine.inspect, "getsource", modified_source)
    assert atoms_digest(bare_atom) == bare_digest
    assert world_module.declaration().world_hash() != before_world
    assert atoms_digest(lib.atoms) != before_atoms
    monkeypatch.setattr(machine.inspect, "getsource", original)
    lib.atoms = tuple(replace(atom, cost=atom.cost + 1) if atom.name == "eq" else atom
                      for atom in lib.atoms)
    assert atoms_digest(lib.atoms) != before_atoms


@pytest.mark.parametrize("probe,expected", (("pc", 0), ("a", 0), ("halted", FALSE), ("cell", 1)))
def test_observation_respects_its_declared_probe(probe, expected):
    state = machine.to_card(reference.load([1, 8, 0, 0], 32))
    args = (nodes.Var("s"),) if probe != "cell" else (nodes.Var("s"), nodes.Lit(0))
    body = nodes.Call(probe, args)
    definition = Definition(f"read_{probe}", "observation", "invented", 1, (probe,),
                            ObservationSpec(f"read_{probe}", (probe,), body), body)
    lib = VNLibrary(world_module.declaration(), machine.atoms(32))
    lib.write(definition)
    lib.check(definition.name)
    lib.make_callable(definition.name, [(state,)])
    lib.verify(definition.name, VerifyRequest("bounded", ((state,),),
                                             {"domain": "one state", "size": 1},
                                             reference=lambda s: Ok(expected)))
    assert lib.run(definition.name, (state,)).outcome == Ok(expected)
    assert machine.from_card(state) == reference.load([1, 8, 0, 0], 32)


def test_observation_rejects_incorrect_oracle():
    state = machine.to_card(reference.load([1, 8, 0, 0], 32))
    body = nodes.Call("pc", (nodes.Var("s"),))
    definition = Definition("read_pc", "observation", "invented", 1, ("pc",),
                            ObservationSpec("read_pc", ("pc",), body), body)
    lib = VNLibrary(world_module.declaration(), machine.atoms(32))
    lib.write(definition)
    lib.check(definition.name)
    lib.make_callable(definition.name, [(state,)])
    with pytest.raises(ValueError, match="declared reference"):
        lib.verify(definition.name, VerifyRequest("bounded", ((state,),),
                                                  {"domain": "one state", "size": 1},
                                                  reference=lambda s: Ok(1)))


def test_export_marks_actual_out_of_scope_callees():
    story = build_export()["story"]
    entry = next(entry for entry in story if entry["name"] == "source_result")
    example = entry["examples"][0]
    assert example["inputs"][0] not in [value_json(machine.to_card(initial(SUM, values)))
                                        for values in ((1, 2, 3), (0, 0, 0))]
    assert example["outside_scope"] is True
    assert example["callee_scope"]["name"] == "run_routine"
    target = next(entry for entry in story if entry["name"] == "target_result")["examples"][0]
    assert target["outside_scope"] is True
    assert target["callee_scope"]["name"] == "run_routine"
    from opulse.meta.worlds.vonneumann.story import creation_story

    lib, _ = creation_story()
    for entry in story:
        for mark in entry["examples"][0].get("callee_scopes", ()):
            assert mark["input_hash"] not in lib.get(mark["name"]).evidence.scope["input_hashes"]


def test_replay_and_near_miss_at_all_law_inputs():
    from opulse.meta.worlds.vonneumann.story import creation_story

    lib, _ = creation_story()
    state = machine.to_card(initial(RESTORE, (1, 2, 3)))
    original = nodes.Call("get_a", (nodes.Call("reset_operand", (
        nodes.Call("reset_operand", (nodes.Var("s"),)),)),))
    rewritten = rewrite(original, "restore_idempotent", lib, at=(0,))
    for operand in (32, 29, 0):
        scoped = machine.poke(state, 7, operand)
        replay = replay_rewrite(original, rewritten, "restore_idempotent", lib,
                                {"s": scoped}, fuel=100)
        assert len(replay.steps) == 1 and replay.charged_steps == 2
        before = kernel.evaluate(original, {"s": scoped}, lib.scope())
        after = kernel.evaluate(rewritten, {"s": scoped}, lib.scope())
        assert before.outcome == after.outcome == Ok(0)
        assert before.steps == 3 and after.steps == 2
        repaired = machine.poke(scoped, 7, 29)
        assert machine.poke(repaired, 7, 29) == repaired
        assert (repaired == scoped) is (operand == 29)
    with pytest.raises(RewriteError, match="verified scope"):
        replay_rewrite(original, rewritten, "restore_idempotent", lib,
                       {"s": machine.poke(state, 7, 31)}, fuel=100)


def test_bridge_domain_and_family_members_on_exact_inputs():
    from opulse.meta.worlds.vonneumann.story import creation_story

    lib, _ = creation_story()
    for first in range(2):
        for second in range(2):
            state = machine.to_card(relocation_start(first, second))
            mapped = lib.run("relocate_12", (state,), fuel=100)
            assert mapped.steps == 25
            assert machine.from_card(mapped.outcome.value).mem[12:18] == RELOCATED.code
            assert lib.run("source_result", (state,), fuel=100).outcome == Ok(first + second)
            assert lib.run("target_result", (mapped.outcome.value,), fuel=100).outcome == Ok(first + second)
            assertion = kernel.evaluate(bridge_defn(lib.get("relocate_12").spec).body,
                                        {"x": state}, lib.scope(), kernel.Limits(fuel=100))
            assert assertion.outcome == mapped.outcome and assertion.steps == 25
    valid = machine.to_card(relocation_start(0, 1))
    for invalid in (machine.poke(valid, 1, 27), machine.poke(valid, 31, 2),
                    machine.set_pc(valid, 1)):
        assert lib.run("relocate_12", (invalid,), fuel=100).outcome == Bottom("outside_domain")
    source = machine.to_card(initial(RESTORE, (1, 2, 3)))
    for operand in (29, 30, 31):
        for previous in (32, 29):
            state = machine.poke(source, 7, previous)
            actual = lib.run(f"retarget_{operand}", (state,), fuel=100)
            assert actual.outcome == Ok(machine.poke(state, 7, operand)) and actual.steps == 1


def test_random_boundaries_and_read_only_probes():
    from opulse.atoms.verify import unfold_equivalent
    from opulse.meta.worlds.vonneumann.story import creation_story

    lib, _ = creation_story()
    rng = random.Random(41829)
    for _ in range(12):
        state = machine.to_card(relocation_start(rng.randrange(2), rng.randrange(2)))
        for name in ("source_result", "relocate_add", "next_op"):
            run = lib.run(name, (state,), fuel=100, trace=True)
            expanded = kernel.evaluate(kernel.inline(nodes.Call(name, (nodes.Lit(state),)), lib.scope()),
                                       scope=lib.scope(), limits=kernel.Limits(fuel=100))
            assert run.outcome == expanded.outcome and run.steps == expanded.steps
            boundaries = [Boundary(), Boundary.unfold_all(), Boundary(depth=rng.randrange(1, 5)),
                          Boundary(open_names=frozenset({name}))]
            assert unfold_equivalent(run.trace, boundaries).ok
        for probe, args in (("pc", (state,)), ("a", (state,)), ("halted", (state,)),
                            ("cell", (state, 0))):
            assert isinstance(lib.run(probe, args).outcome, Ok)
            assert machine.from_card(state) == relocation_start(
                machine.from_card(state).mem[28], machine.from_card(state).mem[29])


def test_export_examples_are_distinct():
    examples = [(entry["name"], json.dumps(entry["examples"][0]["inputs"], sort_keys=True),
                 json.dumps(entry["examples"][0]["outcome"], sort_keys=True),
                 entry["examples"][0]["steps"]) for entry in build_export()["story"]]
    for index, first in enumerate(examples):
        for second in examples[index + 1:]:
            assert first[1:] != second[1:], (first[0], second[0])
