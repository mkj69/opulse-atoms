"""Write frozen operation tasks (docs/spec/atoms-v2.md, section 12)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opulse.tasks_v2.angles.operation import ANGLES, VERSIONS, WORLD_NAMES, generate


def build(world: str, seed: int, per_angle: int, out: str | Path, modality: str = "text") -> list[Path]:
    if per_angle < 1:
        raise ValueError("per_angle must be positive")
    root = Path(out) / f"{world}@{VERSIONS[world]}"
    root.mkdir(parents=True, exist_ok=True)
    files = []
    for angle in ANGLES:
        path = root / f"operation_{angle}.json"
        tasks = [generate(world, angle, seed, index, modality=modality).to_dict() for index in range(per_angle)]
        path.write_text(json.dumps(tasks, ensure_ascii=True, separators=(",", ":")) + "\n",
                        encoding="utf-8")
        files.append(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", choices=(*WORLD_NAMES, "all"), default="all")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--per-angle", type=int, default=8)
    parser.add_argument("--out", default="worlds/tasks/")
    args = parser.parse_args()
    for world in (WORLD_NAMES if args.world == "all" else (args.world,)):
        build(world, args.seed, args.per_angle, args.out)


if __name__ == "__main__":
    main()
