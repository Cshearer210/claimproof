# agentattest

[![CI](https://github.com/Cshearer210/agentattest/actions/workflows/ci.yml/badge.svg)](https://github.com/Cshearer210/agentattest/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agentattest.svg)](https://pypi.org/project/agentattest/)
[![Python](https://img.shields.io/pypi/pyversions/agentattest.svg)](https://pypi.org/project/agentattest/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

AI coding agents routinely report work as finished when it isn't. Not by lying, but because a
fluent summary and a correct one feel identical from the inside, and nothing in the loop is
checking. `agentattest` makes an agent prove it, at the runtime layer, before its turn can end.

```bash
pip install agentattest
python -m agentattest.demo
```

```
1. The agent says it is done, and shows nothing.
--------------------------------------------------------------------
  | I fixed the parser bug. All tests pass.
--------------------------------------------------------------------
  -> REFUSED (exit 2)
     Turn refused: completion claim(s) with no evidence in the same turn.
       x line 1: completion claim 'fixed' with no nearby evidence
     Show the proof (command output, exit code, test result, or file and
     snippet), or soften the claim. A dry run proves wiring, not correctness.

2. Same claim, with the receipt attached.
--------------------------------------------------------------------
  | I fixed the parser bug.
  | ```
  | 56 passed in 0.14s
  | ```
  | All tests pass.
--------------------------------------------------------------------
  -> allowed (exit 0)

3. Honest uncertainty is left alone.
--------------------------------------------------------------------
  | This should fix the parser bug, but I have not run the suite yet.
--------------------------------------------------------------------
  -> allowed (exit 0)
```

Hedged language passes on purpose. A claim that admits its own uncertainty is the honest case,
and a gate that punishes honesty teaches agents to be vague instead of accurate.

## A gate that has never failed proves nothing

Most checks are written, pass on their first run, and are never once fed a case they were
supposed to catch. Nobody finds out they are broken until the thing they guarded against happens.

So `selftest_cases()` is abstract and **must include a case the gate is required to flag**. A gate
that cannot demonstrate its own failure mode is refused at construction, not at review time.

```python
from agentattest import Gate, Case

class UnbackedClaims(Gate):
    def inspect(self, text: str) -> list[Finding]:
        ...

    def selftest_cases(self) -> list[Case]:          # required
        return [Case(text="It works.",          expect_flagged=True),
                Case(text="It works. exit=0",   expect_flagged=False)]
```

`gate.check(text)` verifies before it inspects, so a clean result can never come out of an
unproven gate:

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

## Wire it into the runtime

A gate you have to remember to call is a suggestion. The same gate wired into the harness is a
rule, because the runtime calls it whether anyone remembers or not.

```python
from agentattest.gates import UnbackedClaims
from agentattest.hooks import run_stop_hook

raise SystemExit(run_stop_hook([UnbackedClaims()]))   # JSON on stdin, exit 2 blocks
```

There is a `pre_tool_use_hook` too, for refusing a write that would violate a declared invariant
before it lands rather than catching it in review.

Malformed input fails **open**. A hook that wedges every turn gets deleted within the hour, and a
deleted hook protects nothing.

## Checks that look at the world, not the code

A test suite proves your code is internally correct. It cannot tell you the backup stopped
running, the hook got unwired, or the service died quietly. Code does not decay. Reality does.

```python
from agentattest import Harness

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

```python
from agentattest.basis import ClaimBasis

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

```python
h.check("claims", "Every closed claim still rests on the evidence it cited")(basis.as_check())
```

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
pip install agentattest
```

Python 3.10+. No runtime dependencies.

## Examples you can copy

Four runnable files in [examples/](examples/):

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: if you report a case this gets wrong,
paste the exact string. It usually becomes a test fixture verbatim.

The one rule that is not negotiable is that a gate must be able to fail and you must prove it.
That applies to changes here as much as to gates you write with it.

## License

MIT. See [CHANGELOG.md](CHANGELOG.md) for what changed and [SECURITY.md](SECURITY.md) for what
this does and does not protect against.
