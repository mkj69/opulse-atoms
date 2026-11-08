"""Command line interface for the atoms-v2 generator."""

from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import re
from collections import Counter
from pathlib import Path

from opulse.gen_v2 import worlds
from opulse.gen_v2.audit import audit
from opulse.gen_v2.run import generate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m opulse.gen_v2")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("list", help="list available world adapters")
    runner = subcommands.add_parser("run", help="generate and export a world")
    runner.add_argument("--world", required=True, help="adapter module, or classic:<world>")
    runner.add_argument("--target", type=int, default=300)
    runner.add_argument("--seed", type=int, default=1)
    runner.add_argument("--time-limit", type=float, default=None)
    runner.add_argument("--per-kind-min", type=int, default=50)
    runner.add_argument("--layer-target", type=int, default=10)
    runner.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    available = sorted(info.name for info in pkgutil.iter_modules(worlds.__path__)
                       if not info.ispkg and not info.name.startswith("_"))
    if args.command == "list":
        for name in available:
            print(name)
        return 0
    module_name, _, option = args.world.partition(":")  # classic:integer selects one classic world
    if module_name not in available:
        parser.error(f"unknown world {args.world!r}; choose from: {', '.join(available)}")
    adapter = importlib.import_module(f"{worlds.__name__}.{module_name}")
    world = adapter.gen_world(option) if option else adapter.gen_world()
    state = generate(world, args.target, args.seed, args.per_kind_min,
                     args.time_limit, args.layer_target)
    report = audit(state)
    if not report.ok:
        print(f"{world.name}: audit failed: {report.failures}")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        exporter = importlib.import_module("opulse.gen_v2.export")
    except ModuleNotFoundError as error:
        if error.name != "opulse.gen_v2.export":
            raise
        exporter = None
    if exporter is not None:
        slug = re.sub(r"[^a-z0-9-]+", "-", args.world.lower()).strip("-")
        if not slug:
            parser.error("world name has no URL-safe characters")
        base = args.out / slug
        exporter.export(state, base.with_suffix(".json"))
        from opulse.gen_v2.curate import curate, showcase

        chosen = curate(state, min(100, len(state.entries)), per_kind_min=1, per_layer_min=1)
        compact_path = base.with_suffix(".compact.json")
        featured = showcase(state)
        stories = exporter.export_story(state, [item["name"] for item in featured])
        while True:
            compact = exporter.export_compact(state, compact_path, selection=chosen)
            compact["showcase"] = featured
            compact["story"] = stories
            compact_path.write_text(json.dumps(compact, sort_keys=True, ensure_ascii=True,
                                               separators=(",", ":")) + "\n", encoding="utf-8")
            if compact_path.stat().st_size <= 2_000_000:
                break
            if len(chosen) <= 1:
                raise ValueError(f"compact export exceeds 2 MB: {args.world}")
            chosen = curate(state, max(1, len(chosen) // 2), per_kind_min=1, per_layer_min=1)
        exporter.export_jsonl(state, base.with_suffix(".jsonl"))
        summary = exporter.export_summary_md(state)
        if featured:
            summary += "\n## Showcase\n" + "".join(
                f"- {item['name']}: {item['why']}\n" for item in featured)
        base.with_suffix(".md").write_text(summary, encoding="utf-8")
    if exporter is None:
        data = {"schema": "opulse.gen-v2.export/1", "world": world.name, "seed": args.seed,
                "entries": [state.library.get(name).to_dict() for name in state.entries]}
        (args.out / "entries.json").write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    counts = Counter(entry.kind for entry in state.entries.values())
    print(f"{world.name}: {len(state.entries)} admitted, {state.max_layer()} max layer, "
          f"{state.attempts} attempts; counts {dict(counts)}; output {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
