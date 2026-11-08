"""Invented VN definitions and self-modifying routines (atoms-meta 4, 7)."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.bridges import bridge_defn
from opulse.atoms.combinators import fix_spec
from opulse.atoms.library import (
    Library,
    PipelineError,
    VerifyRequest,
    atoms_digest,
    checked_scope,
)
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Contract,
    Definition,
    Edge,
    Evidence,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.templates import instantiate
from opulse.atoms.values import Card, Ok, outcome_equal
from opulse.meta.export_util import input_hash
from opulse.meta.vn import machine, reference
from opulse.meta.vn.asm import assemble
from opulse.meta.worlds.vonneumann.routines import Routine, RoutineDomain, RoutineLedger
from opulse.meta.worlds.vonneumann.world import declaration, decrement, equal, positive

SUM_SOURCE = """\
LD 28       ; Restore the accumulated total for the next item.
ADD 29      ; Add the item at the operand byte, address 3.
ST 28       ; Save the new total.
LD 3        ; Read the ADD operand from the code.
ADDI 1      ; Advance the address without an index register.
ST 3        ; Rewrite the ADD operand in place.
LD 27       ; Read the remaining-item counter.
ADDI 255    ; Subtract one modulo 256.
ST 27       ; Save the remaining-item counter.
JZ @done    ; Stop after exactly three iterations.
JMP 0       ; Process the next item.
done: LD 28 ; Return the saved total.
HALT        ; Stop execution.
"""

RESTORE_SOURCE = """\
LDI 29      ; Select the first array cell.
ST 7        ; Restore the ADD operand before each call.
loop: LD 27 ; Load the running sum (caller supplies zero).
ADD 29      ; Add the current array cell, initially 29.
ST 27       ; Save the updated sum.
LD 7        ; Read the operand byte from the ADD instruction.
ADDI 1      ; Advance the data address.
ST 7        ; Patch the operand byte for the next iteration.
SUB 28      ; Compare with the exclusive end address, 32.
JZ @done    ; Exit when all three cells have been read.
JMP @loop   ; Otherwise repeat with the patched ADD.
done: LD 27 ; Return the total.
HALT        ; Stop execution.
"""

SUM = Routine(0, tuple(assemble(SUM_SOURCE, 32)))
RESTORE = Routine(0, tuple(assemble(RESTORE_SOURCE, 32)))
SMALL_SOURCE = """\
LD 28   ; Load the first input byte.
ADD 29  ; Add the second input byte.
HALT    ; Return the accumulator.
"""
SMALL = Routine(0, tuple(assemble(SMALL_SOURCE, 32)))
RELOCATED = Routine(12, (2, 30, 4, 31, 0, 0))


def relocation_start(first, second):
    return reference.load(SMALL.code, 32, {28: first, 29: second,
                                           30: first, 31: second})


def _relocate_reference(state, fuel):
    status, final, steps = reference.run(state, fuel)
    if status != "ok":
        raise ValueError(status)
    return final, steps


def relocation_evidence(ledger):
    """Reverify bytes at a new base instead of inheriting the source's proof."""
    domain = RoutineDomain.product("all 16 source pairs in 0..3", (range(4),) * 2,
                                   lambda values: relocation_start(*values))
    scope = domain.enumerate()
    ledger.verify(SMALL, domain, _relocate_reference)
    ledger.promote(SMALL, Contract("adds two source bytes modulo 256", (), ("28", "29")))
    def relocated_start(values):
        mem = list(relocation_start(*values).mem)
        mem[12:18] = RELOCATED.code
        return reference.State(12, 0, tuple(mem))

    ledger.verify(RELOCATED, RoutineDomain.product("all 16 relocated pairs in 0..3",
                                                   (range(4),) * 2, relocated_start),
                  _relocate_reference)
    ledger.promote(RELOCATED, Contract("adds two relocated bytes modulo 256", (), ("30", "31")))
    return scope


def initial(routine, values):
    """Caller-owned scratch is initialized on each invocation."""
    data = {29 + index: value for index, value in enumerate(values)}
    data.update({27: 3, 28: 0} if routine == SUM else {27: 0, 28: 32})
    return reference.load(routine.code, 32, data)


def again(final):
    """Reset call state and scratch, preserving every code byte."""
    mem = list(final.mem)
    mem[27] = 3
    mem[28] = 0
    return reference.State(0, 0, tuple(mem))


