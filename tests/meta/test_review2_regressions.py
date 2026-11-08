"""Review 2 reproductions and boundary checks for meta worlds."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_builder_instantiate import StubLedger, body_world
from test_builder_wf import base

from opulse.atoms import nodes as n
from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import Card, Ok
from opulse.meta import code as C
from opulse.meta.builder import world_value as V
from opulse.meta.builder.instantiate import WorldError, _assemble, extend
from opulse.meta.builder.wf import wf
from opulse.meta.compiler.compile import Prog, compile_tiny
from opulse.meta.compiler.validate import prog_hash, validate, validate_compiler
from opulse.meta.vn import machine, reference
from opulse.meta.vn.report import report


def test_m_validate_1_full_program_identity_and_addresses():
    body = n.Call("sub", (n.Var("x0"), n.Var("x1")))
    prog = compile_tiny(body, ("x0", "x1"))
    good = validate(body, ("x0", "x1"), prog, [(3, 1)], 100)
    bad = validate(body, ("x0", "x1"), replace(prog, args=prog.args[::-1]), [(3, 1)], 100)
    assert good.accepted and good.counterexample is None
    assert not bad.accepted and bad.counterexample.compiled == Ok(254)
    assert good.pair != bad.pair
    assert prog_hash(Prog(16, (1, 3, 0, 0), ())) == (
        "640f5e7725021e595633866ea9d80031d173dc6ce18b51452516150a795a0b9d")
    assert prog_hash(Prog(16, (1, 3, 0, 0), (), out="mem")) == (
        "9a56ba92950d398eaa7e2fd356b741c058025861188e1311b7fa3b32072137ab")
    with pytest.raises(ValueError, match="output mode"):
        validate(n.Lit(3), (), Prog(16, (1, 3, 0, 0), (), out="mem"), [()], 20)
    for address in (-1, 16, True):
        with pytest.raises(ValueError, match="argument address"):
            validate(n.Var("x0"), ("x0",), Prog(16, (2, 4, 0, 0), (address,)), [(3,)], 20)


def test_m_compiler_1_global_definition_shadows_caller_rec():
    defs = {"helper": (n.Call("loop", (n.Var("y"),)), ("y",)),
            "loop": (n.Lit(7), ("y",))}
    body = n.Rec("loop", ("v",), n.Call("helper", (n.Var("v"),)),
                 (n.Var("x0"),), "fuel")
    prog = compile_tiny(body, ("x0",), defs)
    result = validate(body, ("x0",), prog, [(2,)], 200)
    assert result.accepted and result.counterexample is None
    assert (prog.run((2,), 200)[0], prog.run((2,), 200)[1].a, prog.run((2,), 200)[2]) == (
        "ok", 7, 8)


def test_inlined_local_rec_shadows_global_definition():
    helper = n.Rec("loop", ("v",),
                   n.Case(((n.Test(n.Call("is_zero", (n.Var("v"),))), n.Lit(7)),),
                          n.Call("loop", (n.Call("sub", (n.Var("v"), n.Lit(1))),))),
                   (n.Var("y"),), "fuel")
    defs = {"helper": (helper, ("y",)), "loop": (n.Lit(11), ("y",))}
    body = n.Rec("loop", ("v",), n.Call("helper", (n.Var("v"),)),
                 (n.Var("x0"),), "fuel")
    prog = compile_tiny(body, ("x0",), defs)
    result = validate(body, ("x0",), prog, [(0,), (2,)], 200)
    assert result.accepted and result.counterexample is None
    assert [(prog.run((value,), 200)[1].a, prog.run((value,), 200)[2]) for value in (0, 2)] == [
        (7, 11), (7, 29)]


def test_m_builder_1_private_range_primitive_not_callable_from_body():
    code = C.make_code("operation", C.sig_op([], ("bool", "bottom")), (),
                       n.Call("le", (n.Lit(1), n.Lit(2))),
                       lambda name: C.Resolved(digest="builtin:le/1") if name == "le" else None)
    world = base(ops=[V.body("test_le", code)], probes=[])
    assert wf(world) == Card("report", "bad", ("bodies", "foreign or forward atom in test_le"))
    reserved = V.table("__range_le", "decide", [], "bool", [],
                       [V.row([], V.val(Card("bool", "true")))])
    assert wf(base(ops=[reserved], probes=[])) == Card(
        "report", "bad", ("names", "reserved operation name"))


def test_declared_le_with_real_digest_is_callable():
    first = V.table("le", "decide", ["z", "z"], "bool", [],
                    [V.row([Card("z", left), Card("z", right)],
                           V.val(Card("bool", "true" if left <= right else "false")))
                     for left in ("z0", "z1") for right in ("z0", "z1")])
    declared = base(ops=[first], probes=[])
    digest = C.atom_digest(_assemble(declared)[0].operations[0])
    code = C.make_code("operation", C.sig_op([], ("bool", "bottom")), (),
                       n.Call("le", (n.Lit(Card("z", "z0")), n.Lit(Card("z", "z1")))),
                       lambda name: C.Resolved(digest=digest) if name == "le" else None)
    assert wf(base(ops=[first, V.body("ordered", code)], probes=[])) == Card("report", "ok")


def test_m_builder_2_closed_kind_rejects_body_and_extension():
    world, code = body_world()
    fields = list(world.fields)
    fields[8] = C.lst(["object"])
    fields[9] = C.lst(V.tag(tag.fields[0], ["object"] if tag.fields[0] == "open_kinds" else
                             "object" if tag.fields[0] == "star_kind" else tag.fields[1])
                      for tag in C.items(fields[9]))
    closed = Card("world", "world", tuple(fields))
    assert wf(closed) == Card("report", "bad", ("bodies", "operation kind is closed"))
    given_only = replace(closed, fields=(*closed.fields[:3], C.lst(C.items(closed.fields[3])[:1]),
                                         *closed.fields[4:]))
    assert wf(given_only) == Card("report", "ok")
    evidence = Evidence("bounded", {"domain": "z", "size": 2}, world_hash=V.world_hash(given_only))
    with pytest.raises(WorldError, match="operation kind is closed"):
        extend(given_only, code, StubLedger((evidence, Contract("works"))))


def test_m_validate_2_empty_scope_never_accepts():
    result = validate(n.Lit(1), (), Prog(16, (9, 0), ()), [], 100)
    assert not result.accepted and result.scope["size"] == 0
    with pytest.raises(ValueError, match="non-empty"):
        validate_compiler([n.Lit(1)], [])


def test_m_vn_1_exact_constructor_and_card_types():
    memory = (0,) * 16
    for pc, accumulator, halted in ((True, True, 1), (True, 0, False),
                                    (0, True, False), (0, 0, 1)):
        with pytest.raises(ValueError):
            reference.State(pc, accumulator, memory, halted)
    card = machine.to_card(reference.State(0, 0, memory))
    for position in (0, 1):
        fields = list(card.fields)
        fields[position] = True
        with pytest.raises(ValueError):
            machine.from_card(replace(card, fields=tuple(fields)))


def test_fetch_wraps_from_last_address_to_zero():
    memory = [0] * 16
    memory[15] = 1
    memory[0] = 23
    state = reference.State(15, 0, tuple(memory))
    expected = reference.State(1, 23, tuple(memory))
    assert reference.step(state) == expected
    assert machine.step(machine.to_card(state)) == machine.to_card(expected)
    assert report(state, 1).fetched == frozenset({15, 0})
    assert report(state, 1).outcome == machine.run(machine.to_card(state), 1).outcome


def test_repeated_stores_across_wrap_have_exact_version_hashes():
    memory = [0] * 16
    memory[15], memory[0] = 6, 1
    memory[1:9] = [3, 15, 1, 4, 3, 15, 0, 0]
    state = reference.State(15, 3, tuple(memory))
    result = report(state, 5)
    assert result.fetched == frozenset({15, *range(9)})
    assert result.stores == ((2, 15, 6, 3), (4, 15, 3, 4))
    assert (result.self_modifying, result.writes_ahead, result.writes_behind) == (True, False, True)
    expected_bytes = []
    for opcode in (6, 3, 4):
        pairs = tuple((address, opcode if address == 15 else memory[address])
                      for address in sorted(result.fetched))
        expected_bytes.append(pairs)
    assert tuple(image.name for image in result.versions) == ("C_0", "C_1", "C_2")
    for image, pairs in zip(result.versions, expected_bytes):
        payload = json.dumps([[address, byte] for address, byte in pairs], separators=(",", ":"))
        expected_hash = hashlib.sha256(("opulse.vn/1\n16\n" + payload).encode("ascii")).hexdigest()
        assert image.bytes == pairs and image.identity == expected_hash
    final_memory = list(memory)
    final_memory[15] = 4
    assert result.outcome == Ok(machine.to_card(reference.State(7, 4, tuple(final_memory), True)))
