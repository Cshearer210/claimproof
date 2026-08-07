"""agentattest: agents claim work is done that isn't. This makes them prove it.

    Gate     -- inspect output and block what cannot be backed. selftest_cases()
                is abstract and must include a case the gate is REQUIRED to flag,
                so a gate that has never been made to fail cannot be trusted.
    Case     -- one selftest fixture and its expected verdict.
    Finding  -- one problem a gate found.

    gates.UnbackedClaims -- flags completion claims with no evidence nearby.
    gates.TypedScope     -- flags source that decides its own population from a
                            hardcoded list of paths, so "I scanned everything"
                            means whatever the author happened to remember.

    hooks.stop_hook          -- refuse a turn that claims done without proof.
    hooks.pre_tool_use_hook  -- refuse a tool call that breaks an invariant.

    claude_code -- the one-command Claude Code integration:
                   `python -m agentattest.claude_code install` wires the claims
                   gate into a project's Stop hook; the module is also the
                   runtime entry that reads the real transcript at every turn.

    ledger.Ledger      -- every ask recorded verbatim, closed only with
                          evidence or skipped with a reason on the record.
                          Nothing auto-closes; state lives on disk.
    ledger.NothingLeft -- the gate that refuses "all done" while the ledger
                          still holds open items. A claim about one item is
                          left alone; only total claims are checked.

    Coverage -- a count is not a result until it says what it did not look at.
                "22 nodes, 0 broken" reads as the system being healthy and means
                the 22 that were chosen are healthy. Anything discovered and then
                neither examined nor skipped-with-a-measured-reason is UNKNOWN.

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
from agentattest.coverage import Coverage, CoverageError, Diff, Entry
from agentattest.harness import BROKE, OK, UNKNOWN, Harness, Result

__version__ = "0.9.0"
__all__ = [
    "Case", "Finding", "Gate", "SelftestError",
    "Harness", "Result", "OK", "BROKE", "UNKNOWN",
    "BasisError", "Claim", "ClaimBasis", "Evidence", "Status",
    "Coverage", "CoverageError", "Diff", "Entry",
    "__version__",
]
