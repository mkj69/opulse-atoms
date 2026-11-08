"""Published legacy operators through the generator pipeline and golden kernel."""

from __future__ import annotations

import itertools
import json
import os
from dataclasses import replace

import pytest

from opulse.atoms import golden, nodes
from opulse.atoms.legacy import scope_from_registry
from opulse.atoms.values import Ok
from opulse.core.semantics import NAN
from opulse.core.types import same_value
from opulse.gen_v2.base import GenState
from opulse.gen_v2.export import export, export_story
from opulse.gen_v2.legacy_import import (
    encode_published_value,
    import_report,
    import_world,
)


@pytest.fixture(scope="module", params=("integer", "clock", "strings"))
def imported(request):
    return request.param, import_world(request.param)


def test_published_promoted_with_evidence_and_metadata(imported):
    world_name, state = imported
    report = import_report(state)
    assert report["published"] == 100
    # Published operators are kept even when a generator filter would refuse them (legacy_keep);
    # the filter verdict is recorded on the entry instead.
    assert report["admitted"] == 100
    assert len(report["refused"]) == 0
    flagged = [entry for entry in state.entries.values() if entry.meta.get("filter_verdict")]
    # True-clock publication flags six operators (indexes 8, 43, 61, 63, 75, 77).
    assert len(flagged) == {"integer": 5, "clock": 6, "strings": 9}[world_name]
    assert all(row["computed_layer"] != row["adapter_layer"] for row in report["layer_mismatches"])
    assert "dependency layer" in report["layer_explanation"]
    assert all(row["name"].startswith("published_") and row["stage"] in
               {"degenerate", "duplicate"} for row in report["refused"])
    assert state.world.dialect == "legacy-v1"
    assert state.world.open_kinds == frozenset({"operation"})
    data = json.loads((golden.DEFAULT_ROOT / f"{world_name}.json").read_text(encoding="utf-8"))
    for entry in state.entries.values():
        definition = state.library.get(entry.name)
        assert definition.status == "promoted"
        assert definition.evidence.method in ("exhaustive", "bounded")
        assert definition.evidence.scope["size"] > 0
        assert entry.meta["legacy_keep"] is True
        assert "display" not in entry.meta
        assert entry.layer == entry.meta["legacy"]["computed_layer"]
        assert entry.meta["legacy"]["adapter_layer"] == entry.meta["legacy"]["published_layer"] + 1
        assert definition.depends_on == tuple(sorted(nodes.references(definition.body)))
        row = data["operators"][int(entry.name.removeprefix("published_"))]
        assert entry.meta["legacy"]["symbol"] == row["name"]
        assert entry.meta["legacy"]["func_id"] == entry.name
        assert {key: value for key, value in entry.meta["legacy"]["interest"].items()
                if key != "nearest"} == {key: value for key, value in row["interest"].items()
                                      if key != "nearest"}
        assert (entry.meta["legacy"]["interest"].get("nearest") or "").isascii()
        assert entry.meta["legacy"]["featured"] == row["featured"]
        assert entry.meta["legacy"]["curated"] == (row["name"] in data["curated"])


def test_legacy_kernel_steps_match_golden_on_twenty_domain_cases(imported):
    world_name, state = imported
    data = json.loads((golden.DEFAULT_ROOT / f"{world_name}.json").read_text(encoding="utf-8"))
    reference = golden.CurrentEngine().load_published(data)
    tools = reference.tools
    scope, info = scope_from_registry(tools.registry, tools.settings.semantics.build(), tools.oracle.parser)
    published = {row["name"]: f"published_{index}" for index, row in enumerate(data["operators"])}
    golden_state = golden.KernelState(reference, scope, info.names, published)
    cases = []
    seen = set()
    for case in golden.iter_cases(world_name, main_only=True):
        if (case.kind != "operator_example" or published[case.operator] not in state.entries or
                case.operator in seen):
            continue
        seen.add(case.operator)
        signature = state.entries[published[case.operator]].signature
        domain = itertools.product(*(state.sorts[sort].values for sort in signature.inputs))
        args = next(itertools.islice(domain, len(cases) % 6, None))
        cases.append(replace(case, inputs=args, expected_steps=None))
        if len(cases) >= 20:
            break
    assert len(cases) == 20
    for case in cases[:20]:
        name = published[case.operator]
        original = golden.KernelEngine().run(golden_state, case)
        generated = state.library.run(name, case.inputs)
        assert generated.steps == original.base_ops
        output = generated.outcome.value if isinstance(generated.outcome, Ok) else NAN
        assert same_value(output, original.output), (world_name, case.operator, case.inputs)


def test_probe_domain_and_order_are_deterministic(imported):
    world_name, state = imported
    replay = import_world(world_name)
    assert list(replay.entries) == list(state.entries)
    assert import_report(replay) == import_report(state)
    assert all(replay.sorts[sort].values == values.values
               for sort, values in state.sorts.items())


def test_prebuilt_empty_catalogue_is_supported(imported):
    world_name, state = imported
    library = type(state.library)(state.world.decl, state.world.atoms, state.world.dialect)
    empty = GenState(state.world, library, dict(state.sorts))
    assert import_world(world_name, empty) is empty
    assert import_report(empty) == import_report(state)


