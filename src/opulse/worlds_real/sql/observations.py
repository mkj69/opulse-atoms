"""Observations expose query output, not the hidden source database."""

from __future__ import annotations

from collections import Counter

from .reference import Database, Query, evaluate


def observe(db: Database, query: Query, view: str = "rows") -> object:
    rows = evaluate(db, query)
    if view == "schema":
        return tuple(item.alias for item in query.select)
    if view == "rows":
        return rows
    if view == "bag":
        return Counter(rows)
    if view == "ordered":
        if not query.order_by:
            raise ValueError("ordered observation requires ORDER BY")
        return rows
    if view == "null_count":
        return sum(value is None for row in rows for value in row)
    raise ValueError(f"unknown observation: {view}")
