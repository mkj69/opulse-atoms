"""Exact checks for the stored-program creation story (atoms-meta 4, 7)."""

import json
from pathlib import Path

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.laws import RewriteError, replay_rewrite, rewrite
from opulse.atoms.library import PipelineError, VerifyRequest, atoms_digest
from opulse.atoms.spec import Contract, Definition, ObjectSpec
from opulse.atoms.templates import cite_template_evidence
from opulse.atoms.values import Bottom, Card, Ok, boolean, outcome_equal
from opulse.atoms.world import WorldDecl
from opulse.meta.check import export_problems
from opulse.meta.code import (
    Resolved,
    canonicalize,
    decode,
    encode_node,
    instantiate_code,
    quote_from_library,
)
from opulse.meta.engine import call as meta_call
from opulse.meta.engine import eval_atom
from opulse.meta.export_util import outcome_json, trace_json, value_json
from opulse.meta.vn import machine, reference
from opulse.meta.vn.report import report
from opulse.meta.worlds.vonneumann.export import build_export
from opulse.meta.worlds.vonneumann.routines import Routine, RoutineDomain, RoutineLedger
from opulse.meta.worlds.vonneumann.showcase import (
    COMPUTE_CODE,
    COMPUTE_DATA,
    DECIDE_CODE,
    INVERT_CODE,
    INVERT_DATA,
    compute,
    decide,
    invert,
    tasks,
)
from opulse.meta.worlds.vonneumann.story import (
    RELOCATED,
    RESTORE,
    SMALL,
    SUM,
    VNLibrary,
    again,
    creation_story,
    evidence,
    initial,
    relocation_evidence,
    relocation_start,
    restore_again,
)
from opulse.meta.worlds.vonneumann.world import LADDER, declaration

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def story():
    return creation_story()


def test_declaration_and_export_are_current():
    raw = json.loads((ROOT / "worlds/decl/meta/vonneumann@1.json").read_text())
    assert raw == declaration().to_dict()
    assert WorldDecl.from_dict(raw).to_dict() == raw
    exported = json.loads((ROOT / "docs/assets/data/meta/vonneumann.json").read_text())
    assert exported == build_export()
    assert export_problems(exported, ROOT / "docs/assets/data/meta/vonneumann.json", strict=True) == []
    assert all(entry["ascii"].isascii() and all(example["ascii"].isascii()
               for example in entry["examples"]) for entry in exported["story"])
    assert next(entry for entry in exported["story"] if entry["name"] == "retarget_operand")[
        "ascii"] == "template op retarget_operand[operand: int] = patch_operand(s, 7, operand) L1"
    assert exported["schema"] == "opulse.world_v2_export/1"
    assert len(LADDER) == 5 and len(exported["showcase"]) == 3
    assert "#law scope 3 images" in LADDER[4]["knobs"]
    assert "~bridge scope 4 inputs" in LADDER[4]["knobs"]
    twice = next(item for item in exported["story"] if item["name"] == "twice_run")
    assert twice["examples"][0]["inputs"][0] == value_json(kernel.FnRef("step"))
    assert raw["operations"][0]["impl"] == machine._host_rule(machine.step)
    example = machine.run(machine.to_card(initial(SUM, (1, 3, 2))), 100)
    assert next(item for item in exported["story"] if item["name"] == "sum3_loop")[
        "examples"][0]["outcome"] == outcome_json(example.outcome)
    assert trace_json(example.trace) is None


def test_committed_host_digests_cover_all_declared_kinds():
    raw = json.loads((ROOT / "worlds/decl/meta/vonneumann@1.json").read_text())
    current = declaration().to_dict()
    assert raw["lock"]["host_digests"] == current["lock"]["host_digests"]
    assert raw["objects"] == current["objects"]
    assert raw["operations"] == current["operations"]
    assert raw["observation"] == current["observation"]


