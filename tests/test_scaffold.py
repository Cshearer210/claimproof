"""Phase 0 only proves the package imports and CI is really running.

Deliberately does NOT assert `True == True`. A test that cannot fail is the
exact thing this library exists to argue against, so even the placeholder
asserts something that would break if the package were misconfigured.
"""
import agentattest


def test_package_imports_and_reports_a_version():
    assert isinstance(agentattest.__version__, str)
    assert agentattest.__version__.count(".") == 2


def test_version_is_not_a_placeholder():
    # Catches the classic "shipped with version unset" mistake.
    assert agentattest.__version__ not in ("", "0.0.0", "unknown")
