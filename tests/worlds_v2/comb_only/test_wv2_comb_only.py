"""Combinators-only scheduling: locked capability and exact design replay."""

import json
import re

import pytest

from opulse.atoms import kernel, nodes, notation
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import (
    BridgeSpec,
    Definition,
    Edge,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
    OperationSpec,
    TemplateSpec,
)
from opulse.atoms.values import Bottom, Ok, Unknown
from opulse.worlds_v2.comb_only import hosts, reference
from opulse.worlds_v2.comb_only.export import (
    DESIGN_PATH,
    EXPORT_PATH,
    NAMES,
    examples,
    visible,
)
from opulse.worlds_v2.comb_only.story import build_library
from opulse.worlds_v2.comb_only.world import decl, new_library
from opulse.worlds_v2.export_util import body_sha256, source_matches


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def design():
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def test_comb_only_tags_use_controlled_vocabulary():
    tags = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["tags"]
    assert set(tags) == {"domain", "modalities", "open_kinds", "star_kind", "reasoning",
                         "state", "outcomes", "visibility", "agents", "scale", "difficulty", "uses"}
    assert tags["domain"] in {"math", "logic", "language", "perception", "agent", "probability",
                              "music", "program", "social", "resource", "time"}
    assert isinstance(tags["modalities"], list) and tags["modalities"]
    assert set(tags["modalities"]) <= {"text", "image", "audio"}
    assert isinstance(tags["open_kinds"], list) and tags["open_kinds"]
    assert set(tags["open_kinds"]) <= {"object", "operation", "combinator", "observation"}
    assert tags["star_kind"] in tags["open_kinds"]
    assert isinstance(tags["reasoning"], list) and tags["reasoning"]
    assert set(tags["reasoning"]) <= {"compute", "search", "planning", "counting", "probability",
                                      "equivalence", "parsing", "geometry", "inference", "strategy"}
    assert tags["state"] in {"stateless", "stateful"}
    assert tags["outcomes"] in {"deterministic", "multi-valued", "probabilistic"}
    assert tags["visibility"] in {"full", "partial"}
    assert type(tags["agents"]) is int and tags["agents"] >= 1
    assert isinstance(tags["scale"], str)
    assert re.fullmatch(r"[1-9]\d* vertices, [1-9]\d* invented combinators", tags["scale"])
    assert tags["scale"] == f"120 vertices, {len(NAMES)} invented combinators"
    assert isinstance(tags["difficulty"], str) and tags["difficulty"].strip()
    assert isinstance(tags["uses"], list) and tags["uses"]
    assert set(tags["uses"]) <= {"rl-training", "evaluation", "interpretability", "teaching", "experiment"}


def test_closed_kinds_refused_at_write():
    library = new_library()
    assert library.world.open_kinds == ("combinator",)
    body = nodes.Lit(0)
    specs = {
        "object": ObjectSpec("NewObject", "given"),
        "operation": OperationSpec("new_operation", "transform", (Edge("int"),), Edge("int"), "test"),
        "observation": ObservationSpec("new_observation", ("State",), body),
        "law": LawSpec("new_law", (), body),
        "bridge": BridgeSpec("new_bridge", "State", "State", body),
    }
    for kind, spec in specs.items():
        with pytest.raises(PipelineError, match=f"kind {kind} is closed"):
            library.write(Definition(spec.name, kind, "invented", 1, (), spec, body))
    template = TemplateSpec("new_template", (), "object", {})
    with pytest.raises(PipelineError, match="kind template is closed"):
        library.write(Definition("new_template", "template", "invented", 1, (), template, body))


def test_all_eight_examples_from_core(library, design):
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert [row["name"] for row in exported["story"]] == list(NAMES)
    assert exported["open_kinds"] == design["open_kinds"]
    assert exported["decl"]["open_kinds"] == list(decl().open_kinds)
    assert exported["world_hash"] == decl().world_hash()
    for name, definition, entry, arguments, row in zip(
            NAMES, (library.get(name) for name in NAMES), design["tower"], examples(), exported["story"], strict=True):
        assert definition.status == "promoted" and definition.kind == "combinator"
        assert definition.evidence.world_hash == library.world.world_hash()
        assert row["examples"][0]["text"] == entry["example"]
        assert row["examples"][0]["inputs"] == [hosts.encode_value(value) for value in arguments]
        run = library.run(name, arguments, fuel=10_000_000)
        assert isinstance(run.outcome, Ok), name
        assert visible(name, run.outcome.value) == entry["value"]
        # Review round 25 G2: the shown text, outcome and steps are one evaluation of the shown expression.
        shown = kernel.evaluate(notation.parse_expr(entry["example"], library), scope=library.scope(),
                                limits=kernel.Limits(fuel=10_000_000))
        assert row["examples"][0]["outcome"] == {"ok": hosts.encode_value(shown.outcome.value)}
        assert row["examples"][0]["steps"] == shown.steps >= run.steps
        if name != "opt":
            assert shown.outcome == run.outcome
        else:
            expression = notation.parse_expr(entry["example"], library)
            assert isinstance(expression, nodes.Call) and expression.fn == "score"
            assert shown.outcome == Ok(run.outcome.value.earned)
            assert row["examples"][0]["trace"]["steps"] == shown.steps


