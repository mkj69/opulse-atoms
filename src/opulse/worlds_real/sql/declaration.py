"""Layer-0 world declaration and a ten-layer, executable-SQL invention story."""

from __future__ import annotations

TAGS = {
    "domain": "program", "modalities": ["text"],
    "open_kinds": ["object", "operation", "combinator", "observation"],
    "star_kind": "combinator", "reasoning": ["compute", "search", "counting", "equivalence", "inference"],
    "state": "stateless", "outcomes": "deterministic", "visibility": "partial", "agents": "1",
    "scale": "0-8 rows per table; 1-10 invented definitions",
    "difficulty": "single-table filtering through correlated subqueries and null-safe grouped outer joins",
    "uses": ["rl-training", "evaluation", "teaching", "experiment"],
}

WORLD = {
    "world": "real_sql", "version": 1, "dialect": "atoms-v2",
    "open_kinds": TAGS["open_kinds"], "tags": TAGS,
    "objects": [
        "obj SqlValue = compose <Null | Int(value: int) | Text(value: text)> given",
        "obj Column = compose <column(name: text, type: text, nullable: int)> given",
        "obj Schema = compose <columns(Column*)> given",
        "obj ColumnNames = compose <names(text*)> given",
        "obj Row = compose <cells(SqlValue*)> given",
        "obj Table = compose <table(name: text, schema: Schema, rows: Row*)> given",
        "obj Database = compose <tables(Table*)> given",
        "obj Query = compose <select(source: text, projection: text, predicates: text)> given",
        "obj ResultBag = compose <rows(Row*)> given",
        "obj ResultSet = refine ResultBag where distinct_rows given",
    ],
    "operations": [
        "op eq(SqlValue, SqlValue) -> SqlValue given",
        "op and(SqlValue, SqlValue) -> SqlValue given",
        "op is_null(SqlValue) -> Int given",
        "op select(Database, Query) -> ResultBag given",
        "op where(ResultBag, Query) -> ResultBag given",
        "op join(ResultBag, ResultBag, Query) -> ResultBag given",
        "op left_join(ResultBag, ResultBag, Query) -> ResultBag given",
        "op group_by(ResultBag, Query) -> ResultBag given",
        "op count(ResultBag) -> Int given",
        "op sum(ResultBag) -> SqlValue given",
        "op avg(ResultBag) -> SqlValue given",
        "op min(ResultBag) -> SqlValue given",
        "op max(ResultBag) -> SqlValue given",
        "op order_by(ResultBag, Query) -> ResultBag given",
        "op distinct(ResultBag) -> ResultSet given",
    ],
    "combinators": [
        "comb @pipe[read, filter, project](Database) -> ResultBag given",
        "comb @inner_join[left, right, on](Database) -> ResultBag given",
        "comb @left_join[left, right, on](Database) -> ResultBag given",
        "comb @correlate[outer, inner](Database) -> ResultBag given",
        "comb @derived[inner, outer](Database) -> ResultBag given",
    ],
    "observations": [
        "obs ?schema{ResultBag} -> ColumnNames given",
        "obs ?rows{ResultBag} -> ResultBag given",
        "obs ?bag{ResultBag} -> ResultBag given",
        "obs ?ordered{ResultBag} -> ResultBag given",
        "obs ?null_count{ResultBag} -> Int given",
    ],
    "semantics": {
        "bag": "SELECT ALL preserves duplicates; DISTINCT removes duplicate projected rows; GROUP BY treats NULL keys as equal",
        "null": "comparison with NULL yields UNKNOWN; WHERE and JOIN ON keep only TRUE; COUNT(*) counts rows, COUNT(expr) skips NULL",
        "order": "no ORDER BY means bag equality; with ORDER BY exact sequence requires a total output ordering",
        "visibility": "the learner sees only the selected schema and result, never hidden base tables unless provided as task input",
        "oracle": "sqlite3 in-memory, binary text collation, INT/TEXT affinity, no floating-point input",
    },
}


STORY = (
    (1, "object", "obj NonNullAmount = refine SqlValue where is_null(value) = 0 L1",
     "Filter a nullable amount before adding it; SQL: amount IS NOT NULL."),
    (2, "operation", "op positive_amount(SqlValue) -> SqlValue L2",
     "SQL: amount > 0; a NULL amount yields UNKNOWN, not FALSE."),
    (3, "combinator", "comb @paid_lines[orders, lines](Database) -> ResultBag L3",
     "SQL: orders INNER JOIN lines ON orders.id = lines.order_id AND lines.amount > 0."),
    (4, "observation", "obs ?unpaid{ResultBag} -> Int L4",
     "Count rows with NULL amount in the projected bag, including duplicate rows."),
    (5, "object", "obj CustomerTotals = compose <rows(Row*)> L5",
     "Derived table: SELECT customer_id, SUM(amount) AS total FROM orders GROUP BY customer_id."),
    (6, "operation", "op total_paid(ResultBag) -> SqlValue L6",
     "SQL: SUM(amount); empty or all-NULL groups yield NULL rather than 0."),
    (7, "combinator", "comb @per_customer[filter, sum](Database) -> ResultBag L7",
     "SQL: SELECT customer_id, SUM(amount) FROM orders WHERE amount > 0 GROUP BY customer_id."),
    (8, "observation", "obs ?multiplicities{ResultBag} -> ResultBag L8",
     "Expose the count for each projected row; a DISTINCT query makes each count one."),
    (9, "object", "obj OrphanOrders = refine ResultBag where missing_parent L9",
     "SQL: SELECT orders.id FROM orders LEFT JOIN customers ON ... WHERE customers.id IS NULL."),
    (10, "combinator", "comb @has_order[customer, correlated_orders](Database) -> ResultBag L10",
     "SQL: WHERE EXISTS (SELECT 1 FROM orders WHERE orders.customer_id = customer.id)."),
)

LADDER = (
    (1, "Filter one typed table; distinguish NULL from zero and preserve duplicate rows."),
    (2, "Combine WHERE, DISTINCT and total ORDER BY; account for bag vs set results."),
    (3, "Inner and left join with duplicate matches, missing keys and ON vs WHERE."),
    (4, "Group NULL keys; compare COUNT(*), COUNT(col), SUM and AVG on empty inputs."),
    (5, "Compose derived tables and correlated EXISTS/scalar subqueries with joins, grouping, NULLs and ties."),
)
