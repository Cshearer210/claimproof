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

    unreliable = report.get("unreliable_killers", [])
    if unreliable:
        lines(f"\n  {len(unreliable)} credited test(s) ALSO failed with no corruption applied "
              f"-- their catches are not trusted:")
        for t in unreliable:
            lines(f"    ? {t}")

    lines(f"\n  {report['mutations_applied']} corruption(s) actually applied, "
          f"{sum(1 for o in report['outcomes'] if o.verdict == KILLED)} caught, "
          f"in {report['seconds']}s.")
    return "\n".join(out)


def ratchet(found: int, baseline_path: Path, update: bool = False) -> tuple[int, str]:
    """Compare `found` against the count recorded at `baseline_path`. Never worse, never silent.

    Returns (exit_code, message) rather than printing directly, so a caller -- the CLI, a
    GitHub Action, a test -- decides where the message goes. This is the same shape as
    `regression_guard.py`'s own class of checks elsewhere in this project's own tooling: a
    baseline may only ever ratchet DOWN. A run that regresses fails and never rewrites the
    file, so one bad run can never quietly relax the bar for the next one.

    No file at `baseline_path` is not an error -- it is what a first run looks like. This
    writes one and passes, the same way a fresh `git` repo's first commit has nothing to
    diff against.
    """
    if not baseline_path.is_file():
        baseline_path.write_text(json.dumps({"dead_canaries": found}, indent=2) + "\n",
                                  encoding="utf-8")
        return 0, (f"deadcanary: no baseline yet -- recorded {found} dead canaries to "
                    f"{baseline_path}. Commit it; future runs are held to this.")
    try:
        recorded = json.loads(baseline_path.read_text(encoding="utf-8"))["dead_canaries"]
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        return 2, (f"deadcanary: {baseline_path} exists but does not hold a valid baseline "
                    f"({exc}) -- refusing to ratchet against a file that cannot be read")
    if found > recorded:
        return 1, (f"deadcanary: {found} dead canaries now, {recorded} recorded in "
                    f"{baseline_path.name} -- coverage got WORSE")
    message = (f"deadcanary: {found} dead canaries, at or under the {recorded} recorded "
               f"in {baseline_path.name}")
    if update and found < recorded:
        baseline_path.write_text(json.dumps({"dead_canaries": found}, indent=2) + "\n",
                                  encoding="utf-8")
        message += f"\ndeadcanary: {baseline_path.name} ratcheted down to {found}"
    return 0, message


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="deadcanary", description="Find the data tests that cannot fail.")
    ap.add_argument("project", nargs="?", default=".", help="path to a dbt project")
    ap.add_argument("--limit", type=int, help="stop after N corruptions (for a quick look)")
    ap.add_argument("--verify-null", action="store_true",
                    help="after the sweep, confirm every test credited with a catch does "
                         "NOT also fail on clean data -- a null model, so a real catch can "
                         "be told apart from a test that just fails sometimes on its own. "
                         "Costs --null-repeats extra rebuilds; off by default because it is "
                         "real extra time on a real warehouse.")
    ap.add_argument("--null-repeats", type=int, default=2, metavar="N",
                    help="with --verify-null, how many clean rebuilds to check each "
                         "credited test against (default: 2)")
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    ap.add_argument("--quiet", action="store_true",
                    help="gate mode: exit 1 if any test is a dead canary")
    ap.add_argument("--expect-dead", type=int, metavar="N",
                    help="fail unless EXACTLY N dead canaries are found. The demo "
                         "project carries two on purpose; CI asserts they are still "
                         "found, so a broken tool cannot pass while the README "
                         "still promises the demo works.")
    ap.add_argument("--baseline", metavar="PATH",
                    help="ratchet mode: fail only if the dead-canary count is HIGHER than "
                         "the count recorded at PATH. No file there yet means no baseline "
                         "-- this run records one and passes, same as a first commit. "
                         "Point a real project's CI at this: it goes red only when "
                         "coverage genuinely got worse, not every time a new test is added.")
    ap.add_argument("--update-baseline", action="store_true",
                    help="with --baseline, rewrite the file when the count went DOWN. It "
                         "only ever ratchets down -- a run that regresses fails and never "
                         "rewrites it, so one bad run cannot quietly relax the bar.")
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

    if args.expect_dead is not None and args.baseline is not None:
        print("deadcanary: --expect-dead and --baseline are two different rules for the "
              "same number -- pick one", file=sys.stderr)
        return 2

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
        report = hunt(project, limit=args.limit, echo=not (args.json or args.quiet),
                       verify_null=args.verify_null, null_repeats=args.null_repeats)
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
        # --json promises stdout is nothing but the report. This success line used to
        # print there unconditionally -- harmless alone, but it silently corrupted
        # `deadcanary ... --json --attest`'s output the moment both flags were combined,
        # which is exactly the combination a CI step wiring the JSON into another tool
        # would reach for. Same fix at every site below.
        print(f"deadcanary: proof recorded in {store.name}. Re-check it any time with "
              f"`python -m deadcanary {args.project} --recheck`.",
              file=sys.stderr if args.json else sys.stdout)

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
        print(f"deadcanary: {found} dead canaries, as expected",
              file=sys.stderr if args.json else sys.stdout)
        return 0

    if args.baseline is not None:
        if not report["coverage_complete"]:
            print("deadcanary: coverage was not complete, so the count means nothing -- "
                  "refusing to ratchet against it", file=sys.stderr)
            return 2
        code, message = ratchet(len(report["dead_canaries"]), Path(args.baseline),
                                 update=args.update_baseline)
        print(message, file=sys.stderr if (code or args.json) else sys.stdout)
        return code

    return 1 if report["dead_canaries"] else 0


if __name__ == "__main__":
    sys.exit(main())
