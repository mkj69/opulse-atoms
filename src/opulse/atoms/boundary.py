"""Visibility boundaries for the four atom kinds (docs/spec/atoms-v2.md, section 10)."""

from __future__ import annotations

from dataclasses import dataclass, field

from opulse.atoms import KINDS
from opulse.core.operator import Operator


@dataclass(frozen=True)
class Boundary:
    depth: int | None = None
    open_names: frozenset[str] = field(default_factory=frozenset)
    keep_names: frozenset[str] = field(default_factory=frozenset)
    open_paths: frozenset[tuple[int, ...]] = field(default_factory=frozenset)
    kinds: frozenset[str] = field(default_factory=lambda: frozenset(KINDS))

    def opens(self, defn: object, path: tuple[int, ...] = ()) -> bool:
        """Whether this call opens; legacy names match either symbol or func_id."""
        if isinstance(defn, Operator):
            given = defn.definition is None
            names = {defn.symbol, defn.func_id}
            kind = "operation"
            layer = defn.recursive_layer or 0
        else:
            given = defn.given
            names = {defn.name}
            kind = defn.kind
            layer = defn.layer
            if not path:
                path = defn.path
        return (not given and kind in self.kinds and not names.intersection(self.keep_names)
                and ((self.depth is not None and layer >= self.depth)
                     or bool(names.intersection(self.open_names)) or path in self.open_paths))

    @classmethod
    def unfold_all(cls) -> Boundary:
        return cls(depth=0)

    @classmethod
    def unfold_none(cls) -> Boundary:
        return cls()

    @classmethod
    def from_cut(cls, known=(), known_layers: int = 0) -> Boundary:
        return cls(depth=known_layers, keep_names=frozenset(known), kinds=frozenset({"operation"}))

    def to_dict(self) -> dict:
        return {"depth": self.depth, "open_names": sorted(self.open_names),
                "keep_names": sorted(self.keep_names),
                "open_paths": [list(path) for path in sorted(self.open_paths)],
                "kinds": sorted(self.kinds)}

    @classmethod
    def from_dict(cls, data: dict) -> Boundary:
        return cls(depth=data.get("depth"), open_names=frozenset(data.get("open_names", ())),
                   keep_names=frozenset(data.get("keep_names", ())),
                   open_paths=frozenset(tuple(path) for path in data.get("open_paths", ())),
                   kinds=frozenset(data.get("kinds", KINDS)))


def legacy_expand(boundary: Boundary):
    """Adapt a position-independent boundary to ``trace.tree.flatten``."""
    if boundary.open_paths:
        raise ValueError("a path-aware boundary cannot be represented by a legacy expand predicate")
    return lambda operator: boundary.opens(operator)


def flatten_calls(root, boundary: Boundary) -> list:
    """Visible kernel call steps in execution order, omitting the synthetic root."""
    visible = []

    def visit(node) -> None:
        for child in node.children:
            if not getattr(child, "fast", False) and boundary.opens(child, child.path):
                visit(child)
            else:
                visible.append(child)

    visit(root)
    return visible
