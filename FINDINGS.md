# What this found in dbt-labs' own projects

Two public projects, both from dbt-labs, both measured with the tool in this repo.
Every number below is reproducible with the commands given; nothing here is an
estimate.

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

## What these numbers are not

- **Two projects is two projects.** This is not a survey of the ecosystem, and no
  claim like "X% of data tests in the wild are decorative" is made anywhere in
  this repo.
- **Both are teaching projects from one vendor.** They are meant to be simple.
  Production suites may be better or very much worse; nobody has measured that.
- **"Dead canary" means no corruption THIS TOOL TRIED could kill it.** The
  catalogue is eight named corruptions. A test surviving all of them may still
  catch something not modelled here.
- **A dead test is not always a useless test.** It documents intent, and intent
  has value. What it does not do is warn you.

## Why the method can be trusted, in four numbers this tool refuses to fudge

Every one of these was a real defect that made the tool look MORE impressive than
the truth, and each is now a verdict of its own rather than a silent assumption:

| | |
|---|---|
| **20** corruptions on the template changed no rows | counted as NO-OP, never as "nothing caught it" |
| corruptions wiped by a dbt rebuild | counted as UNDONE, never as a miss |
| tests dbt skipped after another test failed | never credited with a catch, and never called dead |
| a project with nothing corruptible | refused with exit 2, cannot tell, never exit 0 |

The first version of this tool reported **20 of 20 tests dead** on jaffle_shop.
That was an artifact: it was corrupting models, which dbt rebuilds from source, so
the damage was gone before a single test ran. It read as a spectacular finding.
The difference between that and the numbers above is the four rules in this table.
