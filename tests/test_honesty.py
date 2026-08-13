"""The three ways this tool can lie, each held down by a test.

Every one of these was a real defect in the first working version, and every one
failed in the FLATTERING direction -- more tests looked dead than were dead, which
reads as a discovery rather than as a bug. That is what makes them worth pinning:
a wrong number here is not obviously wrong to anybody reading the report.

dbt is stubbed rather than run. The subject under test is the bookkeeping -- what
counts as measured, what counts as nothing -- and that logic must be provable in
under a second, not in the six minutes a real hunt takes.
"""
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from deadcanary.hunt import (
    BROKE, KILLED, NOOP, SURVIVED, UNDONE, DbtProject, NothingToCorrupt,
    apply_one, hunt,
)
from deadcanary.mutations import Mutation, Target

HEALTHY = {"test.a": "pass", "test.b": "pass"}


def _make_project(tmp_path: Path, rows: int = 20) -> Path:
    root = tmp_path / "proj"
    (root / "target").mkdir(parents=True)
    (root / "dbt_project.yml").write_text("name: fake\n", encoding="utf-8")
    con = duckdb.connect(str(root / "w.duckdb"))
    con.execute("create table raw_orders (id integer, status varchar)")
    con.execute(f"insert into raw_orders select i, 'placed' from range({rows}) t(i)")
    con.execute("create table blanks (id integer)")
    con.execute("insert into blanks select NULL from range(5)")
    con.close()
    return root


class StubProject(DbtProject):
    """A dbt project whose dbt is a stub with a scripted answer."""

    def __init__(self, root, results, rebuilds=(), undo=False):
        super().__init__(root)
        self._results = results
        self._rebuilds = set(rebuilds)
        self._undo = undo
        self.calls = []

    def dbt(self, *args, timeout=1200):
        self.calls.append(args)
        if self._undo:                       # simulate dbt regenerating the table
            shutil.copy2(self.pristine, self.database)
        (self.root / "target" / "run_results.json").write_text(
            json.dumps({"results": [{"unique_id": k, "status": v}
                                    for k, v in self._results.items()]}), encoding="utf-8")

        class R:
            returncode = 0
        return R()

    def rebuilt_tables(self):
        return self._rebuilds


def _mutation(table="raw_orders", column="status", sql=None):
    t = Target("main", table, column, "VARCHAR")
    return Mutation("test_mut", f"something happened to {table}", t,
                    sql or f'update {t.fqn} set "{column}" = NULL')


# ------------------------------------------------------------------ NO-OP

def test_a_corruption_that_changes_nothing_is_never_counted_as_missed(tmp_path):
    """Nulling an all-null column changes nothing, so no test could catch it.

    Counting that as SURVIVED would pad the headline with corruptions that never
    happened -- the cheapest way to manufacture an impressive number.
    """
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY)
    p.snapshot()
    m = _mutation(table="blanks", column="id", sql='update "main"."blanks" set "id" = NULL')

    out = apply_one(p, m, HEALTHY)

    assert out.verdict == NOOP
    assert not p.calls, "dbt should not even be run for a corruption that did nothing"


def test_invalid_sql_is_a_noop_not_a_missed_corruption(tmp_path):
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY)
    p.snapshot()
    out = apply_one(p, _mutation(sql="update nope set nothing = 1"), HEALTHY)
    assert out.verdict == NOOP
    assert "could not apply" in out.detail


# --------------------------------------------------------- UNDONE BY REBUILD

def test_a_corruption_wiped_by_a_rebuild_is_never_counted_as_missed(tmp_path):
    """The defect that made the first real run report 20 of 20 tests dead.

    dbt regenerates its models from source. Corrupt one and the damage is gone
    before the first test executes, so every test passes and every test looks
    decorative. It read as a spectacular finding and was an artifact.
    """
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY, undo=True)
    p.snapshot()

    out = apply_one(p, _mutation(), HEALTHY)

    assert out.verdict == UNDONE
    assert "wiped the corruption" in out.detail


def test_models_are_never_aimed_at(tmp_path):
    """The other half of the same fix: do not target what dbt rebuilds at all."""
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY, rebuilds={"raw_orders"})
    report = hunt(p, echo=False)
    assert "raw_orders" not in report["tables_available"]


# --------------------------------------------------------- PARTIAL COVERAGE

def test_a_partial_run_refuses_to_name_any_dead_canary(tmp_path):
    """A test never given a chance to fire looks exactly like a dead one.

    `limit` is high enough to get past the all-NULL `blanks` table, whose first
    corruption is a no-op -- with only a no-op applied, nothing executed at all
    and there is correctly nothing to report either way.
    """
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY)
    report = hunt(p, limit=6, echo=False)

    assert report["coverage_complete"] is False
    assert report["dead_canaries"] == [], "no figure may be claimed from a partial run"
    assert report["dead_canaries_provisional"], "but the provisional list is still kept"


