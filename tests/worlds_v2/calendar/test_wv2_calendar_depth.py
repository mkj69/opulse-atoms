"""Independent depth oracle, pipeline, cost, and committed-export checks."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes as n
from opulse.atoms import notation, values
from opulse.atoms.boundary import Boundary
from opulse.atoms.observations import check_observation
from opulse.atoms.values import Bottom, Card, Ok, boolean
from opulse.atoms.verify import unfold_equivalent
from opulse.atoms.world import WorldDecl
from opulse.tasks_v2.decl import load, validate
from opulse.worlds_v2.calendar import hosts
from opulse.worlds_v2.calendar.deep import build_library, holiday_scope
from opulse.worlds_v2.calendar.export import build_export, display
from opulse.worlds_v2.calendar.world import decl, new_library
from opulse.worlds_v2.export_util import body_sha256, source_matches

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def calendar_library():
    return build_library()


@pytest.fixture(scope="module")
def calendar_export(calendar_library):
    return build_export(calendar_library)


def oracle():
    path = ROOT / "worlds/catalogue/depth/calendar.py"
    spec = importlib.util.spec_from_file_location("calendar_depth_oracle", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gregorian_date_scope_and_boundaries():
    dates = hosts.dates()
    reference = oracle()
    assert len(dates) == 36525
    for date in dates:
        assert hosts.weekday(date) == reference.weekday(reference.Date(*date.fields))
    assert hosts.next_date(dates[-1]) == Bottom("range")
    assert hosts.next_date(hosts.to_card(2000, 2, 28)) == hosts.to_card(2000, 2, 29)
    assert hosts.to_card(2001, 2, 29) == Bottom("invalid")


def test_first_three_cards_build_fresh():
    library = build_library(limit=3)
    assert [library.get(name).status for name in ("LeapDay", "week_later", "workday")] == [
        "promoted", "promoted", "promoted"]
    assert library.run("workday", (hosts.to_card(2000, 2, 29),)).outcome == Ok(boolean(True))


@settings(max_examples=12, deadline=None)
@given(year=st.integers(min_value=2000, max_value=2099),
       month=st.integers(min_value=1, max_value=12),
       ordinal=st.integers(min_value=1, max_value=5),
       weekday=st.integers(min_value=0, max_value=6))
def test_nth_weekday_unfolds_on_random_months(calendar_library, year, month, ordinal, weekday):
    run = calendar_library.run("nth_weekday", (year, month, ordinal, weekday), trace=True)
    assert unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0), Boundary(depth=1))).ok
    assert calendar_library.run("nth_weekday", (year, month, ordinal, weekday)).outcome == run.outcome


def test_refined_objects_reject_invalid_values(calendar_library):
    library = calendar_library
    for date in (hosts.to_card(2000, 2, 28), hosts.to_card(2001, 3, 1),
                 hosts.to_card(2032, 11, 25)):
        assert not isinstance(library.run("LeapDay.make", (date,)).outcome, Ok)
    start = hosts.to_card(2032, 2, 1)
    for end in (hosts.to_card(2032, 2, 28), hosts.to_card(2032, 3, 1),
                hosts.to_card(2032, 1, 31)):
        assert not isinstance(library.run("MonthSpan.make", (hosts.pair(start, end),)).outcome, Ok)
    for date in (hosts.to_card(2032, 11, 24), hosts.to_card(2032, 11, 26),
                 hosts.to_card(2032, 2, 28)):
        assert not isinstance(library.run("Holiday.make", (date,)).outcome, Ok)
    fake_span = Card("MonthSpan", "other", (hosts.pair(start, hosts.to_card(2032, 2, 29)),))
    assert library.run("MonthSpan.base", (fake_span,)).outcome == Bottom("invalid")
    forged = Card("MonthSpan", "val", (hosts.pair(start, hosts.to_card(2032, 2, 28)),))
    assert library.run("MonthSpan.base", (forged,)).outcome == Bottom("invalid")


def test_core_observation_checker_rejects_reconstructed_policy(calendar_library):
    problems = set(check_observation(calendar_library.get("open_day"), calendar_library))
    assert problems == {f"operation {name} may read or change truth" for name in (
        "holiday_match", "week_later", "next_date",
        *(f"weekday_is_{weekday}" for weekday in range(7)))}


def test_twelve_kernel_examples_equal_the_design(calendar_export):
    reference = oracle()
    source = json.loads((ROOT / "worlds/catalogue/depth/calendar.json").read_text(encoding="utf-8"))
    export = calendar_export
    assert len(export["story"]) == len(source["tower"]) == 12
    for card, design, expected in zip(export["story"], source["tower"], reference.cases()):
        assert (card["tower_position"], card["kind"]) == (design["layer"], design["kind"])
        assert card["layer"] == card["def_layer"]
        assert card["status"] == "promoted" and card["evidence"]["scope"]["size"] >= 50
        assert card["evidence"]["scope"]["checked"]
        example = card["examples"][0]
        assert display(values.decode_outcome(example["outcome"]).value) == reference._value(expected)
        assert example["steps"] == example["trace"]["steps"]
    assert [task["answer"] for task in export["showcase"]] == [
        reference._value(answer) for answer in (reference.showcase_compute(),
                                                reference.showcase_invert(), reference.showcase_decide())]
    assert all(task["answer_checked"] for task in export["showcase"])


def test_failures_sealed_objects_and_slot_families(calendar_library, calendar_export):
    library = calendar_library
    assert library.get("MonthSpan").spec.interface == ("MonthSpan.make", "MonthSpan.base")
    first = hosts.to_card(2000, 2, 29)
    assert library.run("LeapDay.make", (first,)).outcome.value.sort == "LeapDay"
    assert library.run("LeapDay.make", (hosts.to_card(2001, 2, 28),)).outcome == Bottom("invalid")
    assert library.run("Holiday.make", (hosts.to_card(2032, 11, 25),)).outcome.value.sort == "Holiday"
    assert library.run("Holiday.make", (hosts.to_card(2032, 11, 24),)).outcome == Bottom("invalid")
    assert library.run("week_later", (hosts.to_card(2099, 12, 27),)).outcome == Bottom("range")
    assert library.run("week_later", (first,), fuel=0).outcome.resource == "fuel"
    assert values.decode_outcome(calendar_export["story"][1]["examples"][1]["outcome"]) == Bottom("range")
    for name in ("seek", "month_fold"):
        evidence = library.get(name).evidence
        assert evidence.method == "bounded"
        assert evidence.scope["checked"]
        assert all(len(family) >= 2 for family in evidence.scope["op_family"].values())
        assert "fixed_ops" not in evidence.scope


def test_all_additional_examples_against_oracle(calendar_export):
    reference = oracle()
    examples = {entry["name"]: entry["examples"][1:] for entry in calendar_export["story"]}
    expected = {
        "week_later": [Bottom("range"), reference.Date(2004, 3, 7)],
        "workday": [True],
        "seek": [reference.Date(2000, 3, 7)],
        "weekday_count": [reference.weekday_count(2032, 3)],
        "Holiday": [reference.Holiday(reference.Date(2032, 1, 19))],
        "open_day": [False],
    }
    for name, outcomes in expected.items():
        for example, value in zip(examples[name], outcomes):
            actual = values.decode_outcome(example["outcome"])
            if isinstance(value, Bottom):
                assert actual == value
            else:
                assert isinstance(actual, Ok)
                assert display(actual.value) == reference._value(value)
            assert example["steps"] == example["trace"]["steps"]


def test_i1_i2_i3_i4_and_locked_declaration(calendar_library):
    library = calendar_library
    assert not validate(load(ROOT / "worlds/decl/v2/calendar@1.json"))
    assert WorldDecl.from_dict(decl().to_dict()).to_dict() == decl().to_dict()
    for spec in decl().combinators["library"]:
        given = library.get(spec["name"])
        assert given.origin == "given" and given.status == "promoted"
        assert given.spec.to_dict() == spec
    assert len(new_library().atoms) == len(decl().operations) + len(decl().observation["probes"])
    assert len(library.derived_world().promoted) >= 12
    for name, args in (("week_later", (hosts.to_card(2032, 2, 29),)),
                       ("nth_weekday", (2032, 11, 4, 3)), ("settle", (2032, 12))):
        run = library.run(name, args, trace=True)
        assert unfold_equivalent(run.trace, (Boundary(), Boundary(depth=0), Boundary(depth=1))).ok
        assert library.run(name, args).outcome == run.outcome
        assert library.run(name, args).steps == run.steps
    for (date,) in holiday_scope():
        assert library.run("open_day", (date,)).outcome == Ok(boolean(
            hosts.weekday(date) < 5 and
            library.run("holiday_match", (date,)).outcome == Ok(boolean(False))))
    assert library.run("settle", (2032, 12)).outcome == Ok(hosts.to_card(2032, 12, 30))


def test_export_is_current_and_ascii(calendar_export):
    exported = calendar_export
    stored = json.loads((ROOT / "docs/assets/data/worlds_v2/calendar.json").read_text(encoding="utf-8"))
    assert stored == exported
    forbidden = re.compile("[\u27e8\u27e9\u27e6\u27e7\u2985\u2986\u2660\u2666\u25cb\u25c9\U0001d400-\U0001d7ff]")

    def check(item, key=""):
        if isinstance(item, dict):
            for name, value in item.items():
                check(value, name)
        elif isinstance(item, list):
            for value in item:
                check(value, key)
        elif isinstance(item, str) and not key.endswith("_zh"):
            assert not forbidden.search(item), (key, item)
            if key in ("decl", "text", "symbol", "answer"):
                assert item.isascii(), (key, item)

    check({key: value for key, value in exported.items() if key != 'notation3'})


def test_story_ascii_declarations_and_evaluated_expressions(calendar_library, calendar_export):
    design = json.loads((ROOT / "worlds/catalogue/depth/calendar.json").read_text(encoding="utf-8"))
    unrepresentable = {"LeapDay.make", "Holiday.make", "seek"}
    for row, original in zip(calendar_export["story"], design["tower"]):
        digest = body_sha256(calendar_library.get(row["name"]).body)
        assert row["body_sha256"] == digest
        if "ascii" in row:
            source = row["ascii"]
            definition = notation.parse_definition(source)
            assert definition.name == row["name"]
            assert definition.kind == row["kind"]
            assert source.endswith(f" L{row['def_layer']}")
            assert row["decl"] == source
            assert source_matches(source, digest)
        else:
            assert "decl" not in row
        assert row["design_decl"] == row["design_text"] == original["decl"]
        for example in row["examples"]:
            expected = n.Call("Holiday.make" if row["name"] == "Holiday" else
                              "LeapDay.make" if row["name"] == "LeapDay" else
                              "month_span" if row["name"] == "MonthSpan" else row["name"],
                              tuple(n.Lit(values.decode(value)) for value in example["inputs"]))
            if expected.fn in unrepresentable:
                with pytest.raises(notation.NotationError):
                    notation.parse_expr(example["text"], calendar_library)
            else:
                assert notation.parse_expr(example["text"], calendar_library) == expected
