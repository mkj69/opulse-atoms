"""Regenerate generic task samples (docs/spec/atoms-v2.md, section 12)."""

from __future__ import annotations

from pathlib import Path

from opulse.tasks_v2.fixtures import computer_world, sensor_counter_world, toy_world
from opulse.tasks_v2.generic import write_samples


def main() -> None:
    root = Path(__file__).resolve().parents[3] / "worlds/tasks/generic"
    print(f"Wrote {len(write_samples((toy_world(), sensor_counter_world(), computer_world()), root))} samples")


if __name__ == "__main__":
    main()
