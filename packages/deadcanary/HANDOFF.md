# HANDOFF — claimproof and deadcanary, 2026-08-13 (evening)

> **THE PLAN IS the project's own plan file, one level up.** Read it first. It is the one list for
> this project, written after Chris said this had taken too long to become
> downloadable. This file is the state and the traps; that file is the work.
>
> **Picking it up tomorrow: Tier 1.1 is the only thing blocking "ready for anyone
> to download" — merge PR #26 and cut the release.** Everything else is
> improvement, not blocking.

Everything below was verified by running it, not recalled. Where something is
still in flight it says so rather than being written as finished.

## THEY ARE ONE REPO NOW

Chris, 2026-08-13: *"i want deadcanary and claimproof to be combined and both
used as the things people download. they should be combined in a skillful way
that makes sense."*

| | |
|---|---|
| Home | `Cshearer210/claimproof`, `main` clean and green |
| Locally | `PureEuphoria/claimproof`, with deadcanary at `packages/deadcanary` |
| Tests | **316** claimproof + **77** deadcanary, both from a clean venv |
| CI | 17 jobs |
| PyPI | `claimproof` **0.14.0** · `deadcanary` **0.1.0** — both published 2026-08-13 |

`pip install claimproof` is the library. `claimproof[dbt]` is both halves.
`pip install deadcanary` still works on its own — two downloads, one repo.

**`Cshearer210/deadcanary` is ARCHIVED** (read-only on GitHub, 2026-08-13). Its
description and README both say where the work went. History and inbound links
survive; nothing can be pushed there. The local checkout that used to sit at
`PureEuphoria/deadcanary` is **gone** — 528 MB, proven behind everywhere and
ahead nowhere before it was removed.

## THE TWO OPEN QUESTIONS ARE ANSWERED — do not ask them again

1. ~~Publish deadcanary to PyPI?~~ **YES**, Chris, 2026-08-13. The publish
   workflow handles both packages; the release has not been cut yet (see below).
2. ~~Which is the resume artifact?~~ **NEITHER ALONE — combine them**, and that
   is what the whole of this handoff describes.

## What the two things are, and why they are one idea

claimproof refuses a claim of success that carries no evidence a machine can
check. **"All 20 data tests pass" is exactly such a claim**, and green is equally
what a test that *cannot fail* looks like, every morning, for two years.
deadcanary settles which one you have by corrupting real data on purpose.

**The seam is code, in `src/deadcanary/gate.py`:**

- `GreenTestsUnproven` — a claimproof `Gate`. Refuses a claim of data-test health
  unless a complete deadcanary run backs it. Six selftest cases, **four of them
  guards**, because a gate that reaches into claims it has no business in gets
  switched off and then catches nothing at all.
- `attest()` / `recheck()` — the proof EXPIRES. It is fingerprinted against the
  test **suite** (every test, its kind, what it hangs off, every source), so
  adding a test reopens the claim on its own. **Proven both ways on the real demo
  project, not a fixture:** recorded → HOLDS exit 0; one test added → REOPENED
  exit 1 naming `dbt:test-suite`; file restored → HOLDS again, which also shows
  the fingerprint is content and not a timestamp.
- It deliberately ignores dbt's run metadata. `manifest.json` carries a fresh
  timestamp and invocation id on every build, so fingerprinting the file would
  reopen the claim after every run — a checker crying wolf, which gets switched
  off within a week.

## THE FIVE WAYS THIS TOOL CAN LIE — do not "optimise" any of them

Every one was a real defect found by real use, and every one made the tool look
MORE impressive than the truth.

1. **NO-OP** — a corruption that changed no rows is never a miss.
2. **UNDONE-BY-REBUILD** — dbt regenerates models, so a corruption aimed at one
   is wiped before any test runs. *The first version reported 20 of 20 tests dead
   for this reason and it read as a spectacular finding.* Models are never
   targeted, and the corruption is re-checked after the run.
