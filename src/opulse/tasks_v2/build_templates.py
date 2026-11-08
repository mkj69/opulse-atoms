"""Freeze definition-template tasks (atoms-v2, definition templates)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opulse.tasks_v2.angles import template


def build(seed=0, per_angle=None, out="worlds/tasks/templates"):
    if per_angle is None:
        per_angle = len(template.CASES) + 4
    if per_angle < 8:
        raise ValueError("each angle needs at least eight tasks")
    result = []
    for angle in template.ANGLES:
        tasks = [template.generate(angle, seed, index).to_dict()
                 for index in range(per_angle)]
        path = Path(out) / f"template_{angle}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tasks, ensure_ascii=True, separators=(",", ":")) + "\n",
                        encoding="utf-8")
        result.append(path)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--per-angle", type=int, default=len(template.CASES) + 4)
    parser.add_argument("--out", default="worlds/tasks/templates")
    args = parser.parse_args()
    build(args.seed, args.per_angle, args.out)
