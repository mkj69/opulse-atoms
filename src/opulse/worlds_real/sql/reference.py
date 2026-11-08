"""Independent finite SQL interpreter, with SQLite used only by the oracle.

The AST restricts SQLite to typed INT/TEXT columns, integer arithmetic,
binary collation, qualified columns, and output-alias ORDER BY. Three-valued
predicates, bags, NULL grouping and outer-join extension are preserved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return '"' + name + '"'


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[tuple[str, str], ...]
    rows: tuple[tuple[object, ...], ...]

    def __post_init__(self):
        identifier(self.name)
        names = [name for name, _ in self.columns]
        if len(set(names)) != len(names) or not names:
            raise ValueError("columns must have distinct names")
        for name, kind in self.columns:
            identifier(name)
            if kind not in ("INT", "TEXT"):
                raise ValueError("only INT and TEXT columns are supported")
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError("row width differs from schema")
            for value, (_, kind) in zip(row, self.columns):
                if value is not None and (type(value) is not (int if kind == "INT" else str)):
                    raise ValueError("row value does not match column type")
                if kind == "INT" and value is not None and not -(2**63) <= value < 2**63:
                    raise ValueError("INT value must fit SQLite signed 64-bit range")


@dataclass(frozen=True)
class Database:
    tables: tuple[Table, ...]

    def __post_init__(self):
        if len({table.name for table in self.tables}) != len(self.tables):
            raise ValueError("duplicate table")


@dataclass(frozen=True)
class Column:
    relation: str
    name: str


@dataclass(frozen=True)
class Literal:
    value: int | str | None


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class IsNull:
    value: object
    negate: bool = False


@dataclass(frozen=True)
class Aggregate:
    op: str
    value: object | None = None
    distinct: bool = False


@dataclass(frozen=True)
class Exists:
    query: Query


@dataclass(frozen=True)
class Scalar:
    query: Query


@dataclass(frozen=True)
class Source:
    name: str
    alias: str
    query: Query | None = None


@dataclass(frozen=True)
class Join:
    kind: str
    source: Source
    on: object


@dataclass(frozen=True)
class Select:
    value: object
    alias: str


@dataclass(frozen=True)
class Order:
    alias: str
    descending: bool = False


@dataclass(frozen=True)
class Query:
    source: Source
    select: tuple[Select, ...]
    joins: tuple[Join, ...] = ()
    where: object | None = None
    group_by: tuple[object, ...] = ()
    distinct: bool = False
    order_by: tuple[Order, ...] = ()

    def __post_init__(self):
        names = [item.alias for item in self.select]
        if not names or len(names) != len(set(names)):
            raise ValueError("select aliases must be nonempty and distinct")
        for name in names:
            identifier(name)
        if any(item.alias not in names for item in self.order_by):
            raise ValueError("ORDER BY must reference output aliases")


def expression_sql(expr: object) -> str:
    if isinstance(expr, Column):
        return f"{identifier(expr.relation)}.{identifier(expr.name)}"
    if isinstance(expr, Literal):
        value = expr.value
        if value is None:
            return "NULL"
        if type(value) is int:
            return str(value)
        if type(value) is str:
            return "'" + value.replace("'", "''") + "'"
        raise ValueError("literal must be INT, TEXT or NULL")
    if isinstance(expr, Binary):
        if expr.op not in ("=", "!=", "<", "<=", ">", ">=", "+", "-", "AND", "OR"):
            raise ValueError("unsupported operator")
        return f"({expression_sql(expr.left)} {expr.op} {expression_sql(expr.right)})"
    if isinstance(expr, IsNull):
        return f"({expression_sql(expr.value)} IS {'NOT ' if expr.negate else ''}NULL)"
    if isinstance(expr, Aggregate):
        if expr.op not in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            raise ValueError("unsupported aggregate")
        if expr.value is None:
            if expr.op != "COUNT" or expr.distinct:
                raise ValueError("only COUNT supports *")
            return "COUNT(*)"
        return f"{expr.op}({'DISTINCT ' if expr.distinct else ''}{expression_sql(expr.value)})"
    if isinstance(expr, Exists):
        return f"EXISTS ({render(expr.query)})"
    if isinstance(expr, Scalar):
        if len(expr.query.select) != 1:
            raise ValueError("scalar subquery must have one column")
        return f"({render(expr.query)})"
    raise ValueError(f"unsupported expression: {expr!r}")


def source_sql(source: Source) -> str:
    identifier(source.alias)
    return f"({render(source.query)}) AS {identifier(source.alias)}" if source.query else (
        f"{identifier(source.name)} AS {identifier(source.alias)}")


def render(query: Query) -> str:
    parts = ["SELECT", "DISTINCT" if query.distinct else "",
             ", ".join(f"{expression_sql(item.value)} AS {identifier(item.alias)}" for item in query.select),
             "FROM", source_sql(query.source)]
    for join in query.joins:
        if join.kind not in ("INNER", "LEFT"):
            raise ValueError("only INNER and LEFT joins are supported")
        parts.append(f"{join.kind} JOIN {source_sql(join.source)} ON {expression_sql(join.on)}")
    if query.where is not None:
        parts.append("WHERE " + expression_sql(query.where))
    if query.group_by:
        parts.append("GROUP BY " + ", ".join(map(expression_sql, query.group_by)))
    if query.order_by:
        parts.append("ORDER BY " + ", ".join(
            identifier(item.alias) + (" DESC" if item.descending else " ASC") for item in query.order_by))
    return " ".join(part for part in parts if part)


def _key(value: object) -> tuple[int, object]:
    return (0, 0) if value is None else (1, value) if type(value) in (int, float) else (2, value.encode("utf-8"))


def _truth(value: object) -> bool | None:
    if value is None:
        return None
    if type(value) in (int, float):
        return value != 0
    if type(value) is str:
        try:
            return float(value) != 0
        except ValueError:
            return False
    raise ValueError("unsupported SQL truth value")


def _bad_aggregate():
    raise ValueError("unsupported aggregate")


def _expr(expr: object, row: dict[str, object], db: Database, group: list[dict] | None = None) -> object:
    if isinstance(expr, Column):
        key = f"{expr.relation}.{expr.name}"
        if key not in row:
            raise ValueError(f"unknown column: {key}")
        return row[key]
    if isinstance(expr, Literal):
        if expr.value is not None and type(expr.value) not in (int, str):
            raise ValueError("literal must be INT, TEXT or NULL")
        return expr.value
    if isinstance(expr, Aggregate):
        if group is None:
            raise ValueError("aggregate outside group")
        if expr.value is None:
            return len(group) if expr.op == "COUNT" and not expr.distinct else _bad_aggregate()
        values = [_expr(expr.value, member, db) for member in group]
        values = [value for value in values if value is not None]
        if expr.distinct:
            values = list(dict.fromkeys(values))
        if expr.op == "COUNT":
            return len(values)
        if expr.op == "SUM":
            return sum(values) if values else None
        if expr.op == "AVG":
            return float(sum(values) / len(values)) if values else None
        if expr.op == "MIN":
            return min(values, key=_key) if values else None
        if expr.op == "MAX":
            return max(values, key=_key) if values else None
        return _bad_aggregate()
    if isinstance(expr, Exists):
        return int(bool(evaluate(db, expr.query, row)))
    if isinstance(expr, Scalar):
        result = evaluate(db, expr.query, row)
        if len(expr.query.select) != 1:
            raise ValueError("scalar subquery must have one column")
        return result[0][0] if result else None
    if isinstance(expr, IsNull):
        result = _expr(expr.value, row, db, group) is None
        return int(not result if expr.negate else result)
    if isinstance(expr, Binary):
        left = _expr(expr.left, row, db, group)
        right = _expr(expr.right, row, db, group)
        if expr.op in ("AND", "OR"):
            first, second = _truth(left), _truth(right)
            if expr.op == "AND":
                return 0 if first is False or second is False else None if None in (first, second) else 1
            return 1 if first is True or second is True else None if None in (first, second) else 0
        if left is None or right is None:
            return None
        if expr.op in ("+", "-"):
            if type(left) is not int or type(right) is not int:
                raise ValueError("arithmetic requires INT")
            return left + right if expr.op == "+" else left - right
        if (type(left) is str) != (type(right) is str):
            raise ValueError("mixed TEXT/numeric comparisons require SQLite affinity and are outside this subset")
        if expr.op in ("=", "!="):
            return int((left == right) if expr.op == "=" else (left != right))
        first, second = _key(left), _key(right)
        return int({"<": first < second, "<=": first <= second,
                    ">": first > second, ">=": first >= second}[expr.op])
    raise ValueError(f"unsupported expression: {expr!r}")


def _source(db: Database, source: Source, outer: dict) -> tuple[list[dict], tuple[str, ...]]:
    if source.query is not None:
        columns = tuple(item.alias for item in source.query.select)
        rows = evaluate(db, source.query, outer)
    else:
        table = next((table for table in db.tables if table.name == source.name), None)
        if table is None:
            raise ValueError(f"unknown table: {source.name}")
        columns = tuple(name for name, _ in table.columns)
        rows = table.rows
    keys = tuple(f"{source.alias}.{name}" for name in columns)
    return [dict(zip(keys, values)) for values in rows], keys


def _has_aggregate(expr: object) -> bool:
    if isinstance(expr, Aggregate):
        return True
    if isinstance(expr, Binary):
        return _has_aggregate(expr.left) or _has_aggregate(expr.right)
    if isinstance(expr, IsNull):
        return _has_aggregate(expr.value)
    return False


def evaluate(db: Database, query: Query, outer: dict[str, object] | None = None) -> tuple[tuple[object, ...], ...]:
    """Return result rows as a bag; order is significant only with total ORDER BY."""
    outer = {} if outer is None else outer
    rows, keys = _source(db, query.source, outer)
    rows = [{**outer, **row} for row in rows]
    for join in query.joins:
        right, right_keys = _source(db, join.source, outer)
        if set(keys) & set(right_keys):
            raise ValueError("duplicate relation alias")
        joined = []
        for left_row in rows:
            matches = [{**left_row, **entry} for entry in right
                       if _truth(_expr(join.on, {**left_row, **entry}, db)) is True]
            joined.extend(matches if matches else ([{**left_row, **dict.fromkeys(right_keys)}]
                                                     if join.kind == "LEFT" else []))
        rows, keys = joined, (*keys, *right_keys)
    if query.where is not None:
        rows = [row for row in rows if _truth(_expr(query.where, row, db)) is True]
    aggregate = any(_has_aggregate(item.value) for item in query.select)
    if query.group_by:
        grouped: dict[tuple, list[dict]] = {}
        for row in rows:
            grouped.setdefault(tuple(_expr(expr, row, db) for expr in query.group_by), []).append(row)
        groups = list(grouped.values())
    elif aggregate:
        groups = [rows]
    else:
        groups = [[row] for row in rows]
    result = [tuple(_expr(item.value, group[0] if group else outer, db, group if aggregate else None)
                    for item in query.select) for group in groups]
    if query.distinct:
        result = list(dict.fromkeys(result))
    aliases = [item.alias for item in query.select]
    for ordering in reversed(query.order_by):
        index = aliases.index(ordering.alias)
        result.sort(key=lambda row: _key(row[index]), reverse=ordering.descending)
    return tuple(result)
