"""A finding stays RED until something proves it is gone. Prose has no state.

`Ledger` tracks what was ASKED. This tracks what was FOUND. They are different
failures and they need different stores: an ask is dropped by being forgotten,
a finding is dropped by being rediscovered forever and never closed.

WHY THIS EXISTS, measured on a real system before this was ported here: **590
findings written, 145 ever closed.** One secret went unrotated across 25
consecutive nightly reports, each of which correctly reported it. The detection
was excellent. Nothing closed, because each night's report was a fresh document
with no memory of the last one. A finding written as PROSE gets rediscovered
forever; a finding written as STATE either closes or is still on the board, and
there is no third option and nothing to remember.

THE HARD PART IS NOT RECORDING. IT IS ABSENCE.

When a gate stops reporting something, there are two reasons and they look
identical from outside:

    it was FIXED                      the defect is gone
    it was NOT LOOKED AT              the scope moved, the file was skipped,
                                      the gate was not run this time

Auto-closing on absence gets the first one right and silently loses the second,
which is how a register becomes a worse liar than no register at all. So
`reconcile()` takes the SCOPE that was actually examined, and closes only
findings that were inside it. Everything else stays red and is reported as
NOT RE-EXAMINED, in those words.

    reg = Register("problems.json")
    reg.record("unbacked-claims", gate.inspect(turn), scope="turn-41")
    ...
    reg.reconcile("unbacked-claims", gate.inspect(turn), scope="turn-41")
    reg.red()                      # what is still on the board
    reg.close("a1b2c3d4", "pytest: 7 passed, the claim now carries its receipt")

`StillRed` is the enforcement end, and it is deliberately the same shape as
`ledger.NothingLeft`: a Gate that refuses a claim of total cleanliness while
the register still holds red items.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from claimproof.core import Case, Finding, Gate, SelftestError
from claimproof.ledger import _BARE_CLAIMS, _locked, _now

__all__ = ["RegisterError", "Problem", "Register", "StillRed", "main",
           "RED", "FIXED", "ACCEPTED"]

RED = "red"
FIXED = "fixed"
ACCEPTED = "accepted"


class RegisterError(RuntimeError):
    """Raised when the register cannot honestly do what was asked of it."""


def _fingerprint(gate: str, message: str, excerpt: str) -> str:
    """A stable id for one defect, so finding it again is the SAME item.

    Without this every run creates new rows and the rediscovery count -- the
    single number that shows a register is not working -- can never rise above
    one. Line numbers are deliberately EXCLUDED: text above a defect shifts it
    down a line, and a defect that moved is not a new defect.
    """
    norm = re.sub(r"\s+", " ", f"{gate}|{message}|{excerpt}").strip().lower()
    # Digits are normalised out: "3 of 41 checked" and "3 of 44 checked" are one
    # defect whose denominator moved, not two.
    norm = re.sub(r"\d+", "#", norm)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]


@dataclass
class Problem:
    """One defect, and everything known about whether it is still there."""

    id: str
    gate: str
    message: str
    excerpt: str = ""
    scope: str = ""
    state: str = RED
    first_seen: str = ""
    last_seen: str = ""
    #: How many separate runs have reported this same defect. A high number on a
    #: red item is the shape this module exists to make visible.
    times_seen: int = 1
    evidence: str = ""
    reason: str = ""
    closed_at: str = ""

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Problem":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

    def line(self) -> str:
        again = f"  seen {self.times_seen}x" if self.times_seen > 1 else ""
        tail = f"\n        closed: {self.evidence or self.reason}" if self.closed_at else ""
        return (f"  {self.state:8s} {self.id}  [{self.gate}] {self.message[:70]}{again}"
                f"{tail}")


class Register:
    """The board a finding stays on until something proves it is gone.

    `path=None` keeps it in memory, for fixtures and tests. Real use wants a
    file: surviving the session that forgot is the entire point.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.problems: list[Problem] = []
        if self.path and self.path.exists():
            with _locked(self.path):
                self._read()

    # ----------------------------------------------------------- storage
    def _read(self) -> None:
        if not self.path or not self.path.exists():
            self.problems = []
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RegisterError(
                f"{self.path} is not valid JSON ({exc}). Refusing to start a "
                f"fresh register over what may be the only record of what is "
                f"still broken."
            ) from exc
        self.problems = [Problem.from_dict(p) for p in raw.get("problems", [])]

    def _write(self) -> None:
        """Temp file then rename, so a reader never sees a half-written board."""
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"problems": [p.as_dict() for p in self.problems]},
                             indent=2) + "\n"
        tmp = self.path.with_name(
            "%s.%d.%d.tmp" % (self.path.name, os.getpid(), threading.get_ident()))
        tmp.write_text(payload, encoding="utf-8")
        try:
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _critical(self):
        import contextlib

        @contextlib.contextmanager
        def _cm():
            if not self.path:
                yield
                return
            with _locked(self.path):
                self._read()
                yield
                self._write()

        return _cm()

    # --------------------------------------------------------- recording
    def record(self, gate: str, findings, scope: str = "") -> list[Problem]:
        """Put findings on the board. A repeat updates the row it already has.

        Returns the rows this call touched, new and repeated alike, so a caller
        can say how many of its findings were already known -- which is usually
        the more interesting number.
        """
        if not gate:
            raise RegisterError("a finding has to say which gate produced it")
        touched: list[Problem] = []
        with self._critical():
            by_id = {p.id: p for p in self.problems}
            for f in findings or []:
                msg = f.message if isinstance(f, Finding) else str(f)
                exc = f.excerpt if isinstance(f, Finding) else ""
                pid = _fingerprint(gate, msg, exc)
                existing = by_id.get(pid)
                if existing is None:
                    p = Problem(id=pid, gate=gate, message=msg, excerpt=exc,
                                scope=scope, first_seen=_now(), last_seen=_now())
                    self.problems.append(p)
                    by_id[pid] = p
                    touched.append(p)
                    continue
                existing.last_seen = _now()
                existing.times_seen += 1
                existing.scope = scope or existing.scope
                if existing.state != RED:
                    # It was closed and it is back. That is a REGRESSION, and
                    # leaving it closed is how a register starts lying.
                    existing.state = RED
                    existing.evidence = ""
                    existing.reason = ""
                    existing.closed_at = ""
                touched.append(existing)
        return touched

    def reconcile(self, gate: str, findings, scope: str) -> tuple[list[Problem], list[Problem]]:
        """Record this run, then close what this run proves is gone.

        Returns (closed, not_re_examined).

        ONLY rows whose scope matches `scope` can be closed by absence, because
        only those were actually looked at. Everything else stays red and comes
        back in the second list -- absent-and-fine and never-looked-at must not
        produce the same output, which is the rule this whole library is built
        on.
        """
        if not scope:
            raise RegisterError(
                "reconcile() needs the scope that was examined. Without it, a "
                "finding that vanished because nobody looked is indistinguishable "
                "from one that was fixed.")
        seen = {p.id for p in self.record(gate, findings, scope=scope)}
        closed: list[Problem] = []
        elsewhere: list[Problem] = []
        with self._critical():
            for p in self.problems:
                if p.state != RED or p.gate != gate:
                    continue
                if p.id in seen:
                    continue
                if p.scope == scope:
                    p.state, p.closed_at = FIXED, _now()
                    p.evidence = (f"re-inspected by {gate} over {scope!r} and no longer "
                                  f"found (seen {p.times_seen}x before this)")
                    closed.append(p)
                else:
                    elsewhere.append(p)
        return closed, elsewhere

    # ----------------------------------------------------------- closing
    def close(self, problem_id: str, evidence: str) -> Problem:
        """Close a problem by hand, with the evidence that proves it. No bare claims."""
        ev = (evidence or "").strip()
        if not ev:
            raise RegisterError(f"{problem_id}: closing needs evidence, none given")
        if ev.strip(".!").lower() in _BARE_CLAIMS:
            raise RegisterError(
                f"{problem_id}: {ev!r} is a claim, not evidence. Show what proves "
                f"it: output, an exit code, a test count, a path.")
        with self._critical():
            p = self._problem(problem_id)
            p.state, p.evidence, p.closed_at = FIXED, ev, _now()
            out = p
        return out

    def accept(self, problem_id: str, reason: str) -> Problem:
        """Leave a problem deliberately, on the record. The reason is required."""
        why = (reason or "").strip()
        if not why:
            raise RegisterError(
                f"{problem_id}: accepting a problem without a reason is a silent "
                f"drop wearing a decision's clothes")
        with self._critical():
            p = self._problem(problem_id)
            p.state, p.reason, p.closed_at = ACCEPTED, why, _now()
            out = p
        return out

    # ----------------------------------------------------------- reading
    def _problem(self, problem_id: str) -> Problem:
        for p in self.problems:
            if p.id == problem_id:
                return p
        raise RegisterError(f"no problem {problem_id!r} on the register")

    def red(self) -> list[Problem]:
        return [p for p in self.problems if p.state == RED]

    def rediscovered(self, at_least: int = 3) -> list[Problem]:
        """Red items reported this many times or more.

        The number that says the register is being written and not worked. On
        the system this was ported from it would have shown one item at 25.
        """
        return [p for p in self.red() if p.times_seen >= at_least]

    def report(self) -> str:
        if not self.problems:
            return "register empty: nothing has been recorded yet"
        red = self.red()
        lines = [p.line() for p in sorted(self.problems, key=lambda p: (p.state, p.id))]
        lines.append("")
        lines.append(f"{len(red)} red of {len(self.problems)} recorded")
        stuck = self.rediscovered()
        if stuck:
            lines.append(f"{len(stuck)} of those have been reported 3+ times and never "
                         f"closed -- detection is working and nothing is being fixed")
        return "\n".join(lines)

    def run(self, echo: bool = True) -> int:
        """0 nothing red, 1 something red. There is no third state to report here."""
        if echo:
            print(self.report())
        return 1 if self.red() else 0


