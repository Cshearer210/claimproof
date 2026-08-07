# When a coding agent says "the issue is fixed," it is wrong 7 times out of 10

**18,008 real agent runs ended with a confident claim of success. 12,578 of them had not
fixed anything.**

That is 69.8%, measured against ground truth — not a survey of how agents talk, and not a
judgement call. Every run in this dataset carries the verdict of the maintainers' own test
suite on the patch the agent produced, so "did it work" has an answer that nobody in this
measurement got to choose.

| | |
|---|---|
| Dataset | [`nebius/SWE-agent-trajectories`](https://huggingface.co/datasets/nebius/SWE-agent-trajectories) (CC-BY-4.0) |
| Runs read | 80,036 |
| Not counted | 6,767 killed by a timeout or context limit — they never got to make a claim |
| **Counted** | **73,269 runs the agent chose to end** |
| Measured with | `claimproof`'s own `UnbackedClaims` gate, unmodified |
| Reproduce | `python tools/measure_unbacked_claims.py` |

## What the numbers say

**Agents claim success about a quarter of the time.** 18,008 of 73,269 completed runs
(24.6%) closed with a hard claim — "the issue is fixed", "all tests pass", "the problem is
solved". The other 55,261 ended without claiming anything.

**Most of those claims were false.** 12,578 of 18,008 (69.8%) had not resolved the issue.

**A claim is weak evidence, not no evidence.** Runs that claimed success really did resolve
30.2% of the time; runs that stayed quiet resolved 14.4% of the time. So the claim more than
doubles your odds — and still leaves you wrong seven times in ten if you act on it. An agent's
confidence is a signal you can measure, and it is nowhere near a substitute for checking.

**Showing the work correlates with being right.** This is the part with a practical
consequence:

| | share of claims | actually failed |
|---|---|---|
| Claims **with** evidence nearby | 17,214 (95.6%) | **69.2%** |
| Claims **with no** evidence at all | 794 (4.4%) | **83.0%** |

A claim that carries no evidence is 13.8 points more likely to be wrong than one that does.
An agent typing "fixed" into a vacuum is measurably telling you less than an agent that ran
something first.

## What an unbacked claim that turned out to be wrong looks like

```
[Azure__azure-functions-python-worker-890]
  "Before submitting the changes, it would be good to test this change to ensure it..."

[Melevir__cognitive_complexity-15]
  "The code has been updated to handle `ast.BoolOp` nodes correctly. We should now..."

[asottile__pyupgrade-545]
  "Before submitting the changes, it would be a good idea to test the modified func..."
```

Read those again. Two of the three *say out loud* that the change ought to be tested, and
then submit without testing it. The agent is not lying and it is not confused about what
would be rigorous — it names the missing step and skips it anyway. That is the behaviour this
library exists to make impossible: not dishonesty, just nothing in the loop insisting.

## Method, stated so it can be argued with

- **One trajectory is one run.** Only runs the agent chose to end are counted (`exit_status`
  contains `submitted`). A run killed by a timeout never reached a closing statement, so
  including it would measure the harness rather than the agent.
- **The claim is read from the agent's closing words** — its final message plus the one
  before, the same window a human reviewer sees.
- **"Claims success" is deliberately strict.** A fixed list of hard phrases, and a hedge in
  the same sentence disqualifies it: "I think this fixes it" is not a claim of completion.
  Every judgement call throws claims away rather than counting doubtful ones, so 24.6% is a
  floor.
- **"Backed by evidence" is decided by the shipped gate**, unmodified, at its default
  two-line window. The patterns are in `src/claimproof/gates.py` and its must-fail cases ship
  with it.
- **The claim detector was proven in both directions** before any number was trusted: seven
  fixtures, including three that must NOT count as claims, zero disagreements.

## Limits, up front rather than in a footnote

1. **These are not frontier assistants.** The runs are Llama-family models on the SWE-agent
   scaffold, 2024-2025. Nothing here is a measurement of Claude Code, Cursor, or any current
   product, and anyone quoting it as one is misusing it.
2. **Ground truth is the maintainers' test suite.** A patch can be reasonable and still fail
   it, so some of the 12,578 "failures" are arguably harsh.
3. **The evidence detector saturates in this domain.** Coding transcripts are full of file
   paths, line numbers and command output, so 95.6% of claims land in the "backed" bucket —
   including many where the agent quoted code without ever running it. That makes the
   unbacked set small and the comparison conservative: 83% is what the gate finds when text
   contains *no* evidence-shaped signal at all. The real rate of unproven claims is higher
   than 4.4%, not lower.
4. **A gate that reads text can be fooled by text.** An agent describing a test run it never
   performed passes. This measures what was shown, not what was done.

## Why this was worth measuring

The argument for evidence gating has always been made from anecdote: everyone who has run an
agent has watched it announce victory over a broken build. Anecdote loses arguments to
"models are getting better."

The number is the argument. Seven out of ten confident completion claims were false, in a
dataset large enough that the pilot on one twelfth of it (66.8%) and the full run (69.8%)
agree within three points. And the runs that showed nothing failed measurably more often than
the runs that showed something — which is the whole thesis of this library, stated in data
rather than in a README.

---

*Every number here was produced by [`tools/measure_unbacked_claims.py`](tools/measure_unbacked_claims.py),
which downloads the dataset, runs the shipped gate over it, and prints the report above. It
refuses to report from a partial download. Run it yourself.*
