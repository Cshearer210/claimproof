"""It must refuse to corrupt anything that looks live, before touching it.

This tool damages real rows on purpose. Against production that is an incident,
not a test -- and "only run it against dev" lived in the documentation and
nowhere else, which makes it a rule that holds right up until somebody is in a
hurry.

Most of these test the direction that decides whether the check survives: that
it stays QUIET on ordinary work. A pre-flight that blocks normal development is
removed within the week, and a removed check protects nothing.
"""

import pytest

# duckdb is an OPTIONAL backend. Without this line a clone that lacks it gets a COLLECTION
# ERROR, which reads as broken software rather than a missing extra -- the worst first
# impression a public repo can make on someone who just ran the tests.
pytest.importorskip("duckdb", reason="the duckdb backend is an optional extra")

import hashlib
import json

import duckdb
import pytest

from deadcanary.hunt import hunt
from deadcanary.safety import (OVERRIDE_ENV, LooksLive, assert_not_live, live_reasons)
from deadcanary.sqlchecks import CHECKS_NAME, SqlChecksProject


def _warehouse(path):
    con = duckdb.connect(str(path))
    con.execute("create table raw_orders (id integer, customer_id integer)")
    con.execute("insert into raw_orders values (1, 10), (2, 20), (3, 30), (4, 40)")
    con.close()


@pytest.fixture()
def prod_project(tmp_path):
    db = tmp_path / "warehouse_prod.duckdb"
    _warehouse(db)
    (tmp_path / CHECKS_NAME).write_text(json.dumps({"checks": [
        {"name": "id_not_null", "sql": "select * from raw_orders where id is null"}]}),
        encoding="utf-8")
    return SqlChecksProject(tmp_path, database=db)


def test_an_ordinary_development_project_is_not_flagged(tmp_path):
    """The direction that decides whether this check lives or gets deleted."""
    db = tmp_path / "dev.duckdb"
    db.touch()
    assert live_reasons(tmp_path, db) == []
    assert_not_live(tmp_path, db)


@pytest.mark.parametrize("name", ["reproduction-cases", "productivity", "aliveness",
                                  "prodigy", "deliverables"])
def test_a_word_that_merely_contains_a_live_word_is_not_live(tmp_path, name):
    db = tmp_path / ("%s.duckdb" % name)
    db.touch()
    assert live_reasons(tmp_path, db) == [], name


def test_a_production_looking_path_is_caught(tmp_path):
    db = tmp_path / "warehouse_prod.duckdb"
    db.touch()
    assert live_reasons(tmp_path, db)


def test_a_profile_selecting_prod_is_caught(tmp_path):
    db = tmp_path / "dev.duckdb"
    db.touch()
    (tmp_path / "profiles.yml").write_text(
        "p:\n  target: production\n  outputs:\n    production:\n      type: duckdb\n",
        encoding="utf-8")
    assert any("target" in r for r in live_reasons(tmp_path, db))


def test_the_refusal_names_the_reason(tmp_path):
    db = tmp_path / "prod.duckdb"
    db.touch()
    with pytest.raises(LooksLive) as caught:
        assert_not_live(tmp_path, db)
    assert "prod" in str(caught.value)
    assert OVERRIDE_ENV in str(caught.value), "a refusal nobody can act on gets overridden blindly"


def test_a_hunt_refuses_and_changes_nothing(prod_project):
    """The whole point: refused BEFORE the first corruption, not after."""
    before = hashlib.sha256(prod_project.database.read_bytes()).hexdigest()
    with pytest.raises(LooksLive):
        hunt(prod_project, echo=False)
    after = hashlib.sha256(prod_project.database.read_bytes()).hexdigest()
    assert before == after, "it touched the warehouse it refused to touch"


def test_the_override_lets_a_deliberate_run_through(prod_project, monkeypatch):
    monkeypatch.setenv(OVERRIDE_ENV, "1")
    report = hunt(prod_project, echo=False)
    assert report["mutations_applied"] > 0, "the override must actually let it run"