# ------------------------------------------------------------------- the gate
#: A claim that everything found has been dealt with. Distinct from
#: `ledger._TOTAL_CLAIM`, which is about the ASKS: "all done" is a claim about
#: work, "no issues remain" is a claim about findings, and a turn can honestly
#: make one while the other is false.
_ALL_CLEAR = re.compile(
    r"\b(?:"
    r"no (?:issues?|problems?|findings?|defects?|errors?) (?:remain|are left|left)"
    r"|(?:all|every) (?:issues?|problems?|findings?) (?:are |were |have been )?"
    r"(?:fixed|resolved|closed|addressed|cleared)"
    r"|nothing (?:is )?(?:still )?(?:broken|outstanding|red)"
    r"|everything (?:is |was )?(?:clean|green|clear|resolved)"
    r"|(?:the )?(?:board|register|backlog) is (?:clean|clear|empty)"
    r"|all clear"
    r")\b", re.IGNORECASE)

#: A negation or hedge just before the phrase turns it into NOT a claim:
#: "not all issues are fixed", "once everything is clean", "almost all clear".
_HEDGED = re.compile(
    r"(?:\bnot\b|n't\b|\balmost\b|\bnearly\b|\buntil\b|\bbefore\b|\bonce\b|"
    r"\bwhen\b|\bif\b).{0,14}$", re.IGNORECASE)


