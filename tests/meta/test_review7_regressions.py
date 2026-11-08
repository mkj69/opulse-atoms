"""Review-7 generator regressions against the current template codec."""

from dataclasses import replace

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract, Definition, Edge, OperationSpec, TemplateSpec
from opulse.atoms.templates import instantiate
from opulse.atoms.values import Card, Ok
from opulse.meta.code import (
    Resolved,
    code_hash,
    decode,
    make_code,
    quote_from_library,
    sig_op,
)
from opulse.meta.generators import (
    cite_template_evidence,
    instantiate_family,
    run_generator,
)
from opulse.meta.identity import Ledger, dependency_hash
from tests.meta.test_generators import integer_library, member_request


def step_template(library):
    pattern = {"role": "transform", "inputs": [{"sort": "int"}], "output": {"sort": "int"},
               "rule": "add $step", "input_names": ["arg0"],
               "definition_body": nodes.to_json(nodes.Call("add", (nodes.Var("arg0"), nodes.Lit("$step"))))}
    template = Definition("Step", "template", "invented", 1, (),
                          TemplateSpec("Step", (("step", "int"),), "operation", pattern), nodes.Lit(0))
    library.write(template)
    library.check("Step")
    library.make_callable("Step", ((),))
    return library.get("Step")


def generator_returning(library, name, result):
    generator = Definition(name, "operation", "invented", 1, (),
                           OperationSpec(name, "transform", (), Edge(result.sort), "emit value"),
                           nodes.Lit(result))
    library.write(generator)
    library.check(name)
    library.make_callable(name, ((),))
    return name


def test_template_output_ledger_identifies_stored_definition_and_round_trips():
    library = integer_library()
    step_template(library)
    request = Card("generator", "instantiate", ("Step", Card("list", "items", (2,))))
    record = run_generator(library, Ledger(), generator_returning(library, "emit_step", request), ())[0]
    produced = next(item for item in library.definitions.values()
                    if item.name.startswith("generated_") and item.kind == "operation")
    quoted = quote_from_library(library, produced.name)
    assert quoted == record.code
    assert code_hash(quoted) == code_hash(record.code)
    assert dependency_hash(quoted) == record.deps_hash
    decoded = decode(record.code)
    assert len(decoded.deps) == 1
    assert decoded.main.body == nodes.Let(
        "v0", nodes.Lit(kernel.FnRef(decoded.deps[0].name)),
        nodes.Call("add", (nodes.Var("x0"), nodes.Lit(2))))
    assert code_hash(next(dep for dep in (record.code.fields[4].fields) if dep.sort == "code")) == code_hash(
        quote_from_library(library, "Step"))
    assert library.run(produced.name, (3,)).outcome == Ok(5)
    assert library.run(produced.name, (3,)).steps == 1
    assert Ledger.from_dict(Ledger.from_library(library).to_dict()).record(
        code_hash(quoted), library.world.world_hash()).code == quoted


def test_sampled_members_never_yield_promotable_family():
    library = integer_library()
    step_template(library)
    members = instantiate_family(
        library, "Step", [{"step": 1}],
        lambda index, args, member: replace(member_request(1), method="sampled", seed=42))
    assert members[0].evidence.method == "sampled"
    assert library.get("Step").evidence.method == "sampled"
    with pytest.raises(PipelineError, match="sampled"):
        library.promote("Step", Contract("family"))


def test_forged_outside_member_cannot_cite_family():
    library = integer_library()
    step_template(library)
    member = instantiate_family(library, "Step", [{"step": 1}],
                                lambda index, args, definition: member_request(1))[0]
    outside = instantiate(library.get("Step"), {"step": 4}, "outside", lib=library)
    forged = replace(outside, spec=replace(outside.spec, extra={
        **outside.spec.extra, "template": member.spec.extra["template"]}))
    assert cite_template_evidence(member, library)
    assert not cite_template_evidence(outside, library)
    assert not cite_template_evidence(forged, library)
    library.write(forged)
    library.check("outside")
    assert not cite_template_evidence(library.get("outside"), library)


def test_unrelated_unquotable_candidate_does_not_block_dependency_resolution():
    library = integer_library()
    step_template(library)
    unquotable = instantiate(library.get("Step"), {"step": 2}, "unquotable", lib=library)
    library.write(unquotable)
    library.check("unquotable")
    library.make_callable("unquotable", ((0,),))
    box = Definition("Box", "template", "invented", 1, (),
                     TemplateSpec("Box", (("unit", "int"),), "object",
                                  {"form": "compose", "tags": {"unit": []}}), nodes.Lit(0))
    library.write(box)
    library.check("Box")
    library.make_callable("Box", ((),))
    unquotable_object = instantiate(library.get("Box"), {"unit": 2}, "unquotable_object", lib=library)
    library.write(unquotable_object)
    library.check("unquotable_object")
    library.make_callable("unquotable_object", ((),))
    simple = Definition("simple", "operation", "invented", 1, (),
                        OperationSpec("simple", "transform", (), Edge("int"), "constant"), nodes.Lit(7))
    library.write(simple)
    library.check("simple")
    library.make_callable("simple", ((),))
    code = make_code("operation", sig_op((), ("int", "bottom")), (),
                     nodes.Call("simple", ()),
                     lambda name: Resolved(code=quote_from_library(library, "simple"))
                     if name == "simple" else None)
    record = run_generator(library, Ledger(), generator_returning(library, "emit_reference", code), ())[0]
    produced = next(item for item in library.definitions.values() if item.name.startswith("generated_"))
    assert record.code == quote_from_library(library, produced.name)
    assert library.run(produced.name, ()).outcome == Ok(7)
    assert library.run(produced.name, ()).steps == 0


def test_core_only_template_output_keeps_definition_and_provenance_separate():
    library = integer_library()
    template = Definition("Box", "template", "invented", 1, (),
                          TemplateSpec("Box", (("unit", "int"),), "object",
                                       {"form": "compose", "tags": {"unit": []}}), nodes.Lit(0))
    library.write(template)
    library.check("Box")
    library.make_callable("Box", ((),))
    request = Card("generator", "instantiate", ("Box", Card("list", "items", (2,))))
    ledger = Ledger()
    record = run_generator(library, ledger, generator_returning(library, "emit_box", request), ())[0]
    assert record.definition == library.get(record.definition.name)
    assert record.origin.sort == "origin" and record.origin.tag == "template"
    assert record.origin.fields[0] == quote_from_library(library, "Box")
    assert ledger.provenance(record.definition.name) == record
    assert Ledger.from_dict(ledger.to_dict()).provenance(record.definition.name) == record
    assert Ledger.from_library(library).provenance(record.definition.name).definition == record.definition
