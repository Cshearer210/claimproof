""""CI is green" is checked against what CI actually reported.

The gate's own cases prove it fires and stays quiet on receipts. These cover
the seam: that "green" has exactly one definition, that an ordinary instance
never reaches the network, and that every way a lookup can fail comes back as
unknown rather than as a pass.
"""
import json
import shutil
import subprocess
import types

import pytest

import claimproof
from claimproof import ci
from claimproof.claude_code import default_gates
from claimproof.gates import CIStatusUnbacked, _CI_GOOD


@pytest.fixture()
def stub_gh(monkeypatch):
    """Answer `gh` from a fixture. A test that reached GitHub would prove the
    network works and nothing about this code."""
    def install(payload, rc=0, stderr="", present=True):
        monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/gh" if present else None)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(
            returncode=rc, stdout=json.dumps(payload) if payload is not None else "",
            stderr=stderr))
    return install


def _runs(*pairs):
    return {"total": len(pairs),
            "runs": [{"name": n, "status": "completed" if c else "in_progress",
                      "conclusion": c} for n, c in pairs]}


def test_green_has_exactly_one_definition():
    """Two definitions of one word is the defect this library spends its time
    catching; it would be an odd thing to ship inside it."""
    assert _CI_GOOD == ci._GOOD


def test_it_is_exported_and_runs_in_the_default_set():
    assert claimproof.CIStatusUnbacked is CIStatusUnbacked
    assert "CIStatusUnbacked" in {type(g).__name__ for g in default_gates()}


def test_a_passing_run_is_green(stub_gh):
    stub_gh(_runs(("tests", "success"), ("lint", "skipped")))
    s = ci.query("o/r", "abc")
    assert s.green and s.known and s.failing == 0
    assert ci.receipt(s) == "[claimproof:ci] success o/r@abc 0/2 failing"


@pytest.mark.parametrize("payload,rc,stderr,present,why", [
    (_runs(("tests", "failure"), ("lint", "success")), 0, "", True, "a real failure"),
    (_runs(("tests", None)), 0, "", True, "still running"),
    ({"total": 0, "runs": []}, 0, "", True, "no runs reported yet"),
    (None, 1, "gh: Not Found (HTTP 404)", True, "repo does not exist"),
    (None, 0, "", False, "gh is not installed"),
    ("not json at all", 0, "", True, "unparseable response"),
])
def test_nothing_that_is_not_a_pass_reads_as_green(stub_gh, payload, rc, stderr,
                                                   present, why):
    """A lookup that failed and a suite that passed produce the same silence
    otherwise, and only one of them is good news."""
    if payload == "not json at all":
        stub_gh(None, rc=0, present=present)
        subprocess.run = lambda *a, **k: types.SimpleNamespace(
            returncode=0, stdout="{not json", stderr="")
    else:
        stub_gh(payload, rc=rc, stderr=stderr, present=present)
    assert not ci.query("o/r", "abc").green, why


def test_a_failing_receipt_refuses_a_green_claim():
    found = CIStatusUnbacked().inspect(
        "[claimproof:ci] failure o/r@a1b2c3d 3/18 failing\nCI is green.")
    assert found
    assert "3 of 18" in found[0].message


def test_an_unknown_receipt_refuses_a_green_claim():
    found = CIStatusUnbacked().inspect(
        "[claimproof:ci] unknown o/r@a1b2c3d 0/0 failing\nAll checks passed.")
    assert found, "unknown must never read as clean"
    assert "could not be determined" in found[0].message


def test_an_ordinary_instance_never_reaches_the_network(monkeypatch):
    """Its own selftest would otherwise depend on somebody's connection."""
    def explode(*a, **k):
        raise AssertionError("the gate reached the network")
    monkeypatch.setattr(subprocess, "run", explode)
    gate = CIStatusUnbacked()
    gate.check("Merging o/r@abc1234 -- all checks passed.")   # runs its own cases too


def test_the_live_path_is_used_when_a_lookup_is_wired():
    class Failing:
        repo, ref, conclusion, failing, total = "o/r", "abc1234", "failure", 2, 9
    gate = CIStatusUnbacked(lookup=lambda repo, ref: Failing())
    found = gate.inspect("Merging o/r@abc1234 now -- all checks passed.")
    assert found and "2 of 9" in found[0].message


def test_a_lookup_that_raises_does_not_take_the_turn_down():
    def boom(repo, ref):
        raise RuntimeError("network down")
    assert CIStatusUnbacked(lookup=boom).inspect("o/r@abc1234 -- CI is green.") == []
