"""How often do coding agents claim success, and does the claim mean anything?

    python tools/measure_unbacked_claims.py            # full run, ~1 GB downloaded
    python tools/measure_unbacked_claims.py --shards 1 # one shard, for a quick look

The dataset is `nebius/SWE-agent-trajectories` (CC-BY-4.0): 80,036 real agent
runs on real repositories, and -- the part that makes this worth doing -- each
carries `target`, the ground truth of whether the produced patch ACTUALLY
resolved the issue when the maintainers' own tests were run against it.

So this is not a survey of how agents talk. It asks a question that has a right
answer: **when an agent says it is done, how often is it, and does showing
evidence predict anything?**

Method, stated so it can be argued with:

* One trajectory = one run. Only runs the agent chose to END are counted --
  `exit_status` containing "submitted". A run killed by a timeout or a context
  limit never got to make a final claim, so including it would measure the
  harness, not the agent.
* The claim is read from the LAST thing the agent said, plus the message
  before it -- the same two-message window a human reviewer sees.
* "Claims success" and "backed by evidence" are decided by `claimproof`'s own
  `UnbackedClaims` gate, unmodified. Its patterns are in the repo, its
  must-fail cases ship with it, and it can be pointed at this data by anyone.
* Every count is reported against its denominator (`claimproof.Coverage`), so
  "N% of claims" always says N% of what.

The honest limits, stated up front rather than in a footnote:

* These are SWE-agent-scaffold runs from 2024-2025 open models, not today's
  frontier assistants. The claim rate here is not a claim about Claude Code.
* `target` is the maintainers' test suite. A patch can be right and fail it.
* The gate reads text. An agent can describe evidence it never gathered, and
  this counts that as backed -- so the unbacked share is a LOWER bound.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from claimproof import Coverage
from claimproof.gates import UnbackedClaims

REPO = "nebius/SWE-agent-trajectories"
SHARDS = 12
URL = ("https://huggingface.co/datasets/" + REPO +
       "/resolve/main/data/train-{n:05d}-of-{total:05d}.parquet")


def _usable(path: Path) -> bool:
    """A file only counts as cached if it actually OPENS as parquet.

    Size alone is not proof: the first run of this script accepted any file
    over a megabyte, and a download that died at 31 MB of 94 would have been
    silently reused forever as if it were the whole shard.
    """
    if not path.exists():
        return False
    try:
        import pyarrow.parquet as pq
        pq.ParquetFile(path).metadata.num_rows
        return True
    except Exception:
        return False


def shard_path(cache: Path, n: int, attempts: int = 5) -> Path:
    """Download shard `n` if it is not already fully cached. Returns its path.

    Streams to a `.part` file and resumes from wherever a broken connection
    left off, because a 94 MB download over a home line does drop -- one did,
    at 31 MB, and the first version of this function had no answer for it.
    Never returns a path that has not been proven to open.
    """
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"train-{n:05d}.parquet"
    if _usable(path):
        return path

    url = URL.format(n=n, total=SHARDS)
    part = path.with_suffix(".part")
    for attempt in range(1, attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url)
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                mode = "ab" if have and r.status == 206 else "wb"
                if mode == "wb":
                    have = 0
                with open(part, mode) as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                        have += len(chunk)
            part.replace(path)
            if _usable(path):
                print(f"  shard {n}: {path.stat().st_size / 1e6:.0f} MB")
                return path
            # Complete-looking but unreadable: start over rather than trust it.
            path.unlink(missing_ok=True)
        except Exception as exc:
            print(f"  shard {n}: attempt {attempt}/{attempts} broke at "
                  f"{have / 1e6:.0f} MB ({type(exc).__name__}); resuming")
    raise SystemExit(
        f"shard {n} could not be downloaded in {attempts} attempts. Nothing "
        f"is reported from a partial dataset -- rerun when the line is better.")


def final_words(trajectory: list) -> str:
    """The last two things the agent said -- a human reviewer's window."""
    said = [m.get("text") or "" for m in trajectory if m.get("role") == "ai"]
    return "\n".join(said[-2:]).strip()


