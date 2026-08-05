# agentattest

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

Python 3.11+. No runtime dependencies.

## License

MIT
