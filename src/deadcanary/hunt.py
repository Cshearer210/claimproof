"""Run the hunt: corrupt the data, re-run the tests, record what stayed silent.

The loop, per mutation:

    restore a pristine copy of the warehouse
    apply the corruption          -- and CONFIRM it actually changed rows
    re-run the models and tests
    read dbt's own run_results.json     (never the printed output)
    record which tests moved from pass to fail

A test that no corruption in the whole catalogue could make fail is a **dead
canary**: it is in the suite, it is green every morning, and it is not protecting
anything.

Three outcomes, and keeping them apart is the point:

    KILLED    the corruption was applied and at least one test failed
    SURVIVED  the corruption was applied and every test still passed
    NO-OP     the corruption changed no rows, so nothing was measured

NO-OP is not a pass and not a failure. Counting a no-op as SURVIVED would inflate
the headline number with corruptions that never happened -- the exact way this
kind of tool lies.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from deadcanary.mutations import Mutation, discover, plan

KILLED, SURVIVED, NOOP, BROKE = "KILLED", "SURVIVED", "NO-OP", "BROKE-THE-RUN"


class CannotMeasure(RuntimeError):
    """The run could not be performed at all. Reported as UNKNOWN, never as a pass."""


class NothingToCorrupt(CannotMeasure):
    """There was no raw data in the warehouse to break, so nothing was measured.

    Raised rather than returning an empty report, because an empty report reads as
    "your tests are fine" and the truth is "this tool could not tell you anything".
    """

#: The corruption was applied, and then dbt rebuilt the table from its source and
#: wiped it before a single test ran. Nothing was measured.
#:
#: This is the failure that makes this whole tool lie, and it lies in the most
#: flattering direction: every test looks dead, which reads as a spectacular
#: finding. The first run of this tool reported 20 of 20 tests dead for exactly
#: this reason -- it was corrupting `customers`, a model dbt regenerates on every
#: build. So the corruption is now re-checked AFTER the run, and a corruption that
#: did not survive is never allowed to count as one nothing caught.
UNDONE = "UNDONE-BY-REBUILD"


@dataclasses.dataclass
class Outcome:
    mutation: Mutation
    verdict: str
    rows_changed: int
    failing_tests: tuple[str, ...] = ()
    detail: str = ""
    #: Tests that actually executed under this corruption. A test dbt skipped is
    #: absent here, and absence is why it can never be called a dead canary.
    ran: frozenset = dataclasses.field(default_factory=frozenset)


class DbtProject:
    """A dbt project on DuckDB, and the few things this tool needs from it."""

    def __init__(self, root: Path, database: Path | None = None):
        self.root = Path(root).resolve()
        if not (self.root / "dbt_project.yml").is_file():
            raise FileNotFoundError(f"no dbt_project.yml in {self.root}")
        self.database = Path(database) if database else self._find_database()
        self.pristine = self.root / ".deadcanary-pristine.duckdb"

    def _find_database(self) -> Path:
        """The warehouse file, wherever the project's profile decided to put it.

        Searched recursively, because only the simplest projects keep it beside
        dbt_project.yml -- dbt-labs' own template writes to ./reports/, and the
        root-only glob found nothing and refused to run.
        """
        found = sorted(self.root.glob("*.duckdb")) or sorted(
            p for p in self.root.rglob("*.duckdb")
            if ".deadcanary-pristine" not in p.name
            and "dbt_packages" not in p.parts and "target" not in p.parts)
        if not found:
            raise FileNotFoundError(
                f"no .duckdb file in {self.root}. Run `dbt seed && dbt run` first, "
                f"so there is a healthy warehouse to corrupt."
            )
        return found[0]

    # -- dbt ---------------------------------------------------------------
    def dbt(self, *args: str, timeout: int = 1200) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "dbt.cli.main", *args, "--profiles-dir", "."],
            cwd=str(self.root), capture_output=True, text=True, timeout=timeout,
        )

    def rebuilt_tables(self) -> set[str]:
        """Tables dbt regenerates: every model, and every seed.

        Corrupting one of these and then running dbt is a guaranteed no-op, because
        the corruption is overwritten before anything looks at it. Read from the
        manifest so the answer stays right when the project changes.
        """
        path = self.root / "target" / "manifest.json"
        if not path.is_file():
            return set()
        data = json.loads(path.read_text(encoding="utf-8"))
        return {n["name"] for n in data.get("nodes", {}).values()
                if n.get("resource_type") == "model"}

    def test_results(self) -> dict[str, str]:
        """Every test and its status, from dbt's own artifact.

        Read from run_results.json rather than the console, because the console
        wording is prose and prose changes between releases. A tool that learns
        its answer by grepping another tool's output breaks silently the day that
        output is reworded.
        """
        path = self.root / "target" / "run_results.json"
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {r["unique_id"]: r["status"] for r in data.get("results", [])}

    # -- warehouse state ---------------------------------------------------
    def snapshot(self) -> None:
        try:
            shutil.copy2(self.database, self.pristine)
        except PermissionError as exc:
            # Windows locks the file while any connection is open, including one
            # left by a crashed earlier run. Crashing here would look like a tool
            # bug; the truth is that nothing could be measured.
            raise CannotMeasure(
                f"{self.database.name} is locked by another process, so it cannot "
                f"be copied or safely corrupted. Close anything holding it open "
                f"(a dbt run, a DuckDB shell, an editor preview) and try again."
            ) from exc

    def restore(self) -> None:
        shutil.copy2(self.pristine, self.database)

    def cleanup(self) -> None:
        self.pristine.unlink(missing_ok=True)


def _connect(db: Path):
    import duckdb
    return duckdb.connect(str(db))


def baseline(project: DbtProject) -> dict[str, str]:
    """The healthy suite. Anything already failing is excluded from the hunt.

    A test that is red before a single thing is corrupted tells us nothing about
    whether it can detect corruption, and leaving it in would let a permanently
    broken test masquerade as a vigilant one.
    """
    r = project.dbt("build")
    if r.returncode != 0 and not project.test_results():
        raise RuntimeError(f"`dbt build` failed before any corruption:\n{r.stdout[-1500:]}")
    return project.test_results()


def rebuild_and_test(project: DbtProject) -> subprocess.CompletedProcess:
    """Run the models and the tests, WITHOUT re-loading the seeds.

    `dbt build` would re-seed from the CSVs first and undo the corruption. The
    corruption stands in for bad data arriving from upstream, so the right
    simulation is: the raw table is now wrong, push it through the pipeline.
    """
    # TWO invocations, deliberately, and this is not an oversight to optimise away.
    #
    # `dbt build` interleaves models and tests and STOPS THE CHAIN when a test fails:
    # every test downstream of the failure is skipped. A skipped test did not run, so
    # it cannot be credited with a catch -- and it also cannot be called dead, because
    # it was never given a chance. Measured on the demo project: a single `build` left
    # two tests unexecuted under exactly the corruptions that would have killed them,
    # and both were then reported as dead canaries. Two of four findings were false.
    #
    # `run` then `test` builds every model first, so every test executes every time
    # and each one is judged on its own behaviour. It costs a second dbt start-up per
    # corruption. Correctness is worth more than the second.
    project.dbt("run")
    return project.dbt("test")


def apply_one(project: DbtProject, mutation: Mutation, healthy: dict[str, str]) -> Outcome:
    """Corrupt, rebuild, compare. Always leaves the warehouse pristine again."""
    project.restore()

    con = _connect(project.database)
    try:
        before = con.execute(f"select count(*) from {mutation.target.fqn}").fetchone()[0]
        checksum_before = _checksum(con, mutation.target.fqn)
        try:
            con.execute(mutation.sql)
        except Exception as exc:                       # a mutation that cannot run
            return Outcome(mutation, NOOP, 0, detail=f"could not apply: {type(exc).__name__}: {exc}")
        after = con.execute(f"select count(*) from {mutation.target.fqn}").fetchone()[0]
        checksum_after = _checksum(con, mutation.target.fqn)
    finally:
        con.close()

    changed = abs(after - before) + (0 if checksum_before == checksum_after else 1)
    if changed == 0:
        return Outcome(mutation, NOOP, 0,
                       detail="the corruption ran but changed no rows, so nothing was measured")

    r = rebuild_and_test(project)

    # Did the corruption actually survive long enough to be tested? If dbt rebuilt
    # the table from its source, nothing was measured -- and reporting that as
    # "no test caught it" is the single most flattering way this tool can lie.
    con = _connect(project.database)
    try:
        checksum_now = _checksum(con, mutation.target.fqn)
        rows_now = con.execute(f"select count(*) from {mutation.target.fqn}").fetchone()[0]
    finally:
        con.close()
    if checksum_now == checksum_before and rows_now == before:
        return Outcome(mutation, UNDONE, changed,
                       detail=f"dbt rebuilt {mutation.target.table} and wiped the corruption "
                              f"before any test ran, so nothing was measured")

    after_status = project.test_results()
    if not after_status:
        return Outcome(mutation, BROKE, changed,
                       detail=f"dbt produced no results at all (exit {r.returncode})")

    # ONLY a real failure counts as a catch.
    #
    # When one test fails, dbt SKIPS every test downstream of it. Counting a skip
    # as a catch credits tests that never executed -- measured on the demo project:
    # one genuine failure produced four skips, and all four were recorded as having
    # caught the corruption. That inflates how alive the suite looks and hides real
    # dead canaries; it hid one of the two the demo was built to contain.
    #
    # `error` is excluded for the same reason: the test broke, it did not fire.
    now_failing = tuple(sorted(
        tid for tid, status in after_status.items()
        if status == "fail" and healthy.get(tid) == "pass"
    ))
    # Which tests actually EXECUTED, so a test that was only ever skipped is never
    # called dead -- it was never given a chance, exactly like an uncorrupted table.
    ran = frozenset(tid for tid, status in after_status.items() if status in ("pass", "fail"))
    if now_failing:
        return Outcome(mutation, KILLED, changed, now_failing, ran=ran)
    return Outcome(mutation, SURVIVED, changed, ran=ran,
                   detail="every test still passed with corrupted data in the warehouse")


def _checksum(con, fqn: str) -> str:
    """Content fingerprint, so an UPDATE that changes values but not the row count
    is still recognised as a real change."""
    try:
        return str(con.execute(f"select md5(string_agg(t::VARCHAR, '')) from {fqn} t").fetchone()[0])
    except Exception:
        return ""


def hunt(project: DbtProject, limit: int | None = None, echo: bool = True) -> dict:
    """The whole run. Returns the report as data; printing is somebody else's job."""
    started = time.time()
    healthy = baseline(project)
    live = {t for t, s in healthy.items() if s == "pass"}
    if echo:
        print(f"  {len(healthy)} test(s) in the suite, {len(live)} green before we touch anything")
    if not live:
        raise RuntimeError("no passing tests to evaluate -- fix the suite first")

    con = _connect(project.database)
    try:
        found = discover(con)
    finally:
        con.close()

    # Never aim at a table dbt regenerates -- the corruption would be wiped before
    # any test saw it, and every test would look dead. Excluded LOUDLY, with the
    # count said out loud, because a silently narrowed population is how a scan
    # reports 6 of 40 as though it were all of them.
    rebuilt = project.rebuilt_tables()
    targets = [t for t in found if t.table not in rebuilt]
    if echo and rebuilt:
        skipped = sorted({t.table for t in found if t.table in rebuilt})
        print(f"  not aiming at {len(skipped)} table(s) dbt rebuilds: {', '.join(skipped)}")

    if not targets:
        # NOTHING TO CORRUPT IS NOT A CLEAN RESULT. Measured on
        # dbt-labs/jaffle-shop-template: every table in its warehouse is a model,
        # because its raw data is read straight from CSV via an external source and
        # never lands in the database at all. The run produced no findings and
        # looked exactly like a healthy project -- which is the shape of silent
        # failure this whole tool exists to shout about, occurring in itself.
        raise NothingToCorrupt(
            f"every table in this warehouse is one dbt rebuilds, so there is nothing "
            f"to corrupt. Tables seen: {', '.join(sorted(rebuilt)) or 'none'}. "
            f"This usually means the project reads its raw data from files "
            f"(read_csv/read_parquet in a source's external_location) rather than "
            f"loading it into the warehouse. Corrupting those files is not supported "
            f"yet, so this project cannot be measured -- which is different from "
            f"measuring it and finding nothing."
        )

    project.snapshot()          # only once we know there is something to measure

    mutations = plan(targets)
    if limit:
        mutations = mutations[:limit]
    if echo:
        print(f"  {len(targets)} column(s) discovered, {len(mutations)} corruption(s) to try\n")

    outcomes: list[Outcome] = []
    killers: dict[str, set[str]] = {t: set() for t in live}
    try:
        for i, m in enumerate(mutations, 1):
            out = apply_one(project, m, healthy)
            outcomes.append(out)
            for tid in out.failing_tests:
                killers.setdefault(tid, set()).add(out.mutation.name)
            if echo:
                mark = {KILLED: "caught ", SURVIVED: "MISSED ", NOOP: "  --   ",
                        BROKE: "broke  ", UNDONE: " undone"}[out.verdict]
                print(f"  [{i:3}/{len(mutations)}] {mark} {out.mutation}")
    finally:
        project.restore()
        project.cleanup()

    # A test may only be called a dead canary if the run actually gave it a chance
    # to fire. Cut the run short -- or skip a table -- and the untouched tests look
    # identical to genuinely dead ones. The first limited run of this tool called 15
    # of 20 tests dead when 12 of them simply watched tables nothing had corrupted
    # yet. So coverage is recorded, and the headline is withheld unless it is whole.
    corrupted_tables = {o.mutation.target.table for o in outcomes
                        if o.verdict in (KILLED, SURVIVED, BROKE)}
    available_tables = {t.table for t in targets}
    complete = (not limit) and corrupted_tables >= available_tables

    # A test that dbt SKIPPED in every corruption never executed, so it cannot be
    # called dead any more than a test whose table was never corrupted can. Same
    # rule as partial coverage, one level down: no chance to fire, no verdict.
    ever_ran = set()
    for o in outcomes:
        ever_ran |= o.ran
    never_ran = sorted(t for t in live if t not in ever_ran)

    dead = sorted(t for t in live if not killers.get(t) and t in ever_ran)
    applied = [o for o in outcomes if o.verdict in (KILLED, SURVIVED, BROKE)]
    undone = [o for o in outcomes if o.verdict == UNDONE]
    missed = [o for o in outcomes if o.verdict == SURVIVED]

    report = {
        "project": str(project.root),
        "seconds": round(time.time() - started, 1),
        "tests_total": len(healthy),
        "tests_green": len(live),
        "dead_canaries": dead if complete else [],
        "dead_canaries_provisional": [] if complete else dead,
        "coverage_complete": complete and not never_ran,
        "never_executed": never_ran,
        "tables_corrupted": sorted(corrupted_tables),
        "tables_available": sorted(available_tables),
        "mutations_planned": len(mutations),
        "mutations_applied": len(applied),
        "mutations_noop": len(outcomes) - len(applied) - len(undone),
        "mutations_undone": len(undone),
        "mutations_missed": len(missed),
        "outcomes": outcomes,
        "killers": {t: sorted(v) for t, v in killers.items() if v},
        "corruptions": [
            {"name": o.mutation.name, "table": o.mutation.target.table,
             "column": o.mutation.target.column, "story": o.mutation.story,
             "verdict": o.verdict, "caught_by": list(o.failing_tests),
             "detail": o.detail}
            for o in outcomes
        ],
    }
    save(project, report)
    return report


def save(project: DbtProject, report: dict) -> Path:
    """Write the report next to the project it describes.

    Until this existed a run's findings lived only in a terminal, so every number
    quoted from one was a number nobody else could check. A measurement that leaves
    no artifact is a claim.
    """
    out = project.root / "deadcanary-report.json"
    out.write_text(json.dumps({k: v for k, v in report.items() if k != "outcomes"},
                              indent=2, sort_keys=True), encoding="utf-8")
    return out
