# deadcanary

**Find the data tests that cannot fail.**

A canary that is already dead cannot warn you about anything, and it looks exactly like
one that is alive and well.

Data test suites fill up with them. A team accumulates hundreds of `not_null`, `unique`
and `accepted_values` checks over a couple of years. Every one of them is green every
morning. Some are green because the data is healthy. Some are green because they were
never capable of going red — the column they watch is behind a join that drops the bad
rows, or the model rebuilds from a source the test never sees, or the assertion is
simply about something that cannot happen.

Nobody can tell those two groups apart by looking, and nobody ever checks.

The only way to know is to **break the data on purpose and see which tests notice.**

```
$ deadcanary path/to/dbt/project

  28 test(s) in the suite, 20 green before we touch anything
  not aiming at 2 table(s) dbt rebuilds: customers, orders
  11 column(s) discovered, 41 corruption(s) to try

  [  1/41] caught  blank_required on raw_customers.id
  [  2/41] caught  duplicate_key on raw_customers.id
  [  3/41] MISSED  blank_required on raw_customers.first_name
  ...
```

This is **mutation testing** — decades old, well proven for source code
([`mutmut`](https://pypi.org/project/mutmut/),
[`cosmic-ray`](https://pypi.org/project/cosmic-ray/)) — pointed at data quality rules
instead of at functions.

## What it found in three real dbt projects

**6 of 20 green tests in dbt-labs' current jaffle-shop template cannot fail.**
Among them `unique_orders_order_id` and `not_null_orders_order_id` — the two most
common tests in dbt. 102 corruptions were applied to that project and **76 caught
nothing at all.**

In the older `jaffle_shop_duckdb`, every test earns its place — and yet
**emptying `raw_orders` entirely, 99 rows to 0, leaves all 20 tests green.**

And in `adityawarmanfw/dbt_duckdb_chinook`, by an independent author and building
completely unmodified: **0 dead canaries — every one of its 63 tests can be made
to fail — and 182 of the 255 corruptions applied, 71%, were caught by nothing.**
That suite is 53 `not_null` and 10 `unique` tests, so it catches nulls and
duplicates and very little else. **Every one of its eleven source tables can be
emptied completely and all 63 tests stay green.**

**Zero dead canaries is not a clean bill of health**, and that project is the
proof. The two questions are different: *can this test fail?* and *what is nobody
watching?*

All three are reproducible, the raw report for the newest is committed in
[findings/](https://github.com/Cshearer210/claimproof/tree/main/packages/deadcanary/findings), and the limits of what any of it means are stated:
[FINDINGS.md](https://github.com/Cshearer210/claimproof/blob/main/packages/deadcanary/FINDINGS.md).

## Try it without a dbt project of your own

A tiny dbt project with **two deliberately useless tests planted in it** ships
inside the package, so there is nothing to clone and nothing to wire up.

<!-- readme: illustration -->
```bash
pip install deadcanary[demo]
python -m deadcanary.demo
```

It builds a small warehouse, corrupts it fourteen ways, and re-runs the suite
against each one. **Give it five to ten minutes** and watch the corruptions go by:
every line is a real dbt run, which is the only way this question can be answered
honestly. Nothing is pre-recorded.

Already have a dbt project? Skip the demo:

<!-- readme: run -->
```bash
git clone https://github.com/Cshearer210/claimproof
cd claimproof/packages/deadcanary
pip install -e .[dbt]

cd src/deadcanary/_demo && dbt build --profiles-dir . && cd ../../..   # 10 green tests
python -m deadcanary src/deadcanary/_demo
```

It finds both:

```
  2 of 7 green tests are DEAD CANARIES (29%)

  Tests that cannot fail:
    x accepted_values_stg_orders_status__placed__shipped__completed
    x not_null_orders_amount
```

Neither is contrived. Look at `src/deadcanary/_demo/models/stg_orders.sql`: it filters to
`status in ('placed','shipped','completed')`, so the `accepted_values` test on
that column can never see a bad value however broken the upstream data gets.
And `src/deadcanary/_demo/models/orders.sql` wraps the amount in `coalesce(amount, 0)`, so a NULL
arriving from upstream becomes a zero before the `not_null` test ever looks. Both
are ordinary, sensible-looking SQL. Both quietly disarm the test above them.

The other five tests in that project are alive, and the run says which corruption
killed each one.

## Install

<!-- readme: illustration -->
```bash
pip install deadcanary[dbt]         # this package alone
pip install claimproof[dbt]         # ...or both halves, see below
```

Runs locally against DuckDB: no warehouse credentials, no cloud spend, no model
calls.

## The other half: `claimproof`

deadcanary lives in the [claimproof](https://github.com/Cshearer210/claimproof) repo
because it is the same idea one layer down. **A check nobody has ever made fail is not
a check.** claimproof enforces that on gates — it refuses one at construction unless
the gate can demonstrate both a case it catches and a guard case it leaves alone.
deadcanary asks it of a whole dbt test suite, and answers with real corrupted data
instead of fixtures.

They join at one seam, and it does two things neither does alone.

**"The data tests pass" stops being accepted as evidence.** It is a claim like any
other, and it reads identically whether the data is healthy or the tests cannot fail:

<!-- readme: illustration -->
```python
from deadcanary.gate import GreenTestsUnproven

GreenTestsUnproven(project="warehouse/dbt").inspect("All 20 dbt tests pass.")
# -> these data tests have never been proved able to fail -- no deadcanary run
#    backs this. Green is also what a test that cannot fail looks like.
```

It is a claimproof `Gate`, so it had to prove itself in both directions before it was
allowed to refuse anything. Four of its six cases are guards — an ordinary unit-test
suite, an honest hedge, a reported failure, and somebody asking the question rather
than claiming the answer — because a gate that reaches into claims it has no business
in gets switched off, and after that it catches nothing at all.

**And the proof expires.** This answers *can these tests fail?* for the suite as it
stood on the day it ran. Add a test next month and that answer describes a suite that
no longer exists, and nothing anywhere would say so:

<!-- readme: illustration -->
```bash
python -m deadcanary warehouse/dbt --attest     # record what was proved
python -m deadcanary warehouse/dbt --recheck    # 0 holds - 1 measure again - 2 cannot tell
```

```
REOPENED  deadcanary:dbt
          closed 2026-08-13T19:09:25Z on "the data tests in dbt were proved able to
          fail (20 green, 0 dead)", but 1 of 2 piece(s) of evidence changed since
          (dbt:test-suite), so it is UNVERIFIED until re-measured
```

The fingerprint covers what the suite **tests** — every test, its kind, what it hangs
off, and every source — and deliberately ignores dbt's run metadata. `manifest.json`
carries a fresh timestamp and invocation id on every build, so fingerprinting the file
would reopen the claim after every single run. A checker that cries wolf gets switched
off within a week, and then the one time it is right is ignored too.

## Two kinds of project, one report

Where a project's raw data lives decides what there is to break.

**Data in the warehouse.** Seeds and source tables get corrupted in the database.
Models are never touched, because dbt rebuilds them from source and the damage
would be gone before a single test ran.

**Data in files.** A lot of real dbt work never loads raw data at all -- a
dbt-duckdb source can point straight at a CSV:

```yaml
sources:
  - name: raw_orders
    meta:
      external_location: "read_csv_auto('./jaffle-data/{name}.csv', header=1)"
```

dbt-labs' own current jaffle-shop template is built this way, and against a
project like that the warehouse holds nothing but models. So the file *is* the
raw table, and it gets corrupted the same way, with the same named corruptions
and the same stories. Paths come from dbt's manifest rather than from parsing the
YAML, every file is copied aside first, and every one is restored byte for byte.

Parquet sources are recognised and declined rather than skipped quietly. A
project with nothing corruptible at all is refused out loud with exit 2 -- cannot
tell -- never exit 0, which would read as "your tests are fine".

## The five ways a tool like this lies, and what stops each one

This is the interesting part, and it is most of the work. A tool that corrupts data and
counts silence has three easy ways to produce an impressive number that means nothing.
All three were live in the first working version, and each is now a verdict of its own
rather than a quiet assumption.

**1. The corruption never happened.** A mutation that sets a column to NULL when the
column is already all NULL changes nothing, so of course no test fires. Counting that as
"nothing caught it" inflates the headline with corruptions that never occurred.
→ every mutation is re-read afterwards; unchanged data is **NO-OP**, counted neither way.

**2. The corruption was undone before anything looked at it.** dbt rebuilds its models
from source on every run. Corrupt one of those and the damage is gone before the first
test executes. *The first run of this tool reported 20 of 20 tests dead for exactly this
reason.* It read as a spectacular finding and it was an artifact.
→ models are never targeted, and the corruption is re-checked after the run. Wiped
damage is **UNDONE-BY-REBUILD**, counted neither way.

**3. The test never got a chance.** Stop the run early, or skip a table, and every test
watching the untouched data has "never failed" — indistinguishable from a genuinely dead
one.
→ coverage is tracked per table, and **no dead-canary figure is claimed at all** unless
every discovered table was actually corrupted.

**4. dbt skipped the test.** When one test fails, dbt skips everything downstream of it.
A skipped test neither caught the problem nor missed it — it never ran. Counting a skip as
a catch made one real failure credit four tests that never executed.
→ only a genuine `fail` counts, models and tests are run in separate passes so nothing is
skipped in the first place, and a test skipped everywhere is reported as never-executed.

**5. There was nothing to corrupt.** Point it at a project whose raw data lives in files
and, before file support existed, it discovered zero tables and reported a completed run
with no findings. Exit 0. It looked exactly like a healthy project.
→ **`NothingToCorrupt`, and the CLI exits 2 — cannot tell.** A tool arguing that absent
and fine must never look like present and fine was doing precisely that about itself.

Each of those turns a flattering lie into an honest gap. That is the entire design.

## What it does not do

- **It does not judge whether a test is *worth* having.** A test that catches only
  corruptions nobody would ever ship is still counted as alive.
- **It does not prove a live test is correct**, only that something can make it fail.
- **It only knows the corruptions in its catalogue.** A test that survives all of them
  might still catch something not modelled here. "Dead canary" means "no corruption *we
  tried* could kill it" — which is why the catalogue is short, named, and readable.

## Prior art, checked before this was built

- [`Agincy-Agint/datahub-quality-mutant`](https://github.com/Agincy-Agint/datahub-quality-mutant)
  (2026-08-07) applies mutation testing to **DataHub** data contracts. Same core idea,
  different target; this project addresses dbt and does not overlap it.
- [`dbt-coverage`](https://pypi.org/project/dbt-coverage/) reports which models and
  columns *have* a test. It never asks whether those tests can fail.
- [Great Expectations](https://pypi.org/project/great-expectations/),
  [`soda-core`](https://pypi.org/project/soda-core/) and
  [`elementary-data`](https://pypi.org/project/elementary-data/) run and monitor
  expectations. None of them validates the expectations themselves.
- [`mutmut`](https://pypi.org/project/mutmut/) and
  [`cosmic-ray`](https://pypi.org/project/cosmic-ray/) are the mature mutation testing
  tools for Python source, and the direct inspiration.

## Licence

MIT.
