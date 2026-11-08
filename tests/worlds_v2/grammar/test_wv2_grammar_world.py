"""Deep grammar: finite independent reference, kernel pipeline and export."""

import json
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError, VerifyRequest
from opulse.atoms.spec import Contract, Definition, Edge, Evidence, OperationSpec
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.export_util import body_sha256, bound_evidence, source_matches
from opulse.worlds_v2.grammar import hosts
from opulse.worlds_v2.grammar.adapter import GrammarLibrary
from opulse.worlds_v2.grammar.export import (
    EXPORT_PATH,
    JUDGE_PATH,
    NAMES,
    _public_expression,
    _public_text,
    build_export,
    format_value,
    outcome_text,
)
from opulse.worlds_v2.grammar.story import build_library, definitions, oracle
from opulse.worlds_v2.grammar.world import decl, new_library

DECL_PATH = Path(__file__).resolve().parents[3] / "worlds/decl/v2/grammar@1.json"
DESIGN_PATH = Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/grammar.json"


@pytest.fixture(scope="module")
def library():
    return build_library()


@pytest.fixture(scope="module")
def exported():
    return json.loads(EXPORT_PATH.read_text(encoding="utf-8"))


def test_first_three_cards_build_fresh():
    fresh = build_library(stop_after="chart")
    for name in NAMES[:3]:
        assert fresh.get(name).status == "promoted"
    assert fresh.run("ExprTree.make", (hosts.to_card(("num", 7)),)).outcome == values.Ok(
        values.Card("ExprTree", "val", (hosts.to_card(("num", 7)),)))
    assert fresh.run("split", (hosts.word(2, "+", "(", 3, "*", 2, ")"),)).outcome == values.Ok(
        values.Card("List", "items", (1,)))
    assert fresh.run("chart", tuple(kernel.FnRef(item) for item in
                                    ("one", "multiply", "identity", "combine_count", "zero")) +
                     (hosts.word(1, "+", 2, "*", 3, "+", 1),)).outcome == values.Ok(5)


@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="fresh full export exceeds 60 seconds")
def test_fresh_export_matches_committed():
    assert build_export() == json.loads(EXPORT_PATH.read_text(encoding="utf-8"))


def test_declaration_hosts_and_pipeline(library):
    source = json.loads(DECL_PATH.read_text(encoding="utf-8"))
    assert {key: value for key, value in decl().to_dict().items() if key != "open_kinds"} == source
    assert not validate(load(DECL_PATH))
    assert {operation.name for operation in decl().operations} | {"yield_probe"} == {
        atom.name for atom in new_library().atoms}
    assert [library.get(name).kind for name in NAMES] == [
        "object", "operation", "combinator", "observation", "operation", "observation",
        "object", "combinator", "observation", "operation", "operation"]
    assert len(library.derived_world().promoted) >= 11
    for name in NAMES:
        definition = library.get(name)
        assert definition.status == "promoted"
        assert definition.evidence.method == "bounded"
        assert definition.evidence.scope["size"] >= 50
        assert definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
        assert len(definition.evidence.scope["checked"]["sha256"]) == 64
        assert definition.contract and definition.cost
        assert definition.layer <= NAMES.index(name) + 1
    assert library.get("chart").spec.op_params == ("leaf", "join", "wrap", "merge", "zero_slot")
    assert library.get("ExprTree").spec.interface == ("ExprTree.make",)
    assert library.get("chart").evidence.scope["memo_steps"] == library.get("chart").evidence.scope["plain_steps"]
    assert library.get("chart").evidence.scope["memo_steps"] == 228
    assert library.get("chart").evidence.scope["memo_work"] == 207
    assert library.get("chart").evidence.scope["plain_work"] == 228
    assert {"Rule", "Hist"} <= {item.name for item in decl().objects}
    assert library.get("fold").spec.op_params == ("leaf", "join", "wrap")
    assert library.get("seq").origin == "given" and library.get("bounded_rec").origin == "given"


