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
"""
from deadcanary.hunt import BROKE, KILLED, NOOP, SURVIVED, DbtProject, Outcome, hunt
from deadcanary.mutations import CATALOGUE, Mutation, Target, discover, plan

__version__ = "0.1.0"
__all__ = [
    "DbtProject", "hunt", "Outcome",
    "KILLED", "SURVIVED", "NOOP", "BROKE",
    "Mutation", "Target", "CATALOGUE", "discover", "plan",
    "__version__",
]
