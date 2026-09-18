"""The seam, with something other than dbt plugged into it.

`QualityProject` was extracted from `DbtProject` so a second data-quality tool
could plug in. A seam nothing has ever plugged into is a claim, not a seam --
so this hunts a project that has no dbt anywhere near it.
"""
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from deadcanary.hunt import hunt
from deadcanary.project import QualityProject
from deadcanary.sqlchecks import (CHECKS_NAME, MalformedChecks, RESULTS_NAME,
                                  SqlChecksProject)

REAL = {"name": "customer_id_is_never_null",
        "sql": "select * from raw_orders where customer_id is null"}
DEAD = {"name": "impossible_check", "sql": "select * from raw_orders where 1 = 0"}


@pytest.fixture()
def project(tmp_path):
    db = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create table raw_orders (id integer, customer_id integer, note varchar)")
    con.execute("insert into raw_orders values (1, 10, 'a'), (2, 20, 'b'), (3, 30, 'c'), "
                "(4, 40, 'd'), (5, 50, 'e')")
    con.close()
    (tmp_path / CHECKS_NAME).write_text(json.dumps({"checks": [REAL, DEAD]}),
                                        encoding="utf-8")
    return SqlChecksProject(tmp_path)


def test_it_satisfies_the_seam_structurally(project):
    assert isinstance(project, QualityProject)


def test_hunting_a_non_dbt_project_finds_the_planted_dead_canary(project):
    report = hunt(project, echo=False)
    dead = report["dead_canaries"] or report["dead_canaries_provisional"]
    assert "test.sqlchecks.impossible_check" in dead
    assert "test.sqlchecks.customer_id_is_never_null" not in dead, (
        "a check that really can fail must not be called dead")
    assert report["mutations_applied"] > 0


def test_a_check_that_can_see_damage_actually_catches_it(project):
    """The other direction. A backend where nothing ever passes proves nothing."""
    project.build()
    assert project.test_results()["test.sqlchecks.customer_id_is_never_null"] == "pass"
    con = duckdb.connect(str(project.database))
    con.execute("update raw_orders set customer_id = NULL where id = 1")
    con.close()
    project.run_and_test()
    assert project.test_results()["test.sqlchecks.customer_id_is_never_null"] == "fail"


def test_a_query_that_cannot_run_is_an_error_not_a_pass(tmp_path):
    db = tmp_path / "w.duckdb"
    duckdb.connect(str(db)).close()
    (tmp_path / CHECKS_NAME).write_text(json.dumps({"checks": [
        {"name": "broken", "sql": "select * from a_table_that_does_not_exist"}]}),
        encoding="utf-8")
    p = SqlChecksProject(tmp_path)
    p.build()
    assert p.test_results()["test.sqlchecks.broken"] == "error"


def test_results_before_any_run_are_absent_not_passing(project):
    with pytest.raises(FileNotFoundError):
        project.test_results()


def test_a_project_with_no_checks_file_is_refused(tmp_path):
    duckdb.connect(str(tmp_path / "w.duckdb")).close()
    p = SqlChecksProject(tmp_path)
    with pytest.raises(MalformedChecks):
        p.checks()


@pytest.mark.parametrize("body", ['{"checks": []}', '{"checks": [{"name": "x"}]}', "not json"])
def test_an_untrustworthy_checks_file_is_refused_not_ignored(tmp_path, body):
    duckdb.connect(str(tmp_path / "w.duckdb")).close()
    (tmp_path / CHECKS_NAME).write_text(body, encoding="utf-8")
    with pytest.raises(MalformedChecks):
        SqlChecksProject(tmp_path).checks()


def test_a_directory_with_no_warehouse_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        SqlChecksProject(tmp_path)


def test_cleanup_leaves_nothing_behind(project):
    project.snapshot()
    project.build()
    assert project.pristine.exists()
    project.cleanup()
    assert not project.pristine.exists()
    assert not (project.root / RESULTS_NAME).exists()