def restore_again(final):
    mem = list(final.mem)
    mem[27] = 0
    mem[7] = 29
    return reference.State(0, 0, tuple(mem))


def expected(initial_state, fuel):
    status, final, steps = reference.run(initial_state, fuel)
    if status != "ok":
        raise ValueError(f"reference did not halt: {status}")
    assert final.a == sum(initial_state.mem[29:32]) % 256
    return final, steps


@lru_cache(maxsize=1)
def evidence():
    ledger = RoutineLedger(declaration())
    ledger.verify(SUM, RoutineDomain.product("all 4096 triples at 29..31 in 0..15",
                                             (range(16),) * 3, lambda values: initial(SUM, values)),
                  expected)
    ledger.promote(SUM, Contract("sum of three 0..15 bytes modulo 256; fresh call scratch",
                                 ("3", "27", "28"), ("29", "30", "31")))
    ledger.verify(RESTORE, RoutineDomain.product("all 64 triples at 29..31 in 0..3",
                                                 (range(4),) * 3,
                                                 lambda values: initial(RESTORE, values)),
                  expected, reset=restore_again, reset_addresses=(7, 27))
    ledger.promote(RESTORE, Contract("two calls after caller resets accumulator and scratch 27",
                                     ("7", "27"), ("28", "29", "30", "31")))
    relocation_evidence(ledger)
    return ledger


def _operation(name, layer, body, inputs, output, dependencies):
    spec = OperationSpec(name, "transform", tuple(Edge(sort, name=param) for param, sort in inputs),
                         Edge(output), "Unfold the recorded kernel body.", extra={"input_names": [p for p, _ in inputs]})
    return Definition(name, "operation", "invented", layer, dependencies, spec, body)


class VNLibrary(Library):
    """Adapt VN's state-valued probes; core's observation verifier assumes robot states."""

    def __init__(self, world, atoms):
        super().__init__(world, (*atoms, kernel.Atom("eq", 2, machine._CommittedHost(equal), 0),
                                 kernel.Atom("comb_positive", 1, machine._CommittedHost(positive)),
                                 kernel.Atom("comb_dec", 1, machine._CommittedHost(decrement))))

    def _params(self, definition):
        if definition.kind == "observation":
            return ("s",)
        return super()._params(definition)

    def check(self, name):
        definition = self.get(name)
        if definition.kind == "observation":
            allowed = set(definition.spec.reads)
            if definition.body != definition.spec.body or not allowed <= {"pc", "a", "cell", "halted"} or \
                    any(isinstance(item, n.Call) and item.fn not in allowed for item in n.walk(definition.body)):
                raise ValueError("observation may read declared VN probes only")
            return self._advance(name, "checked")
        return super().check(name)

    def make_callable(self, name, sample):
        if self.get(name).kind == "observation":
            for args in sample:
                result = kernel.call(name, args, self.scope().extend([
                    kernel.Defn(name, ("s",), self.get(name).body, "observation")]))
                if not isinstance(result.outcome, Ok):
                    raise PipelineError(f"observation sample {args!r} gave {result.outcome!r}")
            return self._advance(name, "callable")
        return super().make_callable(name, sample)

    def verify(self, name, request):
        definition = self.get(name)
        request = replace(request, scope={**request.scope,
                                          "input_hashes": [input_hash(args) for args in request.domain]})
        if definition.kind not in ("object", "observation"):
            return super().verify(name, request)
        if definition.status != "callable" or request.method not in ("exhaustive", "bounded") or \
                not request.domain or request.scope["size"] != len(request.domain):
            raise ValueError("invalid VN verification scope")
        steps = []
        for args in request.domain:
            original = deepcopy(tuple(args))
            actual = self.run(name, args, fuel=100)
            unfolded = kernel.evaluate(kernel.inline(n.Call(name, tuple(n.Lit(arg) for arg in args)),
                                                      self.scope()), scope=self.scope(), limits=kernel.Limits(fuel=100))
            if not outcome_equal(actual.outcome, unfolded.outcome) or actual.steps != unfolded.steps or \
                    not isinstance(actual.outcome, Ok):
                raise ValueError("VN unfolding differs")
            if definition.kind == "object" and actual.outcome.value != definition.body.value:
                raise ValueError("constant differs")
            if definition.kind == "observation":
                if tuple(args) != original:
                    raise ValueError("observation changes facts")
                if not callable(request.reference):
                    raise ValueError("observation requires an independent reference oracle")
                reference_result = request.reference(*original)
                if not outcome_equal(actual.outcome, reference_result):
                    raise ValueError("observation differs from declared reference")
            steps.append(actual.steps)
        checks = (("unfold_equivalence",) if definition.kind == "object" else
                  ("dependency", "facts_unchanged", "non_interference", "reference", "unfold_equivalence"))
        scope = {**request.scope, "checked": {**checked_scope(request.domain), "by": "library"}}
        evidence = Evidence(request.method, scope, checks=checks,
                            world_hash=self.world.world_hash(), deps_hash=self._deps_hash(name),
                            content_hash=self.content_hash(name), atoms_hash=atoms_digest(self.atoms))
        self._steps[name] = steps
        self._library_checked.add(name)
        self._definitions[name] = replace(definition, evidence=evidence)
        return self._advance(name, "verified")


