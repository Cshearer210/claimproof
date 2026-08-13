"""The command line: `python -m deadcanary <path-to-dbt-project>`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from deadcanary.hunt import (KILLED, NOOP, SURVIVED, UNDONE, DbtProject,
                             CannotMeasure, hunt)

#: Where the recorded proof lives. Beside the report it is proof of.
CLAIMS_NAME = "deadcanary-claims.json"


def render(report: dict) -> str:
    out = []
    green = report["tests_green"]
    complete = report["coverage_complete"]
    dead = report["dead_canaries"] if complete else report["dead_canaries_provisional"]
    lines = out.append

    lines("")
    lines("=" * 72)
    if not complete:
        missing = sorted(set(report["tables_available"]) - set(report["tables_corrupted"]))
        lines("  PARTIAL RUN -- no dead-canary figure is claimed.")
        lines(f"  {len(dead)} test(s) never failed, but the run did not corrupt every table"
              + (f" (untouched: {', '.join(missing)})" if missing
                 else " (the run was cut short)") + ".")
        lines("  A test that was never given a chance to fire looks exactly like a dead one.")
    elif dead:
        pct = len(dead) / green * 100
        lines(f"  {len(dead)} of {green} green tests are DEAD CANARIES ({pct:.0f}%)")
        lines("  No corruption in the catalogue could make them fail.")
    else:
        lines(f"  Every one of the {green} green tests caught something. No dead canaries.")
    lines("=" * 72)

    if dead:
        lines("\n  Tests that cannot fail:")
        for t in dead:
            lines(f"    x {t}")

    missed = [o for o in report["outcomes"] if o.verdict == SURVIVED]
    if missed:
        lines(f"\n  {len(missed)} corruption(s) NOTHING caught -- real damage, suite still green:")
        for o in missed:
            lines(f"    ! {o.mutation.story}")

    undone = [o for o in report["outcomes"] if o.verdict == UNDONE]
    if undone:
        lines(f"\n  {len(undone)} corruption(s) were wiped by a rebuild before any test ran.")
        lines("  Not counted either way -- nothing was measured.")

    noop = [o for o in report["outcomes"] if o.verdict == NOOP]
    if noop:
        lines(f"\n  {len(noop)} corruption(s) changed no rows and were NOT counted either way.")

    lines(f"\n  {report['mutations_applied']} corruption(s) actually applied, "
          f"{sum(1 for o in report['outcomes'] if o.verdict == KILLED)} caught, "
          f"in {report['seconds']}s.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="deadcanary", description="Find the data tests that cannot fail.")
    ap.add_argument("project", nargs="?", default=".", help="path to a dbt project")
    ap.add_argument("--limit", type=int, help="stop after N corruptions (for a quick look)")
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    ap.add_argument("--quiet", action="store_true",
                    help="gate mode: exit 1 if any test is a dead canary")
    ap.add_argument("--expect-dead", type=int, metavar="N",
                    help="fail unless EXACTLY N dead canaries are found. The demo "
                         "project carries two on purpose; CI asserts they are still "
                         "found, so a broken tool cannot pass while the README "
                         "still promises the demo works.")
    ap.add_argument("--attest", action="store_true",
                    help="record this run as a claimproof claim, fingerprinted against "
                         "the test suite it measured. Add a test later and the claim "
                         "reopens, because the old answer covers a suite that no longer "
                         "exists.")
    ap.add_argument("--recheck", action="store_true",
                    help="do not measure anything: ask whether the proof recorded "
                         "earlier still describes the suite that exists now. "
                         "0 it holds, 1 measure again, 2 cannot tell.")
    ap.add_argument("--claims", metavar="PATH",
                    help=f"where the claim store lives (default: <project>/{CLAIMS_NAME})")
    args = ap.parse_args(argv)

    root = Path(args.project)
    store = Path(args.claims) if args.claims else root / CLAIMS_NAME

    if args.recheck:
        from deadcanary.gate import recheck
        if not store.is_file():
            print(f"deadcanary: no claim recorded for {root}. Nothing to re-check -- "
                  f"run `python -m deadcanary {root} --attest` first.", file=sys.stderr)
            return 2                  # never 0: nothing recorded is not "it holds"
        return recheck(root, store, echo=not args.quiet)

    try:
        project = DbtProject(Path(args.project))
    except (FileNotFoundError, OSError) as exc:
        print(f"deadcanary: {exc}", file=sys.stderr)
        return 2

    try:
        report = hunt(project, limit=args.limit, echo=not (args.json or args.quiet))
    except CannotMeasure as exc:
        print(f"deadcanary: {exc}", file=sys.stderr)
        return 2                      # cannot tell -- never 0, which would read as a pass

    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "outcomes"}, indent=2))
    elif not args.quiet:
        print(render(report))

    if args.attest:
        # Only a run that measured everything may be recorded as proof. A partial
        # run names no dead canaries, which reads identically to finding none --
        # recording that would put a false clean bill of health in the store.
        if not report["coverage_complete"]:
            print("deadcanary: coverage was not complete, so there is nothing to "
                  "attest -- a partial run cannot prove a suite can fail.",
                  file=sys.stderr)
            return 2
        from deadcanary.gate import attest
        attest(project.root, store=store)
        print(f"deadcanary: proof recorded in {store.name}. Re-check it any time with "
              f"`python -m deadcanary {args.project} --recheck`.")

    if args.expect_dead is not None:
        found = len(report["dead_canaries"])
        if not report["coverage_complete"]:
            print(f"deadcanary: coverage was not complete, so the count means nothing",
                  file=sys.stderr)
            return 2
        if found != args.expect_dead:
            print(f"deadcanary: expected {args.expect_dead} dead canaries, found {found}",
                  file=sys.stderr)
            return 1
        print(f"deadcanary: {found} dead canaries, as expected")
        return 0

    return 1 if report["dead_canaries"] else 0


if __name__ == "__main__":
    sys.exit(main())
