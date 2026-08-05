"""Gates that ship with the library.

`UnbackedClaims` is the one that matters. It reads a message an agent is about to
send and flags every hard completion claim that has no evidence near it.

It is deliberately conservative. It only fires on unambiguous claims with nothing
resembling evidence anywhere nearby, because a gate that cries wolf gets disabled,
and a disabled gate is worse than no gate: everyone still believes it is running.
"""
from __future__ import annotations

import re

from agentattest.core import Case, Finding, Gate

__all__ = ["UnbackedClaims"]


# Hard claims only. "should work", "I think this fixes it" and other hedges are
# left alone on purpose -- they are honest about their own uncertainty.
_CLAIM = re.compile(
    r"\b("
    r"fixed|verified|confirmed working|works now|it works|working now|"
    r"all (?:tests? )?pass(?:ing|ed|es)?|tests? pass(?:ing|ed|es)?|"
    r"deployed|shipped|done and (?:verified|tested)|all green|no errors"
    r")\b",
    re.I,
)

# Any one of these near a claim clears it. Broad on purpose: the goal is to catch
# claims made into a total vacuum, not to grade the quality of the evidence.
_EVIDENCE = re.compile(
    r"```"                                  # a fenced block
    r"|\bexit(?:\s*code|\s*status)?\s*[=:]?\s*\d"
    r"|\b\d+\s*(?:/|of)\s*\d+\b"            # 12/12
    r"|\b\d+\s+(?:tests?|files?|checks?|passed|failed|findings?|rows?)\b"
    r"|\$\s|\bstdout\b|\bstderr\b|\boutput\b|\bran\b|\blogs?\b"
    r"|\.(?:py|js|ts|sh|json|toml|yml|yaml|md)\b"
    r"|:\d+\b"                              # file:line
    r"|→|->|✓|✅",
    re.I,
)

# Deliberately CASE-SENSITIVE, and kept separate from the pattern above.
#
# This started as `(?:PASS|FAIL|OK|ERROR)` inside the case-insensitive pattern.
# That made the lowercase word "pass" count as evidence, so the claim
# "All tests pass." cleared ITSELF and the gate silently approved every claim
# containing the word. The gate's own required must-fail case caught it before
# this ever shipped, which is the entire argument for making that case mandatory.
#
# Real tool output shouts these tokens. Prose does not.
_EVIDENCE_SHOUTED = re.compile(r"\b(?:PASS|PASSED|FAIL|FAILED|OK|ERROR|BROKE|UNKNOWN)\b")


def _has_evidence(neighbourhood: str) -> bool:
    return bool(_EVIDENCE.search(neighbourhood) or _EVIDENCE_SHOUTED.search(neighbourhood))


class UnbackedClaims(Gate):
    """Flag completion claims that have no evidence within `window` lines.

    >>> UnbackedClaims().check("It works.")            # doctest: +ELLIPSIS
    [<...Finding...>]
    >>> UnbackedClaims().check("It works. exit=0")
    []
    """

    name = "unbacked-claims"

    def __init__(self, window: int = 2) -> None:
        if window < 0:
            raise ValueError("window must be >= 0")
        self.window = window
        super().__init__()

    def inspect(self, text: str) -> list[Finding]:
        lines = (text or "").splitlines()
        findings: list[Finding] = []

        for i, line in enumerate(lines):
            match = _CLAIM.search(line)
            if not match:
                continue

            lo = max(0, i - self.window)
            hi = min(len(lines), i + self.window + 1)
            neighbourhood = "\n".join(lines[lo:hi])

            if _has_evidence(neighbourhood):
                continue

            findings.append(
                Finding(
                    message=f"completion claim {match.group(0)!r} with no nearby evidence",
                    line=i + 1,
                    excerpt=line.strip()[:80],
                )
            )

        return findings

    def selftest_cases(self) -> list[Case]:
        """Cases valid for THIS gate's window.

        A gate configured with window=0 genuinely cannot see evidence on an
        adjacent line, so asserting a multi-line fixture against it would be
        testing a guarantee it never made. The multi-line cases are therefore
        added only when the window can actually reach them.
        """
        cases = [
            # Must flag: bare claims into a vacuum. Same line, any window.
            Case(text="It works.", expect_flagged=True, name="bare claim"),
            Case(text="Everything is fixed now.", expect_flagged=True, name="fixed, no proof"),
            Case(text="Deployed.", expect_flagged=True, name="deployed, no proof"),
            Case(text="All tests pass.", expect_flagged=True, name="lowercase pass is not evidence"),
            # Must NOT flag: claims carrying their receipt on the same line.
            Case(text="It works. exit=0", expect_flagged=False, name="claim + exit code"),
            Case(
                text="Fixed the import in core.py:41 and the 12 tests now pass.",
                expect_flagged=False,
                name="claim + file:line",
            ),
            # Must NOT flag: hedged language is honest, leave it alone.
            Case(text="This should work, but I have not run it.", expect_flagged=False,
                 name="hedged, not a hard claim"),
            Case(text="", expect_flagged=False, name="empty"),
        ]

        if self.window >= 1:
            cases.append(Case(
                text="I refactored the parser.\nAll tests pass.\nOn to the next thing.",
                expect_flagged=True,
                name="claim buried in prose",
            ))
        if self.window >= 2:
            cases.append(Case(
                text="Ran the suite:\n```\n12 passed in 0.06s\n```\nAll tests pass.",
                expect_flagged=False,
                name="claim + fenced output two lines up",
            ))
        return cases
