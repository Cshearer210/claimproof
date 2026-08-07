"""Request six of eight quietly never happening -- and the gate that notices.

Run me:

    python no_silent_drops.py

A user asks for three things in two messages. The agent does most of them,
declares victory, and the ledger disagrees -- by name, with what is still
open. Then the work actually finishes (one item honestly skipped, on the
record) and the same claim passes, because now it is true.
"""
import sys
import textwrap

from agentattest.ledger import Ledger, NothingLeft


def show(label, body):
    print(label)
    print("-" * len(label))
    print(textwrap.indent(body.rstrip(), "  "))
    print()


def claim(gate, text):
    findings = gate.check(text)
    if findings:
        return "\n".join(f"REFUSED: {f}" for f in findings)
    return f"allowed: {text!r}"


def main():
    led = Ledger()  # in-memory for the demo; real use passes a file path

    led.ask("fix the parser bug and add a regression test")
    led.split(1, "fix the parser bug", "add a regression test")
    led.ask("bump the version")
    show("The user asked for three things (two messages, recorded verbatim)",
         led.report())

    gate = NothingLeft(led)
    led.done("1a", "pytest: 57 passed, was 56")
    show('Two still open, and the agent says "All done, everything works."',
         claim(gate, "All done, everything works."))

    show("Finishing one thing was never the problem -- partial claims pass",
         claim(gate, "Done with the parser fix; test and version bump are next."))

    led.done("1b", "test_parser.py::test_regression added, fails on the old code")
    led.skip("2a", "version bumps happen at release, agreed with the user")
    show("The remaining items are closed WITH evidence, or skipped ON the record",
         led.report())

    show('The same claim, now that it is true',
         claim(gate, "All done, everything works."))

    print("The refusal named what was open. The skip carries its reason. And")
    print("closing an item with the bare word 'done' is refused -- the ledger")
    print("cannot judge your evidence, but it can refuse a claim posing as one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
