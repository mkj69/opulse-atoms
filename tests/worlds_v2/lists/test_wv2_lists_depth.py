"""Depth catalogue invariants and exact kernel evidence for lists."""

import json
import re
from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes, notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract
from opulse.atoms.verify import unfold_equivalent_calls
from opulse.atoms.world import WorldDecl
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.lists import hosts, oracle
from opulse.worlds_v2.lists.export import (
    DESIGN_PATH,
    EXPORT_PATH,
    NAMES,
    build_export,
    examples,
)
from opulse.worlds_v2.lists.story import build_library, definitions
from opulse.worlds_v2.lists.world import decl, new_library


@pytest.fixture(scope="module")
def world():
    return build_library()


@pytest.fixture(scope="module")
def exported():
    return build_export()


def test_decl_and_host_discipline():
    source = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    declaration = decl()
    assert WorldDecl.from_dict(declaration.to_dict()).to_dict() == declaration.to_dict()
    assert len(declaration.lock["world_hash"]) == 64
    assert declaration.params["exhibit_max_length"] >= 32
    assert {"nil", "cons", "head", "tail", "lt", "le", "eq", "ne", "add", "sub", "split_at", "half_floor"} <= {op.name for op in declaration.operations}
    assert len(source["tower"]) == 12
    for row in ((), (1,), (-2, 0, 1, 0)):
        assert hosts.from_card(hosts.to_card(row)) == row
    assert hosts.head(hosts.NIL) == values.Bottom("empty")
    assert hosts.tail(hosts.NIL) == values.Bottom("empty")


def test_catalogue_values_and_pipeline(world, exported):
    design = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
    assert len(exported["story"]) == 12
    for name, catalogue, (args,), card in zip(NAMES, design["tower"], examples(), exported["story"]):
        definition = world.get(name)
        assert definition.status == "promoted"
        assert definition.origin == "invented" and definition.layer == card["def_layer"]
        assert card["layer"] == catalogue["layer"] and card["kind"] == catalogue["kind"]
        assert definition.evidence.scope["size"] > 0
        assert definition.evidence.scope["checked"]["size"] == definition.evidence.scope["size"]
        assert re.fullmatch(r"[0-9a-f]{64}", definition.evidence.scope["checked"]["sha256"])
        assert definition.evidence.method in ("exhaustive", "bounded")
        assert definition.evidence.world_hash == world.world.world_hash()
        if definition.kind == "object":
            assert "canon_total" in definition.evidence.checks
        else:
            assert "unfold_equivalence" in definition.evidence.checks
        actual = world.run(name + ".make" if definition.kind == "object" else name, args, trace=True)
        assert actual.outcome == values.Ok(oracle.expected(name + ".make" if definition.kind == "object" else name, args))
        assert values.decode_outcome(card["examples"][0]["outcome"]) == actual.outcome
        assert card["examples"][0]["steps"] == actual.steps
        rendered = ("true" if actual.outcome.value == values.TRUE else
                    "false" if actual.outcome.value == values.FALSE else
                    oracle.reference.ascii_value(oracle.convert(actual.outcome.value)))
        assert rendered == catalogue["value"]
        assert card["design_decl"] == catalogue["decl"]
        assert card["title"] and card["definition"]


def test_exported_story_notation(world, exported):
    context = {"kinds": {name: world.get(name).kind for name in NAMES},
               "op_arity": {name: len(world.get(name).spec.op_params) for name in NAMES
                            if world.get(name).kind == "combinator"},
               "observation_arity": {"certificate": 2}}
    for card in exported["story"]:
        digest = export_util.body_sha256(world.get(card["name"]).body)
        assert card["body_sha256"] == digest
        if "ascii" in card:
            source = card["decl"]
            parsed = notation.parse_definition(source)
            assert parsed.name == card["name"]
            assert parsed.kind == card["kind"]
            assert parsed.layer == card["def_layer"]
            assert source.endswith(f" L{card['def_layer']}")
            assert card["ascii"] == source
            assert export_util.source_matches(card["ascii"], digest)
        else:
            assert "decl" not in card
        assert card["design_text"] == card["design_decl"]
        for example in card["examples"]:
            args = tuple(kernel.FnRef(value["v"]) if value["t"] == "fn" else values.decode(value)
                         for value in example["inputs"])
            if card["kind"] == "object":
                with pytest.raises(notation.NotationError, match="expected '<'"):
                    notation.parse_expr(example["text"], context)
                assert "ascii" not in example
                continue
            parsed_expr = notation.parse_expr(example["text"], context)
            assert parsed_expr == nodes.Call(card["name"], tuple(nodes.Lit(arg) for arg in args))


