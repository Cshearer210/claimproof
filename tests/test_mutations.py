"""The corruption catalogue: does it produce sane, non-duplicated, typed work?

These run against a real DuckDB in memory rather than a mock, because the whole
point of a mutation is that it changes a real table, and a mock would happily
accept SQL that no database would.
"""
import duckdb
import pytest

from deadcanary.mutations import (
    BLAST, CATALOGUE, Target, blank_required, discover, drop_rows,
    duplicate_key, empty_table, future_date, negative_amount, plan,
    unexpected_category,
)


@pytest.fixture
def warehouse():
    con = duckdb.connect(":memory:")
    con.execute("create table orders (id integer, customer_id integer, "
                "placed_at date, status varchar, amount double)")
    con.execute("insert into orders select i, i % 7, "
                "DATE '2020-01-01' + INTERVAL (i) DAY, 'placed', i * 1.5 "
                "from range(40) t(i)")
    yield con
    con.close()


def test_targets_are_discovered_from_the_warehouse_not_typed(warehouse):
    """A typed table list can only contain what somebody remembered."""
    found = discover(warehouse)
    assert {t.table for t in found} == {"orders"}
    assert {t.column for t in found} == {"id", "customer_id", "placed_at", "status", "amount"}


def test_a_view_is_not_a_target(warehouse):
    """Corrupting a view does nothing -- it is derived from the table beneath it."""
    warehouse.execute("create view recent as select * from orders")
    assert all(t.table != "recent" for t in discover(warehouse))


# ---------------------------------------------------------------- typing

def test_numeric_only_mutations_refuse_a_text_column():
    text = Target("main", "orders", "status", "VARCHAR")
    assert negative_amount(text) is None
    assert future_date(text) is None


def test_text_only_mutations_refuse_a_number():
    num = Target("main", "orders", "amount", "DOUBLE")
    assert unexpected_category(num) is None


def test_date_mutation_only_applies_to_dates():
    assert future_date(Target("main", "o", "placed_at", "DATE")) is not None
    assert future_date(Target("main", "o", "amount", "DOUBLE")) is None


# ------------------------------------------------- no duplicated corruptions

TABLE_LEVEL = {"drop_rows", "empty_table", "duplicate_key"}


def test_table_level_corruptions_run_once_per_table_not_once_per_column(warehouse):
    """The bug that inflated the first published number.

    `drop_rows` deletes rows; naming a column changes nothing about what it does.
    Run per-column it produced one identical DELETE per column and reported each
    as a separate finding -- 45 corruptions and 16 misses where the truth was
    37 and 13.
    """
    counts = {}
    for m in plan(discover(warehouse)):
        counts[m.name] = counts.get(m.name, 0) + 1
    for name in TABLE_LEVEL:
        assert counts.get(name) == 1, f"{name} ran {counts.get(name)} times, expected once"


def test_column_level_corruptions_still_run_per_column(warehouse):
    """The guard case: the dedup must not flatten the per-column corruptions too."""
    counts = {}
    for m in plan(discover(warehouse)):
        counts[m.name] = counts.get(m.name, 0) + 1
    assert counts["blank_required"] == 5, "one per column of the 5-column table"


def test_plan_is_stable_across_runs(warehouse):
    """Two runs over one warehouse must produce the same report, in the same order."""
    a = [str(m) for m in plan(discover(warehouse))]
    b = [str(m) for m in plan(discover(warehouse))]
    assert a == b


# ------------------------------------------------------ the SQL really runs

@pytest.mark.parametrize("make", CATALOGUE, ids=[f.__name__ for f in CATALOGUE])
def test_every_corruption_is_valid_sql_that_changes_something(warehouse, make):
    """A mutation that cannot execute, or that changes nothing, measures nothing."""
    typed = {"blank_required": "status", "duplicate_key": "id", "drop_rows": "id",
             "empty_table": "id", "break_reference": "customer_id",
             "negative_amount": "amount", "unexpected_category": "status",
             "future_date": "placed_at"}
    col = typed[make.__name__]
    dtype = dict(warehouse.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_name = 'orders'").fetchall())[col]

    m = make(Target("main", "orders", col, dtype))
    assert m is not None, f"{make.__name__} refused a column it should accept"

    before = warehouse.execute("select count(*) from orders").fetchone()[0]
    checksum_before = warehouse.execute(
        "select md5(string_agg(t::VARCHAR, '')) from orders t").fetchone()[0]
    warehouse.execute(m.sql)
    after = warehouse.execute("select count(*) from orders").fetchone()[0]
    checksum_after = warehouse.execute(
        "select md5(string_agg(t::VARCHAR, '')) from orders t").fetchone()[0]

    assert (before, checksum_before) != (after, checksum_after), \
        f"{m.name} ran but changed nothing"


def test_partial_corruptions_leave_most_of_the_table_alone(warehouse):
    """A corruption that hits every row is caught by anything.

    The useful ones are small enough that a careless test walks past them, which
    is why BLAST is 3 and not 'all'.
    """
    t = Target("main", "orders", "status", "VARCHAR")
    warehouse.execute(unexpected_category(t).sql)
    untouched = warehouse.execute(
        "select count(*) from orders where status = 'placed'").fetchone()[0]
    assert untouched == 40 - BLAST


def test_every_corruption_explains_itself_in_plain_words(warehouse):
    """The report is read by someone who was not there. A name is not an explanation."""
    for m in plan(discover(warehouse)):
        assert len(m.story) > 20, f"{m.name} has no story"
        assert m.target.table in m.story or m.target.column in m.story, \
            f"{m.name} story does not say what it touched: {m.story!r}"