def test_sum_exhaustive_scope_and_code_identity():
    ledger = evidence()
    first_evidence, changed, contract = ledger.record(SUM)
    assert first_evidence.method == "exhaustive" and first_evidence.scope["size"] == 4096
    assert changed == {3, 27, 28} and {str(address) for address in changed} <= set(contract.may_change)
    state = initial(SUM, (1, 2, 3))
    execution = report(state, 100)
    assert execution.self_modifying and execution.writes_ahead and execution.writes_behind
    assert len(execution.versions) == 4
    first = machine.run(machine.to_card(state), 100)
    assert first.steps == 34 and isinstance(first.outcome, Ok)
    final = machine.from_card(first.outcome.value)
    assert (final.a, final.mem[3], final.mem[28]) == (6, 32, 6)
    changed_routine = Routine(0, final.mem[:len(SUM.code)])
    assert ledger.identity(changed_routine) != ledger.identity(SUM)
    assert ledger.record(changed_routine) is None
    second = machine.run(machine.to_card(again(final)), 100)
    assert second.steps == 34 and machine.from_card(second.outcome.value).a == 34
    with pytest.raises(ValueError, match="contract omits"):
        fresh = RoutineLedger(declaration())
        fresh.verify(SUM, RoutineDomain.product("one triple", ((1,), (2,), (3,)),
                                                lambda values: initial(SUM, values)),
                     lambda s, f: (reference.run(s, f)[1], 34))
        fresh.promote(SUM, Contract("incomplete", ("27", "28")))


def test_routine_domain_rejects_forged_coverage_and_missing_changes():
    ledger = RoutineLedger(declaration())
    zero = initial(SUM, (0, 0, 0))
    with pytest.raises(TypeError, match="declared domain"):
        ledger.verify(SUM, [zero], lambda s, fuel: reference.run(s, fuel)[1:],
                      description="all 4096 triples in 0..15")
    domain = RoutineDomain.product("all 4096 triples", (range(16),) * 3,
                                   lambda values: initial(SUM, values))
    with pytest.raises(ValueError, match="size"):
        ledger.verify(SUM, domain, lambda s, fuel: reference.run(s, fuel)[1:], claimed_size=1)
    assert ledger.verify(SUM, domain, lambda s, fuel: reference.run(s, fuel)[1:]).scope["size"] == 4096
    with pytest.raises(ValueError, match="contract omits"):
        ledger.promote(SUM, Contract("incomplete", ("3", "27")))


def test_routine_promotion_rejects_changed_atom_implementation(monkeypatch):
    ledger = RoutineLedger(declaration())
    domain = RoutineDomain.product("one triple", ((0,),) * 3,
                                   lambda values: initial(SUM, values))
    proof = ledger.verify(SUM, domain, lambda state, fuel: reference.run(state, fuel)[1:])
    assert proof.atoms_hash == machine.atoms_hash(32)
    original_atoms = machine.atoms

    def changed_atoms(size):
        atoms = original_atoms(size)
        return (kernel.Atom(atoms[0].name, atoms[0].arity, lambda state: state, atoms[0].cost),
                *atoms[1:])

    monkeypatch.setattr(machine, "atoms", changed_atoms)
    with pytest.raises(ValueError, match="routine atoms hash changed"):
        ledger.promote(SUM, Contract("zero", ("3", "27")))


@pytest.mark.parametrize("change", ("wrapper", "helper", "cost"))
def test_routine_promotion_pins_transitive_source_and_cost(monkeypatch, change):
    ledger = RoutineLedger(declaration())
    domain = RoutineDomain.product("one pair", ((1,), (2,)),
                                   lambda values: relocation_start(*values))
    proof = ledger.verify(SMALL, domain, lambda state, fuel: reference.run(state, fuel)[1:])
    original_hash = proof.atoms_hash
    if change == "wrapper":
        original = machine._OPERATIONS
        monkeypatch.setattr(machine, "_OPERATIONS", (
            ("step", lambda state: state, 1, 1, "vn", "transform", ("illegal",)),
            *original[1:]))
    elif change == "helper":
        monkeypatch.setattr(reference, "step", lambda state: state)
    else:
        original = machine._OPERATIONS
        name, fn, arity, cost, result, role, errors = original[0]
        monkeypatch.setattr(machine, "_OPERATIONS", (
            (name, fn, arity, cost + 1, result, role, errors), *original[1:]))
    assert machine.atoms_hash(32) != original_hash
    with pytest.raises(ValueError, match="routine atoms hash changed"):
        ledger.promote(SMALL, Contract("adds 1 and 2", ()))
    assert ledger.record(SMALL)[2] is None


