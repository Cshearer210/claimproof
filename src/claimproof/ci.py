"""Ask the CI provider what it thinks, rather than believing the sentence.

"CI is green" is the claim furthest from its evidence in this whole library.
The evidence lives on somebody else's server, it changes after the reply is
written, and the person writing the sentence is usually going from what a
dashboard said several minutes ago. There is nothing in the text to check.

So this queries the real API and writes a receipt, and
`gates.CIStatusUnbacked` judges the sentence against that receipt. The split is
the same one `capture` and `evidence` use, for the same reason: a gate that
reaches the network cannot be proven in both directions offline, and a gate
that cannot be proven does not get trusted.

The query goes through the `gh` CLI when it is available. That is deliberate:
it means this library never handles anyone's token, and it inherits whatever
auth the developer already has working.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

__all__ = ["CiStatus", "UNKNOWN", "receipt", "gh_available", "query"]

#: What we say when we could not find out. Never "success" -- a lookup that
#: failed and a suite that passed produce the same silence otherwise, and only
#: one of them is good news.
UNKNOWN = "unknown"

#: Conclusions GitHub reports that mean the run really did pass.
_GOOD = {"success", "neutral", "skipped"}


@dataclass(frozen=True)
class CiStatus:
    repo: str
    ref: str
    conclusion: str
    total: int = 0
    failing: int = 0
    detail: str = ""

    @property
    def green(self) -> bool:
        return self.conclusion in _GOOD and self.failing == 0

    @property
    def known(self) -> bool:
        return self.conclusion != UNKNOWN


def receipt(status: CiStatus) -> str:
    """One line, the format `CIStatusUnbacked` reads back."""
    return "[claimproof:ci] %s %s@%s %d/%d failing" % (
        status.conclusion or UNKNOWN, status.repo or "?", status.ref or "?",
        status.failing, status.total)


def gh_available() -> bool:
    return shutil.which("gh") is not None


def query(repo: str, ref: str = "HEAD", timeout: int = 20) -> CiStatus:
    """Ask GitHub what the checks on `ref` actually concluded.

    Every failure path returns UNKNOWN rather than raising or guessing: no `gh`,
    not authenticated, no network, a repo that does not exist, a ref with no
    runs yet. The caller gets a status object either way and can tell the
    difference by asking `.known`.
    """
    if not gh_available():
        return CiStatus(repo, ref, UNKNOWN, detail="the gh CLI is not installed")
    try:
        proc = subprocess.run(
            ["gh", "api", "repos/%s/commits/%s/check-runs" % (repo, ref),
             "--jq", "{total: .total_count, runs: [.check_runs[] "
                     "| {name, status, conclusion}]}"],
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return CiStatus(repo, ref, UNKNOWN, detail=type(exc).__name__)

    if proc.returncode != 0:
        return CiStatus(repo, ref, UNKNOWN,
                        detail=(proc.stderr or "").strip().splitlines()[:1] and
                               (proc.stderr or "").strip().splitlines()[0][:120] or
                               "gh exited %d" % proc.returncode)
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        return CiStatus(repo, ref, UNKNOWN, detail="gh returned unparseable JSON")

    runs = data.get("runs") or []
    if not runs:
        return CiStatus(repo, ref, UNKNOWN, total=0,
                        detail="no check runs reported for this ref")

    pending = [r for r in runs if (r.get("status") or "") != "completed"]
    failing = [r for r in runs
               if (r.get("conclusion") or "") not in _GOOD
               and (r.get("status") or "") == "completed"]

    if pending:
        conclusion = "pending"
    elif failing:
        conclusion = "failure"
    else:
        conclusion = "success"

    return CiStatus(
        repo=repo, ref=ref, conclusion=conclusion,
        total=len(runs), failing=len(failing),
        detail=", ".join(str(r.get("name") or "?") for r in failing[:3]))


def selftest() -> None:
    """Prove the verdicts without touching the network.

    The parsing is the part that can be wrong, so the parsing is what is
    tested -- by calling `query` with a stubbed `subprocess.run`. A test that
    reached GitHub would prove the network works and nothing about this code.
    """
    import types

    def stub(payload, rc=0, stderr=""):
        def fake(*a, **k):
            return types.SimpleNamespace(
                returncode=rc, stdout=json.dumps(payload) if payload is not None else "",
                stderr=stderr)
        return fake

    real_run, real_which = subprocess.run, shutil.which
    shutil.which = lambda _n: "/usr/bin/gh"
    try:
        subprocess.run = stub({"total": 2, "runs": [
            {"name": "tests", "status": "completed", "conclusion": "success"},
            {"name": "lint", "status": "completed", "conclusion": "skipped"}]})
        s = query("o/r", "abc")
        assert s.green and s.conclusion == "success" and s.failing == 0, s
        assert receipt(s) == "[claimproof:ci] success o/r@abc 0/2 failing", receipt(s)

        subprocess.run = stub({"total": 2, "runs": [
            {"name": "tests", "status": "completed", "conclusion": "failure"},
            {"name": "lint", "status": "completed", "conclusion": "success"}]})
        s = query("o/r", "abc")
        assert not s.green and s.failing == 1 and "tests" in s.detail, s

        subprocess.run = stub({"total": 1, "runs": [
            {"name": "tests", "status": "in_progress", "conclusion": None}]})
        s = query("o/r", "abc")
        assert s.conclusion == "pending" and not s.green, s

        subprocess.run = stub({"total": 0, "runs": []})
        s = query("o/r", "abc")
        assert s.conclusion == UNKNOWN and not s.known and not s.green, s

        subprocess.run = stub(None, rc=1, stderr="gh: Not Found (HTTP 404)")
        s = query("o/nope", "abc")
        assert s.conclusion == UNKNOWN and "404" in s.detail, s

        shutil.which = lambda _n: None
        s = query("o/r", "abc")
        assert s.conclusion == UNKNOWN and "not installed" in s.detail, s
    finally:
        subprocess.run, shutil.which = real_run, real_which
    print("ci: selftest PASS (6 checks, incl. 3 that must NOT read as green)")


if __name__ == "__main__":
    selftest()
