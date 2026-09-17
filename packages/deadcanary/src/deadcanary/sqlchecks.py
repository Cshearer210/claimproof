"""A second backend, with no framework behind it at all.

`QualityProject` was extracted from `DbtProject` to let a second data-quality
tool plug in. A seam nothing has ever plugged into is a claim, not a seam, so
this is the second thing that plugs in -- and it deliberately depends on
nothing.

A project here is a warehouse file and a list of SQL assertions:

    {"checks": [
       {"name": "orders_have_a_customer",
        "sql": "select * from raw_orders where customer_id is null"}]}

A check FAILS when its query returns rows. That is the convention dbt itself
uses for a singular test, and Soda and Great Expectations both reduce to it, so
a project written this way is a fair stand-in for any of them.

⚠ **WHY NOT GREAT EXPECTATIONS DIRECTLY, stated rather than quietly skipped.**
GE was the named candidate and it was tried first: on this interpreter pip
resolves it to 0.18.x, the legacy API, while 1.x is current. Shipping a backend
bound to a deprecated API -- and one heavy enough that CI could not honestly run
it -- would make the second backend the most fragile thing in the package. This
carries no dependency, runs in the test suite on every commit, and proves the
same thing about `hunt()`: that it is not a dbt tool with a seam bolted on.
Adapting GE or Soda is then the same five methods, against a live example.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

__all__ = ["SqlChecksProject", "CHECKS_NAME", "RESULTS_NAME"]

CHECKS_NAME = "deadcanary-checks.json"
RESULTS_NAME = ".deadcanary-sqlchecks-results.json"
PRISTINE_SUFFIX = ".deadcanary-pristine"


class MalformedChecks(ValueError):
    """A checks file that cannot be trusted. Never silently treated as empty."""


class SqlChecksProject:
    """Satisfies `QualityProject` with plain SQL and no framework.

    Structural typing, like `DbtProject`: nothing is inherited, and
    `isinstance(p, QualityProject)` is true because the five methods are here.
    """

    def __init__(self, root: Path | str, database: Path | str | None = None):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError("no such project directory: %s" % self.root)
        self.database = Path(database) if database else self._find_database()
        self.pristine = self.database.with_suffix(self.database.suffix + PRISTINE_SUFFIX)

    # -- discovery ---------------------------------------------------------
    def _find_database(self) -> Path:
        found = [p for p in sorted(self.root.glob("*.duckdb"))
                 if not p.name.endswith(PRISTINE_SUFFIX)]
        if not found:
            raise FileNotFoundError(
                "no .duckdb file in %s, so there is nothing to corrupt or check. "
                "An absent warehouse is not an empty one." % self.root)
        return found[0]

    def checks(self) -> list[dict]:
        path = self.root / CHECKS_NAME
        if not path.is_file():
            raise MalformedChecks(
                "no %s in %s -- a project with no checks cannot be measured, and "
                "reporting that as 'nothing failed' would be a lie." % (CHECKS_NAME, self.root))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MalformedChecks("%s cannot be read (%s)" % (path, exc)) from exc
        checks = data.get("checks") if isinstance(data, dict) else data
        if not isinstance(checks, list) or not checks:
            raise MalformedChecks("%s holds no checks" % path)
        for c in checks:
            if not isinstance(c, dict) or not c.get("name") or not c.get("sql"):
                raise MalformedChecks("%s: every check needs a name and a sql query" % path)
        return checks

    # -- QualityProject ----------------------------------------------------
    def build(self) -> subprocess.CompletedProcess:
        return self._run()

    def run_and_test(self) -> subprocess.CompletedProcess:
        # No transformation layer: there is nothing to rebuild, so re-running the
        # checks IS the whole job. Critically this does not reload raw data --
        # doing so would undo the corruption before anything looked at it.
        return self._run()

    def _run(self) -> subprocess.CompletedProcess:
        import duckdb

        con = duckdb.connect(str(self.database))
        results = {}
        try:
            for check in self.checks():
                cid = "test.sqlchecks.%s" % check["name"]
                try:
                    rows = con.execute(check["sql"]).fetchall()
                except Exception:
                    # A query that cannot run is an ERROR, never a pass. hunt()
                    # reads anything that is not "fail" as no catch, and "error"
                    # keeps it out of the credited set where it belongs.
                    results[cid] = "error"
                    continue
                results[cid] = "fail" if rows else "pass"
        finally:
            con.close()
        (self.root / RESULTS_NAME).write_text(json.dumps({"results": results}),
                                              encoding="utf-8")
        failed = sum(1 for v in results.values() if v == "fail")
        return subprocess.CompletedProcess(args=["sqlchecks"], returncode=1 if failed else 0)

    def test_results(self) -> dict[str, str]:
        path = self.root / RESULTS_NAME
        if not path.is_file():
            raise FileNotFoundError(
                "%s has not run yet, so there are no results. An absent result is "
                "not a passing one." % RESULTS_NAME)
        return dict(json.loads(path.read_text(encoding="utf-8"))["results"])

    def rebuilt_tables(self) -> set[str]:
        # Nothing is regenerated here, so every table is a legitimate target.
        return set()

    # -- warehouse state ---------------------------------------------------
    def snapshot(self) -> None:
        shutil.copy2(self.database, self.pristine)

    def restore(self) -> None:
        shutil.copy2(self.pristine, self.database)

    def cleanup(self) -> None:
        self.pristine.unlink(missing_ok=True)
        (self.root / RESULTS_NAME).unlink(missing_ok=True)


def selftest() -> None:
    """Build a real warehouse, hunt it, and check the answer is the known one."""
    import tempfile

    import duckdb

    from deadcanary.hunt import hunt
    from deadcanary.project import QualityProject

    root = Path(tempfile.mkdtemp(prefix="deadcanary-sqlchecks-"))
    db = root / "warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create table raw_orders (id integer, customer_id integer, note varchar)")
    con.execute("insert into raw_orders values (1, 10, 'a'), (2, 20, 'b'), (3, 30, 'c'), "
                "(4, 40, 'd'), (5, 50, 'e')")
    con.close()

    (root / CHECKS_NAME).write_text(json.dumps({"checks": [
        # A real check: it can see a null customer_id.
        {"name": "customer_id_is_never_null",
         "sql": "select * from raw_orders where customer_id is null"},
        # A DEAD CANARY on purpose: this can never return a row.
        {"name": "impossible_check", "sql": "select * from raw_orders where 1 = 0"},
    ]}), encoding="utf-8")

    project = SqlChecksProject(root)
    assert isinstance(project, QualityProject), "it must satisfy the seam structurally"

    report = hunt(project, echo=False)
    dead = report["dead_canaries"] or report["dead_canaries_provisional"]
    assert "test.sqlchecks.impossible_check" in dead, dead
    assert "test.sqlchecks.customer_id_is_never_null" not in dead, dead
    assert report["mutations_applied"] > 0, report["mutations_applied"]
    project.cleanup()
    shutil.rmtree(root, ignore_errors=True)
    print("sqlchecks: selftest PASS -- a non-dbt project, hunted, dead canary found")


if __name__ == "__main__":
    selftest()
