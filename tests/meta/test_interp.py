"""Exact vn/1 translation checks (docs/spec/atoms-meta.md, section 5)."""

import random
from dataclasses import replace
from itertools import product
from statistics import mean

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import (
    PipelineError,
    VerifyRequest,
    atoms_digest,
    checked_scope,
)
from opulse.atoms.spec import Contract
from opulse.atoms.values import Bottom, Card, Ok
from opulse.meta.code import lst
from opulse.meta.compiler.interp import (
    _unfolded_interpreter,
    expected,
    make_library,
    verify_library,
)
from opulse.meta.vn import reference

FAMILY_DESCRIPTION = ("bounded vn/1 n=16, fuel=12: all opcodes 0..9, operands "
                      "{0,1,2,3,15}, a {0,1,255}, plus 3000 seeded 20261104 "
                      "opcodes 0..9, operands 0..15, a {0,1,255}")


def _memory(*code, size=16):
    return lst(tuple(code) + (0,) * (size - len(code)))


def _family():
    operands = (0, 1, 2, 3, 15)
    for op0, arg0, op1, arg1, acc in product(range(10), operands, range(10), operands,
                                             (0, 1, 255)):
        yield _memory(op0, arg0, op1, arg1), acc, 0, 12
    randomizer = random.Random(20261104)
    for _ in range(3000):
        yield (_memory(randomizer.randrange(10), randomizer.randrange(16),
                       randomizer.randrange(10), randomizer.randrange(16)),
               randomizer.choice((0, 1, 255)), 0, 12)


@pytest.fixture(scope="module")
def verified_family():
    domain = tuple(_family())
    library = make_library()
    verify_library(library, domain, FAMILY_DESCRIPTION)
    return library, domain


def test_kernel_definitions_and_pipeline():
    library = make_library()
    definitions = library.definitions
    for name, layer in (("fetch", 1), ("exec_one", 1), ("vn_interp", 2)):
        assert definitions[name].origin == "invented"
        assert definitions[name].layer == layer
        assert isinstance(definitions[name].body, n.NODE_TYPES)
    assert next(op for op in library.world.operations if op.name == "fail_illegal").output.sort == "list"
    assert definitions["exec_one"].spec.output.sort == "list"
    rec = definitions["vn_interp"].body
    assert isinstance(rec, n.Rec) and rec.measure == n.Var("remaining")
    assert library.run("exec_one", (_memory(9, 0), 0, 0, 9)).outcome == Bottom("illegal")
    assert library.run("exec_one", (_memory(255, 0), 0, 0, 255)).outcome == Bottom("illegal")
    domain = ((_memory(0, 0), 0, 0, 12), (_memory(9, 0), 1, 0, 12),
              (_memory(6, 0), 255, 0, 12), (_memory(1, 255, 0), 0, 0, 12))
    verify_library(library, domain)
    for name in ("fetch", "exec_one", "vn_interp"):
        definition = library.get(name)
        assert definition.status == "promoted"
        assert definition.evidence.method == "bounded"
        assert definition.evidence.checks == ("reference", "unfold_equivalence")
        assert definition.evidence.atoms_hash == atoms_digest(library.atoms)
        assert definition.cost.steps["min"] <= definition.cost.steps["mean"] <= definition.cost.steps["max"]


def test_verified_interpreter_evidence_rejects_changed_atoms():
    library = make_library()
    sample = (_memory(0, 0), 0, 0, 4)
    library.verify("vn_interp", VerifyRequest("bounded", (sample,),
                   {"domain": "one n=16 HALT, fuel=4", "size": 1}, reference=expected))
    library.atoms = tuple(replace(atom, fn=lambda left, right: left - right)
                          if atom.name == "add" else atom for atom in library.atoms)
    with pytest.raises(PipelineError, match="promote requires verified status"):
        library.promote("vn_interp", Contract("Only the recorded HALT input"))
    assert library.get("vn_interp").status == "callable"
    assert library.get("vn_interp").evidence is None


def test_interpreter_evidence_records_exact_checked_domain():
    library = make_library()
    sample = (_memory(0, 0), 0, 0, 4)
    verified = library.verify("vn_interp", VerifyRequest(
        "bounded", (sample,), {"domain": "one n=16 HALT, fuel=4", "size": 1}, reference=expected))
    assert verified.evidence.scope["checked"] == {**checked_scope((sample,)), "by": "library"}
    assert library.promote("vn_interp", Contract("Only the recorded HALT input")).status == "promoted"