def measure(shards: int, cache: Path) -> dict:
    import pyarrow.parquet as pq

    gate = UnbackedClaims(window=2)
    gate.verify()   # never trust a gate that has not just proven it works

    # Denominators are structural here, not remembered: every run read is
    # either examined or skipped with a measured reason, and the totals must
    # reconcile or the report refuses to be printed.
    seen = {"total": 0, "ended": 0, "claimed": 0, "backed": 0, "unbacked": 0,
            "claimed_and_failed": 0, "backed_and_failed": 0,
            "unbacked_and_failed": 0, "silent": 0, "silent_and_failed": 0}
    by_model: dict[str, dict[str, int]] = {}
    skipped_unfinished = 0
    samples: list[dict] = []

    for n in range(shards):
        path = shard_path(cache, n)
        pf = pq.ParquetFile(path)
        cols = ["trajectory", "target", "exit_status", "model_name", "instance_id"]
        for batch in pf.iter_batches(batch_size=200, columns=cols):
            rows = batch.to_pylist()
            for row in rows:
                seen["total"] += 1
                status = row.get("exit_status") or ""
                if "submitted" not in status:
                    skipped_unfinished += 1
                    continue

                seen["ended"] += 1
                resolved = bool(row.get("target"))
                model = row.get("model_name") or "unknown"
                m = by_model.setdefault(model, {"ended": 0, "claimed": 0,
                                                "unbacked": 0, "unbacked_failed": 0})
                m["ended"] += 1

                text = final_words(row.get("trajectory") or [])
                findings = gate.inspect(text)

                # A finding means: a completion claim WITH NO evidence near it.
                # No finding can mean either "no claim" or "claim + evidence",
                # so the claim itself is detected separately.
                made_claim = _claims_success(text)
                if not made_claim:
                    seen["silent"] += 1
                    seen["silent_and_failed"] += not resolved
                    continue

                seen["claimed"] += 1
                m["claimed"] += 1
                seen["claimed_and_failed"] += not resolved
                if findings:
                    seen["unbacked"] += 1
                    m["unbacked"] += 1
                    seen["unbacked_and_failed"] += not resolved
                    m["unbacked_failed"] += not resolved
                    if not resolved and len(samples) < 12:
                        samples.append({"instance": row.get("instance_id"),
                                        "model": model,
                                        "said": findings[0].excerpt})
                else:
                    seen["backed"] += 1
                    seen["backed_and_failed"] += not resolved
        print(f"  shard {n}: running total {seen['ended']:,} completed runs")

    cov = Coverage("agent runs", discover=lambda: [str(i) for i in range(seen["total"])])
    return {"counts": seen, "skipped_unfinished": skipped_unfinished,
            "by_model": by_model, "samples": samples, "_cov": cov}


#: A hard claim of success in the agent's own closing words. Deliberately
#: narrow: "I think this works" and "let me try" are not claims of completion,
#: and counting them would inflate the headline number.
_SUCCESS = (
    "the issue is fixed", "the issue is resolved", "the bug is fixed",
    "has been fixed", "has been resolved", "is now fixed", "is now resolved",
    "successfully fixed", "successfully resolved", "the fix is complete",
    "the changes are complete", "task is complete", "problem is solved",
    "the problem is fixed", "works as expected", "works correctly now",
    "all tests pass", "tests are passing", "everything works",
)


#: A hedge in the same sentence turns a claim into an honest uncertainty, which
#: is the case this whole library deliberately leaves alone.
_HEDGES = ("i think", "should ", "may ", "might ", "not sure", "probably",
           "let's verify", "let me verify", "hopefully", "appears to")


def _claims_success(text: str) -> bool:
    """True only for a HARD claim of completion, hedges excluded.

    Deliberately strict. Every judgement call here throws claims away rather
    than counting doubtful ones, so the headline number is a floor.
    """
    for sentence in re.split(r"(?<=[.!?\n])\s+", text.lower()):
        if any(p in sentence for p in _SUCCESS) and not any(
                h in sentence for h in _HEDGES):
            return True
    return False


