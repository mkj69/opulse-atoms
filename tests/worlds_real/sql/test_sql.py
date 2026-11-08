"""SQLite is an independent oracle, never the implementation under test."""

from dataclasses import replace

import pytest

from opulse.worlds_real.sql import oracle
from opulse.worlds_real.sql.declaration import LADDER, STORY, TAGS, WORLD
from opulse.worlds_real.sql.observations import observe
from opulse.worlds_real.sql.oracle import (
    cross_check,
    equivalent,
    generate_level,
    sqlite_result,
)
from opulse.worlds_real.sql.reference import (
    Aggregate,
    Binary,
    Column,
    Database,
    Exists,
    Join,
    Literal,
    Order,
    Query,
    Select,
    Source,
    Table,
    evaluate,
)
from opulse.worlds_real.sql.showcase import (
    creation_candidates,
    fixture,
    grade,
    prompt_payload,
    tasks,
)


def test_2400_generated_cases_match_sqlite():
    assert cross_check(2400) == 2400


def test_200_more_independent_cases_match_sqlite():
    assert cross_check(200, 100000) == 200


@pytest.mark.parametrize("level", (1, 2, 3, 4, 5))
def test_ladder_generates_oracle_checked_queries(level):
    for seed in range(40):
        database, query = generate_level(level, seed)
        assert equivalent(database, query)


def test_bags_nulls_and_left_join_on_vs_where():
    database = fixture()
    query = Query(Source("p", "p"),
                  (Select(Column("p", "id"), "id"), Select(Column("c", "amount"), "amount")),
                  joins=(Join("LEFT", Source("c", "c"),
                              Binary("=", Column("p", "id"), Column("c", "pid"))),),
                  order_by=(Order("id"), Order("amount")))
    assert evaluate(database, query) == ((0, None), (0, 2), (0, 2),
                                          (1, None), (2, None), (3, 0), (4, None))
    assert sqlite_result(database, query) == evaluate(database, query)
    assert observe(database, query, "bag")[(0, 2)] == 2
    assert observe(database, query, "null_count") == 4
    assert observe(database, query, "schema") == ("id", "amount")
    assert equivalent(database, query)
    assert evaluate(database, Query(Source("p", "p"), (Select(Column("p", "id"), "id"),),
                                    where=Binary("=", Column("p", "v"), Literal(None)))) == ()


def test_empty_aggregate_and_group_null():
    database = Database((Table("t", (("a", "INT"),), ()),))
    query = Query(Source("t", "t"),
                  (Select(Aggregate("COUNT"), "all"),
                   Select(Aggregate("COUNT", Column("t", "a")), "nonnull"),
                   Select(Aggregate("SUM", Column("t", "a")), "total"),
                   Select(Aggregate("AVG", Column("t", "a")), "mean")))
    assert evaluate(database, query) == sqlite_result(database, query) == ((0, 0, None, None),)
    rows = Database((Table("t", (("a", "INT"),), ((None,), (None,), (0,))),))
    grouped = Query(Source("t", "t"), (Select(Column("t", "a"), "a"),
                                        Select(Aggregate("COUNT"), "n")),
                    group_by=(Column("t", "a"),), order_by=(Order("a"),))
    assert evaluate(rows, grouped) == sqlite_result(rows, grouped) == ((None, 2), (0, 1))


def test_distinct_and_count_distinct_ignore_null():
    database = Database((Table("t", (("v", "INT"),), ((None,), (None,), (2,), (2,), (3,))),))
    bag = Query(Source("t", "t"), (Select(Column("t", "v"), "v"),))
    unique = Query(Source("t", "t"), (Select(Column("t", "v"), "v"),), distinct=True)
    counted = Query(Source("t", "t"),
                    (Select(Aggregate("COUNT"), "all"),
                     Select(Aggregate("COUNT", Column("t", "v")), "nonnull"),
                     Select(Aggregate("COUNT", Column("t", "v"), True), "unique")))
    assert len(evaluate(database, bag)) == len(sqlite_result(database, bag)) == 5
    assert observe(database, bag, "bag")[(2,)] == 2
    assert len(evaluate(database, unique)) == len(sqlite_result(database, unique)) == 3
    assert evaluate(database, counted) == sqlite_result(database, counted) == ((5, 3, 2),)


def test_declaration_and_story():
    assert set(WORLD["open_kinds"]) == {"object", "operation", "combinator", "observation"}
    assert set(TAGS) == {"domain", "modalities", "open_kinds", "star_kind", "reasoning", "state",
                         "outcomes", "visibility", "agents", "scale", "difficulty", "uses"}
    assert len(STORY) == 10 and len(LADDER) == 5
    assert {entry[1] for entry in STORY} == set(WORLD["open_kinds"])
    for kind, prefix in (("objects", "obj "), ("operations", "op "),
                         ("combinators", "comb @"), ("observations", "obs ?")):
        assert all(item.startswith(prefix) and item.endswith("given") for item in WORLD[kind])


