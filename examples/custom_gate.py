#!/usr/bin/env python3
"""Writing your own gate. Run it: python custom_gate.py

Two gates below. The first is correct. The second looks correct and is not, and
the library refuses it. That second one is the whole point: it is the shape a
broken check actually takes in the wild, and reading it passes review.
"""
from agentattest import Case, Finding, Gate, SelftestError


class NoTodoLeftBehind(Gate):
    """Refuse a turn that ships a TODO or FIXME the agent just wrote."""

    name = "no-todo-left-behind"

    def inspect(self, text: str) -> list[Finding]:
        out = []
        for i, line in enumerate(text.splitlines()):
            for marker in ("TODO", "FIXME", "XXX"):
                if marker in line:
                    out.append(Finding(
                        message=f"{marker} left in the output",
                        line=i + 1,
                        excerpt=line.strip()[:60],
                    ))
                    break
        return out

    def selftest_cases(self) -> list[Case]:
        # At least one case MUST be one this gate is required to catch.
        # Without it, the library refuses to run the gate at all.
        return [
            Case(text="def f():\n    pass  # TODO wire this up", expect_flagged=True),
            Case(text="raise NotImplementedError  # FIXME", expect_flagged=True),
            Case(text="def f():\n    return 1", expect_flagged=False),
            Case(text="", expect_flagged=False),
        ]


class LooksFineIsNot(Gate):
    """The dangerous shape. It has cases, it has an inspect(), it reads fine.

    The bug is `startswith` where it should be `in`. A TODO at the start of a
    line gets caught; a TODO in a trailing comment, which is where they nearly
    always live, does not. So in practice it approves everything, and it would
    pass any test you were likely to write by hand.
    """

    name = "looks-fine-is-not"

    def inspect(self, text: str) -> list[Finding]:
        return [Finding(message="TODO left in the output", line=i + 1)
                for i, line in enumerate(text.splitlines())
                if line.strip().startswith("TODO")]      # <-- the bug

    def selftest_cases(self) -> list[Case]:
        return [
            Case(text="pass  # TODO wire this up", expect_flagged=True),
            Case(text="return 1", expect_flagged=False),
        ]


def main() -> int:
    print("\n1. A correct gate verifies, then finds what it should.\n")
    gate = NoTodoLeftBehind()
    print(f"   verified {len(gate.verify())} cases")
    for f in gate.check("x = 1\ny = 2  # TODO handle the empty case\nz = 3"):
        print(f"   found -> {f}")
    print(f"   clean input -> {gate.check('x = 1')} ")

    print("\n2. The broken gate is refused, and the message names the case.\n")
    try:
        LooksFineIsNot().check("pass  # TODO wire this up")
        print("   allowed. THIS SHOULD NOT HAPPEN.")
        return 1
    except SelftestError as exc:
        print(f"   {exc}")

    print("\n   Note what happened there. inspect() on its own returns:")
    print(f"   {LooksFineIsNot().inspect('pass  # TODO wire this up')}")
    print("   which looks like a clean result. check() is what refuses it.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
