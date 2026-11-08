"""The bridge catalogue is made by the real core pipeline."""

import json
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms.library import PipelineError
from opulse.atoms.spec import Contract
from opulse.atoms.values import Bottom, Card, Ok
from opulse.worlds_v2 import export_util
from opulse.worlds_v2.bridges.export import EXPORT_PATH, build_export
from opulse.worlds_v2.bridges.world import (
    BEAT_SPEC,
    FRAC_SPEC,
    beat_libraries,
    beat_request,
    beat_to_row,
    beat_values,
    check_all_rotations,
    definition,
    frac_library,
    frac_request,
    int_product,
    pair_domain,
    rotate_one,
    shift_one,
)
from opulse.worlds_v2.integer import hosts as integers
from opulse.worlds_v2.integer import story as integer_story
from opulse.worlds_v2.pixels import hosts as pixels
from opulse.worlds_v2.rhythm import hosts as rhythm


def test_beat_commutes_on_all_residues_and_core_checks_interface():
    library, _ = beat_libraries()
    library.write(definition(BEAT_SPEC))
    library.check("beat_row")
    library.make_callable("beat_row", ((rhythm.make_rhythm((2, 0, 1)),),))
    values = beat_values()
    assert check_all_rotations(values) == sum(len(value.fields) for value in values)
    request = beat_request()
    library.verify("beat_row", request)
    assert library.get("beat_row").evidence.scope["pairs_checked"] == len(request.domain)
    assert library.get("beat_row").evidence.scope["checked"]["size"] == len(request.domain)


def test_beat_uses_attached_pixel_world():
    library, context = beat_libraries()
    library.write(definition(BEAT_SPEC))
    assert context.source_lib is library
    assert context.target_lib.world.world == "pixels"
    assert library.local_scope().resolve("shift_one") is None
    assert context.target_lib.local_scope().resolve("shift_one") is not None
    assert library.scope().resolve("shift_one") is not None


def test_fraction_add_commutes_on_bounded_pairs():
    library = frac_library()
    library.write(definition(FRAC_SPEC))
    library.check("to_frac")
    library.make_callable("to_frac", ((integers.pair(1, 1),),))
    library.verify("to_frac", frac_request())
    assert library.get("to_frac").evidence.scope["pairs_checked"] == 681
    assert library.get("to_frac").evidence.scope["skipped"] == 48
    assert library.get("to_frac").evidence.scope["checked"]["size"] == 27


@pytest.mark.parametrize("forgery", (
    Card("frac", "val", (integers.pair(2, 2),)),
    Card("frac", "val", (integers.pair(0, 2),)),
    Card("frac", "val", (integers.pair(1, -2),)),
    Card("frac", "val", (integers.pair(1, 0),)),
    Card("frac", "val", (integers.pair(True, 2),)),
    Card("frac", "val", (integers.pair(1, "2"),)),
    Card("frac", "val", (Card("pair", "other", (1, 2)),)),
    Card("frac", "val", (integers.pair(1, 2), integers.pair(2, 3))),
    Card("frac", "val", ()),
))
def test_frac_add_rejects_noncanonical_and_malformed_cards(callable_fractions, forgery):
    valid = integer_story.canonical_reference(1, 3)
    assert callable_fractions.run("frac_add", (forgery, valid)).outcome == Bottom("invalid")
    assert callable_fractions.run("frac_add", (valid, forgery)).outcome == Bottom("invalid")


def test_fraction_interface_uses_independent_arithmetic(callable_fractions, monkeypatch):
    def forbidden(*args):
        raise AssertionError("interface must not call the reference constructor")

    monkeypatch.setattr(integer_story, "canonical_reference", forbidden)
    left, right = integers.pair(1, 2), integers.pair(1, 2)
    assert int_product(2, 2) == 4
    source = callable_fractions.run("pair_add", (left, right)).outcome
    assert source == Ok(integers.pair(1, 1))
    mapped = callable_fractions.run("to_frac", (source.value,)).outcome
    first = callable_fractions.run("to_frac", (left,)).outcome.value
    second = callable_fractions.run("to_frac", (right,)).outcome.value
    assert callable_fractions.run("frac_add", (first, second)).outcome == mapped


def test_beat_hosts_reject_forged_invented_cards():
    forged_accent = Card("accented", "val", (rhythm.make_rhythm((2, 0)),))
    forged_island = Card("Island", "val", (pixels.to_card(("#",)),))
    assert rotate_one(forged_accent) == Bottom("invalid")
    assert beat_to_row(forged_accent) == Bottom("invalid")
    assert shift_one(forged_island) == Bottom("invalid")


