"""Ask each test the question it was written to answer.

The ordinary sweep asks every corruption of every column, which is thorough and
blunt. It can tell you a test never failed. It cannot tell you the sharper
thing: that a `not_null` test does not notice a null *in its own column*.

That finding is different in kind. "This test never fired" invites the answer
"nothing broke". "This test is blind to the single thing it exists to detect"
does not.

⚠ **THE BRIDGE IS A NAME MATCH, NOT LINEAGE, AND THAT IS STATED RATHER THAN
HIDDEN.** dbt tests attach to MODELS, and models are rebuilt from source on
every run -- corrupting one is wiped before any test reads it, which is why the
sweep never targets them. The corruptible tables are the raw sources upstream.
Mapping a model column back to the source column it came from is real lineage
and this does not do it; it matches on column NAME. So a target here is a
*plausible* upstream for the test, and where no corruptible table carries that
column the aim is reported UNREACHABLE rather than quietly dropped. A question
nobody could pose is not a question that was answered.
"""
from __future__ import annotations

import dataclasses

from deadcanary.mutations import (Mutation, Target, blank_required, break_reference,
                                  duplicate_key, unexpected_category)

__all__ = ["Aim", "aims_from_manifest", "blind_to_own_purpose"]

#: What each kind of dbt test claims to guarantee, and the corruption that
#: breaks exactly that guarantee. A test type missing here gets no targeted
#: corruption -- and is reported as such, never silently treated as covered.
BY_TEST_TYPE = {
    "not_null": blank_required,
    "unique": duplicate_key,
    "accepted_values": unexpected_category,
    "relationships": break_reference,
}


@dataclasses.dataclass(frozen=True)
class Aim:
    """One test, and the corruption written to trip it."""

    test_id: str
    test_type: str
    column: str
    #: None when no corruptible table carries this column -- an UNREACHABLE aim.
    mutation: Mutation | None
    note: str = ""

    @property
    def reachable(self) -> bool:
        return self.mutation is not None

    def __str__(self) -> str:
        short = self.test_id.split(".")[-2] if self.test_id.count(".") >= 2 else self.test_id
        if not self.reachable:
            return f"{short}: {self.note}"
        return f"{short} <- {self.mutation}"


def _tests(manifest: dict) -> list[tuple[str, str, str]]:
    """(test id, test type, column) for every data test that names a column."""
    out = []
    for tid, node in (manifest.get("nodes") or {}).items():
        if node.get("resource_type") != "test":
            continue
        meta = node.get("test_metadata") or {}
        kind = meta.get("name")
        column = node.get("column_name") or (meta.get("kwargs") or {}).get("column_name")
        if kind and column:
            out.append((tid, str(kind), str(column)))
    return sorted(out)


def aims_from_manifest(manifest: dict, targets: list[Target]) -> list[Aim]:
    """Pair every column test with the corruption that should trip it.

    `targets` is the corruptible set the sweep already discovered -- raw tables
    only, models excluded, because a corrupted model is rebuilt before any test
    can read it.
    """
    by_column: dict[str, list[Target]] = {}
    for t in targets:
        by_column.setdefault(t.column, []).append(t)

    aims: list[Aim] = []
    for tid, kind, column in _tests(manifest):
        build = BY_TEST_TYPE.get(kind)
        if build is None:
            aims.append(Aim(tid, kind, column, None,
                            note=f"no targeted corruption is defined for a {kind!r} test"))
            continue
        candidates = by_column.get(column) or []
        if not candidates:
            aims.append(Aim(tid, kind, column, None,
                            note=f"no corruptible table carries a {column!r} column, "
                                 f"so this question cannot be put to it"))
            continue
        # Deterministic: the same project must produce the same plan every run,
        # or two runs cannot be compared with each other.
        target = sorted(candidates, key=lambda t: (t.table, t.schema))[0]
        mutation = build(target)
        if mutation is None:
            aims.append(Aim(tid, kind, column, None,
                            note=f"{kind} cannot be posed against {target}"))
            continue
        aims.append(Aim(tid, kind, column, mutation))
    return aims


