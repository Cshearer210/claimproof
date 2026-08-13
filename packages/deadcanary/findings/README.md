# The raw reports behind FINDINGS.md

`FINDINGS.md` says *"nothing here is an estimate"*. These are the receipts — the
report files the tool wrote itself, unedited, so anyone can check a number rather
than take the summary's word for it.

| File | Project | Headline |
|---|---|---|
| `chinook-2026-08-13.json` | `adityawarmanfw/dbt_duckdb_chinook` | 63 green tests, **0 dead canaries**, 182 of 255 applied corruptions caught by nothing |

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

**Why only one file so far.** The two dbt-labs projects were measured before this
folder existed, and their raw reports were not kept — the numbers in `FINDINGS.md`
are reproducible from the commands given there, but the original artifacts are
gone. That is a gap, stated rather than papered over. Any future measurement
lands here.

**These are outputs, not fixtures.** Nothing reads them, no test depends on them,
and a report here is never treated as a current fact about a project: it is what
that project looked like on that date. `--recheck` exists precisely because a
measurement stops describing reality the moment the suite changes.
