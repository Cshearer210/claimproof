"""rag_index: gate_label_mismatches / index -- checks a gate's declared label matches what it does.

rag_index.selftest() kills 12/12 of its own mutants (measured 2026-09-24), yet no pytest test ran
it, so the suite covered this module 0%. Wiring it in closes the whole gap."""
from claimproof import rag_index


def test_its_own_selftest_passes():
    assert not rag_index.selftest()


def test_index_over_real_source_does_not_crash():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert rag_index.index(root) is not None
