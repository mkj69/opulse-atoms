"""Independent review regression for the Pascal memo evidence claim."""

import inspect
import math
from pathlib import Path

import pytest
from atoms_boundary.memo import memo_scope
from atoms_boundary.memo_cost import build_cost_tower
from atoms_boundary.pipeline import promote_tower
from atoms_boundary.tower import build_tower
from hypothesis import given, settings
from hypothesis import strategies as st

from opulse.atoms import kernel
from opulse.atoms.values import Ok


@pytest.fixture(scope="module")
def cost_tower():
    return build_cost_tower()


def test_pascal_memo_variant_carries_its_own_promoted_evidence(cost_tower):
    library = cost_tower
    memo_body = memo_scope(library.scope()).defns["choose"].body
    record = library.get("choose_memo")
    assert record.body == memo_body
    assert record.status == "promoted"
    assert record.evidence.method == "exhaustive"
    assert record.evidence.scope["size"] == 45
    assert record.evidence.scope["checked"]["size"] == 45
    assert record.evidence.content_hash != library.get("choose").evidence.content_hash
    assert "unfold_equivalence" in record.evidence.checks
    assert record.contract is not None


@settings(max_examples=25, deadline=None)
@given(n=st.integers(min_value=0, max_value=8),
       k=st.integers(min_value=0, max_value=8))
def test_promoted_pascal_memo_variant_preserves_charged_unfolding(cost_tower, n, k):
    if k > n:
        return
    scope = cost_tower.scope()
    assert memo_scope(scope).defns["choose"].body == scope.defns["choose_memo"].body
    plain = kernel.call("choose", (n, k), scope)
    memo = kernel.call("choose_memo", (n, k), scope)
    assert plain.outcome == memo.outcome == Ok(math.comb(n, k))
    assert plain.steps == memo.steps
    assert memo.work <= plain.work


def test_memo_scope_rejects_diverging_promoted_variant(cost_tower):
    from dataclasses import replace

    scope = cost_tower.scope()
    different = replace(scope.defns["choose_memo"], body=scope.defns["choose"].body)
    with pytest.raises(ValueError, match="memo variant differs from choose"):
        memo_scope(scope.extend((different,)))


def test_pascal_tower_shares_promotion_pipeline_with_primary_tower():
    primary = inspect.getsource(build_tower)
    pascal = inspect.getsource(build_cost_tower)
    stages = (
        "library.write(definition)",
        "library.check(",
        "library.make_callable(",
        "library.verify(",
        "library.account(",
        "library.promote(",
    )
    assert not all(stage in primary and stage in pascal for stage in stages)
    assert "promote_tower(" in primary and "promote_tower(" in pascal


def test_shared_pipeline_rejects_unrepresentable_mutual_recursion(monkeypatch):
    from atoms_boundary import pipeline

    class Entry:
        name = "cycle"

    monkeypatch.setattr(pipeline, "parse_program", lambda source: type("Program", (), {"defs": [Entry()]})())
    monkeypatch.setattr(pipeline, "compile_definition", lambda entry, lookup: None)
    with pytest.raises(ValueError, match="mutual recursion in cycle"):
        promote_tower(None, "unused", {}, {}, {}, {})


def test_tower_hash_covers_the_shared_pipeline(monkeypatch, tmp_path):
    from atoms_boundary import run

    directory = tmp_path / "atoms_boundary"
    directory.mkdir()
    for source in (Path(run.ROOT) / "atoms_boundary").glob("*.py"):
        (directory / source.name).write_bytes(source.read_bytes())
    monkeypatch.setattr(run, "ROOT", tmp_path)
    before = run.configuration("oracle", 1, None)["hashes"]["tower"]
    (directory / "pipeline.py").write_text("changed", encoding="ascii")
    assert run.configuration("oracle", 1, None)["hashes"]["tower"] != before
