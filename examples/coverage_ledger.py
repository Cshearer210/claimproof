#!/usr/bin/env python3
"""The same work, reported two ways. Run it: python coverage_ledger.py

It builds a throwaway project directory and runs the same trivial audit over it
twice. The first pass reports the way almost every tool reports. The second
attaches the denominator. Nothing about the work changes. Only one of them is
honest about what it did not look at, and only one of them refuses to exit 0.
"""
import sys
import tempfile
from pathlib import Path

from claimproof.coverage import Coverage


def build_project(root: Path) -> None:
    """A small project with the usual mix: source, tests, docs, and a fat cache.

    Every file carries the required header EXCEPT one, and that one is sitting in
    a directory the typed audit below never opens. That is the whole point: the
    defect is not hidden anywhere clever, it is just outside the list somebody
    wrote down once.
    """
    for name, files in [
        ("src", ["app.py", "db.py", "auth.py"]),
        ("tests", ["test_app.py"]),
        ("docs", ["index.md"]),
        ("scripts", ["deploy.sh"]),
        (".cache", [f"blob{i}.bin" for i in range(240)]),
        ("node_modules", [f"pkg{i}.js" for i in range(80)]),
    ]:
        d = root / name
        d.mkdir()
        for f in files:
            body = "x\n" if (name, f) == ("docs", "index.md") else "# header\nx\n"
            (d / f).write_text(body, encoding="utf-8")


def has_a_header(path: Path) -> bool:
    return path.read_text(encoding="utf-8").startswith("#")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_project(root)

        print("A project with 6 top-level directories.\n")
        print("=" * 68)
        print("PASS 1 -- the report almost every tool prints")
        print("=" * 68)

        # The audit everybody writes. The list of places to look is typed, so its
        # completeness is capped by what the author happened to think of.
        checked = 0
        problems = 0
        for name in ["src", "tests"]:                # <- the whole bug, in one line
            for f in (root / name).iterdir():
                checked += 1
                if not has_a_header(f):
                    problems += 1
        print(f"\n  {checked} files checked, {problems} problems\n")
        print("Reads as: the project is fine.")
        print("Means   : the 2 directories I thought of are fine.")
        print("Nothing in that output can tell you which one it is, and there IS")
        print("a real problem in this project.\n")

        print("=" * 68)
        print("PASS 2 -- the same audit, with the denominator attached")
        print("=" * 68)
        print()

        # The population is DISCOVERED. A directory added next month is in scope
        # without anyone remembering to add it here.
        cov = Coverage("directories",
                       discover=lambda: sorted(p.name for p in root.iterdir() if p.is_dir()))

        for name in cov.population():
            d = root / name

            # An exclusion is allowed. An exclusion nobody measured is not: from
            # the outside, a good call and a guess look exactly the same.
            if name in (".cache", "node_modules"):
                cov.skip(name, "vendor or regenerable, not written here",
                         measured=len(list(d.iterdir())))
                continue

            if name == "scripts":
                # Genuinely could not tell. Not a pass, not a failure.
                cov.examine(name, None, "shell scripts, and this audit only reads Python")
                continue

            bad = [f.name for f in d.iterdir() if not has_a_header(f)]
            cov.examine(name, not bad,
                        "every file has a header" if not bad
                        else f"missing a header: {', '.join(bad)}",
                        measured=len(list(d.iterdir())))

        code = cov.run()

        print("\nSame project, same trivial check. The first pass reported 0")
        print("problems and exited 0. The second found a real one, in a directory")
        print("the first never opened, and it exited 1.")
        print()
        print("The first pass was not wrong about anything it looked at. It was")
        print("wrong about how much that was, and it had no way to say so. That")
        print("is what attaching the denominator buys: 4 of 6, not just 4.")
        return code


if __name__ == "__main__":
    code = main()
    print(f"\nexit {code}")
    sys.exit(code)
