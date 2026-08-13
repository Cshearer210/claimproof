#!/usr/bin/env python3
"""Run the README's own quickstart, exactly as written.

    python tools/readme_runs.py              # run it
    python tools/readme_runs.py --selftest   # prove this check can fail

CALLED BY: .github/workflows/ci.yml (job `readme`)

The test suite proves the CODE works. CI's `installed` job proves the PACKAGE
works. Neither reads the README, and documentation rots on its own schedule: a
quickstart can name a flag that was renamed two releases ago while every test
passes, and nothing here would notice. The first thing a stranger does is type
what the README says, so that is what this types.

The mechanism is lifted from claimproof's `tools/fresh_eyes.py` -- specifically
the marker idea: a block declares whether it is meant to run, and an UNMARKED
block is a failure rather than a silent skip, so a block added next month cannot
quietly fall out of coverage. Only that idea is copied; this file is much smaller
because deadcanary's README has one runnable path instead of four.
"""
from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

#: A ```bash block must carry one of these on the line before it.
RUN = "<!-- readme: run -->"
SHOW = "<!-- readme: illustration -->"

FAILURES: list[str] = []


def say(ok: bool, label: str, detail: str = "") -> bool:
    print(f"  {'ok   ' if ok else 'FAIL '} {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILURES.append(label)
    return ok


def blocks(text: str) -> tuple[list[str], list[str]]:
    """Every ```bash block, split into the ones to run and the undeclared ones."""
    run, unmarked = [], []
    for m in re.finditer(r"(?:(<!-- readme: \w+ -->)\s*\n)?```bash\n(.*?)```", text, re.S):
        marker, body = m.group(1), m.group(2)
        if marker == RUN:
            run.append(body)
        elif marker != SHOW:
            first = body.strip().splitlines()[0] if body.strip() else "<empty>"
            unmarked.append(first[:70])
    return run, unmarked


def _rewrite_for_a_local_copy(script: str, clone: Path) -> str:
    """A stranger clones from GitHub; CI already has the working tree.

    The clone and cd lines are replaced with the checkout under test -- otherwise
    this would verify whatever is on main rather than the change being reviewed,
    which is the opposite of what a pre-merge check is for.

    Matched on where the `cd` LANDS rather than on its literal text. The first
    version compared against the exact string `cd deadcanary`, which stopped
    being what the README says the day this package moved into the claimproof
    repo -- and a stale two-line helper would then have failed as though the
    quickstart itself were broken.
    """
    out = []
    for line in script.splitlines():
        s = line.strip()
        # A bare `cd` INTO this package, however deep it sits. Anything with a
        # `&&` in it is real quickstart work (`cd demo && dbt build ...`) and is
        # never dropped -- without the demo build there is nothing to measure.
        entering = (s.startswith("cd ") and "&&" not in s
                    and s.split(maxsplit=1)[1].rstrip("/").endswith("deadcanary"))
        if s.startswith("git clone") or entering:
            continue
        out.append(line)
    return "\n".join(out)


def _run_lines(script: str, cwd: Path, python: Path | None = None) -> tuple[int, str]:
    """Execute the block a line at a time, with no shell involved.

    Shelling out to `bash` looked simpler and was wrong: on Windows `bash`
    resolves to WSL, which does not have the checkout, the interpreter, or any of
    the packages -- so the check failed for a reason that had nothing to do with
    the README. Running the argv directly behaves identically on a laptop and in
    CI, which is the whole point of a check that is supposed to speak for a
    stranger on an unknown machine.

    `cd` is handled here rather than executed, because without a shell there is no
    process to carry the change to the next line.
    """
    log = []
    # A README line is often a chain -- `cd demo && dbt build && cd ..` -- and
    # treating it as one command turned `demo` into `demo/demo`. Splitting on &&
    # is the whole of the shell grammar this needs; anything more elaborate in a
    # quickstart is a sign the quickstart is too complicated for a stranger.
    steps = [part.strip()
             for raw in script.splitlines()
             for part in raw.split("#")[0].split("&&")]
    for line in steps:
        if not line:
            continue
        # posix=True, so quotes are STRIPPED rather than passed through. With
        # posix=False, `python -c "raise SystemExit(3)"` handed python a quoted
        # string, which it evaluated as a harmless expression and exited 0 -- a
        # failing command silently reported as a pass. README commands are written
        # in POSIX style, so this is also the shape they are meant to be read in.
        parts = shlex.split(line, posix=True)
        if parts[0] == "cd":
            cwd = (cwd / parts[1].strip('"')).resolve()
            continue
        exe = str(python or sys.executable)
        if parts[0] in ("python", "python3", "py"):
            parts[0:1] = [exe]
        elif parts[0] == "pip":
            parts[0:1] = [exe, "-m", "pip"]
        elif parts[0] == "dbt":
            parts[0:1] = [exe, "-m", "dbt.cli.main"]
        elif parts[0] == "deadcanary":
            parts[0:1] = [exe, "-m", "deadcanary"]
        r = subprocess.run(parts, cwd=str(cwd), capture_output=True, text=True, timeout=3600)
        log.append(f"$ {line}\n{(r.stdout or '')[-400:]}{(r.stderr or '')[-400:]}")

        # deadcanary exits 1 when it FINDS dead canaries. That is the tool working,
        # and the demo is built to contain two, so the quickstart's last command is
        # SUPPOSED to exit 1. Treating every non-zero exit as broken made this check
        # call a correct run a failure -- the same conflation of "found something"
        # with "went wrong" that the tool itself is careful to avoid. Exit 2 is the
        # real error: cannot tell.
        finding = _is_deadcanary(parts) and r.returncode == 1
        if r.returncode != 0 and not finding:
            return r.returncode, f"failing step: {line}\n" + "\n".join(log)
    return 0, "\n".join(log)


def _is_deadcanary(parts: list[str]) -> bool:
    return any("deadcanary" in str(p) for p in parts[1:3])


def run_quickstart() -> None:
    text = README.read_text(encoding="utf-8")
    runnable, unmarked = blocks(text)

    if not say(not unmarked, "every bash block in the README declares whether it runs",
               f"{len(unmarked)} unmarked: {'; '.join(unmarked[:3])}" if unmarked else ""):
        print(f"        put {RUN} or {SHOW} on the line above each one")
    if not say(bool(runnable), "the README has a runnable quickstart", f"{len(runnable)} block(s)"):
        return

    with tempfile.TemporaryDirectory() as tmp:
        room = Path(tmp) / "clone"
        shutil.copytree(REPO, room, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.egg-info", ".pytest_cache", "dist", "build",
            "target", "*.duckdb", ".venv"))

        # A THROWAWAY interpreter, not the one running this file.
        #
        # The quickstart contains `pip install -e .`, and the first version ran it
        # with the ambient python. That repointed the developer's own editable
        # install at this temp copy, which was then deleted -- so running the check
        # BROKE the working environment of anyone who ran it, silently, and the
        # next `pytest` could not import the package at all. A check that damages
        # the machine it runs on is worse than no check.
        venv = Path(tmp) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=900)
        python = venv / ("Scripts" if sys.platform == "win32" else "bin") / (
            "python.exe" if sys.platform == "win32" else "python")
        say(python.is_file(), "a throwaway environment, so the quickstart cannot "
                              "touch the one you are working in")

        for i, body in enumerate(runnable, 1):
            script = _rewrite_for_a_local_copy(body, room)
            first = script.strip().splitlines()[0][:52] if script.strip() else "<empty>"
            code, out = _run_lines(script, room, python=python)
            if not say(code == 0, f"quickstart block {i}: {first}", f"exit {code}"):
                print(out[-1200:])


