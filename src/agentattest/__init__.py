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

    ClaimBasis -- what a completion claim was measured against, so that when the
                evidence moves the claim REOPENS instead of quietly becoming a
                lie. Gate asks "is there evidence now"; this asks "is the
                evidence you cited still the evidence you cited".
    Evidence -- one thing a claim rests on, and its fingerprint at the time.
    Status   -- what a recheck concluded about one claim, and why, in plain words.

    The claim verdicts (HOLDS / REOPENED / UNKNOWN / RETIRED) live in
    `agentattest.basis` rather than here on purpose: `UNKNOWN` at this level is
    the Harness display verdict, and one name cannot mean two things.
"""

from agentattest.basis import BasisError, Claim, ClaimBasis, Evidence, Status
from agentattest.core import Case, Finding, Gate, SelftestError
from agentattest.harness import BROKE, OK, UNKNOWN, Harness, Result

__version__ = "0.5.0"
__all__ = [
    "Case", "Finding", "Gate", "SelftestError",
    "Harness", "Result", "OK", "BROKE", "UNKNOWN",
    "BasisError", "Claim", "ClaimBasis", "Evidence", "Status",
    "__version__",
]