def test_failure_and_invalid_certificates(world, exported):
    failure = exported["story"][0]["examples"][1]
    assert values.decode_outcome(failure["outcome"]) == values.Bottom("invalid")
    assert failure["trace"]["outcome"]["bottom"] == "invalid"
    for original, steps in (((1, 1), (0,)), ((2, 1), ()), ((2, 1), (2,))):
        assert world.run("certificate", (hosts.to_card(original), hosts.to_card(steps))).outcome == values.Ok(values.FALSE)


def test_refinements_reject_invalid_bases(world):
    for invalid in (hosts.NIL, values.Card("list", "cons", ("x", hosts.NIL))):
        assert isinstance(world.run("NonEmpty.make", (invalid,)).outcome, values.Bottom)
    for invalid in (hosts.pair(1, 0), hosts.pair(1, -1), hosts.pair("x", 2),
                    hosts.pair(1, True), values.Card("pair", "odd", (1, 2))):
        assert isinstance(world.run("Run.make", (invalid,)).outcome, values.Bottom)


def test_refinements_reject_forged_cards(world):
    for forged in (values.Card("Run", "val", (hosts.pair(1, 0),)),
                   values.Card("NonEmpty", "val", (hosts.NIL,))):
        assert isinstance(world.run(forged.sort + ".base", (forged,)).outcome, values.Bottom)
    assert hosts.list_valid(hosts.to_card((values.Card("Run", "val", (hosts.pair(1, 0),)),)))


@settings(max_examples=16, deadline=None)
@given(st.lists(st.integers(-2, 2), max_size=4))
def test_random_rle_unfold_and_boundary(world, row):
    items = hosts.to_card(row)
    result = world.run("rle", (items,), trace=True)
    assert result.outcome == values.Ok(oracle.expected("rle", (items,)))
    assert unfold_equivalent_calls(result.trace, [Boundary(), Boundary(depth=2), Boundary.unfold_all()]).ok


def test_fresh_first_three_cards():
    library = build_library(limit=3)
    for name, (args,) in zip(NAMES[:3], examples()[:3]):
        target = name + ".make" if name == "NonEmpty" else name
        result = library.run(target, args, trace=True)
        assert result.outcome == values.Ok(oracle.expected(target, args))
        assert result.trace is not None


def test_independent_reference_scope(world):
    rows = [hosts.to_card(row) for size in range(4) for row in product((-1, 0, 1), repeat=size)]
    for row in rows:
        for name in ("reverse", "rle", "sort", "inversions", "trace", "palindrome"):
            assert world.run(name, (row,)).outcome == values.Ok(oracle.expected(name, (row,)))
        trace = world.run("trace", (row,)).outcome.value
        assert world.run("certificate", (row, trace)).outcome == values.Ok(values.TRUE)


def test_large_realistic_count(world):
    row = tuple((position * 17 % 13) - 6 for position in range(512))
    items = hosts.to_card(row)
    assert hosts.from_card(world.run("sort", (items,)).outcome.value) == oracle.reference.sort(row)
    assert world.run("inversions", (items,)).outcome == values.Ok(oracle.reference.inversions(row))


def test_nested_private_operation_is_rejected(world):
    with pytest.raises(PipelineError, match="sealed object private name"):
        world.run("length", ((kernel.FnRef("NonEmpty._pack"),),))


