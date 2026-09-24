"""capture: run a command and record a receipt (command, returncode, output) -- the Ran result.

Other tests use capture indirectly (captured-evidence flow) but never asserted on capture.py's own
logic, so the suite killed only 1/8 of its mutants. capture.selftest() kills 8/8 (measured
2026-09-24); wiring it in plus a direct receipt assertion closes the gap. selftest() returns None
and raises on failure, so `assert not ...` = 'it did not raise'."""
import sys

from claimproof import capture


def test_its_own_selftest_passes():
    assert not capture.selftest()


def test_run_records_returncode_and_ok():
    ran = capture.run([sys.executable, "-c", "import sys; sys.exit(0)"], echo=False)
    assert ran.returncode == 0
    assert ran.ok is True                 # Ran.ok is a property, not a method
    bad = capture.run([sys.executable, "-c", "import sys; sys.exit(3)"], echo=False)
    assert bad.returncode == 3
    assert bad.ok is False
