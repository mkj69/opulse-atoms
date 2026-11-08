"""Exact generator and template-family pipelines (atoms-meta, section 7)."""

from dataclasses import replace

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.library import Library, PipelineError, VerifyRequest
from opulse.atoms.spec import (
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    OperationSpec,
    TemplateSpec,
    content_hash,
)
from opulse.atoms.templates import instantiate
from opulse.atoms.values import Card, Ok, encode
from opulse.atoms.world import WorldDecl
from opulse.meta.code import (
    Resolved,
    atom_digest,
    code_hash,
    make_code,
    quote_from_library,
    sig_bridge,
    sig_law,
    sig_op,
)
from opulse.meta.generators import (
    cite_template_evidence,
    instantiate_family,
    run_generator,
)
from opulse.meta.identity import Ledger


def integer_library(*, with_eq=False):
    operations = (
        OperationSpec("add", "combine", (Edge("int"), Edge("int")), Edge("int"), "integer addition"),
        OperationSpec("is_zero", "decide", (Edge("int"),), Edge("bool"), "zero predicate"),
    )
    extra = (OperationSpec("eq", "decide", (Edge("int"), Edge("int")), Edge("bool"), "equality"),) if with_eq else ()
    world = WorldDecl("generator_integer", 1, "atoms-v2", {}, {},
                      (ObjectSpec("int", "given"), ObjectSpec("code", "given"),
                       ObjectSpec("generator", "given")), operations + extra,
                      {"nodes": list(nodes.NODE_NAMES), "recursion": "fuel"}, {}, {},
                      open_kinds=("operation", "object", "combinator", "observation", "law", "bridge"))
    return Library(world, (kernel.Atom("add", 2, lambda left, right: left + right),
                           kernel.Atom("is_zero", 1, lambda value: value == 0)) +
                   ((kernel.Atom("eq", 2, lambda left, right: left == right),) if with_eq else ()))


def member_request(increment):
    return VerifyRequest("bounded", ((0,), (3,)), {"domain": "bounded inputs 0 and 3", "size": 2},
                         reference=lambda value: value + increment)


def test_generator_program_outputs_are_new_unevidenced_definitions():
    library = integer_library()
    signature = sig_op((("int", "bottom"),), ("int", "bottom"))
    resolver = lambda name: Resolved(digest=atom_digest(library.world.operations[0])) if name == "add" else None
    first = make_code("operation", signature, ("value",),
                      nodes.Call("add", (nodes.Var("value"), nodes.Lit(1))), resolver)
    second = make_code("operation", signature, ("value",),
                       nodes.Call("add", (nodes.Var("value"), nodes.Lit(2))), resolver)
    generator = Definition("choose_code", "operation", "invented", 1, ("is_zero",),
                           OperationSpec("choose_code", "transform", (Edge("int"),), Edge("code"),
                                         "choose a code value", extra={"input_names": ["selector"]}),
                           nodes.Case(((nodes.Test(nodes.Call("is_zero", (nodes.Var("selector"),))),
                                        nodes.Lit(first)),), nodes.Lit(second)))
    library.write(generator)
    library.check(generator.name)
    library.make_callable(generator.name, ((0,),))
    assert library.run(generator.name, (0,)).outcome == Ok(first)
    assert library.run(generator.name, (0,)).steps == 1
    ledger = Ledger()
    produced = run_generator(library, ledger, generator.name, (0,))
    assert len(produced) == 1
    record = produced[0]
    assert record.status == "callable" and record.evidence == () and record.contract is None
    assert record.produced_by == (code_hash(quote_from_library(library, generator.name)),
                                  content_hash(encode(0)))
    output_name = f"generated_{code_hash(first)[:12]}"
    assert library.get(output_name).origin == "invented"
    assert library.get(output_name).status == "callable"
    assert library.get(output_name).evidence is None
    assert library.run(output_name, (3,)).outcome == Ok(4)
    assert library.run(output_name, (3,)).steps == 1
    library.verify(output_name, member_request(1))
    assert library.get(output_name).evidence.checks == ("reference", "unfold_equivalence")
    assert record.evidence == ()
    repeated = run_generator(library, ledger, generator.name, (0,))[0]
    assert code_hash(repeated.code) == code_hash(record.code)
    assert library.get(f"{output_name}_1").status == "callable"
    assert library.get(f"{output_name}_1").evidence is None
    other = run_generator(library, ledger, generator.name, (1,))[0]
    assert code_hash(other.code) == code_hash(second) != code_hash(record.code)
    assert other.status == "callable" and other.evidence == ()
    assert library.run(f"generated_{code_hash(second)[:12]}", (3,)).outcome == Ok(5)


