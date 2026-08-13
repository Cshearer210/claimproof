# What this found in real dbt projects

Three public projects measured with the tool in this repo. Two are dbt-labs' own
teaching projects; the third is by an independent author, uses a different
dataset, and reads its raw data a different way. Every number below is
reproducible with the commands given; nothing here is an estimate.

## The question

A data test that has been green every morning for two years is green for one of
two reasons: the data is healthy, or the test cannot fail. Nobody can tell those
apart by looking, and almost nobody checks.

So: break the data on purpose, and see which tests notice.

## dbt-labs/jaffle-shop-template — 6 of 20 green tests cannot fail

dbt-labs' current jaffle-shop, the one most people meet first.

| | |
|---|---|
| Green tests before anything is touched | 20 |
| **Tests no corruption could make fail** | **6 — 30%** |
| Corruptions actually applied | 102 |
| Corruptions **nothing caught** | 76 |
| Corruptions that changed no rows, not counted either way | 20 |
| Coverage | complete — every discovered source was corrupted |

The six:

```
accepted_values_customers_customer_type__new__returning
dbt_utils_expression_is_true_orders_count_food_items_count_drink_items
dbt_utils_expression_is_true_orders_subtotal_food_items_subtotal_drink_items
not_null_orders_order_id
not_null_stg_supplies_supply_uuid
unique_orders_order_id
```

`unique_orders_order_id` and `not_null_orders_order_id` are the two most common
tests in dbt. In this project neither can be made to fail by any corruption in
the catalogue — including emptying the source file the orders are built from.

**Reproduce it.** This project pins `dbt-labs/metrics`, which dbt-labs has since
withdrawn from the package hub, so it needs an older dbt and that one dependency
removed. Nothing else about the project is changed, and no model or test is
touched:

```bash
python -m venv .dbt18 && ./.dbt18/bin/pip install "dbt-core~=1.8.0" "dbt-duckdb~=1.8.0"
git clone https://github.com/dbt-labs/jaffle-shop-template
cd jaffle-shop-template
# remove the withdrawn metrics package and the one file that uses it
printf 'packages:\n  - package: dbt-labs/dbt_utils\n    version: 1.0.0\n' > packages.yml
rm -rf models/metrics
../.dbt18/bin/dbt deps --profiles-dir . && ../.dbt18/bin/dbt build --profiles-dir .
../.dbt18/bin/pip install deadcanary
../.dbt18/bin/python -m deadcanary .
```

## dbt-labs/jaffle_shop_duckdb — 0 dead, but 13 corruptions nothing caught

The older, smaller jaffle_shop, 285 stars.

| | |
|---|---|
| Green tests | 20 |
| Tests no corruption could make fail | 0 |
| Corruptions applied | 37 |
| Corruptions **nothing caught** | 13 |

Every test here earns its place — but the suite still misses a third of what was
thrown at it. The starkest: **emptying `raw_orders` entirely, 99 rows to 0,
leaves all 20 tests green.** A test suite that cannot tell the difference between
a full table and an empty one is not watching for the failure most likely to
actually happen.

## adityawarmanfw/dbt_duckdb_chinook — 0 dead canaries, and 182 corruptions nothing caught

**Every test in this suite can be made to fail. Not one is decorative.** And the
suite still missed **182 of the 255 corruptions actually applied — 71%** —
including emptying every single one of its eleven source tables.

| | |
|---|---|
| Green tests before anything is touched | 63 |
| **Tests no corruption could make fail** | **0** |
| Corruptions planned | 289 |
| Corruptions actually applied | 255 |
| **Corruptions nothing caught** | **182 — 71%** |
| Corruptions that changed no rows, not counted either way | 34 |
| Corruptions wiped by a rebuild, not counted either way | 0 |
| Coverage | complete — every discovered source was corrupted |
| Run time | 115 minutes |

**This is the more useful finding of the three, and it is not the flattering one.**
A dead-canary count answers *is this test decorative?* This answers the question
underneath it: *what does a green suite actually protect you from?*

The suite is 53 `not_null` tests and 10 `unique` tests. What it caught:

```
53  blank_required     a required column arrives empty
10  duplicate_key      a row is loaded twice
10  break_reference    a key points at a row that does not exist
```

What walked straight through it:

```
64  unexpected_category  a column starts arriving as an unagreed value
54  break_reference      a key pointing at nothing, everywhere the joins tolerate it
30  negative_amount      a number arrives with its sign reversed
11  drop_rows            rows never arrive, and nothing errors
11  empty_table          the ENTIRE table is empty
11  blank_required       a required column empty, where no not_null watches it
```

**A suite of `not_null` and `unique` tests catches nulls and duplicates.** Said
aloud it is obvious. What nobody had measured is the size of the remainder, and
on this project the remainder is seven corruptions in ten.

