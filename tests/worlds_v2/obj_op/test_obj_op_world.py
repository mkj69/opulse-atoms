"""Design-oracle, published-card, and closed-kind regressions."""

import importlib.util
import json
from pathlib import Path

import pytest

from opulse.atoms import KINDS, kernel, nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    LawSpec,
    ObservationSpec,
)
from opulse.atoms.values import Bottom, Card, Ok, Unknown
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.export_util import body_sha256, source_matches
from opulse.worlds_v2.index import build_index
from opulse.worlds_v2.obj_op import hosts
from opulse.worlds_v2.obj_op.export import DESIGN_PATH, EXPORT_PATH, build_export
from opulse.worlds_v2.obj_op.expressions import calls_in, display, run
from opulse.worlds_v2.obj_op.story import build_library
from opulse.worlds_v2.obj_op.world import (
    DECL_PATH,
    decl,
    fold_spec,
    new_library,
    until_spec,
)


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def reference():
    path = Path(__file__).with_name("reference.py")
    spec = importlib.util.spec_from_file_location("obj_op_design_reference", path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_locked_world_and_closed_kinds():
    source = WorldDecl.from_dict(json.loads(DECL_PATH.read_text(encoding="utf-8")))
    assert source == decl()
    assert validate(load(DECL_PATH)) == []
    assert source.world_hash() == source.lock["world_hash"]
    assert source.open_kinds == ("object", "operation")
    assert source.combinators["library"][0] == fold_spec().to_dict()
    assert source.combinators["library"][2] == until_spec().to_dict()
    specs = {
        "combinator": CombinatorSpec("forbidden", ("x",), (), nodes.Var("x")),
        "observation": ObservationSpec("forbidden", ("public",), nodes.Var("s")),
        "law": LawSpec("forbidden", (), nodes.Lit(True)),
        "bridge": BridgeSpec("forbidden", "Int", "Int", nodes.Var("x")),
    }
    assert set(specs) == set(KINDS) - set(source.open_kinds)
    for kind, spec in specs.items():
        library = new_library()
        with pytest.raises(PipelineError, match=f"kind {kind} is closed"):
            library.write(Definition("forbidden", kind, "invented", 1, (), spec, nodes.Var("x")))
        assert "forbidden" not in library.definitions


def test_fixed_combinators_and_observations():
    library = new_library()
    assert library.run("fold", (kernel.FnRef("sub"), 0, (1, 2, 3))).outcome == Ok(-6)
    assert library.run("map", (kernel.FnRef("lt"), ())).outcome == Ok(())
    assert library.run("until", (kernel.FnRef("is_empty"), kernel.FnRef("tail"), (1, 2), 1)).outcome == Unknown("resource")
    assert library.run("until", (kernel.FnRef("is_empty"), kernel.FnRef("tail"), (1, 2), 2)).outcome == Ok(())
    assert library.run("value", (3,)).outcome == Ok("3")
    assert library.run("status", (Bottom("period"),)).outcome == Ok("Bottom(period)")
    assert library.run("range", (hosts.band(3, 8),)).outcome == Ok((3, 8))


def test_object_rules_are_written_above_layer_zero(library):
    source = decl()
    forbidden = {f"{name}_{suffix}" for name in ("cycle", "plan", "window", "blackout", "band")
                 for suffix in ("valid", "canon", "normal")}
    names = {operation.name for operation in source.operations}
    assert not names & forbidden
    assert all(not hasattr(hosts, name) for name in forbidden)
    primitives = {"lt", "le", "eq", "mod", "add", "sub", "is_empty", "head", "tail",
                  "list_length", "cons", "record_field", "is_defined", "band", "band_lo",
                  "band_hi", "cycle_raw", "plan_raw", "window_raw", "blackout_raw"}
    assert primitives <= names
    invented = {"Cycle": 1, "join": 2, "Plan": 3, "compile": 4,
                "Window": 5, "first_hit": 6, "Blackout": 7, "clear_hit": 8}
    for name in ("Cycle", "Plan", "Window", "Blackout"):
        definition = library.get(name)
        assert definition.spec.valid is not None and definition.spec.canon is not None
        earlier = {previous for previous, layer in invented.items() if layer < invented[name]}
        accessors = {f"{previous}.{field}" for previous, layer in invented.items()
                     if previous in ("Cycle", "Plan", "Window") and layer < invented[name]
                     for field in ("residue", "period", "cycles", "plan", "lo", "hi", "compiled", "make")}
        for body in (definition.spec.valid, definition.spec.canon):
            assert nodes.references(body) <= primitives | earlier | accessors


def test_fixed_ascii_sigils(library):
    assert display(run(library, "@fold[sub](0,List<1,2,3>)").outcome) == "-6"
    assert display(run(library, "@fold[join](Cycle<0,6>,List<Cycle<0,9>,Cycle<0,10>>)").outcome) == "Cycle<0, 90>"
    assert run(library, "@map[is_empty](List<List<>,List<1>>)").outcome == Ok((True, False))
    assert display(run(library, "?value{Cycle<1,7>}").outcome) == "Cycle<1, 7>"
    assert run(library, "?status{Cycle<1,0>}").outcome == Ok("Bottom(period)")
    assert run(library, "?status{@until[is_empty,tail](List<1,2>,1)}").outcome == Ok("Unknown(resource)")
    assert run(library, "?range{Band<3,8>}").outcome == Ok((3, 8))


def test_promoted_pipeline_and_tower_examples(library, reference):
    reference.verify()
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    for layer, card in enumerate(design["tower"], 1):
        definition = library.get(("Cycle", "join", "Plan", "compile", "Window", "first_hit",
                                  "Blackout", "clear_hit")[layer - 1])
        assert definition.status == "promoted" and definition.layer == layer
        assert definition.evidence.world_hash == library.world.world_hash()
        assert definition.evidence.scope["checked"]["size"] == 1
        result = run(library, card["example"])
        assert display(result.outcome) == card["value"] == reference.evaluate(card["example"])
        assert result.steps > 0
    assert reference.compute_cases() == {**{f"L{card['layer']}": card["value"] for card in design["tower"]},
                                          **{card["angle"]: card["answer"] for card in design["showcase"]}}


def test_all_showcase_answers_and_inverse_certificate(library, reference):
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    compute, inverse, decide = design["showcase"]
    assert display(run(library, next(calls_in(compute["prompt"]))).outcome) == compute["answer"]
    candidates = (1748143545, 1754796345, 1761449145)
    pairs = reference.inverse_solutions()
    assert "; ".join(f"({left}, {right})" for left, right in pairs) == inverse["answer"]
    for pair, target in zip(pairs, candidates):
        expression = next(calls_in(inverse["prompt"]))
        expression = expression.replace("r9", str(pair[0])).replace("r13", str(pair[1]))
        assert display(run(library, expression).outcome) == str(target)
    witnesses = [display(run(library, expression).outcome) for expression in calls_in(decide["prompt"])]
    assert witnesses == ["4855001145", "4076623545"]
    assert str(witnesses[0] == witnesses[1]).lower() == decide["answer"]
    assert display(run(library, "join(Cycle<271545,604800>,Cycle<1481146,1814400>)").outcome) == "Bottom(incompatible)"


@pytest.mark.parametrize(("source", "expected"), [
    ("Cycle<0,0>", "Bottom(period)"),
    ("join(Cycle<0,6>,Cycle<1,9>)", "Bottom(incompatible)"),
    ("first_hit(Window<Plan<Cycle<0,10>>,1,9>)", "Bottom(no_hit)"),
    ("clear_hit(Blackout<Window<Plan<Cycle<0,10>>,0,20>,Band<0,20>>)", "Bottom(no_hit)"),
    ("Window<Plan<Cycle<1,2>,Cycle<0,2>>,0,10>", "Bottom(incompatible)"),
    ("Band<2,1>", "Bottom(band_order)"),
])
def test_failure_semantics(library, source, expected):
    result = run(library, source)
    assert isinstance(result.outcome, Bottom) and display(result.outcome) == expected


def test_bounded_carriers_and_window_invariant(library):
    assert display(run(library, f"Cycle<{10**120},7>").outcome) == "Bottom(range)"
    assert display(run(library, f"add({10**120 - 1},1)").outcome) == "Bottom(range)"
    assert display(run(library, "Plan<" + ",".join("Cycle<0,7>" for _ in range(33)) + ">").outcome) == "Bottom(plan_size)"
    cycle = run(library, "Cycle<0,7>").outcome.value
    plan = run(library, "Plan<Cycle<0,7>>").outcome.value
    incorrect = run(library, "Cycle<1,7>").outcome.value
    forged = hosts.window_raw(plan, 0, 20, incorrect)
    assert library.run("Window.make", (forged,)).outcome == Bottom("invalid")
    bad_window = Card("Window", "val", (forged,))
    assert library.run("Blackout.make", (hosts.blackout_raw(bad_window, ()),)).outcome == Bottom("invalid")
    malformed = Card("Plan", "val", (Card("PlanRaw", "val", ((Card("Cycle", "val", ()),),)),))
    assert library.run("Window.make", (hosts.window_raw(malformed, 0, 20, cycle),)).outcome == Bottom("invalid")
    assert library.run("join", (cycle, incorrect)).outcome == Bottom("incompatible")
    maximum = 10**120 - 1
    assert display(run(library, f"first_hit(Window<Plan<Cycle<0,10>>,{maximum - 2},{maximum}>)").outcome) == "Bottom(no_hit)"
    assert display(run(library, f"first_hit(Window<Plan<Cycle<1,10>>,-{maximum},{maximum}>)").outcome) == str(-maximum)
    assert display(run(library, f"clear_hit(Blackout<Window<Plan<Cycle<0,1>>,{maximum},{maximum}>,Band<{maximum},{maximum}>>)").outcome) == "Bottom(no_hit)"


def test_object_rules_reject_forged_inputs_and_normalize_bands(library):
    cycle = run(library, "Cycle<0,7>").outcome.value
    plan = run(library, "Plan<Cycle<0,7>>").outcome.value
    window = run(library, "Window<Plan<Cycle<0,7>>,0,20>").outcome.value
    assert library.run("Cycle.make", (hosts.cycle_raw(0, 0),)).outcome == Bottom("invalid")
    forged_cycle = Card("Cycle", "val", (hosts.cycle_raw(7, 7),))
    assert library.run("Plan.make", (hosts.plan_raw((forged_cycle,)),)).outcome == Bottom("invalid")
    assert library.run("Window.make", (hosts.window_raw(plan, 20, 0, cycle),)).outcome == Bottom("invalid")
    assert run(library, "Window<Plan<Cycle<0,7>>,20,0>").outcome == Bottom("window_order")
    invalid_band = Card("Band", "val", (3, 2))
    assert library.run("Blackout.make", (hosts.blackout_raw(window, (invalid_band,)),)).outcome == Bottom("invalid")
    assert library.run("Blackout.make", (hosts.blackout_raw(window, (3,)),)).outcome == Bottom("invalid")
    result = library.run("Blackout.make", (hosts.blackout_raw(window, (
        hosts.band(10, 12), hosts.band(2, 4), hosts.band(5, 9), hosts.band(-5, -1))),)).outcome
    assert result == Ok(Card("Blackout", "val", (hosts.blackout_raw(window, (hosts.band(2, 12),)),)))


def test_sealed_public_accessors(library):
    cycle = run(library, "Cycle<-1,7>").outcome.value
    plan = run(library, "Plan<Cycle<-1,7>>").outcome.value
    window = run(library, "Window<Plan<Cycle<-1,7>>,0,20>").outcome.value
    blackout = run(library, "Blackout<Window<Plan<Cycle<-1,7>>,0,20>,Band<2,3>>").outcome.value
    assert library.run("Cycle.residue", (cycle,)).outcome == Ok(6)
    assert library.run("Cycle.period", (cycle,)).outcome == Ok(7)
    assert library.run("Plan.cycles", (plan,)).outcome == Ok((cycle,))
    assert library.run("Window.plan", (window,)).outcome == Ok(plan)
    assert library.run("Window.lo", (window,)).outcome == Ok(0)
    assert library.run("Window.hi", (window,)).outcome == Ok(20)
    assert library.run("Window.compiled", (window,)).outcome == Ok(cycle)
    assert library.run("Blackout.window", (blackout,)).outcome == Ok(window)
    assert library.run("Blackout.bands", (blackout,)).outcome == Ok((hosts.band(2, 3),))


@pytest.mark.parametrize(("left", "right"), [
    ((-1, 6), (5, 9)), ((0, 6), (1, 9)), ((29, 14), (1, 21)),
    ((-99, 7), (32, 11)), ((17, 8), (-1, 12)), ((0, 1), (0, 1)),
])
def test_generalized_crt_against_independent_reference(library, reference, left, right):
    source = f"join(Cycle<{left[0]},{left[1]}>,Cycle<{right[0]},{right[1]}>)"
    assert display(run(library, source).outcome) == reference.evaluate(source)


def test_export_is_reproducible_and_tagged(library):
    exported = build_export(library)
    published = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert exported == published
    assert published["tags"]["open_kinds"] == published["open_kinds"] == ["object", "operation"]
    assert published["tags"]["agents"] == 1
    assert type(published["tags"]["agents"]) is int
    assert published["tower_source"] == "depth" and published["wave"] == 4
    assert len(published["story"]) == 8 and len(published["showcase"]) == 3
    assert all(row["valid"] is not None and row["canon"] is not None
               for row in published["story"] if row["kind"] == "object")
    assert all(row["status"] == "promoted" and isinstance(row["examples"][0]["steps"], int)
               for row in published["story"])
    published_index = json.loads((EXPORT_PATH.parent / "index.json").read_text(encoding="utf-8"))
    expected_index = build_index()
    assert published_index == expected_index
    obj_entry = next(item for item in expected_index["worlds"] if item["world"] == "obj_op")
    assert obj_entry["world_hash"] == library.world.world_hash()


def test_published_sources_match_stored_bodies(library):
    published = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert {row["name"] for row in published["story"] if "ascii" not in row} == {
        "Cycle", "join", "Plan", "compile", "Window", "first_hit", "Blackout", "clear_hit",
    }
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    for row, card in zip(published["story"], design["tower"]):
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert row["design_decl"] == card["decl"]
        if "ascii" in row:
            assert row["decl"] == row["ascii"]
            assert source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row


def test_public_export_and_declaration_use_ascii_outside_zh_fields():
    def non_ascii(value, key=""):
        if isinstance(value, dict):
            # Notation v3: the generated display block is not machine notation.
            return [text for name, item in value.items() if name != "notation3"
                    for text in non_ascii(item, name)]
        if isinstance(value, list):
            return [text for item in value for text in non_ascii(item, key)]
        if isinstance(value, str) and not key.endswith("_zh") and not value.isascii():
            return [value]
        return []

    assert not non_ascii(json.loads(EXPORT_PATH.read_text(encoding="utf-8")))
    assert not non_ascii(json.loads(DECL_PATH.read_text(encoding="utf-8")))