def test_template_family_each_member_verifies_and_citation_stays_bounded():
    library = integer_library()
    pattern = {"name": "ignored", "role": "transform", "inputs": [{"sort": "int"}],
               "output": {"sort": "int"}, "rule": "add $increment", "input_names": ["arg0"],
               "definition_body": nodes.to_json(nodes.Call("add", (nodes.Var("arg0"),
                                                              nodes.Lit("$increment"))))}
    template = Definition("Iter", "template", "invented", 1, (),
                          TemplateSpec("Iter", (("increment", "int"),), "operation", pattern), nodes.Lit(0))
    library.write(template)
    family = [{"increment": 1}, {"increment": 2}, {"increment": 3}]
    members = instantiate_family(library, "Iter", family,
                                 lambda index, args, member: member_request(args["increment"]))
    assert library.get("Iter").evidence.method == "bounded"
    assert library.get("Iter").evidence.scope["family"] == family
    assert len(members) == 3
    for index, member in enumerate(members):
        assert member.status == "verified" and member.evidence.method == "bounded"
        assert member.evidence.checks == ("reference", "unfold_equivalence")
        assert cite_template_evidence(member, library)
        assert library.run(member.name, (3,)).outcome == Ok(index + 4)
        assert library.run(member.name, (3,)).steps == 1
    outside = instantiate(library.get("Iter"), {"increment": 4}, "outside", lib=library)
    assert not cite_template_evidence(outside, library)
    repeated = instantiate(library.get("Iter"), family[0], members[0].name, lib=library)
    assert repeated.content_hash() == replace(members[0], status="written", evidence=None).content_hash()
    assert repeated.content_hash() != outside.content_hash()


def test_generator_template_request_starts_without_evidence():
    library = integer_library()
    pattern = {"role": "transform", "inputs": [{"sort": "int"}], "output": {"sort": "int"},
               "rule": "add $step", "input_names": ["arg0"],
               "definition_body": nodes.to_json(nodes.Call("add", (nodes.Var("arg0"), nodes.Lit("$step"))))}
    template = Definition("Step", "template", "invented", 1, (),
                          TemplateSpec("Step", (("step", "int"),), "operation", pattern), nodes.Lit(0))
    library.write(template)
    library.check("Step")
    library.make_callable("Step", ((),))
    request = Card("generator", "instantiate", ("Step", Card("list", "items", (2,))))
    generator = Definition("request_step", "operation", "invented", 1, (),
                           OperationSpec("request_step", "transform", (), Edge("generator"), "request step"),
                           nodes.Lit(request))
    library.write(generator)
    library.check(generator.name)
    library.make_callable(generator.name, ((),))
    record = run_generator(library, Ledger(), generator.name, ())[0]
    assert record.status == "callable" and record.evidence == ()
    assert record.produced_by == (code_hash(quote_from_library(library, generator.name)),)
    assert record.code.fields[4].fields[-1].sort == "origin"
    assert record.code.fields[4].fields[-1].fields[0] == quote_from_library(library, "Step")
    repeated = run_generator(library, Ledger(), generator.name, ())[0]
    assert code_hash(repeated.code) == code_hash(record.code)
    assert repeated.produced_by == record.produced_by
    next_request = Card("generator", "instantiate", ("Step", Card("list", "items", (3,))))
    next_generator = Definition("request_step_three", "operation", "invented", 1, (),
                                OperationSpec("request_step_three", "transform", (), Edge("generator"), "request step"),
                                nodes.Lit(next_request))
    library.write(next_generator)
    library.check(next_generator.name)
    library.make_callable(next_generator.name, ((),))
    third = run_generator(library, Ledger(), next_generator.name, ())[0]
    assert code_hash(third.code) != code_hash(record.code)
    assert third.produced_by == (code_hash(quote_from_library(library, next_generator.name)),)
    produced = [definition for definition in library.definitions.values()
                if definition.spec.extra.get("template", {}).get("name") == "Step"]
    assert len(produced) == 3
    assert record.code == quote_from_library(library, produced[0].name)
    assert all(member.status == "callable" and member.evidence is None for member in produced)
    assert library.run(produced[0].name, (3,)).outcome == Ok(5)
    assert library.run(produced[0].name, (3,)).steps == 1
    library.verify(produced[0].name, member_request(2))
    assert library.get(produced[0].name).evidence.checks == ("reference", "unfold_equivalence")