def test_vn_host_digest_pins_reference_helper(monkeypatch):
    before = declaration()
    monkeypatch.setattr(reference, "step", lambda state: state)
    after = declaration()
    assert after.operations[0].impl["digest"] != before.operations[0].impl["digest"]
    assert after.world_hash() != before.world_hash()


def test_vn_host_digest_pins_reference_source(monkeypatch):
    before = declaration()
    atoms_hash = machine.atoms_hash(32)
    original_getsource = machine.inspect.getsource

    def changed_source(value):
        source = original_getsource(value)
        return source + "\n# Changed reference source\n" if value is reference else source

    monkeypatch.setattr(machine.inspect, "getsource", changed_source)
    assert declaration().operations[0].impl["digest"] != before.operations[0].impl["digest"]
    assert machine.atoms_hash(32) != atoms_hash


def test_vn_template_instance_quote(story):
    lib, _ = story
    template = quote_from_library(lib, "retarget_operand")
    instance = quote_from_library(lib, "retarget_29")
    generated = instantiate_code(template, (29,),
                                 lambda name: Resolved(code=quote_from_library(
                                     lib, "retarget_operand" if name == "template_source" else name))
                                 if name in ("patch_operand", "template_source") else None,
                                 name="retarget_29")
    assert canonicalize(template) == template
    assert canonicalize(instance) == instance
    assert generated == instance
    decoded = decode(instance)
    assert decoded.kind == "operation"
    state = machine.poke(machine.to_card(initial(RESTORE, (1, 2, 3))), 7, 32)
    quoted = kernel.call(decoded.main.name, (state,),
                         kernel.DictScope(lib.atoms, (decoded.main, *decoded.deps)),
                         kernel.Limits(fuel=100))
    direct = lib.run("retarget_29", (state,), fuel=100)
    assert quoted.outcome == direct.outcome == Ok(machine.poke(state, 7, 29))
    assert quoted.steps == direct.steps == 1
    evaluated = meta_call("eval", (canonicalize(generated), Card("list", "items", (state,))),
                          kernel.DictScope((eval_atom(lib.atoms, dict(decoded.atoms)),)),
                          kernel.Limits(fuel=100))
    assert evaluated.outcome == direct.outcome
    assert evaluated.steps == direct.steps == 1


def test_vn_library_promotion_rejects_changed_atom_implementation():
    lib = VNLibrary(declaration(), machine.atoms(32))
    body = nodes.Lit(7)
    definition = Definition("seven", "object", "invented", 1, (),
                            ObjectSpec("seven", "constant", body=body), body)
    lib.write(definition)
    lib.check("seven")
    lib.make_callable("seven", [()])
    lib.verify("seven", VerifyRequest("bounded", ((),),
                                      {"domain": "one constant", "size": 1},
                                      extra={"values": [7]}))
    lib.account("seven")
    assert lib.get("seven").evidence.atoms_hash == atoms_digest(lib.atoms)
    lib.atoms = (*lib.atoms, kernel.Atom("new_atom", 0, lambda: 7))
    assert lib.get("seven").status == "callable" and lib.get("seven").evidence is None
    with pytest.raises(PipelineError, match="promote requires verified status"):
        lib.promote("seven", Contract("returns seven"))


