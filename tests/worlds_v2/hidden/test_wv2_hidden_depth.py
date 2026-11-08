"""Independent depth oracle, finite evidence, kernel boundaries, and sealed capabilities."""

import importlib.util
import json
import os
import re
import sys
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.hidden import hosts
from opulse.worlds_v2.hidden.adapter import HiddenLibrary
from opulse.worlds_v2.hidden.export import (
    DEPTH_PATH,
    EXPORT_PATH,
    JUDGE_PATH,
    NAMES,
    TEXT,
    ascii_declaration,
    build_export,
    expression,
    run_expression,
)
from opulse.worlds_v2.hidden.story import (
    belief,
    build_library,
    definitions,
    lamps,
    modes,
)
from opulse.worlds_v2.hidden.world import atoms, decl


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def oracle():
    path = DEPTH_PATH.with_suffix(".py")
    specification = importlib.util.spec_from_file_location("hidden_depth_reference_tests", path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def rendered(value, reference):
    if isinstance(value, values.Card):
        if value.sort == "Rational":
            return str(hosts.fraction(value))
        if value.sort == "Belief":
            return "Belief<" + ",".join(rendered(item, reference) for item in value.fields[0].fields) + ">"
        if value.sort == "Policy":
            def node(item):
                return ("Leaf<" + item.fields[0] + ">" if item.tag == "Leaf" else
                        "Ask<" + item.fields[0] + "," + node(item.fields[1]) + "," + node(item.fields[2]) + ">")
            return "Policy<" + node(value.fields[0]) + ">"
        if value.sort in ("Lamps", "Modes"):
            return "List<" + ",".join(value.fields) + ">"
    return value


def test_story_ascii_declarations_and_exact_parseable_examples():
    for definition in definitions():
        if definition.name not in NAMES:
            continue
        source = ascii_declaration(definition)
        if source is not None:
            assert notation.parse_definition(source).layer == definition.layer
            assert export_util.source_matches(source, export_util.body_sha256(definition.body))
    for name in ("lamps", "update"):
        assert notation.parse_expr(TEXT[name]) == expression(name)


def test_published_ascii_matches_stored_body(library):
    rows = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    # Round 6: an observation printed with subject {s} whose body reads another variable is not published.
    assert [row["name"] for row in rows if "ascii" not in row] == [
        "lamps", "Belief", "update", "scan", "confidence", "Policy", "value", "optimize", "first", "regret"]
    for row in rows:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row


def test_first_three_cards_build_fresh():
    library = build_library(limit=3)
    committed = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    for name, row in zip(NAMES[:3], committed["story"][:3]):
        assert values.encode_outcome(run_expression(library, expression(name)).outcome) == row["examples"][0]["outcome"]


def test_reference_all_ten_examples_and_kernel_traces(library, oracle):
    expected, showcase, _, _, _ = oracle._checks()
    design = json.loads(DEPTH_PATH.read_text(encoding="utf-8"))
    assert len(NAMES) == len(expected) == 10
    for name, answer, card in zip(NAMES, expected, design["tower"]):
        run = kernel.evaluate(expression(name), scope=library.scope(), trace=True)
        assert isinstance(run.outcome, values.Ok), name
        assert rendered(run.outcome.value, oracle) == answer, name
        assert run.steps > 0
        assert unfold_equivalent(run.trace, [Boundary(), Boundary(depth=0)]).ok
        assert library.get(name).kind == card["kind"]
    assert showcase == [item["answer"] for item in design["showcase"]]


def test_failure_from_scan_and_sealed_non_interference(library):
    initial = belief(Fraction(1, 2), Fraction(1, 2))
    assert library.run("scan", (kernel.FnRef("update"), initial, modes("A"), lamps())).outcome == values.Bottom("unpaired")
    prior = belief(Fraction(0), Fraction(1))
    assert library.run("update", (prior, "A", "blue")).outcome == values.Ok(prior)
    assert library.run("update", (belief(Fraction(1), Fraction(0)), "A", "blue")).outcome == values.Bottom("impossible")
    assert library.run("Belief.make", (hosts.pair(hosts.rational(2), hosts.rational(0)),)).outcome == values.Bottom("invalid")
    assert library.run("value", (library.run("Policy.make", (hosts.node_leaf("R"),)).outcome.value,
                                  initial, 13)).outcome == values.Bottom("budget")
    assert library.run("optimize", (kernel.FnRef("value"), initial, 13)).outcome == values.Bottom("budget")
    assert len(hosts.signal(hosts.state("R"), "A").fields) == 1
    left = hosts.state("R", (("A", "red"), ("B", "blue")))
    right = hosts.state("B", (("A", "red"), ("B", "blue")))
    assert library.learner_view(left) == library.learner_view(right)
    assert library.judge_view(left) != library.judge_view(right)
    assert hosts.judge(left, "R") != hosts.judge(right, "R")
    assert library.run("lamps", (library.learner_view(left),), trace=True) == library.run(
        "lamps", (library.learner_view(right),), trace=True)
    with pytest.raises(KeyError):
        library.run("signal", (left, "A"))
    with pytest.raises(KeyError):
        library.run("judge", (left, "R"))
    judge = HiddenLibrary(decl(), atoms(), agent="judge")
    assert judge.run("judge", (left, "R")).outcome == values.Ok(values.TRUE)


def test_given_bind_has_public_unfold_and_equal_weight_merging():
    assert hosts.eq(values.Card("Rational", "fraction", (2, 4)), hosts.rational(Fraction(1, 2))) == values.TRUE
    state = hosts.state("R")
    distribution = hosts.signal(state, "B")
    library = HiddenLibrary(decl(), atoms(), agent="judge")
    for mapper in ("singleton", "duplicate"):
        run = library.run("bind", (kernel.FnRef(mapper), distribution), trace=True)
        assert run.outcome == values.Ok(distribution)
        assert unfold_equivalent(run.trace, [Boundary(), Boundary(depth=0)]).ok
    assert all(atom.name != "bind" for atom in atoms())


@given(st.lists(st.tuples(st.sampled_from(("A", "B")), st.sampled_from(("red", "blue"))),
                min_size=0, max_size=3))
@settings(max_examples=12, deadline=None)
def test_public_histories_are_boundary_invariant(library, history):
    red = hosts.state("R", history)
    blue = hosts.state("B", history)
    assert library.learner_view(red) == library.learner_view(blue)
    run = library.run("lamps", (library.learner_view(red),), trace=True)
    assert run == library.run("lamps", (library.learner_view(blue),), trace=True)
    assert unfold_equivalent(run.trace, [Boundary(), Boundary(depth=0)]).ok


def test_observation_evidence_checks_paired_views_and_unfolding(library, monkeypatch):
    from opulse.worlds_v2.hidden import adapter

    for name in ("lamps", "confidence", "first"):
        evidence = library.get(name).evidence
        assert {"non_interference", "unfold_equivalence"} <= set(evidence.checks)
        assert "paired R/B" in evidence.scope["domain"]
    original = adapter.kernel.inline

    def wrong_unfold(*args, **kwargs):
        return adapter.nodes.Lit("wrong")

    monkeypatch.setattr(adapter.kernel, "inline", wrong_unfold)
    with pytest.raises(adapter.PipelineError, match="unfold_equivalence"):
        fresh = HiddenLibrary(decl(), atoms())
        fresh.write(next(definition for definition in definitions() if definition.name == "lamps"))
        fresh.check("lamps")
        from opulse.worlds_v2.hidden.story import evidence_request, samples
        fresh.make_callable("lamps", samples("lamps")[:1])
        fresh.verify("lamps", evidence_request("lamps"))
    monkeypatch.setattr(adapter.kernel, "inline", original)


def test_observation_rejects_unequal_paired_views(monkeypatch):
    from opulse.worlds_v2.hidden.story import evidence_request, samples

    library = HiddenLibrary(decl(), atoms())
    library.write(next(definition for definition in definitions() if definition.name == "lamps"))
    library.check("lamps")
    library.make_callable("lamps", samples("lamps")[:1])
    original = hosts.receiver

    def leaking_receiver(truth):
        view = original(truth)
        if truth.fields[0] == "B":
            return values.Card("ReceiverView", "view", (view.fields[0], values.Card("Actions", "list", ("B",))))
        return view

    monkeypatch.setattr(hosts, "receiver", leaking_receiver)
    with pytest.raises(PipelineError, match="paired views differ"):
        library.verify("lamps", evidence_request("lamps"))


def test_forged_cards_are_invalid_for_hosts_and_learner(library):
    forged = values.Card("Policy", "val", (values.Card("PolicyNode", "Ask", ("X",)),))
    bad_view = values.Card("ReceiverView", "view", (values.Card("History", "list", ("not-a-step",)),
                                                      values.Card("Actions", "list")))
    for card, name in ((forged, "first"), (bad_view, "lamps")):
        assert library.run(name, (card,)).outcome == values.Bottom("invalid")
    assert hosts.history(bad_view) == values.Bottom("invalid")
    assert hosts.node_mode(forged.fields[0]) == values.Bottom("invalid")
    assert hosts.fraction(values.Card("Rational", "forged", (1, 2))) == values.Bottom("invalid")
    invalid_belief = values.Card("Belief", "val", (hosts.pair(hosts.rational(2), hosts.rational(-1)),))
    assert library.run("confidence", (invalid_belief,)).outcome == values.Bottom("invalid")
    noncanonical = values.Card("Belief", "val", (hosts.pair(values.Card("Rational", "fraction", (2, 4)),
                                                           hosts.rational(Fraction(1, 2))),))
    assert library.run("confidence", (noncanonical,)).outcome == values.Bottom("invalid")
    assert hosts.pair_r(invalid_belief.fields[0]) == hosts.rational(2)
    assert library.run("Belief.r", (invalid_belief,)).outcome == values.Bottom("invalid")


def test_refinements_reject_invalid_base_values(library):
    for red, blue in ((2, -1), (0, 0), (-1, 2), (1, 1)):
        raw = hosts.pair(hosts.rational(red), hosts.rational(blue))
        assert library.run("Belief.make", (raw,)).outcome == values.Bottom("invalid")
    forged_belief = values.Card("Belief", "val", (hosts.pair(hosts.rational(1), hosts.rational(0)),))
    assert isinstance(library.run("Belief.make", (forged_belief,)).outcome, values.Bottom)
    for raw in (values.Card("PolicyNode", "Leaf", ("X",)),
                values.Card("PolicyNode", "Leaf", ()),
                values.Card("PolicyNode", "Ask", ("A", hosts.node_leaf("R"), "X")),
                values.Card("PolicyNode", "Ask", ("C", hosts.node_leaf("R"), hosts.node_leaf("B")))):
        assert library.run("Policy.make", (raw,)).outcome == values.Bottom("invalid")
    forged_policy = values.Card("Policy", "val", (hosts.node_leaf("R"),))
    assert isinstance(library.run("Policy.make", (forged_policy,)).outcome, values.Bottom)


def test_evidence_scopes_promotion_and_combinator_slots(library):
    from opulse.atoms.library import checked_scope
    from opulse.worlds_v2.hidden.story import samples

    definitions_by_name = library.definitions
    assert len([definition for definition in definitions_by_name.values() if definition.origin == "invented"]) == 12
    for name in (*NAMES, "update_copy", "value_copy"):
        definition = library.get(name)
        assert definition.status == "promoted"
        assert definition.evidence.method in ("bounded", "exhaustive")
        assert definition.evidence.scope["size"] >= 50
        assert {k: v for k, v in definition.evidence.scope["checked"].items() if k != "by"} == checked_scope(samples(name))
        assert definition.evidence.world_hash == library.world.world_hash()
        assert definition.cost.steps["max"] >= definition.cost.steps["min"]
        assert definition.contract is not None
    for name in ("scan", "optimize"):
        assert len(set(library.get(name).evidence.scope["op_family"])) >= 2
        assert "fixed_ops" not in library.get(name).evidence.scope
    assert library.get("scan").layer == 1
    assert library.get("regret").layer == 4
    assert all(definition.layer >= 1 for definition in definitions())


def test_declaration_validator_roundtrip_and_codec():
    path = EXPORT_PATH.parents[4] / "worlds/decl/v2/hidden@1.json"
    assert validate(load(path)) == []
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert WorldDecl.from_dict(stored).to_dict() == decl().to_dict()
    assert {key: value for key, value in decl().to_dict().items() if key != "open_kinds"} == stored
    assert {"channel", "signal", "guess", "add", "mul", "div", "lt", "le", "eq"} <= {
        op.name for op in decl().operations}
    assert decl().combinators["library"][0]["name"] == "bind"


@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="set OPULSE_RUN_SLOW=1 to compare the fresh full export")
def test_export_is_committed_exact_sealed_and_ascii(library):
    actual = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    rebuilt, judge = build_export(include_judge=True)
    assert actual == rebuilt
    assert judge == json.loads(JUDGE_PATH.read_text(encoding="utf-8"))
    assert all("judge_view" not in example for row in actual["story"] for example in row["examples"])
    assert EXPORT_PATH.stat().st_size < 3_000_000
    assert actual["tower_source"] == "depth"
    assert [entry["name"] for entry in actual["story"]] == list(NAMES)
    assert [entry["kind"] for entry in actual["story"]] == [
        item["kind"] for item in json.loads(DEPTH_PATH.read_text(encoding="utf-8"))["tower"]]
    for item in actual["story"]:
        assert item["layer"] in range(1, 11)
        assert item["def_layer"] == library.get(item["name"]).layer
        assert item["body_sha256"] == export_util.body_sha256(library.get(item["name"]).body)
        if "ascii" in item:
            assert notation.parse_definition(item["ascii"]).layer == item["def_layer"]
            assert item["ascii"] == item["decl"]
            assert export_util.source_matches(item["ascii"], item["body_sha256"])
        else:
            assert "decl" not in item
        assert item["design_text"] == item["design_decl"]
        assert item["title"] and item["definition"]
        for example in item["examples"]:
            if "ascii" in example:
                assert notation.parse_expr(example["text"]) == expression(item["name"])
            assert "learner_view" in example and "judge_view" not in example
            assert example["learner_view"]["receiver"]["t"] == "ReceiverView"
            assert "Truth" not in json.dumps(example["learner_view"])
            assert "Truth" not in json.dumps(example["inputs"])
            assert "Truth" not in json.dumps(example["trace"])
            assert "Truth" not in example["text"]
            assert example["steps"] > 0
        assert item["examples"][0]["text"] == TEXT[item["name"]]
    assert {entry["id"] for entry in judge["examples"]} == set(NAMES) | {"scan:unpaired"}
    for entry in judge["examples"]:
        example = next(example for item in actual["story"] for example in item["examples"]
                       if example["id"] == entry["id"])
        truth = entry["judge_view"]["truth"]
        assert truth["t"] == "Truth"
        assert entry["inputs"] == example["inputs"]
        assert entry["judge_view"]["public_inputs"] == example["inputs"]
        assert truth["f"][1:] == example["learner_view"]["receiver"]["f"]
    for name, count in (("lamps", 3), ("scan", 6), ("confidence", 2), ("regret", 3),
                        ("update", 1), ("first", 0), ("scan:unpaired", 0)):
        entry = next(entry for entry in judge["examples"] if entry["id"] == name)
        assert len(entry["judge_view"]["truth"]["f"][1]["f"]) == count
    for name, history in (("scan", (("A", "red"), ("B", "blue"), ("B", "red"),
                                    ("A", "red"), ("B", "blue"), ("B", "red"))),
                          ("confidence", (("A", "red"), ("A", "red"))),
                          ("regret", (("A", "red"), ("B", "blue"), ("B", "red")))):
        example = next(row["examples"][0] for row in actual["story"] if row["name"] == name)
        steps = example["learner_view"]["receiver"]["f"][0]["f"]
        assert tuple(tuple(field["v"] for field in step["f"]) for step in steps) == history
    assert any(example["outcome"] == {"bottom": "unpaired"}
               for item in actual["story"] for example in item["examples"])
    assert actual["showcase"] and all(task["answer_checked"] for task in actual["showcase"])

    def strings(data, key=""):
        if isinstance(data, dict):
            for name, item in data.items():
                if name.endswith("_zh"):
                    continue
                yield from strings(item, name)
        elif isinstance(data, list):
            for item in data:
                yield from strings(item, key)
        elif isinstance(data, str) and not key.endswith("_zh"):
            yield data

    assert all(not re.search("[^\\x00-\\x7f]", item)
               for item in strings({key: value for key, value in actual.items()
                                    if key not in ("decl", "notation3")}))
