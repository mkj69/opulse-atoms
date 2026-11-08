"""Legacy golden compatibility (atoms-v2 spec section 13.3)."""

import json
import os
import time
from dataclasses import replace

from opulse.atoms.golden import (
    CLOCK_REASON,
    DEFAULT_ROOT,
    MANIFEST,
    WORLDS,
    CurrentEngine,
    EngineResult,
    GoldenCase,
    KernelEngine,
    _reference_base_ops,
    compare,
    compare_kernel,
    iter_cases,
    published_hashes,
    run_golden,
)
from opulse.core.semantics import NAN


def test_published_data_manifest():
    assert json.loads(MANIFEST.read_text(encoding="utf-8")) == published_hashes()


def test_golden_reports_per_case_exception_and_continues(monkeypatch):
    from opulse.atoms import golden

    cases = [GoldenCase("integer", "integer.json", 10, name, "", (), (), 0, None, "atom_example")
             for name in ("broken", "working")]
    monkeypatch.setattr(golden, "iter_cases", lambda world, root: iter(cases))
    monkeypatch.setattr(golden, "compare", lambda case, result: [])

    class Engine:
        name = "test"

        def load(self, data):
            return data

        def run(self, state, case):
            if case.operator == "broken":
                raise RuntimeError("bad input")
            return EngineResult(0)

    report = run_golden(Engine(), ("integer",))
    assert report.worlds["integer"].failed == 1
    assert report.worlds["integer"].passed == 1
    assert "RuntimeError: bad input" in report.worlds["integer"].diffs[0]


def test_kernel_loads_published_seed_without_regeneration(monkeypatch):
    from opulse.atoms import golden

    monkeypatch.setattr(golden, "_PREPARED", {})
    monkeypatch.setattr(golden, "_PUBLISHED", {})
    def reject_regeneration(self, publication):
        raise AssertionError("kernel golden must not regenerate the published world")

    monkeypatch.setattr(CurrentEngine, "load", reject_regeneration)
    publication = json.loads((DEFAULT_ROOT / "integer.json").read_text(encoding="utf-8"))
    engine = KernelEngine()
    state = engine.load(publication)
    case = next(case for case in iter_cases("integer", main_only=True)
                if case.seed == publication["seed"] and case.kind == "operator_example")
    case = replace(case, expected_base_ops=_reference_base_ops(case, state))
    assert compare_kernel(case, engine.run(state, case)) == []
    assert ("integer", publication["seed"]) in golden._PUBLISHED
    assert ("integer", publication["seed"]) not in golden._PREPARED
    generated = object()
    monkeypatch.setattr(golden, "_load_current", lambda data: generated)
    assert golden._prepared(publication) is generated
    assert golden._PUBLISHED[("integer", publication["seed"])] is state.reference


def test_case_inventory_and_clock_skip():
    for world in WORLDS:
        cases = list(iter_cases(world, DEFAULT_ROOT, main_only=True))
        assert any(case.kind == "atom_example" for case in cases)
        assert any(case.kind == "operator_example" and case.expected_steps is not None
                   for case in cases)
        assert any(case.kind == "task" and case.skip_reason for case in cases)
        publication = json.loads((DEFAULT_ROOT / f"{world}.json").read_text(encoding="utf-8"))
        assert len({entry["seed"] for entry in publication["seeds"]}) == 3
    report = run_golden(CurrentEngine(), ("clock",))
    assert report.worlds["clock"].passed == report.worlds["clock"].failed == 0
    assert report.worlds["clock"].reasons[CLOCK_REASON] == report.worlds["clock"].cases


def test_compare_reports_output_count_and_step_fields():
    case = GoldenCase("integer", "integer.json", 30, "x", "x a = { a + 1 }", ("int",),
                      (1,), NAN, [{"kind": "eval", "expression": "2", "focus": "x 1",
                                     "value": {"t": "nan"}, "gate": "x", "branch": None,
                                     "note": "Compute x.", "note_zh": "calculate"}],
                      "operator_example")
    assert compare(case, EngineResult(NAN, case.expected_steps)) == []
    diffs = compare(case, EngineResult(2, [{"kind": "expand", "expression": "3"}]))
    assert any("output" in diff for diff in diffs)
    assert any("step 0 kind" in diff for diff in diffs)
    assert any("step 0 note" in diff for diff in diffs)
    assert any("step 0 value" in diff for diff in diffs)
    assert any("steps: missing" in diff for diff in compare(case, EngineResult(NAN)))
    assert any("steps: expected" in diff for diff in compare(case, EngineResult(NAN, [])))


def test_current_engine_golden():
    worlds = tuple(world for world in WORLDS if world != "clock")
    if os.getenv("OPULSE_GOLDEN_FULL") == "1":
        for engine in (CurrentEngine(), KernelEngine()):
            started = time.monotonic()
            report = run_golden(engine, worlds)
            print(report)
            print(f"{engine.name} full golden: {time.monotonic() - started:.1f}s")
            for count in report.worlds.values():
                assert not count.failed, str(report)
                assert count.passed == count.cases - count.skipped
    else:
        for world in worlds:
            cases = list(iter_cases(world, main_only=True))
            seed = json.loads((DEFAULT_ROOT / f"{world}.json").read_text())["seed"]
            for engine in (CurrentEngine(), KernelEngine()):
                source = next(case.source for case in cases if case.seed == seed and
                              case.kind == "operator_example")
                publication = json.loads((DEFAULT_ROOT / source).read_text(encoding="utf-8"))
                state = (engine.load_published(publication) if isinstance(engine, CurrentEngine)
                         else engine.load(publication))
                first = [case for case in cases if case.seed == seed and
                         case.kind == "operator_example" and case.example_index == 0]
                undefined = [case for case in cases if case.seed == seed and
                             case.kind == "operator_example" and
                             any(step["kind"] == "undefined" for step in case.expected_steps)]
                selected = first[:15] + undefined[:5]
                checker = compare_kernel if isinstance(engine, KernelEngine) else compare
                for case in selected:
                    if isinstance(engine, KernelEngine) and world != "action":
                        case = replace(case, expected_base_ops=_reference_base_ops(case, state))
                    assert checker(case, engine.run(state, case)) == [], (world, seed, case.operator)
                for atom in (case for case in cases if case.seed == seed and case.kind == "atom_example"):
                    assert checker(atom, engine.run(state, atom)) == [], (world, seed, atom.operator)
