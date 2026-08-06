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
import re

from agentattest.core import Case, Finding, Gate

__all__ = ["UnbackedClaims", "TypedScope", "SilentSkip"]


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
# is a visible decision rather than an oversight. Both source gates honour the
# same marker, and both use it on their own fixtures and deliberate degradations,
# which is the honest way to be exempt from your own rule.
#
#     ROOTS = [...]                 # noscope: one known mount, not a population
#     except SyntaxError: return [] # agentattest: lenient by design, see strict=True
_EXEMPT = re.compile(r"#\s*(?:noscope|agentattest)\s*:\s*\S+")


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
        except SyntaxError:
            if self.strict:
                return [Finding(
                    message="this is not parseable Python, so the gate could not "
                            "judge it. Refusing to report it clean")]
            return []  # agentattest: this IS a deliberate degrade, which is why strict= exists

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