@pytest.mark.parametrize("name,value,expected", (
    ("beat_row", rhythm.make_rhythm((0,) * 9), "outside_domain"),
    ("to_frac", integers.pair(3, 0), "outside_domain"),
))
def test_outside_domain_is_a_real_failure(name, value, expected):
    if name == "beat_row":
        library, _ = beat_libraries()
        spec = BEAT_SPEC
    else:
        library = frac_library()
        spec = FRAC_SPEC
    library.write(definition(spec))
    library.check(name)
    library.make_callable(name, ((rhythm.make_rhythm((1,)) if name == "beat_row"
                                  else integers.pair(1, 1),),))
    assert library.run(name, (value,)).outcome == Bottom(expected)


@pytest.mark.parametrize("name", ("beat_row", "to_frac"))
def test_promotion_refused_without_evidence(name):
    library = beat_libraries()[0] if name == "beat_row" else frac_library()
    spec = BEAT_SPEC if name == "beat_row" else FRAC_SPEC
    library.write(definition(spec))
    library.check(name)
    library.make_callable(name, ((rhythm.make_rhythm((1,)) if name == "beat_row"
                                  else integers.pair(1, 1),),))
    with pytest.raises(PipelineError, match="verified status"):
        library.promote(name, Contract("not yet verified"))


@given(st.lists(st.integers(0, 2), min_size=1, max_size=8), st.integers(-50, 50))
def test_random_rhythm_rotations_commute(cells, offset):
    value = rhythm.make_rhythm(tuple(cells))
    row = pixels.from_card(beat_to_row(value))[0]
    shift = offset % len(cells)
    assert beat_to_row(rhythm.left(value, offset)) == pixels.to_card((row[shift:] + row[:shift],))
    if shift == 1:
        assert shift_one(beat_to_row(value)) == beat_to_row(rhythm.left(value, 1))


@pytest.fixture(scope="module")
def callable_fractions():
    library = frac_library()
    library.write(definition(FRAC_SPEC))
    library.check("to_frac")
    library.make_callable("to_frac", ((integers.pair(1, 1),),))
    return library


@given(st.integers(-40, 40), st.integers(1, 3),
       st.integers(-40, 40), st.integers(1, 3))
def test_random_fraction_add_commutes(callable_fractions, left, left_den, right, right_den):
    first = integers.pair(left, left_den)
    second = integers.pair(right, right_den)
    summed = callable_fractions.run("pair_add", (first, second)).outcome.value
    expected = Fraction(left, left_den) + Fraction(right, right_den)
    assert summed == integers.pair(expected.numerator, expected.denominator)
    first_frac = callable_fractions.run("to_frac", (first,)).outcome.value
    second_frac = callable_fractions.run("to_frac", (second,)).outcome.value
    target = callable_fractions.run("frac_add", (first_frac, second_frac)).outcome
    assert target == Ok(integer_story.frac(expected.numerator, expected.denominator))
    translated_sum = callable_fractions.run("to_frac", (summed,)).outcome
    if not pair_domain(summed):
        assert translated_sum == Bottom("outside_domain")
        return
    assert translated_sum == target


def test_export_matches_fresh_build():
    from opulse.notation3.export import add_notation3

    assert json.loads(EXPORT_PATH.read_text(encoding="utf-8")) == add_notation3(
        build_export(), 'worlds_v2')


def test_published_bridge_source_matches_stored_body():
    from opulse.worlds_v2.bridges.world import build_library

    beats, fractions = build_library()
    libraries = {"beat_row": beats, "to_frac": fractions}
    for row in build_export()["story"]:
        digest = export_util.body_sha256(libraries[row["name"]].get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            assert row["ascii"] == row["decl"]
            assert export_util.source_matches(row["ascii"], digest)
        else:
            assert "decl" not in row


def test_export_failure_examples_are_traced_and_outside_domain():
    rows = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    assert {row["symbol"] for row in rows} == {"~beat_row", "~to_frac"}
    for row in rows:
        failure = row["examples"][-1]
        assert failure["outcome"] == {"bottom": "outside_domain"}
        assert failure["trace"]["children"][0]["name"] == row["name"]
        assert failure["trace"]["steps"] == failure["steps"]


def test_fraction_translation_calls_the_integer_constructor():
    rows = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))["story"]
    fraction = next(row for row in rows if row["name"] == "to_frac")
    bridge_call = fraction["examples"][0]["trace"]["children"][0]
    assert any(child["name"] == "frac.make" for child in bridge_call["children"])
