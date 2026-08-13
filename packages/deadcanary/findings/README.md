# The raw reports behind FINDINGS.md

`FINDINGS.md` says *"nothing here is an estimate"*. These are the receipts — the
report files the tool wrote itself, unedited, so anyone can check a number rather
than take the summary's word for it.

| File | Project | Headline |
|---|---|---|
| `chinook-2026-08-13.json` | `adityawarmanfw/dbt_duckdb_chinook` | 63 green tests, **0 dead canaries**, 182 of 255 applied corruptions caught by nothing |
| `jaffle-shop-duckdb-2026-08-13.json` | `dbt-labs/jaffle_shop_duckdb` | 20 green tests, **0 dead canaries**, 13 of 37 applied corruptions caught by nothing |

Every corruption is in there with its verdict and its plain-English story, so a
disagreement can be settled by reading rather than by re-running two hours of dbt:

```bash
python - <<'PY'
import json
from collections import Counter
r = json.load(open("findings/chinook-2026-08-13.json"))
print(Counter(c["verdict"] for c in r["corruptions"]))
print([c["story"] for c in r["corruptions"]
       if c["verdict"] == "SURVIVED" and c["name"] == "empty_table"])
PY
```

**The jaffle_shop_duckdb report is a RE-measurement, and that is the point of it.**
Five defects in this tool were fixed on 2026-08-13, after that project's numbers
had already been published. Reasoning said the fixes could not have moved them —
they only add source shapes, read the warehouse path from the profile, and stop
counting models as tests. Reasoning is not measuring, and this is a repo whose
entire argument is that those are different things. So it was run again from a
fresh clone:

```
                     PUBLISHED    RE-MEASURED
  green tests               20             20
  dead canaries              0              0
  corruptions applied       37             37
  nothing caught            13             13
```

It reproduces exactly.

**`jaffle-shop-template` still has no raw report.** It was measured before this
folder existed and its artifact was not kept. Its numbers are reproducible from
the commands in `FINDINGS.md`, and re-running it needs an older dbt in its own
environment plus a withdrawn dependency removed. That gap is stated rather than
papered over.

**These are outputs, not fixtures.** Nothing reads them, no test depends on them,
and a report here is never treated as a current fact about a project: it is what
that project looked like on that date. `--recheck` exists precisely because a
measurement stops describing reality the moment the suite changes.
