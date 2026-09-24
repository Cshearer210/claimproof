"""multimethod: the multi-detector scan (weak-oracle / silent-swallow / unreachable-except / ...).

Its own selftest() drives every detector against known-good and known-bad fixtures and returns
non-zero if any detector's behaviour drifts. Measured 2026-09-24: that selftest kills 75/80 of
multimethod.py's mutants -- but nothing in the pytest suite RAN it, so the suite scored 0% against
this 880-line module. Wiring it in is the fix, and it is the repo's established pattern
(test_gates / test_core / ... all drive a module's own selftest)."""
from claimproof import multimethod


def test_its_own_selftest_passes():
    assert not multimethod.selftest()


def test_scan_over_real_source_returns_a_list():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert isinstance(multimethod.scan(root), list)
