"""A 30 second demo. Run it:

    python -m claimproof.demo

Shows an agent trying to end its turn on a claim it cannot back, getting refused,
and then getting through once it shows the receipt; "all done" checked against
the list of what was actually asked; a gate that has never been made to fail
being rejected outright; and live-state checks where UNKNOWN is not a pass.
"""
from __future__ import annotations

import sys

from claimproof import Case, Gate, Harness, SelftestError
from claimproof.gates import UnbackedClaims
from claimproof.hooks import BLOCK, stop_hook
from claimproof.ledger import Ledger, NothingLeft
from claimproof.core import Finding
from claimproof.register import Register

BAR = "-" * 68


def _turn(label: str, text: str) -> None:
    code, message = stop_hook({"text": text}, [UnbackedClaims()])
    verdict = "REFUSED" if code == BLOCK else "allowed"
    print(f"\n{label}")
    print(BAR)
    for line in text.splitlines() or [""]:
        print(f"  | {line}")
    print(BAR)
    print(f"  -> {verdict} (exit {code})")
    if message:
        for line in message.splitlines():
            print(f"     {line}")


class NeverFails(Gate):
    """Looks like a gate. Returns clean on everything. Nobody would notice."""

    name = "looks-fine"
    #: Declared so `claimproof audit` reports this as exempt-with-a-reason
    #: rather than as a finding. It is SUPPOSED to fail its own contract --
    #: step 5 of the demo exists to show exactly that happening.
    audit_exempt = ("a deliberately broken gate, used by the demo to show one "
                    "being refused at construction")

    def inspect(self, text):
        return []

    def selftest_cases(self):
        # Both directions declared, so this gate is refused for the real reason:
        # it cannot flag the case it says it must. The guard case passes -- which
        # is exactly why a gate proven in one direction only proves nothing.
        return [
            Case(text="obviously bad", expect_flagged=True),
            Case(text="obviously fine", expect_flagged=False),
        ]


def main() -> int:
    print("\nclaimproof: agents claim work is done that isn't.\n")

    _turn("1. The agent says it is done, and shows nothing.",
          "I fixed the parser bug. All tests pass.")

    _turn("2. Same claim, with the receipt attached.",
          "I fixed the parser bug.\n"
          "```\n"
          "56 passed in 0.14s\n"
          "```\n"
          "All tests pass.")

    _turn("3. Honest uncertainty is left alone.",
          "This should fix the parser bug, but I have not run the suite yet.")

    print('\n4. "All done" is checked against what was actually asked.')
    print(BAR)
    led = Ledger()
    led.ask("fix the parser bug")
    led.ask("update the changelog")
    led.done("1a", "pytest: 56 passed in 0.14s")
    gate = NothingLeft(led)
    print('  | All done, everything works.')
    print(BAR)
    for f in gate.check("All done, everything works."):
        print(f"  -> REFUSED: {f.message}")
    led.skip("2a", "changelog is generated at release time")
    print("  after closing the last item, on the record:")
    if gate.check("All done, everything works."):
        print("  -> REFUSED. THIS SHOULD NOT HAPPEN.")
        return 1
    print("  -> allowed: the same claim passes, because now it is true")

    print("\n5. A gate that has never been made to fail cannot be used.")
    print(BAR)
    try:
        NeverFails().check("obviously bad")
        print("  -> allowed. THIS SHOULD NOT HAPPEN.")
        return 1
    except SelftestError as exc:
        print(f"  -> refused at construction, not at review time:\n     {exc}")

    print("\n6. Live-state checks. UNKNOWN is not a pass.")
    print(BAR)
    h = Harness()
    h.check("disk", "There is room on the disk")(lambda: (True, "41% used"))
    h.check("backup", "The off-machine backup ran recently")(lambda: (False, "last run 41 days ago"))
    h.check("gpu", "The GPU is reachable")(lambda: (None, "no driver on this host, cannot tell"))
    code = h.run()
    print(f"  -> exit {code}")

    print("\n7. A gate can pass its own selftest and still prove nothing.")
    print(BAR)
    from claimproof.audit import audit_gate

    class GuardProvesNothing(Gate):
        """Fires on the bad case, stays quiet on a guard with nothing in common."""

        name = "guard-proves-nothing"

        def inspect(self, text):
            return [Finding("no receipt")] if "done, no receipt" in text else []

        def selftest_cases(self):
            return [Case("the migration is done, no receipt at all", True),
                    Case("z", False)]

    GuardProvesNothing().verify()      # its own contract is satisfied
    print("  | verify() passes: it flags its bad case and leaves its guard alone")
    verdict = audit_gate(GuardProvesNothing)
    print(BAR)
    print(f"  -> audit says {verdict.verdict}:")
    for line in _wrapped(verdict.detail):
        print(f"     {line}")

    print("\n8. A finding stays red until something proves it is gone.")
    print(BAR)
    reg = Register()
    reg.record("unbacked-claims", [Finding("claims done with no receipt")],
               scope="turn-41")
    reg.record("unbacked-claims", [Finding("claims done with no receipt")],
               scope="turn-42")
    red = reg.red()[0]
    print(f"  | the same finding twice is one row, seen {red.times_seen}x")
    closed, not_examined = reg.reconcile("unbacked-claims", [], scope="turn-42")
    print("  | re-inspected turn-42: the finding is not there any more")
    print(f"  | closed {len(closed)}, still waiting on {len(not_examined)}")
    still = reg.red()
    print(BAR)
    if still:
        print(f"  -> and {len(still)} stayed RED: {still[0].message}")
        print("     it was found in turn-41, which nothing re-examined. Absent because")
        print("     it was fixed and absent because nobody looked are not the same answer.")
    else:
        print("  -> nothing stayed red. THIS SHOULD NOT HAPPEN.")
        return 1

    print("\nNothing above was mocked. Every verdict came from the real code.\n")
    return 0


def _wrapped(text: str, width: int = 66) -> list[str]:
    """Wrap a detail line so the demo stays inside a terminal and inside the SVG."""
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    sys.exit(main())