3. **PARTIAL COVERAGE** — a run that did not corrupt every source names no dead
   canaries at all.
4. **SKIPPED BY DBT** — when a test fails, dbt skips everything downstream. Only
   a genuine `fail` counts. **`hunt.py` runs `dbt run` then `dbt test` as two
   calls on purpose; someone folded that into one `dbt build` and it made 2 of 4
   findings false.** Do not undo it.
5. **NOTHING TO CORRUPT** — raises `NothingToCorrupt`, CLI exits 2 (cannot tell),
   never 0.

## FOUR MORE DEFECTS, FOUND 2026-08-13 BY MEASURING A THIRD PROJECT

The first two made the tool **refuse healthy projects and blame the project**.

6. **The warehouse is wherever the PROFILE says it is.** Searching the disk for a
   `.duckdb` is a guess, and it was wrong in both directions:
   `adityawarmanfw/dbt_duckdb_chinook` writes to `./target/chinook.duckdb`, which
   the search skipped as a build artifact — then told the user to run
   `dbt seed && dbt run`, which they had just done.
   `matsonj/nba-monte-carlo` keeps its warehouse OUTSIDE the project, where no
   search under the root can ever reach. Now read from the profile, with the
   search as a fallback only when the answer is not certain (no profile, Jinja in
   the path, a file not yet built). **`dbt-labs/jaffle-shop-template` templates
   its path, so it still takes the fallback — that is a guard case in the tests.**
7. **A source location is written in THREE places** and the tool knew one.
   `meta.external_location` wrapped in `read_csv_auto()` was the only shape read;
   `sdebruyn/inzight` writes the same key as a **bare path**, and the
   `dbt-external-tables` package writes `external.location` with an empty `meta`.
   Both are real projects whose raw data sat in plain sight while this reported
   NOTHING TO CORRUPT — a verdict that reads as *your project is fine*.
   The guard matters: once a bare string counts as a path, a bucket, a URL or a
   plain warehouse table name must all be turned away.
8. **PyYAML was an accident, not a dependency.** Reading the profile was wrapped
   in `except ImportError: return None`, so on any machine without PyYAML the
   whole method silently did nothing and the tool reverted to the guess it exists
   to replace. It passed here only because dbt drags PyYAML in. **CI caught it
   within a minute.** Declared now, and the swallow is gone.
9. **Models were counted as tests.** A run announced *"82 test(s) in the suite,
   63 green"* for a project with 63 tests and nothing failing: `dbt build` writes
   models and tests into one artifact and `test_results()` read both. It inflated
   the suite by every model and made a clean run read as 19 failures. The
   verdicts were never affected — a model reports `success` where a test reports
   `pass`, so the green set was right by accident — but **the headline is the
   number a reader takes away.** Held down by
   `test_models_are_never_counted_as_tests`.

## AND THE MERGE ITSELF SWITCHED TWO CHECKS OFF

`git subtree` brought `packages/deadcanary/.github/workflows/ci.yml` along, and
**GitHub runs only workflows at the repository ROOT.** So the check that the demo
still finds its two planted dead canaries, and the one that types what the README
says, stopped running the moment the merge landed — while the file sat in the
tree looking exactly like coverage. Both are root jobs now
(`deadcanary-demo`, `deadcanary-readme`) and the orphaned file is deleted.

## THE THIRD PROJECT, MEASURED

`adityawarmanfw/dbt_duckdb_chinook` — independent author, real relational schema,
and it builds **completely unmodified**, which the dbt-labs template measurement
could never claim.

| | |
|---|---|
| Green tests | 63 |
| **Tests no corruption could make fail** | **0** |
| Corruptions applied | 255 of 289 planned (34 no-op, 0 undone) |
| **Corruptions nothing caught** | **182 — 71%** |
| Run time | 115 minutes |

**The finding is the second number.** The suite is 53 `not_null` and 10 `unique`
tests; it caught nulls and duplicates and missed everything else. **Every one of
its eleven source tables can be emptied completely and all 63 tests stay green.**

