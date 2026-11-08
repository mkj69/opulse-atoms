"""Independent regressions for refused learner definitions."""

from dataclasses import replace

import pytest
from atoms_kinds.ascii import parse
from atoms_kinds.harness import discard_refused, grade, save
from atoms_kinds.world import make_library
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms.values import Ok


def test_discard_refused_removes_checked_draft_and_releases_name():
    library = make_library("K1")
    definitions, _ = parse(
        "op helper(a: Int) -> Int = add(a, 1)\n"
        "save helper\n"
        "op solve(a: Int) -> Int = helper(a)"
    )
    library.write(replace(definitions[0], layer=1))
    library.check("helper")
    discard_refused(library, "helper")
    assert "helper" not in library.definitions
    assert library.scope().resolve("helper") is None
    assert save(library, definitions, (2,))[0]["status"] == "callable"


@given(st.integers(min_value=-100, max_value=100))
def test_refused_definition_can_be_corrected_on_next_attempt(value):
    library = make_library("K1")
    invalid, _ = parse(
        "op helper(a: Int) -> Int = missing(a)\n"
        "save helper\n"
        "op solve(a: Int) -> Int = helper(a)"
    )
    assert "unresolved call: missing" in save(library, invalid, (value,))[0]["refusal"]
    assert "helper" not in library.definitions

    corrected, _ = parse(
        "op helper(a: Int) -> Int = add(a, 1)\n"
        "save helper\n"
        "op solve(a: Int) -> Int = helper(a)"
    )
    assert save(library, corrected, (value,))[0]["status"] == "callable"
    assert library.run("helper", (value,)).outcome == Ok(value + 1)
    assert "definition already exists: helper" in save(library, corrected, (value,))[0]["refusal"]


def test_refused_object_cannot_be_used_in_an_answer():
    library = make_library("K2")
    rejected, _ = parse(
        "obj Odd = <num: Int, den: Int> where true "
        "canon Pair<add(Pair.num(x), 1), Pair.den(x)> sealed (make, num, den)\n"
        "save Odd\n"
        "op solve(a: Int) -> Int = Odd.num(Odd.make(Pair<a, 4>))"
    )
    assert "canon_idempotent" in save(library, rejected, (2, 4))[0]["refusal"]
    assert "Odd" not in library.definitions
    assert library.scope().resolve("Odd.make") is None
    _, (_, _, answer) = parse("op solve(a: Int) -> Int = Odd.num(Odd.make(Pair<a, 4>))")
    task = {"family": "compare", "hidden_cases": [{"args": [2], "expected": [4]}]}
    with pytest.raises(ValueError, match="unknown operation"):
        grade(task, (answer,), library, 200_000)


def test_refused_object_cannot_be_used_by_later_definition():
    library = make_library("K2")
    definitions, _ = parse(
        "obj Odd = <num: Int, den: Int> where true "
        "canon Pair<add(Pair.num(x), 1), Pair.den(x)> sealed (make, num, den)\n"
        "save Odd\n"
        "op helper(a: Int) -> Int = Odd.num(Odd.make(Pair<a, 4>))\n"
        "save helper\n"
        "op solve(a: Int) -> Int = helper(a)"
    )
    statuses = save(library, definitions, (2,))
    assert "canon_idempotent" in statuses[0]["refusal"]
    assert statuses[1]["status"] == "refused"
    assert "Odd" not in library.definitions
    assert "helper" not in library.definitions


def test_object_refused_by_verification_can_be_corrected():
    library = make_library("K2")
    rejected, _ = parse(
        "obj Odd = <num: Int, den: Int> where true "
        "canon Pair<add(Pair.num(x), 1), Pair.den(x)> sealed (make, num, den)\n"
        "save Odd\n"
        "op solve(a: Int) -> Int = a"
    )
    assert "canon_idempotent" in save(library, rejected, (2,))[0]["refusal"]
    corrected, _ = parse(
        "obj Odd = <num: Int, den: Int> where true "
        "canon Pair<Pair.num(x), Pair.den(x)> sealed (make, num, den)\n"
        "save Odd\n"
        "op solve(a: Int) -> Int = Odd.num(Odd.make(Pair<a, 4>))"
    )
    assert save(library, corrected, (2,))[0]["status"] == "promoted"
    assert "definition already exists: Odd" in save(library, corrected, (2,))[0]["refusal"]


def test_grading_requires_callable_core_status():
    library = make_library("K1")
    definitions, (_, _, answer) = parse(
        "op helper(a: Int) -> Int = add(a, 1)\n"
        "save helper\n"
        "op solve(a: Int) -> Int = helper(a)"
    )
    library.write(replace(definitions[0], layer=1))
    task = {"family": "compare", "hidden_cases": [{"args": [2], "expected": [3]}]}
    for status in ("written", "checked"):
        assert library.get("helper").status == status
        with pytest.raises(ValueError, match="unknown operation"):
            grade(task, (answer,), library, 200_000)
        if status == "written":
            library.check("helper")
    library.make_callable("helper", ((2,),))
    assert grade(task, (answer,), library, 200_000)[0]