# ------------------------------------------------------- SKIPPED BY DBT

class SkippingProject(StubProject):
    """dbt's real behaviour: when one test fails, everything downstream is SKIPPED."""

    def dbt(self, *args, timeout=1200):
        # The FIRST call is the baseline, and a healthy suite is all green -- a
        # project whose tests were already failing would be rejected before the
        # hunt starts, so the skipping only begins once data is corrupted.
        first = not self.calls
        self.calls.append(args)
        results = ([{"unique_id": "test.a", "status": "pass"},
                    {"unique_id": "test.b", "status": "pass"}] if first else
                   [{"unique_id": "test.a", "status": "fail"},
                    {"unique_id": "test.b", "status": "skipped"}])
        (self.root / "target" / "run_results.json").write_text(
            json.dumps({"results": results}), encoding="utf-8")

        class R:
            returncode = 0 if first else 1
        return R()


def test_a_skipped_test_is_never_credited_with_a_catch(tmp_path):
    """dbt skips downstream tests when one fails. A skip is not a catch.

    Measured on the demo project: one genuine failure produced four skips, and
    all four were recorded as having caught the corruption. That made the suite
    look far more alive than it is and hid a real dead canary.
    """
    root = _make_project(tmp_path)
    p = SkippingProject(root, HEALTHY)
    p.dbt("build")          # consume the baseline call, as hunt() would
    p.snapshot()

    out = apply_one(p, _mutation(), HEALTHY)

    assert out.verdict == KILLED
    assert out.failing_tests == ("test.a",), "only the FAILING test may be credited"
    assert "test.b" not in out.ran, "a skipped test did not execute"


def test_a_test_skipped_in_every_run_is_unknown_not_dead(tmp_path):
    """No chance to fire, no verdict -- the same rule as an uncorrupted table."""
    root = _make_project(tmp_path)
    p = SkippingProject(root, HEALTHY)
    report = hunt(p, echo=False)

    assert "test.b" in report["never_executed"]
    assert "test.b" not in report["dead_canaries"],         "a test dbt never ran cannot be called decorative"
    assert report["coverage_complete"] is False, "a run with unexecuted tests is not whole"


def test_a_complete_run_does_name_them(tmp_path):
    """The guard case: the caution must not swallow a real, whole-run finding."""
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY)                 # nothing ever fails -> all dead
    report = hunt(p, echo=False)

    assert report["coverage_complete"] is True
    assert sorted(report["dead_canaries"]) == ["test.a", "test.b"]


# --------------------------------------------------------------- KILLED

def test_a_test_that_goes_red_is_credited_with_the_catch(tmp_path):
    root = _make_project(tmp_path)
    p = StubProject(root, {"test.a": "fail", "test.b": "pass"})
    p.snapshot()

    out = apply_one(p, _mutation(), HEALTHY)

    assert out.verdict == KILLED
    assert out.failing_tests == ("test.a",)


def test_a_test_already_red_before_we_started_is_not_credited(tmp_path):
    """A permanently broken test must not masquerade as a vigilant one."""
    root = _make_project(tmp_path)
    p = StubProject(root, {"test.a": "fail", "test.b": "pass"})
    p.snapshot()

    already_broken = {"test.a": "fail", "test.b": "pass"}
    out = apply_one(p, _mutation(), already_broken)

    assert out.verdict == SURVIVED, "the only red test was red before the corruption"


# ------------------------------------------------------------ housekeeping

def test_the_warehouse_is_left_exactly_as_it_was_found(tmp_path):
    """A tool that corrupts data must never leave any of it behind."""
    root = _make_project(tmp_path)
    before = (root / "w.duckdb").read_bytes()
    p = StubProject(root, HEALTHY)

    hunt(p, echo=False)

    con = duckdb.connect(str(root / "w.duckdb"))
    rows = con.execute("select count(*) from raw_orders").fetchone()[0]
    con.close()
    assert rows == 20, "the corruption was left in the warehouse"
    assert not (root / ".deadcanary-pristine.duckdb").exists(), "the backup was left behind"


def test_a_project_without_dbt_is_refused_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        DbtProject(tmp_path)


def test_a_project_with_no_warehouse_says_what_to_do(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    (root / "dbt_project.yml").write_text("name: fake\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="dbt seed"):
        DbtProject(root)


def test_every_run_leaves_a_report_on_disk(tmp_path):
    """A measurement that leaves no artifact is a claim, not a measurement."""
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY)
    hunt(p, echo=False)

    out = root / "deadcanary-report.json"
    assert out.is_file(), "the run produced no report file"
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["coverage_complete"] is True
    assert saved["corruptions"], "the report names no corruptions"
    assert all("verdict" in c and "story" in c for c in saved["corruptions"]), \
        "a corruption in the report cannot be read by someone who was not there"


def test_the_report_records_a_partial_run_as_partial(tmp_path):
    """The guard case: the artifact must carry the caution, not just the screen."""
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY)
    hunt(p, limit=1, echo=False)

    saved = json.loads((root / "deadcanary-report.json").read_text(encoding="utf-8"))
    assert saved["coverage_complete"] is False
    assert saved["dead_canaries"] == []


