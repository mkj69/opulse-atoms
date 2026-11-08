"""Independent design-oracle and kernel-pipeline regression checks."""

import importlib.util
import json
import os
import re
from dataclasses import replace
from itertools import islice

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.boundary import Boundary
from opulse.atoms.laws import RewriteError, replay_rewrite, rewrite
from opulse.atoms.library import PipelineError, sampled
from opulse.atoms.spec import Contract
from opulse.atoms.values import Bottom, Card, Ok, Unknown, encode_outcome
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.integer.adapter import check_local
from opulse.worlds_v2.integer.export import (
    DESIGN_PATH,
    EXPORT_PATH,
    build_export,
    display,
    run_expression,
)
from opulse.worlds_v2.integer.story import (
    build_library,
    definitions,
    items,
    pair,
    scope_for,
)
from opulse.worlds_v2.integer.world import DECL_PATH, decl, new_library


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def reference():
    source = DESIGN_PATH.with_suffix(".py")
    spec = importlib.util.spec_from_file_location("integer_depth_reference", source)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_tower_examples_against_independent_reference(library, reference):
    design = json.loads(DESIGN_PATH.read_text())
    export = json.loads(EXPORT_PATH.read_text())
    assert len(design["tower"]) == 12 and len(export["story"]) == 20
    for original, card in zip(design["tower"], export["story"][:12]):
        expected = reference.display(reference.evaluate(original["example"]))
        run = run_expression(library, original["example"])
        assert card["examples"][0]["text"] == original["example"]
        assert expected == original["value"] == display(run.outcome.value)
        assert card["examples"][0]["outcome"] == encode_outcome(run.outcome)
        assert card["examples"][0]["steps"] == run.steps
        assert card["kind"] == original["kind"]
        definition = library.get(card["name"])
        assert definition.status == "promoted" and definition.layer == card["def_layer"]
        assert definition.evidence.method == "bounded"
        assert definition.evidence.scope["size"] > 0
        if definition.kind == "object" and definition.spec.canon is not None:
            assert {"canon_total", "canon_idempotent", "canon_keeps_valid"} <= set(definition.evidence.checks)
        assert len(definition.contract.guarantees) > 0
        for fresh in card["examples"][1:]:
            if "ok" in fresh["outcome"]:
                assert reference.display(reference.evaluate(fresh["text"])) == display(run_expression(library, fresh["text"]).outcome.value)


def test_depth_reference_exercises_independent_bounded_oracles(reference, capsys):
    reference.verify()
    assert capsys.readouterr().out.strip() == "OK"


def test_first_three_cards_build_fresh_without_export_cache():
    fresh = new_library()
    for definition in islice(definitions(), 3):
        fresh.write(definition)
        if definition.kind == "object":
            fresh.check(definition.name)
        else:
            check_local(fresh, definition.name)
        request = scope_for(definition.name)
        sample = (kernel.FnRef(request.extra["op_family"][0]), *request.domain[0]) if definition.kind == "combinator" else request.domain[0]
        fresh.make_callable(definition.name, (sample,))
        fresh.verify(definition.name, request)
        fresh.account(definition.name)
        fresh.promote(definition.name, Contract("Bounded fresh build"))
    assert fresh.run("mul", (-3, 4)).outcome == Ok(-12)


def test_failure_and_fuel_are_distinct(library):
    failure = run_expression(library, "?bounded_convergent{Pair<CF<Frac<1, 2>>, Nat<0>>}")
    assert failure.outcome == Bottom("no_convergent")
    assert json.loads(EXPORT_PATH.read_text())["story"][11]["examples"][-1]["outcome"] == {"bottom": "no_convergent"}
    out_of_fuel = run_expression(library, "@repeat[succ](Int<0>,Nat<24>)", fuel=4)
    assert out_of_fuel.outcome == Unknown("fuel")
    assert library.run("nat.make", (-1,)).outcome == Bottom("invalid")
    assert library.run("frac.make", (pair(1, 0),)).outcome == Bottom("invalid")
    assert library.scope().resolve("nat") is None
    assert library.scope().resolve("frac") is None
    assert library.scope().resolve("cf") is None
    assert library.run("cf_divmod", (1, 0)).outcome == Bottom("divisor")
    assert run_expression(library, "@sequence[succ,neg](Int<4>)").outcome == Ok(-5)
    assert library.run("value", (-8,)).outcome == Ok(-8)