def test_published_source_matches_stored_body(library, design):
    rows = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    assert {row["name"] for row in rows if "ascii" not in row} == {"until", "opt"}
    for row, entry in zip(rows, design["tower"], strict=True):
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert row["design_decl"] == entry["decl"]
        assert ("ascii" in row) == ("decl" in row)
        if "ascii" in row:
            assert row["ascii"] == row["decl"]
            assert source_matches(row["ascii"], digest)


def test_showcase_exact_answers(library, design):
    plan = hosts.Plan(23, 10, 12)
    solution = library.run("opt", (kernel.FnRef("priority"), hosts.start(plan)), fuel=10_000_000).outcome
    assert isinstance(solution, Ok)
    assert library.run("legal", (solution.value,)).outcome == Ok(True)
    certificate = {"score": solution.value.earned, "chosen": list(hosts.vertices(solution.value.chosen))}
    assert certificate == design["showcase"][0]["answer"]
    assert reference.independent_oracle(plan) == (certificate["score"], tuple(certificate["chosen"]))

    target = design["showcase"][1]["target"]
    inverse = [candidate for candidate in range(41)
               if reference.independent_oracle(hosts.Plan(23, 10, 12, 0, candidate))[0] == target]
    assert inverse == design["showcase"][1]["answer"]
    inverted = library.run("opt", (kernel.FnRef("priority"), hosts.start(hosts.Plan(23, 10, 12, 0, 28))),
                           fuel=10_000_000).outcome
    assert isinstance(inverted, Ok) and inverted.value.earned == target

    bridge = hosts.Plan(23, 10, 12, bridges=((0, 13), (26, 39), (49, 62)))
    bridged = library.run("opt", (kernel.FnRef("priority"), hosts.start(bridge)), fuel=10_000_000).outcome
    assert isinstance(bridged, Ok)
    assert library.run("legal", (bridged.value,)).outcome == Ok(True)
    assert reference.independent_oracle(bridge) == (bridged.value.earned, hosts.vertices(bridged.value.chosen))
    assert bridged.value.earned == 753
    assert (bridged.value.earned >= design["showcase"][2]["target"]) == design["showcase"][2]["answer"]
    decision_text = design["showcase"][2]["prompt"].split("decide ", 1)[1].rstrip(".")
    decision = notation.parse_expr(decision_text, library)
    assert isinstance(decision, nodes.Call) and decision.fn == "le"
    exported = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert [row["answer"] for row in exported["showcase"]] == [row["answer"] for row in design["showcase"]]
    assert all(row["answer_checked"] for row in exported["showcase"])


def test_frontier_and_failure_semantics(library):
    plan = hosts.Plan(23, 10, 12)
    closed = library.run("closure", (kernel.FnRef("adjacent"), plan, 1))
    assert closed.outcome == Ok((1 << 12) - 1)
    assert library.run("closure", (kernel.FnRef("adjacent"), plan, 1 << 120)).outcome == Bottom("outside_universe")
    merged = hosts.Plan(23, 10, 12, bridges=((0, 13),))
    groups = library.run("components", (kernel.FnRef("adjacent"), merged)).outcome
    assert isinstance(groups, Ok)
    assert [group.bit_count() for group in groups.value] == [24, *([12] * 8)]
    assert library.run("take", (hosts.start(plan), 120)).outcome == Bottom("unavailable")
    invalid_plan = notation.parse_expr("start(Plan<23,13,12>)", library)
    assert kernel.evaluate(invalid_plan, scope=library.scope()).outcome == Bottom("range")
    repeated_member = notation.parse_expr("@until[drop_lowest,popcount](Set<0,0>)", library)
    assert kernel.evaluate(repeated_member, scope=library.scope()).outcome == Ok(0)
    assert library.run("branch", (kernel.FnRef("priority"), hosts.State(plan, 0))).outcome == Bottom("empty_frontier")
    assert isinstance(library.run("opt", (kernel.FnRef("priority"), hosts.start(plan)), fuel=3).outcome, Unknown)
    assert library.run("case", (kernel.FnRef("identity"), kernel.FnRef("drop_lowest"),
                                kernel.FnRef("nonzero"), 15)).outcome == Ok(15)
    assert library.run("jump", (kernel.FnRef("drop_lowest"), kernel.FnRef("nonzero"), 15, 4)).outcome == Ok(0)
    assert library.run("jump", (kernel.FnRef("drop_lowest"), kernel.FnRef("nonzero"), 15, 3)).outcome == Unknown("resource")
    assert library.run("until", (kernel.FnRef("singleton"), kernel.FnRef("popcount"), 1)).outcome == Bottom(
        "non_decreasing_measure")
