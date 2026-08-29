# bSabna: what to say, and what is actually worth offering back

**Every block below is a DRAFT for Chris to edit and send himself.** A bot-flavoured
first comment on somebody's contribution reads as spam and cannot be taken back.

## What they actually did, so the thanks can be specific

Three separate things, and the second is the one most people would have missed:

1. Built the CrewAI adapter from the walkthrough in issue #2. 1,060 lines added, 0 removed.
2. **Found a silent-failure trap by reading CrewAI's source instead of its documentation.**
   CrewAI executes a private `_guardrail` attribute, populated from the public `guardrail`
   field by a validator that runs only at construction. Assigning it afterwards leaves the
   gate configured and never called, while every test that invokes the public field directly
   still passes.
3. Fixed a real defect in claimproof's own suite: `_shipped_gates()` imported every submodule
   unconditionally, so a clean install without the extra crashed on discovery.

They also made two design choices worth naming, because naming them is what proves the
thanks was read rather than generated: they used CrewAI's own `guardrail_max_retries`
instead of inventing a second retry loop, and they counted real tool calls through
`crewai_event_bus` rather than inferring "did work" from the output text.

---

## DRAFT 1: the thank-you, to paste on the PR or issue #2

**CUT DOWN 2026-08-29 by Chris: "way too long and makes me look bad". He was right on
both, and the second mattered more. Three lines had him telling a stranger, publicly
and permanently on his own project, that he would have made mistakes the contributor
avoided -- and one of them published a defect in his own test suite, which
never-post-about-our-own-bugs.md bans outright. A thank-you lands by naming what THEY
did precisely. It never needs him to be smaller so they can be bigger.**
> Merged, thank you.
>
> Two calls worth naming: using `guardrail_max_retries` rather than adding a second
> retry loop in the adapter, and counting tool calls off `crewai_event_bus` instead of
> inferring work from the output. Both are right.
>
> The `_guardrail` find is the valuable part. A guardrail that is set, visible on the
> object, and never executed while every test on the public field passes, is exactly
> the class this library exists to catch. Reading CrewAI's source rather than its docs
> is what found it.
>
> Credited in the README and the changelog.

**Check before sending:** does it name a concrete choice they made? Yes, three of them.

---

## DRAFT 2: the follow-up, offering help on THEIR work

**Send this separately and later, not stapled to the thank-you.** The point is that it asks
them for nothing.

> Unrelated to this repo, and ignore it if it is not useful. I had a look at
> Healthcare-multiagent-ai because the orchestrator/agent split is close to something I
> work on, and two things stood out that are cheap to fix and would matter to anyone
> cloning it:
>
> There is no LICENSE file, so strictly nobody can reuse it. GitHub will add one from a
> template in about thirty seconds and it is the single highest-value file in a public repo.
>
> `requirements.txt` is unpinned - `langchain`, `chromadb`, `sentence-transformers` with no
> versions. Those move fast enough that the repo will break on somebody's machine at some
> point and there will be no way to tell what changed. `pip freeze` on your working
> environment would pin it.
>
> Happy to open either as a PR if you would rather not, or leave it alone entirely.

---

## DRAFT 3: an issue for their repo, if he prefers an issue to a comment

> **Title:** No LICENSE file, so the project cannot legally be reused
>
> Cloning this to read the orchestrator/agent split and noticed there is no LICENSE.
>
> Without one, default copyright applies and nobody can legally copy, modify or run it,
> however public it is. For a portfolio repo that is worth fixing, because the people most
> likely to look at it are the people most likely to care.
>
> GitHub adds one from a template through Add file, Create new file, typing LICENSE. MIT is
> the usual choice for this kind of project and it is what claimproof uses.

---

## The small PR: NOT PROPOSED, and the reason matters

The brief allows a PR under 30 lines **only if something was actually reproduced**. Nothing
was. The repo was cloned and read, but installing it would mean pulling langchain, chromadb
and sentence-transformers unpinned, and a failure there would be my environment rather than
their bug.

**Reporting a failure I have not reproduced would be exactly the thing this whole project
refuses.** So: no PR. The two findings above are real, checkable by reading, and enough.

A pinning PR would also be presumptuous - the correct pins come from THEIR working
environment, not from a guess made on somebody else's machine.

## What he should star and follow by hand

- Follow **[@bSabna](https://github.com/bSabna)**.
- Star **Healthcare-multiagent-ai** only. It is the one he would plausibly clone: 11 Python
  files, a real orchestrator/agent/RAG split, a `governance_logger.py` that is adjacent to
  his own subject.
- **Not the others.** Starring all five in one sitting reads as exactly what it would be.
