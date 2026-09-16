# CALLED BY: pytest itself. `conftest.py` is pytest's own auto-discovery hook name --
# every `pytest` invocation in or under this directory imports this file and runs
# `pytest_configure` before collecting a single test, with no import or registration
# required anywhere else. That auto-load IS the wiring.
"""Session-wide guard against a shadowed install of this package.

An editable install pointing at a stale or unrelated checkout can silently take
over every `import claimproof` in an environment. When that happens, a test run
looks green while it is actually exercising a DIFFERENT copy of the code than the
one sitting in this repo -- any work "verified" that way never touched this
checkout at all, and is invisible until someone diffs the two by hand.

A green test run proves the CODE is correct. It says nothing about whether the
test run even imported the code in THIS repo. This fixture closes that gap: it
fails loudly, before a single test runs, if `claimproof` resolves to anywhere
other than this checkout's `src/` directory.
"""
from __future__ import annotations

import os

import claimproof

_THIS_REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def pytest_configure(config):
    resolved = os.path.abspath(os.path.dirname(claimproof.__file__))
    expected = os.path.join(_THIS_REPO_SRC, "claimproof")
    if resolved != os.path.abspath(expected):
        raise RuntimeError(
            f"claimproof resolves to {resolved!r}, not this repo's own "
            f"{expected!r}. Some other install or checkout is shadowing this "
            f"one -- every test in this run would be exercising the WRONG "
            f"copy. Check `pip list | grep claimproof` and `sys.path` before "
            f"trusting any result from this suite."
        )
