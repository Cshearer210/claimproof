"""Gates that ship with the library.

Three of them, all arguing the same thing from different directions: output that
looks like success while proving nothing.

* `UnbackedClaims` reads a message an agent is about to send, and flags every hard
  completion claim with no evidence near it.
* `TypedScope` reads source, and flags a tool that decides for itself what to look
  at, so "I scanned everything" means whatever the author remembered.
* `SilentSkip` reads source, and flags a check that swallows its own failure and
  lets the run continue as if it had passed.

All three are deliberately conservative. They fire on unambiguous cases only,
because a gate that cries wolf gets disabled, and a disabled gate is worse than no
gate: everyone still believes it is running.
"""
from __future__ import annotations

import ast
import os
import re

from claimproof.core import Case, Finding, Gate

__all__ = ["UnbackedClaims", "TypedScope", "SilentSkip", "NoDenominatorClaim",
           "GitDiffUnbacked", "ExitCodeMismatch", "UnbackedTestCount"]


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
    # A count beside a claim IS a measurement. The first version recognised only a
    # handful of nouns, so real receipts went unrecognised and the gate flagged
    # turns that had shown their working: "223 cases", "0 deleted lines",
    # "all 21 empty". Measured 2026-08-12 against 2,975 real agent turns -- this
    # was one of the three shapes behind roughly half the refusals being wrong.
    # One optional word between the number and the noun, because real receipts read
    # "0 deleted lines" and "12 failing checks", not just "12 checks".
    r"|\b\d+\s+(?:\w+\s+)?(?:tests?|files?|checks?|passed|failed|findings?|rows?|cases?|lines?"
    r"|items?|entries|records?|errors?|warnings?|columns?|tables?|commits?|bytes?"
    r"|chars?|characters?|occurrences?|matches?|instances?|detectors?|scripts?"
    r"|modules?|hits?|results?|of them)\b"
    r"|\ball\s+\d+\b"                        # "all 21 empty"
    r"|\bok\s+\S+\s+\d+\.\d+s\b"            # go test: ok pkg/thing 0.42s
    r"|\bTests? run:\s*\d+\b"               # JUnit: Tests run: 14, Failures: 0
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


# A line that DISPLAYS content rather than asserting something about the work.
#
# ADDED 2026-08-06. This gate blocked a reply offering Chris a menu of candidate
# carousel hooks, because one hook read "...the real mechanism is the reason it
# works." Nothing was being claimed -- he was being asked to pick a line. Left
# alone, every content-review turn in this system (hooks, captions, Skool lesson
# text, ebook copy, anything quoted back for approval) would trip the same way,
# and a gate that flags correct work is the one that gets switched off.
#
# THE ACCEPTED BLIND SPOT, stated rather than hidden: a bare unbacked claim
# written INSIDE a table cell or a blockquote is no longer caught. That is a real
# hole. It is narrow because status tables in this system carry a filename, a
# count, or a shouted PASS/FAIL somewhere in the row, all of which already count
# as evidence -- so the claims this stops seeing are almost entirely quoted prose.
_DISPLAYED = re.compile(
    r"^\s*(?:"
    r"\|"                     # a markdown table row -- a menu or a status table
    r"|>"                     # a blockquote -- someone else's words, or quoted copy
    r"|\d+\.\s+[\"“]"    # a numbered option that opens with a quote mark
    r")"
)


# The claim word used as an ORDINARY ADJECTIVE, which is not a claim at all.
#
# ADDED 2026-08-12 after running this gate over 2,975 real end-of-turn replies.
# It refused "Now proving all 166 shipped ebook cheat sheets still render",
# "Proving the deployed code actually writes a verdict" and "the bar branch's
# fixed-character wrap". In every one the word modifies a noun -- shipped sheets,
# deployed code, fixed-character -- and nothing is being asserted about the work.
# This was the single largest source of wrong refusals.
# The discriminator is the copula. "the deployed code" describes a noun; "it IS
# deployed" asserts a completion. So the words between the determiner and the claim
# may not be a form of `be` or `get` -- without that, "The bug is fixed and it works
# now" read as attributive and a genuine claim stopped being caught. The library's
# own test suite caught that regression before it shipped.
_ATTRIBUTIVE = re.compile(
    r"\b(?:the|a|an|this|that|these|those|all|its|their|his|her|our|your|any|"
    r"each|every|some|no|\d+)\s+"
    r"(?:(?!(?:is|was|are|were|be|been|being|get|got|gets|has|have|had)\b)\w+\s+){0,2}"
    r"(?:fixed|deployed|shipped|verified|confirmed)\s+"
    # ...modifying a real noun. A conjunction or adverb after the word means it was
    # never a modifier: "fixed AND tested" is a claim, "fixed WIDTH" is a description.
    r"(?!(?:and|or|but|so|then|now|yet|because|which|that|when|while|after|before|"
    r"in|on|at|by|to|for|with|as|it|its|this|already|properly|successfully)\b)"
    r"[a-z]\w*"
    r"|\b(?:fixed|deployed|shipped|verified)-\w+",     # or hyphenated: fixed-width
    re.I,
)

