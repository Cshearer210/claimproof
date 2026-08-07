"""The core contract: a gate that has never been made to fail cannot be used.

Most checks are written, pass on their first run, and are never once fed a case
they are supposed to catch. Nobody finds out they are broken until the thing they
were guarding against happens. Two real examples this library was built from:

  * A content quality gate defaulted to passing everything once its API budget
    reached zero. Weeks of output shipped ungraded. The failure looked exactly
    like success.
  * A credential scanner had its search paths hardcoded to one operating system.
    On the other machine it read zero files, printed CLEAN, and exited 0.

Neither had a selftest. So here `selftest_cases()` is abstract, and `Gate.verify()`
refuses any gate whose cases do not include at least one the gate must flag.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Iterable

__all__ = ["Finding", "Case", "SelftestError", "Gate"]


@dataclass(frozen=True)
class Finding:
    """One problem a gate found in the text it inspected."""

    message: str
    line: int | None = None
    excerpt: str = ""

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line is not None else ""
        tail = f"  ({self.excerpt})" if self.excerpt else ""
        return f"{where}{self.message}{tail}"


@dataclass(frozen=True)
class Case:
    """One selftest fixture: some text, and whether the gate must flag it.

    `expect_flagged=True` means "this is the bad case, the gate is required to
    catch it". A gate with no such case is not trusted.
    """

    text: str
    expect_flagged: bool
    name: str = ""

    def label(self) -> str:
        if self.name:
            return self.name
        kind = "bad" if self.expect_flagged else "good"
        first = self.text.strip().splitlines()[0] if self.text.strip() else "<empty>"
        return f"{kind}: {first[:48]}"


class SelftestError(RuntimeError):
    """Raised when a gate cannot prove it works. Never caught internally."""


class Gate(abc.ABC):
    """Inspect text, return findings, and be able to prove you can find them.

    Subclasses implement two methods:

        inspect(text)        -> list[Finding]
        selftest_cases()     -> list[Case]      # must include one bad case

    Then::

        gate = MyGate()
        gate.verify()               # raises SelftestError unless it really works
        findings = gate.inspect(text)
    """

    #: Human-readable name. Defaults to the class name.
    name: str = ""

    def __init__(self) -> None:
        if not self.name:
            self.name = type(self).__name__

    # ------------------------------------------------------------------ API
    @abc.abstractmethod
    def inspect(self, text: str) -> list[Finding]:
        """Return every problem found in `text`. Empty list means clean."""

    @abc.abstractmethod
    def selftest_cases(self) -> list[Case]:
        """Fixtures proving this gate works. At least one must be a bad case."""

    # -------------------------------------------------------------- verify
    def verify(self) -> list[str]:
        """Run every selftest case. Raise SelftestError on any disagreement.

        Returns the list of case labels that were checked, so a caller can show
        the denominator rather than a bare "ok".
        """
        cases = list(self.selftest_cases() or [])

        if not cases:
            raise SelftestError(
                f"{self.name}: no selftest cases. A gate that has never been run "
                f"against a known-bad input proves nothing."
            )

        if not any(c.expect_flagged for c in cases):
            raise SelftestError(
                f"{self.name}: every selftest case expects a clean result. At least "
                f"one case must be one this gate is REQUIRED to flag, or the gate has "
                f"never been made to fail on purpose and cannot be trusted."
            )

        checked: list[str] = []
        for case in cases:
            try:
                findings = self.inspect(case.text)
            except Exception as exc:  # a gate that explodes is a broken gate
                raise SelftestError(
                    f"{self.name}: inspect() raised {type(exc).__name__} on case "
                    f"[{case.label()}]: {exc}"
                ) from exc

            flagged = bool(findings)
            if flagged != case.expect_flagged:
                wanted = "flag" if case.expect_flagged else "pass"
                got = "flagged" if flagged else "passed"
                detail = f" (found: {findings[0]})" if findings else ""
                raise SelftestError(
                    f"{self.name}: expected to {wanted} case [{case.label()}] "
                    f"but it {got}{detail}"
                )
            checked.append(case.label())

        return checked

    # ------------------------------------------------------------- helpers
    def check(self, text: str) -> list[Finding]:
        """verify() then inspect(). The safe entry point.

        Use this when a gate's result is about to matter. It refuses to give you
        a clean bill of health from a gate that cannot prove it works.
        """
        self.verify()
        return self.inspect(text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name!r}>"
