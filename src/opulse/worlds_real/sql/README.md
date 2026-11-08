# Real SQL: small relational tables

This world teaches **SQLite SELECT**, not an invented SQL-like algebra. `reference.py`
evaluates a typed query tree without SQLite; `oracle.sqlite_result` constructs independent
in-memory SQLite tables and runs the rendered query. `oracle.cross_check(2400)`
checks 20 seeded families (including empty, duplicated and NULL rows). The tests
run a further 200 cases with disjoint seeds. Failures report the seed and SQL.

## Contract

- Tables contain finite, schema-checked signed 64-bit `INT` and `TEXT` values or `NULL`, no boolean
  values. Mixed TEXT/numeric comparisons requiring SQL affinity are rejected;
  comparisons use binary text collation.
- SELECT ALL returns a **bag**. `DISTINCT` turns projected rows into a set.
  Without `ORDER BY` observations and grading compare bags, not row sequences;
  with `ORDER BY` showcased/generated queries use unique ordering keys or
  identical rows on tied keys, so the sequence is exactly checkable.
- `NULL = NULL` is UNKNOWN; `IS NULL` is TRUE. AND/OR use SQL three-valued logic.
  WHERE/ON retain only TRUE, not UNKNOWN. LEFT JOIN emits one NULL-extended row
  when there is no match; predicates in ON differ from predicates in WHERE.
- GROUP BY combines NULL keys. `COUNT(*)` counts rows, `COUNT(expr)` skips NULL;
  SUM/AVG/MIN/MAX skip NULL and yield NULL on no non-NULL input. A global
  aggregate on zero input returns one row; grouping zero input returns no rows.
- Supports INNER/LEFT JOIN, WHERE, GROUP BY, DISTINCT, stable multi-key ORDER BY,
  aggregate expressions, correlated EXISTS/scalar subqueries and derived tables.
  Scalar subqueries take the first row or NULL when empty, as SQLite does.
  No HAVING, window functions, arbitrary SQL strings, implicit affinity casts,
  collation overrides, or recursive SQL. Grouped output selects only group keys,
  aggregates and literals; global aggregates select only aggregates and literals.
  No assumption of order without ORDER BY.
- Observation `?rows` exposes only selected columns, `?schema` their names (not typed `Schema`),
  `?bag` multiplicities, `?ordered` requires ORDER BY and `?null_count` counts
  projected NULL cells. Tasks supply base data when needed; otherwise hidden
  tables are not observable.

`declaration.WORLD` contains all four kinds at layer 0 in ASCII notation and
the binding tag object. `declaration.STORY` has ten layers of recognized SQL
abstractions (all four kinds); `declaration.LADDER` describes five levels.
`oracle.generate_level(level, seed)` produces executable, oracle-checkable
instances at each level, including correlated scalar and EXISTS queries at level 5.
`showcase.tasks()` supplies hard Compute, Invert, Decide, Induce and Create
problems and `showcase.grade()` checks their concrete answers by executing SQL
in SQLite. A Create answer is a query AST, never string-matched SQL.

Run: `PYTHONPATH=src pytest tests/worlds_real/sql -q`.