def _promote(lib, definition, domain, reference_fn, contract):
    lib.write(definition)
    lib.check(definition.name)
    lib.make_callable(definition.name, domain[:1])
    request = VerifyRequest("bounded", tuple(domain),
                            {"domain": "listed VN states and bound 100 instructions", "size": len(domain),
                             "fingerprint": hashlib.sha256(repr(tuple(domain)).encode("utf-8")).hexdigest()},
                            reference=reference_fn, extra={"fuel": 100})
    lib.verify(definition.name, request)
    lib.account(definition.name)
    return lib.promote(definition.name, contract)


def creation_story():
    """All invented bodies are kernel nodes; no invented host rule is installed."""
    lib = VNLibrary(declaration(), machine.atoms(32))
    states = [(machine.to_card(initial(SUM, values)),) for values in ((1, 2, 3), (0, 0, 0))]
    defs = []
    program_bytes = Card("SampleProgram", "items", initial(SUM, (1, 2, 3)).mem)
    constant = Definition("SampleProgram", "object", "invented", 1, (),
                          ObjectSpec("SampleProgram", "constant", body=n.Lit(program_bytes)),
                          n.Lit(program_bytes))
    lib.write(constant)
    lib.check(constant.name)
    lib.make_callable(constant.name, [()])
    lib.verify(constant.name, VerifyRequest("bounded", ((),),
                                          {"domain": "one constant; bound 1", "size": 1},
                                          extra={"values": [program_bytes]}))
    lib.account(constant.name)
    defs.append(lib.promote(constant.name, Contract("fixed 32-byte program and data image", (), ("memory",))))
    run_body = machine.exec_node(n.Var("s"))
    defs.append(_promote(lib, _operation("run_routine", 1, run_body, (("s", "vn"),), "vn",
                                          ("is_halted", "step")), states,
                         lambda s: Ok(machine.to_card(expected(machine.from_card(s), 100)[0])),
                         Contract("executes until HALT within 100 instructions", ("vn",))))
    defs.append(_promote(lib, _operation("sum_routine", 2, n.Call("run_routine", (n.Var("s"),)),
                                          (("s", "vn"),), "vn", ("run_routine",)), states,
                         lambda s: Ok(machine.to_card(expected(machine.from_card(s), 100)[0])),
                         Contract("@exec over the input state", ("vn",))))
    observation_body = n.Call("cell", (n.Var("s"), n.Call("pc", (n.Var("s"),))))
    observation = Definition("next_op", "observation", "invented", 1, ("cell", "pc"),
                             ObservationSpec("next_op", ("cell", "pc"), observation_body), observation_body)
    lib.write(observation)
    lib.check(observation.name)
    lib.make_callable(observation.name, states[:1])
    lib.verify(observation.name, VerifyRequest("bounded", tuple(states),
                                               {"domain": "two VN states; bound 100 steps", "size": 2},
                                               reference=lambda s: Ok(s.fields[2].fields[s.fields[0]])))
    lib.account(observation.name)
    defs.append(lib.promote(observation.name, Contract("reads only granted pc and cell probes", (), ("vn",))))
    patch_body = n.Call("poke", (n.Var("s"), n.Var("k"), n.Var("b")))
    patch_states = [(states[0][0], 3, byte) for byte in (29, 32)]
    defs.append(_promote(lib, _operation("patch_operand", 1, patch_body,
                                         (("s", "vn"), ("k", "int"), ("b", "byte")),
                                         "vn", ("poke",)), patch_states,
                         lambda s, k, b: Ok(machine.poke(s, k, b)),
                         Contract("writes the selected byte, including code operands", ("vn",))))
    comb_body = n.Call("f", (n.Call("f", (n.Var("s"),)),))
    comb = Definition("twice_run", "combinator", "invented", 1, (),
                      CombinatorSpec("twice_run", ("f", "s"), ("f",), comb_body), comb_body)
    lib.write(comb)
    lib.check(comb.name)
    from opulse.atoms.kernel import FnRef
    lib.make_callable(comb.name, [(FnRef("step"), states[0][0])])
    lib.verify(comb.name, VerifyRequest("bounded", ((states[0][0],),),
                                        {"domain": "one state, bound 2 calls", "size": 1,
                                         "op_family": ["step"]}, extra={"op_family": ["step"]}))
    lib.account(comb.name)
    defs.append(lib.promote(comb.name, Contract("two applications of the plugged operation", ("vn",))))
    repaired = machine.to_card(initial(RESTORE, (1, 2, 3)))
    broken = machine.poke(repaired, 7, 32)
    reset_body = n.Call("patch_operand", (n.Var("s"), n.Lit(7), n.Lit(29)))
    defs.append(_promote(lib, _operation("reset_operand", 2, reset_body,
                                         (("s", "vn"),), "vn", ("patch_operand",)),
                         [(broken,), (repaired,)],
                         lambda s: Ok(machine.poke(s, 7, 29)),
                         Contract("restores the ADD operand at address 7", ("vn",))))
    rerun_body = n.Call("sum_routine", (n.Call("reset_operand", (n.Var("s"),)),))
    defs.append(_promote(lib, _operation("rerun_restored", 3, rerun_body,
                                         (("s", "vn"),), "vn", ("reset_operand", "sum_routine")),
                         [(broken,), (repaired,)],
                         lambda s: Ok(machine.to_card(expected(machine.from_card(machine.poke(s, 7, 29)), 100)[0])),
                         Contract("repairs the operand and runs the three-cell sum", ("vn",))))

    relocation_states = [machine.to_card(relocation_start(1, 2)),
                         machine.to_card(reference.load(SMALL.code, 32,
                                                        {28: 3, 29: 1, 30: 3, 31: 3}))]
    body = n.Var("s")
    for offset in range(6):
        body = n.Call("poke", (body, n.Lit(12 + offset),
                               n.Call("peek", (n.Var("s"), n.Lit(offset)))))
    defs.append(_promote(lib, _operation("copy_six", 1, body, (("s", "vn"),), "vn",
                                         ("peek", "poke")),
                         [(state,) for state in relocation_states],
                         lambda s: Ok(_copy_six_reference(s)),
                         Contract("copies source bytes 0..5 into 12..17", ("vn",))))
    relocated_body = n.Call("patch_operand", (
        n.Call("patch_operand", (n.Call("copy_six", (n.Var("s"),)), n.Lit(13), n.Lit(30))),
        n.Lit(15), n.Lit(31)))
    defs.append(_promote(lib, _operation("relocate_add", 2, relocated_body,
                                         (("s", "vn"),), "vn", ("copy_six", "patch_operand")),
                         [(state,) for state in relocation_states],
                         lambda s: Ok(machine.poke(machine.poke(_copy_six_reference(s), 13, 30), 15, 31)),
                         Contract("copies the program and retargets its two absolute operands", ("vn",))))
    variant_body = n.Call("patch_operand", (n.Call("relocate_add", (n.Var("s"),)),
                                             n.Lit(15), n.Lit(29)))
    defs.append(_promote(lib, _operation("relocate_variant", 3, variant_body,
                                         (("s", "vn"),), "vn", ("relocate_add", "patch_operand")),
                         [(state,) for state in relocation_states],
                         lambda s: Ok(machine.poke(machine.poke(machine.poke(
                             _copy_six_reference(s), 13, 30), 15, 31), 15, 29)),
                         Contract("retargets the copied ADD to source cell 29", ("vn",))))
    variant_run = n.Call("run_routine", (n.Call("set_pc", (
        n.Call("relocate_variant", (n.Var("s"),)), n.Lit(12))),))
    defs.append(_promote(lib, _operation("run_variant", 4, variant_run,
                                         (("s", "vn"),), "vn", ("relocate_variant", "set_pc", "run_routine")),
                         [(state,) for state in (*relocation_states,
                                                machine.to_card(relocation_start(3, 1)))],
                         lambda s: Ok(machine.to_card(_relocate_reference(
                             reference.State(12, 0, machine.from_card(machine.poke(machine.poke(
                                 machine.poke(_copy_six_reference(s), 13, 30), 15, 31), 15, 29)).mem), 100)[0])),
                         Contract("runs the retargeted copy at address 12", ("vn",))))
    defs.append(_promote(lib, _operation("variant_result", 5,
                                         n.Call("get_a", (n.Call("run_variant", (n.Var("s"),)),)),
                                         (("s", "vn"),), "byte", ("run_variant", "get_a")),
                         [(state,) for state in relocation_states],
                         lambda s: Ok(machine.from_card(lib.run("run_variant", (s,), fuel=100).outcome.value).a),
                         Contract("returns the relocated variant's accumulator", (), ("vn",))))

    statement = n.Call("eq", (n.Call("reset_operand", (n.Call("reset_operand", (n.Var("s"),)),)),
                                n.Call("reset_operand", (n.Var("s"),))))
    law = Definition("restore_idempotent", "law", "invented", 3, ("reset_operand", "eq"),
                     LawSpec("restore_idempotent", (("s", "vn"),), statement), statement)
    law_states = ((broken,), (repaired,), (machine.poke(repaired, 7, 0),))
    lib.write(law)
    lib.check(law.name)
    lib.make_callable(law.name, law_states[:1])
    lib.verify(law.name, VerifyRequest("exhaustive", law_states,
                                       {"domain": "exactly the three listed operand images at address 7: 32, 29, 0",
                                        "size": 3}))
    lib.account(law.name)
    defs.append(lib.promote(law.name, Contract("resetting the operand twice equals resetting it once",
                                                (), ("vn",))))
    false_statement = n.Call("eq", (n.Call("reset_operand", (n.Var("s"),)), n.Var("s")))
    false_law = Definition("reset_is_identity", "law", "invented", 3, ("reset_operand", "eq"),
                           LawSpec("reset_is_identity", (("s", "vn"),), false_statement),
                           false_statement)
    lib.write(false_law)
    lib.check(false_law.name)
    lib.make_callable(false_law.name, [(broken,)])
    try:
        lib.verify(false_law.name, VerifyRequest("exhaustive", ((broken,),),
                                                 {"domain": "the single image with operand 7 = 32",
                                                  "size": 1}))
    except PipelineError as error:
        if "law counterexample" not in str(error):
            raise
    else:
        raise AssertionError("a false repair law must remain unpromoted")
    fix = fix_spec()
    fix_body = n.map_nodes(fix.body, lambda node: n.Call("eq", node.args)
                           if isinstance(node, n.Call) and node.fn == "fix_equal" else
                           n.Call("repair", node.args) if isinstance(node, n.Call) and node.fn == "step" else
                           n.Var("repair") if isinstance(node, n.Var) and node.name == "step" else node)
    fix_params = tuple("repair" if param == "step" else param for param in fix.params)
    repair_fix = Definition("fix", "combinator", "invented", 1,
                            ("comb_positive", "comb_dec", "eq"),
                            CombinatorSpec("fix", fix_params, ("repair",), fix_body), fix_body)
    lib.write(repair_fix)
    lib.check(repair_fix.name)
    lib.make_callable(repair_fix.name, [(kernel.FnRef("reset_operand"), broken, 2)])
    lib.verify(repair_fix.name, VerifyRequest("bounded", ((broken, 2), (repaired, 2)),
                                              {"domain": "two operand images 32 and 29; stable after at most two repairs",
                                               "size": 2, "finite_height": 2,
                                               "op_family": ["reset_operand"]},
                                              extra={"op_family": ["reset_operand"]}))
    lib.account(repair_fix.name)
    defs.append(lib.promote(repair_fix.name, Contract("reapply repair until the code image stabilizes",
                                                      ("vn",))))

    source_body = n.Call("get_a", (n.Call("run_routine", (n.Var("s"),)),))
    target_body = n.Call("get_a", (n.Call("run_routine", (
        n.Call("set_pc", (n.Var("s"), n.Lit(12))),)),))
    bridge_states = [machine.to_card(relocation_start(first, second))
                     for first in range(2) for second in range(2)]
    for name, body, reference_fn, dependencies in (
            ("source_result", source_body,
             lambda s: Ok(sum(machine.from_card(s).mem[index] for index in (28, 29)) % 256),
             ("run_routine", "get_a")),
            ("target_result", target_body,
             lambda s: Ok(sum(machine.from_card(s).mem[index] for index in (30, 31)) % 256),
             ("run_routine", "set_pc", "get_a"))):
        verification_states = (bridge_states if name == "source_result" else
                               [lib.run("relocate_add", (state,)).outcome.value for state in bridge_states])
        defs.append(_promote(lib, _operation(name, 2, body, (("s", "vn"),), "byte", dependencies),
                             [(state,) for state in verification_states], reference_fn,
                             Contract("returns the executed routine's accumulator", (), ("vn",))))
    bridge_map = n.Call("relocate_add", (n.Var("x"),))
    requirements = tuple((n.Call("peek", (n.Var("x"), n.Lit(index))), n.Lit(byte))
                         for index, byte in enumerate(SMALL.code)) + (
        (n.Call("get_pc", (n.Var("x"),)), n.Lit(0)),
        (n.Call("peek", (n.Var("x"), n.Lit(28))), n.Call("peek", (n.Var("x"), n.Lit(30)))),
        (n.Call("peek", (n.Var("x"), n.Lit(29))), n.Call("peek", (n.Var("x"), n.Lit(31)))))
    bridge_domain = n.Lit(True)
    for left, right in reversed(requirements):
        bridge_domain = n.Case(((n.Test(n.Call("eq", (left, right))), bridge_domain),), n.Lit(False))
    bridge_spec = BridgeSpec("relocate_12", "vn", "vn", bridge_map, bridge_domain,
                             (("source_result", "target_result"),))
    bridge = Definition("relocate_12", "bridge", "invented", 3,
                        ("relocate_add", "peek", "eq", "get_pc"),
                        bridge_spec, bridge_defn(bridge_spec).body)
    lib.write(bridge)
    lib.check(bridge.name)
    lib.make_callable(bridge.name, [(bridge_states[0],)])
    lib.verify(bridge.name, VerifyRequest("bounded", tuple((state,) for state in bridge_states),
                                          {"domain": "all four source input pairs in 0..1; six-byte source at 0, free target at 12, matching data at 28..31",
                                           "size": 4}, extra={"fuel": 100}))
    lib.account(bridge.name)
    defs.append(lib.promote(bridge.name, Contract("retargeted copy preserves the executed accumulator",
                                                   ("vn",))))
    pattern_body = n.Call("patch_operand", (n.Var("s"), n.Lit(7), n.Lit("$operand")))
    pattern = _operation("operand_member", 3, pattern_body, (("s", "vn"),), "vn",
                         ("patch_operand",)).spec.to_dict()
    pattern["definition_body"] = n.to_json(pattern_body)
    family = [{"operand": operand} for operand in (29, 30, 31)]
    template = Definition("retarget_operand", "template", "invented", 1, (),
                          TemplateSpec("retarget_operand", (("operand", "int"),), "operation",
                                       pattern, {"family": family}), n.Lit("operand family"))
    member_states = ((broken,), (repaired,))

    def member_request(index, args, member):
        operand = args["operand"]
        return VerifyRequest("bounded", member_states,
                             {"domain": f"two exact input images for operand {operand}", "size": 2},
                             reference=lambda s: Ok(machine.poke(s, 7, operand)), extra={"fuel": 100})

    lib.write(template)
    lib.check(template.name)
    lib.make_callable(template.name, [(29,)])
    lib.verify(template.name, VerifyRequest("bounded", ((29,), (30,), (31,)),
                                            {"domain": "three operand bytes 29, 30, 31", "size": 3,
                                             "family": family},
                                            extra={"family": family,
                                                   "member_request_builder": member_request}))
    lib.account(template.name)
    defs.append(lib.promote(template.name, Contract("generates a kernel operand patch", (), ("vn",))))
    for index, args in enumerate(family):
        member = instantiate(lib.get(template.name), args, f"retarget_{args['operand']}", lib=lib)
        defs.append(_promote(lib, member, member_states,
                             member_request(index, args, member).reference,
                             Contract(f"sets operand 7 to {args['operand']}", ("vn",))))
    return lib, defs


def _copy_six_reference(state):
    current = machine.from_card(state)
    memory = list(current.mem)
    memory[12:18] = current.mem[:6]
    return machine.to_card(reference.State(current.pc, current.a, tuple(memory), current.halted))
