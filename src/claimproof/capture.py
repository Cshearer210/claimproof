"""Record what a command actually did, at the moment it does it.

A turn's sentence about a command is written afterwards, from memory, by
whatever is composing the reply. The exit code is available only while the
process is being reaped -- and once that moment passes, nothing in the text can
be distinguished from a number that was simply typed.

So this is the whole idea: run the command through `run()`, and it emits one
fixed receipt line beside the real output:

    [claimproof:exit] 1 pytest -q

`claimproof.gates.ExitCodeMismatch` reads those receipts back and refuses a
sentence that disagrees with them. Neither half is useful alone -- a gate with
no receipts has nothing to check, and receipts nobody reads are a log.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass

__all__ = ["Ran", "receipt", "run"]


@dataclass(frozen=True)
class Ran:
    """One command, and what it really did."""

    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def receipt(command: str, returncode: int) -> str:
    """The one line a gate reads back. Single line, so a receipt cannot be
    split across a truncated tool result and half-parsed."""
    return "[claimproof:exit] %d %s" % (returncode, " ".join(str(command).split()))


def run(command, *, cwd=None, env=None, timeout=None, echo=True, **kwargs) -> Ran:
    """Run `command` and record its real exit code.

    `command` may be a string or a list, exactly as `subprocess.run` takes it.
    The receipt goes to stderr rather than stdout so it never lands in the
    middle of output something else is parsing.
    """
    shell = isinstance(command, str)
    proc = subprocess.run(
        command, shell=shell, cwd=cwd, env=env, timeout=timeout,
        capture_output=True, text=True, **kwargs)

    pretty = command if shell else " ".join(shlex.quote(c) for c in command)
    if echo:
        sys.stderr.write(receipt(pretty, proc.returncode) + "\n")
    return Ran(command=pretty, returncode=proc.returncode,
               stdout=proc.stdout or "", stderr=proc.stderr or "")


def selftest() -> None:
    """Prove the receipt reports what really happened, both ways.

    The point of the false case is that a receipt claiming success for a failing
    command is the exact defect this module exists to make impossible, so it is
    worth one assertion rather than a comment saying it cannot happen.
    """
    good = run([sys.executable, "-c", "print('hi')"], echo=False)
    assert good.returncode == 0 and good.ok, good
    assert good.stdout.strip() == "hi", good

    bad = run([sys.executable, "-c", "raise SystemExit(3)"], echo=False)
    assert bad.returncode == 3 and not bad.ok, bad
    assert receipt(bad.command, bad.returncode).startswith("[claimproof:exit] 3 "), bad

    assert "\n" not in receipt("a\n  b", 0), "a receipt must be exactly one line"
    # Kills: bool const True->False @L27 (frozen=True on Ran)
    import dataclasses
    try:
        good.command = "tampered"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Ran must be frozen (@dataclass(frozen=True))")

    # Kills: bool Or->flip @L63 (stderr=proc.stderr or "")
    # The existing `bad` fixture never writes to stderr, so give one that does.
    loud = run([sys.executable, "-c",
                "import sys; sys.stderr.write('boo'); raise SystemExit(4)"], echo=False)
    assert loud.returncode == 4 and not loud.ok, loud
    assert loud.stderr == "boo", loud

    # Kills: bool const True->False @L47 (echo=True default) and
    #        arith flip @L61 (receipt(...) + "\n" written to stderr)
    # Call run() WITHOUT passing echo at all, so the default is what fires,
    # and check the exact bytes that land on stderr.
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        echoed = run([sys.executable, "-c", "print('x')"])
    assert echoed.ok, echoed
    assert buf.getvalue() == receipt(echoed.command, echoed.returncode) + "\n", buf.getvalue()
    print("capture: selftest PASS (3 checks)")


if __name__ == "__main__":
    selftest()
