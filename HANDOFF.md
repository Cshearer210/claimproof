# HANDOFF — deadcanary and claimproof, 2026-08-13

Written after a long session that compacted. Everything below was verified by
running it, not recalled.

## Where both repos stand

| | claimproof | deadcanary |
|---|---|---|
| GitHub | `Cshearer210/claimproof`, main clean | `Cshearer210/deadcanary`, main clean |
| Tests | 316 pass | 55 pass |
| CI | 12 jobs green | 11 jobs green |
| Published | **PyPI 0.13.0** | **not on PyPI** — deliberate, see below |
| Local | `PureEuphoria/claimproof` | `PureEuphoria/deadcanary` |

Neither has uncommitted work. Both were verified from a clean clone in a fresh
virtual environment, following their own READMEs command for command.

## What deadcanary is

Mutation testing pointed at dbt data quality rules. It corrupts the data on
purpose and reports which tests never noticed — the **dead canaries**, tests that
are green every morning and cannot fail.

**The measured findings, in `FINDINGS.md`:**

- **dbt-labs/jaffle-shop-template: 6 of 20 green tests cannot fail (30%).**
  102 corruptions applied, 76 caught nothing. Among the dead:
  `unique_orders_order_id` and `not_null_orders_order_id`.
- **dbt-labs/jaffle_shop_duckdb: 0 dead canaries**, but emptying `raw_orders`
  entirely (99 rows to 0) leaves all 20 tests green.
- `demo/` in the repo carries **two dead canaries planted on purpose**, and CI
  asserts they are still found (`--expect-dead 2`).

## The five ways this tool can lie, all of them found by real use

Every one made the tool look MORE impressive than the truth. This is the part
worth protecting — if a future session "optimises" any of it, the numbers become
fiction:

1. **NO-OP** — a corruption that changed no rows is never a miss.
2. **UNDONE-BY-REBUILD** — dbt regenerates models, so a corruption aimed at one is
   wiped before any test runs. *The first version reported 20 of 20 tests dead
   for this reason and it read as a spectacular finding.* Models are never
   targeted, and the corruption is re-checked after the run.
3. **PARTIAL COVERAGE** — a run that did not corrupt every source names no dead
   canaries at all.
4. **SKIPPED BY DBT** — when a test fails, dbt skips everything downstream. Only a
   genuine `fail` counts. **`hunt.py` runs `dbt run` then `dbt test` as two calls
   on purpose; someone folded that into one `dbt build` and it made 2 of 4
   findings false.** Do not undo it.
5. **NOTHING TO CORRUPT** — raises `NothingToCorrupt`, CLI exits 2 (cannot tell),
   never 0.

## What is NOT done

**1. deadcanary is not on PyPI.** The README says `pip install -e .[dbt]` from a
clone, which is accurate. Publishing is Chris's call — it is outward-facing and
he has not been asked. `claimproof` publishes on a GitHub release; deadcanary has
no publish workflow yet.

**2. Only two projects measured, both dbt-labs teaching projects.** `FINDINGS.md`
states this limit plainly. A third project from a different author would make the
finding much stronger, and would want its own dbt version in its own venv —
`jaffle-shop-template` needed dbt 1.8 and its withdrawn `dbt-labs/metrics`
dependency removed.

**3. Parquet sources are declined, not corrupted.** Recognised and reported, never
silently skipped. Real work for whoever wants it.

**4. No `deadcanary` entry in `SYSTEM-MAP.md`.** claimproof is routed; this is not.

## Traps that cost time in this session

- **`PureEuphoria/claimproof` used to be called `agentattest`.** Renamed 2026-08-12.
  A drive search for "claimproof" once failed and a second clone got made. Ask pip
  where a package lives, never the filesystem.
- **Both repos protect `main`.** A direct push is rejected; it must be a PR with
  passing checks. `gh pr create` then `gh pr merge --squash`.
- **Pushing needs the `Cshearer210` account.** `gh auth switch --user Cshearer210`,
  and switch back to `noredfarms` afterwards. deadcanary's local git config carries
  the credential helper.
- **`pytest -q | tail -1 && git commit` hides failures** — the pipe reports
  `tail`'s status. Three collection errors got committed that way.
- **`bash` on this laptop resolves to WSL**, which has none of the checkout.
  `tools/readme_runs.py` runs argv directly for this reason.

## The commands

```bash
cd deadcanary
py -m pytest tests/ -q                    # 55
py tools/readme_runs.py --selftest        # prove the README check can fail
py tools/readme_runs.py                   # type what the README says
py -m deadcanary demo --expect-dead 2     # the planted canaries are still found
```

## OPEN QUESTIONS FOR CHRIS

1. **Publish deadcanary to PyPI?** Today anyone must clone it. Publishing means
   `pip install deadcanary` works and the README's own instructions get simpler.
   Cost: it is public and permanent, and the package name is claimed forever.
   Recommendation: yes, once a third project is measured, so the FINDINGS page
   people land on is not two projects from one vendor.
2. **Is deadcanary the resume artifact, or claimproof?** Both are live. deadcanary
   is the newer idea and has the more striking number; claimproof has 316 tests,
   two outside contributors and a published 69.8% finding. Splitting attention
   across both is the risk.
