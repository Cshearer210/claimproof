#!/usr/bin/env python3
"""A claim that was true when it was made, and is not any more.

Run it: python claim_basis.py

Everything below happens in a throwaway temporary directory, so it changes
nothing on your machine. It builds a tiny project, closes a claim against real
files, then does the two ordinary things that make an old claim false, and shows
that the claim reopens itself both times.

The point: a gate asks whether a claim has evidence *now*. Nothing asks whether
the evidence a claim was closed on is still the evidence it was closed on. So a
"done" from three weeks ago sits in the record looking finished, and the files it
pointed at have been rewritten twice since.
"""
import sys
import tempfile
from pathlib import Path

from claimproof.basis import ClaimBasis


def show(title, basis, **kw):
    print(f"\n{title}")
    print("-" * len(title))
    basis.run(echo=True, **kw)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / "src").mkdir()
        (project / "tests").mkdir()
        (project / "src" / "auth.py").write_text("def login(u, p): ...\n", encoding="utf-8")
        (project / "tests" / "test_auth.py").write_text("def test_login(): ...\n",
                                                        encoding="utf-8")

        # The sources this project measures itself against. Discovered, never
        # typed: it is whatever directories exist. If someone adds a third one
        # next month, every claim closed before it appeared reopens on its own,
        # with nobody having to remember that a new place to look changes old
        # answers.
        def sources():
            return [p.name for p in project.iterdir() if p.is_dir()]

        basis = ClaimBasis(project / "claims.json", root=project, scope=sources)

        basis.record(
            "auth refactor done",
            evidence=["src/auth.py", "tests/test_auth.py"],
            claim_id="auth-refactor",
        )
        print("Closed 'auth refactor done' against 2 files and "
              f"{len(sources())} source(s): {', '.join(sorted(sources()))}")

        show("Nothing has moved yet", basis)

        # 1. Somebody edits the code the claim was closed on. Perfectly normal,
        #    happens every day, and nothing anywhere reopens the claim.
        (project / "src" / "auth.py").write_text(
            "def login(u, p, mfa): ...\n", encoding="utf-8")
        show("Someone edited src/auth.py three weeks later", basis)

        # Re-measuring is the fix, and it keeps what was believed before.
        again = basis.record("auth refactor done",
                             evidence=["src/auth.py", "tests/test_auth.py"],
                             claim_id="auth-refactor")
        print(f"\nRe-measured. The previous basis is kept, not overwritten: "
              f"{len(again.superseded)} superseded version on record.")

        # 2. The harder one. Nothing about the claim changed. The project simply
        #    gained somewhere to look that the claim never looked at, so the
        #    measurement behind it is no longer complete.
        (project / "migrations").mkdir()
        show("The project gained a directory the claim never looked at", basis)

        print("\nThe claim was not wrong when it was made. That is the whole")
        print("difficulty: it was honestly true, measured against everything")
        print("visible at the time, and it went stale in silence. REOPENED means")
        print("re-measure, not 'you lied'. Re-measuring costs seconds. A false")
        print("'done' that nobody ever revisits costs considerably more.")

        return basis.run(echo=False)


if __name__ == "__main__":
    code = main()
    print(f"\nexit {code}")
    sys.exit(code)
