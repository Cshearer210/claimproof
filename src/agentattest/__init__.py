"""agentattest: agents claim work is done that isn't. This makes them prove it.

    Gate     -- inspect output and block what cannot be backed. selftest_cases()
                is abstract and must include a case the gate is REQUIRED to flag,
                so a gate that has never been made to fail cannot be trusted.
    Case     -- one selftest fixture and its expected verdict.
    Finding  -- one problem a gate found.

    gates.UnbackedClaims -- flags completion claims with no evidence nearby.

    hooks.stop_hook          -- refuse a turn that claims done without proof.
    hooks.pre_tool_use_hook  -- refuse a tool call that breaks an invariant.

    Harness  -- checks that assert against LIVE STATE rather than source code.
                A check returning None reports UNKNOWN and never counts as a pass.
"""

from agentattest.core import Case, Finding, Gate, SelftestError
from agentattest.harness import BROKE, OK, UNKNOWN, Harness, Result

__version__ = "0.2.0"
__all__ = [
    "Case", "Finding", "Gate", "SelftestError",
    "Harness", "Result", "OK", "BROKE", "UNKNOWN",
    "__version__",
]