def test_layer_zero_matches_reference():
    reference = oracle()
    for token in range(1, 10):
        result = hosts.expand(hosts.HOLE, hosts.list0(), values.Card("Rule", "num", (token,)))
        assert hosts.from_card(result) == reference.expand("E", (), ("num", token))
        assert hosts.yield_probe(result) == hosts.word(*reference.yield_tokens(reference.expr_tree(("num", token))))
    first = hosts.expand(hosts.HOLE, hosts.list0(), values.Card("Rule", "+"))
    first = hosts.expand(first, hosts.list1(1), values.Card("Rule", "num", (2,)))
    first = hosts.expand(first, hosts.list1(2), values.Card("Rule", "num", (3,)))
    assert hosts.from_card(first) == reference.expand(reference.expand(
        reference.expand("E", (), ("+",)), (1,), ("num", 2)), (2,), ("num", 3))
    for invalid in (hosts.word(0), hosts.word(1, "("), hosts.word(*range(13))):
        assert isinstance(invalid, values.Bottom)
    assert hosts.expand(hosts.HOLE, hosts.list1(2), values.Card("Rule", "num", (2,))) == values.Bottom("path")
    assert hosts.yield_probe(hosts.HOLE) == values.Bottom("unfinished")


def test_all_tower_values_and_fresh_dependent_inputs(library, exported):
    reference = oracle()
    judge = json.loads(JUDGE_PATH.read_text(encoding="utf-8"))
    source = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    assert reference.tower_values() == [entry["value"] for entry in source["tower"]]
    assert [entry["kind"] for entry in exported["story"]] == [entry["kind"] for entry in source["tower"]]
    assert [entry["name"] for entry in exported["story"]] == list(NAMES)
    for card, design, sealed in zip(exported["story"], source["tower"], judge["examples"]):
        assert outcome_text(values.decode_outcome(sealed["outcome"])) == design["value"]
        assert card["layer"] == design["layer"]
        assert card["def_layer"] == library.get(card["name"]).layer
        assert card["examples"][0]["steps"] > 0
        assert card["examples"][0]["text"].startswith(("@", "?", card["name"] + "(" , card["name"] + ".make("))
        for example in card["examples"]:
            assert example["learner_view"] and "judge_view" not in example
    assert exported["story"][2]["examples"][1]["inputs"] != exported["story"][2]["examples"][0]["inputs"]
    assert len(exported["story"][4]["examples"]) == 2
    assert exported["story"][4]["examples"][1]["outcome"] == {"bottom": "rank"}


def test_public_chart_and_histogram_for_exact_families(library):
    reference = oracle()
    for first in (1, 2, 3):
        for middle in (1, 2, 3):
            for last in (1, 2, 3):
                for operator in ("+", "*"):
                    word = hosts.word(first, operator, middle, "+", last)
                    assert library.run("split", (word,)).outcome == values.Ok(
                        values.Card("List", "items", reference.split(word.fields)))
                    assert library.run("parse_count", (word,)).outcome == values.Ok(reference.parse_count(word.fields))
                    assert library.run("ambiguous", (word,)).outcome == values.Ok(
                        values.boolean(reference.ambiguous(word.fields)))
                    histogram = library.run("value_hist", (word,)).outcome.value
                    assert {pair.fields[0]: pair.fields[1] for pair in histogram.fields} == reference.value_hist(word.fields)
                    assert library.run("gap", (word,)).outcome == values.Ok(reference.gap(word.fields))


def test_ranked_proofs_are_distinct_and_sealed(library):
    reference = oracle()
    word = hosts.word(1, "+", 2, "*", 3)
    left, right = (library.run("unrank", (word, rank)).outcome.value for rank in (0, 1))
    assert left != right
    with pytest.raises(PipelineError, match="sealed object private name"):
        library.run("ExprTree.base", (left,))
    assert library.run("field", (left, 0)).outcome == values.Bottom("permission")
    for rank, tree in enumerate((left, right)):
        assert hosts.from_card(tree.fields[0]) == reference.unrank(word.fields, rank)
        assert library.run("yield_probe", (tree.fields[0],)).outcome == values.Ok(word)
    witness = library.run("Ambiguity.make", (values.Card("Witness", "triple", (word, left, right)),))
    assert isinstance(witness.outcome, values.Ok)
    assert library.run("field", (witness.outcome.value, 0)).outcome == values.Bottom("permission")
    forged = values.Card("ExprTree", "val", (hosts.to_card(("num", 3)),))
    assert library.run("Ambiguity.make", (values.Card("Witness", "triple", (word, left, forged)),)).outcome == values.Bottom("invalid")
    invalid = library.run("Ambiguity.make", (values.Card("Witness", "triple", (word, left, left)),))
    assert invalid.outcome == values.Bottom("invalid")
    other_word = hosts.word(1, "+", 1, "*", 1)
    assert library.run("Ambiguity.make", (values.Card("Witness", "triple", (other_word, left, right)),)).outcome == values.Bottom("invalid")
    for bad_draft in (hosts.HOLE, values.Card("Draft", "num", (0,)),
                      values.Card("Draft", "+", (hosts.to_card(("num", 1)), hosts.HOLE))):
        assert library.run("ExprTree.make", (bad_draft,)).outcome == values.Bottom("invalid")
    assert library.run("unrank", (word, 99)).outcome == values.Bottom("rank")
    assert library.run("invert_gap", (99999, 4, 2)).outcome == values.Bottom("none")


