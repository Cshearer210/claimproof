"""No silent drops: every ask is recorded, and "all done" is checked against the list.

The most universal agent failure is not a wrong answer. It is request six of
eight quietly never happening. The user asks for several things across a long
session; the early ones get done, one falls out of the context window or is
simply forgotten, and the session signs off with "everything is finished."
Nothing in the loop disagrees, because nothing in the loop was keeping the
list. The claim is fluent, confident, and false, and nobody finds out until
the missing thing matters.

The failure that shaped this, measured on a real system: a capture layer had
recorded 1,318 user requests verbatim -- and not one had ever been turned into
a tracked item, so every completion check ran against an empty list and
passed. Recording is not tracking. Tracking is not closing. This module makes
each step explicit:

* **Asks are recorded verbatim**, not summarized. A paraphrase is where the
  third request in a compound message goes to die.
* **Closing an item requires evidence.** Not a promise, not "done" -- the
  ledger refuses bare claim-words as evidence. It cannot judge whether your
  evidence is good; it can refuse the laziest non-answers and record the rest
  for a human or a `Gate` to judge.
* **Skipping is honest and loud.** An item you decided not to do carries its
  reason. Dropping it with no reason recorded is the exact failure this
  module exists to prevent.
* **Nothing auto-closes.** Not on exit, not on a timer, not on a new session.
  State lives in a file so it survives the context window that forgot it.

`NothingLeft` is the enforcement end: a `Gate` that reads a reply and flags a
claim of total completion -- "all done", "everything is finished", "nothing
left" -- while the ledger still holds open items. A claim about one item
("done with the parser fix") is left alone; finishing one thing is not a claim
that everything is finished. Like every gate in this library it must prove it
can catch its own bad case before its verdict counts for anything, and it
proves that against a fixture ledger so a clean live ledger cannot excuse a
broken detector.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from claimproof.core import Case, Finding, Gate, SelftestError

__all__ = ["LedgerError", "Item", "Ask", "Ledger", "NothingLeft", "main"]

#: How long to wait for another agent to finish with the ledger, in seconds.
#: Generous: the critical section is a few milliseconds of file I/O, so anything
#: approaching this means a crashed holder, which the stale-lock rule handles.
_LOCK_TIMEOUT = 10.0
#: A lock older than this is assumed to belong to a process that died. Without
#: this rule, one crash makes the ledger permanently unusable -- and a tracker
#: nobody can write to is worse than no tracker.
_LOCK_STALE_AFTER = 30.0


@contextlib.contextmanager
def _locked(path: Path):
    """Hold an exclusive lock on `path` for the duration of the block.

    Multi-agent tracking is this module's whole purpose, so two agents on one
    ledger is the NORMAL case, not the exotic one. Measured 2026-08-07 with
    four concurrent writers on Windows: without this, three of them died with
    PermissionError and one left the file unreadable. POSIX was fine, which is
    exactly how a bug like this ships -- it is invisible on the developer's
    machine and breaks on half the users' machines.

    Implemented with an atomic O_EXCL create rather than fcntl or msvcrt: those
    are per-platform, and this needs one behaviour on both. A stale lock is
    broken after `_LOCK_STALE_AFTER` so a crashed agent cannot wedge the
    ledger forever.
    """
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        # PermissionError belongs here, not in an outer handler: on Windows a
        # file in the "delete pending" state -- the instant between another
        # holder unlinking it and the OS finishing -- refuses to be opened with
        # errno 13 rather than "already exists". Treating that as a hard
        # failure makes the ledger randomly unwritable under exactly the
        # concurrency it is for, which is how the first version of this failed.
        except (FileExistsError, PermissionError):
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0            # it vanished; loop and take it
            if age > _LOCK_STALE_AFTER:
                # The holder is gone. Say so out loud rather than silently
                # stealing it: a stolen lock can mean a lost write.
                print("claimproof: breaking a stale ledger lock (%.0fs old) on %s"
                      % (age, lock), file=sys.stderr)
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() > deadline:
                raise LedgerError(
                    f"another agent held {path} for more than {_LOCK_TIMEOUT:.0f}s. "
                    f"Nothing was written and the ledger is unchanged.")
            time.sleep(0.01)
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


#: Words the ledger refuses as evidence on their own. This is not a judgment
#: of evidence quality -- it is the floor below which nothing was even offered.
_BARE_CLAIMS = {"done", "finished", "complete", "completed", "fixed", "works",
                "working", "yes", "ok", "okay", "good", "verified", "passed"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LedgerError(RuntimeError):
    """Raised when the ledger cannot honestly do what was asked of it."""


@dataclass
class Item:
    """One trackable piece of one ask."""

    id: str
    text: str
    status: str = "open"          # open | done | skipped
    evidence: str = ""            # done only
    reason: str = ""              # skipped only
    closed_at: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "status": self.status,
                "evidence": self.evidence, "reason": self.reason,
                "closed_at": self.closed_at}

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        return cls(id=str(d["id"]), text=str(d["text"]),
                   status=str(d.get("status", "open")),
                   evidence=str(d.get("evidence", "")),
                   reason=str(d.get("reason", "")),
                   closed_at=str(d.get("closed_at", "")))


@dataclass
class Ask:
    """One request, exactly as it was made."""

    id: int
    text: str                     # verbatim, never a summary
    when: str
    items: list[Item] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "when": self.when,
                "items": [i.as_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, d: dict) -> "Ask":
        return cls(id=int(d["id"]), text=str(d["text"]), when=str(d.get("when", "")),
                   items=[Item.from_dict(i) for i in d.get("items", [])])


class Ledger:
    """The list an "all done" claim gets checked against.

    `path=None` keeps the ledger in memory -- for tests and fixtures. Real use
    wants a file: the whole point is surviving the session that forgot.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.asks: list[Ask] = []
        if self.path and self.path.exists():
            with _locked(self.path):
                self._read()

    def _read(self) -> None:
        """Load from disk. The caller holds the lock."""
        if not self.path or not self.path.exists():
            self.asks = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise LedgerError(
                f"{self.path} is not valid JSON ({exc}). Refusing to start a "
                f"fresh ledger over what may be the only record of the asks."
            ) from exc
        self.asks = [Ask.from_dict(a) for a in raw.get("asks", [])]

    # ------------------------------------------------------------- recording
    def ask(self, text: str) -> Ask:
        """Record one request verbatim. Returns the ask, already one open item.

        The item can be split later; until then the ask tracks as itself, so a
        request that never gets broken down still cannot be silently dropped.
        """
        text = (text or "").strip()
        if not text:
            raise LedgerError("an empty ask cannot be tracked")

        # Re-read inside the lock before appending. Without this, two agents
        # that both loaded the ledger a second ago each write their own copy
        # and the later one silently erases the earlier one's ask -- which is
        # precisely the "requests quietly disappear" failure this module was
        # built to end, reintroduced by its own storage layer.
        with self._critical():
            ask = Ask(id=len(self.asks) + 1, text=text, when=_now())
            ask.items.append(Item(id=f"{ask.id}a", text=text))
            self.asks.append(ask)
            self._write()
        return ask

    @contextlib.contextmanager
    def _critical(self):
        """Lock, refresh from disk, run the block, write. In-memory: just run."""
        if not self.path:
            yield
            return
        with _locked(self.path):
            self._read()
            yield
            self._write()

    def split(self, ask_id: int, *parts: str) -> list[Item]:
        """Replace an ask's unstarted auto-item with named pieces.

        Refused once work on the ask has been recorded -- rewriting history
        under closed items would detach their evidence from what it proved.
        """
        ask = self._ask(ask_id)
        if not parts:
            raise LedgerError("split needs at least one part")
        if any(i.status != "open" for i in ask.items):
            raise LedgerError(
                f"ask {ask_id} already has closed items; add asks instead of "
                f"rewriting a list that evidence already points into")
        letters = "abcdefghijklmnopqrstuvwxyz"
        if len(parts) > len(letters):
            raise LedgerError("more parts than this ledger can label")
        with self._critical():
            ask = self._ask(ask_id)          # re-fetch: _read replaced the objects
            ask.items = [Item(id=f"{ask_id}{letters[n]}", text=p.strip())
                         for n, p in enumerate(parts) if p.strip()]
            items = list(ask.items)
        return items

    # --------------------------------------------------------------- closing
    def done(self, item_id: str, evidence: str) -> Item:
        """Close an item with the evidence that proves it. Refuses bare claims."""
        item = self._item(item_id)
        ev = (evidence or "").strip()
        if not ev:
            raise LedgerError(f"item {item_id}: closing needs evidence, none given")
        if ev.strip(".!").lower() in _BARE_CLAIMS:
            raise LedgerError(
                f"item {item_id}: {ev!r} is a claim, not evidence. Show what "
                f"proves it: output, an exit code, a test count, a path.")
        with self._critical():
            item = self._item(item_id)       # re-fetch after the refresh
            item.status, item.evidence, item.closed_at = "done", ev, _now()
            closed = item
        return closed

    def skip(self, item_id: str, reason: str) -> Item:
        """Decline an item, on the record. The reason is required."""
        item = self._item(item_id)
        why = (reason or "").strip()
        if not why:
            raise LedgerError(
                f"item {item_id}: skipping without a reason is a silent drop, "
                f"which is the exact thing this ledger exists to prevent")
        with self._critical():
            item = self._item(item_id)       # re-fetch after the refresh
            item.status, item.reason, item.closed_at = "skipped", why, _now()
            closed = item
        return closed

    # --------------------------------------------------------------- reading
    def open_items(self) -> list[Item]:
        return [i for a in self.asks for i in a.items if i.status == "open"]

    def report(self) -> str:
        if not self.asks:
            return "ledger empty: no asks recorded"
        lines = []
        for ask in self.asks:
            lines.append(f"ask {ask.id}: {ask.text}")
            for i in ask.items:
                mark = {"open": "[ ]", "done": "[x]", "skipped": "[-]"}[i.status]
                tail = ""
                if i.status == "done":
                    tail = f"  <- {i.evidence}"
                elif i.status == "skipped":
                    tail = f"  <- skipped: {i.reason}"
                lines.append(f"  {mark} {i.id}: {i.text}{tail}")
        open_ = self.open_items()
        lines.append(f"{len(open_)} open, of "
                     f"{sum(len(a.items) for a in self.asks)} item(s) total")
        return "\n".join(lines)

    def run(self) -> int:
        """Print the report. Exit 1 while anything is open, 0 when nothing is."""
        print(self.report())
        return 1 if self.open_items() else 0

    # -------------------------------------------------------------- plumbing
    def _ask(self, ask_id: int) -> Ask:
        for a in self.asks:
            if a.id == int(ask_id):
                return a
        raise LedgerError(f"no ask {ask_id!r} in this ledger")

    def _item(self, item_id: str) -> Item:
        for a in self.asks:
            for i in a.items:
                if i.id == str(item_id):
                    return i
        raise LedgerError(f"no item {item_id!r} in this ledger")

    def _write(self) -> None:
        """Write the ledger so a reader never sees it half-written.

        Found 2026-08-07 by four threads writing one ledger: the plain
        write truncates the file and then fills it, so a concurrent reader hit
        an empty file and got "Expecting value: line 1 column 1", which this
        class correctly refuses to start fresh over -- meaning a second agent
        could not open the ledger at all until the first finished.

        The fix is to write a sibling temp file and then RENAME it over the
        target: on both POSIX and Windows a rename is atomic, so a reader sees
        either the whole old file or the whole new one, never a torn one.

        The honest limit, stated rather than pretended away: this makes the
        file always READABLE, not the updates transactional. Two agents
        appending at the same moment still race, and the last writer wins.
        Serialising them needs a lock, which is a bigger decision than this
        class should make for its callers.
        """
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"asks": [a.as_dict() for a in self.asks]},
                             indent=2) + "\n"
        # The temp name carries the process AND thread id: two writers sharing
        # one temp file would corrupt each other's, which is the bug this whole
        # method exists to remove.
        tmp = self.path.with_name(
            "%s.%d.%d.tmp" % (self.path.name, os.getpid(),
                              threading.get_ident()))
        tmp.write_text(payload, encoding="utf-8")
        try:
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)   # never leave litter behind a failure
            raise