class StillRed(Gate):
    """Refuse "everything is clean" while the register still holds red items.

    The selftest runs against a FIXTURE register with a known red item, never
    the live one. A register that happens to be empty today must not excuse a
    detector that can no longer detect -- the same reason `ledger.NothingLeft`
    overrides `verify()`, and the same override here.
    """

    name = "still-red"

    def __init__(self, register: Register) -> None:
        super().__init__()
        self.register = register

    def inspect(self, text: str) -> list[Finding]:
        red = self.register.red()
        if not red:
            return []
        out: list[Finding] = []
        for n, line in enumerate((text or "").splitlines(), 1):
            m = _ALL_CLEAR.search(line)
            if not m or _HEDGED.search(line[:m.start()]):
                continue
            shown = "; ".join(f"{p.id}: {p.message[:44]}" for p in red[:3])
            more = f" (+{len(red) - 3} more)" if len(red) > 3 else ""
            out.append(Finding(
                message=(f"claims everything is clean, but {len(red)} finding(s) are "
                         f"still red -- {shown}{more}"),
                line=n, excerpt=line.strip()[:80]))
        return out

    def selftest_cases(self) -> list[Case]:
        """Empty on purpose -- the real cases run in `verify()` against a fixture.

        The base contract would run whatever is returned here against the LIVE
        register, where a must-flag case is only valid while something happens
        to be red.
        """
        return []

    def verify(self) -> list[str]:
        fixture = Register()
        fixture.record("fixture-gate",
                       [Finding("a claim with no receipt", line=3, excerpt="all tests pass")],
                       scope="fixture")

        # Built from `type(self)`, NEVER from the class named here. Writing
        # `class _Probe(StillRed)` makes a SUBCLASS that overrides `inspect`
        # verify the PARENT's behaviour and report itself proven -- a false pass
        # inside the gate whose whole job is refusing those. Found 2026-09-17 by
        # a test that tried to mutate this gate and could not.
        class _Probe(type(self)):       # type: ignore[misc]
            verify = Gate.verify        # the base contract, so the cases really run

            def selftest_cases(self) -> list[Case]:
                return [
                    Case("All clear.", True, "total clean claim with something red"),
                    Case("Everything is green now.", True, "another wording"),
                    Case("All issues are fixed.", True, "claims the findings are gone"),
                    Case("Fixed the first finding; the other is still open.",
                         False, "closing one is not claiming all"),
                    Case("Not everything is clean yet.", False, "negated"),
                    Case("Once everything is clean I will ship.", False, "conditional"),
                    Case("", False, "empty"),
                ]

        checked = _Probe(fixture).verify()

        clean = Register()
        if StillRed(clean).inspect("All clear."):
            raise SelftestError(
                f"{self.name}: flagged 'All clear.' against a register with nothing "
                f"red -- a true claim must never be refused")
        return checked + ["true all-clear on an empty register is left alone"]