# The claim sits inside a conditional, a negation, or something that already
# happened to somebody else. "Caught before it shipped" is a near miss being
# reported, not a completion being claimed.
_HYPOTHETICAL = re.compile(
    r"\b(?:before|until|unless|whether|if|when|once|in case|would|could|should|"
    r"might|may|not|never|no longer|isn't|aren't|wasn't|weren't|hasn't|haven't|"
    r"didn't|don't|doesn't|cannot|can't)\b[^.!?]{0,40}$",
    re.I,
)


class UnbackedClaims(Gate):
    """Flag completion claims that have no evidence within `window` lines.

    WHAT `window` IS, MEASURED RATHER THAN ASSUMED (2026-08-28). It is a cheap
    heuristic, not a measurement, and this library should say so about its own
    knobs before it says it about anyone else's.

    Across 37,997 real assistant messages, claims were labelled BACKED (evidence
    exists anywhere in the message, at any distance) or UNBACKED (none anywhere) --
    labels the window cannot influence, so the answer could not be circular. The
    coverage curve looked decisive: window=2 catches 68% of backed claims, window=8
    catches 92%, window=12 catches 95%. Read alone it says the default is too tight.

    Then the same measurement was run against a null model -- same messages, same
    number of evidence lines, positions randomised. Real distance is
    indistinguishable from random at every percentile. window=2 beats chance by
    about 4 points; every wider window performs at or BELOW it. Proximity is mostly
    an artifact of evidence being dense, not of that evidence belonging to that
    claim. The receipt is `findings/evidence-window-2026-08-28.json`.

    SO DO NOT DERIVE A NEW WINDOW FROM THE COVERAGE CURVE. It moves in the
    direction a reader expects, which makes it the most misleading kind of number:
    it invites a confident wrong conclusion rather than no conclusion.

    WHAT DOES CARRY THE SIGNAL is binary -- whether evidence exists at all. Every
    message carrying a claim and no evidence anywhere is caught at ANY window, so
    the check works and the window is a cheap filter on top of something that does.

    BOUNDARY: that corpus is unusually evidence-dense because the system producing
    it demands evidence, and that density is exactly why proximity carries little
    there. On a sparser corpus it may carry real signal. Re-run the null model
    before assuming this transfers.

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
            if _DISPLAYED.match(line):
                continue                     # content shown for review, not a claim
            match = _CLAIM.search(line)
            if not match:
                continue

            # The word is there, but it is not making a claim: it is describing a
            # noun ("the deployed code"), or it sits under a conditional or a
            # negation ("caught before it shipped").
            if _ATTRIBUTIVE.search(line):
                continue
            if _HYPOTHETICAL.search(line[: match.start()]):
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

            # The three shapes measured on 2,975 real agent turns, 2026-08-12.
            # Each was a wrong refusal; each must now be left alone.
            Case(text="Now proving all 166 shipped ebook cheat sheets still render.",
                 expect_flagged=False, name="'shipped' modifying a noun is not a claim"),
            Case(text="Proving the deployed code actually writes a verdict.",
                 expect_flagged=False, name="'deployed' modifying a noun is not a claim"),
            Case(text="Now the bar branch's fixed-character wrap, which clips labels.",
                 expect_flagged=False, name="hyphenated 'fixed-' is an adjective"),
            Case(text="Caught before it shipped: pythonw resolves to the Store stub.",
                 expect_flagged=False, name="a near miss reported, not a claim"),
            Case(text="I have not fixed the parser yet.",
                 expect_flagged=False, name="a negated claim is not a claim"),
            Case(text="Baseline recorded: 12 tools, 223 cases, all passing.",
                 expect_flagged=False, name="a count IS the receipt"),
            Case(text="Append verified as purely additive (0 deleted lines).",
                 expect_flagged=False, name="zero is a measurement too"),
            Case(text="Verified properly: all 21 empty, three signals agreeing.",
                 expect_flagged=False, name="'all N' is a measurement"),

            # ...and the true positives these must not have blunted.
            Case(text="Deployed. Now fixing the notification gap.",
                 expect_flagged=True, name="a bare 'Deployed.' is still caught"),
            Case(text="Three bugs fixed and measured.",
                 expect_flagged=True, name="a claim with no number is still caught"),
            # Must NOT flag: CONTENT BEING SHOWN FOR REVIEW is not a claim about
            # my own work. Added 2026-08-06 after this gate blocked a menu of
            # candidate carousel hooks because one of them ended "...the real
            # mechanism is the reason it works." Nothing was being claimed; Chris
            # was being asked to pick a line. Every content-review turn -- hooks,
            # captions, lesson text, ebook copy -- would have tripped it, and a
            # gate that flags correct work is the one people switch off.
            Case(text="| 2 | Black cohosh | Lab tests say it never was, and the real "
                      "mechanism is the reason it works. |",
                 expect_flagged=False, name="a table row is content, not a claim"),
            Case(text="> It works, and the plant has been used this way for centuries.",
                 expect_flagged=False, name="a quoted line is content, not a claim"),
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
            cases.append(Case(
                text="Tests run: 14, Failures: 0, Errors: 0\nAll tests pass.",
                expect_flagged=False,
                name="claim + JUnit test count",
            ))
            cases.append(Case(
                text="BUILD SUCCESS\nAll tests pass.",
                expect_flagged=True,
                name="build banner alone is not evidence",
            ))
        if self.window >= 1:
            cases.append(Case(
                text="ok  pkg/thing  0.42s\nAll tests pass.",
                expect_flagged=False,
                name="claim + go test ok line",
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
# is a visible decision rather than an oversight. Both source gates honour the
# same marker, and both use it on their own fixtures and deliberate degradations,
# which is the honest way to be exempt from your own rule.
#
#     ROOTS = [...]                 # noscope: one known mount, not a population
#     except SyntaxError: return [] # claimproof: lenient by design, see strict=True
_EXEMPT = re.compile(r"#\s*(?:noscope|claimproof)\s*:\s*\S+")


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

    Pair it with `claimproof.hooks.pre_tool_use_hook` and the pattern is refused
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


# Names that mean the code was doing the checking, not something incidental.
#
# Anchored at both ends of an underscore-separated word on purpose. Without the
# trailing anchor, `scandir` matched `scan`, so every `os.scandir()` in a
# try/except looked like a swallowed check. That was 1 of the 6 hits in the first
# real-corpus sweep, and a gate whose hits are one-sixth nonsense is a gate people
# stop reading.
_CHECKISH = re.compile(
    r"(?:^|_)(check|verify|validate|assert|selftest|test|audit|scan|inspect|probe|"
    r"finding|violation|lint|grade|health|must_fail)(?:s|ed|ing)?(?:_|$)", re.I)

def _returns_success(node: ast.AST) -> str | None:
    """What a `return` inside an exception handler hands back, if it reads as success.

    Whether that is a BUG depends entirely on what the function was for, which is
    why every one of these only counts inside code that was doing the checking.
    Two measured reasons, both from reading real hits rather than reasoning about
    them:

    * `return 0`, `[]`, `{}`, `""` are wildly ambiguous. A hook returning 0 means
      ALLOW, and failing open there is a deliberate and correct choice; a parser
      returning `[]` for an absent optional file is normal. Counting them
      everywhere flagged 25% of 466 real files.
    * Even `return True` is not damning by itself. `_git_busy()` returning True on
      error means "assume busy, back off", and `_win_alive()` returning True means
      "assume alive, do not steal the lane". Both are the CONSERVATIVE answer --
      the opposite of silently passing -- and both were false alarms.
    """
    if not isinstance(node, ast.Return) or node.value is None:
        return None
    v = node.value
    if isinstance(v, ast.Constant):
        if v.value is True:
            return "True"
        if isinstance(v.value, int) and not isinstance(v.value, bool) and v.value == 0:
            return "0"
        if v.value == "":
            return "an empty string"
    if isinstance(v, ast.List) and not v.elts:
        return "an empty list"
    if isinstance(v, ast.Dict) and not v.keys:
        return "an empty dict"
    return None


def _context(tree: ast.AST) -> dict[int, tuple[str, bool]]:
    """(nearest enclosing function name, is inside a loop) for every node."""
    out: dict[int, tuple[str, bool]] = {}

    def walk(node: ast.AST, name: str, looping: bool) -> None:
        for child in ast.iter_child_nodes(node):
            child_name = (child.name
                          if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                          else name)
            # A function defined inside a loop starts its own non-loop context.
            child_loop = (False if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                          else looping or isinstance(child, (ast.For, ast.AsyncFor, ast.While)))
            out[id(child)] = (child_name, child_loop)
            walk(child, child_name, child_loop)

    walk(tree, "", False)
    return out


def _is_a_check(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            fn = child.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None) or ""
            if _CHECKISH.search(name):
                return True
    return False


class SilentSkip(Gate):
    """Flag a check that swallows its own failure and lets the run continue.

    The shape, which passes review every time because it looks defensive::

        try:
            result = verify_everything()
        except Exception:
            print("SKIPPED: could not run the check")
        return True

    Nothing alarms. The build goes green. The check has not run in eight months
    and the output is identical to the output it produced when it worked. This is
    the same failure as a gate with no must-fail case, one layer further down.

    Two shapes are flagged, and only two. Both share one property: **nothing is
    recorded anywhere**, so the run's output is identical to a run where the check
    passed.

    1. **An exception handler that returns success** (`True`, `0`, `[]`, `{}` or
       an empty string) from a function whose name says it was doing the checking.
       On failure, report that all is well.
    2. **`except: pass` wrapped around something that was doing the checking**
       (a call named `check`, `verify`, `validate`, `selftest`, ...), outside a
       loop.

    A handler that re-raises is never flagged, nor is one that returns a failure
    or an UNKNOWN, nor `try/except: pass` around something incidental like a
    cleanup or an optional import, nor anything inside a loop, where skipping one
    item is ordinary behaviour.

    **A third rule was written and then deleted, and that is worth knowing before
    you re-add it.** It flagged a handler that printed a skip word and carried on
    -- the shape usually described as "prints SKIPPED and lets the build pass".
    Over 466 real files it produced 40 of 45 hits, and every one read by eye was a
    logged loop-item skip or a handler that recorded the failure into a list of
    failures. The flaw is in the idea, not the tuning: a handler that announces a
    skip **is not silent**, and what makes that pattern a bug is the exit code
    afterwards, which rule 1 already covers. Narrowing it further would have been
    tuning against a corpus rather than reasoning about the pattern.

    Measured flag rate with the two surviving rules: **0 of the 26 Python files in
    this repository, and 5 of 466 files (1.1%) of a real production system** -- and
    every one of those five read by eye before the gate was wired in.

    **Text that is not parseable Python yields no findings**, because this gate
    reads Python and anything else is outside what it can judge rather than a
    failure of it. Pass `strict=True` to have it say so instead of staying quiet,
    and prefer `hooks.gate_invariant(SilentSkip(), suffixes=(".py",))` so it only
    ever sees files it can actually read.
    """

    name = "silent-skip"

    def __init__(self, strict: bool = False) -> None:
        self.strict = strict
        super().__init__()

    def inspect(self, text: str) -> list[Finding]:
        source = text or ""
        if not source.strip():
            return []
        try:
            tree = ast.parse(source)
        # ValueError, not just SyntaxError: a file containing a NUL byte makes
        # ast.parse raise `ValueError: source code string cannot contain null
        # bytes` on Python 3.10, and an uncaught exception here takes down the
        # turn this gate was guarding. Found 2026-08-07 by CI on 3.10 -- the
        # local 3.13 run passed, which is the whole argument for the version
        # matrix. RecursionError joins them: a deeply nested expression can
        # blow the stack inside the parser.
        except (SyntaxError, ValueError, RecursionError):
            if self.strict:
                return [Finding(
                    message="this is not parseable Python, so the gate could not "
                            "judge it. Refusing to report it clean")]
            return []  # claimproof: this IS a deliberate degrade, which is why strict= exists

        exempt = {i for i, line in enumerate(source.splitlines(), 1)
                  if _EXEMPT.search(line)}
        context = _context(tree)

        findings: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            function_name, in_loop = context.get(id(node), ("", False))
            for handler in node.handlers:
                for f in self._judge(node, handler, function_name, in_loop):
                    if f.line not in exempt and handler.lineno not in exempt:
                        findings.append(f)
        return sorted(findings, key=lambda f: (f.line or 0, f.message))

    def _judge(self, block: ast.Try, handler: ast.ExceptHandler,
               function_name: str, in_loop: bool) -> list[Finding]:
        body = handler.body
        line = handler.lineno
        reraises = any(isinstance(n, ast.Raise) for stmt in body for n in ast.walk(stmt))
        if reraises:
            return []

        returns = [n for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.Return)]

        # Rule 1 keys on the FUNCTION NAME, never on what the try body called.
        # The name is what tells you the returned value means "it is fine";
        # the call only tells you something was being done. `_win_alive(pid)`
        # calls `probe()` and returns True on error, and that True means "assume
        # alive, do not steal the lane" -- the conservative answer, not a pass.
        if _CHECKISH.search(function_name):
            for r in returns:
                literal = _returns_success(r)
                if not literal:
                    continue
                where = f" from {function_name}()" if function_name else ""
                return [Finding(
                    message=f"an exception handler returns {literal}{where}, so a "
                            f"failure is reported as success",
                    line=r.lineno,
                    excerpt=f"except -> return {literal}")]

        if (len(body) == 1 and isinstance(body[0], ast.Pass)
                and not in_loop and _is_a_check(block)):
            return [Finding(
                message="a check is wrapped in try/except that does nothing, so if "
                        "it throws, the run continues as though it had passed",
                line=line,
                excerpt="except -> pass, around a check")]

        return []

    def selftest_cases(self) -> list[Case]:
        """Cases valid for THIS gate's configuration.

        The unparseable-text case flips with `strict`, because a strict gate makes
        the opposite guarantee. Asserting the lenient expectation against a strict
        gate would be testing a promise it never made -- the same trap
        `UnbackedClaims` hit with its `window`.
        """
        unparseable = Case(
            text="this is not python at all ((",
            expect_flagged=self.strict,
            name=("unparseable text is refused, not called clean" if self.strict
                  else "unparseable text is out of scope, not a finding"))

        return [
            unparseable,
            # Must flag.
            Case(text="def check():\n"
                      "    try:\n        return verify()\n"
                      "    except Exception:\n        return True\n",
                 expect_flagged=True, name="returns True on failure"),
            Case(text="def check():\n"
                      "    try:\n        run()\n"
                      "    except Exception:\n        return 0\n",
                 expect_flagged=True, name="returns 0 on failure"),
            Case(text="def findings():\n"
                      "    try:\n        return scan_it()\n"
                      "    except Exception:\n        return []\n",
                 expect_flagged=True, name="returns no findings on failure"),
            Case(text="def gate():\n"
                      "    try:\n        validate_everything()\n"
                      "    except Exception:\n        pass\n",
                 expect_flagged=True, name="except pass around a check"),
            # Must NOT flag. Each of these is a false alarm that would get the
            # gate switched off, which is worse than not having it.
            Case(text="try:\n    run()\nexcept Exception as e:\n    raise RuntimeError(e)\n",
                 expect_flagged=False, name="re-raises"),
            Case(text="def check():\n"
                      "    try:\n        return verify()\n"
                      "    except Exception as e:\n        return False\n",
                 expect_flagged=False, name="returns a FAILURE on failure, correctly"),
            Case(text="def check():\n"
                      "    try:\n        return verify()\n"
                      "    except Exception as e:\n        return None, str(e)\n",
                 expect_flagged=False, name="reports UNKNOWN on failure, correctly"),
            Case(text="try:\n    os.unlink(tmp)\nexcept OSError:\n    pass\n",
                 expect_flagged=False, name="incidental cleanup, not a check"),
            Case(text="try:\n    import ujson as json\nexcept ImportError:\n    import json\n",
                 expect_flagged=False, name="an optional import"),
            Case(text="def check_all():\n"
                      "    for f in files:\n"
                      "        try:\n            check_one(f)\n"
                      "        except OSError as e:\n            print(f'SKIP {f}: {e}')\n",
                 expect_flagged=False,
                 name="skipping one item of a loop, and saying so, is normal"),
            Case(text="def check():\n"
                      "    try:\n        return verify()\n"
                      "    except Exception as e:\n"
                      "        fails.append(f'could not run: {e}')\n"
                      "        return False\n",
                 expect_flagged=False,
                 name="records the failure AND returns failure, correctly"),
            Case(text="def read_config():\n"
                      "    try:\n        return json.load(open(p))\n"
                      "    except OSError:\n        return {}\n",
                 expect_flagged=False,
                 name="an empty dict from a reader is normal, not a swallowed check"),
            Case(text="def _git_busy():\n"
                      "    try:\n        return subprocess.run(...).returncode == 0\n"
                      "    except Exception:\n        return True\n",
                 expect_flagged=False,
                 name="True as the CONSERVATIVE answer, the opposite of passing"),
            Case(text="", expect_flagged=False, name="empty"),
        ]


# A clean/zero result claim: "0 issues", "no errors found", "found nothing",
# "all clear". One optional adjective is allowed between the number/word and the
# noun ("0 security issues"), matching the shape _EVIDENCE already uses.
_ZERO_CLAIM = re.compile(
    r"\b(?:0|no|zero|none)\s+(?:\w+\s+)?"
    r"(?:issues?|errors?|problems?|findings?|failures?|bugs?)\s+(?:found|remain(?:ing)?)?"
    r"|\ball\s+clear\b"
    r"|\bfound\s+nothing\b"
    r"|\bnothing\s+(?:wrong|found)\b",
    re.I,
)

# A stated population: "of N", "N/N", "N files checked", "every file in the
# repo", or an honest refusal ("I did not check"). Deliberately EXCLUDES "the
# whole X" -- adversarial testing found "went through the whole authentication
# module" reads as a real denominator but is just as unfalsifiable as none at
# all: it names no count and nothing to re-derive it from.
_DENOMINATOR = re.compile(
    r"\bof\s+\d+\b"
    r"|\b\d+\s*/\s*\d+\b"
    r"|\b\d+\s+(?:\w+\s+)?(?:files?|checks?|cases?|items?)\s+checked\b"
    r"|\bevery\s+\w+\s+in\s+the\s+\w+\b"
    r"|\bi\s+did\s+not\s+check\b",
    re.I,
)


class NoDenominatorClaim(Gate):
    """Flags a clean/zero result with no stated population.

    The mirror of `UnbackedClaims` for negative claims. "0 issues found" sounds
    exactly as authoritative whether the scan covered 3 files or 3,000 -- or
    whether anything was scanned at all. Without a denominator, a clean result
    and a skipped check are the same sentence.
    """

    def inspect(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for m in _ZERO_CLAIM.finditer(text):
            start = max(0, m.start() - 120)
            end = min(len(text), m.end() + 120)
            neighbourhood = text[start:end]
            if not _DENOMINATOR.search(neighbourhood):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(Finding(
                    message="a clean/zero result claim with no stated population "
                            "nearby -- how many things were actually checked?",
                    line=line, excerpt=m.group(0)[:60]))
        return findings

    def selftest_cases(self) -> list[Case]:
        return [
            # Must flag.
            Case(text="0 issues found.", expect_flagged=True,
                 name="bare zero, no population"),
            Case(text="No errors found.", expect_flagged=True,
                 name="bare 'no errors', no population"),
            Case(text="All clear.", expect_flagged=True,
                 name="all clear, alone"),
            Case(text="I went through the whole authentication module.\n"
                      "0 security issues found.",
                 expect_flagged=True,
                 name="'the whole X' is not a real denominator (adversarial)"),
            Case(text="Found nothing wrong with the config.", expect_flagged=True,
                 name="found-nothing phrasing, no population"),
            # Must NOT flag.
            Case(text="0 issues found out of 43 checks.", expect_flagged=False,
                 name="zero with a real denominator"),
            Case(text="0/26 findings across the sweep.", expect_flagged=False,
                 name="N/N form"),
            Case(text="Scanned 12 files checked, 0 issues found.",
                 expect_flagged=False,
                 name="files-checked form"),
            Case(text="Every file in the repo was checked. 0 issues found.",
                 expect_flagged=False,
                 name="'every file in the repo', an honest population"),
            Case(text="I did not check for this. 0 issues found in what I did look at.",
                 expect_flagged=False,
                 name="an honest refusal counts as stating the limit"),
            Case(text="12 tests passed, 3 failed.", expect_flagged=False,
                 name="a real non-zero result, nothing to flag"),
            Case(text="", expect_flagged=False, name="empty"),
        ]

class GitDiffUnbacked(Gate):
    """A claim that names a FILE as fixed must show that file in a real diff.

    `UnbackedClaims` asks whether a turn showed evidence of any kind. This asks a
    narrower and harder question: when the claim NAMES something -- "fixed the
    parser bug in parser.py" -- does the diff in that same turn actually touch
    `parser.py`?

    WHY THAT IS A DIFFERENT QUESTION. A turn can be dense with evidence and still
    be wrong about which file it changed. Test output, a traceback and a file
    listing all satisfy "show your work" while the named file was never opened.
    The failure looks exactly like success, which is the shape this whole library
    exists for.

    THE DIFF IS READ FROM THE TURN, NOT FROM THE REPOSITORY, and that is deliberate.
    A gate that shells out to `git` answers a question about the working tree NOW,
    which is not the same as what the turn did -- the tree moves between the claim
    and the check, and a gate whose answer depends on timing is a gate nobody can
    reproduce. Paste the diff into the turn and the check is deterministic, offline,
    and provable from the text alone.

    A turn carrying NO diff at all is left to `UnbackedClaims`; this gate has
    nothing to say about it and says nothing, rather than reporting a second
    finding for one defect.

    >>> GitDiffUnbacked().check("Fixed the bug in parser.py.\n"
    ...                         " src/other.py | 4 ++--")           # doctest: +ELLIPSIS
    [Finding(...)]
    """

    #: A claim that names its target, e.g. "fixed the parser bug in parser.py".
    NAMED_FIX = re.compile(
        r"(?i)\b(?:fixed|repaired|patched|corrected|resolved)\b[^.\n]{0,80}?"
        r"\b([\w./-]+\.(?:py|js|ts|tsx|go|rs|java|rb|sql|yml|yaml|toml|md))\b")
    #: A `git diff --stat` line: `path/to/file.py | 12 +++---`
    DIFF_STAT = re.compile(r"(?m)^\s*([\w./-]+\.\w+)\s*\|\s*\d+\s*[+-]")
    #: A unified-diff header: `+++ b/path/to/file.py`
    DIFF_HEAD = re.compile(r"(?m)^\+\+\+ b/([\w./-]+\.\w+)")

    def inspect(self, text: str) -> list[Finding]:
        touched = {os.path.basename(m) for m in self.DIFF_STAT.findall(text)}
        touched |= {os.path.basename(m) for m in self.DIFF_HEAD.findall(text)}
        if not touched:
            return []          # no diff in this turn: UnbackedClaims' question, not ours
        out: list[Finding] = []
        for m in self.NAMED_FIX.finditer(text):
            named = os.path.basename(m.group(1))
            if named not in touched:
                line = text[:m.start()].count("\n") + 1
                out.append(Finding(
                    message=("claims %r was fixed, but the diff in this turn touches "
                             "%s" % (named, ", ".join(sorted(touched))[:80])),
                    line=line,
                    excerpt=" ".join(m.group(0).split())[:90]))
        return out

    def selftest_cases(self) -> list[Case]:
        stat = " src/claimproof/parser.py | 12 ++++++------\n"
        other = " src/claimproof/other.py  |  4 ++--\n"
        return [
            # MUST FLAG: the named file is not the file that changed.
            Case(text="Fixed the parser bug in parser.py.\n" + other,
                 expect_flagged=True),
            Case(text="Patched auth.py and the tests pass.\n"
                      "+++ b/src/claimproof/other.py\n", expect_flagged=True),
            # GUARD CASES -- each is a shape a careless version would flag.
            Case(text="Fixed the parser bug in parser.py.\n" + stat,
                 expect_flagged=False),
            Case(text="Fixed the parser bug in parser.py.\n"
                      "+++ b/src/claimproof/parser.py\n", expect_flagged=False),
            # no diff anywhere: not this gate's question
            Case(text="Fixed the parser bug in parser.py. All tests pass.",
                 expect_flagged=False),
            # a claim that names nothing cannot be checked against a diff
            Case(text="Fixed it.\n" + other, expect_flagged=False),
            # the file is named in prose but the claim is not a fix
            Case(text="parser.py is where the tokenizer lives.\n" + other,
                 expect_flagged=False),
        ]


# --------------------------------------------------------------------------
# Feature 2: captured exit codes, not quoted ones.
#
# A claim about how a command went is only worth the exit code that was
# recorded WHEN IT RAN. `claimproof.capture.run()` is the wrapper that records
# it; this gate reads those receipts back out of the turn and compares them to
# what the sentence says.
# --------------------------------------------------------------------------

# Written by claimproof.capture.run() at execution time. The format is fixed
# and boring on purpose: a gate that has to guess at its own evidence format is
# a gate that quietly stops finding anything the day the format drifts.
_EXIT_RECEIPT = re.compile(r"(?m)^\s*\[claimproof:exit\]\s+(-?\d+)\s+(.*\S)\s*$")

# "it exited 0", "exit code 2", "returned 1"
_QUOTED_EXIT = re.compile(
    r"(?i)\b(?:exit(?:ed|\s+code|\s+status)?|return(?:ed|\s+code)?)\s*[:=]?\s*(-?\d+)\b")

# Narrower than the module-level _CLAIM: only claims about how a RUN went.
_RUN_WENT_WELL = re.compile(
    r"(?i)\b("
    r"all (?:tests? )?pass(?:ing|ed|es)?|tests? pass(?:ing|ed|es)?|"
    r"(?:the )?(?:suite|build|run|check)s? (?:is |are |was |were )?(?:green|clean|passing|passed)|"
    r"exited cleanly|ran clean(?:ly)?|no errors|all green"
    r")\b")


class ExitCodeMismatch(Gate):
    """A sentence about a command must agree with the exit code that was captured.

    Two ways a turn can disagree with its own receipts, and this gate catches
    exactly those two:

    * It QUOTES an exit code no captured run produced. Saying "it exited 0" when
      the recorded codes are 2 and 2 is not a rounding error -- it is the number
      being written from memory instead of read from the run.
    * It claims the run WENT WELL while every captured run failed. Deliberately
      "every", not "any": a `grep` that finds nothing exits 1, and a gate that
      fired on that would be switched off inside a week, taking the real cases
      with it.

    A turn with no receipts is left alone. That is not this gate's question --
    it is `UnbackedClaims`', which asks whether a claim has any evidence at all.
    """

    name = "exit-code-mismatch"

    def inspect(self, text: str) -> list[Finding]:
        runs = [(int(rc), cmd) for rc, cmd in _EXIT_RECEIPT.findall(text)]
        if not runs:
            return []   # nothing was captured: not our question

        codes = {rc for rc, _ in runs}
        out: list[Finding] = []
        lines = text.splitlines()

        for m in _QUOTED_EXIT.finditer(text):
            quoted = int(m.group(1))
            if quoted in codes:
                continue
            line = text[:m.start()].count("\n") + 1
            out.append(Finding(
                message=("says exit %d, but the codes captured when the commands "
                         "actually ran were %s"
                         % (quoted, ", ".join(str(c) for c in sorted(codes)))),
                line=line,
                excerpt=lines[line - 1].strip()[:120] if line <= len(lines) else "",
            ))

        if 0 not in codes:
            for m in _RUN_WENT_WELL.finditer(text):
                line = text[:m.start()].count("\n") + 1
                worst = sorted(runs, key=lambda r: -abs(r[0]))[0]
                out.append(Finding(
                    message=("claims the run went well, but every captured command "
                            "failed -- %r exited %d" % (worst[1], worst[0])),
                    line=line,
                    excerpt=lines[line - 1].strip()[:120] if line <= len(lines) else "",
                ))
        return out

    def selftest_cases(self) -> list[Case]:
        ok = "[claimproof:exit] 0 pytest -q\n"
        bad = "[claimproof:exit] 1 pytest -q\n"
        grep_miss = "[claimproof:exit] 1 grep -r TODO src/\n"
        return [
            Case(bad + "All tests pass.", True, "success claimed, only run failed"),
            Case(bad + "The suite is green now.", True, "suite green, only run failed"),
            Case(ok + "It exited 2, so I looked at the log.", True,
                 "quotes an exit code no run produced"),

            Case(ok + "All tests pass.", False, "claim agrees with the receipt"),
            Case(ok + grep_miss + "All tests pass.", False,
                 "grep found nothing (exit 1) but the suite really passed"),
            Case(bad + "It failed with exit 1, so the fix is not done.", False,
                 "honest report of a failing run"),
            Case(bad + "Renamed the helper for clarity.", False,
                 "a failing run and no claim about it"),
            Case("All tests pass.", False, "no receipts captured at all"),
        ]


# --------------------------------------------------------------------------
# Feature 3: a cited test count is read out of the real report, never the prose.
# --------------------------------------------------------------------------

# pytest --junit-xml=<path>, or the receipt capture.run() writes for one.
_JUNIT_PATH = re.compile(
    r"(?i)(?:--junit-?xml[= ]|\[claimproof:junit\]\s+)([^\s'\"`]+\.xml)")

_CITED_COUNT = re.compile(
    r"(?i)\b(?:all\s+)?(\d{1,6})\s+(?:tests?\s+(?:pass(?:ed|ing|es)?|succeeded)"
    r"|pass(?:ed|ing)\b)")


class UnbackedTestCount(Gate):
    """A cited test count must match the JUnit report the turn names.

    The principle is the one `Coverage` already uses: read the artifact, never
    the sentence about it. What is new here is that the NUMBER is verified, not
    merely the presence of a number-shaped string -- "all 105 tests pass" beside
    a report holding 105 tests and 3 failures is the exact shape that reads as
    proof and is not.

    A named report that cannot be read is a finding, not a pass. A report that
    cannot be opened and a suite that is genuinely green produce the same
    silence otherwise, and only one of them is good news.
    """

    name = "test-count-unbacked"

    def _read(self, path: str):
        import xml.etree.ElementTree as ET
        root = ET.parse(path).getroot()
        nodes = [root] if root.tag == "testsuite" else list(root)
        total = fail = err = skip = 0
        for n in nodes:
            total += int(n.get("tests", 0) or 0)
            fail += int(n.get("failures", 0) or 0)
            err += int(n.get("errors", 0) or 0)
            skip += int(n.get("skipped", 0) or 0)
        return total, fail, err, skip

    def inspect(self, text: str) -> list[Finding]:
        m = _JUNIT_PATH.search(text)
        if not m:
            return []   # no report named: not our question
        path = m.group(1)

        cited = list(_CITED_COUNT.finditer(text))
        if not cited:
            return []   # a report and no count to check against it

        lines = text.splitlines()

        def at(match):
            line = text[:match.start()].count("\n") + 1
            return line, (lines[line - 1].strip()[:120] if line <= len(lines) else "")

        try:
            total, fail, err, skip = self._read(path)
        except Exception as exc:
            line, excerpt = at(cited[0])
            return [Finding(
                message=("cites a test count, but the report it names (%s) could not "
                         "be read: %s" % (path, exc.__class__.__name__)),
                line=line, excerpt=excerpt)]

        passed = total - fail - err - skip
        out: list[Finding] = []
        for c in cited:
            n = int(c.group(1))
            line, excerpt = at(c)
            if fail or err:
                out.append(Finding(
                    message=("cites %d passing, but %s records %d failure(s) and "
                             "%d error(s) out of %d" % (n, path, fail, err, total)),
                    line=line, excerpt=excerpt))
            elif n != passed:
                out.append(Finding(
                    message=("cites %d passing, but %s records %d passing out of %d"
                             % (n, path, passed, total)),
                    line=line, excerpt=excerpt))
        return out

    def selftest_cases(self) -> list[Case]:
        import tempfile
        d = tempfile.mkdtemp(prefix="claimproof-junit-")

        def write(name, tests, failures=0, errors=0, skipped=0):
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('<?xml version="1.0"?><testsuites><testsuite '
                         'tests="%d" failures="%d" errors="%d" skipped="%d"/>'
                         "</testsuites>" % (tests, failures, errors, skipped))
            return p

        green = write("green.xml", 105)
        red = write("red.xml", 105, failures=3)
        skipped = write("skipped.xml", 106, skipped=1)
        missing = os.path.join(d, "nothing-here.xml")

        return [
            Case("All 105 tests pass. --junit-xml=%s" % red, True,
                 "report records 3 failures"),
            Case("200 tests passed. --junit-xml=%s" % green, True,
                 "cited number is not the report's number"),
            Case("All 105 tests pass. --junit-xml=%s" % missing, True,
                 "named report cannot be read -- unknown is not clean"),

            Case("All 105 tests pass. --junit-xml=%s" % green, False,
                 "cited number matches the report"),
            Case("105 passed, 1 skipped. --junit-xml=%s" % skipped, False,
                 "skips are not failures and are not counted as passes"),
            Case("Reran the suite. --junit-xml=%s" % green, False,
                 "a report and no count cited against it"),
            Case("All 105 tests pass.", False, "no report named at all"),
        ]
