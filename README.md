# agentattest

AI coding agents routinely report that work is finished when it isn't. Not by lying, but because
a fluent summary and a correct one feel identical from the inside, and nothing in the loop is
checking. `agentattest` makes an agent prove it, at the runtime layer, before its turn can end.

> **Status: 0.0.1, scaffold.** The API below is the design, not yet the implementation. Phase 1
> lands the core. Building in the open on purpose.

## The idea

Three things, one principle: a claim without evidence is not a result.

**1. A gate that cannot be trusted until it has failed.**

Most checks are written, pass on the first run, and are never tested against a case they should
catch. So nobody knows whether they work. Here, `selftest_cases()` is abstract and must include a
case the gate is expected to flag. A gate that has never been made to fail cannot be instantiated.

```python
from agentattest import Gate, Case

class UnbackedClaims(Gate):
    def inspect(self, text: str) -> list[Finding]:
        ...

    def selftest_cases(self) -> list[Case]:          # required
        return [Case(text="It works.",        expect_flagged=True),
                Case(text="It works. exit=0", expect_flagged=False)]
```

**2. Checks that assert against live state, not source code.**

Code does not decay. Reality does. A backup that stopped running, a hook that got unwired, a
service that died quietly: none of that shows up in a test suite, because the code is still
correct. These checks look at the world.

```python
from agentattest import Harness

h = Harness()

@h.check("backup-ran", "The off-machine backup actually ran recently")
def _():
    ...
    return True, "newest snapshot 4h ago"

raise SystemExit(h.run())
```

**3. UNKNOWN is never a pass.**

A check that cannot determine its answer returns `None` and is reported as UNKNOWN. Exit 2, not 0.
Absent-and-fine and present-and-fine must never produce the same output, because that is precisely
how a broken check goes unnoticed.

## Why this exists

A content quality gate in a production system defaulted to passing everything once its API budget
reached zero. Weeks of output shipped ungraded and nothing alarmed, because the failure looked
exactly like success.

Separately, a credential scanner in the same system had its search paths hardcoded to one
operating system. On the other machine it scanned zero files, printed `CLEAN`, and exited 0. It
had never once been made to fail on purpose, so nobody knew.

Both are the same bug: a check that reports success while proving nothing. That class of failure
is what this library is built to make structurally difficult.

That is also why CI runs the full matrix on both Linux and Windows. A single-OS matrix would not
have caught the second one.

## Install

```bash
pip install agentattest
```

Requires Python 3.11 or newer. No runtime dependencies.

## License

MIT
