"""The corruptions. Each one is a way real data goes wrong in production.

A mutation is deliberately small and *plausible*. Setting every value in a table
to NULL would be caught by anything; the useful mutations are the ones a tired
pipeline actually produces at 3am -- a nulled column in a few rows, one duplicated
key, a foreign key pointing at a customer who was deleted last week.

Targets are DISCOVERED from the warehouse, never typed. A typed list of tables can
only contain the ones somebody remembered, and the point of this tool is to find
what nobody was watching.

Every mutation reports whether it actually CHANGED anything. A mutation that
silently did nothing -- a column already full of NULLs, a table with one row and
nothing to duplicate -- must never be reported as "no test caught it", because
nothing happened for a test to catch. That distinction is the whole difference
between a measurement and a number.
"""
from __future__ import annotations

import dataclasses
from typing import Callable


@dataclasses.dataclass(frozen=True)
class Target:
    """One column in one table, as found in the warehouse."""

    schema: str
    table: str
    column: str
    dtype: str

    @property
    def fqn(self) -> str:
        return f'"{self.schema}"."{self.table}"'

    def __str__(self) -> str:
        return f"{self.table}.{self.column}"


@dataclasses.dataclass(frozen=True)
class Mutation:
    """A named corruption, in plain words, with the SQL that performs it."""

    name: str
    #: What went wrong in the real world, for somebody reading the report cold.
    story: str
    target: Target
    sql: str

    def __str__(self) -> str:
        return f"{self.name} on {self.target}"


NUMERIC = ("INTEGER", "BIGINT", "DOUBLE", "DECIMAL", "HUGEINT", "FLOAT", "SMALLINT")
TEXTUAL = ("VARCHAR", "TEXT", "CHAR")
TEMPORAL = ("DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE")

#: Rows touched by a partial mutation. Small on purpose: a corruption that hits
#: every row is caught by tests that a realistic one walks straight past.
BLAST = 3


#: Schemas DuckDB keeps for itself. Everything else belongs to the project.
SYSTEM_SCHEMAS = ("information_schema", "pg_catalog", "main.information_schema")


def discover(con, schema: str | None = None) -> list[Target]:
    """Every column of every real table, read out of the warehouse itself.

    `schema=None` means every schema the project owns, DISCOVERED rather than
    assumed. The first version hardcoded "main", which is jaffle_shop's default
    and nothing more -- the second real project tried used "analytics" and the
    tool found no tables at all, then had nothing to say. A default that happens
    to match the example you developed against is a typed scope wearing a
    sensible-looking name.
    """
    if schema is not None:
        where, params = "c.table_schema = ?", [schema]
    else:
        marks = ", ".join("?" for _ in SYSTEM_SCHEMAS)
        where, params = f"c.table_schema not in ({marks})", list(SYSTEM_SCHEMAS)
    rows = con.execute(
        f"""
        select c.table_schema, c.table_name, c.column_name, c.data_type
          from information_schema.columns c
          join information_schema.tables t
            on t.table_schema = c.table_schema and t.table_name = c.table_name
         where t.table_type = 'BASE TABLE' and {where}
         order by c.table_schema, c.table_name, c.ordinal_position
        """,
        params,
    ).fetchall()
    return [Target(*r) for r in rows]


def _key_of(t: Target) -> str:
    return f'"{t.column}"'


def blank_required(t: Target) -> Mutation | None:
    """A column that should always be filled arrives empty for a few rows."""
    return Mutation(
        "blank_required",
        f"{BLAST} rows arrive with {t.column} empty",
        t,
        f'update {t.fqn} set {_key_of(t)} = NULL where rowid in '
        f'(select rowid from {t.fqn} where {_key_of(t)} is not null limit {BLAST})',
    )


def duplicate_key(t: Target) -> Mutation | None:
    """A row is loaded twice -- the classic re-run-the-job-by-hand mistake."""
    return Mutation(
        "duplicate_key",
        f"one row of {t.table} is loaded twice, so {t.column} is no longer unique",
        t,
        f"insert into {t.fqn} select * from {t.fqn} limit 1",
    )