def test_pipeline_and_boundaries(library):
    assert library.get("frac").spec.sealed
    with pytest.raises(PipelineError, match="sealed object private name"):
        library.run("frac.base", (library.run("frac.make", (pair(1, 2),)).outcome.value,))
    for definition in definitions():
        current = library.get(definition.name)
        assert current.origin == "invented" and current.evidence.world_hash == library.world.world_hash()
        assert current.evidence.scope["size"] > 0
        checked = current.evidence.scope["checked"]
        assert checked["size"] == current.evidence.scope["size"]
        assert len(checked["sha256"]) == 64
    for name, arguments in (("nat.make", (3,)), ("mul", (-3, 4)), ("frac.make", (pair(3, 9),)),
                            ("qadd", (library.run("frac.make", (pair(1, 2),)).outcome.value,
                                      library.run("frac.make", (pair(1, 3),)).outcome.value))):
        run = library.run(name, arguments, trace=True)
        unfolded = kernel.evaluate(kernel.inline(nodes.Call(name, tuple(nodes.Lit(arg) for arg in arguments)),
                                                  library.scope()), scope=library.scope())
        assert (run.outcome, run.steps) == (unfolded.outcome, unfolded.steps)
        assert unfold_equivalent(run.trace,
                                 (Boundary(), Boundary(depth=0), Boundary(open_names=frozenset({name})))).ok


def test_widened_evidence_families(library):
    expected = {"nat": 61, "repeat": 50, "whole": 65, "qadd": 100, "qmul": 100,
                "fold_frac": 85, "convergents": 65, "bounded_convergent": 65}
    for name, size in expected.items():
        request = scope_for(name)
        evidence = library.get(name).evidence
        assert len(request.domain) == evidence.scope["size"] == size
        if name in ("repeat", "fold_frac", "convergents"):
            assert len(evidence.scope["op_family"]) == 2
            assert "fixed_ops" not in evidence.scope
            assert len(library._steps[name]) == size * 2
        else:
            assert len(library._steps[name]) == size
    assert len({arguments[0] for arguments in scope_for("whole").domain}) == 65
    assert len({arguments[0].fields[0] for arguments in scope_for("bounded_convergent").domain}) == 65


def test_promotion_refuses_missing_sampled_and_stale_evidence(library):
    candidate = next(definition for definition in definitions() if definition.name == "nat")
    fresh = new_library()
    fresh.write(candidate)
    fresh.check("nat")
    fresh.make_callable("nat", ((1,),))
    with pytest.raises(PipelineError, match="verified"):
        fresh.promote("nat", Contract("candidate"))
    request = sampled(lambda randomizer: (randomizer.randrange(3),), 3, 19, "bound 0..2")
    fresh.verify("nat", replace(request, extra={"interface_ops": {"nat.base": [0]},
                                               "reference_ops": {"nat.base": "nat.base"}}))
    with pytest.raises(PipelineError, match="sampled"):
        fresh.promote("nat", Contract("candidate"))
    fresh.world = replace(fresh.world, constants={"changed": 1})
    assert fresh.get("nat").status == "callable" and fresh.get("nat").evidence is None
    with pytest.raises(PipelineError, match="verified"):
        fresh.promote("nat", Contract("candidate"))
    assert library.derived_world().scopes()["nat"]["size"] == 61


def test_declaration_and_committed_export(library):
    assert validate(load(DECL_PATH)) == []
    assert WorldDecl.from_dict(decl().to_dict()).to_dict() == decl().to_dict()


