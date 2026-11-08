"""World exporters must not leave a raised recursion limit behind.

A permanently raised limit lets later deep recursion on the main thread run past the
native C stack and crash the interpreter instead of raising RecursionError. The
automata example() leak crashed a later test_world_challenges test in a
reverse-order single-process run.
"""

import os
import sys

import pytest

from opulse.worlds_v2 import export_util
from opulse.worlds_v2.automata import export as automata_export
from opulse.worlds_v2.automata.story import build_library as automata_library
from opulse.worlds_v2.geometry import export as geometry_export


def test_automata_example_restores_recursion_limit():
    library = automata_library()
    _, (expression, text) = next(iter(automata_export.extra_examples().items()))
    before = sys.getrecursionlimit()
    result = automata_export.example(expression, text, library)
    assert sys.getrecursionlimit() == before
    assert result["trace"]


def test_geometry_export_scopes_recursion_limit(monkeypatch):
    seen = []

    def body(library=None):
        seen.append(sys.getrecursionlimit())
        raise RuntimeError("stop after the limit check")

    monkeypatch.setattr(geometry_export, "_build_export_unscoped", body)
    before = sys.getrecursionlimit()
    with pytest.raises(RuntimeError):
        geometry_export.build_export()
    assert seen and seen[0] >= 10000
    assert sys.getrecursionlimit() == before


@pytest.mark.skipif(os.environ.get("OPULSE_RUN_SLOW") != "1", reason="fresh exports take minutes")
@pytest.mark.parametrize("module", [geometry_export, automata_export], ids=["geometry", "automata"])
def test_build_export_restores_recursion_limit(module):
    before = sys.getrecursionlimit()
    module.build_export()
    assert sys.getrecursionlimit() == before


def test_recursion_limit_at_least_restores_after_error():
    before = sys.getrecursionlimit()
    with pytest.raises(RuntimeError):
        with export_util.recursion_limit_at_least(before + 5000):
            assert sys.getrecursionlimit() == before + 5000
            raise RuntimeError("boom")
    assert sys.getrecursionlimit() == before
    with export_util.recursion_limit_at_least(10):
        assert sys.getrecursionlimit() == before
    assert sys.getrecursionlimit() == before