def selftest() -> int:
    """Break each rule on purpose. A check that cannot fail proves nothing."""
    print("readme_runs selftest\n")
    ok = True

    run, unmarked = blocks(f"{RUN}\n```bash\necho hi\n```\n")
    ok &= say(run == ["echo hi\n"] and not unmarked, "a marked block is collected")

    run, unmarked = blocks("```bash\necho hi\n```\n")
    ok &= say(not run and bool(unmarked), "an UNMARKED block is reported, never skipped quietly")

    run, unmarked = blocks(f"{SHOW}\n```bash\nnot a real command\n```\n")
    ok &= say(not run and not unmarked, "an illustration is neither run nor complained about")

    # The guard case: other languages are not this check's business.
    run, unmarked = blocks("```python\nprint(1)\n```\n```yaml\na: b\n```\n")
    ok &= say(not run and not unmarked, "a python or yaml block is left alone")

    ok &= say("git clone" not in _rewrite_for_a_local_copy(
        "git clone https://x/y\ncd deadcanary\npip install -e .", Path(".")),
        "the clone step is replaced by the checkout under test")

    # The same quickstart after this package moved into the claimproof repo. The
    # rewriter matched the literal string `cd deadcanary`, so the moment the
    # README said `cd claimproof/packages/deadcanary` instead, CI would have
    # tried to enter a directory that does not exist inside the temporary
    # checkout -- and the failure would have read as a broken quickstart rather
    # than a stale two-line helper.
    moved = _rewrite_for_a_local_copy(
        "git clone https://x/y\ncd claimproof/packages/deadcanary\npip install -e .", Path("."))
    ok &= say("cd claimproof" not in moved and "pip install -e ." in moved,
              "the clone step is replaced wherever this package lives in the repo")

    # The guard: a `cd` that is part of the real quickstart must survive, or the
    # demo never gets built and the check silently measures nothing.
    kept = _rewrite_for_a_local_copy("cd demo && dbt build --profiles-dir . && cd ..", Path("."))
    ok &= say(kept.strip() == "cd demo && dbt build --profiles-dir . && cd ..",
              "GUARD: a working `cd` inside the quickstart is left alone")

    # A finding is not an error, but a real error still is.
    with tempfile.TemporaryDirectory() as _d:
        code, _ = _run_lines("python -m deadcanary --help", Path(_d))
        ok &= say(code == 0, "a normal command must still exit 0")
        code, _ = _run_lines("python -c \"raise SystemExit(3)\"", Path(_d))
        ok &= say(code == 3, "a genuinely failing command is still a failure")

    # The environment this check runs in must be exactly as it was afterwards.
    import importlib.metadata as _md
    where_before = _md.distribution("deadcanary").locate_file("")
    ok &= say("Temp" not in str(where_before) and "tmp" not in str(where_before).lower(),
              "the installed package is not pointing at a temp directory",
              str(where_before)[-60:])

    before = len(FAILURES)
    say(False, "a deliberately failed check is recorded")
    ok &= say(len(FAILURES) == before + 1, "...and it lands in the failure list")
    FAILURES.clear()

    print("\n" + ("selftest PASSED" if ok else "selftest FAILED"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the README's own quickstart.")
    ap.add_argument("--selftest", action="store_true", help="prove this check can fail")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    print("deadcanary: doing what the README says\n")
    run_quickstart()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} thing(s) a stranger following the README would hit:")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("The README's quickstart works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
