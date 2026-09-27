"""core: Finding and Case are frozen dataclasses on purpose (an immutable evidence record).

Nothing asserted the frozen-ness, so the frozen=True mutants survived. Cheap, real kill."""
import dataclasses

from claimproof.core import Finding, Case


def test_finding_is_frozen():
    f = Finding(message="m", line=1, excerpt="e")
    try:
        f.message = "x"
        raise AssertionError("Finding must be frozen")
    except dataclasses.FrozenInstanceError:
        pass


def test_case_is_frozen():
    c = Case(text="t", expect_flagged=True)
    try:
        c.text = "x"
        raise AssertionError("Case must be frozen")
    except dataclasses.FrozenInstanceError:
        pass
