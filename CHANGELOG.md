# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.12.0]

The library required a gate to prove it can fire. It never required a gate to prove it can stay
quiet, which is half a proof presented as a whole one.

An over-firing gate is the more expensive failure and the one nobody thinks to test for, because
it does not look broken. It looks like a discovery. It produces a pile of findings that were never
real, somebody spends a day on them, and when that is worked out the gate gets switched off — at
which point it catches nothing at all. That is strictly worse than never having written it.

### Changed — BREAKING
- `Gate.verify()` now refuses a gate whose selftest cases are **all** `expect_flagged=True`, the
  mirror of the existing refusal for all-`False`. Every gate must ship at least one **guard case**:
  something close enough to the bad case to be tempting, which the gate has to look at and leave
  alone.
- **Migration:** add one `Case(..., expect_flagged=False)` to any gate that has none. Pick a real
  near-miss, not an empty string — an empty case is free and proves nothing on its own. The three
  shipped gates already satisfied this (`UnbackedClaims` carries 9 guard cases of 15, `TypedScope`
  7 of 10, `SilentSkip` 11 of 15), so no in-tree gate changed behaviour.

### Added
- `test_a_gate_with_no_guard_case_is_refused` — the new rule fires.
- `test_one_guard_case_among_many_bad_ones_is_enough` — the guard case for the guard-case rule
  itself: four must-flag cases and exactly one guard still verifies, so the requirement cannot
  quietly become "most cases must be clean".
- `test_a_gate_that_flags_correct_work_is_caught_by_its_guard_case` — the over-firing gate, the
  failure mode this release exists for. 312 tests before, 315 after.

### Added — `tools/fresh_eyes.py`, the rehearsal nobody had run
`verify_wheel.py` proves the CODE works from a clean install by running the test suite outside the
source tree. Nothing proved the PRODUCT works, because nothing here had ever executed the README —
and documentation rots on its own schedule. A doc example can name a keyword argument renamed two
releases ago while every test passes.

Four acts, each a thing a first-time user does in their first ten minutes: install from the built
artifact into an empty environment; run what the README says; point the gates at somebody else's
code; run the one-command Claude Code integration in a throwaway project and make it actually
refuse a turn. It reuses `verify_wheel.clean_install()` rather than building a second, slightly
different environment beside it.

- **It found a real defect immediately.** The README's first example annotated `list[Finding]` and
  imported only `Gate, Case`, so anyone pasting it got `NameError: name 'Finding' is not defined`.
  Fixed. Folded into this release rather than minting 0.12.1, since 0.12.0 has not been published.
