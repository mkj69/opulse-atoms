"""Review-9 generator and provenance regressions (atoms-meta, section 7)."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opulse.atoms import nodes
from opulse.atoms.spec import (
    Definition,
    Edge,
    OperationSpec,
    TemplateSpec,
    content_hash,
)
from opulse.atoms.templates import instantiate
from opulse.atoms.values import Card, Ok, encode
from opulse.meta.code import (
    code_hash,
    instantiate_code,
    make_code,
    quote_from_library,
    sig_obs,
)
from opulse.meta.generators import run_generator
from opulse.meta.identity import Ledger, LedgerError
from tests.meta.test_generators import integer_library
from tests.meta.test_review7_regressions import generator_returning, step_template


def test_direct_template_code_preserves_origin_and_stored_identity():
    library = integer_library()
    step_template(library)
    member = instantiate(library.get("Step"), {"step": 2}, "member", lib=library)
    library.write(member)
    library.check("member")
    library.make_callable("member", ((0,),))
    source = quote_from_library(library, "member")
    generator = generator_returning(library, "emit_member", source)
    ledger = Ledger()
    record = run_generator(library, ledger, generator, ())[0]
    produced = library.get(f"generated_{code_hash(source)[:12]}")
    assert record.code == quote_from_library(library, produced.name) == source
    assert produced.spec.extra["template"]["args"] == {"step": 2}
    assert record.produced_by == (code_hash(quote_from_library(library, generator)),)
    assert library.run(produced.name, (3,)).outcome == Ok(5)
    assert library.run(produced.name, (3,)).steps == 1


def test_template_request_records_generator_inputs_separately_from_origin():
    library = integer_library()
    step_template(library)
    request = Card("generator", "instantiate", ("Step", Card("list", "items", (2,))))
    generator = generator_returning(library, "emit_request", request)
    record = run_generator(library, Ledger(), generator, ())[0]
    assert record.produced_by == (code_hash(quote_from_library(library, generator)),)
    assert record.code.fields[4].fields[-1].fields == (
        quote_from_library(library, "Step"),
        Card("list", "items", (Card("pattern", "value", (2,)),)),
    )
    assert code_hash(record.code) != record.produced_by[0]


def test_template_request_producer_uses_run_inputs_not_template_arguments():
    library = integer_library()
    step_template(library)
    request = Card("generator", "instantiate", ("Step", Card("list", "items", (2,))))
    generator = Definition("emit_with_input", "operation", "invented", 1, (),
                           OperationSpec("emit_with_input", "transform", (Edge("int"),),
                                         Edge("generator"), "emit request", extra={"input_names": ["value"]}),
                           nodes.Lit(request))
    library.write(generator)
    library.check(generator.name)
    library.make_callable(generator.name, ((11,),))
    record = run_generator(library, Ledger(), generator.name, (11,))[0]
    assert record.produced_by == (code_hash(quote_from_library(library, generator.name)),
                                  content_hash(encode(11)))
    assert record.code.fields[4].fields[-1].fields[1].fields == (Card("pattern", "value", (2,)),)


def test_forged_core_only_origin_rejected_on_insertion_and_import():
    library = integer_library()
    box = Definition("Box", "template", "invented", 1, (), TemplateSpec(
        "Box", (("unit", "int"),), "object", {"form": "compose", "tags": {"unit": []}}), nodes.Lit(0))
    library.write(box)
    library.check("Box")
    library.make_callable("Box", ((),))
    actual = instantiate(library.get("Box"), {"unit": 3}, "box_three", lib=library)
    _, origin = instantiate_code(quote_from_library(library, "Box"), (3,))
    _, forged = instantiate_code(quote_from_library(library, "Box"), (2,))
    ledger = Ledger()
    assert ledger.add_provenance(actual, origin, library.world.world_hash()).origin == origin
    with pytest.raises(LedgerError, match="provenance"):
        ledger.add_provenance(actual, forged, library.world.world_hash())
    assert ledger.provenance(actual.name).origin == origin
    corrupted = deepcopy(ledger.to_dict())
    corrupted["provenance"][0]["origin"] = encode(forged)
    with pytest.raises(LedgerError, match="provenance"):
        Ledger.from_dict(corrupted)
    assert Ledger.from_dict(ledger.to_dict()).provenance(actual.name).origin == origin


@pytest.mark.parametrize("field", ("body", "spec", "depends_on"))
def test_core_only_origin_rejects_modified_definition_fields(field):
    library = integer_library()
    box = Definition("Box", "template", "invented", 1, (), TemplateSpec(
        "Box", (("unit", "int"),), "object", {"form": "compose", "tags": {"unit": []}}), nodes.Lit(0))
    library.write(box)
    library.check("Box")
    library.make_callable("Box", ((),))
    actual = instantiate(library.get("Box"), {"unit": 3}, "box_three", lib=library)
    _, origin = instantiate_code(quote_from_library(library, "Box"), (3,))
    changed = {
        "body": nodes.Lit(4),
        "spec": replace(actual.spec, tags={"other": []}),
        "depends_on": ("not_Box",),
    }[field]
    with pytest.raises(LedgerError, match="provenance"):
        Ledger().add_provenance(replace(actual, **{field: changed}), origin, library.world.world_hash())


def test_core_only_generator_request_preserves_producer_and_origin():
    library = integer_library()
    box = Definition("Box", "template", "invented", 1, (), TemplateSpec(
        "Box", (("unit", "int"),), "object", {"form": "compose", "tags": {"unit": []}}), nodes.Lit(0))
    library.write(box)
    library.check("Box")
    library.make_callable("Box", ((),))
    request = Card("generator", "instantiate", ("Box", Card("list", "items", (3,))))
    generator = generator_returning(library, "emit_box", request)
    record = run_generator(library, Ledger(), generator, ())[0]
    assert record.definition.kind == "object" and record.definition.spec.form == "compose"
    assert record.origin.fields[0] == quote_from_library(library, "Box")
    assert record.produced_by == (code_hash(quote_from_library(library, generator)),)
    assert Ledger.from_dict(Ledger.from_library(library).to_dict()).provenance(
        record.definition.name).origin == record.origin


def test_generator_observation_enters_core_and_round_trips():
    library = integer_library()
    source = make_code("observation", sig_obs(()), (), nodes.Lit(7), lambda _: None)
    generator = generator_returning(library, "emit_observation", source)
    record = run_generator(library, Ledger(), generator, ())[0]
    produced = library.get(f"generated_{code_hash(source)[:12]}")
    assert produced.kind == "observation" and produced.status == "callable"
    assert record.code == quote_from_library(library, produced.name) == source
    assert record.produced_by == (code_hash(quote_from_library(library, generator)),)
    assert produced.evidence is None


def test_generator_template_enters_core_and_round_trips():
    library = integer_library()
    step_template(library)
    source = quote_from_library(library, "Step")
    generator = generator_returning(library, "emit_template", source)
    record = run_generator(library, Ledger(), generator, ())[0]
    produced = library.get(f"generated_{code_hash(source)[:12]}")
    assert produced.kind == "template" and produced.status == "callable"
    assert record.code == quote_from_library(library, produced.name) == source
    assert record.produced_by == (code_hash(quote_from_library(library, generator)),)
    assert produced.evidence is None