@pytest.mark.parametrize("world_name", ("lists", "perm", "grid", "pitch", "action", "rel"))
def test_other_classic_worlds_import_with_legacy_values(world_name):
    state = import_world(world_name)
    report = import_report(state)
    published = json.loads((golden.DEFAULT_ROOT / f"{world_name}.json").read_text(encoding="utf-8"))
    assert report["published"] == len(published["operators"])
    assert report["admitted"] > 0
    assert report["admitted"] + len(report["refused"]) == report["published"]
    assert all(state.library.get(entry.name).status == "promoted" and
               state.library.get(entry.name).evidence.method in ("exhaustive", "bounded")
               for entry in state.entries.values())
    for entry in itertools.islice(state.entries.values(), 10):
        for args, encoded, _ in entry.examples[:1]:
            if encoded and "ok" in encoded and "tag" not in encoded["ok"]:
                assert golden.decode(encoded["ok"]) == state.library.run(entry.name, args).outcome.value
    if world_name != "rel":
        assert any(example[1] and example[1].get("ok", {}).get("t") in
                   {"list", "perm", "grid", "melody", "state"}
                   for entry in state.entries.values() for example in entry.examples)


def _golden_published_examples(world_name, state):
    data = json.loads((golden.DEFAULT_ROOT / f"{world_name}.json").read_text(encoding="utf-8"))
    mapping = {row["name"]: f"published_{index}" for index, row in enumerate(data["operators"])}
    reference = golden.KernelEngine().load(data)
    imported = replace(reference, scope=state.library.scope(), ids={**reference.ids, **mapping},
                       names={**reference.names, **{name: symbol for symbol, name in mapping.items()}},
                       search_names=frozenset(mapping.get(name, name) for name in reference.search_names),
                       conditional_names=frozenset(mapping.get(name, name)
                                                   for name in reference.conditional_names))
    cases = (case for case in golden.iter_cases(world_name, main_only=True)
             if case.kind == "operator_example" and mapping[case.operator] in state.entries)
    from opulse.core.semantics import NAN

    successful = next(case for case in cases if case.expected_output is not NAN)
    failed = next(case for case in golden.iter_cases(world_name, main_only=True)
                  if case.kind == "operator_example" and case.expected_output is NAN and
                  mapping[case.operator] in state.entries)
    for case in (successful, failed):
        full_steps = golden._reference_base_ops(case, reference)
        case = replace(case, expected_base_ops=full_steps)
        result = golden.KernelEngine().run(imported, case)
        assert not golden.compare_kernel(case, result), (world_name, case.operator, case.example_index,
                                                          golden.compare_kernel(case, result))
        assert result.base_ops == state.library.run(mapping[case.operator], case.inputs).steps == full_steps


def test_imported_worlds_match_published_success_failure_and_steps(imported):
    world_name, state = imported
    _golden_published_examples(world_name, state)


def test_legacy_export_rejects_unencodable_example(imported, tmp_path):
    world_name, state = imported
    if world_name != "integer":
        return
    entry = next(iter(state.entries.values()))
    entry.examples.append(((object(),), {"ok": {"t": "int", "v": 1}}, 0))
    try:
        with pytest.raises(ValueError, match=f"{world_name}/{entry.name}: unencodable example"):
            export(state, tmp_path / "invalid.json")
    finally:
        entry.examples.pop()


def test_action_export_preserves_robot_states_and_story(tmp_path):
    state = import_world("action")
    data = export(state, tmp_path / "action.json")
    assert len(data["entries"]) == 100 and data["examples_dropped"] == {}
    assert all(item["examples"] for item in data["entries"])
    first = data["entries"][0]["examples"][0]
    assert first["inputs"][0]["t"] == "state" and "robot" in first["inputs"][0]["v"]
    assert encode_published_value("action", golden.decode(first["inputs"][0])) == first["inputs"][0]
    story = export_story(state, [data["entries"][0]["name"]])[0]
    assert story["examples"][0]["trace"]["inputs"][0]["t"] == "state"
    assert (tmp_path / "action.json").read_text().isascii()


@pytest.mark.skipif(not os.environ.get("OPULSE_GEN_SLOW"), reason="slow acceptance run")
@pytest.mark.parametrize("world_name", golden.WORLDS)
def test_all_classic_worlds_export_ascii_and_match_published_golden(world_name, tmp_path):
    state = import_world(world_name)
    data = export(state, tmp_path / f"{world_name}.json")
    assert (tmp_path / f"{world_name}.json").read_text().isascii()
    assert not data["examples_dropped"]
    assert all(len(item["examples"]) == len(state.entries[item["name"]].examples)
               for item in data["entries"])
    assert all(item["name"].isascii() and item["ascii"].isascii() for item in data["entries"])
    assert all(item["name"].startswith("published_") for item in data["entries"])
    for entry in state.entries.values():
        assert all(name.isascii() for name in nodes.references(state.library.get(entry.name).body))
        assert json.dumps({key: value for key, value in entry.meta["legacy"].items()
                           if key != "symbol"}, ensure_ascii=False).isascii()
    for item in data["entries"]:
        for example in item["examples"]:
            for encoded, sort in zip(example["inputs"], item["signature"]["inputs"]):
                assert encode_published_value(world_name, golden.decode(encoded), sort) == encoded
            if "ok" in example["outcome"]:
                encoded = example["outcome"]["ok"]
                assert encode_published_value(world_name, golden.decode(encoded),
                                              item["signature"]["output"]) == encoded
    _golden_published_examples(world_name, state)
