# Contributing

Bug reports and pull requests are welcome. This is a small library with one opinion, so the
fastest way to get a change merged is to show it failing first.

## Setup

```bash
git clone https://github.com/Cshearer210/claimproof
cd claimproof
python -m pip install -e ".[dev]"
python -m pytest
```

You should see all tests pass. If you do not, that is a bug worth reporting on its own, since it
means the project does not build on a machine we have not tried.

`python tools/verify_wheel.py` runs CI's installed-package job locally in about a minute — it
builds a wheel, installs it into a clean environment, and runs the suite against the installed
package. Run it before opening a PR; it has already caught a test that passed against the source
tree while finding zero files against the wheel.

### The second package

`packages/deadcanary` is a separate distribution living in this repo — the same idea pointed at a
dbt project's data tests instead of an agent's reply. It has its own dependencies and its own test
suite, so it is set up separately:

```bash
python -m pip install -e "./packages/deadcanary[dev]"
python -m pytest packages/deadcanary/tests
```

Touching only one package? Run only that package's tests. Touching the seam between them
(`packages/deadcanary/src/deadcanary/gate.py`) means running both, because the gate it contributes
has to satisfy this library's contract — one case it must catch, one it must leave alone — or it
cannot be constructed at all.

**Its README is executable.** `python packages/deadcanary/tools/readme_runs.py` types what that
README tells a stranger to type, and fails if it does not work. If you change the quickstart,
change nothing else until that passes.

## The one rule that is not negotiable

**Every gate must be able to fail AND to stay quiet, and you must prove both.**

`Gate.selftest_cases()` is abstract and must return at least one `Case` with
`expect_flagged=True` and at least one with `expect_flagged=False`. This is enforced in
`verify()`, not by review. A gate whose cases are all happy-path is refused at construction with a
`SelftestError`; so is a gate whose cases are all bad.

One direction only proves half. A gate with no bad case has never been made to fail on purpose. A
gate with no guard case has never been shown to leave correct work alone — and that is the failure
that costs more, because an over-firing gate reads as a discovery rather than a defect. It
manufactures findings that were never real, and once someone works that out it gets switched off,
which is strictly worse than never having written it.

A guard case is only worth something if it is tempting. `Case(text="", expect_flagged=False)` is
free and proves nothing on its own; the useful ones are the near-misses — the commented-out line,
the path inside a docstring, the correct single directory. Ship at least one that would catch a
careless version of your own check.

If you add a check to the library, the same standard applies to your tests: include a case that
demonstrates the check catching something, and one that demonstrates it staying silent.

## Before you touch the README

```bash
python tools/fresh_eyes.py
```

It installs the built package into an empty environment where the source tree is not importable,
then does what the README says — because nothing else here has ever executed the README, and a
documentation example can reference a keyword argument renamed two releases ago while every test
passes.

Every ```` ```python ```` block must carry a marker on the line above it, `<!-- fresh-eyes: run -->`
or `<!-- fresh-eyes: illustration -->` (add ` exit=1` to a `run` block whose point is a non-zero
exit). They are HTML comments, so they do not render. **An unmarked block fails the check rather
than being skipped** — same reason `Coverage` refuses to call an unexamined member a pass. A block
that only makes sense as a fragment of the one above it is an illustration; a block somebody could
paste into a file and run is a `run`.

It also points the source gates at the Python standard library, which nobody wrote to suit this
project, and fails if either describes more than a quarter of it. A gate that fires on ordinary
code is not a discovery.

The project holds itself to this. Before any behaviour change lands, we break the thing on purpose
and confirm the suite goes red:

```bash
# example from a real change
# 1. reintroduce the bug
# 2. python -m pytest   -> expect failures and exit 1
# 3. restore
# 4. python -m pytest   -> expect all passing and exit 0
```

Put that before/after in the pull request description. "Tests pass" is not evidence on its own;
tests passing both before and after a change means the change is untested.

## What makes a good bug report

The most useful reports name a case the library got wrong:

- text you expected to be flagged that was allowed, or
- text you expected to be allowed that was flagged

Paste the exact string. It usually becomes a `Case` in `selftest_cases()` verbatim, which means
your report turns directly into a regression test.

## Scope

This library checks whether a completion claim carries evidence. It deliberately does **not**
judge whether the underlying work was any good. Those are different problems, and mixing them
produces a gate that grades vibes. Pull requests that move toward quality scoring will probably be
declined, though an issue discussing it first is welcome.

Hedged language passing is intentional, not an oversight. *"This should work, but I have not run
it"* is the honest case. A gate that punishes honesty teaches agents to be vague rather than
accurate.

## What makes a good first contribution

Adapters are the friendliest surface. `claude_code.py` shows the shape — payload parsing learned
from a real runtime, a loop guard, gating only turns that did work, failing open but announcing
it. A clean adapter for another agent runtime's stop event, held to the same test discipline, is
genuinely useful. So are new evidence patterns for `UnbackedClaims` — test-runner or CI output
formats it does not recognize yet — with a must-flag and a must-pass case for each.

## Style

- No hard dependencies. The library ships with none and should stay that way.
- Python 3.10 or newer.
- Comments explain *why*, especially for anything that looks arbitrary. Several constants here
  are the way they are because of a specific bug; say which one.

## CI

Every push runs on Linux and Windows across Python 3.10 through 3.13, and separately builds a
wheel, installs it into a clean environment, and runs the tests against the **installed** package
rather than the source tree. That second job exists because a package can pass every test locally
and still be broken for anyone who installs it.
