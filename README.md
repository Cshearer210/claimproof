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

## Try it in one minute

The repo ships a tiny dbt project with **two deliberately useless tests planted in
it**, so you can see the point without wiring anything up.

```bash
git clone https://github.com/Cshearer210/deadcanary
cd deadcanary
pip install -e .[dbt]

cd demo && dbt build --profiles-dir . && cd ..   # 10 green tests
python -m deadcanary demo
```

It finds both:

```
  2 of 7 green tests are DEAD CANARIES (29%)

  Tests that cannot fail:
    x accepted_values_stg_orders_status__placed__shipped__completed
    x not_null_orders_amount
```

Neither is contrived. Look at `demo/models/stg_orders.sql`: it filters to
`status in ('placed','shipped','completed')`, so the `accepted_values` test on
that column can never see a bad value however broken the upstream data gets.
And `demo/models/orders.sql` wraps the amount in `coalesce(amount, 0)`, so a NULL
arriving from upstream becomes a zero before the `not_null` test ever looks. Both
are ordinary, sensible-looking SQL. Both quietly disarm the test above them.

The other five tests in that project are alive, and the run says which corruption
killed each one.

## Install

```bash
pip install -e .[dbt]          # from a clone
```

Not on PyPI yet. Runs locally against DuckDB: no warehouse credentials, no cloud
spend, no model calls.

## The three ways a tool like this lies, and what stops each one

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