def test_routine_second_call_is_derived_and_evidence_is_immutable():
    ledger = RoutineLedger(declaration())
    domain = RoutineDomain.product("zero", ((0,),) * 3,
                                   lambda values: initial(SUM, values))

    def disconnected(state, fuel):
        _, first, steps = reference.run(state, fuel)
        _, second, second_steps = reference.run(initial(SUM, (1, 2, 3)), fuel)
        return first, steps, initial(SUM, (1, 2, 3)), second, second_steps

    with pytest.raises(ValueError, match="second call"):
        ledger.verify(SUM, domain, disconnected, reset=again, reset_addresses=(3, 27, 28))
    with pytest.raises(ValueError, match="second call"):
        ledger.verify(SUM, domain, lambda state, fuel: reference.run(state, fuel)[1:],
                      reset=lambda final: initial(SUM, (1, 2, 3)),
                      reset_addresses=(3, 27, 28))
    restored = RoutineDomain.product("one restored triple", ((1,), (2,), (3,)),
                                     lambda values: initial(RESTORE, values))
    with pytest.raises(ValueError, match="routine identity"):
        ledger.verify(RESTORE, restored, lambda state, fuel: reference.run(state, fuel)[1:],
                      reset=lambda final: reference.State(0, 0, final.mem[:27] + (0,) + final.mem[28:]),
                      reset_addresses=(27,))
    proof = ledger.verify(SUM, domain, lambda state, fuel: reference.run(state, fuel)[1:])
    promoted = ledger.promote(SUM, Contract("zero", ("3", "27")))
    proof.scope["size"] = 99
    promoted[0].scope["size"] = 98
    promoted[0].scope["domain"]["product_axes"][0][0] = 99
    ledger.record(SUM)[0].scope["size"] = 97
    assert ledger.record(SUM)[0].scope["size"] == 1
    assert ledger.record(SUM)[0].scope["domain"]["product_axes"] == [[0], [0], [0]]


def test_restore_prologue_repeated_calls_full_state():
    ledger = evidence()
    proof, changed, contract = ledger.record(RESTORE)
    assert proof.method == "exhaustive" and proof.scope["size"] == 64
    assert changed == {7, 27} and "7" in contract.may_change
    first = machine.run(machine.to_card(initial(RESTORE, (1, 2, 3))), 100)
    assert first.steps == 30 and machine.from_card(first.outcome.value).a == 6
    second_start = restore_again(machine.from_card(first.outcome.value))
    assert second_start.mem[7] == 29
    second = machine.run(machine.to_card(second_start), 100)
    assert second.steps == 30 and machine.from_card(second.outcome.value).a == 6
    assert report(second_start, 100).self_modifying


def test_library_story_unfolding_and_probes(story):
    lib, definitions = story
    assert all(definition.evidence.atoms_hash == atoms_digest(lib.atoms) for definition in definitions)
    assert "reference" in lib.get("next_op").evidence.checks
    assert len(definitions) >= 6 and {d.kind for d in definitions} >= {
        "object", "operation", "observation", "combinator"}
    assert {d.layer for d in definitions} == {1, 2, 3, 4, 5}
    assert all(d.status == "promoted" and d.evidence.method in ("bounded", "exhaustive")
               and d.contract for d in definitions)
    state = machine.to_card(initial(SUM, (1, 2, 3)))
    for definition in definitions:
        if definition.kind in ("law", "bridge", "template"):
            continue
        if definition.name == "fix":
            args = (kernel.FnRef("reset_operand"),
                    machine.poke(machine.to_card(initial(RESTORE, (1, 2, 3))), 7, 32), 2)
        elif definition.kind == "combinator":
            from opulse.atoms.kernel import FnRef
            args = (FnRef("step"), state)
        else:
            args = (() if definition.kind == "object" else
                    (state, 3, 32) if definition.name == "patch_operand" else
                    (machine.to_card(relocation_start(1, 2)),) if definition.name in (
                        "copy_six", "relocate_add", "relocate_variant", "run_variant", "variant_result",
                        "source_result") else
                    (lib.run("relocate_add", (machine.to_card(relocation_start(1, 2)),)).outcome.value,)
                    if definition.name == "target_result" else
                    (machine.poke(machine.to_card(initial(RESTORE, (1, 2, 3))), 7, 32),)
                    if definition.name in ("reset_operand", "rerun_restored", "retarget_29",
                                           "retarget_30", "retarget_31") else (state,))
        actual = lib.run(definition.name, args, fuel=100)
        unfolded = kernel.evaluate(kernel.inline(nodes.Call(definition.name,
                                tuple(nodes.Lit(arg) for arg in args)), lib.scope()),
                                    scope=lib.scope(), limits=kernel.Limits(fuel=100))
        assert outcome_equal(actual.outcome, unfolded.outcome) and actual.steps == unfolded.steps
    assert lib.run("next_op", (state,)).outcome == Ok(2)
    assert lib.run("twice_run", (kernel.FnRef("step"), state)).steps == 2
    assert lib.run("patch_operand", (state, 3, 32)).outcome == Ok(machine.poke(state, 3, 32))
    assert machine.from_card(lib.run("rerun_restored", (
        machine.poke(machine.to_card(initial(RESTORE, (1, 2, 3))), 7, 32),)).outcome.value).a == 6
    unequal = machine.to_card(reference.load(SMALL.code, 32, {28: 3, 29: 1, 30: 3, 31: 3}))
    original = lib.run("relocate_add", (unequal,)).outcome.value
    normal = machine.run(machine.set_pc(original, 12), 100)
    assert machine.from_card(normal.outcome.value).a == 6
    assert lib.run("variant_result", (unequal,)).outcome == Ok(4)
    assert machine.from_card(state) == initial(SUM, (1, 2, 3))


