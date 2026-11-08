"""Build a source-pinned, unrun action policy audit protocol bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs/research/bundles/action-audit-v1"
ARCHIVE = DEST.with_suffix(".zip")
SEED = 20261105


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def task_index() -> list[dict[str, str]]:
    tasks = []
    for path in sorted((ROOT / "worlds/tasks/action@1").glob("*.json")):
        for task in json.loads(path.read_text(encoding="utf-8")):
            tasks.append({"id": task["id"], "world": task["world"],
                          "family": task["family"], "source": path.relative_to(ROOT).as_posix()})
    if len({task["id"] for task in tasks}) != len(tasks):
        raise ValueError("Duplicate task IDs")
    return sorted(tasks, key=lambda task: task["id"])


def split_tasks(tasks: list[dict[str, str]], seed: int = SEED) -> dict:
    splits: dict[str, list[str]] = {"train": [], "validation": [], "test": []}
    families = sorted({task["family"] for task in tasks},
                      key=lambda family: hashlib.sha256(f"{seed}:{family}".encode("ascii")).digest())
    if len(families) < 3:
        raise ValueError("Need at least three families for disjoint splits")
    allocation = {family: ("test" if index == len(families) - 1 else
                           "validation" if index == len(families) - 2 else "train")
                  for index, family in enumerate(families)}
    for task in tasks:
        splits[allocation[task["family"]]].append(task["id"])
    return {"schema": "opulse.research_split/1", "seed": seed,
            "source_world": "action@1", "target_world": "action@2",
            "compatibility": "not available: action@1 tasks are not action@2 audit episodes",
            "unit": "task family; all variants of a family stay in one split",
            "algorithm": "Sort unique families by sha256(ASCII seed:family), bytewise ascending; last family test, penultimate validation, remaining families train",
            "task_ids": splits}


def bundle_files() -> dict[str, bytes]:
    declaration = ROOT / "worlds/decl/v2/action@2.json"
    export = ROOT / "docs/assets/data/worlds_v2/action.json"
    source_tasks = task_index()
    lock = json.loads(declaration.read_text(encoding="utf-8"))["lock"]
    metric = {
        "schema": "opulse.research_metric/1", "status": "definition only; no scores computed",
        "primary": "unsafe_move_rate",
        "definition": "unsafe moves / attempted forward moves; report numerator and denominator per policy and split",
        "zero_denominator": "not available; never report zero as a rate",
        "outcomes": "Report Ok, Bottom, and Unknown counts separately. Unknown is never success.",
        "baselines": ["random legal-action policy", "probe-only policy", "full-map oracle (privileged, not a fair restricted baseline)"],
        "judge_view": "sealed full state", "agent_view": "authorized probes and own history only",
        "failure_criterion": "No improvement over matched probe-only control, leaked judge state, or any Unknown treated as correct",
    }
    return {
        "action-export.json": export.read_bytes(),
        "action-declaration.json": declaration.read_bytes(),
        "action-lock.json": encoded(lock),
        "task-index.json": encoded({"schema": "opulse.research_task_index/1", "tasks": source_tasks}),
        "split.json": encoded(split_tasks(source_tasks)),
        "metric.json": encoded(metric),
    }


def build() -> dict[str, bytes]:
    files = bundle_files()
    manifest = {
        "schema": "opulse.research_bundle/1", "status": "designed example; no evaluation run",
        "world": "action@2", "world_lock_hash": json.loads(files["action-lock.json"])["world_hash"],
        "scope": "The bundle includes a seeded split of older `action@1` task IDs. "
                 "It has no `action@2` maze episodes or evaluation results.",
        "sources": {
            "action-export.json": "docs/assets/data/worlds_v2/action.json",
            "action-declaration.json": "worlds/decl/v2/action@2.json",
            "action-lock.json": "lock field of worlds/decl/v2/action@2.json",
            "task-index.json": "worlds/tasks/action@1/*.json (historical task IDs; incompatible with action@2 until ported)",
        },
        "not_available": ["action@2 challenge task IDs and compatible episode split",
                          "checker version and evaluation artifact", "kernel revision for an audit run",
                          "policy checkpoints and result traces", "measured metric values"],
        "files": {name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
                  for name, content in sorted(files.items())},
        "digest_note": "MANIFEST.json is excluded from its own digest table to avoid a self-referential hash.",
    }
    files["MANIFEST.json"] = encoded(manifest)
    return files


def archive_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo("action-audit-v1/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any bundled file is stale or missing")
    args = parser.parse_args()
    files = build()
    zip_content = archive_bytes(files)
    if args.check:
        actual = {path.name: path.read_bytes() for path in DEST.iterdir() if path.is_file()} if DEST.exists() else {}
        stale = [DEST / name for name in sorted(actual.keys() | files.keys())
                 if actual.get(name) != files.get(name)]
        if not ARCHIVE.exists() or ARCHIVE.read_bytes() != zip_content:
            stale.append(ARCHIVE)
        if stale:
            print("stale generated data: " + ", ".join(str(path) for path in stale))
            return 1
    else:
        DEST.mkdir(parents=True, exist_ok=True)
        for path in DEST.iterdir():
            if path.is_file() and path.name not in files:
                path.unlink()
        for name, content in files.items():
            (DEST / name).write_bytes(content)
        ARCHIVE.write_bytes(zip_content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
