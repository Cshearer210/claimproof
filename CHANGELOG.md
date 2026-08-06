# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0]

The third instance of the same argument: a check that swallows its own failure, so the run's output
is identical to a run where the check passed.

### Added
- `gates.SilentSkip`. Two shapes, both sharing one property -- **nothing is recorded anywhere**: an
  exception handler that returns success (`True`, `0`, `[]`, `{}`, `""`) from a function whose name
  says it was checking, and `except: pass` around a check, outside a loop. AST-based, not regex.
  `strict=True` makes it refuse unparseable text instead of staying quiet, because the lenient
  default is itself the pattern this gate hunts.
- `hooks.gate_invariant(..., suffixes=(".py",))`, so a source gate only sees files it can read.
- `examples/source_gates.py` and a test that runs it as a subprocess.
- Both source gates now honour one exemption marker, `# noscope:` or `# agentattest:`, with a
  written reason on the line. Each uses it on its own fixtures and deliberate degradations, which
  is the honest way to be exempt from your own rule.

### A rule that was written and then deleted, which is the part worth reading
A third rule flagged a handler that printed a skip word and carried on -- the shape usually
described as *"prints SKIPPED and lets the build pass"*. Swept over 466 files of a real production
system it produced **40 of 45 hits**, and every one read by eye was a logged loop-item skip, or a
handler that recorded the failure into a list of failures.

The flaw was in the idea rather than the tuning: a handler that announces a skip **is not silent**,
and what makes that pattern a bug is the exit code afterwards, which rule 1 already covers.
Narrowing it further would have been tuning against a corpus instead of reasoning about the
pattern, so it was removed rather than adjusted.

Two other false alarms found the same way and fixed rather than tolerated:
- `scandir` matched `scan`, so every `os.scandir()` in a `try` looked like a swallowed check.
  Both ends of the word are anchored now.
- `_git_busy()` returning True on error means *"assume busy, back off"*, and `_win_alive()` means
  *"assume alive, do not steal the lane"*. Both are the CONSERVATIVE answer, the opposite of
  passing. Rule 1 therefore keys on the function NAME -- what the returned value means -- and never
  on what the `try` body happened to call.

Measured flag rate: **0 of the 26 Python files here, and 5 of 466 files (1.1%) of a real production
system**, with all five read by eye before the gate was wired in. It started at 38%.

### Verified rather than assumed
155 tests before, **185 after**. Eight deliberate breaks, and the first run **MISSED three of
them** -- the re-raise guard, the inside-a-loop condition, and the suffix filter all had tests that
looked correct and tested nothing:

- the re-raise fixture was a handler whose whole body was `raise`, which no rule would have flagged
  anyway;
- the loop fixture used `print`, not `except: pass`;
- the suffix fixture used `# just prose`, which is a **valid Python comment**, so it parsed cleanly
  and passed whether the filter worked or not.

All three were rewritten and all eight breaks are now caught (1, 29, 1, 1, 1, 2, 3 and 1 failures),
returning to 185 passed on restore.

## [0.6.0]

`"22 nodes, 0 broken"` reads as *the system is healthy* and means *the 22 I chose are healthy*.
This release makes the denominator structural instead of something you remember to mention.

### Added
- `Coverage`, `CoverageError`, `Entry`, `Diff`. The population comes from a **callable** and a
  list is refused, so it is re-established every run. Everything discovered is either examined or
  skipped with a measured reason; anything else is UNACCOUNTED and exits 2. Reconciliation
  (examined + skipped + unaccounted == discovered) is asserted and printed, and every report
  states the fraction. `save()` / `diff()` report NEW, GONE and GREW.
- `gates.TypedScope`, the static half: source that decides its own population from a hardcoded
  list of paths. Fires on two shapes only — two or more absolute paths on one line, or one on a
  line that names a scope. A single path assigned to a singular name is correct and is left alone.
  `# noscope: <reason>` exempts a line, which this gate's own must-fail fixtures use.
- `hooks.gate_invariant()`, which turns any `Gate` into a pre-tool-use invariant that inspects
  what is about to be **written**. Without it a `Gate` could not reach `pre_tool_use_hook` at all
  without a hand-written shim, which was a real gap found by writing the test for it.
- `examples/coverage_ledger.py`, and a test that runs it as a subprocess.

### Decisions worth stating
- **An exclusion with no measurement is UNKNOWN, not a pass.** "It's a cache" is a guess and
  "606 files" is a finding; from the outside the two look identical. `measured=0` is a
  measurement, omitting it is not.
- **The denominator is fixed for a run.** A population that grows halfway through cannot make a
  report internally inconsistent; `population(refresh=True)` picks up the change deliberately.
- **An empty population raises.** "0 of 0 examined" reads as a clean result and proves nothing.
- **Diffing against a baseline that does not exist raises.** No baseline is not the same as
  nothing having changed.
- **`gate_invariant` fails OPEN** when a write carries no inspectable content, because a pre-write
  hook that blocks everything it cannot parse gets removed within the day. `strict=True` refuses
  instead, for people who control the payload shape.
- `TypedScope` is deliberately narrow. An earlier version of this idea also matched `ROOT` and
  flagged 94 files whose only content was one correct constant. A gate that cries wolf gets
  switched off, which is worse than not having it.