# ---------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="claimproof register",
        description="Findings stay red until something proves they are gone.")
    ap.add_argument("--file", default="problems.json", help="where the board lives")
    ap.add_argument("--close", nargs=2, metavar=("ID", "EVIDENCE"))
    ap.add_argument("--accept", nargs=2, metavar=("ID", "REASON"))
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    reg = Register(a.file)
    try:
        if a.close:
            print(reg.close(a.close[0], a.close[1]).line())
            return 0
        if a.accept:
            print(reg.accept(a.accept[0], a.accept[1]).line())
            return 0
    except RegisterError as exc:
        print(f"refused: {exc}")
        return 1
    return reg.run(echo=not a.quiet)


# --------------------------------------------------------------- selftest
def selftest() -> int:
    """Prove the register in both directions, against fixtures only."""
    fails: list[str] = []
    f = lambda m, e="": Finding(m, excerpt=e)                      # noqa: E731

    # 1. The same defect found twice is ONE row, and the count rises.
    r = Register()
    r.record("g", [f("a claim with no receipt", "all tests pass")], scope="s")
    r.record("g", [f("a claim with no receipt", "all tests pass")], scope="s")
    if len(r.problems) != 1:
        fails.append(f"the same defect twice made {len(r.problems)} rows, not 1")
    elif r.problems[0].times_seen != 2:
        fails.append(f"times_seen is {r.problems[0].times_seen}, not 2")

    # 2. A line number moving does not create a second row.
    r2 = Register()
    r2.record("g", [Finding("x", line=3, excerpt="e")], scope="s")
    r2.record("g", [Finding("x", line=99, excerpt="e")], scope="s")
    if len(r2.problems) != 1:
        fails.append("the same defect on a different line was recorded as a new problem")

    # 3. reconcile CLOSES what is gone from the scope it examined...
    r3 = Register()
    r3.record("g", [f("one"), f("two")], scope="turn-1")
    closed, elsewhere = r3.reconcile("g", [f("two")], scope="turn-1")
    if len(closed) != 1 or closed[0].message != "one":
        fails.append(f"reconcile closed {[c.message for c in closed]}, expected ['one']")
    if len(r3.red()) != 1:
        fails.append(f"{len(r3.red())} red after reconcile, expected 1")

    # 4. ...and NEVER closes what it did not look at. This is the whole point.
    r4 = Register()
    r4.record("g", [f("in scope")], scope="turn-1")
    r4.record("g", [f("other scope")], scope="turn-2")
    closed, elsewhere = r4.reconcile("g", [], scope="turn-1")
    if [c.message for c in closed] != ["in scope"]:
        fails.append(f"reconcile closed {[c.message for c in closed]}, expected ['in scope']")
    if [e.message for e in elsewhere] != ["other scope"]:
        fails.append("a finding outside the examined scope was not reported as "
                     "not-re-examined")
    if len(r4.red()) != 1:
        fails.append("a finding outside the examined scope was closed by absence")

    # 5. reconcile without a scope is refused rather than guessed at.
    try:
        Register().reconcile("g", [], scope="")
        fails.append("reconcile() accepted an empty scope")
    except RegisterError:
        pass

    # 6. A closed finding that comes back goes red again.
    r6 = Register()
    r6.record("g", [f("regression")], scope="s")
    r6.close(r6.problems[0].id, "pytest: 12 passed, the receipt is attached")
    r6.record("g", [f("regression")], scope="s")
    if r6.problems[0].state != RED:
        fails.append("a closed finding that reappeared did not go red again")
    if r6.problems[0].evidence:
        fails.append("a reopened finding kept the evidence that closed it")

    # 7. Closing refuses a bare claim and requires evidence.
    r7 = Register()
    r7.record("g", [f("needs proof")], scope="s")
    pid = r7.problems[0].id
    for bad in ("", "   ", "fixed", "done."):
        try:
            r7.close(pid, bad)
            fails.append(f"close() accepted {bad!r} as evidence")
        except RegisterError:
            pass
    r7.close(pid, "exit=0 and the output shows 0 findings")
    if r7.red():
        fails.append("a problem closed with real evidence stayed red")

    # 8. accept() requires a reason.
    r8 = Register()
    r8.record("g", [f("known and deliberate")], scope="s")
    try:
        r8.accept(r8.problems[0].id, "  ")
        fails.append("accept() allowed a silent drop with no reason")
    except RegisterError:
        pass

    # 9. rediscovered() surfaces the item nobody is fixing.
    r9 = Register()
    for _ in range(4):
        r9.record("g", [f("never fixed")], scope="s")
    if len(r9.rediscovered()) != 1:
        fails.append("an item reported 4 times was not surfaced as rediscovered")
    if r9.rediscovered(at_least=9):
        fails.append("rediscovered(at_least=9) surfaced an item seen 4 times")

    # 10. The gate, both directions, against fixtures (verify() does this itself).
    try:
        StillRed(Register()).verify()
    except SelftestError as exc:
        fails.append(f"StillRed could not prove itself: {exc}")

    # 11. On-disk state really survives a new object -- the entire premise.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "problems.json"
        a = Register(p)
        a.record("g", [f("survives a restart")], scope="s")
        b = Register(p)
        if len(b.red()) != 1:
            fails.append("the register did not survive being reopened from disk")
        if b.red() and b.red()[0].id != a.problems[0].id:
            fails.append("the id changed across a reload, so a repeat would make a new row")

    for x in fails:
        print("  FAIL " + x)
    if not fails:
        print("  ok:   one row per defect, absence closes only what was examined, "
              "a reopened finding goes red, evidence is required, the gate proves itself")
    print("claimproof.register selftest: %s" % ("PASS" if not fails else "FAIL"))
    return 1 if fails else 0


if __name__ == "__main__":   # pragma: no cover - module entry
    raise SystemExit(main())
