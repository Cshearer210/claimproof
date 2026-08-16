# MASTER PLAN — claimproof + deadcanary

**Written 2026-08-13 on Chris's instruction, after he said this had taken too long
to become downloadable.** This is the one list for this project. Anything not in
here is not planned; anything in here says plainly what state it is in.

**The goal, in his words: ready for anyone to download and use, and good enough to
put on his resume.**

---

## WHERE IT STANDS RIGHT NOW

| | |
|---|---|
| Repo | `Cshearer210/claimproof` — two packages, one repo |
| PyPI | `claimproof` **0.14.0** live · `deadcanary` **0.1.0** live |
| Tests | 316 claimproof + 77 deadcanary, from clean installs |
| CI | 17 jobs, two operating systems, four Python versions |
| Findings | three public dbt projects measured; two have their raw report committed |

**It installs and works today.** Every path verified from a clean environment:

```
pip install claimproof[dbt]   ->  claimproof + deadcanary
pip install deadcanary        ->  works alone
```

---

## TIER 1 — BLOCKS "READY FOR ANYONE TO DOWNLOAD"

**1.1 is done. 1.2 is the only Tier 1 item left, and it is the one that matters
most: nobody has watched a stranger use this on their own project.**

### 1.1 Cut release 0.14.1 / deadcanary 0.1.1  ·  **DONE 2026-08-13**

**Shipped and verified on the live pages:** both descriptions carry 0 dead
relative links, the hero image URL returns `<svg` rather than an HTML page, and a
fresh `pip install claimproof[dbt]` in a clean venv resolves claimproof 0.14.1 +
deadcanary 0.1.1 with the gate verifying its 6 cases.

**Why it blocks:** PyPI renders the description **shipped inside the release**, not
the one in the repo. Both pages currently show **18 links that go nowhere** and
claimproof's **hero image is broken** — has been since the project first shipped.
The repo is fixed; only a new release moves the pages.

The links return HTTP 200 and serve the byte-identical project page, so every
automated check passes while a human goes in circles. That is the whole reason it
survived this long.

- [x] Merge PR #26 — 17 checks green
- [x] `gh release create v0.14.1` — publish workflow: 4 jobs, all success
- [x] Fresh clean venv: claimproof 0.14.1 + deadcanary 0.1.1
- [x] Live pages: 0 dead links on both, hero image returns real SVG

**One thing to know for next time:** PyPI's JSON summary lagged for a few minutes
after upload and still reported the OLD version's description. Checking the
version-specific endpoint (`/pypi/<pkg>/<version>/json`) gives the truth
immediately. A check that reads only `info.description` will report a fixed page
as still broken.

### 1.2 A first-time user cannot currently succeed without dbt knowledge

**Not yet verified, and it is the real "ready for anyone" question.** Everything so
far proves the package *installs*. Nobody has watched a stranger with their own
dbt project try to use it.

- [ ] Run `deadcanary` against a dbt project **not** in the three already measured,
      following only the README, and write down every place it is confusing or
      fails
- [ ] The most likely failure: a project on Snowflake/BigQuery rather than DuckDB.
      **The tool is DuckDB-only and the README does not say so loudly enough.**
      That is a one-line fix and a large fraction of would-be users.
- [ ] Decide and state plainly at the top of the README: which projects this works
      on today, and which it does not

---

## TIER 2 — MAKES THE RESUME CLAIM STRONGER

### 2.1 Measure a production dbt suite
All three projects measured are demonstrations. `FINDINGS.md` says so, and it is
the first thing a sharp reviewer will ask about. One real suite — even one company's
open-source analytics repo — changes the finding from *"toy projects are thin"* to
*"this is what real coverage looks like"*.

### 2.2 `jaffle-shop-template` has no committed raw report
The other two do. It was measured before the `findings/` folder existed. Re-running
it needs an older dbt in its own environment plus a withdrawn dependency removed.

### 2.3 Parquet sources are declined, not corrupted
Recognised and reported, never silently skipped — so it is honest, not broken. But
a project whose raw data is parquet gets no measurement at all.

### 2.4 `--attest` cannot record a proof from a report already on disk
It re-runs the whole hunt. Fine on the demo, a real barrier on a project where a
run takes two hours. **The right fix is for the report to record the suite
fingerprint it measured**, so attesting from a report can refuse when the suite has
moved since.

---

## TIER 3 — POLISH, NOT BLOCKING

- **A screenshot or short recording of deadcanary running.** claimproof has its
  animated demo; deadcanary has a code block. The finding is visual and it is not
  being shown.
- **A CHANGELOG for deadcanary.** It has none; claimproof's covers both today.
- **Cross-links between the two PyPI pages.** deadcanary's page links to the repo
  but not to claimproof, and vice versa.

---

## THE PART THAT MUST NOT BE UNDONE

Five ways this tool can lie, every one found by real use, every one flattering:

1. **NO-OP** — a corruption that changed no rows is never a miss.
2. **UNDONE-BY-REBUILD** — dbt regenerates models, so a corruption aimed at one is
   wiped before any test runs. *The first version reported 20 of 20 tests dead for
   this reason and it read as a spectacular finding.*
3. **PARTIAL COVERAGE** — a run that did not corrupt every source names no dead
   canaries at all.
4. **SKIPPED BY DBT** — `hunt.py` runs `dbt run` then `dbt test` as **two separate
   calls on purpose**. Someone folded that into one `dbt build` and it made 2 of 4
   findings false. **Do not undo it.**
5. **NOTHING TO CORRUPT** — raises, CLI exits 2 (cannot tell), never 0.

And four more found on 2026-08-13, all of which made the tool refuse healthy
projects or overstate what it measured: the warehouse location was guessed instead
of read from the profile; a source location is written in three places and only one
was known; PyYAML was an accident rather than a dependency, so profile reading
silently did nothing where dbt was absent; and models were counted as tests,
inflating the headline while every verdict stayed correct.

Full detail: `packages/deadcanary/HANDOFF.md`.

---

## OPEN QUESTIONS FOR CHRIS

1. **Should deadcanary support warehouses other than DuckDB?** Today it is DuckDB
   only, which is most of the reason a stranger's project would not work. Snowflake
   or BigQuery support means credentials, cost, and a much slower test loop.
   **Cost:** days of work, and it makes CI depend on a paid warehouse.
   **Recommendation: no, and say so loudly in the README instead.** DuckDB-only is a
   defensible scope, and "works on your local dbt project" is a real audience.
   Answer: support more warehouses, or state the limit clearly.

2. **Is one production dbt suite worth chasing for the resume claim?** It is the
   single thing that would most strengthen the finding, and it depends on locating
   a public one that builds. **Cost:** likely a day, and it may not exist in a
   runnable form. **Recommendation: try for two hours, then stop and keep the
   honest three-project framing.** Answer: chase it, or ship as is.
