"""Review-11 code-world declaration and provenance regressions."""

import json
from dataclasses import replace

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.spec import content_hash
from opulse.atoms.values import Bottom, Card, Ok, encode
from opulse.meta import code
from opulse.meta.check import export_problems
from opulse.meta.export_util import input_hash
from opulse.meta.worlds.code.export import DEST
from opulse.meta.worlds.code.story import (
    build_story,
    record_specialization,
    run_code,
    specialization_family,
)
from opulse.meta.worlds.code.world import DECL, declaration, library


@pytest.fixture(scope="module")
def built():
    return build_story()


@pytest.mark.parametrize("signature", (
    code.sig_law((("x", "int"),)),
    code.sig_bridge("code", "code", (("add", "add"),)),
    code.sig_template((("k", "int"),), "operation"),
))
def test_signatures_construct_from_layer_zero(signature):
    lib = library()
    fields = []
    for field in signature.fields:
        if isinstance(field, Card) and field.sort == "list":
            items = []
            for item in code.items(field):
                outcome = lib.run("mk", (item.sort, item.tag, code.lst(item.fields))).outcome
                assert outcome == Ok(item)
                items.append(outcome.value)
            field = lib.run("mk", ("list", "items", code.lst(items))).outcome.value
        elif isinstance(field, Card):
            assert lib.run("mk", (field.sort, field.tag, code.lst(field.fields))).outcome == Ok(field)
        fields.append(field)
    assert lib.run("mk", ("sig", signature.tag, code.lst(fields))).outcome == Ok(signature)
    assert lib.run("mk", ("sig", signature.tag, code.lst())).outcome == Bottom("invalid")


def test_declared_pattern_and_origin_cards():
    lib = library()
    template_code = code.make_code("object", code.sig_const(), (), nodes.Lit(3), lambda _: None)
    for sort, tag, fields in (("pattern", "none", ()), ("pattern", "value", (3,)),
                              ("pattern", "entry", ("k", code.encode_pattern(3))),
                              ("origin", "template", (template_code, code.lst()))):
        assert lib.run("mk", (sort, tag, code.lst(fields))).outcome == Ok(code.Card(sort, tag, fields))


@pytest.mark.parametrize("signature", (
    Card("sig", "law", (code.lst((Card("var", "var", (3, "int")),)),)),
    Card("sig", "bridge", ("code", "code", code.lst((Card("pair", "pair", ("add", 3)),)),
                              Card("opt", "none"))),
    Card("sig", "template", (code.lst((Card("param", "param", (3, "int")),)), "operation")),
))
def test_malformed_signatures_fail_at_exact_layer_zero_boundary(signature):
    lib = library()
    template = code.make_code("object", code.sig_const(), (), nodes.Lit(3), lambda _: None)
    malformed = Card("code", "def", (template.fields[0], signature, *template.fields[2:]))
    assert lib.run("mk", ("code", "def", code.lst(malformed.fields))).outcome == Bottom("invalid")


def test_specialization_records_every_input_and_exact_cases(built):
    lib, sources, _ = built
    program = specialization_family(lib, sources)[0]
    ledger, digest = record_specialization(lib, program, 3)
    record = ledger.record(digest, lib.world.world_hash())
    assert record.produced_by == (code.code_hash(code.quote_from_library(lib, "specialize")),
                                  code.code_hash(program), content_hash(encode(3)))
    scope = record.evidence[0].scope
    assert scope["size"] == 7
    assert scope["cases"] == [[code.code_hash(program), 3, argument] for argument in range(7)]
    assert scope["domain_hash"] == content_hash(scope["cases"])


def test_template_family_evidence_counts_members(built):
    lib, _, _ = built
    scope = lib.get("Specialize").evidence.scope
    assert scope["family"] == [{"k": 0}, {"k": 3}]
    assert scope["size"] == scope["family_count"] == 2
    assert len(scope["family_members"]) == 2
    assert scope["family_hash"] == content_hash(scope["family_members"])
    assert [row["args"] for row in scope["family_members"]] == scope["family"]
    assert scope["input_hashes"] == [input_hash((0,)), input_hash((3,))]
    for member, row in zip(lib.specialize_members, scope["family_members"]):
        member_scope = member.evidence.scope
        assert row["size"] == member_scope["size"] == 1
        assert row["domain_hash"] == member_scope["domain_hash"]


def test_export_identity_and_template_instance(built):
    lib, _, _ = built
    exported = json.loads(DEST.read_text())
    assert json.loads(DECL.read_text()) == declaration().to_dict()
    assert export_problems(exported, "code.json", strict=True) == []
    assert all(record["world_hash"] == declaration().world_hash() for record in exported["generated"])
    template = next(row for row in exported["story"] if row.get("record_name") == "Specialize")
    member = lib.get("Specialize_member_1")
    example = template["examples"][0]
    assert example["text"].startswith("Specialize[3]")
    assert example["outcome"]["kind"] == "Ok"
    # the export references the member's code value by content hash (the full card is reproducible)
    assert example["outcome"]["code_hash"] == code.code_hash(code.quote_from_library(lib, member.name))
    member_row = next(row for row in exported["story"] if row.get("record_name") == member.name)
    assert example["member"]["result"] == member_row["examples"][0]["outcome"]


