"""Secondary memo accounting without changing the primary boundary experiment."""

from dataclasses import replace
from pathlib import Path

import pytest
from atoms_boundary.items import frozen_inputs, items
from atoms_boundary.memo import compare_runs, main, memo_scope, work_rows
from atoms_boundary.tower import build_tower
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel, nodes
from opulse.atoms.values import Ok, Unknown


@pytest.fixture(scope="module")
def tower():
    return build_tower()


def test_memo_scope_switches_only_recursive_binders(tower):
    plain = tower.scope()
    cached = memo_scope(plain)
    assert isinstance(plain.defns["mul"].body, nodes.Rec)
    assert plain.defns["mul"].body.memo is False
    assert cached.defns["mul"].body == replace(plain.defns["mul"].body, memo=True)
    assert {name: definition for name, definition in cached.defns.items() if name != "mul"} == {
        name: definition for name, definition in plain.defns.items() if name != "mul"}
    assert cached.atoms == plain.atoms
    assert cached.fast_paths == plain.fast_paths
    with pytest.raises(ValueError, match="no recursive definitions"):
        memo_scope(kernel.DictScope())


def test_all_frozen_items_match_outcomes_steps_and_unfolded_traces(tower):
    plain_scope = tower.scope()
    cached_scope = memo_scope(plain_scope)
    for task in items(tower):
        plain, cached = compare_runs(plain_scope, cached_scope, task["args"], trace=True)
        assert plain.outcome == cached.outcome == Ok(task["value"])
        assert plain.steps == cached.steps == task["steps"]
        assert plain.trace == cached.trace == task["trace"]
        assert plain.work == cached.work == plain.steps


@settings(max_examples=90, deadline=None)
@given(args=st.tuples(*(st.integers(min_value=0, max_value=4) for _ in range(3))),
       fuel=st.one_of(st.none(), st.integers(min_value=0, max_value=90)))
def test_random_memo_matches_plain_even_on_fuel_failure(tower, args, fuel):
    plain, cached = compare_runs(tower.scope(), memo_scope(tower.scope()), args, fuel=fuel)
    assert plain.outcome == cached.outcome
    assert plain.steps == cached.steps
    assert cached.work <= cached.steps


def test_compare_runs_refuses_inconsistent_memo_scope(tower):
    plain = tower.scope()
    cached = memo_scope(plain)
    wrong = replace(cached.defns["score"], body=nodes.Lit(999))
    with pytest.raises(ValueError, match="memo unfolding differs"):
        compare_runs(plain, cached.extend((wrong,)), (1, 2, 3))


def test_memo_scope_reduces_work_when_recursive_subcalls_repeat():
    recursive = nodes.Call("fib", (nodes.Call("pred", (nodes.Var("value"),)),))
    body = nodes.Case(((nodes.Test(nodes.Call("is_zero", (nodes.Var("value"),))),
                        nodes.Lit(1)),), nodes.Call("add", (recursive, recursive)))
    score = kernel.Defn("score", ("value",), nodes.Rec(
        "fib", ("value",), body, (nodes.Var("value"),), "fuel"))
    plain_scope = kernel.DictScope(
        [kernel.Atom("is_zero", 1, lambda value: value == 0),
         kernel.Atom("pred", 1, lambda value: value - 1),
         kernel.Atom("add", 2, lambda left, right: left + right)],
        [score],
    )
    plain, cached = compare_runs(plain_scope, memo_scope(plain_scope), (5,), trace=True)
    assert plain.outcome == cached.outcome == Ok(32)
    assert plain.work == plain.steps == cached.steps
    assert cached.work < plain.work
    def frames(frame):
        yield frame
        for child in frame.children:
            yield from frames(child)

    assert any(frame.memo_hit for frame in frames(cached.trace))


def test_work_rows_reproduce_frozen_snapshot_and_accept_custom_inputs(tower, capsys):
    expected = Path(__file__).resolve().parents[1] / "items" / "memo_work.csv"
    main()
    assert capsys.readouterr().out.encode("ascii") == expected.read_bytes()
    rows = work_rows(tower)
    assert len(rows) == len(frozen_inputs()) == 48
    assert all(row[5] == row[6] == row[7] for row in rows)
    assert work_rows(tower, [(1, 2, 3)]) == [(0, 1, 2, 3, 22, 50, 50, 50)]


def test_work_rows_rejects_items_without_exact_answers(tower, monkeypatch):
    from atoms_boundary import memo

    failure = kernel.Run(Unknown("fuel"), 0, 0, None)
    monkeypatch.setattr(memo, "compare_runs", lambda *_: (failure, failure))
    with pytest.raises(TypeError, match="no exact answer"):
        work_rows(tower, [(1, 2, 3)])


@pytest.mark.parametrize("policy", ("oracle", "miscount", "topline"))
def test_existing_boundary_dry_runs_byte_replay_unchanged(policy, tmp_path):
    from atoms_boundary.run import run

    name = f"dryrun_{policy}"
    run(policy=policy, out=tmp_path, run_id=name)
    committed = Path(__file__).resolve().parents[1] / "runs" / name
    replay = tmp_path / name
    for filename in ("config.json", "results.jsonl", *(f"episode_0_form_{form}.json"
                                                    for form in range(3))):
        assert (replay / filename).read_bytes() == (committed / filename).read_bytes()