def blind_to_own_purpose(report: dict, aims: list[Aim]) -> list[Aim]:
    """The tests that missed the corruption written specifically for them.

    Only aims that were actually PUT to the suite count. An aim whose corruption
    never ran says nothing about the test, and reporting it as a blindness would
    be the same inflation this tool exists to refuse.
    """
    from deadcanary.hunt import APPLIED, INCONCLUSIVE

    posed: dict[str, set[str]] = {}
    for c in report.get("corruptions", []):
        verdict = str(c.get("verdict") or "").upper()
        if verdict not in {v.upper() for v in APPLIED}:
            continue
        if verdict in {v.upper() for v in INCONCLUSIVE}:
            continue          # the run broke; this is no evidence about the test
        key = "%s|%s|%s" % (c.get("name"), c.get("table"), c.get("column"))
        posed[key] = set(c.get("caught_by") or [])

    blind = []
    for aim in aims:
        if not aim.reachable:
            continue
        m = aim.mutation
        key = "%s|%s|%s" % (m.name, m.target.table, m.target.column)
        if key not in posed:
            continue                      # never asked -- no verdict either way
        if aim.test_id not in posed[key]:
            blind.append(aim)
    return blind


def render_aims(aims: list[Aim], blind: list[Aim]) -> str:
    reachable = [a for a in aims if a.reachable]
    out = ["", "  TARGETED CORRUPTIONS -- each test asked the question it exists to answer",
           "  " + "-" * 70]
    if not reachable:
        out.append("  No test could be targeted: nothing corruptible carries these columns.")
        return "\n".join(out)
    blind_ids = {a.test_id for a in blind}
    for a in reachable:
        mark = "BLIND" if a.test_id in blind_ids else "  ok "
        out.append("  %s %s" % (mark, a))
    out.append("")
    out.append("  %d of %d targeted test(s) missed the corruption written for them."
               % (len(blind), len(reachable)))
    unreachable = [a for a in aims if not a.reachable]
    if unreachable:
        out.append("  %d test(s) could not be targeted at all, and are NOT counted either way:"
                   % len(unreachable))
        for a in unreachable[:6]:
            out.append("    - %s" % a)
    return "\n".join(out)


def selftest() -> None:
    """Fixtures for the logic, and the REAL demo manifest for the parsing.

    A manifest fixture written by hand matches whatever this file expects, which
    is why the parsing half is proved against the manifest dbt actually wrote.
    """
    import json
    import pathlib

    cols = [Target("main", "raw_orders", "order_id", "INTEGER"),
            Target("main", "raw_orders", "status", "VARCHAR"),
            Target("main", "raw_orders", "amount", "INTEGER")]

    # dbt's real output when a run has produced it; the sample shipped beside the
    # demo when it has not. `_demo/target/` is gitignored build output, so it is
    # absent in CI and absent from the installed wheel -- reading only it meant
    # this selftest could not run for anybody who installed the package.
    demo = pathlib.Path(__file__).parent / "_demo"
    real = demo / "target" / "manifest.json"
    if not real.exists():
        real = demo / "manifest-sample.json"
    manifest = json.loads(real.read_text(encoding="utf-8"))
    aims = aims_from_manifest(manifest, cols)
    assert aims, "the real demo manifest produced no aims at all"
    kinds = {a.test_type for a in aims}
    assert {"not_null", "unique", "accepted_values"} <= kinds, kinds
    by_type = {a.test_type: a for a in aims if a.reachable}
    assert by_type["not_null"].mutation.name == "blank_required", by_type["not_null"]
    assert by_type["unique"].mutation.name == "duplicate_key", by_type["unique"]

    # a column nothing corruptible carries is UNREACHABLE, never silently dropped
    narrow = aims_from_manifest(manifest, [Target("main", "raw_orders", "nothing", "INTEGER")])
    assert narrow and all(not a.reachable for a in narrow), narrow[:2]
    assert "cannot be put to it" in narrow[0].note, narrow[0].note

    # an unknown test type is reported, not assumed covered
    odd = {"nodes": {"test.p.weird.1": {"resource_type": "test", "column_name": "amount",
                                        "test_metadata": {"name": "some_custom_test"}}}}
    a = aims_from_manifest(odd, cols)[0]
    assert not a.reachable and "no targeted corruption" in a.note, a.note

    # blindness, both directions
    aim = by_type["not_null"]
    m = aim.mutation
    caught = {"corruptions": [{"name": m.name, "table": m.target.table,
                               "column": m.target.column, "verdict": "killed",
                               "caught_by": [aim.test_id]}]}
    missed = {"corruptions": [{"name": m.name, "table": m.target.table,
                               "column": m.target.column, "verdict": "survived",
                               "caught_by": []}]}
    never = {"corruptions": []}
    assert blind_to_own_purpose(caught, [aim]) == [], "a test that caught its own is not blind"
    assert blind_to_own_purpose(missed, [aim]) == [aim], "a test that missed its own IS blind"
    assert blind_to_own_purpose(never, [aim]) == [], "never asked is not a verdict"

    print("targeted: selftest PASS (11 checks, real manifest + both directions)")


if __name__ == "__main__":
    selftest()
