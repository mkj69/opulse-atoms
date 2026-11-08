"""Targets and reproducible seeds for available generator world adapters."""

from __future__ import annotations

import importlib.util

from opulse.atoms.golden import WORLDS as CLASSIC_WORLDS

FLAGSHIPS = frozenset({"integer", "pixels", "action", "circuits", "dice"})
CATALOGUE = ("lists", "circuits", "action", "versions", "integer", "pixels",
             "dice", "rhythm", "hidden", "grammar", "automata", "calendar",
             "geometry", "kitchen", "melody", "molecules", "permutation",
             "roads", "shadows", "text")
# computer@2 is a tasks-owned world; its adapter is available only when that world is installed.
def world_installed(module: str) -> bool:
    """True when a world module (not only a leftover package directory) can be imported."""
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


if world_installed("opulse.worlds_v2.computer2.world"):
    CATALOGUE += ("computer",)


def available_adapters():
    """Return available adapters and explanations for adapters not yet installed."""
    ready = {}
    missing = {}
    for name in CATALOGUE:
        if importlib.util.find_spec(f"opulse.gen_v2.worlds.{name}") is None:
            missing[name] = f"opulse.gen_v2.worlds.{name} is not installed"
        else:
            ready[name] = name
    for name in CLASSIC_WORLDS:
        ready[f"classic:{name}"] = f"classic:{name}"
    return ready, missing


WORLDS = {
    name: {"adapter": adapter, "target": 1000 if name in FLAGSHIPS else 300,
           "per_kind_min": 0 if name.startswith("classic:") else 50,
           "layer_target": 10,
           "time_limit": 14400 if name in FLAGSHIPS else 7200,
           "max_attempts": (150000 if name in FLAGSHIPS else
                            60000 if name.startswith("classic:") else 120000), "seed": 1,
           "flagship": name in FLAGSHIPS}
    for name, adapter in available_adapters()[0].items()
}

for _name in ("lists", "action", "circuits"):
    if _name in WORLDS:
        WORLDS[_name]["move_weights"] = {"obj.refine": 0, "obj.seal": 0}

if "versions" in WORLDS:
    WORLDS["versions"]["move_weights"] = {"obs.memory": 0}
