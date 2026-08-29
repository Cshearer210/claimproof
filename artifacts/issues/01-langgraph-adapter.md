**Labels to apply:** `good first issue`, `help wanted`

**Title:** Good first contribution: a stop-event adapter for LangGraph

---

**This is an invitation to contribute, not a defect report. Nothing here is broken.**

One file, one test file, and a worked example already in the repo to copy from. Scoped so
someone new to this project can read one adapter and write another in a sitting.

**What you will learn by doing it:** how an agent harness signals the end of a turn, why
you read a real payload instead of trusting the documentation for it, and how to write a
gate that fails safely rather than getting itself uninstalled.

### The task

`claimproof.claude_code` wires the claims gate into Claude Code in one command, and
`claimproof.crewai` does the same for CrewAI. Both are single self-contained adapters.
This one is LangGraph.

**Clone the shape from one of these two:**

- [`src/claimproof/claude_code.py`](../../src/claimproof/claude_code.py) - the simplest case, no optional dependency
- [`src/claimproof/crewai.py`](../../src/claimproof/crewai.py) - the case with a third-party framework and an extra

### What the adapter has to get right

1. **Field names from the real runtime, not its documentation.** Feed it a captured
   payload from an actual session. The docs for one hook event were once simply wrong,
   and the code built on them recorded nothing, silently.
2. **A loop guard.** When a block makes the agent revise and stop again, the second pass
   must not block forever.
3. **Only gate turns that did real work.** A hook that nags small talk gets uninstalled,
   and an uninstalled hook catches nothing.
4. **Fail open, out loud.** An adapter error allows the turn AND says so on stderr. An
   announced skip, never a silent one.
5. ****LangGraph has no single stop event.** A graph finishes when it reaches END or the stream is exhausted, so decide deliberately where the turn ends and say so in the docstring - that choice is the whole design.**

### The gate contract, from CONTRIBUTING.md and not negotiable

- `selftest_cases()` returns **at least one must-flag and one must-pass case**. A gate
  that has only ever been shown to fire is unproven in the other direction.
- **Over-firing is worse than under-firing.** A gate that flags correct work reads as a
  discovery, gets switched off, and then catches nothing at all.
- **No new runtime dependency on the core library.** LangGraph goes in an optional extra,
  exactly as `crewai` does in `pyproject.toml`.

### How to prove it

```
pip install -e '.[langgraph]'   # add the extra in pyproject.toml, pinned
python -m pytest -q          # the whole suite, not just your file
python tools/verify_wheel.py # proves it works from the INSTALLED package
```

Put both numbers in the pull request: the suite failing before your change if you are
fixing something, and passing after. `verify_wheel.py` matters more than it looks - it is
what catches an adapter that works in the repo and breaks in a clean install.

### Before you start

Comment here naming the runtime so two people do not build the same one, and ask anything
you are unsure about in the same comment. Questions are expected; that is what this issue
is for.

House rules for the PR are in [CONTRIBUTING.md](../../CONTRIBUTING.md).