def test_forged_cards_are_invalid_in_hosts_and_learner_runs(library):
    cases = (
        values.Card("Word", "invented", (1, "+", 2)),
        values.Card("Draft", "num", (0,)),
        values.Card("ExprTree", "invented", (hosts.to_card(("num", 1)),)),
        values.Card("ExprTree", "val", (hosts.HOLE,)),
        values.Card("Ambiguity", "val", (values.Card("Witness", "triple", (hosts.word(1),)),)),
    )
    for forged in cases:
        assert hosts.word(forged) == values.Bottom("invalid")
        assert hosts.tag(forged) == values.Bottom("invalid")
        assert hosts.field(forged, 0) == values.Bottom("invalid")
        assert library.run("tag", (forged,)).outcome == values.Bottom("invalid")
        assert library.run("identity", (forged,)).outcome == values.Bottom("invalid")
    malformed = values.Card("List", "items", (cases[2],))
    assert hosts.length(malformed) == values.Bottom("invalid")
    assert library.run("identity", (malformed,)).outcome == values.Bottom("invalid")
    assert library.run("identity", ((cases[2],),)).outcome == values.Bottom("invalid")
    assert hosts.list1({"tree": cases[2]}) == values.Bottom("invalid")
    assert library.run("identity", ({"tree": cases[2]},)).outcome == values.Bottom("invalid")
    valid_word = hosts.word(1, "+", 2, "*", 3)
    first = library.run("unrank", (valid_word, 0)).outcome.value
    second = library.run("unrank", (valid_word, 1)).outcome.value
    unranked = values.Card("Ambiguity", "val", (
        values.Card("Witness", "triple", (valid_word, first, first)),))
    assert hosts.tag(unranked) == values.Bottom("invalid")
    assert library.run("identity", (unranked,)).outcome == values.Bottom("invalid")
    assert hosts.tag(values.Card("Ambiguity", "val", (
        values.Card("Witness", "triple", (valid_word, first, second)),))) == "val"


def test_observation_evidence_only_claims_checks_performed(library):
    for name in ("parse_count", "ambiguous", "value_hist"):
        assert "non_interference" in library.get(name).evidence.checks
        assert {"facts_unchanged", "reference"} <= set(library.get(name).evidence.checks)
    for name in ("chart", "fold"):
        assert "non_interference" not in library.get(name).evidence.checks


def test_public_nested_examples_execute_the_expression_shown(library, exported):
    examples = {example["id"]: example for card in exported["story"] for example in card["examples"]}
    judge = {example["id"]: example for example in json.loads(JUDGE_PATH.read_text())["examples"]}
    word = hosts.word(1, "+", 2, "*", 3)
    first = library.run("unrank", (word, 0)).outcome.value
    second = library.run("unrank", (word, 1)).outcome.value
    cases = (
        ("ExprTree", "ExprTree.make", (hosts.to_card(("num", 7)),), 15),
        ("Ambiguity", "Ambiguity.make", (values.Card("Witness", "triple", (word, first, second)),), 2681),
        ("fold", "fold", tuple(kernel.FnRef(item) for item in
                               ("identity", "arithmetic", "identity")) + (first,), 648),
    )
    for example_id, name, args, steps in cases:
        expression = _public_expression(library, name, args)
        run = library.run(name, args, expression=expression, trace=True)
        assert examples[example_id]["text"] == _public_text(library, name, args)
        assert examples[example_id]["steps"] == run.steps == steps
        assert values.encode_outcome(run.outcome) == judge[example_id]["outcome"]
        assert run.trace.steps == steps