# ------------------------------------------------------------------- the gate
#: A claim that EVERYTHING is finished. One item being done is not that claim,
#: which is why these are total-phrases rather than the word "done".
_TOTAL_CLAIM = re.compile(
    r"\b(?:"
    r"all (?:done|finished|complete|tasks? (?:are )?(?:done|complete[d]?))"
    r"|everything (?:is |looks )?(?:done|finished|complete[d]?|working)"
    r"|nothing (?:left|remaining|else) (?:to do|to fix)?"
    r"|finished everything"
    r"|wrapped (?:it all|everything) up"
    r")\b", re.IGNORECASE)

#: A negation or hedge within a few words before the match turns it into NOT a
#: total claim: "not all done yet", "almost all done", "once everything is done".
_NEGATED = re.compile(
    r"(?:\bnot\b|n't\b|\balmost\b|\bnearly\b|\buntil\b|\bbefore\b|\bonce\b).{0,12}$",
    re.IGNORECASE)


class NothingLeft(Gate):
    """Refuse "all done" while the ledger still holds open items.

    The gate's selftest runs against a FIXTURE ledger with a known open item,
    never the live one -- a clean live ledger must not excuse a detector that
    can no longer detect. The live ledger is only consulted by `inspect()`.
    """

    name = "nothing-left"

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self.ledger = ledger

    def inspect(self, text: str) -> list[Finding]:
        open_items = self.ledger.open_items()
        findings: list[Finding] = []
        for n, line in enumerate((text or "").splitlines(), 1):
            m = _TOTAL_CLAIM.search(line)
            if not m or not open_items:
                continue
            if _NEGATED.search(line[:m.start()]):
                continue
            shown = "; ".join(f"{i.id}: {i.text[:50]}" for i in open_items[:3])
            more = f" (+{len(open_items) - 3} more)" if len(open_items) > 3 else ""
            findings.append(Finding(
                message=(f"claims everything is finished, but {len(open_items)} "
                         f"item(s) are open -- {shown}{more}"),
                line=n, excerpt=line.strip()[:80]))
        return findings

    def selftest_cases(self) -> list[Case]:
        """The cases live in `verify()`, against a fixture ledger.

        The base contract would run whatever is returned here against the LIVE
        ledger, where the must-flag case is only valid while something happens
        to be open. A detector must prove itself regardless of today's state,
        so `verify()` is overridden instead and this returns nothing.
        """
        return []

    def verify(self) -> list[str]:
        """Prove the detector against fixtures, whatever the live ledger says."""
        fixture = Ledger()
        fixture.ask("fix the parser")
        fixture.ask("update the changelog")
        fixture.done("1a", "pytest: 56 passed")

        class _Probe(NothingLeft):
            verify = Gate.verify  # the base contract, so cases actually run

            def selftest_cases(self) -> list[Case]:
                return [
                    Case("All done.", True, "total claim with an item open"),
                    Case("Everything is finished, wrapping up.", True,
                         "total claim mid-sentence"),
                    Case("Nothing left to do.", True,
                         "nothing-left with an item open"),
                    Case("Done with the parser fix; the changelog is next.",
                         False, "one item is not everything"),
                    Case("Almost all done.", False, "hedged is not a total claim"),
                    Case("Not all done yet.", False, "negated is not a total claim"),
                    Case("", False, "empty"),
                ]

        checked = _Probe(fixture).verify()

        clean = Ledger()
        clean.ask("only ask")
        clean.done("1a", "exit=0, output shown")
        if NothingLeft(clean).inspect("All done."):
            raise SelftestError(
                f"{self.name}: flagged 'All done.' against a ledger with "
                f"nothing open -- a true claim must never be refused")
        return checked + ["true total claim on a clean ledger is left alone"]


