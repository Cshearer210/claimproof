"""The examples are the first code anyone copies. If they break, the project looks dead.

These run the real example files as subprocesses, the same way a reader would,
rather than importing them. An example that only works when imported is not an
example.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

pytestmark = pytest.mark.skipif(
    not EXAMPLES.is_dir(),
    reason="examples/ is not shipped in the wheel, so this only runs from a checkout",
)


def run(script, stdin=None):
    return subprocess.run(
        [sys.executable, str(EXAMPLES / script)],
        input=stdin, capture_output=True, text=True, timeout=120,
    )


def test_stop_hook_refuses_an_unbacked_claim():
    r = run("stop_hook.py", json.dumps({"text": "I fixed it. All tests pass."}))
    assert r.returncode == 2, r.stderr
    assert "Turn refused" in r.stderr
    assert "no nearby evidence" in r.stderr


def test_stop_hook_allows_a_claim_that_shows_its_work():
    r = run("stop_hook.py", json.dumps({"text": "I fixed it.\n56 passed in 0.14s"}))
    assert r.returncode == 0, r.stderr
    assert r.stderr.strip() == ""


def test_stop_hook_fails_open_on_junk_rather_than_wedging_the_agent():
    r = run("stop_hook.py", "this is not json")
    assert r.returncode == 0


def test_custom_gate_example_runs_and_demonstrates_a_refusal():
    r = run("custom_gate.py")
    assert r.returncode == 0, r.stderr
    assert "expected to flag case" in r.stdout
    assert "THIS SHOULD NOT HAPPEN" not in r.stdout
    # The narration claims inspect() looks clean. Assert the output agrees,
    # because a demo whose prose contradicts its output is worse than none.
    assert "inspect() on its own returns:\n   []" in r.stdout


def test_live_checks_example_exits_2_because_some_checks_cannot_tell():
    r = run("live_checks.py")
    assert r.returncode == 2, r.stdout
    assert "UNKNOWN is not a pass" in r.stdout
    assert "??" in r.stdout


def test_claim_basis_example_shows_a_claim_going_stale_both_ways():
    r = run("claim_basis.py")
    assert r.returncode == 1, r.stdout + r.stderr

    # It must actually hold first. An example that reopens from the very start
    # demonstrates a broken checker rather than a stale claim.
    assert "HOLDS" in r.stdout

    # Both routes to staleness, not just the easy one.
    assert "1 of 2 piece(s) of evidence changed since (src/auth.py)" in r.stdout
    assert "it never looked at now exist (migrations)" in r.stdout

    # The prose promises the old basis is kept. Assert the output agrees, because
    # a demo whose narration contradicts its output is worse than no demo.
    assert "1 superseded version on record" in r.stdout


def test_coverage_example_finds_what_the_typed_audit_missed():
    r = run("coverage_ledger.py")
    assert r.returncode == 1, r.stdout + r.stderr

    # The narration's whole argument is that pass 1 looks clean. If it ever stops
    # reporting zero, the example is arguing against an output it no longer has.
    assert "4 files checked, 0 problems" in r.stdout

    # ...and that pass 2 finds a real defect in a directory pass 1 never opened.
    assert "4 of 6 directories examined" in r.stdout
    assert "missing a header: index.md" in r.stdout

    # An exclusion is printed with its measurement, so a wrong call is visible.
    assert "240" in r.stdout and ".cache" in r.stdout
