"""Descriptive cost-only Pascal recursion, separate from the primary forms."""

import math
from dataclasses import replace
from pathlib import Path

import pytest
from atoms_boundary.memo import compare_runs, memo_scope
from atoms_boundary.memo_cost import (
    HEADER,
    SOURCE,
    build_cost_tower,
    cost_inputs,
    cost_rows,
    main,
    memo_hits,
)
from atoms_mul.kernel import parse_program
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import nodes
from opulse.atoms.kernel import CallNode
from opulse.atoms.values import Ok, Unknown


@pytest.fixture(scope="module")
def tower():
    return build_cost_tower()


def test_seeded_inputs_cover_twelve_unique_interior_cells():
    assert len(cost_inputs()) == len(set(cost_inputs())) == 12
    assert set(cost_inputs()) == {(n, k) for n in range(6, 9) for k in range(2, n - 1)}
    assert cost_inputs()[:3] == [(8, 4), (6, 2), (8, 2)]


def test_pascal_source_compiled_checked_and_promoted_on_recorded_scopes(tower):
    assert [entry.name for entry in parse_program(SOURCE).defs] == ["choose", "paths"]
    assert isinstance(tower.get("choose").body, nodes.Rec)
    assert tower.get("choose").body.memo is False
    assert tower.get("paths").layer == tower.get("choose").layer + 1
    assert "score" not in tower.scope().defns
    for name, size in (("choose", 45), ("paths", 12)):
        entry = tower.get(name)
        assert entry.status == "promoted"
        assert entry.evidence.method == "exhaustive"
        assert entry.evidence.scope["size"] == entry.evidence.scope["checked"]["size"] == size
        assert "unfold_equivalence" in entry.evidence.checks
        assert entry.contract is not None
    cached = memo_scope(tower.scope())
    assert cached.defns["choose"].body == replace(tower.scope().defns["choose"].body,
                                                   memo=True)
    assert cached.defns["paths"] == tower.scope().defns["paths"]


def test_every_cost_item_has_equal_outcomes_and_charged_steps_with_savings(tower):
    ordinary = tower.scope()
    cached = memo_scope(ordinary)
    for args in cost_inputs():
        plain, memo = compare_runs(ordinary, cached, args, name="paths", trace=True)
        assert plain.outcome == memo.outcome == Ok(math.comb(*args))
        assert plain.steps == memo.steps == plain.work
        assert memo.work < plain.work
        assert memo_hits(memo.trace) > 0
    rows = cost_rows(tower)
    assert len(rows) == 12
    assert sum(row[6] < row[5] for row in rows) >= 10
    assert all(row[7] > 0 for row in rows)


@settings(max_examples=40, deadline=None)
@given(n=st.integers(min_value=2, max_value=8),
       k=st.integers(min_value=0, max_value=8),
       fuel=st.one_of(st.none(), st.integers(min_value=0, max_value=200)))
def test_pascal_random_inputs_preserve_unfolding_even_with_fuel(tower, n, k, fuel):
    if k > n:
        return
    plain, memo = compare_runs(tower.scope(), memo_scope(tower.scope()), (n, k),
                               name="paths", fuel=fuel)
    assert plain.outcome == memo.outcome
    assert plain.steps == memo.steps
    assert memo.work <= plain.work


def test_cost_rows_rejects_mismatched_reference(tower, monkeypatch):
    from atoms_boundary import memo_cost

    assert cost_rows(tower, [(6, 3)])[0][1:4] == (6, 3, "Ok(20)")
    monkeypatch.setattr(memo_cost.math, "comb", lambda *_: 999)
    with pytest.raises(ValueError, match="Pascal reference differs"):
        cost_rows(tower, [(6, 3)])


def test_cost_rows_rejects_missing_memo_savings(tower, monkeypatch):
    from atoms_boundary import memo_cost

    monkeypatch.setattr(memo_cost, "memo_scope", lambda scope: scope)
    with pytest.raises(ValueError, match="at least 10 of 12"):
        cost_rows(tower)


def test_memo_hits_excludes_replayed_subtrees():
    child = CallNode("choose", "operation", 1, False, (0,), (), Unknown("pending"), 0,
                     memo_hit=True)
    cached = CallNode("choose", "operation", 1, False, (), (), Unknown("pending"), 0,
                      [child], memo_hit=True)
    ordinary = replace(cached, memo_hit=False)
    assert memo_hits(None) == 0
    assert memo_hits(cached) == memo_hits(ordinary) == 1


def test_cost_snapshot_replays_deterministically(tower, capsys):
    snapshot = Path(__file__).resolve().parents[1] / "items" / "memo_pascal_cost.csv"
    main()
    output = capsys.readouterr().out
    assert output.encode("ascii") == snapshot.read_bytes()
    assert output.splitlines()[0] == ",".join(HEADER)