- **Every ```python block must now declare itself** — `<!-- fresh-eyes: run -->` or
  `<!-- fresh-eyes: illustration -->`, HTML comments so nothing renders differently. An unmarked
  block FAILS rather than being skipped, so a block added next month cannot fall out of coverage.
  4 of the 11 blocks execute; the rest are fragments that reference the reader's own code.
- **Aimed at the Python standard library** — 151 files nobody wrote to suit this project —
  `TypedScope` flags 0.7% and `SilentSkip` 1.3%, against a stated 25% over-firing ceiling. The hits
  are real: a hardcoded temp-directory list in `tempfile.py`, and `except: pass` around a check in
  `platform.py` and `webbrowser.py`.
- Wired as its own CI job, so it runs on every change rather than when somebody remembers.

**The rehearsal was wrong twice before the library was.** Act 4 first reported that the headline
feature did not block an unbacked claim. It does. The fixture was a bare text turn with no tool
call, which `decide()` correctly ignores — a hook that nags small talk gets uninstalled. Rewritten
with a `tool_use` block, it still passed, because the fixture said *"I edited core.py and fixed the
parser"* and **a filename is evidence**: "a file and line" is one of the things the gate accepts.
Both are recorded in comments where the fixture is built. A probe that names something you have
just watched work is the probe being wrong.

### The part worth reading
The discipline was already in the library everywhere except the one place it governs somebody
else's code. Sweeping all four self-proof mechanisms: `Harness.selftest` asserts a clean run
returns 0 as well as catching the broken one; `Coverage.selftest` asserts *"the same 0 broken IS a
pass once the whole population is accounted for"*; `ClaimBasis.selftest` asserts *"rewriting the
identical bytes does NOT reopen"* and says why — a checker that fires on a touched-but-identical
file gets switched off. One of four had the hole, and it was `Gate.verify()`, the one every
external gate passes through.

Two fixtures declared only a bad case and were refused for the new reason rather than the reason
they were written to demonstrate: `demo.NeverFails` and the `Exploding` gate in the hostile-input
suite. Both now declare a guard case, so each is refused for its real defect again — returning
clean on everything, and raising from `inspect()`.

## [0.11.1]

### Fixed
- The publish workflow can be triggered manually. Re-running the failed 0.11.0 publish used the
  workflow **as it existed at the tag**, which predated the token support, so it took the trusted
  publishing branch again and failed identically. Without a manual trigger, correcting any
  publishing problem costs a whole new release and the version number becomes a log of
  infrastructure mistakes.

## [0.11.0]

First PyPI release, under the new name.

### Added
- `tests/test_hostile_input.py` — 252 to 311 tests. The suite proved the library did the right
  thing on inputs that make sense; a stranger's data is nothing like ours. This feeds every surface
  what it was not designed for: a 40 MB transcript, a 200,000-character line, a byte-order mark,
  CRLF, emoji, right-to-left text, payload fields of the wrong type, four threads on one ledger.
  The bar is absolute — nothing may raise an unexpected exception — because a gate that kills
  somebody's turn gets uninstalled, and wrong-but-alive beats dead.

### Fixed
Three real defects, all found on the first hostile run:
- `stop_hook` died on a non-string reply. Other runtimes send a number, a list of content blocks, a
  nested dict. `_as_text()` now reads anything text-shaped and treats the rest as no text rather
  than taking the turn down.
- The ledger corrupted under concurrent writes — and multi-agent tracking is its entire purpose. A
  plain write truncates then fills, so a reader hit an empty file. Now an `O_EXCL` lock file, a
  re-read INSIDE the lock, and an atomic rename.
- Windows-only: with the lock added, `os.replace` still raised `PermissionError`, because Windows
  refuses a rename while a reader holds the file.

## [0.10.0]

### Changed
- **Renamed to `claimproof`.** PyPI refuses a name a hyphen away from an existing project, and
  `agent-attest` — an unrelated agent evaluator, on PyPI since 2026-06-19 — got there first.
  `agentattest` was never published, so the cost of moving was only ours.
- `src/agentattest` ships as a compatibility layer: every public name forwards, and
  `agentattest.claude_code` stays RUNNABLE, because that exact command sits in real settings files.
  A rename that silently stops guarding somebody's turns is the failure this library exists to
  catch. `install()` upgrades a pre-rename hook entry in place instead of doubling it; `uninstall()`
  removes either spelling.
- The GitHub address 301s forever, so links already published still resolve.

## [0.9.0]

The most universal agent failure is not a wrong answer — it is request six of eight quietly never
happening. The measured case behind this: a capture layer had recorded 1,318 user requests verbatim
and not one had ever become a tracked item, so every completion check ran against an empty list and
passed.

### Added
- `ledger.Ledger` — asks recorded verbatim (a paraphrase is where the third request in a compound
  message goes to die), items closed only with evidence (bare claim-words like "done" are refused:
  a claim cannot be its own receipt), skips carrying their reason on the record, nothing
  auto-closing, state on disk so it survives the session that forgot. CLI for harnesses:
  `ask|split|done|skip|show|gate`.
- `ledger.NothingLeft` — a `Gate` that flags a claim of TOTAL completion while the ledger holds open
  items, naming them. Partial, negated and hedged claims pass; a true "all done" over a clear list
  passes. Its selftest runs against a FIXTURE ledger, never the live one — a clean live ledger must
  not excuse a detector that can no longer detect.

## [0.8.0]

### Added
- `claimproof.claude_code` — the one-command integration.
  `hooks.stop_hook` was the raw adapter and expected the reply text handed to it. Claude Code's Stop
  event does not carry the text; it carries a transcript path, and the reply has to be dug out of
  the last assistant message. This module is that missing half, with the wiring learned from a hook
  that had run in production for months rather than from documentation: the loop guard
  (`stop_hook_active`), gating only turns that did real work, blocking via the JSON decision form,
  and failing open on every error — while announcing the skip on stderr, never swallowing it, for
  exactly the reason `gates.SilentSkip` exists.
- `install` merges into `.claude/settings.json` without touching anyone else's hooks, twice adds one
  entry not two, `uninstall` removes exactly ours, and an unparseable settings file is refused
  loudly rather than replaced.

---

*0.8.0 through 0.11.1 were reconstructed on 2026-08-12 from the repository's own record and had been
missing since they shipped. Only 0.11.0 and 0.11.1 were ever tagged, so the mapping comes from the
`version` line in `pyproject.toml` at each commit — the one source that cannot disagree with what
was actually built: 0.8.0 `1202f84`, 0.9.0 `7b25159`, 0.10.0 `4172433`, 0.11.0 `69d29ac`, 0.11.1
`98cbda4`. Every entry above is drawn from those commits' own messages, not written from memory.*

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
- Both source gates now honour one exemption marker, `# noscope:` or `# claimproof:`, with a
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
- `ClaimBasis`, `Claim`, `Evidence`, `Status`, `BasisError`, and the `python -m claimproof.basis`
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
- The claim verdicts (`HOLDS` / `REOPENED` / `UNKNOWN` / `RETIRED`) stay in `claimproof.basis`
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
- `python -m claimproof` as an alias for `python -m claimproof.demo`.
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
- `claimproof.demo`, a runnable demonstration. The README transcript is copied from a real run.
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
