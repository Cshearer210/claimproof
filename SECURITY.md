# Security

## Reporting

Open a [private security advisory](https://github.com/Cshearer210/agentattest/security/advisories/new)
rather than a public issue. Expect a reply within a week.

## What this library does and does not protect

Worth being direct, because the name could mislead.

**This is not a security boundary.** It checks whether a completion claim carries evidence
alongside it. A determined agent, or a person, can write text that satisfies the pattern without
having done the work. It raises the cost of an unproven claim; it does not make one impossible.

Treat it the way you treat a linter: useful because it catches the ordinary case reliably, not
because it cannot be worked around.

**The failure mode to actually worry about is a gate that stops working.** That is why
`selftest_cases()` is mandatory and why `check()` verifies before it inspects. If you are relying
on a gate in a pipeline, run its `verify()` on a schedule, not only at import.

## Deliberate design decisions that affect your threat model

- **`run_stop_hook` fails open on malformed input.** Bad JSON on stdin returns exit 0 and allows
  the turn. This is intentional: a hook that crashes an agent on every turn gets removed within
  the hour, and a removed hook protects nothing. If you need fail-closed, call `stop_hook`
  directly and decide for yourself.
- **A gate that raises during `verify()` raises out to you.** It is not swallowed and turned into
  a pass. A broken gate should stop the pipeline, not quietly wave everything through.
- **`Harness` checks that raise report UNKNOWN, not OK**, and UNKNOWN exits 2. A check that could
  not reach a verdict must never be indistinguishable from one that passed.

## Dependencies

None at runtime. The only development dependency is `pytest`. That is on purpose: the fewer things
in the tree, the less there is to audit.