def test_generator_must_be_callable_and_invented():
    library = integer_library()
    with pytest.raises((PipelineError, ValueError)):
        run_generator(library, Ledger(), "add", (1, 2))


def test_foreign_atom_code_cannot_enter_library():
    library = integer_library()
    signature = sig_op((("int", "bottom"),), ("int", "bottom"))
    code = make_code("operation", signature, ("value",),
                     nodes.Call("add", (nodes.Var("value"), nodes.Lit(1))),
                     lambda name: Resolved(digest="foreign") if name == "add" else None)
    generator = Definition("emit_foreign", "operation", "invented", 1, (),
                           OperationSpec("emit_foreign", "transform", (), Edge("code"), "foreign code"),
                           nodes.Lit(code))
    library.write(generator)
    library.check(generator.name)
    library.make_callable(generator.name, ((),))
    with pytest.raises(ValueError, match="foreign given atoms"):
        run_generator(library, Ledger(), generator.name, ())
    assert set(library.definitions) == {"add", "is_zero", "emit_foreign"}


def test_generator_bridge_enters_core_pipeline_with_own_evidence():
    library = integer_library()
    code = make_code("bridge", sig_bridge("int", "int", (("is_zero", "is_zero"),)),
                     ("x",), nodes.Var("x"), lambda _: None)
    generator = Definition("emit_bridge", "operation", "invented", 1, (),
                           OperationSpec("emit_bridge", "transform", (), Edge("code"), "bridge"),
                           nodes.Lit(code))
    library.write(generator)
    library.check(generator.name)
    library.make_callable(generator.name, ((),))
    record = run_generator(library, Ledger(), generator.name, ())[0]
    name = f"generated_{code_hash(code)[:12]}"
    assert record.status == "callable" and record.evidence == ()
    assert record.produced_by == (code_hash(quote_from_library(library, generator.name)),)
    assert library.get(name).kind == "bridge" and library.get(name).evidence is None
    bridge_run = library.run(name, (1,))
    assert bridge_run.outcome == Ok(1) and bridge_run.steps == 0
    library.verify(name, VerifyRequest("bounded", ((0,), (1,)), {"domain": "0 and 1", "size": 2}))
    assert library.get(name).evidence.checks == ("commutes", "total_on_domain")
    assert library.get(name).evidence.method == "bounded"
    assert record.evidence == ()


def test_generator_law_enters_core_pipeline_with_own_evidence():
    library = integer_library(with_eq=True)
    code = make_code("law", sig_law((("value", "int"),)), ("value",),
                     nodes.Call("eq", (nodes.Var("value"), nodes.Var("value"))),
                     lambda name: Resolved(digest=atom_digest(library.world.operations[2])) if name == "eq" else None)
    generator = Definition("emit_law", "operation", "invented", 1, (),
                           OperationSpec("emit_law", "transform", (), Edge("code"), "law"),
                           nodes.Lit(code))
    library.write(generator)
    library.check(generator.name)
    library.make_callable(generator.name, ((),))
    record = run_generator(library, Ledger(), generator.name, ())[0]
    produced = next(item for item in library.definitions.values() if isinstance(item.spec, LawSpec))
    assert record.status == "callable" and record.evidence == ()
    assert record.produced_by == (code_hash(quote_from_library(library, generator.name)),)
    assert library.get(produced.name).status == "callable" and produced.evidence is None
    law_run = kernel.evaluate(produced.spec.statement, {"x0": 3}, library.scope())
    assert law_run.outcome == Ok(True) and law_run.steps == 1
    library.verify(produced.name, VerifyRequest("bounded", ((0,), (3,)),
                                                 {"domain": "0 and 3", "size": 2}))
    assert library.get(produced.name).evidence.method == "bounded"
    assert library.get(produced.name).evidence.checks == ("holds", "equation")
    assert record.evidence == ()
