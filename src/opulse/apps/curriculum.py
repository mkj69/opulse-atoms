"""Difficulty policy shared by training streams and evaluation."""

from __future__ import annotations

from dataclasses import dataclass


def ladder(world: str, level: int) -> dict:
    """Five monotonic knobs; a world provider may map them to native controls."""
    if type(level) is not int or level not in range(1, 6):
        raise ValueError("level must be 1..5")
    profiles = {"integer": {"magnitude": 10 ** level},
                "successor": {"magnitude": 10 ** level},
                "clock": {"modulus": 4 + 2 * level},
                "bits": {"bit_width": 2 + 2 * level},
                "logic": {"variable_count": 1 + level},
                "strings": {"max_length": 2 + 2 * level},
                "lists": {"max_length": 2 + 2 * level},
                "perm": {"permutation_size": 2 + level},
                "rel": {"entity_count": 2 + level},
                "grid": {"side": 2 + level},
                "pitch": {"melody_length": 2 + level},
                "action": {"horizon": 2 * level},
                "computer": {"horizon": 2 * level}}
    return {"world": world, "level": level, "boundary_depth": level - 1,
            "composition_depth": level, "distractors": level - 1,
            "observation_budget": max(1, 6 - level), "max_turns": 2 * level,
            "world_knobs": profiles.get(world.split("@")[0], {"domain_size": 2 ** level})}


@dataclass
class Curriculum:
    """Advance/retreat on a rolling success window, with a minimum sample count."""

    world: str
    level: int = 1
    window: int = 20
    promote_at: float = 0.8
    demote_below: float = 0.3

    def __post_init__(self):
        if self.window < 1 or not 0 <= self.demote_below < self.promote_at <= 1:
            raise ValueError("invalid curriculum thresholds")
        ladder(self.world, self.level)
        self._scores: list[float] = []

    def observe(self, result: dict | float) -> int:
        score = result["reward"] if isinstance(result, dict) else result
        if not 0 <= score <= 1:
            raise ValueError("reward must be in [0, 1]")
        self._scores.append(float(score))
        if len(self._scores) >= self.window:
            mean = sum(self._scores[-self.window:]) / self.window
            if mean >= self.promote_at and self.level < 5:
                self.level += 1
                self._scores.clear()
            elif mean < self.demote_below and self.level > 1:
                self.level -= 1
                self._scores.clear()
        return self.level

    def make(self, **kwargs):
        from opulse.apps import make

        return make(self.world, level=self.level, **kwargs)
