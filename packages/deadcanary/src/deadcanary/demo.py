"""``python -m deadcanary.demo`` -- the whole idea, on a project you already have.

WHY THIS EXISTS
---------------
Before this, trying deadcanary meant having a dbt project with a built warehouse
lying around. `claimproof`, the sibling package, runs `python -m claimproof.demo`
the second it installs, and that is one of the strongest things about it: a reader
sees the thing work before deciding whether to care. This closes the same gap here.

It is a REAL run, not a recording. It seeds a real warehouse, corrupts it, and
re-runs dbt's own tests against the damage. The two dead canaries it finds are
planted in ``_demo/models/schema.yml`` on purpose, and CI asserts that exactly two
are still found -- so a broken tool cannot pass while the README promises this works.

WHY IT COPIES THE PROJECT OUT FIRST
-----------------------------------
dbt writes: ``target/``, ``logs/``, and the duckdb file itself. The packaged copy
lives inside site-packages, which may be read-only and should not accumulate a
warehouse either way. So the project is copied to a temporary directory and the
run happens there. Nothing is left behind unless --keep is passed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent / "_demo"

# Not a guess at dbt's location: it is run as a module through THIS interpreter,
# so a venv where `dbt` is not on PATH (Windows, notably) still works, and the
# dbt that runs is always the one installed alongside deadcanary.
DBT = [sys.executable, "-m", "dbt.cli.main"]


def dbt_is_installed() -> bool:
    try:
        import dbt.cli.main  # noqa: F401
    except Exception:
        return False
    return True


def _run(argv: list[str], cwd: Path, env: dict) -> int:
    r = subprocess.run(argv, cwd=str(cwd), env=env,
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        sys.stderr.write((r.stdout or "") + (r.stderr or ""))
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="deadcanary.demo",
        description="Run deadcanary end to end on a tiny dbt project that ships "
                    "with this package. No setup, no project of your own needed.")
    ap.add_argument("--keep", action="store_true",
                    help="do not delete the temporary project afterwards, and print "
                         "where it is, so you can poke at it")
    args = ap.parse_args(argv)

    if not DEMO_DIR.is_dir():                       # never silently "nothing to do"
        print("deadcanary.demo: the bundled project is missing from this install. "
              "That is a packaging bug, not something you did wrong.", file=sys.stderr)
        return 2

    if not dbt_is_installed():
        # A clear instruction beats a traceback. deadcanary analyses YOUR dbt
        # project, so it does not force dbt on people who already have it -- which
        # means the demo, and only the demo, has to ask for it.
        print("deadcanary.demo needs dbt to run, because this is a real dbt run and "
              "not a recording.\n\n"
              "    pip install deadcanary[dbt]\n\n"
              "Then run this again. If you already have a dbt project, you do not "
              "need the demo at all:\n\n"
              "    python -m deadcanary path/to/your/project\n", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="deadcanary-demo-"))
    work = tmp / "demo"
    shutil.copytree(DEMO_DIR, work)

    env = dict(os.environ)
    env["DBT_PROFILES_DIR"] = str(work)             # the profile ships with the project

    print("deadcanary demo")
    print("=" * 72)
    print("Building a small warehouse with dbt, so there is something healthy to break.")
    print(f"  working copy: {work}")
    print()

    for step, cmd in (("seed", "seed"), ("build the models", "run")):
        print(f"  dbt {cmd} ...", flush=True)
        rc = _run(DBT + [cmd, "--quiet"], work, env)
        if rc != 0:
            print(f"deadcanary.demo: `dbt {cmd}` failed. Output above.", file=sys.stderr)
            if not args.keep:
                shutil.rmtree(tmp, ignore_errors=True)
            return 1

    print()
    print("Every test below is GREEN right now. That is the claim being checked.")
    print("=" * 72)
    print()

    from deadcanary.hunt import CannotMeasure, DbtProject, hunt
    from deadcanary.__main__ import render                # one renderer, not a second copy

    try:
        report = hunt(DbtProject(work), echo=True)
        print(render(report))
    except CannotMeasure as exc:
        print(f"deadcanary.demo: {exc}", file=sys.stderr)
        return 2                     # cannot tell is never 0, same as the real CLI
    finally:
        if args.keep:
            print(f"\nkept: {work}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    dead = len(report["dead_canaries"])
    print()
    print(f"Two of those tests were planted to be undetectable. It found {dead}.")
    print("Point it at your own project next:  python -m deadcanary path/to/project")
    # The demo is an assertion as well as a demonstration. If the planted canaries
    # stop being found, the tool is broken and the README is lying, so this must
    # not exit 0 -- that is what lets CI run the demo as a check.
    return 0 if dead == 2 else 1


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
