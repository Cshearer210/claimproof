# Examples

Five files, each runnable on its own. Start with whichever matches what you want.

```bash
pip install agentattest

python stop_hook.py       # paste JSON on stdin, see a turn refused
python custom_gate.py     # write your own gate, and watch a broken one get rejected
python live_checks.py     # checks that look at your actual machine
python claim_basis.py     # watch a claim that was true go stale on its own
python coverage_ledger.py # the same audit reported two ways, one of them honest
```

## stop_hook.py

The one most people want. A complete hook that refuses an agent's turn when it claims work is
finished without showing anything.

Try it with no agent involved:

```bash
$ echo '{"text": "I fixed it. All tests pass."}' | python stop_hook.py ; echo "exit=$?"
Turn refused: completion claim(s) with no evidence in the same turn.
  x line 1: completion claim 'fixed' with no nearby evidence  (I fixed it. All tests pass.)
Show the proof (command output, exit code, test result, or file and snippet), or
soften the claim. A dry run proves wiring, not correctness.
exit=2

$ printf '{"text": "I fixed it.\n56 passed in 0.14s"}' | python stop_hook.py ; echo "exit=$?"
exit=0
```

To wire it into Claude Code, add this to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {"hooks": [{"type": "command", "command": "python /full/path/to/stop_hook.py"}]}
    ]
  }
}
```

For any other runtime, call `stop_hook(payload, gates)` yourself. It takes a dict and returns
`(exit_code, message)`, so adapting it is a few lines rather than a port.

**It fails open on malformed input.** Junk on stdin exits 0 and allows the turn. A hook that
crashes the agent on every turn gets deleted within the hour, and a deleted hook protects nothing.

## custom_gate.py

How to write your own, and more usefully, what a broken one looks like.

It defines two gates. The first catches TODOs left in output. The second is the dangerous shape:
it has cases, it has an `inspect()`, and it reads fine in review. The bug is `startswith` where it
should be `in`, so it catches a TODO at the start of a line and misses one in a trailing comment,
which is where they always live. In practice it approves everything.

```
looks-fine-is-not: expected to flag case [bad: pass  # TODO wire this up] but it passed

Note what happened there. inspect() on its own returns:
[]
which looks like a clean result. check() is what refuses it.
```

That is the argument for the whole library in one screen. `inspect()` returns an empty list and
looks like a pass. `check()` runs the gate's own must-fail case first and refuses to hand you a
clean result from a gate that just failed to catch something it declared it would catch.

## live_checks.py

Checks that look at the world rather than at code. Run it on two different machines and you should
get two different answers, which is the point.

```
  ok     There is room left on the disk
         51% free (241 GB of 476 GB)
  ??     A GPU is available for local inference
         nvidia-smi not on PATH, so this cannot be determined here

3 holding, 0 REGRESSED, 2 unknown
UNKNOWN is not a pass. It means the check could not tell.
exit 2
```

Two checks report UNKNOWN deliberately. Neither is a failure and neither is a pass, and the exit
code is 2 rather than 0 because there is something we wanted to know and do not.

That distinction is the one worth taking away. Returning `False` for "no GPU driver installed"
would be a lie. Returning `True` would be worse.

## claim_basis.py

The one that took the longest to see. Everything else here asks whether a claim has evidence
*now*. This asks whether the evidence a claim was closed on is still the evidence it was closed
on.

It builds a throwaway project in a temp directory, closes "auth refactor done" against two real
files, and then does two entirely ordinary things.

```
Nothing has moved yet
---------------------
HOLDS     auth-refactor
          same 2 piece(s) of evidence as when it was closed

Someone edited src/auth.py three weeks later
--------------------------------------------
REOPENED  auth-refactor
          closed 2026-08-06T17:11:49Z on "auth refactor done", but 1 of 2 piece(s) of
          evidence changed since (src/auth.py), so it is UNVERIFIED until re-measured

The project gained a directory the claim never looked at
--------------------------------------------------------
REOPENED  auth-refactor
          closed 2026-08-06T17:11:49Z on "auth refactor done", but 1 source(s) it never
          looked at now exist (migrations), so it is UNVERIFIED until re-measured
```

The second reopen is the interesting one. Nothing about the claim changed and no evidence moved.
The project simply gained somewhere to look that the claim never looked at, so the measurement
behind it is no longer complete. Nobody had to remember that a new source changes old answers,
because the scope is discovered on every run rather than written down.

Neither reopen means the claim was wrong. It was honestly true, measured against everything
visible at the time, and it went stale in silence. `REOPENED` means re-measure.

## coverage_ledger.py

One project, one trivial audit, run twice.

```
PASS 1 -- the report almost every tool prints

  4 files checked, 0 problems

Reads as: the project is fine.
Means   : the 2 directories I thought of are fine.

PASS 2 -- the same audit, with the denominator attached

COVERAGE  directories
  DISCOVERED  : 6
  EXAMINED    : 4   (2 ok, 1 BROKE, 1 unknown)
  SKIPPED     : 2   (every one with a reason; 0 with no measurement)
  UNACCOUNTED : 0

  4 of 6 directories examined.

BROKE:
  docs
         missing a header: index.md

OUT OF SCOPE -- measured anyway, so a wrong call is visible:
             240  .cache
                  why: vendor or regenerable, not written here
```

The first pass reported zero problems and exited 0. The second found a real one, in a directory
the first never opened, and exited 1. The defect is not hidden anywhere clever — it is simply
outside the list of places somebody wrote down once.

Two details worth stealing even if you never use this class. The exclusions carry their size, so
calling something a cache is a claim you can check rather than a label nobody questions. And
`scripts/` reports **could not tell** rather than passing: the audit only reads Python, and saying
so is the difference between four directories examined and three examined plus one guess.
