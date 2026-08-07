#!/usr/bin/env python3
"""Build the wheel, install it into a clean environment, and run everything from
a directory where the source tree is not importable.

This is what CI's `installed` job does, runnable locally before you push. It
exists because every other test in this repo runs against the SOURCE TREE, and a
package can pass all of them while being broken on `pip install`: the wheel is
built by different rules than the repo layout, so a file present locally can be
absent from the distribution and nothing local notices.

    python tools/verify_wheel.py

Exit 0 only if the installed package imports, behaves, ships py.typed, reopens a
stale claim, and passes the whole suite from outside the tree.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILURES: list[str] = []

# Fixtures for the TypedScope check below, assembled rather than written out, so
# this file does not itself carry the pattern its own gate exists to refuse.
_MOUNTS = ("a", "b")
BAD_SCOPE = "roots = [" + ", ".join(repr("/srv/" + n) for n in _MOUNTS) + "]"  # noscope: fixture text for the gate's own check
GOOD_PATH = "LOGFILE = " + repr("/var/log/app.log")
SWALLOWED = "\n".join(["def check():", "    try:", "        return verify()",
                       "    except Exception:", "        return True"])
HONEST = SWALLOWED.replace("return True", "return False")


def step(label: str, cmd: list[str], cwd: Path | None = None,
         expect: int = 0, env: dict | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd or REPO), capture_output=True, text=True,
                       timeout=900, env=env)
    ok = r.returncode == expect
    print(f"  {'ok   ' if ok else 'FAIL '} {label}"
          f"{'' if ok else f'  (exit {r.returncode}, wanted {expect})'}")
    if not ok:
        FAILURES.append(label)
        print((r.stdout or "")[-2000:])
        print((r.stderr or "")[-2000:], file=sys.stderr)
    return r


def main() -> int:
    print(f"claimproof wheel verification, {sys.version.split()[0]}\n")

    dist = REPO / "dist"
    before = set(dist.glob("*.whl")) if dist.is_dir() else set()

    step("build sdist and wheel", [sys.executable, "-m", "build"])
    wheels = sorted(set(dist.glob("*.whl")) - before) or sorted(dist.glob("*.whl"))
    if not wheels:
        print("  FAIL  no wheel was produced")
        return 1
    wheel = max(wheels, key=lambda p: p.stat().st_mtime)
    print(f"        using {wheel.name}")

    with tempfile.TemporaryDirectory() as tmp:
        room = Path(tmp)
        venv = room / "venv"
        elsewhere = room / "elsewhere"
        elsewhere.mkdir()

        step("create a clean virtual environment", [sys.executable, "-m", "venv", str(venv)])
        py = venv / ("Scripts" if os.name == "nt" else "bin") / (
            "python.exe" if os.name == "nt" else "python")

        step("install the wheel and pytest into it",
             [str(py), "-m", "pip", "install", "--quiet", str(wheel), "pytest>=8"])

        step("public API is reachable and behaving from outside the source tree",
             [str(py), "-c", (
                 "import claimproof;"
                 "assert 'site-packages' in claimproof.__file__, claimproof.__file__;"
                 "from claimproof import Gate, Case, Finding, Harness, SelftestError;"
                 "from claimproof import ClaimBasis, Evidence, Status, BasisError;"
                 "from claimproof import Coverage, CoverageError, Diff, Entry;"
                 "from claimproof.gates import UnbackedClaims, TypedScope, SilentSkip;"
                 "from claimproof.hooks import stop_hook, pre_tool_use_hook, gate_invariant;"
                 "g = UnbackedClaims(); assert g.verify();"
                 "assert g.check('It works.'), 'failed to flag an unbacked claim';"
                 "assert g.check('It works. exit=0') == [], 'false positive';"
                 "assert ClaimBasis.selftest(echo=False), 'ClaimBasis cannot prove itself';"
                 "assert Coverage.selftest(echo=False), 'Coverage cannot prove itself';"
                 "t = TypedScope(); assert t.verify();"
                 f"assert t.check({BAD_SCOPE!r}), 'TypedScope missed a typed population';"  # noscope: fixture for the gate's own check
                 f"assert t.check({GOOD_PATH!r}) == [], 'TypedScope cried wolf';"
                 "s = SilentSkip(); assert s.verify();"
                 f"assert s.check({SWALLOWED!r}), 'SilentSkip missed a swallowed check';"
                 f"assert s.check({HONEST!r}) == [], 'SilentSkip cried wolf';"
                 "print('ok')")],
             cwd=elsewhere)

        step("a partial scan must not exit 0 from the installed package",
             [str(py), "-m", "claimproof.coverage"], cwd=elsewhere, expect=2)

        step("py.typed ships, or downstream type checking silently does nothing",
             [str(py), "-c", (
                 "import importlib.util, pathlib;"
                 "spec = importlib.util.find_spec('claimproof');"
                 "p = pathlib.Path(spec.origin).parent / 'py.typed';"
                 "assert p.exists(), 'py.typed missing from the installed package';"
                 "print(p)")],
             cwd=elsewhere)

        step("the advertised demo command runs", [str(py), "-m", "claimproof.demo"],
             cwd=elsewhere)
        step("python -m claimproof runs", [str(py), "-m", "claimproof"], cwd=elsewhere)

        # The new feature, end to end, through the CLI a reader would use.
        (elsewhere / "proof.txt").write_text("green\n", encoding="utf-8")
        step("the installed CLI records a claim",
             [str(py), "-m", "claimproof.basis", "--store", "c.json",
              "--record", "the suite passes", "--evidence", "proof.txt"], cwd=elsewhere)
        step("...and reports it holding",
             [str(py), "-m", "claimproof.basis", "--store", "c.json"], cwd=elsewhere)
        (elsewhere / "proof.txt").write_text("red\n", encoding="utf-8")
        step("...and REOPENS it once the evidence changes, exit 1",
             [str(py), "-m", "claimproof.basis", "--store", "c.json"],
             cwd=elsewhere, expect=1)

        shutil.copytree(REPO / "tests", elsewhere / "tests")
        step("the whole suite passes against the INSTALLED package",
             [str(py), "-m", "pytest", "tests"], cwd=elsewhere)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} step(s) FAILED: " + "; ".join(FAILURES))
        return 1
    print("The wheel installs and works from a clean environment.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
