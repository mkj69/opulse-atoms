"""The operations-only world is executable, closed by kind, and replayable."""

import json
from dataclasses import replace

import pytest

from opulse.atoms import kernel, nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import (
    BridgeSpec,
    CombinatorSpec,
    Definition,
    LawSpec,
    ObjectSpec,
    ObservationSpec,
)
from opulse.atoms.values import Bottom, Ok, encode_outcome
from opulse.tasks_v2.decl import WorldFile, validate
from opulse.worlds_v2.export_util import body_sha256, source_matches
from opulse.worlds_v2.op_only import algorithms, hosts, reference
from opulse.worlds_v2.op_only.decl_source import declaration
from opulse.worlds_v2.op_only.export import (
    DESIGN_PATH,
    EXPORT_PATH,
    build_export,
    display,
    evaluator,
)
from opulse.worlds_v2.op_only.story import build_library, definitions, sample
from opulse.worlds_v2.op_only.story import expected as expected_reference
from opulse.worlds_v2.op_only.world import DECL_PATH, decl, new_library


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def design():
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def exported():
    return json.loads(EXPORT_PATH.read_text(encoding="utf-8"))


def test_committed_declaration_matches_source_and_validates():
    data = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    assert data == declaration()
    assert validate(WorldFile.from_dict(data)) == []


def test_published_sources_match_stored_bodies(library, exported, design):
    assert {row["name"] for row in exported["story"] if "ascii" not in row} == {
        "step", "expand", "reach", "mutual", "condense", "advance", "profile", "critical", "backbone",
    }
    for row, card in zip(exported["story"], design["tower"]):
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert row["design_decl"] == card["decl"]
        if "ascii" in row:
            assert row["decl"] == row["ascii"]
            assert source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row


def test_only_operations_can_be_invented():
    assert decl().open_kinds == ("operation",)
    body = nodes.Lit(0)
    closed = {
        "object": ObjectSpec("Closed", "given"),
        "combinator": CombinatorSpec("closed", ("x",), (), body),
        "observation": ObservationSpec("closed", (), body),
        "law": LawSpec("closed", (), body),
        "bridge": BridgeSpec("closed", "Rel", "Rel", body),
    }
    for kind, spec in closed.items():
        invention = Definition("closed_" + kind, kind, "invented", 1, (), spec, body)
        with pytest.raises(PipelineError, match=f"kind {kind} is closed"):
            new_library().write(invention)


def test_promoted_story_matches_every_design_example(library, design, exported):
    assert len(exported["story"]) == len(design["tower"]) == 9
    invented_by_name = {item.name: item for item in definitions()}
    assert set(invented_by_name) == {card["name"] for card in exported["story"]} | {"critical_edge"}
    run = evaluator(library)
    for spec, card in zip(design["tower"], exported["story"]):
        invented = invented_by_name[card["name"]]
        assert spec["kind"] == card["kind"] == "operation"
        assert card["layer"] == spec["layer"]
        assert card["name"] == invented.name
        assert card["examples"][0]["text"] == spec["example"]
        actual = run(spec["example"])
        assert isinstance(actual.outcome, Ok)
        assert display(actual) == spec["value"] == reference.formatted(reference.evaluate(spec["example"]))
        assert card["examples"][0]["outcome"] == encode_outcome(actual.outcome)
        assert card["examples"][0]["steps"] == actual.steps
        record = library.get(invented.name)
        assert record.status == card["status"] == "promoted"
        assert record.evidence.method == "bounded"
        assert record.evidence.world_hash == library.world.world_hash()
        assert record.contract is not None

    helper = library.get("critical_edge")
    assert helper.status == "promoted"
    assert helper.evidence.method == "bounded"
    assert helper.evidence.world_hash == library.world.world_hash()
    assert helper.contract is not None
    arguments = sample("critical_edge")
    assert library.run("critical_edge", arguments).outcome == Ok(expected_reference("critical_edge", *arguments))


def test_showcase_answers_and_certificates(library, design, exported):
    run = evaluator(library, trace=False)
    for task, saved in zip(design["showcase"], exported["showcase"]):
        assert saved["answer"] == task["answer"]
        for expression, expected in task["check"]:
            actual = run(expression)
            assert isinstance(actual.outcome, Ok)
            assert display(actual) == expected == reference.formatted(reference.evaluate(expression))
    reference.verify_showcase(design)


def test_declaration_and_export_are_reproducible(library, exported):
    assert exported["open_kinds"] == exported["tags"]["open_kinds"] == ["operation"]
    assert exported["tags"]["agents"] == 1
    assert type(exported["tags"]["agents"]) is int
    assert exported["world_hash"] == library.world.world_hash()
    assert exported["decl"] == decl().to_dict()
    assert build_export() == exported