def test_quote_eval_law_for_callable_story_definitions(story):
    lib, definitions = story
    state = machine.to_card(initial(SUM, (1, 2, 3)))
    for definition in definitions:
        if definition.kind in ("observation", "law", "bridge", "template") or definition.name == "fix" or \
                "retarget_operand" in definition.depends_on:
            continue
        code = quote_from_library(lib, definition.name)
        decoded = decode(code)
        args = ((kernel.FnRef("step"), state) if definition.kind == "combinator" else
                () if definition.kind == "object" else (state, 3, 32)
                if definition.name == "patch_operand" else
                (machine.to_card(relocation_start(1, 2)),) if definition.name in (
                    "copy_six", "relocate_add", "relocate_variant", "run_variant", "variant_result",
                    "source_result") else
                (lib.run("relocate_add", (machine.to_card(relocation_start(1, 2)),)).outcome.value,)
                if definition.name == "target_result" else
                (machine.poke(machine.to_card(initial(RESTORE, (1, 2, 3))), 7, 32),)
                if definition.name in ("reset_operand", "rerun_restored", "retarget_29",
                                       "retarget_30", "retarget_31") else (state,))
        quoted = kernel.call(decoded.main.name, args, kernel.DictScope(lib.atoms,
                                                                       (decoded.main, *decoded.deps)),
                             kernel.Limits(fuel=100))
        direct = lib.run(definition.name, args, fuel=100)
        assert outcome_equal(quoted.outcome, direct.outcome) and quoted.steps == direct.steps
        arguments = Card("list", "items", tuple(
            encode_node(nodes.Lit(arg)) if isinstance(arg, kernel.FnRef) else arg for arg in args))
        eval_given = eval_atom(lib.atoms, dict(decoded.atoms))
        evaluated = meta_call("eval", (code, arguments), kernel.DictScope((eval_given,)),
                              kernel.Limits(fuel=100))
        assert outcome_equal(evaluated.outcome, direct.outcome) and evaluated.steps == direct.steps


def test_quoted_observation_is_not_callable(story):
    lib, _ = story
    code = quote_from_library(lib, "next_op")
    atom = eval_atom(machine.atoms(32))
    arguments = Card("list", "items", ())
    assert meta_call("eval", (code, arguments), kernel.DictScope((atom,))).outcome == Bottom("not_callable")