**The starkest single result:** *every one of the eleven source tables can be
emptied completely — album, artist, customer, employee, genre, invoice,
invoice_line, media_type, playlist, playlist_track, track — and all 63 tests
stay green.* A suite that cannot tell a full table from an empty one is not
watching for the failure most likely to actually happen. The smaller
`jaffle_shop_duckdb` showed the same thing on one table; here it is all of them.

The first project measured here that is **not** from dbt-labs. Different author,
different dataset — the Chinook music store, a schema with real referential
structure rather than a teaching toy — and a bigger suite than either jaffle
shop: **19 models, 63 tests** (53 `not_null`, 10 `unique`) over **11 CSV
sources**, giving **289 corruptions to try**.

It also reads its raw data a third way, which is the reason this tool could not
see it at all until today. Its sources are staged by the `dbt-external-tables`
package, so the manifest records `external.location` as a bare path with an empty
`meta` — where dbt-labs' template writes `meta.external_location` wrapped in
`read_csv_auto(...)`. A tool that knows one shape reports NOTHING TO CORRUPT on a
project whose raw data is sitting in plain sight, and that verdict reads as *your
project is fine*.

**Reproduce it.** Nothing about the project is changed — no model, no test, not
one line:

```bash
git clone https://github.com/adityawarmanfw/dbt_duckdb_chinook
python -m venv .dbt19
./.dbt19/bin/pip install "dbt-duckdb~=1.9.0" "duckdb==1.1.3" deadcanary
cd dbt_duckdb_chinook
../.dbt19/bin/dbt deps --profiles-dir .
../.dbt19/bin/dbt run-operation stage_external_sources --profiles-dir .   # CSVs -> views
../.dbt19/bin/dbt build --profiles-dir .                                 # 82 pass, 0 error
../.dbt19/bin/python -m deadcanary .
```

**duckdb is pinned to 1.1.3 on purpose, and the pin is the point.** The project's
`dim_date` model does `date_trunc('week', ...) + 6`, which current duckdb refuses
with a binder error. Pinning to the era the project was written for lets it build
**completely unmodified** — a stronger position than the jaffle-shop-template
measurement above, where a withdrawn dependency had to be removed first.

## What these numbers are not

- **Three projects is three projects.** This is not a survey of the ecosystem, and
  no claim like "X% of data tests in the wild are decorative" is made anywhere in
  this repo.
- **All three are demonstration projects, and two are from one vendor.** They are
  meant to be simple. The third at least removes the "one vendor" problem: a
  different author, a different dataset, and raw data read through a different
  mechanism. It does not remove the "not production" problem. Production suites
  may be better or very much worse; nobody has measured that, including me.
- **"Dead canary" means no corruption THIS TOOL TRIED could kill it.** The
  catalogue is eight named corruptions. A test surviving all of them may still
  catch something not modelled here.
- **A dead test is not always a useless test.** It documents intent, and intent
  has value. What it does not do is warn you.
- **Zero dead canaries is not a clean bill of health, and the third project is
  the proof.** Every one of its 63 tests can be made to fail, and 71% of the
  damage thrown at it still went unnoticed. Reading "0 dead" as "well covered"
  gets that exactly backwards. The two questions are different: *can this test
  fail?* and *what is nobody watching?*
- **The 71% figure is a fraction of what THIS CATALOGUE tried**, not of all
  possible damage. A different catalogue would produce a different denominator.
  It is a floor on what the suite misses, never a ceiling.

## Why the method can be trusted, in four numbers this tool refuses to fudge

Every one of these was a real defect that made the tool look MORE impressive than
the truth, and each is now a verdict of its own rather than a silent assumption:

| | |
|---|---|
| **20** on the template and **34** on chinook changed no rows | counted as NO-OP, never as "nothing caught it" |
| corruptions wiped by a dbt rebuild | counted as UNDONE, never as a miss |
| tests dbt skipped after another test failed | never credited with a catch, and never called dead |
| a project with nothing corruptible | refused with exit 2, cannot tell, never exit 0 |

The first version of this tool reported **20 of 20 tests dead** on jaffle_shop.
That was an artifact: it was corrupting models, which dbt rebuilds from source, so
the damage was gone before a single test ran. It read as a spectacular finding.
The difference between that and the numbers above is the four rules in this table.

**And a fifth found while measuring the third project, in the same direction.**
The run announced *"82 test(s) in the suite, 63 green"* for a project with 63
tests and nothing failing: `dbt build` writes models and tests into the same
artifact, and this counted both. It inflated the suite by every model in the
project and made a completely green run read as 19 failures. The verdicts were
never affected -- a model reports `success` where a test reports `pass`, so the
green set was right by accident -- but the headline was wrong, and the headline
is the number a reader takes away. Held down now by
`test_models_are_never_counted_as_tests`.
