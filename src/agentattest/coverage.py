"""A count is not a result until it says what it did not look at.

    "22 nodes, 0 broken"

reads as *the system is healthy*. It means *the 22 I chose are healthy*. Those are
different sentences and only one of them is supported by the work that was done.

The failure this comes from, measured: one tool discovered 685,507 files. Another
written the same day walked its own hand-typed list of places to look, opened
57,100, and that was reported as "every file." **The gap was 628,407 files and
nothing could notice**, because a scan of 4 roots prints the same shape of output
as a scan of 40. Completeness was capped by what the author already knew about
the system, which is the thing the scan existed to establish.

So `Coverage` makes the denominator structural rather than something you remember
to mention:

    cov = Coverage("services", discover=list_services)

    for name in cov.population():
        if name.startswith("legacy-"):
            cov.skip(name, "retired in 2024", measured=0)
            continue
        cov.examine(name, *health_of(name))

    print(cov.report())
    raise SystemExit(cov.run())

Four rules, each of which is otherwise a way of reporting success while proving
nothing:

1. **The population is discovered, never typed.** `discover` is a callable and a
   list is refused, so the population is re-established on every run and something
   that appears next month is in scope without anyone remembering it.
2. **No exclusion without a measurement.** "it's a cache" is a guess; "606 files"
   is a finding. A `skip()` with no `measured=` reports UNKNOWN, never a pass.
   `measured=0` is a measurement. Omitting it is not.
3. **Reconcile, and print it.** examined + skipped + unaccounted == discovered.
   Anything unaccounted is UNKNOWN and exits 2, because unexamined is not the same
   as fine.
4. **Persist and diff.** NEW and GONE are reported, so a member that appears next
   month surfaces itself instead of waiting to be stumbled on.

**The honest limit**, stated because the whole point is not overclaiming: this
stops a tool *silently* narrowing its own scope, and it forces the fraction into
every report. It cannot guarantee your `discover` function is complete. Nothing
can. `agentattest.gates.TypedScope` catches the most common way it goes wrong --
a literal list of paths hardcoded where the population should be -- and that is
the limit of what a library can do from here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

__all__ = ["CoverageError", "Entry", "Diff", "Coverage"]

EXAMINED = "examined"
SKIPPED = "skipped"


class CoverageError(RuntimeError):
    """Raised when a coverage report would be misleading. Never caught internally."""


@dataclass(frozen=True)
class Entry:
    """One member of the population and what was done about it."""

    item: str
    status: str                      # EXAMINED | SKIPPED
    verdict: bool | None = None      # examined only: True ok, False broke, None unknown
    detail: str = ""
    reason: str = ""                 # skipped only: why it left scope
    measured: int | None = None      # how big the thing is. None means nobody looked.

    @property
    def is_broke(self) -> bool:
        return self.status == EXAMINED and self.verdict is False

    @property
    def is_unknown(self) -> bool:
        if self.status == EXAMINED:
            return self.verdict is None
        return self.measured is None   # an unmeasured exclusion is a guess

    def as_dict(self) -> dict:
        return {"item": self.item, "status": self.status, "verdict": self.verdict,
                "detail": self.detail, "reason": self.reason, "measured": self.measured}

    @classmethod
    def from_dict(cls, d: dict) -> "Entry":
        return cls(item=str(d["item"]), status=str(d["status"]), verdict=d.get("verdict"),
                   detail=str(d.get("detail", "")), reason=str(d.get("reason", "")),
                   measured=d.get("measured"))


@dataclass(frozen=True)
class Diff:
    """What changed in the POPULATION since last time, not in the findings."""

    appeared: tuple[str, ...] = ()
    vanished: tuple[str, ...] = ()
    grew: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.appeared or self.vanished or self.grew)

    def report(self) -> str:
        lines = [f"  NEW since last run  : {len(self.appeared)}"]
        lines += [f"    + {p}" for p in self.appeared]
        lines.append(f"  GONE since last run : {len(self.vanished)}")
        lines += [f"    - {p}" for p in self.vanished]
        lines.append(f"  GREW                : {len(self.grew)}")
        lines += [f"    ^ {p}" for p in self.grew]
        return "\n".join(lines)


class Coverage:
    """Track what was looked at, out of what, and refuse to lose the denominator.

    `what` is the plural noun for one member of the population -- "services",
    "files", "customer accounts". It is used in the report, so write it the way
    you would say it out loud.
    """

    def __init__(self, what: str, discover: Callable[[], Iterable[str]]) -> None:
        if not callable(discover):
            # The whole failure this class exists for is a population someone
            # typed once. A list cannot be re-established on the next run, so
            # something that appears next month is silently out of scope forever.
            raise CoverageError(
                f"discover must be a CALLABLE that finds the population, not a "
                f"{type(discover).__name__}. A list written down once can only "
                f"contain what somebody already thought of, and it is exactly how "
                f"a scan of 4 places gets reported as a scan of 40. Pass a function."
            )
        self.what = what
        self._discover = discover
        self._population: tuple[str, ...] | None = None
        self._entries: dict[str, Entry] = {}

    # ---------------------------------------------------------- population
    def population(self, refresh: bool = False) -> tuple[str, ...]:
        """The full population, discovered. Cached within a run so the
        denominator cannot change halfway through a report."""
        if self._population is None or refresh:
            found = tuple(dict.fromkeys(str(x) for x in self._discover()))
            if not found:
                raise CoverageError(
                    f"discovering {self.what} returned nothing. Refusing to report "
                    f"coverage over an empty population: 0 of 0 examined reads as a "
                    f"clean result and proves nothing at all."
                )
            self._population = found
        return self._population

    def __len__(self) -> int:
        return len(self.population())

    # ------------------------------------------------------------ recording
    def _accept(self, item: str) -> str:
        name = str(item)
        if name not in self.population():
            raise CoverageError(
                f"{name!r} is not in the discovered population of {self.what}. "
                f"Recording it would make the fraction meaningless -- the "
                f"numerator would count something the denominator never included."
            )
        if name in self._entries:
            raise CoverageError(f"{name!r} was already recorded as "
                                f"{self._entries[name].status}")
        return name

    def examine(self, item: str, verdict: bool | None, detail: str = "",
                measured: int | None = None) -> Entry:
        """Record that this member was actually looked at.

        `verdict` follows `Harness`: True fine, False broken, **None means the
        check could not tell**, which is never a pass.
        """
        name = self._accept(item)
        entry = Entry(item=name, status=EXAMINED, verdict=verdict, detail=detail,
                      measured=measured)
        self._entries[name] = entry
        return entry

    def skip(self, item: str, reason: str, measured: int | None = None) -> Entry:
        """Record that this member was deliberately left out, and why.

        `measured` is how much is in the thing you are not looking at. Leave it
        out and the skip reports UNKNOWN, because an exclusion nobody measured is
        a guess that looks identical to a good decision from the outside.
        `measured=0` is a measurement; omitting it is not.
        """
        if not reason or not reason.strip():
            raise CoverageError(
                f"skipping {item!r} needs a reason. An unexplained exclusion is "
                f"indistinguishable from an oversight, and it silently shrinks "
                f"the denominator of everything reported afterwards."
            )
        name = self._accept(item)
        entry = Entry(item=name, status=SKIPPED, reason=reason, measured=measured)
        self._entries[name] = entry
        return entry

    # ------------------------------------------------------------ accounting
    @property
    def entries(self) -> list[Entry]:
        return [self._entries[i] for i in self.population() if i in self._entries]

    @property
    def examined(self) -> list[Entry]:
        return [e for e in self.entries if e.status == EXAMINED]

    @property
    def skipped(self) -> list[Entry]:
        return [e for e in self.entries if e.status == SKIPPED]

    @property
    def unaccounted(self) -> tuple[str, ...]:
        """Discovered, and neither examined nor skipped. The silent gap."""
        return tuple(i for i in self.population() if i not in self._entries)

    def reconcile(self) -> None:
        """examined + skipped + unaccounted == discovered. Nothing may fall between."""
        total = len(self.examined) + len(self.skipped) + len(self.unaccounted)
        if total != len(self.population()):
            raise CoverageError(
                f"coverage does not reconcile: {len(self.examined)} examined + "
                f"{len(self.skipped)} skipped + {len(self.unaccounted)} unaccounted "
                f"= {total}, but {len(self.population())} {self.what} were "
                f"discovered. Something fell between the two."
            )

    @property
    def broke(self) -> list[Entry]:
        return [e for e in self.entries if e.is_broke]

    @property
    def unknown(self) -> list[Entry]:
        return [e for e in self.entries if e.is_unknown]

    def fraction(self) -> str:
        """The one sentence that must appear in every report."""
        return (f"{len(self.examined)} of {len(self.population())} {self.what} "
                f"examined")

    # --------------------------------------------------------------- report
    def report(self) -> str:
        self.reconcile()
        pop = len(self.population())
        ok = [e for e in self.examined if e.verdict is True]
        unmeasured = [e for e in self.skipped if e.measured is None]

        lines = [
            f"COVERAGE  {self.what}",
            f"  DISCOVERED  : {pop}",
            f"  EXAMINED    : {len(self.examined)}   "
            f"({len(ok)} ok, {len(self.broke)} BROKE, "
            f"{len([e for e in self.examined if e.verdict is None])} unknown)",
            f"  SKIPPED     : {len(self.skipped)}   "
            f"(every one with a reason; {len(unmeasured)} with no measurement)",
            f"  UNACCOUNTED : {len(self.unaccounted)}",
            "",
            f"  {self.fraction()}.",
        ]
        if self.unaccounted:
            lines.append(f"  {len(self.unaccounted)} were never looked at and never "
                         f"skipped, so nothing here is a clean bill of health.")
        lines.append("")

        if self.broke:
            lines.append("BROKE:")
            lines += [f"  {e.item}\n         {e.detail}" for e in self.broke]
            lines.append("")

        unknown_examined = [e for e in self.examined if e.verdict is None]
        if unknown_examined:
            lines.append("COULD NOT TELL:")
            lines += [f"  {e.item}\n         {e.detail}" for e in unknown_examined]
            lines.append("")

        if self.skipped:
            lines.append("OUT OF SCOPE -- measured anyway, so a wrong call is visible:")
            for e in self.skipped:
                size = "NOT MEASURED" if e.measured is None else f"{e.measured:,}"
                lines.append(f"  {size:>14}  {e.item}")
                lines.append(f"                  why: {e.reason}")
            if unmeasured:
                lines.append("")
                lines.append(f"  {len(unmeasured)} exclusion(s) have no measurement. "
                             f"An exclusion nobody measured is a guess, and from the "
                             f"outside it looks exactly like a good decision.")
            lines.append("")

        if self.unaccounted:
            lines.append("UNACCOUNTED -- discovered, then neither examined nor skipped:")
            lines += [f"  ? {i}" for i in self.unaccounted]
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def run(self, echo: bool = True) -> int:
        """0 everything examined and fine, 1 something broke, 2 could not tell.

        Unaccounted members and unmeasured exclusions both land on 2. Neither is
        a failure and neither is a pass: they are the shape of not knowing, and
        the exit code refuses to let that read as success.
        """
        text = self.report()
        if echo:
            print(text)
        if self.broke:
            return 1
        if self.unknown or self.unaccounted:
            if echo:
                print("UNKNOWN is not a pass. Part of the population was never "
                      "judged, so no conclusion here is supported.")
            return 2
        return 0

    def as_check(self):
        """A `Harness` check: this population is fully accounted for and healthy."""
        def _check() -> tuple[bool | None, str]:
            try:
                self.reconcile()
            except CoverageError as exc:
                return None, str(exc)
            if self.broke:
                return False, (f"{len(self.broke)} of {len(self.population())} "
                               f"{self.what} broken ({self.fraction()})")
            if self.unaccounted:
                return None, (f"{len(self.unaccounted)} of "
                              f"{len(self.population())} {self.what} were never "
                              f"looked at, so 0 broken means nothing")
            if self.unknown:
                return None, (f"{len(self.unknown)} of {len(self.population())} "
                              f"{self.what} could not be judged")
            return True, f"{self.fraction()}, all fine, {len(self.skipped)} skipped"
        return _check

    # ----------------------------------------------------------- persistence
    def as_dict(self) -> dict:
        self.reconcile()
        return {
            "version": 1,
            "what": self.what,
            "discovered": list(self.population()),
            "entries": [e.as_dict() for e in self.entries],
        }

    def save(self, path: str | os.PathLike[str]) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
        return p

    def diff(self, previous: str | os.PathLike[str] | dict,
             grew_by: float = 1.5, grew_at_least: int = 10) -> Diff:
        """NEW, GONE and GREW against a saved run.

        A member that appears next month surfaces itself here instead of waiting
        to be stumbled on. GREW only compares members that carry a measurement in
        BOTH runs; comparing against a missing number would invent a change.
        """
        if isinstance(previous, dict):
            old = previous
        else:
            p = Path(previous)
            if not p.exists():
                # No baseline is not "nothing changed". Say so rather than
                # returning an empty diff that reads like a clean run.
                raise CoverageError(
                    f"no previous run at {p}. There is nothing to diff against, "
                    f"which is not the same as nothing having changed."
                )
            old = json.loads(p.read_text(encoding="utf-8"))

        old_pop = list(old.get("discovered", []))
        new_pop = list(self.population())
        old_size = {e["item"]: e.get("measured") for e in old.get("entries", [])}
        new_size = {e.item: e.measured for e in self.entries}

        grew = []
        for item in set(old_size) & set(new_size):
            a, b = old_size[item], new_size[item]
            if a is None or b is None:
                continue
            if b > a * grew_by and b - a >= grew_at_least:
                grew.append(item)

        return Diff(
            appeared=tuple(sorted(set(new_pop) - set(old_pop))),
            vanished=tuple(sorted(set(old_pop) - set(new_pop))),
            grew=tuple(sorted(grew)),
        )

    # -------------------------------------------------------------- selftest
    @staticmethod
    def selftest(echo: bool = True) -> bool:
        """Make each rule fail on purpose and confirm it is caught."""
        ok = True

        def check(label: str, cond: bool) -> None:
            nonlocal ok
            if echo:
                print(("  ok    " if cond else "  FAIL  ") + label)
            ok = ok and bool(cond)

        members = ["a", "b", "c", "d"]

        # THE CASE THIS EXISTS FOR: everything looked at is fine, and half the
        # population was never looked at.
        partial = Coverage("nodes", lambda: members)
        partial.examine("a", True, "fine")
        partial.examine("b", True, "fine")
        check("a run with 2 of 4 examined and 0 broken is NOT a pass",
              partial.run(echo=False) == 2)
        check("...and the report says the fraction out loud, not just '0 broken'",
              "2 of 4 nodes examined" in partial.report())
        check("...and it names the members nobody looked at",
              "? c" in partial.report() and "? d" in partial.report())

        full = Coverage("nodes", lambda: members)
        for m in members:
            full.examine(m, True, "fine")
        check("the same 0 broken IS a pass once the whole population is accounted for",
              full.run(echo=False) == 0)
        check("...and it still states the denominator",
              "4 of 4 nodes examined" in full.report())

        broken = Coverage("nodes", lambda: members)
        broken.examine("a", False, "down")
        for m in members[1:]:
            broken.skip(m, "not in this tier", measured=0)
        check("a broken member exits 1, ahead of any unknown",
              broken.run(echo=False) == 1)

        # An exclusion nobody measured is a guess.
        guessed = Coverage("dirs", lambda: ["src", "cache"])
        guessed.examine("src", True, "read")
        guessed.skip("cache", "it's a cache")            # no measurement
        check("an exclusion with a reason but NO measurement is UNKNOWN, not a pass",
              guessed.run(echo=False) == 2)
        check("...and the report says so in a sentence a reader can act on",
              "guess" in guessed.report())

        measured = Coverage("dirs", lambda: ["src", "cache"])
        measured.examine("src", True, "read")
        measured.skip("cache", "package downloads, re-fetchable", measured=606)
        check("the same exclusion WITH a measurement passes", measured.run(echo=False) == 0)
        check("...and the measurement is printed, so a wrong call is visible",
              "606" in measured.report())

        # measured=0 is a measurement. Omitting it is not.
        zero = Coverage("dirs", lambda: ["src", "empty"])
        zero.examine("src", True, "read")
        zero.skip("empty", "nothing in it", measured=0)
        check("measured=0 is a real measurement and is NOT treated as missing",
              zero.run(echo=False) == 0)

        # Structural refusals.
        try:
            Coverage("nodes", ["a", "b"])  # type: ignore[arg-type]
            typed_raised = False
        except CoverageError:
            typed_raised = True
        check("a typed LIST as the population is refused; it must be a callable",
              typed_raised)

        try:
            Coverage("nodes", lambda: []).population()
            empty_raised = False
        except CoverageError:
            empty_raised = True
        check("an EMPTY population raises -- 0 of 0 reads as clean and proves nothing",
              empty_raised)

        try:
            Coverage("nodes", lambda: members).examine("zzz", True)
            stranger_raised = False
        except CoverageError:
            stranger_raised = True
        check("examining something outside the population is refused -- the "
              "numerator may not count what the denominator never included",
              stranger_raised)

        try:
            dupe = Coverage("nodes", lambda: members)
            dupe.examine("a", True)
            dupe.examine("a", False)
            dupe_raised = False
        except CoverageError:
            dupe_raised = True
        check("recording the same member twice is refused", dupe_raised)

        try:
            Coverage("nodes", lambda: members).skip("a", "   ")
            reason_raised = False
        except CoverageError:
            reason_raised = True
        check("an exclusion with no reason is refused", reason_raised)

        # A population that GROWS mid-run must not change the denominator.
        moving = list(members)
        drifting = Coverage("nodes", lambda: moving)
        for m in drifting.population():
            drifting.examine(m, True, "fine")
        moving.append("e")
        check("the denominator is fixed for the run, so a population that grows "
              "halfway through cannot make the report inconsistent",
              drifting.run(echo=False) == 0 and len(drifting.population()) == 4)
        check("...and refreshing deliberately picks the new member up",
              len(drifting.population(refresh=True)) == 5)

        # Diff.
        first = Coverage("nodes", lambda: ["a", "b"])
        first.examine("a", True, measured=10)
        first.examine("b", True, measured=10)
        snapshot = first.as_dict()

        later = Coverage("nodes", lambda: ["a", "c"])
        later.examine("a", True, measured=100)
        later.examine("c", True, measured=10)
        d = later.diff(snapshot)
        check("a member that APPEARED since the last run is reported", d.appeared == ("c",))
        check("a member that VANISHED is reported", d.vanished == ("b",))
        check("a member that grew far larger is reported", d.grew == ("a",))
        check("an unchanged run diffs to nothing", not first.diff(snapshot))

        try:
            first.diff(Path("no-such-baseline.json"))
            baseline_raised = False
        except CoverageError:
            baseline_raised = True
        check("diffing against a baseline that does not exist raises -- no baseline "
              "is not the same as nothing having changed", baseline_raised)

        if echo:
            print("SELFTEST", "PASS" if ok else "FAIL")
        return ok


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m agentattest.coverage",
        description="A count is not a result until it says what it did not look at.")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="show the same 0-broken result read two ways (the default)")
    args = ap.parse_args(argv)

    if args.selftest:
        return 0 if Coverage.selftest() else 1

    nodes = ["web-1", "web-2", "db-1", "db-2", "cache-1", "worker-1", "worker-2"]

    print("The report almost every tool prints:\n")
    print("  2 nodes checked, 0 broken\n")
    print("Read as: the system is fine. Means: the 2 I picked are fine.")
    print("Same work, with the denominator attached:\n")

    cov = Coverage("nodes", lambda: nodes)
    cov.examine("web-1", True, "responding in 40ms")
    cov.examine("web-2", True, "responding in 38ms")
    code = cov.run()
    print(f"exit {code}\n")
    print("Nothing was found to be broken in either version. Only one of them")
    print("admits that five nodes were never looked at, and only one of them")
    print("refuses to exit 0.")
    return code


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
