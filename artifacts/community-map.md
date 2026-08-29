# What exists, what is missing, and where each change goes

Mapped 2026-08-28 from the repo on disk and the GitHub API, not from memory.

## What already exists

| | |
|---|---|
| remote | `https://github.com/Cshearer210/claimproof.git`, branch `main`, tree clean |
| the CrewAI adapter | `src/claimproof/crewai.py` 378 lines, `tests/test_crewai.py` 563, `examples/crewai_guardrail.py` 100 |
| PR #32 | **MERGED** 2026-08-29 by bSabna, squashed as `1fc4dfc` |
| issue #2 | **still OPEN**, labels `help wanted` and `good first issue` |
| core dependencies | **NONE**. `crewai==1.15.14` is an optional extra |
| version | 0.14.1, Keep a Changelog format |
| contributors | Cshearer210 54, slegarraga 2, bSabna 1 |
| tests | 316 in claimproof, 85 in deadcanary |

## What was missing, and is now written on this branch

| gap | where it went |
|---|---|
| no contributor credit anywhere | `README.md`, inside the existing Contributing section |
| no integrations overview | `README.md`, a new `## Integrations` table |
| the adapter in no version's changelog | `CHANGELOG.md`, a new `## [Unreleased]` |
| no follow-on work sliced for strangers | `artifacts/issues/*.md`, three of them |
| topics and profile text undecided | `artifacts/github-settings.md` |
| nothing recorded about upstream debts | `artifacts/give-back.md` |

## What is still missing and is HIS to do

1. **Issue #2 is open although it is finished.** A second stranger could start the same
   adapter tonight. This is the most time-sensitive item in the whole plan.
2. **Issue #2 also still says `agentattest.claude_code`** - the old package name, from
   before the rename. `fresh_eyes.py` confirms the README no longer does. A stranger
   following that issue would `pip install` something that is not the project.
3. Topics, description, Discussions tab, profile README: Settings UI only.
4. A tagged release naming the adapter, before any community post.

## bSabna: which repo is the reciprocity target

| repo | pushed | python files | tests | license | deps |
|---|---|---|---|---|---|
| **Healthcare-multiagent-ai** | 2026-07-23 | 11 | no | **none** | unpinned |
| Agentic-AI-project | 2026-07-22 | - | no | **none** | **none at all** |
| MRNet-MLOps | 2026-07-12 | - | yes | **none** | declared |

**Target: Healthcare-multiagent-ai.** Most recently pushed of the agent repos, and the one
with a real orchestrator/agent/RAG structure. Full reasoning in `bsabna-reciprocity.md`.