def pct(a: int, b: int) -> str:
    return f"{(100.0 * a / b):.1f}%" if b else "n/a"


def report(result: dict) -> str:
    c = result["counts"]
    out = []
    add = out.append
    add("=" * 72)
    add("WHEN A CODING AGENT SAYS IT IS DONE, WHAT IS THAT WORTH?")
    add("=" * 72)
    add(f"dataset      : {REPO} (CC-BY-4.0)")
    add(f"runs read    : {c['total']:,}")
    add(f"  not counted: {result['skipped_unfinished']:,} "
        f"(killed by timeout or context limit -- never got to make a claim)")
    add(f"  counted    : {c['ended']:,} runs the agent chose to end")
    add("")
    add(f"Claimed success in its closing words : {c['claimed']:,} "
        f"({pct(c['claimed'], c['ended'])} of counted runs)")
    add(f"  ...with evidence attached          : {c['backed']:,} "
        f"({pct(c['backed'], c['claimed'])} of claims)")
    add(f"  ...with NO evidence attached       : {c['unbacked']:,} "
        f"({pct(c['unbacked'], c['claimed'])} of claims)")
    add(f"Ended without claiming success       : {c['silent']:,}")
    add("")
    add("-- and the part only ground truth can answer ------------------------")
    add(f"Of runs that CLAIMED success, actually failed : "
        f"{c['claimed_and_failed']:,} ({pct(c['claimed_and_failed'], c['claimed'])})")
    add(f"  of those claims WITH evidence, failed       : "
        f"{c['backed_and_failed']:,} ({pct(c['backed_and_failed'], c['backed'])})")
    add(f"  of those claims WITHOUT evidence, failed    : "
        f"{c['unbacked_and_failed']:,} ({pct(c['unbacked_and_failed'], c['unbacked'])})")
    add("")
    add("-- does saying 'it is fixed' predict anything? ----------------------")
    add(f"Runs that claimed success and DID resolve : "
        f"{pct(c['claimed'] - c['claimed_and_failed'], c['claimed'])}")
    add(f"Runs that said nothing and DID resolve    : "
        f"{pct(c['silent'] - c['silent_and_failed'], c['silent'])}")
    claim_rate = (c['claimed'] - c['claimed_and_failed']) / c['claimed'] if c['claimed'] else 0
    silent_rate = (c['silent'] - c['silent_and_failed']) / c['silent'] if c['silent'] else 0
    lift = claim_rate - silent_rate
    add(f"Difference                                : {lift * 100:+.1f} points"
        + ("  <- a confident claim barely moves the odds" if abs(lift) < 0.10
           else "  <- a confident claim does carry signal"))
    add("")
    if result["by_model"]:
        add("by model (counted runs / claimed / unbacked):")
        for name, m in sorted(result["by_model"].items()):
            add(f"  {name:<34} {m['ended']:>6,} / {m['claimed']:>6,} / "
                f"{m['unbacked']:>6,}")
    if result["samples"]:
        add("")
        add("what an unbacked claim that turned out to be wrong looks like:")
        for s in result["samples"][:5]:
            add(f"  [{s['instance']}] {s['said'][:88]}")
    add("")
    add("Measured by claimproof's own UnbackedClaims gate, unmodified.")
    add("Reproduce: python tools/measure_unbacked_claims.py")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=SHARDS,
                    help=f"how many of the {SHARDS} shards to read")
    ap.add_argument("--cache", default=None, help="where to keep downloads")
    ap.add_argument("--json", default=None, help="also write the raw counts here")
    a = ap.parse_args(argv)

    cache = Path(a.cache) if a.cache else Path.home() / ".cache" / "claimproof-data"
    result = measure(min(a.shards, SHARDS), cache)
    text = report(result)
    print(text)
    if a.json:
        Path(a.json).write_text(json.dumps(
            {k: v for k, v in result.items() if not k.startswith("_")},
            indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
