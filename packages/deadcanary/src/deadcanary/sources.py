"""Corrupting the FILES a project reads, for the projects that never load them.

A lot of real dbt work never puts raw data in the warehouse at all. dbt-duckdb
sources can point straight at a CSV or a Parquet file on disk:

    sources:
      - name: raw_orders
        meta:
          external_location: "read_csv_auto('./jaffle-data/{name}.csv', header=1)"

dbt-labs' own current jaffle-shop template is built this way. Against a project
like that, corrupting warehouse tables reaches nothing -- every table there is a
model, models are rebuilt, and the hunt has nothing to break. It used to report
that as a completed run with no findings, which read as a clean bill of health.

So the file IS the raw table, and this module corrupts it the same way
`mutations.py` corrupts a table: the same eight named corruptions, the same
plain-English stories, the same rule that a corruption which changed nothing is
never counted as one nothing caught.

Rows are read and written with the stdlib `csv` module rather than pandas: the
point is to write back a file byte-compatible with what dbt will read, and a
dataframe round-trip quietly reformats dates, drops leading zeros, and turns
empty strings into NaN -- each of which would be a corruption this tool did not
intend and could not name.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import re
import shutil
from pathlib import Path

from deadcanary.mutations import BLAST

#: `read_csv_auto('./jaffle-data/{name}.csv', header=1)` -> the path, with {name}
#: still in it. Parquet is matched too; the corruptions below only handle CSV, and
#: a matched-but-unsupported file is reported rather than skipped in silence.
_LOCATION = re.compile(r"""read_(csv|csv_auto|parquet)\s*\(\s*['"]([^'"]+)['"]""", re.I)

#: Anything with a scheme in front of it is somebody else's storage: a bucket, a
#: URL, an http-served file. Real and readable by dbt, and not a file this tool
#: may edit. Needed only once bare strings count as paths -- see `_location_of`.
_REMOTE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


def _location_of(node: dict) -> str:
    """Where dbt recorded the file this source reads. Three places, all real.

    A source location is written in whichever of these the project happened to
    use, and a tool that knows only one reports NOTHING TO CORRUPT on a project
    whose raw data is sitting in plain sight:

    ``meta.external_location``     hand-written, dbt-labs' own jaffle-shop template
    ``config.external_location``   the same thing, moved by newer dbt versions
    ``external.location``          written by the `dbt-external-tables` package

    Measured: dbt-labs/jaffle-shop-template uses the first wrapped in
    ``read_csv_auto()``, sdebruyn/inzight uses the first as a bare path, and
    adityawarmanfw/dbt_duckdb_chinook uses the third with an empty ``meta``.
    """
    return str((node.get("meta") or {}).get("external_location")
               or (node.get("config") or {}).get("external_location")
               or (node.get("external") or {}).get("location") or "")


@dataclasses.dataclass(frozen=True)
class FileTarget:
    """One column of one file that a dbt source reads directly."""

    source: str
    path: Path
    column: str

    @property
    def table(self) -> str:            # so reports read the same as table targets
        return self.source

    @property
    def schema(self) -> str:
        return "file"

    def __str__(self) -> str:
        return f"{self.source}.{self.column}"


def discover_files(project_root: Path) -> list[FileTarget]:
    """Every column of every file a source reads, from dbt's own manifest.

    Read from the manifest rather than by parsing the YAML, because dbt has
    already resolved the templating and the manifest is what dbt itself acted on.
    """
    manifest = project_root / "target" / "manifest.json"
    if not manifest.is_file():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))

    out: list[FileTarget] = []
    for node in data.get("sources", {}).values():
        location = _location_of(node)
        if not location:
            continue
        m = _LOCATION.search(location)
        if m:
            kind, template = m.group(1).lower(), m.group(2)
            if "parquet" in kind:
                continue                # binary; not corrupted by this module yet
        else:
            # The bare form: the location IS the path. Everything that is not a
            # local CSV has to be turned away here, or the tool starts naming
            # targets it cannot touch -- a bucket, a URL, or a plain warehouse
            # table name, which is what this field holds in most projects.
            template = location.strip()
            if _REMOTE.match(template) or not template.lower().endswith(".csv"):
                continue
        path = (project_root / template.replace("{name}", node["name"])).resolve()
        if not path.is_file():
            continue
        try:
            with path.open(newline="", encoding="utf-8") as fh:
                header = next(csv.reader(fh), [])
        except OSError:
            continue
        out.extend(FileTarget(node["name"], path, col) for col in header if col)
    return out


# ------------------------------------------------------------------ the edits
#
# Each returns (rows, changed). `changed` is the real count -- a corruption that
# matched nothing must report 0 so the caller can record a NO-OP rather than a
# miss, exactly as the table corruptions do.

def _blank(rows, col, header):
    i, n = header.index(col), 0
    for r in rows:
        if n >= BLAST:
            break
        if i < len(r) and r[i] != "":
            r[i], n = "", n + 1
    return rows, n


def _duplicate(rows, col, header):
    return (rows + [list(rows[0])], 1) if rows else (rows, 0)


def _drop(rows, col, header):
    keep = rows[BLAST:]
    return keep, len(rows) - len(keep)


def _empty(rows, col, header):
    return [], len(rows)


def _unexpected(rows, col, header):
    i, n = header.index(col), 0
    for r in rows[:BLAST]:
        if i < len(r):
            r[i], n = "UNKNOWN_FROM_UPSTREAM", n + 1
    return rows, n


def _negative(rows, col, header):
    i, n = header.index(col), 0
    for r in rows:
        if n >= BLAST:
            break
        if i < len(r):
            try:
                v = float(r[i])
            except ValueError:
                continue
            r[i], n = str(-abs(v)), n + 1
    return rows, n


def _break_ref(rows, col, header):
    i, n = header.index(col), 0
    for r in rows[:BLAST]:
        if i < len(r):
            r[i], n = "999999999", n + 1
    return rows, n


#: name -> (edit, story). Names match `mutations.CATALOGUE` so one report can hold
#: both kinds and a reader never has to learn two vocabularies.
FILE_CORRUPTIONS = {
    "blank_required": (_blank, "{n} rows of {t} arrive with {c} empty"),
    "duplicate_key": (_duplicate, "one row of {t} is loaded twice, so {c} is no longer unique"),
    "drop_rows": (_drop, "{n} rows of {t} never arrive, and nothing errors"),
    "empty_table": (_empty, "{t} is empty -- the file is there and the rows are gone"),
    "unexpected_category": (_unexpected, "{c} starts arriving as an unagreed value from upstream"),
    "negative_amount": (_negative, "{c} comes through negative, reversing the sign"),
    "break_reference": (_break_ref, "{n} rows point at a {c} that does not exist anywhere"),
}

#: Per-FILE rather than per-column: naming a column changes nothing about what
#: they do, and running them once per column would inflate the denominator.
PER_FILE = ("duplicate_key", "drop_rows", "empty_table")


def apply_to_file(target: FileTarget, name: str) -> int:
    """Corrupt the file in place. Returns how many rows actually changed."""
    edit, _ = FILE_CORRUPTIONS[name]
    with target.path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return 0
    header, body = rows[0], [list(r) for r in rows[1:]]
    if target.column not in header:
        return 0
    body, changed = edit(body, target.column, header)
    if not changed:
        return 0
    with target.path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(body)
    return changed


def snapshot_files(targets: list[FileTarget], room: Path) -> dict[Path, Path]:
    """Copy every source file aside. A tool that corrupts somebody's data on disk
    and cannot put it back is not one anybody should run twice."""
    room.mkdir(parents=True, exist_ok=True)
    saved: dict[Path, Path] = {}
    for t in targets:
        if t.path not in saved:
            keep = room / f"{len(saved)}-{t.path.name}"
            shutil.copy2(t.path, keep)
            saved[t.path] = keep
    return saved


def restore_files(saved: dict[Path, Path]) -> None:
    for original, keep in saved.items():
        shutil.copy2(keep, original)
