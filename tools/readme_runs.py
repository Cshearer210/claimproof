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
    """
    out = []
    for line in script.splitlines():
        s = line.strip()
        if s.startswith("git clone") or s == "cd deadcanary":
            continue
        out.append(line)
    return "\n".join(out)


def _run_lines(script: str, cwd: Path) -> tuple[int, str]:
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
        if parts[0] in ("python", "python3", "py"):
            parts[0:1] = [sys.executable]
        elif parts[0] == "pip":
            parts[0:1] = [sys.executable, "-m", "pip"]
        elif parts[0] == "dbt":
            parts[0:1] = [sys.executable, "-m", "dbt.cli.main"]
        elif parts[0] == "deadcanary":
            parts[0:1] = [sys.executable, "-m", "deadcanary"]
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

        for i, body in enumerate(runnable, 1):
            script = _rewrite_for_a_local_copy(body, room)
            first = script.strip().splitlines()[0][:52] if script.strip() else "<empty>"
            code, out = _run_lines(script, room)
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

    # A finding is not an error, but a real error still is.
    with tempfile.TemporaryDirectory() as _d:
        code, _ = _run_lines("python -m deadcanary --help", Path(_d))
        ok &= say(code == 0, "a normal command must still exit 0")
        code, _ = _run_lines("python -c \"raise SystemExit(3)\"", Path(_d))
        ok &= say(code == 3, "a genuinely failing command is still a failure")

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
