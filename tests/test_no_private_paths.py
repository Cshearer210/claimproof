"""Nothing tracked in this public repo names the machine that built it.

WHY THIS IS A TEST AND NOT A HABIT. This repo is generated against, built into,
and demoed from a private workstation. dbt writes absolute paths into its build
output; a demo report records where it ran; a note quotes a local path. Those
files are gitignored today and the working tree is clean, but an ignore rule is a
promise about files that EXIST, not about the next demo somebody adds. Redacting
after the fact does not remove anything from git history, so the check has to run
before a merge rather than after a discovery.

It reads only what git actually TRACKS, which is exactly what a stranger clones.

⚠ THE FIXTURES BELOW ARE BUILT FROM PARTS, NOT TYPED. Writing a real private path
into this file would make the file itself the thing it exists to prevent -- and
that is not hypothetical: the first version of this test was refused for exactly
that, by the guard this test backs up.

⚠ AND THE OTHER DIRECTION, which is the one that gets a check deleted. Three
tracked lines matched on its first real run and all three were SYNTHETIC test
fixtures -- `/home/me/projects`, invented to exercise a different gate. A check
that flags correct work gets switched off, and then it catches nothing at all.
The answer is not a looser pattern (which would miss a real leak) and not an
allowlist of pretend usernames (which rots the day somebody picks a new one):
it is a per-line marker, so every exemption is written down, visible in a diff,
and belongs to the line rather than to the file.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: A path that names a person's machine. Deliberately narrow: these are the two
#: shapes a home directory takes, not a general "looks private" heuristic, which
#: would fire on ordinary prose and get this test deleted.
PRIVATE_PATH = re.compile(r"/home/[a-z][\w.-]*/|[A-Za-z]:\\+Users\\+[\w.-]+")

#: This file quotes the patterns it searches for, so it would find itself.
SELF = Path(__file__).name

#: A line carrying this marker is a deliberate FAKE path -- a test fixture whose
#: whole job is to look like the thing being searched for. It exempts THAT LINE
#: and nothing else, so an exemption cannot spread silently through a file.
SYNTHETIC = "synthetic-path:"

#: Text only. A png cannot be read as source, and a wheel is not tracked.
READABLE = {".py", ".md", ".txt", ".toml", ".cfg", ".yml", ".yaml", ".json",
            ".sql", ".csv", ".sh", ".ini", ".rst", ".html"}

_B = chr(92)          # the backslash, built rather than typed
_DRIVE = "C" + ":" + _B + _B + "Users" + _B + _B + "Owner"
_NIX = "/" + "home" + "/" + "someone" + "/"


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, timeout=120)
    if out.returncode != 0:
        pytest.skip("not a git checkout, so there is nothing tracked to examine")
    return [f for f in out.stdout.splitlines() if f.strip()]


def test_no_tracked_file_names_a_private_machine():
    files = tracked_files()
    assert files, "git tracks nothing here, which is not a clean result"

    findings, judged, exempt = [], 0, 0
    for rel in files:
        if Path(rel).suffix.lower() not in READABLE or Path(rel).name == SELF:
            continue
        p = REPO / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            pytest.fail(f"{rel} could not be read ({exc}); unreadable is not clean")
        judged += 1
        lines = text.splitlines()
        for m in PRIVATE_PATH.finditer(text):
            n = text[:m.start()].count("\n") + 1
            if SYNTHETIC in lines[n - 1]:
                exempt += 1
                continue
            findings.append("%s:%d" % (rel, n))

    assert not findings, (
        "%d tracked line(s) name a private machine, out of %d files examined "
        "(%d line(s) exempted as synthetic):\n  %s"
        % (len(findings), judged, exempt, "\n  ".join(findings[:20])))
    assert judged > 20, f"only {judged} files examined; this cannot have looked properly"


def test_the_pattern_catches_the_shapes_it_claims_to():
    """A finder proven only by finding nothing has not been proven.

    Both sets are synthetic and assembled from parts. The guard cases are real
    shapes that appear in this repo and must never be flagged, because a check
    that fires on ordinary text gets deleted and then catches nothing at all.
    """
    must_catch = [
        '"' + "/home/runner/work/claimproof/src" + '"',
        _DRIVE + _B + _B + "project",
        "path: " + _NIX + "projects/thing/target/manifest.json",
    ]
    must_ignore = [
        "install it with pip install deadcanary",
        "a path like ~/projects/yours works fine",
        "/usr/lib/python3.12/site-packages",
        "see packages/deadcanary/README.md",
        "C" + ":" + _B + "Windows" + _B + "Fonts",
        "",
    ]
    for s in must_catch:
        assert PRIVATE_PATH.search(s), "missed a private path"
    for s in must_ignore:
        assert not PRIVATE_PATH.search(s), f"flagged ordinary text: {s!r}"


def test_the_synthetic_marker_exempts_one_line_and_not_the_file(tmp_path):
    """An escape hatch nobody can audit is how a check quietly stops checking.

    Proven both ways on one file: the marked line is let through, and the line
    below it -- same file, same shape, no marker -- is still caught.
    """
    marked = "p = " + '"' + _NIX + 'a"' + "  # " + SYNTHETIC + " a fixture"
    plain = "q = " + '"' + _NIX + 'b"'
    hits = []
    lines = (marked + "\n" + plain).splitlines()
    for i, line in enumerate(lines, 1):
        if PRIVATE_PATH.search(line) and SYNTHETIC not in line:
            hits.append(i)
    assert hits == [2], f"expected only the unmarked line to be caught, got {hits}"


#: The file dbt writes the absolute build path into. Asking about THIS, rather
#: than about the directory holding it, is deliberate -- see below.
BUILD_ARTIFACTS = (
    "packages/deadcanary/src/deadcanary/_demo/target/manifest.json",
    "packages/deadcanary/projects/jaffle_shop_duckdb/target/manifest.json",
)


def _ignored(rel):
    r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO,
                       capture_output=True, timeout=60)
    if r.returncode not in (0, 1):
        pytest.fail(f"git could not answer whether {rel} is ignored (exit {r.returncode}); "
                    f"unanswerable is not clean")
    return r.returncode == 0


def test_the_build_output_that_caused_this_is_still_ignored():
    """dbt's manifest is where the absolute paths come from. It stays untracked.

    ⚠ IT ASKS ABOUT THE FILE, NEVER THE DIRECTORY, AND THAT IS THE WHOLE POINT.
    The ignore rule is written `target/` -- a directory-only pattern -- so
    `git check-ignore` on the bare path `.../target` answers "ignored" only when
    the directory HAPPENS TO EXIST, because that is the only way git knows it is
    a directory. This test passed on a machine that had run dbt and FAILED in CI,
    which has never run it: a verdict that depends on local build leftovers is
    not a verdict about the repo. Naming the file inside makes the answer the
    same everywhere.
    """
    for rel in BUILD_ARTIFACTS:
        assert _ignored(rel), (
            f"{rel} is no longer ignored; dbt writes the absolute path of "
            f"whichever machine produced it into that file")


def test_this_ignore_check_can_still_say_no(tmp_path):
    """A check that has only ever returned "ignored" has not been shown to look.

    Points the same question at a path nothing ignores. If this comes back
    "ignored" too, the check above is answering yes to everything and proves
    nothing about the build output.
    """
    assert not _ignored("README.md"), (
        "git reports README.md as ignored, so this check cannot tell "
        "ignored from tracked and its clean verdict above means nothing")