def test_scoped_repair_law_replay_and_false_near_miss(story):
    lib, _ = story
    repaired = machine.to_card(initial(RESTORE, (1, 2, 3)))
    broken = machine.poke(repaired, 7, 32)
    law = lib.get("restore_idempotent")
    assert law.evidence.method == "exhaustive"
    assert law.evidence.scope["size"] == 3
    assert law.evidence.scope["values"] == tuple(
        (json.dumps(value_json(state), sort_keys=True),) for state in
        (broken, repaired, machine.poke(repaired, 7, 0)))
    assert law.evidence.checks == ("holds", "equation")
    assert law.evidence.atoms_hash == atoms_digest(lib.atoms)
    assert lib.get("reset_is_identity").status == "callable"
    assert lib.get("reset_is_identity").evidence is None
    false_run = kernel.evaluate(lib.get("reset_is_identity").body, {"s": broken}, lib.scope())
    assert false_run.outcome == Ok(boolean(False))
    assert false_run.steps == 1 and machine.from_card(broken).mem[7] == 32
    assert machine.from_card(lib.run("reset_operand", (broken,)).outcome.value).mem[7] == 29
    original = nodes.Call("get_a", (nodes.Call("reset_operand", (
        nodes.Call("reset_operand", (nodes.Var("s"),)),)),))
    rewritten = rewrite(original, law, lib, at=(0,))
    assert rewritten == nodes.Call("get_a", (nodes.Call("reset_operand", (nodes.Var("s"),)),))
    derivation = replay_rewrite(original, rewritten, law, lib, {"s": broken}, fuel=100)
    assert derivation.charged_steps == 2 and len(derivation.steps) == 1
    assert derivation.steps[0].path == (0,) and derivation.steps[0].law == law.name
    assert kernel.evaluate(original, {"s": broken}, lib.scope()).outcome == Ok(0)
    assert kernel.evaluate(rewritten, {"s": broken}, lib.scope()).outcome == Ok(0)
    with pytest.raises(RewriteError, match="verified scope"):
        replay_rewrite(original, rewritten, law, lib,
                       {"s": machine.poke(repaired, 7, 31)}, fuel=100)
    exported = build_export()["near_misses"][0]
    assert exported["symbol"] == "#reset_is_identity" and exported["changed_operand"] == 29
    assert exported["status"] == "callable" and exported["steps"] == 1
    assert exported["outcome"] == outcome_json(false_run.outcome)
    replay = next(item for item in build_export()["story"]
                  if item["name"] == law.name)["derivation"]
    assert replay["law"] == "#restore_idempotent" and replay["path"] == [0]
    assert replay["rewrite_steps"] == 1 and replay["charged_steps"] == 2
    assert replay["outcome"] == outcome_json(Ok(0))
    assert replay["before"] == nodes.to_json(original)
    assert replay["after"] == nodes.to_json(rewritten)


def test_partial_relocation_bridge_commutes_only_on_its_recorded_scope(story):
    lib, _ = story
    bridge = lib.get("relocate_12")
    assert bridge.evidence.scope["size"] == 4
    assert bridge.evidence.scope["pairs_checked"] == 4
    assert bridge.evidence.checks == ("commutes", "total_on_domain")
    assert bridge.evidence.atoms_hash == atoms_digest(lib.atoms)
    for first in range(2):
        for second in range(2):
            source = machine.to_card(relocation_start(first, second))
            mapped = lib.run("relocate_12", (source,), fuel=100)
            assert isinstance(mapped.outcome, Ok) and mapped.steps == 25 and mapped.trace is None
            assert machine.from_card(mapped.outcome.value).mem[12:18] == RELOCATED.code
            assert lib.run("source_result", (source,), fuel=100).outcome == Ok(first + second)
            assert lib.run("target_result", (mapped.outcome.value,), fuel=100).outcome == Ok(
                first + second)
            assert mapped.outcome == kernel.evaluate(bridge_defn(bridge.spec).body,
                                                     {"x": source}, lib.scope(),
                                                     kernel.Limits(fuel=100)).outcome
    invalid = machine.poke(machine.to_card(relocation_start(0, 1)), 1, 27)
    assert lib.run("relocate_12", (invalid,), fuel=100).outcome == Bottom("outside_domain")
    unequal = machine.to_card(reference.load(SMALL.code, 32, {28: 3, 29: 1, 30: 3, 31: 3}))
    assert lib.run("relocate_12", (unequal,), fuel=100).outcome == Bottom("outside_domain")
    copied = lib.run("copy_six", (unequal,), fuel=100).outcome.value
    retargeted = lib.run("relocate_add", (unequal,), fuel=100).outcome.value
    assert lib.run("target_result", (copied,), fuel=100).outcome == Ok(4)
    assert lib.run("target_result", (retargeted,), fuel=100).outcome == Ok(6)