def test_export_traces_include_plugged_invocations(exported):
    def count_named(frame, name):
        return (frame["name"] == name) + sum(count_named(child, name)
                                               for child in frame["children"])

    by_name = {item["name"]: item["examples"][0] for item in exported["story"]}
    reach = by_name["reach"]
    profile = by_name["profile"]
    assert reach["steps"] > by_name["expand"]["steps"]
    assert profile["steps"] > by_name["advance"]["steps"]
    assert count_named(reach["trace"], "expand") >= 2
    assert count_named(profile["trace"], "advance") >= 1


def test_closed_kind_cannot_be_reopened_after_promotion(library):
    assert library.get("backbone").status == "promoted"
    attempt = replace(library.get("backbone"), kind="object", origin="invented",
                      spec=ObjectSpec("backbone", "given"), status="written",
                      evidence=None, contract=None)
    with pytest.raises(PipelineError, match="kind object is closed"):
        library.write(attempt)


def test_fixed_combinators_use_their_plugs(library):
    graph = hosts.pack(reference.Rel(3, (1 << 1, 1 << 2, 0)))
    seed = hosts.identity(graph)
    scope = library.scope()
    scope.defns["keep_relation"] = kernel.Defn("keep_relation", ("current", "base"),
                                               nodes.Var("current"))
    ordinary = kernel.call("fix2", (kernel.FnRef("expand"), seed, graph), scope)
    alternate = kernel.call("fix2", (kernel.FnRef("keep_relation"), seed, graph), scope)
    assert ordinary.outcome == Ok(hosts.pack(reference.reach(reference.Rel(3, (2, 4, 0)))))
    assert alternate.outcome == Ok(seed)
    assert ordinary.steps > alternate.steps

    scope.defns["keep_profile"] = kernel.Defn("keep_profile", ("profile", "source", "target"),
                                              nodes.Var("profile"))
    ordinary = kernel.call("dag_fold", (kernel.FnRef("advance"), graph), scope)
    alternate = kernel.call("dag_fold", (kernel.FnRef("keep_profile"), graph), scope)
    assert ordinary.outcome != alternate.outcome
    assert hosts.profile_value(alternate.outcome.value).depth == [0, 0, 0]


def test_fixed_combinators_meter_each_round_and_edge(library):
    scope = library.scope()
    chain = hosts.pack(reference.Rel(4, (2, 4, 8, 0)))
    short = hosts.pack(reference.Rel(4, (2, 0, 0, 0)))
    long_run = kernel.call("fix2", (kernel.FnRef("expand"), hosts.identity(chain), chain),
                           scope, trace=True)
    short_run = kernel.call("fix2", (kernel.FnRef("expand"), hosts.identity(short), short),
                            scope, trace=True)
    def calls(run, operation):
        return sum(frame.name == operation for frame in run.trace.children[0].children[0].children)

    assert calls(long_run, "expand") > calls(short_run, "expand")
    assert long_run.steps > short_run.steps
    long_fold = kernel.call("dag_fold", (kernel.FnRef("advance"), chain), scope, trace=True)
    short_fold = kernel.call("dag_fold", (kernel.FnRef("advance"), short), scope, trace=True)
    assert calls(long_fold, "advance") == 3
    assert calls(short_fold, "advance") == 1
    assert long_fold.steps > short_fold.steps

    shrinking = kernel.Defn("shrink", ("current", "base"), nodes.Var("base"))
    scope.defns["shrink"] = shrinking
    assert kernel.call("fix2", (kernel.FnRef("shrink"), hosts.identity(chain), chain),
                       scope).outcome == Bottom("non_monotone")


def test_no_answer_hosts_or_update_operation():
    names = {operation.name for operation in decl().operations}
    assert "update" not in names
    assert not names.intersection({"advance", "reach", "profile", "critical", "backbone"})
    assert "set_profile" in names
    assert not any(hasattr(algorithms, name) for name in
                   ("advance", "reach", "profile", "critical", "backbone"))


def test_dag_fold_refuses_cycles(library):
    cycle = hosts.pack(reference.Rel(2, (2, 1)))
    assert kernel.call("dag_fold", (kernel.FnRef("advance"), cycle),
                       library.scope()).outcome == Bottom("cycle")


@pytest.mark.parametrize("size", (3, 17, 64, 129))
def test_generic_bitset_compose_matches_reference(size):
    left = tuple(sum(1 << target for target in range(size)
                     if (source * 13 + target * 17) % 7 < 3) for source in range(size))
    right = tuple(sum(1 << target for target in range(size)
                      if (source * 19 + target * 11) % 13 < 2) for source in range(size))
    assert algorithms.compose(algorithms.Rel(size, left), algorithms.Rel(size, right)).rows == (
        reference.compose(reference.Rel(size, left), reference.Rel(size, right)).rows)
