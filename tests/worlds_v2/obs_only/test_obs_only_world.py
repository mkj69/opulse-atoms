"""Binding design answers and the closed-world invention boundary."""

import ast
import json
from pathlib import Path

import pytest

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.values import Bottom, Ok
from opulse.atoms.world import DerivedWorld
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.export_util import body_sha256, source_matches
from opulse.worlds_v2.obs_only import reference as ref
from opulse.worlds_v2.obs_only.declgen import build
from opulse.worlds_v2.obs_only.export import EXPORT, answer, build_export, design
from opulse.worlds_v2.obs_only.story import args_for, build_library
from opulse.worlds_v2.obs_only.world import DECL_PATH, decl, new_library


def test_committed_declaration_matches_generator_and_validates():
    stored = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    assert stored == build()
    assert validate(load(DECL_PATH)) == []
    assert stored["observation"]["truth"] == "State"
    assert all(probe["reads"] == "State" for probe in stored["observation"]["probes"])


def test_layer_zero_has_no_story_answers_or_reference_import():
    forbidden = {"credible_cells", "bounds", "label", "possible", "exact", "route_labels",
                 "select_route", "audit_view", "filter_vector", "initial_weights", "advance"}
    names = [operation.name for operation in decl().operations]
    assert len(names) == len(set(names))
    assert not forbidden.intersection(names)
    assert not {row["check"]["query"] for row in design()["tower"]}.intersection(names)
    source = Path(__file__).resolve().parents[3] / "src/opulse/worlds_v2/obs_only/hosts.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.ImportFrom) and
                   (node.module == "reference" or
                    any(alias.name == "reference" for alias in node.names)) or
                   isinstance(node, ast.Import) and any(alias.name.endswith(".reference") for alias in node.names)
                   for node in ast.walk(tree))


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.mark.parametrize("kind,spec", [
    ("object", ObjectSpec("forged", "given")),
    ("operation", OperationSpec("forged", "transform", (), Edge("int"), "forged")),
    ("combinator", CombinatorSpec("forged", (), (), n.Lit(1))),
    ("law", LawSpec("forged", (), n.Lit(True))),
    ("bridge", BridgeSpec("forged", "State", "Trace", n.Lit(1))),
    ("template", TemplateSpec("forged", (), "object", {})),
])
def test_closed_kind_inventions_are_refused(kind, spec):
    assert decl().open_kinds == ("observation",)
    with pytest.raises(PipelineError, match="closed"):
        new_library().write(Definition("forged", kind, "invented", 1, (), spec, n.Lit(1)))


def test_story_promoted_with_reference_bound_evidence(library):
    source = design()
    promoted = tuple(library.get(row["check"]["query"]) for row in source["tower"])
    assert all(item.status == "promoted" and item.kind == "observation" for item in promoted)
    assert [item.layer for item in promoted] == list(range(1, 11))
    assert all("reference" in item.evidence.checks for item in promoted)
    assert DerivedWorld.build(library.world, promoted).open_kinds == ("observation",)


@pytest.mark.parametrize("source_key", ["tower", "showcase", "generated_cases"])
def test_every_design_example_and_showcase(library, source_key):
    for row in design()[source_key]:
        assert answer(library, row["check"]) == row.get("value", row.get("answer")), row
        if source_key == "tower":
            definition = library.get(row["check"]["query"])
            assert isinstance(library.run(definition.name, args_for(definition, row["check"])).outcome, Ok)


def test_sealed_state_and_impossible_history(library):
    config = ref.DEFAULT
    state = ref.State(0, ref.Trace("", "0"), ())
    assert library.run("step", (state, "R", config)).outcome == Bottom("exhausted_draws")
    impossible = ref.Trace("LR", "633")
    sharp = ref.PublicConfig(protocol="sharp")
    assert library.run("status", (impossible, 2, sharp)).outcome == Ok("IMPOSSIBLE")
    assert library.run("belief", (impossible, 2, 0, sharp)).outcome == Bottom("impossible_public_trace")


def test_fixed_combinators_and_public_probes(library):
    assert library.run("chain", (kernel.FnRef("inc"), kernel.FnRef("inc"), 2)).outcome == Ok(4)
    assert library.run("fold", (kernel.FnRef("add"), 0, (1, 2, 3))).outcome == Ok(6)
    assert library.run("repeat", (kernel.FnRef("inc"), 2, 3)).outcome == Ok(5)
    trace = ref.Trace("LR", "010")
    assert library.run("trace_rec", (kernel.FnRef("trace_sum"), 0, trace, 2)).outcome == Ok(1)
    assert library.run("frame", (trace, 1)).outcome == Ok(1)
    assert library.run("issued", (trace, 0)).outcome == Ok("L")
    assert library.run("prior", (ref.DEFAULT, 0)).outcome == Ok(ref.Fraction(1, 64))
    assert library.run("protocol", (ref.DEFAULT, 0, 0)).outcome == Ok(ref.Fraction(63, 100))
    assert library.run("public_config", (trace,)).outcome == Ok(ref.DEFAULT)


def test_observation_cannot_read_sealed_state():
    library = new_library()
    body = n.Var("state")
    definition = Definition("leak", "observation", "invented", 1, (),
                            ObservationSpec("leak", (), body, extra={"inputs": [["state", "State"]]}), body)
    library.write(definition)
    with pytest.raises(PipelineError, match="public sorts"):
        library.check("leak")


def test_public_config_is_task_scoped_and_division_is_exact():
    config = ref.PublicConfig(prior="edge", protocol="sharp")
    library = new_library(config)
    trace = ref.Trace("", "6")
    assert library.run("public_config", (trace,)).outcome == Ok(config)
    assert library.run("config_of", (trace,)).outcome == Ok(config)
    assert library.run("div", (1, 3)).outcome == Ok(ref.Fraction(1, 3))
    assert library.run("div", (1, 0)).outcome == Bottom("Fraction(1,_0)")


def test_published_source_matches_stored_body(library):
    rows = json.loads(EXPORT.read_text(encoding="utf-8"))["story"]
    assert all("ascii" not in row and "decl" not in row for row in rows)
    for row, entry in zip(rows, design()["tower"], strict=True):
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert row["design_decl"] == entry["decl"]
        assert ("ascii" in row) == ("decl" in row)
        if "ascii" in row:
            assert row["ascii"] == row["decl"]
            assert source_matches(row["ascii"], digest)


def test_export_is_reproducible(library):
    stored = json.loads(EXPORT.read_text(encoding="utf-8"))
    assert stored == build_export()
    assert stored["tags"]["open_kinds"] == ["observation"]
    assert stored["world_hash"] == decl().world_hash()
