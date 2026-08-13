# claimproof

[![CI](https://github.com/Cshearer210/claimproof/actions/workflows/ci.yml/badge.svg)](https://github.com/Cshearer210/claimproof/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/claimproof.svg)](https://pypi.org/project/claimproof/)
[![Python](https://img.shields.io/pypi/pyversions/claimproof.svg)](https://pypi.org/project/claimproof/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**claimproof stops an AI coding agent from ending its turn saying "done" until it shows proof a
machine can check.**

Agents report work as finished when it isn't — not by lying, but because a fluent summary and a
correct one feel identical from the inside, and nothing in the loop is checking. This runs at the
runtime layer, before the turn can end.

```bash
pip install claimproof
python -m claimproof.demo
```

![An unbacked claim is refused; the same claim with the test result attached is allowed; honest uncertainty is left alone](assets/demo.svg)

*The first four acts of `python -m claimproof.demo`, drawn from the demo's real output.
`tools/render_demo_svg.py` regenerates this image from a live run and refuses to render if the
output drifts — the same standard the library holds everyone else to.*

> **Renamed from `agentattest` (2026-08-07).** PyPI refuses names a hyphen away from an existing
> project, and `agent-attest` — an unrelated agent evaluator — got there first. The old GitHub
> address redirects, `import agentattest` still works via a compatibility layer, and a Claude Code
> hook installed under the old name is upgraded in place rather than doubled. Nothing you already
> wired up breaks.

## The number this exists for

**18,008 real agent runs ended with a confident claim of success. 12,578 of them had not fixed
anything** — 69.8%, measured against the maintainers' own test suites across 73,269 completed
runs. And claims carrying no evidence failed 83.0% of the time against 69.2% for claims that
showed something, so an agent that shows its work is measurably more likely to be right.

Measured with the gate below, unmodified, over a public CC-BY dataset. Method, limits and the
script that reproduces it: **[FINDINGS.md](FINDINGS.md)**.

Hedged language passes on purpose. A claim that admits its own uncertainty is the honest case,
and a gate that punishes honesty teaches agents to be vague instead of accurate.

## A gate is unproven in BOTH directions until you prove it

Most checks are written, pass on their first run, and are never once fed a case they were
supposed to catch. Nobody finds out they are broken until the thing they guarded against happens.

The mirror of that is the failure nobody thinks to check, and it is the more expensive one. A gate
that flags correct work does not look broken — it looks like a discovery. It generates a pile of
findings that were never real, somebody eventually switches it off, and from then on it catches
nothing at all.

So `selftest_cases()` is abstract and **must include both**: at least one case the gate is
required to flag, and at least one **guard case** — something close enough to be tempting that
the gate has to look at and leave alone. A gate that can demonstrate only one of the two is
refused at construction, not at review time.

<!-- fresh-eyes: run -->
```python
from claimproof import Case, Finding, Gate

class UnbackedClaims(Gate):
    def inspect(self, text: str) -> list[Finding]:
        ...

    def selftest_cases(self) -> list[Case]:          # required
        return [Case(text="It works.",          expect_flagged=True),    # must catch
                Case(text="It works. exit=0",   expect_flagged=False)]   # must leave alone
```

Pick guard cases that are genuinely tempting. `TypedScope` ships seven of its ten cases as guards,
including a commented-out line, a path inside a docstring, and a single project directory that is
correct — every one of them a shape a careless version of the check would flag.

`gate.check(text)` verifies before it inspects, so a clean result can never come out of an
unproven gate:

<!-- fresh-eyes: illustration -->
```python
>>> AlwaysPasses().inspect("this is bad")   # the trap: looks fine
[]
>>> AlwaysPasses().check("this is bad")     # the guard
SelftestError: expected to flag case [bad: this is bad] but it passed
```

This is not theoretical. It caught two real bugs in this library before either shipped:

1. The evidence pattern matched `PASS` case-insensitively, so the word "pass" inside
   *"All tests pass"* cleared its own claim. Every claim containing the word was silently
   approved. The mandatory must-fail case caught it on the first run.
2. `selftest_cases()` asserted multi-line fixtures against a `window=0` gate, a guarantee that
   configuration never made.

## Isn't this what an eval framework does?

No, and the difference is the whole point.

| | Eval frameworks (DeepEval, promptfoo) | claimproof |
|---|---|---|
| **When** | after the run, on a transcript | during the run, before the turn can end |
| **What it produces** | a score you read later | a refusal the agent has to answer now |
| **Who judges** | usually another model | the text itself: an exit code, a test count, a file and line |
| **Cost per check** | a model call | none |

An eval tells you your agent was wrong last Tuesday. This refuses to let it be wrong now. They
compose fine — run evals on your prompts, and run this on the turn.

The same distinction separates it from verification tools that call a second model to grade the
first: those pay per check and inherit that model's judgement. This one asks a narrower question
that a regular expression can answer, which is why it can run on every turn for free.

## Wire it into Claude Code in one command

```bash
python -m claimproof.claude_code install          # this project
python -m claimproof.claude_code install --user   # every project
```

That is the whole setup. From the next turn on, the agent in that scope cannot end a turn on
"Fixed. All tests pass." with nothing attached — the turn is refused and the reason is handed
back to the agent, which revises the reply instead of guessing. Honest hedging still passes, and
conversational turns are never inspected: only turns that actually edited files or did real tool
work are held to the standard, because a hook that nags small talk gets uninstalled, and then it
catches nothing.

`install` merges into `.claude/settings.json` without touching anything else in it, running it
twice adds one entry not two, `uninstall` removes exactly that entry, and a settings file that
does not parse is refused loudly rather than replaced. Errors at runtime allow the turn *and say
so on stderr* — an announced skip, never a silent one, for exactly the reason `gates.SilentSkip`
exists.

[examples/claude_code_install.py](examples/claude_code_install.py) runs the whole journey in a
sandbox — install, a refused turn, the fix, uninstall — without touching your real settings.

## Wire it into any other runtime

A gate you have to remember to call is a suggestion. The same gate wired into the harness is a
rule, because the runtime calls it whether anyone remembers or not.

<!-- fresh-eyes: run -->
```python
from claimproof.gates import UnbackedClaims
from claimproof.hooks import run_stop_hook

raise SystemExit(run_stop_hook([UnbackedClaims()]))   # JSON on stdin, exit 2 blocks
```

There is a `pre_tool_use_hook` too, for refusing a write that would violate a declared invariant
before it lands rather than catching it in review.

Malformed input fails **open**. A hook that wedges every turn gets deleted within the hour, and a
deleted hook protects nothing.

## "All done" is a claim about a list. Keep the list.

The most universal agent failure is not a wrong answer -- it is request six of eight quietly
never happening. The early asks get done, one falls out of the context window, and the session
signs off "everything is finished" with nothing in the loop keeping the list. The measured case
this was built from: a capture layer had recorded 1,318 user requests verbatim, and not one had
ever become a tracked item, so every completion check ran against an empty list and passed.

<!-- fresh-eyes: run -->
```python
from claimproof.ledger import Ledger, NothingLeft

led = Ledger("ledger.json")               # on disk: it survives the session that forgot
led.ask("fix the parser bug and add a regression test")
led.split(1, "fix the parser bug", "add a regression test")

NothingLeft(led).check("All done.")
# -> claims everything is finished, but 2 item(s) are open -- 1a: fix the parser bug; ...

led.done("1a", "pytest: 57 passed, was 56")   # evidence required; "done" alone is refused
led.skip("1b", "agreed: the regression test ships with the next change")  # on the record
```

Closing an item takes evidence -- the ledger refuses bare claim-words like "done" or "fixed",
because a claim cannot be its own receipt. Skipping is allowed and honest: the reason goes on the
record instead of into the void. Partial claims ("done with the parser fix") pass; only a claim
of *total* completion is checked against the list, and a true "all done" over a clear list passes
untouched. There is a CLI for harnesses that drive it from outside:
`python -m claimproof.ledger ask|split|done|skip|show|gate`.

## Checks that look at the world, not the code

A test suite proves your code is internally correct. It cannot tell you the backup stopped
running, the hook got unwired, or the service died quietly. Code does not decay. Reality does.

<!-- fresh-eyes: run exit=1 -->
```python
from claimproof import Harness

h = Harness()

@h.check("backup", "The off-machine backup ran recently")
def _():
    return False, "last run 41 days ago"

@h.check("gpu", "The GPU is reachable")
def _():
    return None, "no driver on this host, cannot tell"    # UNKNOWN

raise SystemExit(h.run())
```

```
  BROKE  The off-machine backup ran recently
         last run 41 days ago
  ??     The GPU is reachable
         no driver on this host, cannot tell

1 holding, 1 REGRESSED, 1 unknown
UNKNOWN is not a pass. It means the check could not tell.
```

**A check returning `None` reports UNKNOWN and exits 2.** Absent-and-fine and present-and-fine
must never produce the same output, because that is exactly how a broken check goes unnoticed for
months. A check that raises is UNKNOWN too, never OK.

## The claim was true when you made it. Is it still?

Everything above asks whether a claim has evidence **now**. Nothing asks the question underneath
it: *the evidence you cited has since changed, so is the claim still true?*

You close "auth refactor done" pointing at two files. Three weeks later both have been rewritten,
the claim still reads as finished, and nothing anywhere reopened it. It was never a lie. It went
stale in silence, which is worse, because a lie has an author and this has none.

<!-- fresh-eyes: illustration -->
```python
from claimproof.basis import ClaimBasis

basis = ClaimBasis("claims.json")
basis.record("auth refactor done", evidence=["src/auth.py", "tests/test_auth.py"])

# ... three weeks of ordinary work later ...

raise SystemExit(basis.run())
```

```
REOPENED  auth-refactor-done
          closed 2026-08-06T17:11:49Z on "auth refactor done", but 1 of 2 piece(s)
          of evidence changed since (src/auth.py), so it is UNVERIFIED until re-measured

1 claim(s) checked: 0 holding, 1 REOPENED, 0 unknown
```

**REOPENED is not "false".** It is *unverified*: re-measure it. Re-measuring costs seconds. A false
"done" that nobody revisits costs a great deal more, and the fix for unknown is to go and look.

There is a second way an old claim rots, and it is the one nobody instruments. Give the basis a
`scope` — the *places you look*, as distinct from the evidence you cite — and it is discovered on
every run rather than written down:

<!-- fresh-eyes: illustration -->
```python
basis = ClaimBasis("claims.json", scope=lambda: [s.name for s in Path("sources").iterdir()])
basis.record("no open item is older than March", evidence=["report.json"])
```

Wire in a source next month and every claim recorded before it existed reopens **on its own**. The
measurement was honest; it was taken against two sources and there are now three. A hand-written
list of sources would have to be edited by the same person who would have had to remember — which
is the thing that already failed.

Evidence and scope are treated differently on purpose:

| | vanishes | appears |
|---|---|---|
| **evidence** (what you cited) | REOPENED — the proof cannot be re-read | n/a |
| **scope** (where you looked) | noted, **not** reopened | REOPENED — you never looked there |

Somewhere you no longer look cannot hold evidence the claim missed. Reopening on it would cry
wolf, and a checker that cries wolf gets switched off, which is how the one real alarm gets
ignored.

Three more rules it will not bend on, each of which is a way of quietly reporting success:

- **Fingerprints are content, never timestamps.** A checkout rewrites files without changing them.
- **Recording a claim against a file that does not exist raises.** Storing it would put a claim in
  the record that nothing can ever re-verify.
- **An empty store exits 2, not 0.** Nothing being watched looks identical to nothing having
  expired.

It drops into the live-state harness, so the whole thing is one exit code:

<!-- fresh-eyes: illustration -->
```python
h.check("claims", "Every closed claim still rests on the evidence it cited")(basis.as_check())
```

## The same question, asked of your data — `deadcanary`

Everything above holds a claim to evidence. Here is a claim nobody thinks to question, because it
arrives already looking like evidence:

> **All 20 data tests pass.**

A data test that has been green every morning for two years is green for one of two reasons: the
data is healthy, or **the test cannot fail.** Nobody can tell those apart by looking, the sentence
reads identically either way, and almost nobody checks. It is the same failure this whole library
is about, one layer down — a check that has never been made to fail, trusted because it is quiet.

`deadcanary` settles it the only way it can be settled: it corrupts the data on purpose, re-runs
the suite, and reports which tests never noticed. **Dead canaries** — green every morning,
protecting nothing.

**Measured on dbt-labs' own current jaffle-shop template: 6 of its 20 green tests cannot be made to
fail by any corruption in the catalogue.** Among them `unique_orders_order_id` and
`not_null_orders_order_id`, the two most common tests in dbt. Full numbers, limits, and the
commands that reproduce them: [packages/deadcanary/FINDINGS.md](packages/deadcanary/FINDINGS.md).

```bash
pip install claimproof[dbt]
python -m deadcanary path/to/dbt/project
```

It lives in this repo at [`packages/deadcanary`](packages/deadcanary), installs on its own as
`pip install deadcanary`, and joins here at exactly one seam:

<!-- fresh-eyes: illustration -->
```python
from deadcanary.gate import GreenTestsUnproven

gate = GreenTestsUnproven(project="warehouse/dbt")
gate.inspect("All 20 dbt tests pass. Data quality is covered.")
# -> these data tests have never been proved able to fail -- no deadcanary run
#    backs this. Green is also what a test that cannot fail looks like.
```

It is a `Gate` like any other here, so it has to prove itself in both directions before it is
allowed to refuse anything. Four of its six selftest cases are guards — a normal unit-test suite,
an honest hedge, a reported failure, and someone asking the question rather than claiming the
answer — because a gate that reaches into claims it has no business in gets switched off, and after
that it catches nothing at all.

### And the proof expires, which is the part neither half has alone

`deadcanary` answers *can these tests fail?* for the suite as it stood the day it ran. Add a test
tomorrow, wire in a new source next month, and that answer describes a suite that no longer exists.
Nothing anywhere would say so — so it is recorded as a claim, against the machinery two sections up:

<!-- fresh-eyes: illustration -->
```bash
python -m deadcanary warehouse/dbt --attest     # record what was proved
python -m deadcanary warehouse/dbt --recheck    # 0 holds - 1 measure again - 2 cannot tell
```

```
REOPENED  deadcanary:dbt
          closed 2026-08-13T18:44:02Z on "the data tests in dbt were proved able to
          fail (20 green, 0 dead)", but 1 of 2 piece(s) of evidence changed since
          (dbt:test-suite), so it is UNVERIFIED until re-measured
```

The fingerprint covers what the suite **tests** — every test, what kind it is, what it hangs off,
and every source — and deliberately ignores dbt's own run metadata. `manifest.json` carries a fresh
timestamp and invocation id on every single build, so fingerprinting the file would reopen the
claim after every run. That is a checker crying wolf, and this README already says what happens to
those.

## "22 nodes, 0 broken" is not a result

It reads as *the system is healthy*. It means *the 22 I chose are healthy*. Those are different
sentences, and nothing in that output tells you which one you are looking at.

The measured version: one tool discovered 685,507 files. Another written the same day walked its
own hand-typed list of places to look, opened 57,100, and that was reported as "every file." The
gap was 628,407 files and **nothing could notice**, because a scan of 4 roots prints the same
shape of output as a scan of 40.

<!-- fresh-eyes: illustration -->
```python
from claimproof import Coverage

cov = Coverage("nodes", discover=list_all_nodes)   # a callable, not a list

for node in cov.population():
    if node.startswith("legacy-"):
        cov.skip(node, "retired in 2024", measured=0)
        continue
    cov.examine(node, *health_of(node))

raise SystemExit(cov.run())
```

```
COVERAGE  nodes
  DISCOVERED  : 7
  EXAMINED    : 2   (2 ok, 0 BROKE, 0 unknown)
  SKIPPED     : 0   (every one with a reason; 0 with no measurement)
  UNACCOUNTED : 5

  2 of 7 nodes examined.
  5 were never looked at and never skipped, so nothing here is a clean bill of health.
```

**Exit 2, not 0.** Unexamined is not the same as fine, and the exit code refuses to let one read
as the other. Four rules make that structural rather than something you remember to mention:

- **The population is discovered, never typed.** `discover` must be a callable — passing a list is
  refused — so the population is re-established every run and something that appears next month is
  in scope without anyone remembering it.
- **No exclusion without a measurement.** *"it's a cache"* is a guess; *"606 files"* is a finding.
  A `skip()` with no `measured=` reports UNKNOWN. `measured=0` is a measurement; omitting it is not.
- **Reconcile, and print it.** examined + skipped + unaccounted == discovered, asserted every run.
- **Persist and diff.** `save()` and `diff()` report NEW, GONE and GREW, so a member that appears
  next month surfaces itself instead of waiting to be stumbled on.

The other half of the same problem is the code that decides what to look at, and that one is
catchable before it lands:

<!-- fresh-eyes: illustration -->
```python
from claimproof.gates import TypedScope
from claimproof.hooks import gate_invariant, pre_tool_use_hook

pre_tool_use_hook(payload, [gate_invariant(TypedScope())])
```

```
Tool call refused: it would violate a declared invariant.
  x typed-scope in scan.py: line 1: 2 absolute paths on one line is a hand-written
    population, not a discovered one  (roots = ["/srv/a", "/opt/b"])
```

`TypedScope` fires on exactly two shapes — two or more absolute paths on one line, or one on a
line that names a scope (`roots`, `scan_dirs`, `search_paths`). A single path assigned to a
singular name is correct and normal and is left alone, as are comments and docstrings. That
narrowness is the point: an earlier version of this idea matched `ROOT` as well and flagged 94
files whose only content was one correct constant. **A gate that cries wolf gets switched off,
which is worse than not having it.** An exemption is allowed with `# noscope: <reason>` written on
the line, so an exception is a visible decision rather than an oversight.

**The honest limit**, since the whole argument here is about not overclaiming: this stops a tool
*silently* narrowing its own scope and forces the fraction into every report. It cannot prove your
`discover` function is complete. Nothing can.

## The check that stopped running eight months ago

<!-- fresh-eyes: illustration -->
```python
try:
    result = verify_everything()
except Exception:
    print("SKIPPED: could not run the check")
return True
```

Nothing alarms. The build goes green. The output is identical to the output it produced when it
worked. `SilentSkip` reads source and flags this before it lands:

```
  x silent-skip in certs.py: line 5: an exception handler returns True from
    check_certificates(), so a failure is reported as success  (except -> return True)
```

Two shapes only, and both share one property — **nothing is recorded anywhere**, so the run's
output is the same as a run where the check passed:

1. An exception handler that **returns success** (`True`, `0`, `[]`, `{}`, `""`) from a function
   whose name says it was doing the checking.
2. **`except: pass`** wrapped around something that was doing the checking, outside a loop.

Re-raising is never flagged. Returning a failure or an UNKNOWN is never flagged. Nor is
`try/except: pass` around a cleanup or an optional import, nor anything inside a loop, where
skipping one item is ordinary.

**A third rule was written and then deleted, which is the part worth reading.** It flagged a
handler that printed a skip word and carried on — the shape usually described as *"prints SKIPPED
and lets the build pass"*. Over 466 files of a real production system it produced **40 of 45
hits**, and every one read by eye was a logged loop-item skip, or a handler that recorded the
failure into a list of failures. The flaw was in the idea rather than the tuning: a handler that
announces a skip **is not silent**, and what makes that pattern a bug is the exit code afterwards,
which rule 1 already covers. Narrowing it further would have been tuning against a corpus instead
of reasoning about the pattern.

Measured on the two surviving rules: **0 of the 26 Python files here, and 5 of 466 files (1.1%) of
a real production system** — with all five read by eye before the gate was wired in.

## Why this exists

A content quality gate in a production system defaulted to passing everything once its API budget
reached zero. Weeks of output shipped ungraded and nothing alarmed, because the failure looked
exactly like success.

Separately, a credential scanner in the same system had its search paths hardcoded to one
operating system. On the other machine it read zero files, printed `CLEAN`, and exited 0. It had
never once been made to fail on purpose, so nobody knew.

Both are the same bug: something that reports success while proving nothing. This library exists
to make that shape structurally difficult.

That is also why CI runs the full matrix on Linux **and** Windows. A single-OS matrix would not
have caught the second one.

## Install

```bash
pip install claimproof          # the library. Python 3.10+, no runtime dependencies
pip install claimproof[dbt]     # ...and deadcanary, for the data-test half
```

Two packages, one repo, one idea. `claimproof` holds a claim of success to evidence a machine can
check. [`deadcanary`](packages/deadcanary) asks the same question of a dbt test suite, by breaking
the data on purpose to find the tests that cannot fail. Either installs alone; together, "our data
tests are green" stops counting as evidence until something has proved those tests can go red.

## Examples you can copy

Six runnable files in [examples/](examples/):

- **[stop_hook.py](examples/stop_hook.py)** is a complete hook. Copy it, point your runtime at it,
  done. Includes the `settings.json` block for Claude Code and a one-line way to try it with no
  agent involved.
- **[custom_gate.py](examples/custom_gate.py)** shows how to write your own, and more usefully what
  a broken one looks like: a gate whose bug is `startswith` where it should be `in`, which passes
  review and approves everything.
- **[live_checks.py](examples/live_checks.py)** runs checks against your actual machine, including
  two that deliberately report UNKNOWN.
- **[claim_basis.py](examples/claim_basis.py)** builds a throwaway project, closes a claim against
  real files, then does the two ordinary things that make an old claim false and shows it reopen
  itself both times.
- **[coverage_ledger.py](examples/coverage_ledger.py)** runs the same trivial audit twice over one
  project. The first pass reports `0 problems` and exits 0. The second finds a real defect in a
  directory the first never opened.
- **[source_gates.py](examples/source_gates.py)** runs the two source gates through the pre-write
  hook: two writes refused, and a third carrying both innocent twins allowed through.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: if you report a case this gets wrong,
paste the exact string. It usually becomes a test fixture verbatim.

The one rule that is not negotiable is that a gate must be able to fail and you must prove it.
That applies to changes here as much as to gates you write with it.

## License

MIT. See [CHANGELOG.md](CHANGELOG.md) for what changed and [SECURITY.md](SECURITY.md) for what
this does and does not protect against.