@pytest.mark.skipif(os.getenv("OPULSE_RUN_SLOW") != "1", reason="fresh full export takes over 60 s")
def test_fresh_export_matches_committed():
    assert EXPORT_PATH.read_text() == json.dumps(build_export(), sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    assert EXPORT_PATH.stat().st_size < 3_000_000
    assert all(task["answer_checked"] for task in json.loads(EXPORT_PATH.read_text())["showcase"])


def test_export_notation_ascii():
    export = json.loads(EXPORT_PATH.read_text())
    for entry in export["story"]:
        assert entry["symbol"].isascii()
        if entry.get("decl"):
            assert entry["decl"].isascii()
        for sample in entry["examples"]:
            assert sample["text"].isascii()
    for task in export["showcase"]:
        assert task["prompt"].isascii() and task["answer"].isascii()


def test_story_declarations_are_parseable_at_computed_layers(library):
    from opulse.worlds_v2 import export_util
    from opulse.worlds_v2.integer.extensions import extend_library

    story = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    assert len(story) == 20
    assert {row["name"] for row in story if "ascii" not in row} == {
        "nat", "repeat", "mul", "frac", "qadd", "qmul", "cf_divmod", "cf",
        "convergents", "bounded_convergent", "add_comm", "mul_distrib", "Quot",
        "quot_frac", "hour",
    }
    if "Quot" not in library.definitions:
        extend_library(library)
    for row in story:
        definition = library.get(row["name"])
        digest = export_util.body_sha256(definition.body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            source = row["decl"]
            parsed = notation.parse_definition(source)
            assert parsed.layer == row["def_layer"]
            assert re.search(rf" L{row['def_layer']}$", source)
            assert row["ascii"] == source
            assert export_util.source_matches(row["ascii"], digest)
        else:
            assert not row.get("decl")
        assert row["design_text"] == row["design_decl"]


def test_parseable_example_sources_are_exact_evaluated_expressions():
    from opulse.worlds_v2.integer.export import parse

    story = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    literal_constructor_examples = {"qadd", "qmul", "cf", "Quot", "quot_frac", "hour"}
    for row in story:
        for sample in row["examples"]:
            if "ascii" in sample:
                assert sample["ascii"] == sample["text"]
                if row["name"] not in literal_constructor_examples:
                    assert notation.parse_expr(sample["text"]) == parse(sample["text"])


def test_law_and_template_rows_have_story_metadata():
    story = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    rows = story[12:]
    assert [row["name"] for row in rows] == ["add_comm", "mul_comm", "mul_distrib", "gcd_comm",
                                               "gcd_mul_lcm", "Quot", "quot_frac", "hour"]
    for layer, row in enumerate(rows, start=13):
        assert row["layer"] == layer
        assert isinstance(row["def_layer"], int)
        assert all(isinstance(row[key], str) and row[key].strip() for key in
                   ("title", "definition", "title_zh", "definition_zh", "symbol", "design_decl"))
        assert row["symbol"].isascii()
        if row["kind"] == "law":
            assert row["symbol"] == "#" + row["name"]
            if "ascii" in row:
                assert row["decl"].startswith("law " + row["symbol"] + ": eq(")
    assert rows[5]["symbol"] == "Quot[T, canon]"


@given(st.integers(-12, 12), st.integers(-12, 12).filter(lambda value: value != 0))
@settings(max_examples=30, deadline=None)
def test_frac_canon_total_idempotent_valid_and_unfolds(library, numerator, denominator):
    value = pair(numerator, denominator)
    spec = library.get("frac").spec
    canon = kernel.evaluate(spec.canon, {"x": value}, library.scope()).outcome
    assert isinstance(canon, Ok)
    assert kernel.evaluate(spec.canon, {"x": canon.value}, library.scope()).outcome == canon
    assert kernel.evaluate(spec.valid, {"x": canon.value}, library.scope()).outcome == Ok(True)
    result = library.run("frac.make", (value,), trace=True)
    assert isinstance(result.outcome, Ok)
    assert result.outcome.value.fields[0] == canon.value
    assert unfold_equivalent(result.trace, (Boundary(), Boundary(depth=0))).ok


def test_negative_pair_canon_regression(library):
    spec = library.get("frac").spec
    canonical = kernel.evaluate(spec.canon, {"x": pair(-5, -5)}, library.scope())
    assert canonical.outcome == Ok(pair(1, 1))
    assert library.run("frac.make", (pair(-5, -5),)).outcome.value.fields[0] == pair(1, 1)


@pytest.mark.parametrize("digits", [(), (1, 1), (0, 1), (2, 0, 3), (2, -1, 3)])
def test_cf_rejects_noncanonical_expansions(library, digits):
    assert library.run("cf.make", (items(*digits),)).outcome == Bottom("invalid")


def test_cf_base_rejects_forged_cards(library):
    for stored in (pair(1, 2), items(), items(1, 1)):
        assert library.run("cf.base", (Card("cf", "val", (stored,)),)).outcome == Bottom("invalid")


def test_cf_ascii_constructor_rejects_noncanonical_lists(library):
    assert run_expression(library, "CF<List<1, 1>>").outcome == Bottom("invalid")
    assert run_expression(library, "CF<List<>>").outcome == Bottom("invalid")


def test_only_object_constructors_mint_refined_cards(library):
    for name in ("frac_pair", "cf_card", "nat_card"):
        assert library.scope().resolve(name) is None
    for name, value in (("frac.make", pair(1, 0)), ("nat.make", -2),
                        ("cf.make", items()), ("cf.make", items(1, 1))):
        assert library.run(name, (value,)).outcome == Bottom("invalid")


def test_laws_are_promoted_and_rewrite_only_on_verified_tuples(library):
    names = ("add_comm", "mul_comm", "mul_distrib", "gcd_comm", "gcd_mul_lcm")
    for name in names:
        assert library.get(name).kind == "law" and library.get(name).status == "promoted"
        assert library.get(name).evidence.scope["values"]
    before = nodes.Call("mul", (nodes.Lit(2), nodes.Lit(-1)))
    after = rewrite(before, library.get("mul_comm"), library)
    assert len(replay_rewrite(before, after, "mul_comm", library, {}).steps) == 1
    outside = nodes.Call("mul", (nodes.Lit(25), nodes.Lit(-1)))
    with pytest.raises(RewriteError, match="scope"):
        replay_rewrite(outside, rewrite(outside, library.get("mul_comm"), library),
                       "mul_comm", library, {})


def test_quotient_template_instances(library):
    assert library.get("Quot").kind == "template"
    assert library.get("Quot").spec.params[0] == ("T", "sort")
    assert library.get("Quot").evidence.scope["family"] == [
        {"T": "pair", "canon": "reduce_ratio"}, {"T": "int", "canon": "mod12"}]
    assert library.run("quot_frac.make", (pair(-5, -5),)).outcome.value.fields[0] == pair(1, 1)
    assert library.run("hour.make", (-13,)).outcome.value.fields[0] == 11
    assert isinstance(library.run("quot_frac.make", (pair(1, 0),)).outcome, Bottom)
    assert library.run("quot_frac.make", (1,)).outcome == Bottom("invalid")
    assert library.run("hour.make", (pair(1, 2),)).outcome == Bottom("invalid")
