# GitHub settings: what to paste, and where

**All of this is Settings-UI work. Nothing here can be done from a terminal, and none of
it should be done by an agent.**

## Repo topics (Settings, or the gear beside About)

Current topics already include most of these. Confirm the full set is:

```
ai-agents  guardrails  evals  crewai  dbt  python  claude-code
agent-reliability  mutation-testing  data-quality  llm  testing
```

## Public description (one sentence, the About box)

> Agents claim work is done that isn't. This makes them prove it: evidence-gated turns,
> gates that must be shown to fail, and a ledger that catches "all done" lies.

That is close to what is there now. The one change worth making is dropping any clause
that reads as a feature list; the first sentence should be the problem, not the parts.

## Discussions tab

Settings, Features, tick Discussions. Worth it for one reason: issue #2 is currently doing
the job of a discussion thread, and an issue that stays open for conversation is
indistinguishable from an issue nobody finished.

## Profile README (Cshearer210/Cshearer210)

Five to eight lines. No business, no ranch, no private repos, no nored-ws-* anything.

```markdown
I build the reliability layer for agent systems: harnesses, gates and evals that fail
loudly instead of quietly.

- **[claimproof](https://github.com/Cshearer210/claimproof)** - an agent cannot end its turn
  claiming it finished unless it shows evidence a machine can check. Adapters for Claude Code
  and CrewAI.
- **[deadcanary](https://github.com/Cshearer210/claimproof/tree/main/packages/deadcanary)** -
  the same question asked of data: which of your green tests cannot be made to fail?

Before software, a decade running industrial process equipment. A gauge you have never seen
fail on purpose is not a measurement.
```

**Do not list the working repos.** They are private for good reasons and a profile that
links two finished things reads better than one listing thirty folders.
