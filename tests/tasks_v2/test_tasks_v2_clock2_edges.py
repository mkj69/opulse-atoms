"""Clock declaration and entered operation edges (atoms-v2, sections 4 and 6)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms.values import Card, Ok
from opulse.tasks_v2 import templates
from opulse.tasks_v2.decl import find, validate


@pytest.fixture(scope="module")
def clock_library():
    return templates.library("clock@2")


def test_clock_declaration_builds_and_uses_x_for_refinement(clock_library):
    declaration = find("clock", 2)
    assert validate(declaration) == []
    hour = next(obj for obj in declaration.objects if obj.name == "hour")
    assert hour.canon["args"] == [{"node": "Var", "name": "x"}]
    for name in ("int_mod_twelve", "nonnegative", "below_twelve"):
        assert name in clock_library.scope().atoms


@pytest.mark.parametrize(("operation", "arguments", "expected"), (
    ("add", (14, 0), 2),
    ("add", (-4, 0), 8),
    ("mul", (5, 5), 1),
))
def test_clock_arithmetic_through_declared_edges(clock_library, operation, arguments, expected):
    scope = clock_library.scope()
    assert scope.resolve(operation).params == ("a", "b")
    for index in range(2):
        assert f"__opulse_edge_{operation}_{index}" in scope.atoms
    assert f"__opulse_edge_{operation}_output" in scope.atoms
    result = kernel.call(operation, arguments, scope)
    assert result.outcome == Ok(Card("hour", "val", (expected,)))
    assert clock_library.run(operation, arguments).outcome == result.outcome


def test_clock_result_can_be_reused_as_an_input(clock_library):
    hour = clock_library.run("add", (14, 0)).outcome
    assert hour == Ok(Card("hour", "val", (2,)))
    assert clock_library.run("mul", (hour.value, 7)).outcome == Ok(Card("hour", "val", (2,)))


@settings(max_examples=30, deadline=None)
@given(left=st.integers(min_value=-1000, max_value=1000),
       right=st.integers(min_value=-1000, max_value=1000),
       operation=st.sampled_from(("add", "mul")))
def test_clock_edges_normalize_inputs_and_outputs(clock_library, left, right, operation):
    normalized_left, normalized_right = left % 12, right % 12
    expected = (normalized_left + normalized_right if operation == "add" else
                normalized_left * normalized_right) % 12
    assert clock_library.run(operation, (left, right)).outcome == Ok(Card("hour", "val", (expected,)))
