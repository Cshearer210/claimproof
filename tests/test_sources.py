"""Corrupting the FILES a source reads, for projects that never load them.

The file is the raw table for a large class of real dbt projects -- dbt-labs' own
current jaffle-shop template among them. These hold that path to the same rules
as the warehouse path: a corruption that changed nothing is a no-op, the data is
always put back, and the file that goes back is byte-identical to the one that
came out.
"""
import csv
import json
import shutil
from pathlib import Path

import pytest

from deadcanary.sources import (FILE_CORRUPTIONS, PER_FILE, apply_to_file,
                                discover_files, restore_files, snapshot_files)

ROWS = [
    ["id", "customer_id", "status", "amount"],
    ["1", "1", "placed", "10.00"],
    ["2", "1", "shipped", "25.50"],
    ["3", "2", "completed", "8.75"],
    ["4", "2", "placed", "42.00"],
    ["5", "3", "shipped", "17.25"],
]


@pytest.fixture
def project(tmp_path):
    """A dbt project whose source is a CSV on disk, as dbt records it."""
    root = tmp_path / "proj"
    (root / "target").mkdir(parents=True)
    (root / "data").mkdir()
    with (root / "data" / "raw_orders.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(ROWS)
    (root / "target" / "manifest.json").write_text(json.dumps({"sources": {
        "source.p.raw.raw_orders": {
            "name": "raw_orders",
            "meta": {"external_location": "read_csv_auto('./data/{name}.csv', header=1)"},
        }}}), encoding="utf-8")
    return root


def _read(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


# ------------------------------------------------------------- discovery

def test_source_files_are_discovered_from_the_manifest(project):
    targets = discover_files(project)
    assert {t.column for t in targets} == {"id", "customer_id", "status", "amount"}
    assert all(t.path.name == "raw_orders.csv" for t in targets)
    assert all(t.schema == "file" for t in targets)


def test_a_source_whose_file_is_missing_is_not_offered(project):
    (project / "data" / "raw_orders.csv").unlink()
    assert discover_files(project) == []


def test_a_project_with_no_external_sources_yields_nothing(tmp_path):
    """The guard case: this must stay silent on a perfectly ordinary project."""
    root = tmp_path / "plain"
    (root / "target").mkdir(parents=True)
    (root / "target" / "manifest.json").write_text(
        json.dumps({"sources": {"s.1": {"name": "raw", "meta": {}}}}), encoding="utf-8")
    assert discover_files(root) == []


def test_a_bare_csv_path_is_discovered(tmp_path):
    """Not every project wraps the file in read_csv_auto().

    `sdebruyn/inzight` writes `external_location: "assets/fluvius.csv"` -- the bare
    path, no function around it. dbt-duckdb accepts both, so a tool that only
    recognises the wrapped form reports NOTHING TO CORRUPT on a project whose raw
    data is sitting right there in a CSV.
    """
    root = tmp_path / "bare"
    (root / "target").mkdir(parents=True)
    (root / "data").mkdir()
    with (root / "data" / "raw_orders.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(ROWS)
    (root / "target" / "manifest.json").write_text(json.dumps({"sources": {"s.1": {
        "name": "raw_orders", "meta": {"external_location": "data/raw_orders.csv"}}}}),
        encoding="utf-8")

    assert {t.column for t in discover_files(root)} == {"id", "customer_id", "status", "amount"}


def test_the_external_block_is_discovered(tmp_path):
    """`dbt-external-tables` records the location somewhere else again.

    Measured on `adityawarmanfw/dbt_duckdb_chinook`: its manifest carries
    `external: {"location": "csvs/album.csv"}` and an empty `meta`, because the
    location was written by the dbt-external-tables package rather than by hand.
    Same file on disk, third place to look for it.
    """
    root = tmp_path / "ext"
    (root / "target").mkdir(parents=True)
    (root / "csvs").mkdir()
    with (root / "csvs" / "album.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(ROWS)
    (root / "target" / "manifest.json").write_text(json.dumps({"sources": {"s.1": {
        "name": "album", "meta": {}, "external": {"location": "csvs/album.csv"}}}}),
        encoding="utf-8")

    targets = discover_files(root)
    assert targets, "the external block was not read"
    assert all(t.path.name == "album.csv" for t in targets)


def test_a_location_that_is_not_a_local_file_is_not_offered(tmp_path):
    """The guard case, and the reason the bare form needs one.

    Once a bare string counts as a path, every source location that is NOT a file
    -- a bucket, a URL, a warehouse table name -- has to be turned away, or the
    tool starts reporting targets it cannot touch.
    """
    root = tmp_path / "remote"
    (root / "target").mkdir(parents=True)
    (root / "target" / "manifest.json").write_text(json.dumps({"sources": {
        "s.1": {"name": "a", "meta": {"external_location": "s3://bucket/orders.csv"}},
        "s.2": {"name": "b", "meta": {"external_location": "https://x.test/orders.csv"}},
        "s.3": {"name": "c", "meta": {"external_location": "raw.orders"}},
        "s.4": {"name": "d", "meta": {"external_location": "./nowhere/orders.csv"}},
    }}), encoding="utf-8")

    assert discover_files(root) == []


def test_a_bare_parquet_path_is_not_offered(tmp_path):
    """Binary is out of scope in the bare form too, not only the wrapped one."""
    root = tmp_path / "bpq"
    (root / "target").mkdir(parents=True)
    (root / "raw.parquet").write_bytes(b"PAR1")
    (root / "target" / "manifest.json").write_text(json.dumps({"sources": {"s.1": {
        "name": "raw", "meta": {"external_location": "raw.parquet"}}}}), encoding="utf-8")

    assert discover_files(root) == []


def test_parquet_is_recognised_but_not_corrupted(tmp_path):
    """Binary formats are out of scope, and being out of scope is not a silent skip."""
    root = tmp_path / "pq"
    (root / "target").mkdir(parents=True)
    (root / "raw.parquet").write_bytes(b"PAR1")
    (root / "target" / "manifest.json").write_text(json.dumps({"sources": {"s.1": {
        "name": "raw", "meta": {"external_location": "read_parquet('./{name}.parquet')"}}}}),
        encoding="utf-8")
    assert discover_files(root) == [], "parquet must not be offered as a CSV target"


# ------------------------------------------------------------ the edits

@pytest.mark.parametrize("name", sorted(FILE_CORRUPTIONS))
def test_every_file_corruption_actually_changes_the_file(project, name):
    targets = {t.column: t for t in discover_files(project)}
    target = targets["amount"] if name == "negative_amount" else targets["status"]

    before = _read(target.path)
    changed = apply_to_file(target, name)
    after = _read(target.path)

    assert changed > 0, f"{name} reported no change"
    assert after != before, f"{name} said it changed {changed} rows and the file is identical"


def test_the_header_always_survives(project):
    """A corruption that eats the header is not corrupt data, it is a broken file --
    dbt would fail to parse it and every test would error rather than fail."""
    target = {t.column: t for t in discover_files(project)}["status"]
    for name in FILE_CORRUPTIONS:
        shutil.copy2(target.path, target.path.with_suffix(".bak"))
        apply_to_file(target, name)
        assert _read(target.path)[0] == ROWS[0], f"{name} damaged the header"
        shutil.copy2(target.path.with_suffix(".bak"), target.path)


def test_a_corruption_that_matches_nothing_reports_zero(project):
    """No-op must be distinguishable from 'nothing caught it'."""
    target = {t.column: t for t in discover_files(project)}["status"]
    apply_to_file(target, "empty_table")             # now there are no rows left
    assert apply_to_file(target, "blank_required") == 0


def test_a_column_that_is_not_in_the_file_is_a_noop(project):
    from deadcanary.sources import FileTarget
    ghost = FileTarget("raw_orders", project / "data" / "raw_orders.csv", "not_a_column")
    assert apply_to_file(ghost, "blank_required") == 0


def test_partial_corruptions_leave_most_rows_alone(project):
    target = {t.column: t for t in discover_files(project)}["status"]
    apply_to_file(target, "unexpected_category")
    rows = _read(target.path)[1:]
    untouched = sum(1 for r in rows if r[2] != "UNKNOWN_FROM_UPSTREAM")
    assert untouched == len(ROWS) - 1 - 3


# --------------------------------------------------------- putting it back

def test_the_files_are_restored_byte_for_byte(project, tmp_path):
    """A tool that corrupts somebody's data on disk and cannot put it back exactly
    is not one anybody should run twice."""
    targets = discover_files(project)
    original = targets[0].path.read_bytes()

    saved = snapshot_files(targets, tmp_path / "backup")
    for name in FILE_CORRUPTIONS:
        apply_to_file(targets[0], name)
    assert targets[0].path.read_bytes() != original, "the test corrupted nothing"

    restore_files(saved)
    assert targets[0].path.read_bytes() == original, "the file came back different"


def test_per_file_corruptions_are_not_repeated_once_per_column():
    """Deleting rows does not depend on which column you name it after."""
    assert set(PER_FILE) == {"duplicate_key", "drop_rows", "empty_table"}
    assert all(p in FILE_CORRUPTIONS for p in PER_FILE)
