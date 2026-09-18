"""What the tools actually did, kept for the length of one turn.

`ExitCodeMismatch` can only check a sentence against a captured exit code if a
captured exit code is there to check against -- and a turn's own text almost
never carries one. The agent runs a command through the harness, the harness
reports the result, and by the time the reply is written the number is a
memory.

So the PostToolUse hook writes each real result here as it happens, and the
Stop hook reads them back before judging the reply. That is the whole reason
this file exists: to carry evidence across the gap between when a command runs
and when a claim about it is made.

The store is deliberately dumb -- one append-only text file per session, in the
OS temp directory. It holds no secrets (a receipt is a command line and an
integer), it expires on its own, and losing it costs a check rather than data.
"""
from __future__ import annotations

import os
import re
import tempfile
import time

__all__ = ["store_dir", "path_for", "record", "read", "clear", "prune"]

#: Beyond this, the oldest receipts are dropped. A turn that ran 400 commands
#: does not need all 400 to prove one claim, and an unbounded file in a temp
#: directory is somebody's disk-full incident later.
MAX_RECEIPTS = 200

#: Files older than this are other sessions' leftovers. Deleted on sight.
MAX_AGE_SECONDS = 24 * 60 * 60

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def store_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "claimproof-evidence")
    os.makedirs(d, exist_ok=True)
    return d


def path_for(session: str) -> str:
    """One file per session, named from the id with everything else stripped.

    The sanitising is not decoration: a session id arrives from someone else's
    runtime, and an id of `../../.bashrc` must become a filename, never a path.
    """
    safe = _SAFE.sub("_", str(session or "unknown"))[:120] or "unknown"
    return os.path.join(store_dir(), safe + ".receipts")


def record(session: str, line: str) -> None:
    """Append one receipt. Never raises -- a hook that dies takes the turn with it."""
    line = " ".join(str(line).split())
    if not line:
        return
    try:
        prune()
        p = path_for(session)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        existing = read(session)
        if len(existing) > MAX_RECEIPTS:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("\n".join(existing[-MAX_RECEIPTS:]) + "\n")
    except OSError:
        pass


def read(session: str) -> list[str]:
    """Every receipt recorded for this session, oldest first. [] if none."""
    try:
        with open(path_for(session), encoding="utf-8") as fh:
            return [l.strip() for l in fh if l.strip()]
    except OSError:
        return []


def clear(session: str) -> None:
    try:
        os.remove(path_for(session))
    except OSError:
        pass


def prune(now: float | None = None) -> int:
    """Delete other sessions' leftovers. Returns how many went."""
    now = time.time() if now is None else now
    gone = 0
    try:
        d = store_dir()
        for name in os.listdir(d):
            p = os.path.join(d, name)
            try:
                if now - os.path.getmtime(p) > MAX_AGE_SECONDS:
                    os.remove(p)
                    gone += 1
            except OSError:
                continue
    except OSError:
        pass
    return gone


def selftest() -> None:
    import uuid
    s = "test-" + uuid.uuid4().hex
    assert read(s) == [], "a fresh session must start empty"
    record(s, "[claimproof:exit] 0 pytest -q")
    record(s, "[claimproof:exit] 1 make build")
    assert read(s) == ["[claimproof:exit] 0 pytest -q",
                       "[claimproof:exit] 1 make build"], read(s)

    # a hostile id becomes a filename and never escapes the store
    evil = path_for("../../etc/passwd")
    assert os.path.dirname(evil) == store_dir(), evil

    # the cap holds
    big = "test-" + uuid.uuid4().hex
    for i in range(MAX_RECEIPTS + 25):
        record(big, "[claimproof:exit] 0 cmd%d" % i)
    assert len(read(big)) <= MAX_RECEIPTS, len(read(big))

    clear(s); clear(big)
    assert read(s) == [], "clear must actually remove it"
    print("evidence: selftest PASS (5 checks)")


if __name__ == "__main__":
    selftest()
