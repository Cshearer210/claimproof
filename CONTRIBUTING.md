# Contributing

Bug reports and pull requests are welcome. This is a small library with one opinion, so the
fastest way to get a change merged is to show it failing first.

## Setup

```bash
git clone https://github.com/Cshearer210/agentattest
cd agentattest
python -m pip install -e ".[dev]"
python -m pytest
```

You should see all tests pass. If you do not, that is a bug worth reporting on its own, since it
means the project does not build on a machine we have not tried.

## The one rule that is not negotiable

**Every gate must be able to fail, and you must prove it.**

`Gate.selftest_cases()` is abstract and must return at least one `Case` with
`expect_flagged=True`. This is enforced in `verify()`, not by review. A gate whose cases are all
happy-path is refused at construction with a `SelftestError`.

If you add a check to the library, the same standard applies to your tests: include a case that
demonstrates the check catching something, not just a case where nothing is wrong. A test that
has only ever passed tells you nothing about whether it can fail.

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