# ---------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m claimproof.ledger",
        description="Record asks, close them with evidence, and check "
                    "'all done' against the list.")
    ap.add_argument("--file", default="ledger.json", help="ledger path")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("show")
    p = sub.add_parser("ask"); p.add_argument("text")
    p = sub.add_parser("split"); p.add_argument("ask_id", type=int)
    p.add_argument("parts", nargs="+")
    p = sub.add_parser("done"); p.add_argument("item_id"); p.add_argument("evidence")
    p = sub.add_parser("skip"); p.add_argument("item_id"); p.add_argument("reason")
    sub.add_parser("gate", help="read a reply on stdin; exit 2 if it claims "
                                "total completion the ledger disagrees with")
    args = ap.parse_args(argv)

    led = Ledger(args.file)
    try:
        if args.cmd == "ask":
            a = led.ask(args.text)
            print(f"recorded ask {a.id} ({a.items[0].id} open)")
        elif args.cmd == "split":
            items = led.split(args.ask_id, *args.parts)
            print("\n".join(f"open {i.id}: {i.text}" for i in items))
        elif args.cmd == "done":
            i = led.done(args.item_id, args.evidence)
            print(f"closed {i.id} <- {i.evidence}")
        elif args.cmd == "skip":
            i = led.skip(args.item_id, args.reason)
            print(f"skipped {i.id} <- {i.reason}")
        elif args.cmd == "gate":
            findings = NothingLeft(led).check(sys.stdin.read())
            if findings:
                for f in findings:
                    print(f"  x {f}", file=sys.stderr)
                return 2
            return 0
        else:
            return led.run()
    except LedgerError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
