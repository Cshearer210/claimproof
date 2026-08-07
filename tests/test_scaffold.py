"""Phase 0 only proves the package imports and CI is really running.

Deliberately does NOT assert `True == True`. A test that cannot fail is the
exact thing this library exists to argue against, so even the placeholder
asserts something that would break if the package were misconfigured.
"""
import claimproof


def test_package_imports_and_reports_a_version():
    assert isinstance(claimproof.__version__, str)
    assert claimproof.__version__.count(".") == 2


def test_version_is_not_a_placeholder():
    # Catches the classic "shipped with version unset" mistake.
    assert claimproof.__version__ not in ("", "0.0.0", "unknown")


def test_the_version_in_the_package_matches_the_one_being_built():
    """A wheel whose metadata disagrees with `__version__` installs a lie.

    Skipped when the package metadata is unavailable (running straight from a
    source tree that was never installed), rather than passing on absence.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("claimproof")
    except PackageNotFoundError:  # pragma: no cover - only when not installed
        import pytest
        pytest.skip("claimproof is not installed, so there is no metadata to compare")

    assert installed == claimproof.__version__


def test_two_names_for_unknown_do_not_silently_collide():
    """`UNKNOWN` means the Harness display verdict at the top level.

    The claim verdicts are kept in `claimproof.basis` on purpose. If a later
    change re-exports them here, one name starts meaning two things and every
    `from claimproof import UNKNOWN` silently changes value.
    """
    from claimproof import basis

    assert claimproof.UNKNOWN == "??"
    assert basis.UNKNOWN == "UNKNOWN"
    assert "HOLDS" not in claimproof.__all__
