"""Per-world generator runs and published site and dataset files."""

# ruff: noqa: BLE001

from __future__ import annotations

import argparse
import copy
import fcntl
import gzip
import importlib
import json
import re
import shutil
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

from opulse.atoms.values import Bottom
from opulse.gen_v2 import configs
from opulse.gen_v2.audit import audit
from opulse.gen_v2.base import KINDS, Names
from opulse.gen_v2.codec import encode_value
from opulse.gen_v2.curate import curate, graph_stats, mark_featured, showcase
from opulse.gen_v2.export import (
    export_compact,
    export_jsonl,
    export_story,
    export_summary_md,
)
from opulse.gen_v2.library import GenLibrary
from opulse.gen_v2.moves.registry import discover_moves
from opulse.gen_v2.run import RunState, generate

DATA_DIR = Path(__file__).resolve().parents[3] / "docs/assets/data/gen_v2"
DATASET_DIR = Path(__file__).resolve().parents[3] / "dataset-exports/gen_v2"
SCHEMA = "opulse.gen_v2.batch/1"


def _slug(name):
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError("world name has no URL-safe characters")
    return slug


def _dataset_dir(out_dir, dataset_dir):
    return Path(dataset_dir) if dataset_dir is not None else (
        DATASET_DIR if Path(out_dir).resolve() == DATA_DIR.resolve()
        else Path(out_dir).parent / "dataset-exports/gen_v2")


def _story_value(value):
    if isinstance(value, Bottom):
        return encode_value(value)
    raise TypeError(f"unencodable story value: {type(value).__name__}")


def _top_rejections(state):
    ranked = Counter((item.kind, item.move, item.stage, item.reason)
                     for item in state.rejections)
    top = {}
    for (kind, move, stage, reason), count in ranked.most_common():
        top.setdefault(kind, {"move": move, "stage": stage,
                              "reason": reason, "count": count})
    return top


def _move_crash(error):
    for frame, _ in traceback.walk_tb(error.__traceback__):
        if "/moves/" in frame.f_code.co_filename and frame.f_code.co_name == "__call__":
            move = frame.f_locals.get("self")
            if move is not None and hasattr(move, "name"):
                return move.name
    return "unknown"


def _audit_once(state):
    return audit(state, sample=None, seed=state.seed)


def _write_index(directory, name, summary):
    index_path = directory / "index.json"
    with index_path.open("a+", encoding="utf-8") as output:
        fcntl.flock(output, fcntl.LOCK_EX)
        output.seek(0)
        index = json.loads(output.read() or '{"schema":"opulse.gen_v2.batch/1","worlds":{}}')
        index["worlds"][_slug(name)] = summary
        output.seek(0)
        output.truncate()
        output.write(json.dumps(index, sort_keys=True, ensure_ascii=True,
                                separators=(",", ":")) + "\n")


def _world(adapter):
    if adapter.startswith("classic:"):
        from opulse.gen_v2.worlds.classic import gen_world

        return gen_world(adapter.partition(":")[2])
    return importlib.import_module(f"opulse.gen_v2.worlds.{adapter}").gen_world()


def run_world(name, *, quick=False):
    """Generate a configured world; quick mode limits work without changing the config."""
    config = configs.WORLDS[name]
    world = _world(config["adapter"])
    target = min(config["target"], 8) if quick else config["target"]
    weights = config.get("move_weights", {})
    moves = None
    if weights:
        moves = {kind: [move for move in options if weights.get(move.name, 1) > 0
                        for _ in range(max(1, round(weights.get(move.name, 1))))]
                 for kind, options in discover_moves().items()}
    library = GenLibrary(world.decl, world.atoms, world.dialect, world.extra_scope, world.signatures)
    state = RunState(world, library, dict(world.sorts), seed=config["seed"])
    state.names = Names(tuple(library._definitions) + tuple(library._extra_defns))
    start = time.monotonic()
    try:
        limit = min(config["time_limit"], 5) if quick else config["time_limit"]
        budget = 200 if quick else config.get("max_attempts", 100 * 3 * target)
        if not quick and budget < 100 * max(target, config["per_kind_min"] * len(world.open_kinds)):
            raise ValueError(f"attempt budget cannot reach target: {name}")
        state = generate(world, target, config["seed"],
                         per_kind_min=0 if quick else config["per_kind_min"],
                         layer_target=0 if quick else config["layer_target"],
                         time_limit=limit,
                         moves=moves, state=state)
        while (not quick and not meets_target(name, state) and
               state.attempts < budget and time.monotonic() - start < limit):
            next_target = min(budget // 100, max(len(state.entries) + 100,
                                                  target + 100, int(target * 1.5)))
            if next_target <= target:
                break
            previous_attempts = state.attempts
            state = generate(world, next_target, config["seed"],
                             per_kind_min=config["per_kind_min"],
                             layer_target=config["layer_target"],
                             time_limit=max(0, limit - (time.monotonic() - start)),
                             moves=moves, state=state)
            if state.attempts == previous_attempts:
                break
            target = next_target
    except Exception as error:
        state.elapsed_seconds = time.monotonic() - start
        state.time_limit_hit = state.elapsed_seconds >= limit
        error.partial_state = state
        raise
    state.elapsed_seconds = time.monotonic() - start
    state.time_limit_hit = state.elapsed_seconds >= limit
    return state


