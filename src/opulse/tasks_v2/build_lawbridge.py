"""Freeze six-angle law and bridge tasks (docs/spec/atoms-v2.md, section 12)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opulse.tasks_v2.angles import bridge, law


def build(seed=0, per_angle=8, out="worlds/tasks"):
    if per_angle < 8:
        raise ValueError("each angle needs at least eight tasks")
    paths = []
    for module in (law, bridge):
        for angle in module.ANGLES:
            groups = {}
            for index in range(per_angle):
                record = module.generate(angle, seed, index).to_dict()
                groups.setdefault(record["world"], []).append(record)
            for world, tasks in groups.items():
                path = Path(out) / world / f"{module.__name__.rsplit('.', 1)[-1]}_{angle}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(tasks, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8")
                paths.append(path)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--per-angle", type=int, default=8)
    parser.add_argument("--out", default="worlds/tasks")
    arguments = parser.parse_args()
    build(arguments.seed, arguments.per_angle, arguments.out)
