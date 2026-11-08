"""Independent, finite checks of all twelve weighted-text cards."""

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, notation, values
from opulse.atoms import nodes as n
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.text import hosts
from opulse.worlds_v2.text.export import DESTINATION, build_export, examples, render
from opulse.worlds_v2.text.story import (
    TOWER,
    build_library,
    build_library_until,
    definitions,
    lex,
    oracle_lex,
    oracle_value,
    reference_module,
    word,
)
from opulse.worlds_v2.text.world import decl, new_library


def test_declaration_and_round_trip():
    path = Path(__file__).resolve().parents[3] / "worlds/decl/v2/text@1.json"
    declaration = decl()
    assert declaration == WorldDecl.from_dict(declaration.to_dict())
    assert not validate(load(path))
    assert declaration.params["max_length"] == 64
    assert declaration.params["max_lexicon"] == 16


def test_design_oracle_and_export():
    design = json.loads((Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/text.json").read_text())
    assert reference_module().checks()[0] == [item["value"] for item in design["tower"]]
    published = json.loads(DESTINATION.read_text(encoding="utf-8"))
    assert published == build_export()
    assert len(published["story"]) == 12
    assert all(card["status"] == "promoted" and card["evidence"]["scope"]["size"] >= 50
               for card in published["story"])
    assert all(card["evidence"]["scope"]["checked"]["size"] == card["evidence"]["scope"]["size"]
               for card in published["story"])
    assert all("fixed_ops" not in card["evidence"]["scope"]
               for card in published["story"] if card["name"] in ("rewrite", "routes"))
    assert all(card["layer"] == index for index, card in enumerate(published["story"], 1))
    assert published["tower_source"] == "depth"
    assert all(card["answer_checked"] for card in published["showcase"])


def test_fresh_first_three_cards():
    library = build_library_until("rewrite")
    assert library.get("rewrite").status == "promoted"
    assert library.run("split", ("a b",)).outcome == values.Ok(hosts.sequence(word("a"), word("b")))


@settings(max_examples=12, deadline=None)
@given(st.text(alphabet="ab ", max_size=5))
def test_random_split_unfold_boundary(source):
    library = build_library()
    result = library.run("split", (source,), trace=True)
    assert result.outcome == values.Ok(oracle_value(reference_module().split(source)))
    assert unfold_equivalent(result.trace, [Boundary.unfold_none(), Boundary.unfold_all(),
                                            Boundary(depth=1)]).ok


def test_exact_tower_values_and_failure():
    lib = build_library()
    for name in ("Word", "Lex", "Parse"):
        assert lib.get(name).spec.interface == (f"{name}.make", f"{name}.base")
    design = json.loads((Path(__file__).resolve().parents[3] / "worlds/catalogue/depth/text.json").read_text())
    for index, (name, args) in enumerate(examples()):
        result = lib.run(name, args, trace=True)
        assert isinstance(result.outcome, values.Ok), (name, result.outcome)
        expected = design["tower"][index]["value"]
        actual = ("Text<" + render(result.outcome.value) + ">" if index == 2 else
                  result.outcome.value if type(expected) is int else render(result.outcome.value))
        assert actual == expected
        assert result.steps > 0
        assert unfold_equivalent(result.trace, [Boundary.unfold_none(), Boundary.unfold_all(),
                                                Boundary(depth=2)]).ok
        definition = lib.get(TOWER[index])
        assert definition.evidence.world_hash == lib.world.world_hash()
        assert definition.contract is not None
    assert lib.run("Word.make", ("",)).outcome == values.Bottom("invalid")
    assert lib.run("Word.make", ("a b",)).outcome == values.Bottom("invalid")
    assert lib.run("kth_optimal", ("aab", examples()[7][1][1], 99)).outcome == values.Bottom("index")
    assert lib.run("best", ("b", lex(("a", 1)))).outcome == values.Ok(values.Card("Option", "none"))
    assert lib.run("parses", ("", lex(("a", 1)))).outcome == values.Ok(1)


def test_long_inputs_match_independent_dynamic_programming():
    lib = build_library()
    oracle = reference_module()
    for source in ("aab", "abababab", "a" * 12, "ab" * 12, "ab" * 24):
        dictionary = lex(("a", 2), ("aa", 3), ("aaa", 4), ("b", 2),
                         ("ab", 4), ("aba", 6), ("ba", 4), ("bab", 6))
        reference_dict = oracle_lex(dictionary)
        for name in ("parses", "best", "optimal_count"):
            assert lib.run(name, (source, dictionary)).outcome == values.Ok(
                oracle_value(getattr(oracle, name)(source, reference_dict)))
    dictionary = lex(("a", 2), ("aa", 3), ("ab", 4), ("b", 3))
    for source in ("aab", "abab", "aaaa", "aaba"):
        for rank in range(min(oracle.optimal_count(source, oracle_lex(dictionary)), 3)):
            assert lib.run("kth_optimal", (source, dictionary, rank)).outcome == values.Ok(
                oracle_value(oracle.kth_optimal(source, oracle_lex(dictionary), rank)))


def test_given_host_discipline_and_four_invariants():
    lib = build_library()
    assert not {"edges", "routes", "parses", "best", "optimal_count", "kth_optimal"} & {
        op.name for op in lib.world.operations}
    assert hosts.concat("a" * 64, "b") == values.Bottom("text_domain_or_size")
    assert hosts.slice_text("ab", 2, 1) == values.Bottom("span")
    assert hosts.sub_nat(0, 1) == values.Bottom("nat_subtraction")
    assert hosts.add(2**100, 1) == 2**100 + 1
    assert hosts.length("a" * 64) == 64
    assert lib.run("map_chars", (kernel.FnRef("identity"), "ab " * 21 + "a")).outcome == values.Ok("ab " * 21 + "a")
    assert lib.run("Lex.make", (hosts.sequence(hosts.pair(word("a"), 2),
                                                hosts.pair(word("a"), 3)),)).outcome == values.Bottom("invalid")
    assert isinstance(lib.run("Lex.make", (hosts.sequence(hosts.pair(values.Card("Word", "val", ("a b",)), 2)),)).outcome,
                      values.Bottom)
    assert lib.run("Parse.make", (hosts.pair("aa", hosts.pair(lex(("a", 2)),
                                                      hosts.sequence(word("b")))),)).outcome == values.Bottom("invalid")
    for source in ("a  b", "ab a", "", " b  a "):
        before = source
        assert lib.run("chars", (source,)).outcome == values.Ok(hosts.chars(source))
        assert lib.run("starts", (source,)).outcome == values.Ok(oracle_value(reference_module().starts(source)))
        assert source == before
    with pytest.raises(PipelineError, match="requires verif"):
        empty = new_library()
        definition = definitions()[0]
        empty.write(definition)
        empty.check(definition.name)
        empty.make_callable(definition.name, (("ab",),))
        empty.promote(definition.name, Contract("cannot promote without evidence"))
    assert all(lib.get(name).evidence.method in ("bounded", "exhaustive") for name in TOWER)


def test_refinement_constructors_reject_invalid_inputs():
    library = build_library()
    for invalid in ("", "a b", "c", "a" * 65, 4):
        assert library.run("Word.make", (invalid,)).outcome == values.Bottom("invalid")
    for entries in (hosts.sequence(hosts.pair(word("a"), 0)),
                    hosts.sequence(hosts.pair(word("a"), 10)),
                    hosts.sequence(hosts.pair(word("a"), 2), hosts.pair(word("a"), 3)),
                    hosts.sequence(hosts.pair(values.Card("Word", "val", ("a b",)), 2))):
        assert isinstance(library.run("Lex.make", (entries,)).outcome, values.Bottom)
    dictionary = lex(("a", 2))
    for source, words in (("a", hosts.sequence()),
                          ("aa", hosts.sequence(word("a"))),
                          ("b", hosts.sequence(word("b")))):
        certificate = hosts.pair(source, hosts.pair(dictionary, words))
        assert library.run("Parse.make", (certificate,)).outcome == values.Bottom("invalid")
    forged_dictionary = values.Card("Lex", "val", (hosts.sequence(hosts.pair(word("a"), 0)),))
    forged_certificate = hosts.pair("", hosts.pair(forged_dictionary, hosts.sequence()))
    assert isinstance(library.run("Parse.make", (forged_certificate,)).outcome, values.Bottom)
    assert isinstance(library.run("Word.base", (word("a b"),)).outcome, values.Bottom)
    assert isinstance(library.run("Lex.base", (forged_dictionary,)).outcome, values.Bottom)


def test_ascii_notation_and_checked_expression_inputs():
    exported = build_export()
    library = build_library()
    expression_context = {"kinds": {card["name"]: card["kind"] for card in exported["story"]},
                          "op_arity": {"rewrite": 1, "routes": 2},
                          "observation_arity": {"starts": 1, "parses": 2, "best": 2,
                                                "optimal_count": 2}}
    for card in exported["story"]:
        digest = export_util.body_sha256(library.get(card["name"]).body)
        assert card["body_sha256"] == digest
        assert ("ascii" in card) == ("decl" in card)
        if "ascii" in card:
            assert notation.parse_definition(card["decl"]).layer == card["def_layer"]
            assert card["decl"].endswith(f" L{card['def_layer']}")
            assert card["ascii"] == card["decl"]
            assert export_util.source_matches(card["ascii"], digest)
        assert card["design_text"] == card["design_decl"]
        assert card["symbol"].startswith({"object": card["name"] + "<",
                                           "operation": card["name"] + "(",
                                           "combinator": "@" + card["name"] + "[",
                                           "observation": "?" + card["name"] + "{"}[card["kind"]])
        assert card["cost"]["steps_scope"] == "verification family; see evidence.scope"
        assert card["example_steps"]["max"] == max(example["steps"] for example in card["examples"])
        for key in ("symbol", "title", "definition"):
            assert card[key].isascii()
        for example in card["examples"]:
            assert example["text"].isascii()
            assert example["text"].startswith(("?", "@", card["name"], "Word.make", "Lex.make", "Parse.make"))
            if card["name"] not in ("Word", "Lex", "Parse"):
                parsed = notation.parse_expr(example["text"], expression_context)
                assert isinstance(parsed, n.Call) and parsed.fn == card["name"]
                assert [({"t": "fn", "v": arg.value.name} if isinstance(arg.value, kernel.FnRef)
                         else values.encode(arg.value)) for arg in parsed.args] == example["inputs"]
            assert example["trace"] is not None
    for name in ("objects", "operations", "combinators", "observation"):
        group = exported["layer0"][name]
        for item in (group["entries"] if isinstance(group, dict) else group):
            assert item["decl"].isascii()


def test_published_ascii_matches_stored_bodies():
    library = build_library()
    rows = build_export()["story"]
    assert {row["name"] for row in rows if "ascii" not in row} == {
        "Word", "split", "rewrite", "Lex", "edges", "parses", "best", "optimal_count",
        "Parse", "kth_optimal", "starts",  # round 6: printed subject {s} does not bind the body's text
    }
    for row in rows:
        digest = export_util.body_sha256(library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        assert ("ascii" in row) == ("decl" in row)
        if "ascii" in row:
            assert export_util.source_matches(row["ascii"], digest)