### Verified rather than assumed
103 tests before, **155 after**. `TypedScope` was run over every Python file in the repo before
being wired in: 22 files read, 0 false alarms, and it is clean over the library's own source
(a test now asserts that across every module, with the count). Each new rule was then removed on
purpose and the suite went red every time.

The version-agreement test added in 0.5.0 immediately earned its keep: `__init__.py` was bumped to
0.6.0 while `pyproject.toml` still said 0.5.0, and the suite caught it rather than a user finding
a wheel whose metadata disagreed with its code.

## [0.5.0]

Everything before this asked whether a claim has evidence **now**. This release asks the question
underneath it: the evidence you cited has since changed, so is the claim still true?

### Added
- `ClaimBasis`, `Claim`, `Evidence`, `Status`, `BasisError`, and the `python -m agentattest.basis`
  command. Record what a completion claim was measured against; `recheck()` reopens it when the
  evidence moves. `REOPENED` means *unverified*, never *false*.
- A `scope` callable, discovered on every run rather than written down. A source appearing next
  month reopens every claim recorded before it existed, with nobody having to remember that a new
  place to look changes old answers.
- `ClaimBasis.as_check()`, so claim staleness is one more check inside an existing `Harness`.
- `examples/claim_basis.py`, and a test that runs it as a subprocess the way a reader would.
- `tests/test_scaffold.py` now asserts the installed package metadata agrees with `__version__`.
  A wheel whose metadata disagrees with the code installs a lie; this caught the stale editable
  install during development, before the wheel was ever built.

### Decisions worth stating, because each is a way of quietly reporting success
- **Fingerprints are content, never timestamps.** A checkout rewrites files without changing them,
  and a checker that reopens every claim after a checkout is switched off within a week.
- **Evidence vanishing reopens a claim; a scope entry vanishing does not.** Somewhere you no
  longer look cannot hold evidence the claim missed.
- **Recording a claim against a file that does not exist raises** rather than storing it. A stored
  claim with absent evidence can never be re-verified.
- **An empty store exits 2, not 0.** Nothing being watched looks identical to nothing having
  expired.
- **Evidence that cannot be judged reports UNKNOWN**, matching `Harness`. Non-file evidence with
  no current value supplied never counts as holding.
- **A corrupt store raises** rather than starting from empty, which would report every claim as
  holding.
- The claim verdicts (`HOLDS` / `REOPENED` / `UNKNOWN` / `RETIRED`) stay in `agentattest.basis`
  and are deliberately **not** re-exported at the top level, where `UNKNOWN` already means the
  `Harness` display verdict. A test asserts they have not silently collided.

### Verified rather than assumed
64 tests before, **103 after**. Each of the five rules above was then removed on purpose and the
suite went red every time — 11, 4, 3, 4 and 3 failures respectively — and returned to 103 passed
when restored. A suite that is green before and after a change has not tested the change.

## [0.4.0]

Everything before this released and tested only from the source tree. This release is about
making sure the thing people actually install works, which is a different question.

### Added
- `py.typed`, so downstream type checkers see the annotations. Without it every `mypy` and
  `pyright` user silently gets nothing from a fully annotated package.
- `python -m agentattest` as an alias for `python -m agentattest.demo`.
- A CI job that builds the wheel, installs it into a clean virtual environment, and runs the
  suite from a directory where the source tree is not importable. The existing jobs all tested
  the repo, which cannot catch a packaging bug.
- `CONTRIBUTING.md` and `SECURITY.md`.

### Changed
- Minimum Python lowered from 3.11 to 3.10. Nothing in the codebase required 3.11; the floor was
  arbitrary and excluded users for no reason.

### Fixed
- Nothing. The `py.typed` entry above was a genuinely missing file, not a broken config.

  A first draft of this changelog claimed the file also needed declaring in the build config or it
  would not ship. That was asserted without testing and it is **false**: hatchling includes
  `py.typed` automatically because it lives inside the package directory. Verified by removing the
  declaration, rebuilding, and confirming the wheel still contained it. The declaration was dead
  config and has been removed. CI asserts the file is present in the *installed* package, which is
  the check that actually protects this.

## [0.3.0]

### Added
- `agentattest.demo`, a runnable demonstration. The README transcript is copied from a real run.
- Tests asserting the demo actually refuses and actually allows, so it cannot decay into prose
  describing a refusal it no longer performs.

## [0.2.0]

### Added
- `gates.UnbackedClaims`: flags hard completion claims with no evidence within a configurable
  window. Hedged language passes on purpose.
- `hooks.stop_hook` and `hooks.pre_tool_use_hook`. Malformed input fails open, because a hook
  that wedges every turn gets deleted and then protects nothing.
- `Harness`: checks that assert against live state. `None` reports UNKNOWN and exits 2, never 0.
- `Harness.selftest()`, proving the three verdicts stay distinguishable.

### Fixed
- The evidence pattern matched `PASS` case-insensitively, so the word "pass" inside
  *"All tests pass"* cleared its own claim and every claim containing the word was silently
  approved. Now a separate case-sensitive pattern, with a regression test.
- `selftest_cases()` asserted multi-line fixtures against a `window=0` gate, a guarantee that
  configuration never made. Cases now match the gate's own window.

Both were caught by the mandatory must-fail case before either shipped.

## [0.1.0]

### Added
- `Gate`, `Case`, `Finding`, `SelftestError`. `selftest_cases()` is abstract and must include a
  case the gate is required to flag, so a gate that has never been made to fail on purpose cannot
  return a clean result through `check()`.
