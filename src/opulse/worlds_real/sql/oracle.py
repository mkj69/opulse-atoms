"""Reproducible SQLite cross-checks; failures include seed, SQL and counterexample."""

from __future__ import annotations

import random
import sqlite3
from collections import Counter
from dataclasses import dataclass

from .reference import Aggregate as Agg
from .reference import Binary as Bin
from .reference import Column as Col
from .reference import (
    Database,
    Exists,
    IsNull,
    Join,
    Order,
    Query,
    Scalar,
    Select,
    Source,
    Table,
    evaluate,
    identifier,
    render,
)
from .reference import Literal as Lit


def sqlite_result(db: Database, query: Query) -> tuple[tuple[object, ...], ...]:
    """Execute rendered SQL in an isolated SQLite in-memory database."""
    with sqlite3.connect(":memory:") as connection:
        for table in db.tables:
            connection.execute(f"CREATE TABLE {identifier(table.name)} (" + ", ".join(
                f"{identifier(name)} {kind}" for name, kind in table.columns) + ")")
            connection.executemany(f"INSERT INTO {identifier(table.name)} VALUES (" +
                                   ",".join("?" for _ in table.columns) + ")", table.rows)
        return tuple(tuple(row) for row in connection.execute(render(query)))


def equivalent(db: Database, query: Query) -> bool:
    actual, expected = evaluate(db, query), sqlite_result(db, query)
    return actual == expected if query.order_by else Counter(actual) == Counter(expected)


def generated(seed: int) -> tuple[Database, Query]:
    """Twenty query families; random nullable, duplicated, empty and orphan rows."""
    rng = random.Random(seed)
    parents = tuple((index, rng.choice((None, 0, 1, 2, 3)), rng.choice((None, "a", "b", "a")))
                    for index in range(rng.randrange(7)))
    children = tuple((index, rng.choice((None, 0, 1, 2, 7)), rng.choice((None, 0, 1, 2, 2, -1)))
                     for index in range(rng.randrange(8)))
    db = Database((Table("p", (("id", "INT"), ("v", "INT"), ("label", "TEXT")), parents),
                   Table("c", (("id", "INT"), ("pid", "INT"), ("amount", "INT")), children)))
    family = seed % 20
    threshold = rng.choice((None, -1, 0, 1, 2))
    value = Col("p", "v")
    amount = Col("c", "amount")
    base = Source("p", "p")
    right = Source("c", "c")
    on = Bin("=", Col("p", "id"), Col("c", "pid"))
    if family < 4:
        predicate = (Bin("=", value, Lit(threshold)), IsNull(value),
                     Bin("OR", Bin("<", value, Lit(2)), Bin("=", value, Lit(None))),
                     Bin("AND", IsNull(value, True), Bin(">=", value, Lit(0))))[family]
        query = Query(base, (Select(Col("p", "id"), "id"), Select(value, "v")),
                      where=predicate, order_by=(Order("id"),))
    elif family < 8:
        query = Query(base, (Select(Col("p", "id"), "id"), Select(amount, "amount")),
                      joins=(Join("LEFT" if family % 2 else "INNER", right,
                                  on if family < 6 else Bin("AND", on, Bin(">", amount, Lit(0)))),),
                      where=IsNull(amount) if family == 7 else None,
                      order_by=(Order("id"), Order("amount")))
    elif family < 12:
        op = ("COUNT", "SUM", "AVG", "MAX")[family - 8]
        query = Query(base, (Select(value, "v"), Select(Agg(op, amount), "stat"),
                             Select(Agg("COUNT"), "rows")),
                      joins=(Join("LEFT", right, on),), group_by=(value,),
                      order_by=(Order("v"),))
    elif family < 14:
        query = Query(base, (Select(value, "v"), Select(Col("p", "label"), "label")),
                      distinct=True, order_by=(Order("v", family == 13), Order("label")))
    elif family < 17:
        inner = Query(Source("c", "c"), (Select(Agg("SUM" if family == 14 else "COUNT", amount
                                                        if family == 14 else None), "total"),),
                      where=Bin("=", Col("c", "pid"), Col("p", "id")))
        query = Query(base, (Select(Col("p", "id"), "id"), Select(Scalar(inner), "total")),
                      where=Exists(Query(Source("c", "x"), (Select(Lit(1), "one"),),
                                         where=Bin("=", Col("x", "pid"), Col("p", "id"))))
                      if family == 16 else None, order_by=(Order("id"),))
    else:
        inner = Query(Source("c", "c"), (Select(Col("c", "pid"), "pid"),
                                              Select(Agg("COUNT"), "n")),
                      group_by=(Col("c", "pid"),))
        query = Query(Source("", "stats", inner),
                      (Select(Col("stats", "pid"), "pid"), Select(Col("stats", "n"), "n")),
                      where=Bin(">", Col("stats", "n"), Lit(family - 18)) if family != 17 else None,
                      order_by=(Order("pid"),))
    return db, query


def generate_level(level: int, seed: int) -> tuple[Database, Query]:
    """Five reproducible difficulty levels with disjoint, escalating SQL families."""
    families = {1: (0, 1, 2, 3), 2: (12, 13), 3: (4, 5, 6, 7),
                4: (8, 9, 10, 11), 5: (14, 15, 16, 17, 18, 19)}
    if level not in families:
        raise ValueError("SQL level must be 1..5")
    family = families[level][seed % len(families[level])]
    return generated(seed * 20 + family)


@dataclass(frozen=True)
class OracleMismatch(AssertionError):
    seed: int
    sql: str
    actual: tuple
    expected: tuple

    def __str__(self) -> str:
        return f"seed={self.seed} SQL={self.sql}\nreference={self.actual}\nsqlite3={self.expected}"


def cross_check(count: int = 2400, start: int = 0) -> int:
    """Run count independently seeded cases, raising with a reproducible witness."""
    for seed in range(start, start + count):
        db, query = generated(seed)
        actual, expected = evaluate(db, query), sqlite_result(db, query)
        if actual != expected:
            raise OracleMismatch(seed, render(query), actual, expected)
    return count