def test_showcases_sqlite_verification():
    examples = tasks()
    assert tuple(task.kind for task in examples) == ("Compute", "Invert", "Decide", "Induce", "Create")
    for task in examples:
        assert grade(task, task.query if task.kind == "Create" else task.answer)
        assert task.query is not None
        payload = prompt_payload(task)
        assert payload["databases"] and "answer" not in payload
        if task.kind == "Invert":
            assert payload["databases"][0][1]["rows"][-1] == (99, 0, None)
            assert payload["observed"] == ((None, 7, 2, 5),)
        for database in task.databases:
            assert equivalent(database, task.query)
    assert not grade(examples[0], ())
    assert not grade(examples[1], 0)
    assert not grade(examples[2], True)
    assert not grade(examples[3], "count_rows")
    assert not grade(examples[4], creation_candidates()["null_amount"])


def test_invalid_input_rejected():
    with pytest.raises(ValueError, match="type"):
        Table("bad", (("a", "INT"),), ((True,),))
    with pytest.raises(ValueError, match="identifier"):
        Table("bad; DROP TABLE p", (("a", "INT"),), ())
    with pytest.raises(ValueError, match="ORDER BY"):
        Query(Source("p", "p"), (Select(Literal(1), "one"),), order_by=(Order("not_selected"),))
    with pytest.raises(ValueError, match="requires ORDER BY"):
        observe(fixture(), Query(Source("p", "p"), (Select(Literal(1), "one"),)), "ordered")
    with pytest.raises(ValueError, match="level"):
        generate_level(6, 1)
    mixed = Query(Source("p", "p"), (Select(Column("p", "id"), "id"),),
                  where=Binary("=", Column("p", "label"), Literal(1)))
    with pytest.raises(ValueError, match="affinity"):
        evaluate(fixture(), mixed)


def test_inner_alias_shadows_correlated_outer_alias():
    database = fixture()
    inner = Query(Source("p", "p"), (Select(Column("p", "id"), "id"),),
                  where=Binary("=", Column("p", "id"), Column("c", "pid")))
    query = Query(Source("p", "p"), (Select(Column("p", "id"), "id"),),
                  joins=(Join("INNER", Source("c", "c"),
                              Binary("=", Column("p", "id"), Column("c", "pid"))),),
                  where=Exists(inner), order_by=(Order("id"),))
    assert evaluate(database, query) == sqlite_result(database, query)


def test_create_grading_accepts_different_order_without_requested_order():
    task = tasks()[-1]
    reversed_query = replace(task.query, order_by=(Order("id", descending=True),))
    assert grade(task, reversed_query)


@pytest.mark.parametrize("answer", [
    Query(Source("missing", "m"), (Select(Column("m", "id"), "id"),)),
    Query(Source("p", "p"), (Select(Column("p", "missing"), "id"),)),
    Query(Source("p", "p"), (Select(Binary("?", Literal(1), Literal(2)), "id"),)),
])
def test_create_grading_rejects_invalid_queries_without_raising(answer):
    reasons = []
    assert grade(tasks()[-1], answer, reasons) is False
    assert reasons and reasons[0]


def test_create_grading_honors_explicit_order_requirement():
    task = replace(tasks()[-1], ordered=True)
    reversed_query = replace(task.query, order_by=(Order("id", descending=True),))
    assert not grade(task, reversed_query)


def test_create_grading_explains_incorrect_results():
    reasons = []
    assert not grade(tasks()[-1], creation_candidates()["all_parents"], reasons)
    assert reasons == ["Submitted query does not match expected results"]


@pytest.mark.parametrize("value", [-(2**63) - 1, 2**63])
def test_table_rejects_ints_sqlite_cannot_store(value):
    with pytest.raises(ValueError, match="64-bit"):
        Table("t", (("n", "INT"),), ((value,),))


@pytest.mark.parametrize("value", [-(2**63), 2**63 - 1])
def test_table_accepts_sqlite_int_boundaries(value):
    database = Database((Table("t", (("n", "INT"),), ((value,),)),))
    query = Query(Source("t", "t"), (Select(Column("t", "n"), "n"),))
    assert evaluate(database, query) == sqlite_result(database, query) == ((value,),)


def test_schema_declaration_matches_names_only_observation():
    database = fixture()
    query = Query(Source("p", "p"), (Select(Column("p", "id"), "id"),))
    assert observe(database, query, "schema") == ("id",)
    assert "-> ColumnNames given" in WORLD["observations"][0]
    assert any("obj ColumnNames" in item for item in WORLD["objects"])


def test_sqlite_execution_owned_by_oracle_module():
    assert oracle.sqlite_result.__module__ == oracle.__name__
    assert oracle.equivalent.__module__ == oracle.__name__
