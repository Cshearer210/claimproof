"""agentattest: agents claim work is done that isn't. This makes them prove it.

Scaffold only at 0.0.1. The public surface lands in Phase 1:

    Gate     -- inspect output, block what cannot be backed. selftest_cases()
                is abstract, so a gate that has never been made to fail on
                purpose cannot be instantiated at all.
    Case     -- one selftest fixture, with the expected verdict.
    Harness  -- registered checks that assert against LIVE STATE, not source.
                A check returning None reports UNKNOWN and never counts as a pass.
"""

__version__ = "0.0.1"
__all__ = ["__version__"]