def test_a_project_with_nothing_to_corrupt_refuses_loudly(tmp_path):
    """Nothing to corrupt is NOT a clean bill of health.

    Measured on dbt-labs/jaffle-shop-template: every table in its warehouse is a
    model, because its raw data is read straight from CSV via an external source
    and never lands in the database. The run produced no findings and looked
    exactly like a healthy project -- the shape of silent failure this tool
    exists to shout about, happening in the tool itself.
    """
    root = _make_project(tmp_path)
    p = StubProject(root, HEALTHY, rebuilds={"raw_orders", "blanks"})

    with pytest.raises(NothingToCorrupt, match="nothing to corrupt"):
        hunt(p, echo=False)


def test_the_cli_reports_that_as_cannot_tell_not_as_a_pass(tmp_path):
    """Exit 0 would mean 'no dead canaries'. The truth is 'no measurement'."""
    root = _make_project(tmp_path)
    (root / "target" / "manifest.json").write_text(json.dumps({"nodes": {
        "m.1": {"name": "raw_orders", "resource_type": "model"},
        "m.2": {"name": "blanks", "resource_type": "model"},
    }}), encoding="utf-8")
    (root / "target" / "run_results.json").write_text(json.dumps({"results": [
        {"unique_id": "test.a", "status": "pass"}]}), encoding="utf-8")

    from deadcanary.__main__ import main
    assert main([str(root)]) == 2, "an unmeasurable project must not exit 0"


def test_the_warehouse_is_found_where_the_PROFILE_puts_it(tmp_path):
    """The profile says where the warehouse is. Searching for it is a guess.

    Measured on `adityawarmanfw/dbt_duckdb_chinook`, whose profile writes to
    `./target/chinook.duckdb`: the search skipped `target/` as a build artifact,
    found nothing, and told the user to run `dbt seed && dbt run` -- which they
    had just done. The tool refused to run on a perfectly healthy project and
    blamed the project.

    `matsonj/nba-monte-carlo` is the same class one step worse: its warehouse is
    at `../data/data_catalog/mdsbox.duckdb`, OUTSIDE the project, where no
    search under the project root can ever reach it.
    """
    root = tmp_path / "proj"
    (root / "target").mkdir(parents=True)
    (root / "dbt_project.yml").write_text("name: fake\nprofile: 'p'\n", encoding="utf-8")
    duckdb.connect(str(root / "target" / "chinook.duckdb")).close()
    (root / "profiles.yml").write_text(
        "p:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        "      path: './target/chinook.duckdb'\n", encoding="utf-8")

    assert DbtProject(root).database == (root / "target" / "chinook.duckdb").resolve()


def test_a_profile_path_that_is_not_a_plain_path_falls_back_to_searching(tmp_path):
    """The guard case, and it is a real project, not a hypothetical.

    dbt-labs/jaffle-shop-template writes
    `path: "{{ env_var('JAFFLE_DB_PATH', './reports/jaffle_shop.duckdb') }}"`.
    Reading that literally would hand back a filename with braces in it. Anything
    this module cannot resolve for certain must fall back to the search that
    already works, never guess.
    """
    root = _make_project(tmp_path)
    (root / "profiles.yml").write_text(
        "duckdb:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        "      path: \"{{ env_var('JAFFLE_DB_PATH', './reports/jaffle_shop.duckdb') }}\"\n",
        encoding="utf-8")

    assert DbtProject(root).database.name == "w.duckdb"


def test_a_profile_naming_a_file_that_does_not_exist_falls_back_too(tmp_path):
    """A profile can name a warehouse nobody has built yet. That is not an answer."""
    root = _make_project(tmp_path)
    (root / "profiles.yml").write_text(
        "p:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
        "      path: './never_built.duckdb'\n", encoding="utf-8")

    assert DbtProject(root).database.name == "w.duckdb"


def test_a_leftover_backup_is_never_mistaken_for_the_warehouse(tmp_path):
    """A crashed run leaves .deadcanary-pristine.duckdb behind.

    The recursive search excluded it, the root-level search did not, so the next
    run adopted the tool's own backup as the user's warehouse and then failed
    copying a file onto itself. A tool's leftovers are the one thing it must never
    confuse with real data.
    """
    root = _make_project(tmp_path)
    shutil.copy2(root / "w.duckdb", root / ".deadcanary-pristine.duckdb")

    p = DbtProject(root)

    assert p.database.name == "w.duckdb", f"adopted {p.database.name} as the warehouse"
