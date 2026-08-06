"""Gates that ship with the library.

`UnbackedClaims` is the one that matters. It reads a message an agent is about to
send and flags every hard completion claim that has no evidence near it.

`TypedScope` reads source code instead of prose, and flags the other half of the
same problem: a tool that decides for itself what to look at.

Both are deliberately conservative. They only fire on unambiguous cases, because a
gate that cries wolf gets disabled, and a disabled gate is worse than no gate:
everyone still believes it is running.
"""
from __future__ import annotations

import re

from agentattest.core import Case, Finding, Gate

__all__ = ["UnbackedClaims", "TypedScope"]


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


# A string literal that is an absolute path on either platform.
_ABS_PATH = re.compile(
    r"""['"](?:[A-Za-z]:[\\/]|/home/|/Users/|/var/|/opt/|/srv/|/mnt/|/data/)[^'"]*['"]""")

# Only a name that means a POPULATION to walk. Singular names are left alone:
# `ROOT = "/srv/app"` is one project directory and is correct and normal. An
# earlier version of this idea matched `ROOT` too and flagged 94 files whose only
# content was one correct constant. A gate that cries wolf gets switched off,
# which is how the previous two attempts at this died.
_SCOPE_NAME = re.compile(
    r"\b(roots|anchors|scan_?dirs|search_?paths|base_?dirs|scan_?roots|"
    r"populations|watch_?dirs|include_?dirs)\b", re.I)

# An exemption is allowed, but it has to be written on the line, so an exception
# is a visible decision rather than an oversight. This gate's own must-fail
# fixtures use it, which is the honest way to be exempt from your own rule.
_EXEMPT = re.compile(r"#\s*noscope:\s*\S+")


class TypedScope(Gate):
    """Flag source that decides its own population from a hardcoded list of paths.

    The bug looks responsible in review, which is why it keeps happening::

        def default_roots():
            return [<absolute path>, <absolute path>, <absolute path>]

    A list written down once can only contain the places somebody already thought
    of, so the tool's completeness is capped by what its author remembered -- and
    that is usually the exact thing the tool was written to find out. It fails in
    silence: a scan of 4 roots prints the same shape of output as a scan of 40.

    Two shapes are flagged, and only two:

    * **two or more absolute paths on one line**, which is a population by
      definition, whatever it is called;
    * **one absolute path on a line that also names a scope** (`roots`,
      `scan_dirs`, `search_paths`, ...).

    Everything else passes, including a single path assigned to a singular name,
    a log file, a commented-out line, and anything inside a docstring.

    Pair it with `agentattest.hooks.pre_tool_use_hook` and the pattern is refused
    before it lands, rather than found later by somebody reading the diff.
    """

    name = "typed-scope"

    def inspect(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        in_docstring = False

        for i, line in enumerate((text or "").splitlines(), 1):
            # A docstring legitimately quotes the bad pattern in order to explain
            # it. Skipping them is not laziness: this class's own docstring would
            # otherwise flag itself.
            if (line.count('"""') + line.count("'''")) % 2:
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue

            stripped = line.strip()
            if stripped.startswith("#") or _EXEMPT.search(line):
                continue

            paths = _ABS_PATH.findall(line)
            if not paths:
                continue

            if len(paths) >= 2:
                findings.append(Finding(
                    message=f"{len(paths)} absolute paths on one line is a "
                            f"hand-written population, not a discovered one",
                    line=i, excerpt=stripped[:80]))
            elif _SCOPE_NAME.search(line):
                findings.append(Finding(
                    message="an absolute path assigned to something that names a "
                            "scope: discover the population instead of typing it",
                    line=i, excerpt=stripped[:80]))

        return findings

    def selftest_cases(self) -> list[Case]:
        """Every fixture below carries `# noscope:` because the fixture text IS
        the bad pattern, and this gate must not flag its own test data."""
        return [
            # Must flag.
            Case(text='def roots():\n    return ["/srv/app", "/opt/data"]',  # noscope: this gate's own must-fail fixture
                 expect_flagged=True, name="the classic typed-population bug"),
            Case(text='SCAN_ROOTS = ["/home/me/projects"]',  # noscope: this gate's own must-fail fixture
                 expect_flagged=True, name="one path, and the name says scope"),
            Case(text='search_paths = ["C:\\\\Work\\\\a", "C:\\\\Work\\\\b"]',  # noscope: this gate's own must-fail fixture
                 expect_flagged=True, name="windows paths count too"),
            # Must NOT flag. Every one of these is a false alarm that would get
            # the gate switched off, which is worse than not having it.
            Case(text='LOGFILE = "/var/log/app.log"',
                 expect_flagged=False, name="a log path is not a population"),
            Case(text='ROOT = "/srv/app"',
                 expect_flagged=False, name="a single project directory is correct"),
            Case(text="roots = discover_roots()",
                 expect_flagged=False, name="the sanctioned form"),
            Case(text='SCAN_ROOTS = ["/srv/only-mount"]  # noscope: one known mount',
                 expect_flagged=False, name="an exemption with a written reason"),
            Case(text='# roots = ["/srv/a", "/opt/b"]',  # noscope: this gate's own fixture
                 expect_flagged=False, name="a commented-out line"),
            Case(text='"""\nroots = ["/srv/a", "/opt/b"]\n"""',  # noscope: this gate's own fixture
                 expect_flagged=False, name="a docstring explaining the pattern"),
            Case(text="", expect_flagged=False, name="empty"),
        ]
