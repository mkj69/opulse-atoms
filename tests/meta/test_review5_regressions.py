"""Exact regressions for the fifth meta review."""

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import Bottom, Card, Ok
from opulse.meta import code as C
from opulse.meta import engine
from opulse.meta.builder import world_value as V
from opulse.meta.builder.wf import wf
from opulse.meta.compiler.compile import CompileError, Prog, compile_tiny
from opulse.meta.compiler.validate import validate
from opulse.meta.export_util import outcome_json, trace_json, value_json
from opulse.meta.identity import Ledger
from opulse.meta.worlds.builder import hosts as builder_hosts
from opulse.meta.worlds.builder import world as builder_world
from opulse.meta.worlds.code import world as code_world


def test_translation_rejects_different_bottom_reasons():
    body = n.Case((), None)
    try:
        prog = compile_tiny(body, ())
    except CompileError:
        prog = Prog(64, (9, 0), ())
    else:
        result = validate(body, (), prog, [()], 100)
        assert result.counterexample.source == Bottom("no_branch")
        assert result.counterexample.compiled == Bottom("illegal")
        assert not result.accepted
    try:
        compile_tiny(body, ())
    except CompileError:
        pass
    else:
        raise AssertionError("case without default must not compile to an illegal opcode")


def test_imported_evidence_is_a_snapshot():
    program = C.make_code("operation", C.sig_op([], ("int", "bottom")), (), n.Lit(5), lambda _: None)
    ledger = Ledger()
    digest = ledger.add(program, "w")
    ledger.attach_evidence(digest, "w", Evidence("bounded", {"domain": [[]], "size": 1}, world_hash="w"))
    ledger.promote(digest, "w", Contract("constant"))
    raw = ledger.to_dict()
    imported = Ledger.from_dict(raw)
    raw["records"][0]["evidence"][0]["scope"]["domain"].append([13])
    assert imported.record(digest, "w").evidence[0].scope == {"domain": [[]], "size": 1}


def test_canonical_code_rejects_lexical_global_collision():
    program = Card("code", "def", ("operation", C.sig_op([("int", "bottom")], ("int", "bottom")),
                                   Card("expr", "call", ("x0", C.lst())),
                                   C.lst((Card("atom", "atom", ("x0", "digest")),)), C.lst()))
    atom = kernel.Atom("x0", 0, lambda: 42)
    scope = kernel.DictScope(atoms=[atom, engine.eval_atom([atom], {"x0": "digest"})])
    assert not C.is_canonical(program)
    assert engine.call("eval", (program, C.lst((99,))), scope).outcome == Bottom("ill_formed")


def test_unused_global_metadata_cannot_shadow_a_bound_name():
    program = Card("code", "def", ("operation", C.sig_op([], ("int", "bottom")),
                                   C.encode_node(n.Let("v0", n.Lit(2), n.Var("v0"))),
                                   C.lst((Card("atom", "atom", ("v0", "digest")),)), C.lst()))
    assert not C.is_canonical(program)


def test_noncallable_body_checked_before_kind():
    program = C.make_code("observation", C.sig_obs([]), (), n.Var("unbound"), lambda _: None)
    for digests in ({"some_atom": "digest"}, {}):
        scope = kernel.DictScope(atoms=[engine.eval_atom([], digests)])
        assert engine.call("eval", (program, C.lst()), scope).outcome == Bottom("ill_formed")


def test_world_rejects_undeclared_judging_projection():
    tags = [V.tag(key, value) for key, value in (
        ("domain", "math"), ("modalities", ["text"]), ("open_kinds", ["operation"]),
        ("star_kind", "operation"), ("reasoning", ["compute"]), ("state", "stateless"),
        ("outcomes", "deterministic"), ("visibility", "full"), ("agents", "1"),
        ("uses", ["teaching"]))]
    value = V.world("test", 1, [V.range_sort("small", 0, 0)], [], ["Var", "Lit"], "none", [],
                    "contract_projection(nonexistent)", ["operation"], tags)
    assert wf(value) == Card("report", "bad", ("kinds", "invalid judge_view"))


def test_nested_evaluation_remains_metered():
    scope = kernel.DictScope(atoms=[kernel.Atom("nested", 0, lambda: engine.evaluate(n.Lit(7)).outcome.value)])
    result = engine.call("nested", (), scope, trace=True)
    assert result.outcome == Ok(7)
    assert result.steps == 1
    assert result.trace.children[0].name == "nested"
    encoded = trace_json(result.trace)
    assert encoded["children"][0]["name"] == "nested"
    assert encoded["children"][0]["steps"] == 1
    assert encoded["outcome"] == outcome_json(Ok(7))
    assert value_json(kernel.FnRef("nested")) == {"fn": "nested"}


def test_shared_code_interface_in_both_worlds():
    program = C.make_code("operation", C.sig_op([], ("int", "bottom")), (), n.Lit(5), lambda _: None)
    for declaration, atoms in ((code_world.declaration(), code_world.library().atoms),
                               (builder_world.declaration(), builder_hosts.atoms())):
        obj = next(obj for obj in declaration.objects if obj.name == "code")
        assert obj.form == "compose" and obj.canon_cost == "free"
        assert {"tag_of", "field", "with_field", "mk", "list_len", "list_get", "list_append",
                "str_eq", "code_hash", "eval", "run"} <= {op.name for op in declaration.operations}
        scope = kernel.DictScope(atoms=atoms)
        evaluated = engine.call("eval", (program, C.lst()), scope, trace=True)
        assert evaluated.outcome == Ok(5) and evaluated.steps == 0
        assert [(frame.name, frame.steps) for frame in evaluated.trace.children] == [("eval", 0)]
        ran = engine.call("run", (program, C.lst(), 0), scope)
        assert ran.outcome == Ok(Card("result", "ok", (5,))) and ran.steps == 0
        hashed = engine.call("code_hash", (program,), scope)
        assert hashed.outcome == Ok(C.code_hash(program)) and hashed.steps == 1
    assert builder_hosts.field(3, 0) == Bottom("invalid")
    assert builder_hosts.list_get(C.lst(), 0) == Bottom("invalid")
