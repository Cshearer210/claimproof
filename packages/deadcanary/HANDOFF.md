# HANDOFF — claimproof and deadcanary, 2026-08-13 (evening)

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
| Tests | **316** claimproof + **76** deadcanary, both from a clean venv |
| CI | 17 jobs |
| PyPI | `claimproof` **0.13.0 published** · `deadcanary` **approved, not yet released** |

`pip install claimproof` is the library. `claimproof[dbt]` is both halves.
`pip install deadcanary` still works on its own — two downloads, one repo.

**`Cshearer210/deadcanary` is a fossil.** Its README says so. A change made there
reaches nothing. It was kept rather than deleted because inbound links and its
history point at it.

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

## THREE MORE DEFECTS, FOUND 2026-08-13 BY MEASURING A THIRD PROJECT

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

## AND THE MERGE ITSELF SWITCHED TWO CHECKS OFF

`git subtree` brought `packages/deadcanary/.github/workflows/ci.yml` along, and
**GitHub runs only workflows at the repository ROOT.** So the check that the demo
still finds its two planted dead canaries, and the one that types what the README
says, stopped running the moment the merge landed — while the file sat in the
tree looking exactly like coverage. Both are root jobs now
(`deadcanary-demo`, `deadcanary-readme`) and the orphaned file is deleted.

## IN FLIGHT RIGHT NOW

**The third project's measurement is still running** —
`adityawarmanfw/dbt_duckdb_chinook`, 19 models, **63 tests** (53 `not_null`, 10
`unique`), 11 CSV sources, **289 planned corruptions** at roughly 30 seconds each
because every one is a full dbt rebuild plus a test run. Started 13:35 local,
expect ~2.5 hours. It writes `deadcanary-report.json` beside the project when
done. **`FINDINGS.md` has NOT been updated with it — no numbers exist yet, and
none may be written until that file lands.**

How it was set up, which is the part worth not re-deriving:

```bash
cd packages/deadcanary/projects
git clone https://github.com/adityawarmanfw/dbt_duckdb_chinook.git
py -m venv .venv-chinook
./.venv-chinook/Scripts/python.exe -m pip install "dbt-duckdb~=1.9.0" "duckdb==1.1.3"
cd dbt_duckdb_chinook
../.venv-chinook/Scripts/python.exe -m dbt.cli.main deps --profiles-dir .
../.venv-chinook/Scripts/python.exe -m dbt.cli.main run-operation stage_external_sources --profiles-dir .
../.venv-chinook/Scripts/python.exe -m dbt.cli.main build --profiles-dir .   # 82 pass, 0 error
../.venv-chinook/Scripts/python.exe -m deadcanary .
```

**duckdb is pinned to 1.1.3 on purpose.** The project's `dim_date` model does
`date_trunc('week', ...) + 6`, which modern duckdb refuses with a binder error.
Pinning is what lets the project build **completely unmodified** — no model and
no test is touched, which is a stronger position than the jaffle-shop-template
measurement, where a withdrawn dependency had to be removed.

## WHAT IS NOT DONE

1. **The PyPI release has not been cut.** Publishing is approved and the workflow
   is ready and tested; it fires on a published GitHub release, or by
   `workflow_dispatch`. Recorded in the workflow: a token scoped to the
   *claimproof project* cannot create a new project, so the first `deadcanary`
   upload may 403 while claimproof succeeds. That is a credential scope, not a
   broken workflow, and the fix is an account-scoped token or a pending publisher
   for `deadcanary` at pypi.org — **both are browser steps only Chris can do.**
2. **`FINDINGS.md` still describes two projects**, both dbt-labs. See above.
3. **Parquet sources are declined, not corrupted.** Recognised and reported,
   never silently skipped. Real work for whoever wants it.
4. **The local `PureEuphoria/deadcanary` checkout is now a duplicate** of
   `claimproof/packages/deadcanary`. It is only still there because the
   measurement is running inside it. Once that finishes it should go, along with
   `projects/` (cloned third-party dbt projects and a venv, all re-creatable from
   the commands above).

## DECISIONS WAITING ON CHRIS

Both are instant and public with no review step, which is why they were not taken:

1. **The repo's public description and topics still describe only claimproof** —
   no mention of dbt or data tests, so somebody finding it sees half of what is
   in it. Recommend updating both.
2. **Archive `Cshearer210/deadcanary` on GitHub?** Its README already says the
   work moved. Archiving makes that unmissable and is reversible. Recommend yes.

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
py -m pytest packages/deadcanary/tests -q               # 76
py tools/fresh_eyes.py                                  # the claimproof README, typed out
py packages/deadcanary/tools/readme_runs.py --selftest   # prove the README check can fail
cd packages/deadcanary
py -m deadcanary demo --expect-dead 2                   # the planted canaries are still found
py -m deadcanary demo --recheck                         # 0 holds, 1 measure again, 2 cannot tell
```
