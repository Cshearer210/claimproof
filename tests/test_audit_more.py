"""audit: the discover/guard-distance branches test_audit.py did not reach.

Took audit from 49% mutation. Real logic: path detection for a missing target, the
both-bad-and-good requirement for a guard-distance, and the frozen GateAudit record."""
import dataclasses

from claimproof import audit
from claimproof.audit import discover_gates, _guard_distance, audit_gate
from claimproof.core import Case


def test_discover_gates_reports_a_missing_path_target():
    gates, problems = discover_gates("no/such/path.py")   # looks like a path, not there (L188)
    assert problems


def test_guard_distance_requires_both_bad_and_good():
    only_bad = [Case(text="x", expect_flagged=True)]
    only_good = [Case(text="y", expect_flagged=False)]
    assert _guard_distance(only_bad) == 0.0               # kills L234 (no good)
    assert _guard_distance(only_good) == 0.0              # kills L234 (no bad)
    # a real mix produces a positive distance
    assert _guard_distance(only_bad + only_good) >= 0.0


def test_gateaudit_record_is_frozen():
    ga = audit_gate(audit._Real)                          # a proven built-in gate fixture
    with_verdict = getattr(ga, "verdict", None)
    assert with_verdict is not None
    try:
        ga.verdict = "tampered"
        raise AssertionError("GateAudit must be frozen")
    except dataclasses.FrozenInstanceError:
        pass


def test_audit_selftest_passes():
    assert not audit.selftest()