def test_operand_template_members_have_independent_evidence_and_identity(story):
    lib, definitions = story
    family = lib.get("retarget_operand")
    assert family.evidence.method == "bounded"
    assert family.evidence.scope["family"] == [{"operand": 29}, {"operand": 30},
                                                {"operand": 31}]
    assert family.evidence.checks == ("family",)
    state = machine.poke(machine.to_card(initial(RESTORE, (1, 2, 3))), 7, 32)
    members = [lib.get(f"retarget_{operand}") for operand in (29, 30, 31)]
    assert len({lib.content_hash(member.name) for member in members}) == 3
    assert all(member.evidence.scope["size"] == 2 and member.status == "promoted"
               and member.evidence.atoms_hash == atoms_digest(lib.atoms)
               and cite_template_evidence(member, lib) for member in members)
    assert all("retarget_operand" in member.depends_on for member in members)
    for operand in (29, 30, 31):
        actual = lib.run(f"retarget_{operand}", (state,), fuel=100)
        assert actual.outcome == Ok(machine.poke(state, 7, operand)) and actual.steps == 1
        assert decode(quote_from_library(lib, f"retarget_{operand}")).kind == "operation"
    assert len([definition for definition in definitions if definition.kind == "template"]) == 1


def test_repair_fixpoint_has_exact_height_and_unfolding_cost(story):
    lib, _ = story
    definition = lib.get("fix")
    assert definition.evidence.scope["finite_height"] == 2
    assert definition.evidence.scope["op_family"] == ["reset_operand"]
    repaired = machine.to_card(initial(RESTORE, (1, 2, 3)))
    broken = machine.poke(repaired, 7, 32)
    for state, height, result, steps in (
            (broken, 1, Bottom("not_stable"), 4),
            (broken, 2, Ok(repaired), 5),
            (repaired, 1, Ok(repaired), 2)):
        actual = lib.run("fix", (kernel.FnRef("reset_operand"), state, height), fuel=100)
        assert actual.outcome == result and actual.steps == steps and actual.trace is None
        expanded = kernel.evaluate(kernel.inline(nodes.Call("fix", (
            nodes.Lit(kernel.FnRef("reset_operand")), nodes.Lit(state), nodes.Lit(height))),
            lib.scope()), scope=lib.scope(), limits=kernel.Limits(fuel=100))
        assert actual.outcome == expanded.outcome and actual.steps == expanded.steps


def test_relocation_creates_new_identity_and_requires_new_proof(story):
    ledger = RoutineLedger(declaration())
    scope = relocation_evidence(ledger)
    assert ledger.identity(SMALL) != ledger.identity(RELOCATED)
    assert ledger.record(SMALL)[0].scope["size"] == 16
    assert ledger.record(RELOCATED)[0].scope["size"] == 16
    lib, _ = story
    for state in scope:
        changed = machine.from_card(lib.run("relocate_add", (machine.to_card(state),)).outcome.value)
        relocated = Routine(12, changed.mem[12:18])
        assert relocated == RELOCATED
        assert ledger.record(relocated) is not None
        assert ledger.record(Routine(12, changed.mem[12:16])) is None
        variant = machine.from_card(lib.run("relocate_variant", (machine.to_card(state),)).outcome.value)
        assert ledger.record(Routine(12, variant.mem[12:18])) is None
        start = reference.State(12, 0, changed.mem)
        status, final, steps = reference.run(start, 100)
        actual = machine.run(machine.to_card(start), 100)
        assert status == "ok" and steps == 3 and actual.steps == steps
        assert actual.outcome == Ok(machine.to_card(final))
        assert final.a == (state.mem[30] + state.mem[31]) % 256


