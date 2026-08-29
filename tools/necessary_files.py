#!/usr/bin/env python3
"""Refuse any file that is not necessary for this package to be used.

CALLED BY: .github/workflows/ci.yml on every push and pull request.

WHY AN ALLOWLIST AND NOT A BLOCKLIST
------------------------------------
A blocklist would have to name the things that must not appear -- and naming them here,
in a public repository, publishes them. The list of things you are trying to keep out is
itself the thing you are trying to keep out.

So this asks the opposite question, which is also the honest one: is this file necessary
for somebody to install, understand, verify, run, or contribute to this package? A path
that is not on the list below is refused. Adding one is then a deliberate act with a
reviewer attached, rather than something that happens by habit.

WHAT COUNTS AS NECESSARY
------------------------
    src/ tests/ packages/     the software and its proof
    pyproject.toml LICENSE    you cannot install or legally reuse it without these
    README CHANGELOG          what it is, and what changed
    CONTRIBUTING SECURITY     how to help, and how to report a problem
    CODE_OF_CONDUCT           expected of a public project
    .github/                  CI, issue templates, pull request template
    examples/                 usage somebody actually runs
    FINDINGS.md findings/     the evidence for the central claim. On a project arguing
                              that an unbacked claim is worthless, its own evidence and
                              the means to reproduce it are necessary by definition
    tools/                    the scripts that produce those findings
    assets/                   images the README displays

Everything else belongs somewhere private. It is not that other files are dangerous --
they are simply not part of what anybody downloads this to get, and a repository that
carries them asks every reader to sort the package from the workspace around it.

    python tools/necessary_files.py            # report
    python tools/necessary_files.py --selftest # prove it refuses AND allows
"""
from __future__ import annotations

import re
import subprocess
import sys

# A file is necessary if its path matches one of these, anchored at the repo root.
ALLOW = [
    r"^src/",
    r"^tests/",
    r"^packages/[^/]+/(src|tests|tools|findings)/",
    r"^packages/[^/]+/(pyproject\.toml|README\.md|LICENSE|CHANGELOG\.md|FINDINGS\.md)$",
    r"^packages/[^/]+/\.gitignore$",
    r"^examples/",
    r"^tools/",
    r"^assets/",
    r"^findings/",
    r"^\.github/",
    r"^(README|CHANGELOG|CONTRIBUTING|SECURITY|CODE_OF_CONDUCT|FINDINGS)\.md$",
    r"^(LICENSE|pyproject\.toml|\.gitignore)$",
    r"^py\.typed$",
]

# Generic shapes, so the message can say WHY rather than only "not on the list". These
# describe categories anybody would recognise; nothing here names a specific document,
# because doing so would defeat the reason this is an allowlist in the first place.
WHY_NOT = [
    (r"\.(env|key|pem|p12|pfx)$", "this looks like a credential file"),
    (r"(^|/)\.DS_Store$", "an operating-system leftover"),
    (r"(^|/)[^/]*\.(bak|orig|tmp|swp)$", "an editor or backup leftover"),
    (r"(^|/)(scratch|tmp|temp)/", "a scratch folder"),
]


def tracked(root="."):
    r = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    if r.returncode != 0:
        return None
    return [p.strip() for p in (r.stdout or "").splitlines() if p.strip()]


def is_necessary(path):
    return any(re.search(p, path) for p in ALLOW)


def why_not(path):
    for pat, reason in WHY_NOT:
        if re.search(pat, path):
            return reason
    return "not part of what this package needs to be used"


def check(paths):
    return [(p, why_not(p)) for p in paths if not is_necessary(p)]


def selftest():
    """Both directions. A check that refuses everything is as broken as one that
    refuses nothing, and only the second is obvious."""
    must_refuse = [
        "PLANNING.md",
        "my-working-notes.md",
        "workspace/todo.md",
        "scratch/idea.md",
        "internal/audit.md",
        ".env",
        "secrets.pem",
        "README.md.bak",
        ".DS_Store",
    ]
    must_allow = [
        "src/claimproof/__init__.py",
        "src/claimproof/crewai.py",
        "tests/test_gate.py",
        "packages/deadcanary/src/deadcanary/cli.py",
        "packages/deadcanary/README.md",
        "packages/deadcanary/FINDINGS.md",
        "examples/crewai_guardrail.py",
        "tools/measure_unbacked_claims.py",
        "assets/demo.svg",
        "findings/evidence-window-2026-08-28.json",
        ".github/workflows/ci.yml",
        ".github/ISSUE_TEMPLATE/gate_missed_it.md",
        "README.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "CHANGELOG.md",
        "FINDINGS.md",
        "LICENSE",
        "pyproject.toml",
        ".gitignore",
    ]
    bad = 0
    for p in must_refuse:
        ok = not is_necessary(p)
        bad += 0 if ok else 1
        print("  refuse  %-44s %s" % (p, "ok" if ok else "FAIL - it was allowed"))
    print()
    for p in must_allow:
        ok = is_necessary(p)
        bad += 0 if ok else 1
        print("  allow   %-44s %s" % (p, "ok" if ok else "FAIL - it was refused"))
    print()
    print("%d case(s), %d failure(s)" % (len(must_refuse) + len(must_allow), bad))
    return 1 if bad else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    paths = tracked()
    if paths is None:
        print("could not list tracked files -- UNKNOWN, which is not the same as clean")
        return 2
    bad = check(paths)
    print("%d tracked file(s) examined" % len(paths))
    if not bad:
        print("every one of them is necessary for this package.")
        return 0
    print()
    print("%d file(s) are not necessary for this package:" % len(bad))
    for p, reason in bad:
        print("   %-52s %s" % (p, reason))
    print()
    print("Keep them somewhere private. If one genuinely belongs here, add its path to")
    print("ALLOW in tools/necessary_files.py in the same change, so the decision is")
    print("reviewed rather than accidental.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
