"""The version this package reports has to be the version it actually is.

WHY THIS EXISTS, and it is not hypothetical: **deadcanary 0.2.0 shipped to PyPI
reporting itself as 0.1.1.** The version lives in two places -- `pyproject.toml`,
which decides what PyPI serves, and `__init__.py`, which decides what
`deadcanary.__version__` says. The release bumped one and not the other, so anyone
who installed it and checked would have concluded the install had failed.

claimproof has had exactly this test since it shipped
(`tests/test_scaffold.py::test_the_version_in_the_package_matches_the_one_being_built`,
whose docstring reads "A wheel whose metadata disagrees with `__version__` installs
a lie"). When deadcanary was added as a second package in this repo, the test was
not brought along -- so the one package without the guard is the one that shipped
the defect it guards against. That is the whole argument of this repo, arriving
from the inside.

Two doors for one fact is the defect; a test that both doors agree is the fix that
does not depend on anyone remembering.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import deadcanary

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_package_reports_a_real_version():
    assert isinstance(deadcanary.__version__, str)
    assert deadcanary.__version__.count(".") == 2
    assert deadcanary.__version__ not in ("", "0.0.0", "unknown")


def test_the_version_in_the_code_matches_the_one_being_built():
    """`__init__.py` against `pyproject.toml`, read off disk.

    This is the one that would have caught the 0.2.0 release, and it needs no
    install to do it -- which matters, because the mistake is made at commit time
    and this fails at commit time.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "no version found in pyproject.toml"
    assert m.group(1) == deadcanary.__version__, (
        "pyproject.toml says %s and deadcanary.__version__ says %s. Whichever is "
        "wrong, a release from here would tell users the other one." % (
            m.group(1), deadcanary.__version__))


def test_the_installed_metadata_agrees_too():
    """And against what pip actually recorded, when there is an install to ask.

    Skipped rather than passed when the package is not installed: absent metadata
    is 'cannot tell', and this repo does not let that read as a pass.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("deadcanary")
    except PackageNotFoundError:  # pragma: no cover - only when not installed
        pytest.skip("deadcanary is not installed, so there is no metadata to compare")

    assert installed == deadcanary.__version__, (
        "the installed distribution is %s but the code says %s" % (
            installed, deadcanary.__version__))