def test_six_kinds_can_be_assembled_from_declared_cards(built):
    lib, _, _ = built
    names = ("poly", "const_fold", "pipeline", "fold_idempotent", "fold_bridge", "Specialize")
    for name in names:
        quoted = code.quote_from_library(lib, name)
        assert lib.run("mk", ("sig", quoted.fields[1].tag, code.lst(quoted.fields[1].fields))).outcome == Ok(
            quoted.fields[1])
        assert lib.run("mk", ("code", "def", code.lst(quoted.fields))).outcome == Ok(quoted)
    observation = code.make_code("observation", code.sig_obs(("x",)), (), nodes.Lit(1), lambda _: None)
    assert lib.run("mk", ("code", "def", code.lst(observation.fields))).outcome == Ok(observation)
    malformed = Card("sig", "law", (code.lst((Card("var", "var", (3, "int")),)),))
    broken = Card("code", "def", (*code.quote_from_library(lib, "fold_idempotent").fields[:1],
                                  malformed, *code.quote_from_library(lib, "fold_idempotent").fields[2:]))
    assert lib.run("mk", ("code", "def", code.lst(broken.fields))).outcome == Bottom("invalid")


def _strict_program(program, arguments):
    """Evaluate the arithmetic subset without the kernel or the code-world evaluator."""
    decoded = code.decode(program)
    bindings = dict(zip(decoded.main.params, arguments))

    def condition(node, environment):
        if isinstance(node, nodes.Always):
            return True, 0
        if isinstance(node, nodes.Not):
            value, steps = condition(node.operand, environment)
            return not value, steps
        if isinstance(node, (nodes.And, nodes.Or)):
            left, steps = condition(node.left, environment)
            if left == isinstance(node, nodes.Or):
                return left, steps
            right, more_steps = condition(node.right, environment)
            return right, steps + more_steps
        assert isinstance(node, nodes.Test)
        result, steps = evaluate(node.expr, environment)
        assert isinstance(result, Ok)
        return result.value in (True, Card("bool", "true")), steps

    def evaluate(node, environment):
        if isinstance(node, nodes.Var):
            return Ok(environment[node.name]), 0
        if isinstance(node, nodes.Lit):
            return Ok(node.value), 0
        if isinstance(node, nodes.Let):
            value, steps = evaluate(node.value, environment)
            if not isinstance(value, Ok):
                return value, steps
            result, tail_steps = evaluate(node.body, {**environment, node.name: value.value})
            return result, steps + tail_steps
        if isinstance(node, nodes.Case):
            steps = 0
            for test, body in node.arms:
                active, used = condition(test, environment)
                steps += used
                if active:
                    result, used = evaluate(body, environment)
                    return result, steps + used
            assert node.default is not None
            result, used = evaluate(node.default, environment)
            return result, steps + used
        assert isinstance(node, nodes.Call)
        args, steps = [], 0
        for argument in node.args:
            result, used = evaluate(argument, environment)
            steps += used
            if not isinstance(result, Ok):
                return result, steps
            args.append(result.value)
        if node.fn == "div" and args[1] == 0:
            return Bottom("div_zero"), steps + 1
        operations = {"add": lambda: args[0] + args[1], "sub": lambda: args[0] - args[1],
                      "mul": lambda: args[0] * args[1], "div": lambda: args[0] // args[1],
                      "is_zero": lambda: args[0] == 0}
        assert node.fn in operations
        return Ok(operations[node.fn]()), steps + 1

    return evaluate(decoded.main.body, bindings)


def test_independent_strict_arithmetic_and_commuting_domains(built):
    lib, sources, counterexample = built
    original_steps = folded_steps = cases = 0
    assert len(sources) == 224
    for program in sources:
        fold = lib.run("const_fold", (program,)).outcome.value
        assert lib.run("const_fold", (fold,)).outcome == Ok(fold)
        assert lib.run("fold_bridge", (program,)).outcome == Ok(fold)
        for argument in range(7):
            before = _strict_program(program, (argument,))
            after = _strict_program(fold, (argument,))
            assert before[0] == after[0]
            assert (run_code(lib, program, (argument,)).outcome,
                    run_code(lib, program, (argument,)).steps) == before
            assert (run_code(lib, fold, (argument,)).outcome,
                    run_code(lib, fold, (argument,)).steps) == after
            original_steps += before[1]
            folded_steps += after[1]
            cases += 1
    assert (cases, original_steps, folded_steps) == (1568, 2443, 1267)
    unsafe = lib.run("simplify_unsafe", (counterexample,)).outcome.value
    assert _strict_program(counterexample, (0,))[0] == Bottom("div_zero")
    assert _strict_program(unsafe, (0,))[0] == Ok(0)


def test_specialization_exact_independent_domain(built):
    lib, sources, _ = built
    cases = 0
    for program in specialization_family(lib, sources):
        for constant in range(7):
            generated = lib.run("specialize", (program, constant)).outcome.value
            for argument in range(7):
                assert _strict_program(program, (constant, argument))[0] == _strict_program(
                    generated, (argument,))[0]
                cases += 1
    assert cases == 1470


def test_memoized_and_plain_recursion_charge_same_steps(built):
    lib, _, witness = built
    definition = lib.get("const_fold")
    assert any(isinstance(item, nodes.Rec) and item.memo for item in nodes.walk(definition.body))
    memoized = lib.run("const_fold", (witness,), trace=True)
    plain_body = nodes.map_nodes(definition.body, lambda node: replace(node, memo=False)
                                 if isinstance(node, nodes.Rec) else node)
    (parameter,) = definition.spec.extra["input_names"]
    plain = kernel.evaluate(plain_body, {parameter: witness}, scope=lib.scope())
    assert memoized.outcome == plain.outcome
    assert (memoized.steps, plain.steps) == (122, 122)
    assert (memoized.work, plain.work) == (78, 122)
