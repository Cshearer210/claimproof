"""The seam a second data-quality tool plugs into.

`hunt.py` was written against `DbtProject` directly, because dbt was the only
tool this package ever ran against. Read closely, almost none of what it does
is actually about dbt -- it corrupts a DuckDB warehouse (`mutations.py`,
`sources.py`), and it needs exactly five things back from "the project":
run the checks, read their verdicts, and snapshot/restore the warehouse
around each one.

`QualityProject` names those five things as a `typing.Protocol` -- structural,
not inherited, so `DbtProject` satisfies it without changing what it is. A
second backend (Great Expectations, Soda Core, anything that validates a
DuckDB table) only has to implement this Protocol; `hunt()` does not change.

What is deliberately NOT in this contract, and why:

    a query language              every checker here already speaks SQL
                                   against the same warehouse file; the
                                   corruption layer needs no cooperation
                                   from whatever validates it afterwards
    "the manifest"                dbt's manifest.json is how DbtProject
                                   answers `rebuilt_tables()`; a project
                                   with no transformation layer of its own
                                   (checks run straight against raw tables)
                                   can just return an empty set
    a specific result file shape  `test_results()` returns dbt's own
                                   vocabulary (`pass`/`fail`/`skipped`/
                                   `error`) because that is what hunt.py's
                                   bookkeeping already keys on. A future
                                   backend translates its own result shape
                                   into this one at the boundary, once,
                                   rather than teaching hunt.py a second
                                   vocabulary.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class QualityProject(Protocol):
    """What `hunt()` needs from a project, however its checks are written.

    Every method here already exists on `DbtProject` (`hunt.py`) under this
    exact name -- this Protocol was extracted FROM that class, not designed
    ahead of it, so a mismatch here is a mismatch with running code, never
    an untested guess about what a second backend would need.
    """

    #: The project's root directory. Read to find checks, source files, and
    #: to write `deadcanary-report.json` beside the project when a run ends.
    root: Path

    #: The DuckDB warehouse file the checks run against. `hunt()` connects
    #: to this directly (`mutations.discover`, `apply_one`'s corruption
    #: SQL) -- the corruption layer speaks DuckDB, not whatever tool is
    #: validating the result, which is what makes one corruption engine
    #: usable by more than one checker.
    database: Path

    def build(self) -> subprocess.CompletedProcess:
        """Run every check from a clean state and report the outcome.

        Called exactly once, before any corruption, to establish which
        checks are healthy right now (`hunt.baseline`). A check that is
        already red here tells the hunt nothing about whether it can
        detect corruption, so it is excluded from the run entirely.
        """
        ...

    def run_and_test(self) -> subprocess.CompletedProcess:
        """Re-run whatever transforms the data, then re-run the checks --
        WITHOUT reloading the raw source. The corruption stands in for bad
        data arriving from upstream; reloading it from the source would
        silently undo the very thing being tested.

        For a project with no transformation step (checks run straight
        against tables that are never rebuilt), this is the same as
        `build()` minus any seed/load step.
        """
        ...

    def test_results(self) -> dict[str, str]:
        """Every check and its status, keyed by a stable id, read from
        whatever artifact the tool itself wrote -- never from console
        output, which is prose and changes wording between releases.

        Statuses are dbt's own vocabulary because hunt.py's bookkeeping
        already keys on it: `"pass"` and `"fail"` are load-bearing, and
        anything else (`"skipped"`, `"error"`, or a tool's own word for
        either) is read only to be excluded, never credited with a catch.
        A second backend translates its own result shape into these words
        at the boundary; it does not need to reproduce dbt's file format.
        """
        ...

    def rebuilt_tables(self) -> set[str]:
        """Tables/views this project regenerates on its own, e.g. from a
        transformation layer running on top of the warehouse.

        Corrupting one of these is a guaranteed no-op: the corruption is
        overwritten before any check sees it. A project with no
        transformation layer of its own returns an empty set -- every raw
        table is then a legitimate corruption target.
        """
        ...

    def snapshot(self) -> None:
        """Copy the warehouse aside so it can be restored after each
        corruption. Called once per hunt, before the first corruption."""
        ...

    def restore(self) -> None:
        """Put the warehouse back exactly as `snapshot()` found it. Called
        before every corruption (so each one starts clean) and once more
        when the hunt ends, successfully or not."""
        ...

    def cleanup(self) -> None:
        """Remove whatever `snapshot()` left behind. Called once, when the
        hunt ends -- a snapshot that outlives its run is a leftover that
        could later be mistaken for the real warehouse (see `DbtProject.
        _find_database`'s own `.deadcanary-pristine` exclusion)."""
        ...