The raw report is committed at `findings/chinook-2026-08-13.json`, so any number
in `FINDINGS.md` can be checked by reading rather than by re-running two hours of
dbt. The two dbt-labs projects predate that folder and their raw reports were not
kept — reproducible from the commands in FINDINGS.md, but the artifacts are gone.

**To measure a fourth project**, the setup that worked:

```bash
cd packages/deadcanary/projects          # gitignored; clones live here
git clone <the project>
py -m venv .venv-<name>
./.venv-<name>/Scripts/python.exe -m pip install "dbt-duckdb~=1.9.0" deadcanary
```

**Pin duckdb to the era the project was written for.** chinook needed
`duckdb==1.1.3` because its `dim_date` does `date_trunc('week', ...) + 6`, which
current duckdb refuses. Pinning is what let it build with nothing edited.

## WHAT IS NOT DONE

0. **RELEASE 0.14.1 IS NOT CUT.** PR #26 is open with both version bumps and was
   green on 12 of 17 checks when the session ended. **Until it ships, both PyPI
   pages show 18 links that go nowhere and claimproof's hero image is broken** —
   PyPI renders the description shipped inside the release, so fixing the repo
   changed nothing on the pages. This is the single thing standing between today
   and "ready for anyone to download".
1. **Parquet sources are declined, not corrupted.** Recognised and reported, never
   silently skipped. Real work for whoever wants it.
2. **No production dbt suite has ever been measured.** All three projects are
   demonstrations. `FINDINGS.md` says so plainly and no claim about "data tests in
   the wild" is made anywhere.
3. **The two dbt-labs raw reports were never kept.** See above.
4. **`--attest` re-runs the whole hunt.** It rides free on an existing run
   (`--expect-dead 2 --attest` is one hunt), but there is no way to record a proof
   from a report already on disk. Fine today; it would matter for a big project.

## DECISIONS: ALL ANSWERED, NOTHING WAITING

Nothing is blocked on Chris. For the record, resolved 2026-08-13:

- **Publish to PyPI?** Yes — both are live.
- **Which is the resume artifact?** Neither alone; they were combined.
- **Repo description and topics?** Updated to cover both packages, plus six new
  topics (dbt, data-quality, mutation-testing, data-engineering, duckdb,
  analytics-engineering).
- **Archive the old repo?** Yes. Chris: *"why would we not archive the old
  versions"* — and he was right that the question was badly worded: the thing
  archived is the OLD standalone repo, never the new combined build.

## TRAPS THAT COST TIME

- **`pytest -q | tail -1 && git commit` hides failures** — the pipe reports
  `tail`'s status. Three collection errors got committed that way. The same trap
  bit again this session reading `$?` after piping a `deadcanary` run into `tail`.
- **`bash` on this laptop resolves to WSL**, which has none of the checkout.
  `tools/readme_runs.py` runs argv directly for this reason.
- **Both repos protect `main`.** `gh pr create`, then `gh pr merge --squash`.
- **Pushing needs the `Cshearer210` account.** `gh auth switch --user Cshearer210`,
  and switch back to `noredfarms` afterwards.
- **A long `deadcanary` run buffers its stdout when redirected**, so the output
  file sits at 0 bytes for hours. To tell whether it is alive, watch the mtime of
  the project's `target/run_results.json` — it moves every ~30 seconds.

## THE COMMANDS

```bash
cd claimproof
py -m pytest tests -q                                   # 316
py -m pytest packages/deadcanary/tests -q               # 77
py tools/fresh_eyes.py                                  # the claimproof README, typed out
py packages/deadcanary/tools/readme_runs.py --selftest   # prove the README check can fail
cd packages/deadcanary
py -m deadcanary demo --expect-dead 2                   # the planted canaries are still found
py -m deadcanary demo --recheck                         # 0 holds, 1 measure again, 2 cannot tell
```
