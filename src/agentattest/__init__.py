"""agentattest: agents claim work is done that isn't. This makes them prove it.

    Gate     -- inspect output and block what cannot be backed. selftest_cases()
                is abstract and must include a case the gate is REQUIRED to flag,
                so a gate that has never been made to fail cannot be trusted.
    Case     -- one selftest fixture and its expected verdict.
    Finding  -- one problem a gate found.

    Harness  -- (Phase 3) registered checks that assert against LIVE STATE rather
                than source. A check returning None reports UNKNOWN, never a pass.
"""

from agentattest.core import Case, Finding, Gate, SelftestError

__version__ = "0.1.0"
__all__ = ["Case", "Finding", "Gate", "SelftestError", "__version__"]
