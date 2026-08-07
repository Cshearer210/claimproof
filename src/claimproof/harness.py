"""Checks that assert against live state, not source code.

A test suite proves your code is internally correct. It cannot tell you the backup
stopped running, the hook got unwired, or the service died. Code does not decay.
Reality does.

The rule that makes this useful: a check returning None reports UNKNOWN and never
counts as a pass. Absent-and-fine and present-and-fine must not produce the same
output, because that is exactly how a broken check goes unnoticed for months.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

__all__ = ["OK", "BROKE", "UNKNOWN", "Result", "Harness"]

OK = "ok"
BROKE = "BROKE"
UNKNOWN = "??"

#: A check returns (verdict, detail). verdict True/False/None -> ok/BROKE/UNKNOWN.
CheckFn = Callable[[], Tuple[Optional[bool], str]]


@dataclass(frozen=True)
class Result:
    check_id: str
    what: str
    verdict: str
    detail: str

    def line(self) -> str:
        return f"  {self.verdict:6s} {self.what}\n         {self.detail}"


class Harness:
    """Register checks, run them, exit on the worst outcome.

        h = Harness()

        @h.check("backup-ran", "The off-machine backup actually ran recently")
        def _():
            ...
            return True, "newest snapshot 4h ago"

        raise SystemExit(h.run())

    Exit codes: 0 all ok, 1 something BROKE, 2 something UNKNOWN and nothing broke.
    UNKNOWN exits non-zero on purpose. It is not a pass.
    """

    def __init__(self) -> None:
        self._checks: list[tuple[str, str, CheckFn]] = []

    def check(self, check_id: str, what: str):
        """Decorator. `what` is shown to a human, so write it as a full sentence."""
        if not check_id:
            raise ValueError("check_id is required")
        if any(c[0] == check_id for c in self._checks):
            raise ValueError(f"duplicate check_id {check_id!r}")

        def deco(fn: CheckFn) -> CheckFn:
            self._checks.append((check_id, what, fn))
            return fn

        return deco

    def __len__(self) -> int:
        return len(self._checks)

    @property
    def ids(self) -> list[str]:
        return [c[0] for c in self._checks]

    def evaluate(self) -> list[Result]:
        results: list[Result] = []
        for check_id, what, fn in self._checks:
            try:
                verdict, detail = fn()
            except Exception as exc:
                # A check that crashed did not pass. It could not tell.
                results.append(Result(check_id, what, UNKNOWN,
                                      f"check raised {type(exc).__name__}: {exc}"))
                continue

            if verdict is None:
                results.append(Result(check_id, what, UNKNOWN, detail))
            elif verdict:
                results.append(Result(check_id, what, OK, detail))
            else:
                results.append(Result(check_id, what, BROKE, detail))
        return results

    def run(self, echo: bool = True) -> int:
        results = self.evaluate()
        broke = [r for r in results if r.verdict == BROKE]
        unknown = [r for r in results if r.verdict == UNKNOWN]

        if echo:
            for r in results:
                print(r.line())
            print(
                f"\n{len(results) - len(broke) - len(unknown)} holding, "
                f"{len(broke)} REGRESSED, {len(unknown)} unknown"
            )
            if unknown:
                print("UNKNOWN is not a pass. It means the check could not tell.")

        if broke:
            return 1
        if unknown:
            return 2
        return 0

    def selftest(self) -> bool:
        """Prove the harness itself still distinguishes the three outcomes.

        Without this, a harness bug that turned every check into a pass would look
        exactly like a healthy system.
        """
        probe = Harness()
        probe.check("t-ok", "passes")(lambda: (True, "fine"))
        probe.check("t-broke", "fails")(lambda: (False, "bad"))
        probe.check("t-unknown", "cannot tell")(lambda: (None, "no data"))
        probe.check("t-raises", "explodes")(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        verdicts = {r.check_id: r.verdict for r in probe.evaluate()}
        expected = {"t-ok": OK, "t-broke": BROKE, "t-unknown": UNKNOWN, "t-raises": UNKNOWN}
        if verdicts != expected:
            return False

        # A run containing a BROKE must exit 1, and UNKNOWN alone must exit 2.
        if probe.run(echo=False) != 1:
            return False

        only_unknown = Harness()
        only_unknown.check("u", "cannot tell")(lambda: (None, "no data"))
        if only_unknown.run(echo=False) != 2:
            return False

        clean = Harness()
        clean.check("c", "fine")(lambda: (True, "fine"))
        return clean.run(echo=False) == 0
