# SEND CHECKLIST

**In order. Nothing above has been sent, posted, pushed or opened.**
Each line says exactly where it goes.

## 1. Do tonight, because it is costing something right now

- [ ] **Close issue #2, or edit it to say the CrewAI slot is taken.**
      Where: https://github.com/Cshearer210/claimproof/issues/2
      Why now: bSabna finished it and it still reads as available. A second stranger could
      start the same adapter tonight and lose a weekend.
      Suggested edit: keep it open as the walkthrough, add at the top - "CrewAI is done
      (#32, @bSabna). Still open for LangGraph, the OpenAI Agents SDK, AutoGen or whatever
      you run. Comment naming yours before you start."

- [ ] **Fix the old package name in issue #2.** It says `agentattest.claude_code`; the
      package is `claimproof`. Anyone following it installs the wrong thing.

## 2. The thank-you, while the merge is fresh

- [ ] **Read `artifacts/bsabna-reciprocity.md`, DRAFT 1. Edit until it sounds like you.**
      Where: https://github.com/Cshearer210/claimproof/pull/32
      Bar: does it name a concrete choice they made? The draft names three.

- [ ] **Follow @bSabna. Star Healthcare-multiagent-ai only.** By hand, one repo.

## 3. The branch, after you skim it

- [ ] **Read the diff on `community/reciprocity`.** Two files: README credit plus an
      Integrations table, and a CHANGELOG `[Unreleased]` section.
      `git diff main..community/reciprocity`
      Bar: does the Integrations table stay as short as the rest of the README?
- [ ] **Merge it yourself** if the credit lines read right. They name what each person
      actually did rather than thanking them as a group.

## 4. Settings UI, none of which a terminal can do

- [ ] Topics, description, Discussions tab. Text is in `artifacts/github-settings.md`.
- [ ] Profile README on Cshearer210/Cshearer210. Draft in the same file.
      **Keep every ranch, business and nored-ws folder off it.**

## 5. Decisions only you can make

- [ ] Offer bSabna the adapter file, or collaborator status? A relationship call.
- [ ] Do noredfarms and Cshearer210 stay separate identities publicly?
- [ ] Sponsors or thanks.dev on pytest and duckdb? See `artifacts/give-back.md`.

## 6. Only after a tagged release

- [ ] Tag a release naming the CrewAI adapter. A release is a promise about the package.
- [ ] Then, and only then: CrewAI Discord, Show HN, awesome-crewai.
      These have to be you, and they land badly if the adapter is not installable yet.

## 7. Later, and slowly

- [ ] The three issue drafts in `artifacts/issues/`. File them one at a time, not as a
      batch - three identical issues posted together reads as filler.
- [ ] `artifacts/give-back.md`, when you have something real to say to each project.

## Never, whoever offers

- force-push, rewriting merge commits, or squashing a contributor's PR out of history
- mass-starring or mass-following
- opening PRs on CrewAI core or other large projects for visibility
- making any nored-ws-* repo public so the profile looks busier
- asking bSabna to keep building the roadmap
