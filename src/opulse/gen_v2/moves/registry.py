"""Discover proposal moves without requiring every kind's module to be installed."""

from __future__ import annotations

import importlib
import pkgutil

from opulse.gen_v2.base import KINDS


def discover_moves() -> dict[str, list]:
    """Return moves in module order, grouped by kind; report missing dependencies."""
    package = importlib.import_module("opulse.gen_v2.moves")
    grouped = {kind: [] for kind in KINDS}
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda item: item.name):
        if info.name == "registry" or info.ispkg:
            continue
        module_name = f"{package.__name__}.{info.name}"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name == module_name:
                continue
            raise
        for move in getattr(module, "MOVES", ()):
            if move.kind not in grouped:
                raise ValueError(f"unknown move kind: {move.kind}")
            grouped[move.kind].append(move)
    return grouped


__all__ = ["discover_moves"]