def test_non_interference_rejects_equal_view_counterexample(library, monkeypatch):
    word = hosts.word(1)
    equal_view_copy = values.Card("Word", "tokens", tuple(word.fields))
    assert word is not equal_view_copy and word.fields == equal_view_copy.fields
    runs = iter((1, 2))
    references = iter((1, 2))
    original = library.get("parse_count")
    library._definitions["parse_count"] = replace(original, status="callable")

    def altered_run(self, name, args, fuel=None, trace=False):
        return kernel.Run(values.Ok(next(runs)), 1, 0, None, 1)

    monkeypatch.setattr(GrammarLibrary, "run", altered_run)
    request = VerifyRequest("bounded", ((word,), (equal_view_copy,)),
                            {"domain": "two distinct equal-view public words", "size": 2},
                            reference=lambda *_: next(references))
    try:
        with pytest.raises(PipelineError, match="non-interference"):
            library.verify("parse_count", request)
    finally:
        library._definitions["parse_count"] = original


def test_kernel_boundaries_and_accounting(library):
    word = hosts.word(2, "+", 3, "*", 1)
    run = library.run("parse_count", (word,), trace=True)
    assert run.outcome == values.Ok(2)
    assert run.steps == sum(item.steps for item in run.trace.children)
    assert unfold_equivalent_calls(run.trace, [Boundary(None), Boundary(1)]).ok
    scope = library.scope()
    result = kernel.evaluate(kernel.inline(nodes.Call("parse_count", (nodes.Lit(word),)), scope), scope=scope)
    assert result.outcome == run.outcome and result.steps == run.steps


@settings(max_examples=12, deadline=None)
@given(numbers=st.lists(st.integers(min_value=1, max_value=3), min_size=1, max_size=3),
       operators=st.lists(st.sampled_from(("+", "*")), min_size=2, max_size=2))
def test_random_small_parse_unfolds(library, numbers, operators):
    tokens = [numbers[0]]
    for operator, number in zip(operators, numbers[1:]):
        tokens.extend((operator, number))
    run = library.run("parse_count", (hosts.word(*tokens),), trace=True)
    assert isinstance(run.outcome, values.Ok)
    assert unfold_equivalent_calls(run.trace, [Boundary(None), Boundary(1)]).ok


def test_i1_i4_and_promotion_guards(library):
    word = hosts.word(1, "+", 2, "*", 3)
    left = library.run("unrank", (word, 0)).outcome.value
    right = library.run("unrank", (word, 1)).outcome.value
    assert left != right and library.run("yield_probe", (left.fields[0],)).outcome == values.Ok(word)
    assert library.run("yield_probe", (right.fields[0],)).outcome == values.Ok(word)
    assert library.run("ambiguous", (word,)).outcome == values.Ok(values.TRUE)
    first = library.run("value_hist", (word,)).outcome
    altered_private_draft = right.fields[0]
    assert library.run("yield_probe", (altered_private_draft,)).outcome == values.Ok(word)
    assert library.run("value_hist", (word,)).outcome == first
    outsider = Definition("leak_tree", "operation", "invented", 2, ("ExprTree._pack",),
                          OperationSpec("leak_tree", "transform", (Edge("Draft"),), Edge("ExprTree"),
                                        "Try to bypass the sealed constructor.",
                                        extra={"input_names": ["tree"]}),
                          nodes.Call("ExprTree._pack", (nodes.Var("tree"),)))
    fresh = new_library()
    fresh.write(next(definitions()))
    fresh.check("ExprTree")
    fresh.make_callable("ExprTree", [(hosts.to_card(("num", 3)),)])
    fresh.write(outsider)
    with pytest.raises(PipelineError, match="private sealed operation ExprTree\\._pack"):
        fresh.check("leak_tree")
    forged_fold = next(item for item in definitions() if item.name == "fold")
    fresh.write(replace(forged_fold, body=nodes.Call("ExprTree.base", (nodes.Var("t"),)),
                        depends_on=("ExprTree.base",)))
    with pytest.raises(PipelineError, match="private sealed operation ExprTree\\.base"):
        fresh.check("fold")
    assert all(library.get(name).evidence.world_hash == library.world.world_hash() for name in NAMES)
    for name in ("split", "unrank", "value_hist"):
        assert library.get(name).evidence.deps_hash == library._deps_hash(name)

    fresh = new_library()
    candidate = next(definitions())
    fresh.write(candidate)
    fresh.check(candidate.name)
    fresh.make_callable(candidate.name, [(hosts.to_card(("num", 3)),)])
    with pytest.raises(PipelineError):
        fresh.promote(candidate.name, Contract(guarantees="unverified"))
    evidence = bound_evidence(fresh, candidate.name,
                              Evidence("sampled", {"domain": "one draft", "size": 1}, 17, ("valid",),
                                       fresh.world.world_hash(), fresh._deps_hash(candidate.name)),
                              ((hosts.to_card(("num", 3)),),))
    fresh._definitions[candidate.name] = replace(fresh.get(candidate.name), status="verified", evidence=evidence)
    with pytest.raises(PipelineError, match="sampled"):
        fresh.promote(candidate.name, Contract(guarantees="sampled"))


