"""deadcanary: find the data tests that cannot fail.

A canary that is already dead cannot warn you about anything, and it looks exactly
like one that is alive and well. Data test suites fill up with them: hundreds of
checks that have been green every morning for two years, some because the data is
healthy and some because they were never capable of going red.

The only way to tell the two apart is to break the data on purpose and see which
tests notice.

    from deadcanary import DbtProject, hunt

    report = hunt(DbtProject("path/to/dbt/project"))
    report["dead_canaries"]     # tests no corruption could make fail

This is mutation testing, which is decades old and well proven for source code
(`mutmut`, `cosmic-ray`), pointed at data quality rules instead.

Three outcomes per corruption, and keeping them apart is the whole discipline:
KILLED (a test caught it), SURVIVED (nothing caught it), NO-OP (the corruption
changed no rows, so nothing was measured). A no-op counted as SURVIVED would
inflate the headline number with corruptions that never happened.

And the other half, because "the data tests pass" is a claim like any other:

    from deadcanary import GreenTestsUnproven, attest, recheck

`GreenTestsUnproven` is a `claimproof.Gate` that refuses that claim unless a
complete run backs it. `attest()` records the proof, and `recheck()` says whether
it still describes the suite that exists now -- adding a test reopens it, because
the old answer covered a suite that no longer exists.
"""
from deadcanary.gate import (GreenTestsUnproven, attest, current_values, recheck,
                             suite_fingerprint)
from deadcanary.hunt import BROKE, KILLED, NOOP, SURVIVED, DbtProject, Outcome, hunt
from deadcanary.mutations import CATALOGUE, Mutation, Target, discover, plan

__version__ = "0.1.1"
__all__ = [
    "DbtProject", "hunt", "Outcome",
    "KILLED", "SURVIVED", "NOOP", "BROKE",
    "Mutation", "Target", "CATALOGUE", "discover", "plan",
    # The seam with claimproof. Exported here rather than left at
    # `deadcanary.gate` because a capability you can only reach by already
    # knowing the submodule name is one nobody finds.
    "GreenTestsUnproven", "attest", "recheck", "current_values", "suite_fingerprint",
    "__version__",
]
