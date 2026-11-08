"""Typed ASCII definitions and operation-only experiment declarations."""

import pytest
from atoms_mul.kernel import (
    AmlSyntaxError,
    Library,
    check_program,
    format_def,
    load_world,
    parse_program,
    size,
)
from atoms_mul.kernel.core_library import CoreMirror
from hypothesis import given
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.atoms.library import PipelineError
from opulse.atoms.spec import CombinatorSpec, Definition, ObjectSpec


@pytest.mark.parametrize("text", [
    "def rep(n, x) = add(n, x)",
    "op rep(n) -> Nat = n",
    "op rep(n: Int) -> Nat = n",
    "op rep(n: Nat) -> Int = n",
    "op rep(n: Nat) Nat = n",
])
def test_bad_syntax_is_always_aml_syntax_error(text):
    with pytest.raises(AmlSyntaxError):
        parse_program(text)


def test_old_keyword_suggests_typed_op_definition():
    with pytest.raises(AmlSyntaxError, match=r"use op NAME\(a: Nat\) -> Nat = "):
        parse_program("def answer(x) = x")


@pytest.mark.parametrize("source,fragment", [
    ("op f(n: Bool) -> Nat = add(n, 1)", "argument 1 of add expects Nat, got Bool"),
    ("op f(n: Nat) -> Bool = succ(n)", "result of f expects Bool, got Nat"),
    ("op f(n: Nat) -> Nat = if n then 1 else 2", "if condition must be Bool"),
    ("op f(n: Nat) -> Nat = if is_zero(n) then n else is_zero(n)", "if branches must have the same sort"),
    ("op f(n: Nat) -> Nat = if is_zero(n) then n else 1 op g(n: Nat) -> Nat = f(is_zero(n))",
     "argument 1 of f expects Nat, got Bool"),
])
def test_sort_errors_are_visible(source, fragment):
    assert any(fragment in error for error in check_program(parse_program(source), load_world("B"), Library()))


@given(st.lists(st.sampled_from(("Nat", "Bool")), max_size=4))
def test_annotated_format_round_trips_without_changing_size(sorts):
    params = ", ".join(f"p{index}: {sort}" for index, sort in enumerate(sorts))
    source = f"op test({params}) -> Nat = 0"
    definition = parse_program(source).defs[0]
    assert format_def(definition) == source
    assert parse_program(format_def(definition)).defs[0] == definition
    assert size(definition) == 2 + len(sorts)


def test_library_layer_listing_and_saved_bool_signature():
    library = Library()
    first = parse_program("op positive(n: Nat) -> Bool = lt(0, n) save positive")
    library.add_from_program(first, ["positive"], "task")
    assert library.listing() == "op positive(n: Nat) -> Bool = lt(0, n) L1"
    assert check_program(parse_program("op test(n: Nat) -> Bool = positive(n)"), load_world("B"), library) == []
    assert check_program(parse_program("op test(n: Nat) -> Nat = positive(n)"), load_world("B"), library) == [
        "result of test expects Nat, got Bool"
    ]


def test_core_mirror_accepts_typed_bool_result():
    library = Library()
    program = parse_program("op positive(n: Nat) -> Bool = lt(0, n) save positive")
    entries = library.add_from_program(program, program.saves, "task")
    report, = CoreMirror("B").mirror(entries)
    assert report["core_status"] == "callable"
    assert report["problems"] == []


@pytest.mark.parametrize("group", list("ABC"))
@pytest.mark.parametrize("kind,spec", [
    ("object", ObjectSpec("Number", "constant", body=nodes.Lit(1))),
    ("combinator", CombinatorSpec("twice", ("x",), (), nodes.Var("x"))),
])
def test_core_refuses_closed_inventions(group, kind, spec):
    mirror = CoreMirror(group)
    definition = Definition(spec.name, kind, "invented", 1, (), spec, spec.body)
    with pytest.raises(PipelineError, match=f"kind {kind} is closed"):
        mirror.library.write(definition)