def test_export_is_committed_and_ascii(exported):
    assert json.loads(EXPORT_PATH.read_text(encoding="utf-8")) == exported
    assert EXPORT_PATH.stat().st_size < 3_000_000
    assert exported["tower_source"] == "depth"
    assert len(exported["ladder"]) == 5 and len(exported["showcase"]) == 3
    assert all(task["answer_checked"] for task in exported["showcase"])
    assert [task["answer"] for task in exported["showcase"]] == oracle().showcase_values()

    def walk(item, field=""):
        if isinstance(item, dict):
            for name, value in item.items():
                if name == "notation3":  # Notation v3: the generated display block is not machine notation
                    continue
                yield from walk(value, name)
        elif isinstance(item, list):
            for value in item:
                yield from walk(value, field)
        elif isinstance(item, str) and not field.endswith("_zh"):
            yield item

    forbidden = "⟨⟩⟦⟧⦅⦆♠♦○◉ℚ𝔹"
    assert not [(field, char) for field in walk(exported) for char in forbidden if char in field]
    assert format_value(hosts.word(2, "+", 3)) == "Word<2,+,3>"


def test_story_ascii_matches_stored_bodies(exported, library):
    for row in exported["story"]:
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert source_matches(row["ascii"], digest)


def test_story_notation_matches_computed_layers_and_examples(exported, library):
    # Round 6: an observation printed with subject {s} whose body reads another variable is not published.
    assert [row["name"] for row in exported["story"] if "ascii" in row] == ["chart"]
    context = {"kinds": {row["name"]: row["kind"] for row in exported["story"]},
               "op_arity": {"chart": 5, "fold": 3}}
    judge_inputs = {item["id"]: item["inputs"] for item in json.loads(JUDGE_PATH.read_text())["examples"]}
    for row in exported["story"]:
        source = row.get("ascii")
        assert row["design_decl"] == row["design_text"]
        digest = body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if source is not None:
            assert row["decl"] == source
            assert source_matches(source, digest)
            assert source.isascii()
            assert re.search(rf" L{row['def_layer']}$", source)
            parsed = notation.parse_definition(source)
            assert parsed.name == row["name"]
            assert parsed.layer == row["def_layer"]
        else:
            assert "decl" not in row
        for example in row["examples"]:
            if row["kind"] == "object":
                assert "ascii" not in example
                with pytest.raises(notation.NotationError):
                    notation.parse_expr(example["text"], context)
            else:
                expression = notation.parse_expr(example["text"], context)
                assert isinstance(expression, nodes.Call)
                assert expression.fn == row["name"]
                if row["name"] not in ("fold",):
                    assert expression == nodes.Call(row["name"], tuple(
                        nodes.Lit(values.decode(item)) for item in judge_inputs[example["id"]]))
                if row["kind"] == "operation":
                    assert example["ascii"] == example["text"]


def test_sealed_examples_live_only_in_judge_file(exported):
    judge = json.loads(JUDGE_PATH.read_text(encoding="utf-8"))
    assert len(judge["examples"]) == sum(len(card["examples"]) for card in exported["story"])
    assert {ex["id"] for ex in judge["examples"]} == {ex["id"] for card in exported["story"] for ex in card["examples"]}
    assert "Draft" not in json.dumps(exported["story"][6]["examples"])
    assert "Draft<" in json.dumps(judge["examples"][0])
    assert all("judge_view" not in example for card in exported["story"] for example in card["examples"])