def test_integer_primitives_and_exact_trace():
    library = make_library()
    scope = library.scope()
    assert scope.resolve("mod").fn(9, 0) == Bottom("div_zero")
    assert scope.resolve("list_get").fn(_memory(0), 16) == Bottom("index")
    assert scope.resolve("list_set").fn(_memory(0), -1, 5) == Bottom("index")
    assert scope.resolve("is_zero").fn(0) == Card("bool", "true")
    for code, steps, result in (([0, 0], 5, "ok"), ([9, 0], 5, "err"),
                                ([1, 5, 0, 0], 25, "ok"), ([6, 0], 290, "out")):
        run = library.run("vn_interp", (_memory(*code), 0, 0, 12), trace=True)
        assert run.steps == steps
        assert isinstance(run.outcome, Ok) and run.outcome.value.tag == result
        assert run.trace.steps == steps
        assert run.outcome.value == expected(_memory(*code), 0, 0, 12)
    assert library.run("vn_interp", (_memory(0), 0, 0, 0)).outcome == Ok(
        Card("result", "out", ("fuel",)))


def test_instruction_trace_is_exactly_layer_zero():
    library = make_library()

    def leaves(frame):
        if frame.given:
            yield frame.name, frame.steps
        for child in frame.children:
            yield from leaves(child)

    for code, names in (
        ((0, 0), ("is_zero", "list_get", "eq", "list_set", "list_set_list", "compose")),
        ((9, 0), ("is_zero", "list_get", "eq", "lt", "list_set_str", "compose")),
    ):
        run = library.run("vn_interp", (_memory(*code), 0, 0, 12), trace=True)
        assert tuple(leaves(run.trace)) == tuple((name, 0 if name == "compose" else 1)
                                                 for name in names)
        assert run.trace.children[0].name == "vn_interp"
        assert run.trace.children[0].steps == run.steps == 5


def test_bounded_two_instruction_programs_n16(verified_family):
    """All 7,500 programs over operands 0,1,2,3,15 plus 3,000 seeded cases."""
    library, domain = verified_family
    definition = library.get("vn_interp")
    assert definition.evidence.checks == ("reference", "unfold_equivalence")
    costs = library._steps["vn_interp"]
    assert len(domain) == len(costs)
    assert len(costs) == 10_500
    assert (min(costs), max(costs), mean(costs)) == (5, 332, 280009 / 5250)


def test_reused_unfolding_matches_per_input_unfolding(verified_family):
    library, domain = verified_family
    scope = library.scope()
    expanded, params = _unfolded_interpreter(scope)
    for args in random.Random(20261104).sample(domain, 32):
        direct = kernel.call("vn_interp", args, scope)
        reused = kernel.evaluate(expanded, dict(zip(params, args)), scope)
        original = kernel.inline(n.Call("vn_interp", tuple(n.Lit(arg) for arg in args)), scope)
        per_input = kernel.evaluate(original, scope=scope)
        assert (reused.outcome, reused.steps) == (per_input.outcome, per_input.steps)
        assert (direct.outcome, direct.steps) == (reused.outcome, reused.steps)


def test_bounded_verifier_rejects_reference_counterexample():
    library = make_library()
    request = VerifyRequest("bounded", ((_memory(0, 0), 0, 0, 12),),
                            {"domain": "bounded n=16, one invalid reference", "size": 1},
                            reference=lambda *_: Card("result", "out", ("fuel",)))
    with pytest.raises(PipelineError, match="reference counterexample"):
        library.verify("vn_interp", request)
    assert library.get("vn_interp").status == "callable"


@pytest.mark.slow
def test_family_bounded_evidence_and_cost(verified_family):
    library, domain = verified_family
    definition = library.get("vn_interp")
    assert definition.status == "promoted"
    assert len(domain) == 10_500
    assert definition.evidence.scope["size"] == 10_500
    assert definition.cost.steps == {
        "min": 5, "max": 332, "mean": 280009 / 5250,
        "over": {"domain": FAMILY_DESCRIPTION, "size": 10_500,
                 "checked": {**checked_scope(domain), "by": "library"}},
    }


def test_self_modifying_array_sum():
    # LDI 0; ST 50: clear the accumulator cell.
    # LDI 40; ST 17: patch the ADD operand to the first array address.
    # JMP 14: enter the loop.
    # LD 50; ADD 40; ST 50: add the element addressed by the patched operand.
    # LD 17; ADD 52; ST 17: advance the operand byte of ADD by one.
    # SUB 53; JZ 34; JMP 14: stop after address 43.
    # HALT (unreached padding); LD 50; HALT: return the sum.
    code = (1, 0, 3, 50, 1, 40, 3, 17, 6, 14,
            0, 0, 0, 0, 2, 50, 4, 40, 3, 50,
            2, 17, 4, 52, 3, 17, 5, 53, 7, 34,
            6, 14, 0, 0, 2, 50, 0, 0)
    data = {40: 2, 41: 3, 42: 5, 43: 7, 52: 1, 53: 44}
    machine = reference.load(code, 64, data)
    status, final, instructions = reference.run(machine, 100)
    assert status == "ok" and instructions == 42
    assert final.a == 17 and final.mem[17] == 44 and final.mem[50] == 17
    library = make_library()
    run = library.run("vn_interp", (lst(machine.mem), machine.a, machine.pc, 100))
    assert run.outcome == Ok(Card("result", "ok", (final.a, lst(final.mem))))