def drop_rows(t: Target) -> Mutation | None:
    """Silent partial data loss: some rows simply never arrive."""
    return Mutation(
        "drop_rows",
        f"{BLAST} rows of {t.table} never arrive, and nothing errors",
        t,
        f"delete from {t.fqn} where rowid in (select rowid from {t.fqn} limit {BLAST})",
    )


def empty_table(t: Target) -> Mutation | None:
    """Yesterday's load never ran. The table is there and it is empty."""
    return Mutation(
        "empty_table",
        f"{t.table} is empty -- the load never ran, and the table still exists",
        t,
        f"delete from {t.fqn}",
    )


def break_reference(t: Target) -> Mutation | None:
    """A foreign key points at something that is not there."""
    if t.dtype not in NUMERIC:
        return None
    return Mutation(
        "break_reference",
        f"{BLAST} rows point at a {t.column} that does not exist anywhere",
        t,
        f'update {t.fqn} set {_key_of(t)} = 999999999 where rowid in '
        f'(select rowid from {t.fqn} limit {BLAST})',
    )


def negative_amount(t: Target) -> Mutation | None:
    """A sign flip -- the mistake that quietly reverses revenue."""
    if t.dtype not in NUMERIC:
        return None
    return Mutation(
        "negative_amount",
        f"{t.column} comes through negative, reversing the sign",
        t,
        f'update {t.fqn} set {_key_of(t)} = -abs({_key_of(t)}) where rowid in '
        f'(select rowid from {t.fqn} limit {BLAST})',
    )


def unexpected_category(t: Target) -> Mutation | None:
    """An upstream system starts sending a status nobody agreed to."""
    if t.dtype not in TEXTUAL:
        return None
    return Mutation(
        "unexpected_category",
        f"{t.column} starts arriving as an unagreed value from upstream",
        t,
        f"""update {t.fqn} set {_key_of(t)} = 'UNKNOWN_FROM_UPSTREAM' where rowid in """
        f"(select rowid from {t.fqn} limit {BLAST})",
    )


def future_date(t: Target) -> Mutation | None:
    """A timezone or epoch bug throws dates far into the future."""
    if t.dtype not in TEMPORAL:
        return None
    return Mutation(
        "future_date",
        f"{t.column} lands 100 years in the future, the shape of an epoch bug",
        t,
        f"""update {t.fqn} set {_key_of(t)} = {_key_of(t)} + INTERVAL 100 YEAR where rowid in """
        f"(select rowid from {t.fqn} limit {BLAST})",
    )


#: Every corruption this tool knows how to perform. Order is stable so two runs
#: over the same warehouse produce the same report.
CATALOGUE: tuple[Callable[[Target], Mutation | None], ...] = (
    blank_required,
    duplicate_key,
    drop_rows,
    empty_table,
    break_reference,
    negative_amount,
    unexpected_category,
    future_date,
)


def plan(targets: list[Target]) -> list[Mutation]:
    """Every mutation that makes sense for every discovered column.

    `empty_table` and `duplicate_key` are per-TABLE, not per-column: applying
    them once per column would run the same corruption a dozen times and inflate
    the denominator, which would make the survival rate look better than it is.
    """
    # `drop_rows` was per-COLUMN in the first version, which ran the identical
    # DELETE once for every column in the table and reported it as that many
    # separate findings. On the reference project it turned one missed corruption
    # into four, padding both the denominator and the miss count. A corruption that
    # does not depend on which column it names is a TABLE-level corruption.
    out: list[Mutation] = []
    seen_tables: set[tuple[str, str]] = set()
    for t in targets:
        for make in CATALOGUE:
            per_table = make in (empty_table, duplicate_key, drop_rows)
            if per_table and (t.table, make.__name__) in seen_tables:
                continue
            m = make(t)
            if m is None:
                continue
            if per_table:
                seen_tables.add((t.table, make.__name__))
            out.append(m)
    return out