DEFINITION_KINDS = ("object", "operation", "combinator", "observation")


def meets_target(name, state, *, publication=False):
    """Check the requested total, per-open-kind quota and each kind's depth."""
    config = configs.WORLDS[name]
    counts = Counter(entry.kind for entry in state.entries.values())
    # Quotas cover the four definition kinds; laws and bridges are discovered over the admitted
    # definitions afterwards and published as separate records, so an open law/bridge kind has
    # no entry quota (otherwise the run chases it until the safety time limit).
    kinds = [kind for kind in DEFINITION_KINDS if kind in state.world.open_kinds]
    target = config["target"]
    if not len(state.entries) >= target:
        return False
    return all(counts[kind] >= config["per_kind_min"] and
               state.max_layer(kind) >= config["layer_target"] for kind in kinds)


def publish(name, state, out_dir=DATA_DIR, audit_result=None, dataset_dir=None):
    """Publish site files and a deterministic compressed full dataset."""
    if getattr(state, "time_limit_hit", False):
        raise ValueError("safety time limit reached; non-deterministic run cannot publish")
    result = audit_result if audit_result is not None else _audit_once(state)
    if result.failures:
        raise ValueError("audit failed; cannot publish")
    expected = Counter(entry.kind for entry in state.entries.values())
    if result.skipped or any(result.checked.get(kind, 0) != expected[kind] for kind in KINDS):
        raise ValueError("incomplete audit; cannot publish")
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    datasets = _dataset_dir(directory, dataset_dir)
    datasets.mkdir(parents=True, exist_ok=True)
    slug = _slug(name)
    chosen = curate(state, min(100, len(state.entries)), per_kind_min=1, per_layer_min=1)
    mark_featured(state, chosen)
    compact_path = directory / f"{slug}.json"
    templates_path = directory / f"{slug}.templates.json"

    def write_compact():
        data = export_compact(state, compact_path, selection=chosen)
        if data.get("templates"):
            templates_path.write_text(json.dumps({"schema": "opulse.gen_v2.templates/1",
                                                   "templates": data["templates"],
                                                   "template_instance_links": data["template_instance_links"],
                                                   "template_counts": data["template_counts"]},
                                                  sort_keys=True, ensure_ascii=True,
                                                  separators=(",", ":")) + "\n", encoding="utf-8")
            data["templates_file"] = templates_path.name
            featured_templates = []
            for template in data["templates"][:8]:
                if sum(len(json.dumps(item, ensure_ascii=True)) for item in featured_templates) + len(
                        json.dumps(template, ensure_ascii=True)) > 80_000:
                    break
                featured_templates.append(template)
            data["templates"] = featured_templates
            data["template_instance_links"] = {
                entry["name"]: data["template_instance_links"][entry["name"]]
                for entry in data["entries"] if entry["name"] in data["template_instance_links"]}
        data["showcase"] = showcase(state)
        from opulse.gen_v2.tasks_bridge import four_kinds_path

        data["four_kinds_path"] = four_kinds_path(state)
        errors = []
        data["story"] = []
        for item in data["showcase"]:
            try:
                stories = export_story(state, [item["name"]])
                if len(stories) != 1 or stories[0].get("name") != item["name"]:
                    raise ValueError(f"missing story: {item['name']}")
                data["story"].extend(stories)
            except (TypeError, ValueError, KeyError) as error:
                errors.append({"name": item["name"], "error": str(error)})
                data["story"].append({"name": item["name"], "error": str(error),
                                      "fallback": True, "examples": []})
        data["story"] = json.loads(json.dumps(data["story"], default=_story_value))
        data["story_errors"] = errors
        compact_path.write_text(json.dumps(data, sort_keys=True, ensure_ascii=True,
                                           separators=(",", ":")) + "\n", encoding="utf-8")

    def trim_story(example_limit):
        data = json.loads(compact_path.read_text(encoding="utf-8"))
        for story in data["story"]:
            story["examples"] = story.get("examples", [])[:example_limit]
        compact_path.write_text(json.dumps(data, sort_keys=True, ensure_ascii=True,
                                           separators=(",", ":")) + "\n", encoding="utf-8")

    write_compact()
    if compact_path.stat().st_size > 2_000_000:
        trim_story(2)
    while compact_path.stat().st_size > 2_000_000 and len(chosen) > 1:
        smaller = curate(state, max(1, len(chosen) // 2), per_kind_min=1, per_layer_min=1)
        if len(smaller) >= len(chosen):
            break
        chosen = smaller
        write_compact()
        if compact_path.stat().st_size > 2_000_000:
            trim_story(2)
    if compact_path.stat().st_size > 2_000_000:
        for example_limit in (1, 0):
            trim_story(example_limit)
            if compact_path.stat().st_size <= 2_000_000:
                break
    if compact_path.stat().st_size > 2_000_000:
        raise ValueError(f"compact export exceeds 2 MB: {name}")
    dataset_path = datasets / f"{slug}.jsonl.gz"
    with tempfile.NamedTemporaryFile(suffix=".jsonl", dir=datasets, delete=False) as temp:
        temporary_path = Path(temp.name)
    try:
        export_jsonl(state, temporary_path)
        with (temporary_path.open("rb") as source, dataset_path.open("wb") as target,
              gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as packed):
            shutil.copyfileobj(source, packed)
    finally:
        temporary_path.unlink(missing_ok=True)
    (directory / f"{slug}.md").write_text(export_summary_md(state), encoding="utf-8")
    from opulse.gen_v2 import bridges, laws

    law_state = copy.copy(state)
    law_state.entries = {entry: state.entries[entry] for entry in chosen}
    discovered_laws = laws.discover(law_state, max_laws=50, seed=state.seed)
    (directory / f"{slug}.laws.json").write_text(
        json.dumps(laws.export_json(discovered_laws, state), sort_keys=True,
                   ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8")
    bridge_state = copy.copy(state)
    bridge_selection = set(curate(state, min(60, len(state.entries)),
                                  per_kind_min=1, per_layer_min=1))
    bridge_state.entries = {entry: state.entries[entry] for entry in bridge_selection}
    bridge_state.sorts = {sort: info for sort, info in state.sorts.items()
                          if info.defined_by is None or info.defined_by in bridge_selection}
    proposed_bridges = bridges.propose(bridge_state, max_bridges=20, seed=state.seed)
    (directory / f"{slug}.bridges.json").write_text(
        bridges.to_json(proposed_bridges) + "\n", encoding="utf-8")
    sizes = {extension: (directory / f"{slug}.{extension}").stat().st_size
             for extension in ("json", "md", "laws.json", "bridges.json")}
    if templates_path.exists():
        sizes["templates.json"] = templates_path.stat().st_size
    sizes["jsonl.gz"] = dataset_path.stat().st_size
    per_kind_layer = {kind: {str(layer): count for layer, count in sorted(Counter(
        entry.layer for entry in state.entries.values() if entry.kind == kind).items())}
        for kind in KINDS}
    rejection_reasons = Counter(f"{item.move}: {item.stage}: {item.reason}" for item in state.rejections)
    compact_data = json.loads(compact_path.read_text(encoding="utf-8"))
    compact_errors = compact_data["story_errors"]
    summary = {"schema": SCHEMA, "world": name, "seed": state.seed,
               "counts": {kind: sum(entry.kind == kind for entry in state.entries.values()) for kind in KINDS},
               "counts_per_kind_layer": per_kind_layer,
               "max_layer_per_kind": {kind: state.max_layer(kind) for kind in KINDS},
               "max_layer": state.max_layer(), "graph": json.loads(json.dumps(graph_stats(state))),
               "laws": len(discovered_laws), "bridges": len(proposed_bridges),
               "templates": compact_data.get("template_counts", {}).get("total", 0),
               "audit": {"ok": result.ok, "checked": result.checked,
                         "sample": None,
                         "failures": [vars(item) for item in result.failures],
                         "skipped": [vars(item) for item in result.skipped]},
               "attempts": getattr(state, "attempts", None),
               "rejections": dict(rejection_reasons.most_common(10)),
               "top_rejection_per_kind": _top_rejections(state),
               "sizes_bytes": sizes,
               "story_errors": compact_errors,
               "size_warnings": [f"{extension} exceeds {limit} bytes"
                                 for extension, limit in (("json", 2_000_000), ("jsonl.gz", 15_000_000))
                                 if sizes[extension] > limit],
               "target_met": name in configs.WORLDS and meets_target(name, state,
                                                                       publication=True)}
    summary["four_kinds_path"] = compact_data.get("four_kinds_path") is not None
    summary["published"] = summary["target_met"] and not getattr(state, "time_limit_hit", False)
    if not summary["target_met"]:
        summary["reason"] = "quick"
    _write_index(directory, name, summary)
    return summary


def blocker(name, state, result, out_dir=DATA_DIR, export_error=None, run_error=None,
            dataset_dir=None, export_error_path=None):
    """Record unsuccessful runs without publishing unverified definitions."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _remove_exports(directory, name, dataset_dir)
    reasons = Counter((item.kind, item.move, item.stage, item.reason) for item in state.rejections)
    summary = {
        "schema": SCHEMA, "world": name, "seed": state.seed, "target_met": meets_target(name, state,
                                                                                             publication=True),
        "published": False,
        "time_limit_hit": getattr(state, "time_limit_hit", False),
        "counts": {kind: sum(entry.kind == kind for entry in state.entries.values()) for kind in KINDS},
        "max_layer_per_kind": {kind: state.max_layer(kind) for kind in KINDS},
        "unmet": {kind: {"count_short": max(0, configs.WORLDS[name]["per_kind_min"] -
                                         sum(entry.kind == kind for entry in state.entries.values())),
                         "layer_short": max(0, configs.WORLDS[name]["layer_target"] - state.max_layer(kind))}
                  for kind in state.world.open_kinds
                  if (sum(entry.kind == kind for entry in state.entries.values()) <
                      configs.WORLDS[name]["per_kind_min"] or
                      state.max_layer(kind) < configs.WORLDS[name]["layer_target"])},
        "audit": {"ok": result.ok, "checked": result.checked,
                  "failures": [vars(item) for item in result.failures]},
        "rejections": {f"{kind}: {move}: {stage}: {reason}": count
                       for (kind, move, stage, reason), count in reasons.most_common(10)},
        "top_rejection_per_kind": _top_rejections(state),
        "attempts": state.attempts,
    }
    if export_error is not None:
        summary["export_error"] = export_error
        if export_error_path:
            summary["error_path"] = export_error_path
    if run_error is not None:
        frames = traceback.extract_tb(run_error.__traceback__)
        move_frames = [frame for frame in frames if "/moves/" in frame.filename]
        summary["run_error"] = f"{type(run_error).__name__}: {run_error}"
        summary["crashing_move"] = _move_crash(run_error)
        summary["error_path"] = [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                                 for frame in move_frames]
    _write_index(directory, name, summary)
    return summary


def run_failure(name, error, out_dir=DATA_DIR, dataset_dir=None):
    """Keep an index row even when a move crashes before a state is returned."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _remove_exports(directory, name, dataset_dir)
    frames = traceback.extract_tb(error.__traceback__)
    move_frames = [frame for frame in frames if "/moves/" in frame.filename]
    move = move_frames[-1].name if move_frames else "unknown"
    kind = next((part for part in ("object", "operation", "combinator", "observation")
                 if any(f"/moves/{part}.py" in frame.filename for frame in move_frames)), "unknown")
    reason = f"{type(error).__name__}: {error}"
    summary = {"schema": SCHEMA, "world": name, "seed": configs.WORLDS[name]["seed"],
               "target_met": False, "published": False,
               "counts": dict.fromkeys(KINDS, 0), "max_layer_per_kind": dict.fromkeys(KINDS, 0),
               "audit": {"ok": False, "checked": {}, "failures": []},
               "rejections": {f"{kind}: {move}: {reason}": 1},
               "top_rejection_per_kind": {kind: {"move": move, "reason": reason, "count": 1}},
               "run_error": reason, "error_path": [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                                                      for frame in move_frames],
               "crashing_move": _move_crash(error)}
    _write_index(directory, name, summary)
    return summary


def _remove_exports(directory, name, dataset_dir=None):
    for extension in ("json", "jsonl", "md", "laws.json", "bridges.json", "templates.json"):
        (directory / f"{_slug(name)}.{extension}").unlink(missing_ok=True)
    (_dataset_dir(directory, dataset_dir) / f"{_slug(name)}.jsonl.gz").unlink(missing_ok=True)


def report_table(index, durations=None):
    """Summarize recorded world runs for the command-line report."""
    durations = durations or {}
    lines = ["world | object/op/comb/obs/law/bridge | max layer by kind | laws | bridges | templates | four-kind path | audit | published | time (s) | blocker"]
    for name, data in sorted(index.get("worlds", {}).items()):
        counts = data["counts"]
        layers = data["max_layer_per_kind"]
        values = lambda source: "/".join(str(source.get(kind, 0)) for kind in KINDS)
        top = (f"{data.get('crashing_move', 'unknown')}: {data['run_error']}"
               if data.get("run_error") else
               data.get("export_error") or next(iter(data.get("rejections", {})), "none"))
        if data.get("unmet"):
            top = f"unmet {data['unmet']}; {top}"
        if data.get("time_limit_hit"):
            top = f"safety time limit; {top}"
        if data.get("published"):
            top = "none"
        lines.append(f"{name} | {values(counts)} | {values(layers)} | "
                     f"{data.get('laws', 0)} | {data.get('bridges', 0)} | {data.get('templates', 0)} | "
                     f"{'yes' if data.get('four_kinds_path') else 'no'} | "
                     f"{len(data['audit']['failures'])} failures / {sum(data['audit'].get('checked', {}).values())} checked | "
                     f"{'yes' if data.get('published') else 'no'} | {durations.get(name, '-')} | {top}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate and publish atoms-v2 world datasets")
    parser.add_argument("--worlds", help="comma-separated adapter names (default: all available)")
    parser.add_argument("--quick", action="store_true", help="short diagnostic run, also publish partial results")
    parser.add_argument("--report", action="store_true", help="print the published index table")
    parser.add_argument("--out", type=Path, default=DATA_DIR, help="export directory")
    parser.add_argument("--datasets", type=Path, help="compressed full dataset directory")
    parser.add_argument("--checkpoints", type=Path,
                        help="also save each finished run state here (run.save JSON), for re-export")
    args = parser.parse_args(argv)
    if args.report:
        index_path = args.out / "index.json"
        if not index_path.exists():
            parser.error(f"missing index: {index_path}")
        print(report_table(json.loads(index_path.read_text(encoding="utf-8"))))
        return 0
    names = args.worlds.split(",") if args.worlds else list(configs.WORLDS)
    _, missing = configs.available_adapters()
    failed = False
    for name in names:
        if name not in configs.WORLDS:
            print(f"Skipping {name}: {missing.get(name, 'unknown adapter')}")
            failed |= bool(args.worlds)
            continue
        state = None
        check = None
        try:
            state = run_world(name, quick=args.quick)
            if args.checkpoints is not None:
                from opulse.gen_v2.run import save

                args.checkpoints.mkdir(parents=True, exist_ok=True)
                checkpoint = args.checkpoints / f"{_slug(name)}.json"
                try:
                    save(state, checkpoint)
                except (TypeError, ValueError) as error:
                    # e.g. display-only legacy host values cannot be restored; the run still publishes
                    checkpoint.unlink(missing_ok=True)
                    print(f"{name}: checkpoint skipped: {error}")
            if args.quick or (not getattr(state, "time_limit_hit", False) and
                              meets_target(name, state, publication=True)):
                check = _audit_once(state)
                if check.failures:
                    blocker(name, state, check, args.out, dataset_dir=args.datasets)
                    print(f"{name}: {len(check.failures)} audit failures; not published")
                    failed = True
                    continue
                report = publish(name, state, args.out, audit_result=check,
                                 dataset_dir=args.datasets)
                print(f"{name}: {len(state.entries)} admitted, L{state.max_layer()}, "
                      f"{state.elapsed_seconds:.1f}s, {len(report['audit']['failures'])} audit failures")
                for warning in report["size_warnings"]:
                    print(f"{name}: {warning}")
            else:
                blocker(name, state, _audit_once(state), args.out, dataset_dir=args.datasets)
                print(f"{name}: {len(state.entries)} admitted, L{state.max_layer()}, "
                      f"{state.elapsed_seconds:.1f}s; target not met, not published")
                failed |= bool(args.worlds and not args.quick)
        except Exception as error:
            state = state if state is not None else getattr(error, "partial_state", None)
            if state is not None:
                try:
                    check = check if check is not None else _audit_once(state)
                except Exception:
                    from opulse.gen_v2.audit import AuditReport

                    check = AuditReport()
                blocker(name, state, check, args.out, dataset_dir=args.datasets,
                        export_error=f"{type(error).__name__}: {error}" if state is not getattr(error, "partial_state", None) else None,
                        run_error=error if state is getattr(error, "partial_state", None) else None,
                        export_error_path=[f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                                           for frame in traceback.extract_tb(error.__traceback__)]
                        if state is not getattr(error, "partial_state", None) else None)
            else:
                run_failure(name, error, args.out, dataset_dir=args.datasets)
            print(f"Skipping {name}: {type(error).__name__}: {error}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
