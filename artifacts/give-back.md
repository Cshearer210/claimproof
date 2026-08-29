# What this project actually stands on, and what we owe them

Discovered from the real import graph and the declared dependencies, not from memory.
**Do not open issues on any of these.** This is a list for him to work through by hand,
slowly, when he has something real to say.

The core library has **no runtime dependencies**, which is deliberate and is itself the
biggest thing it owes upstream: nothing here is a burden on anyone's release schedule.
The debts below are from the development and the wider system.

| project | why we owe them | one small thing worth contributing |
|---|---|---|
| **pytest** | every gate's proof is a pytest run; 316 tests here and 85 in deadcanary | a docs example for asserting a check FAILS as intended. The docs cover asserting success far better than asserting a deliberate failure, which is this project's whole subject |
| **dbt-labs/jaffle_shop_duckdb** | deadcanary's headline finding is measured ON their template | offer the measurement back as an issue with the raw report attached, framed as "here is what a mutation pass finds", never as a defect report. Their template teaches the right shapes |
| **duckdb** | deadcanary runs its corruptions through it | a reproduction for any bug found while writing the corruption passes. They fix fast and reproductions are what they lack |
| **CrewAI** | now an adapter target, and their event bus made the tool-call counting possible | **the private `_guardrail` finding is a genuine documentation gap.** A docs PR saying assignment after construction does not take effect would save other people the same silent failure. This is the highest-value item here and it is bSabna's find, so it is theirs to file if they want it |
| **Textualize/rich** | used across the wider system's output | a terminal-width edge case reproduction if one is ever hit. Nothing invented |
| **tqdm** | used in the batch paths | nothing owed yet beyond a star, which is done |
| **anthropics/anthropic-sdk-python** | the metered paths route through it | nothing owed yet |

## Sponsors and money

**His call, not an agent's.** The two with the clearest claim on it are **pytest** (via the
Python Software Foundation / OpenCollective) and **duckdb**. Both are load-bearing and
neither is a large company's side project.

## The rule this list follows

A contribution is docs, a reproduction, or a test. **Never a rewrite, never a drive-by
refactor, and never a pull request opened on a large project for visibility.** That is
transparent from the outside and it costs more reputation than it buys.