def test_showcase_exact_answers_and_completeness(story):
    assert compute() == (24, 10)
    compute_state = reference.load(COMPUTE_CODE, 32, COMPUTE_DATA)
    computed = report(compute_state, 30)
    assert computed.writes_ahead and computed.self_modifying
    assert machine.from_card(computed.outcome.value).mem[16] == 5
    status, final, exact_steps = reference.run(compute_state, 30)
    assert status == "ok" and exact_steps == 10 and computed.outcome == Ok(machine.to_card(final))
    verdict, outcome, steps = decide()
    assert verdict is True and isinstance(outcome, Ok) and steps == 19
    decision = report(reference.load(DECIDE_CODE, 32), 40)
    assert decision.writes_ahead is True and decision.writes_behind is False
    assert len(decision.versions) == 3 and decision.stores[-1] == (17, 30, 8, 0)
    assert decision.outcome == outcome
    lib, _ = story
    assert lib.run("next_op", (outcome.value,)).outcome == Ok(0)
    assert invert() == [50, 83, 100, 178]
    matches = []
    for byte in range(256):
        state = reference.load(INVERT_CODE, 32, {**INVERT_DATA, 29: byte})
        result = machine.run(machine.to_card(state), 20)
        assert isinstance(result.outcome, Ok)
        reference_status, final, count = reference.run(state, 20)
        assert reference_status == "ok" and result.steps == count
        assert result.outcome == Ok(machine.to_card(final))
        if final.a == 100:
            matches.append(byte)
    assert matches == tasks()[2]["answer"]
    assert tasks()[0]["answer"] == [24, 10] and tasks()[1]["answer"] is True
    assert "versions=3" in tasks()[1]["check"]


def test_export_prompts_scope_and_visibility(story):
    payload = build_export()
    assert payload["tags"]["visibility"] == "full"
    assert all("0 hidden cells" in level["knobs"] for level in payload["ladder"])
    assert [task["angle"] for task in payload["showcase"]] == ["Compute", "Decide", "Invert"]
    assert all("all other cells are 0" in task["prompt"] and task["kinds_involved"]
               for task in payload["showcase"])
    assert "mem[15]=0" in payload["showcase"][2]["prompt"]
    other_fill = reference.load(INVERT_CODE, 32, {**INVERT_DATA, 15: 1, 29: 100})
    assert reference.run(other_fill, 20)[1].a != 100
    examples = {entry["name"]: entry["examples"][0] for entry in payload["story"]}
    assert examples["run_routine"]["inputs"] != examples["sum_routine"]["inputs"]
    assert all(examples[name]["outside_scope"] for name in
               ("reset_operand", "rerun_restored", "relocate_add", "relocate_variant",
                "variant_result"))
    assert examples["run_variant"]["outside_scope"] is True
    assert examples["run_variant"]["callee_scope"]["name"] == "relocate_variant"
    assert examples["run_variant"]["callee_scope"]["outside_scope"] is True
    assert {item["name"] for item in examples["run_variant"]["callee_scopes"]} >= {
        "relocate_variant", "relocate_add"}
    lib, _ = story
    example_input = machine.to_card(relocation_start(3, 1))
    assert lib.get("run_variant").evidence.scope["size"] == 3
    assert lib.get("relocate_variant").evidence.scope["size"] == 2
    assert lib.get("run_variant").evidence.scope["fingerprint"] != lib.get(
        "relocate_variant").evidence.scope["fingerprint"]
    assert example_input != machine.to_card(relocation_start(1, 2))
    assert example_input != machine.to_card(reference.load(SMALL.code, 32,
                                                          {28: 3, 29: 1, 30: 3, 31: 3}))
    assert lib.run("run_variant", (example_input,), fuel=100).outcome == Ok(
        machine.to_card(reference.run(machine.from_card(machine.set_pc(
            lib.run("relocate_variant", (example_input,)).outcome.value, 12)), 100)[1]))
    assert all(entry["definition"].endswith(".") for entry in payload["story"])
