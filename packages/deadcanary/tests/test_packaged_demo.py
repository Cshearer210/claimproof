"""The demo has to survive being PACKAGED, which the source tree cannot prove.

The failure this exists for is specific and quiet: `_demo/` is data, not code, so
setuptools leaves it out unless told. A wheel built without it installs cleanly,
imports cleanly, passes every other test in this suite -- and then
`python -m deadcanary.demo` says the project is missing. Everything looks right
except the one thing the README tells a stranger to run first.

So these tests build a real wheel and look inside it. Reading `src/` instead would
pass whether or not the packaging is correct, which is the whole trap.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "deadcanary/_demo/dbt_project.yml",
    "deadcanary/_demo/profiles.yml",
    "deadcanary/_demo/models/schema.yml",
    "deadcanary/_demo/models/orders.sql",
    "deadcanary/_demo/models/stg_orders.sql",
    "deadcanary/_demo/seeds/raw_orders.csv",
}


def test_the_demo_project_is_present_in_the_source_tree():
    """The cheap half. If this fails, the move went wrong, not the packaging."""
    missing = [rel for rel in EXPECTED
               if not (PKG_ROOT / "src" / rel).is_file()]
    assert not missing, f"missing from src/: {missing}"


def test_demo_imports_without_dbt_installed():
    """Importing the module must not require dbt.

    `deadcanary.demo` is imported by anything that enumerates the package. If the
    import itself pulled in dbt, deadcanary would gain a heavy hard dependency by
    accident -- exactly what the optional extra exists to avoid.
    """
    r = subprocess.run(
        [sys.executable, "-c",
         "import deadcanary.demo as d; assert callable(d.main); print('ok')"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_it_says_what_to_do_instead_of_crashing_when_dbt_is_absent(monkeypatch, capsys):
    """A stranger without dbt gets an instruction, not a traceback."""
    import deadcanary.demo as demo
    monkeypatch.setattr(demo, "dbt_is_installed", lambda: False)
    rc = demo.main([])
    err = capsys.readouterr().err
    assert rc == 2, "a demo that cannot run must not exit 0"
    assert "pip install deadcanary[dbt]" in err
    assert "Traceback" not in err


def test_missing_bundled_project_is_reported_not_silently_skipped(monkeypatch, capsys):
    """Absent-and-fine and present-and-fine must not look the same.

    This is the packaging bug the wheel test guards against, seen from inside: if
    `_demo/` is gone the demo must SAY so and fail, never print a tidy nothing.
    """
    import deadcanary.demo as demo
    monkeypatch.setattr(demo, "DEMO_DIR", PKG_ROOT / "does-not-exist")
    rc = demo.main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "packaging bug" in err


def test_a_built_wheel_actually_carries_the_demo(tmp_path):
    """The one that matters. Build the wheel, open it, look.

    IT BUILDS FROM A PRISTINE COPY, AND THAT IS NOT FUSSINESS -- IT IS THE TEST.
    The first version ran `build` against the package directory in place, and it
    PASSED with `_demo` deleted. setuptools had left a `build/lib/` from an earlier
    run still holding the files, and copied the wheel out of that. The test reported
    the packaging as correct while measuring a stale artifact from a previous build:
    a check that could not fail, which is precisely what this package exists to find
    in other people's suites. Found here by deleting the files and watching it stay
    green.

    Copying to a clean directory first makes the source tree the only possible input.

    Skipped rather than failed when `build` is unavailable: an absent build tool is
    'cannot tell', and reporting that as a pass is the thing this repo exists to
    stop -- so it is a skip that says why.
    """
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("the `build` package is not installed, so the wheel cannot be "
                    "inspected here -- CI installs it")

    pristine = tmp_path / "src-copy"
    shutil.copytree(
        PKG_ROOT, pristine,
        ignore=shutil.ignore_patterns("build", "dist", "*.egg-info", "__pycache__",
                                      ".pytest_cache", "*.duckdb", "target", "logs"))

    out = tmp_path / "dist"
    r = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(pristine)],
        capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stdout + r.stderr

    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"

    with zipfile.ZipFile(wheels[0]) as z:
        names = set(z.namelist())

    missing = sorted(EXPECTED - names)
    assert not missing, (
        "the wheel installs and imports fine but cannot run its own demo. "
        f"missing from {wheels[0].name}: {missing}")
