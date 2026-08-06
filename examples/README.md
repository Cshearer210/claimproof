# Examples

Three files, each runnable on its own. Start with whichever matches what you want.

```bash
pip install agentattest

python stop_hook.py    # paste JSON on stdin, see a turn refused
python custom_gate.py  # write your own gate, and watch a broken one get rejected
python live_checks.py  # checks that look at your actual machine
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