def test_boundaries_and_reproducible_export(world, exported):
    assert exported == json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    assert len(EXPORT_PATH.read_bytes()) < 3_000_000
    for name, (args,) in zip(NAMES, examples()):
        target = name + ".make" if name in ("NonEmpty", "Run") else name
        run = world.run(target, args, trace=True)
        check = unfold_equivalent_calls(run.trace, [Boundary(), Boundary(depth=2), Boundary.unfold_all()])
        assert check.ok, (name, check.problems)
        inline = kernel.evaluate(kernel.inline(nodes.Call(target, tuple(nodes.Lit(arg) for arg in args)), world.scope()),
                                 scope=world.scope())
        assert values.outcome_equal(run.outcome, inline.outcome) and run.steps == inline.steps
    assert all(task["answer_checked"] for task in exported["showcase"])
    assert len(exported["ladder"]) == 5
    assert exported["tower_source"] == "depth"


def test_all_exported_examples_against_oracle(world, exported):
    for card in exported["story"]:
        for example in card["examples"]:
            args = tuple(kernel.FnRef(value["v"]) if value["t"] == "fn" else values.decode(value)
                         for value in example["inputs"])
            target = card["name"] + ".make" if card["kind"] == "object" else card["name"]
            result = world.run(target, args, trace=True)
            expected = oracle.expected(target, args)
            assert result.outcome == (expected if isinstance(expected, values.Bottom) else values.Ok(expected))
            assert result.outcome == values.decode_outcome(example["outcome"])
            assert result.steps == example["steps"] == example["trace"]["steps"]
    assert all(len(card["examples"]) >= 2 for card in exported["story"])


def test_scope_and_operation_families(world, exported):
    by_name = {card["name"]: card for card in exported["story"]}
    for name in ("NonEmpty", "fold", "reverse", "palindrome", "rle", "sort", "inversions", "trace"):
        assert by_name[name]["evidence"]["scope"]["size"] == 121
    for name in ("stable_merge", "merge_count"):
        assert by_name[name]["evidence"]["scope"]["size"] == 400
        assert by_name[name]["evidence"]["scope"]["op_family"] == ["le", "ge"]
    assert by_name["fold"]["evidence"]["scope"]["op_family"] == ["cons", "snoc"]
    assert by_name["certificate"]["evidence"]["scope"]["size"] == 76
    for name in ("stable_merge", "merge_count"):
        for example in by_name[name]["examples"]:
            left, right = (hosts.from_card(values.decode(arg)) for arg in example["inputs"][1:])
            assert left == tuple(sorted(left)) and right == tuple(sorted(right))
            assert all(-1 <= item <= 1 for item in (*left, *right)) if example["inputs"][0]["v"] == "ge" else True
    assert "rle_step" in world.get("rle").depends_on
    assert "stable_merge" in world.get("merge_count").depends_on
    for card in exported["story"]:
        assert all(example["text"] and example["text"].isascii() for example in card["examples"])
    for kind in ("objects", "operations"):
        assert all(item["title"] and item["definition"] for item in exported["layer0"][kind])
    sample = hosts.to_card((2, 1, 2))
    assert world.run("then", (kernel.FnRef("reverse"), kernel.FnRef("reverse"), sample)).outcome == values.Ok(sample)


def test_export_ascii_notation(exported):
    forbidden = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\u211a\u211d\u2115\u2124\U0001d400-\U0001d7ff]")
    def inspect(item, key=""):
        if isinstance(item, dict):
            for name, value in item.items():
                if name == "notation3":  # Notation v3: the generated display block is not machine notation
                    continue
                inspect(value, name)
        elif isinstance(item, list):
            for value in item:
                inspect(value, key)
        elif isinstance(item, str) and not key.endswith("_zh"):
            assert not forbidden.search(item), (key, item)
    inspect(exported)
    assert all(all(ord(char) < 128 for char in example["text"])
               for card in exported["story"] for example in card["examples"])
    assert all(all(ord(char) < 128 for char in card["decl"])
               for card in exported["story"] if "decl" in card)


def test_promotion_requires_evidence():
    library = new_library()
    definition = next(definitions())
    library.write(definition)
    library.check(definition.name)
    library.make_callable(definition.name, ((hosts.to_card((1,)),),))
    with pytest.raises(PipelineError):
        library.promote(definition.name, Contract(guarantees="unverified"))
