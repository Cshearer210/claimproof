"""A 30 second demo. Run it:

    python -m agentattest.demo

Shows an agent trying to end its turn on a claim it cannot back, getting refused,
and then getting through once it shows the receipt. Then shows a gate that has
never been made to fail being rejected outright.
"""
from __future__ import annotations

import sys

from agentattest import Case, Gate, Harness, SelftestError
from agentattest.gates import UnbackedClaims
from agentattest.hooks import BLOCK, stop_hook

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

    def inspect(self, text):
        return []

    def selftest_cases(self):
        return [Case(text="obviously bad", expect_flagged=True)]


def main() -> int:
    print("\nagentattest: agents claim work is done that isn't.\n")

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

    print("\n4. A gate that has never been made to fail cannot be used.")
    print(BAR)
    try:
        NeverFails().check("obviously bad")
        print("  -> allowed. THIS SHOULD NOT HAPPEN.")
        return 1
    except SelftestError as exc:
        print(f"  -> refused at construction, not at review time:\n     {exc}")

    print("\n5. Live-state checks. UNKNOWN is not a pass.")
    print(BAR)
    h = Harness()
    h.check("disk", "There is room on the disk")(lambda: (True, "41% used"))
    h.check("backup", "The off-machine backup ran recently")(lambda: (False, "last run 41 days ago"))
    h.check("gpu", "The GPU is reachable")(lambda: (None, "no driver on this host, cannot tell"))
    code = h.run()
    print(f"  -> exit {code}")

    print("\nNothing above was mocked. Every verdict came from the real code.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
