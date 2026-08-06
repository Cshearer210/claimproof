"""A claim that was true when it was measured, and is not any more.

Every test here uses real files in a real temporary directory. The bug this
module guards against lives in reading a file and comparing it to what was read
before, so a test with a mocked filesystem would have proved nothing about it.

The test that matters most is `test_editing_the_evidence_reopens_the_claim`.
Everything else is a way for that one to stay honest.
"""
import json
import subprocess
import sys

import pytest

from agentattest import Harness
from agentattest.basis import (
    ABSENT, HOLDS, REOPENED, RETIRED, UNKNOWN,
    BasisError, ClaimBasis, Evidence, fingerprint_path, slug,
)


@pytest.fixture()
def room(tmp_path):
    (tmp_path / "proof.txt").write_text("green\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def basis(room):
    b = ClaimBasis(room / "claims.json", root=room)
    b.record("the suite passes", evidence=["proof.txt"], claim_id="suite")
    return b


# --------------------------------------------------------------- the core case
def test_unchanged_evidence_holds(basis):
    assert basis.recheck()[0].verdict == HOLDS
    assert basis.run(echo=False) == 0


def test_editing_the_evidence_reopens_the_claim(basis, room):
    (room / "proof.txt").write_text("red\n", encoding="utf-8")

    status = basis.recheck()[0]
    assert status.verdict == REOPENED
    assert status.changed == ("proof.txt",)
    assert basis.run(echo=False) == 1


def test_the_reason_names_the_file_that_moved(basis, room):
    (room / "proof.txt").write_text("red\n", encoding="utf-8")

    why = basis.recheck()[0].why()
    assert "proof.txt" in why
    assert "UNVERIFIED" in why
    # It must say what the claim WAS, or a reader cannot judge whether the
    # change matters.
    assert "the suite passes" in why


def test_rewriting_identical_bytes_is_not_a_change(basis, room):
    """Fingerprints are content, not timestamps.

    A checkout rewrites files without changing them. A checker that reopened
    every claim after a checkout would be switched off inside a week.
    """
    (room / "proof.txt").write_text("red\n", encoding="utf-8")
    assert basis.recheck()[0].verdict == REOPENED

    (room / "proof.txt").write_text("green\n", encoding="utf-8")
    assert basis.recheck()[0].verdict == HOLDS


def test_vanished_evidence_reopens(basis, room):
    (room / "proof.txt").unlink()

    status = basis.recheck()[0]
    assert status.verdict == REOPENED
    assert status.vanished == ("proof.txt",)
    assert "cannot be re-read" in status.why()


def test_a_directory_gaining_a_file_counts_as_a_change(room):
    fixtures = room / "fixtures"
    fixtures.mkdir()
    (fixtures / "one.txt").write_text("a", encoding="utf-8")

    b = ClaimBasis(root=room)
    b.record("all fixtures covered", evidence=["fixtures"], claim_id="fx")
    assert b.recheck()[0].verdict == HOLDS

    (fixtures / "two.txt").write_text("b", encoding="utf-8")
    assert b.recheck()[0].verdict == REOPENED


# ------------------------------------------------------- refusing to record
def test_recording_against_a_file_that_does_not_exist_raises(room):
    b = ClaimBasis(root=room)
    with pytest.raises(BasisError) as exc:
        b.record("built it", evidence=["nope.txt"])
    assert "does not exist" in str(exc.value)
    assert len(b) == 0, "a refused claim must not land in the store"


def test_recording_with_no_evidence_raises(room):
    with pytest.raises(BasisError) as exc:
        ClaimBasis(root=room).record("built it", evidence=[])
    assert "empty basis" in str(exc.value)


def test_recording_an_empty_claim_raises(room):
    with pytest.raises(BasisError):
        ClaimBasis(root=room).record("   ", evidence=["proof.txt"])


# ------------------------------------------------------------------- scope
def test_a_new_source_reopens_claims_recorded_before_it_existed(room):
    sources = {"logs", "tests"}
    b = ClaimBasis(root=room, scope=lambda: sorted(sources))
    b.record("nothing older than March is open", evidence=["proof.txt"], claim_id="ages")
    assert b.recheck()[0].verdict == HOLDS

    sources.add("inbox")

    status = b.recheck()[0]
    assert status.verdict == REOPENED
    assert status.appeared == ("inbox",)
    assert "never looked at" in status.why()


def test_a_source_disappearing_does_not_reopen(room):
    """Somewhere you no longer look cannot hold evidence the claim missed.

    Reopening on it would cry wolf, and a checker that cries wolf gets ignored,
    which is how the one real alarm gets missed.
    """
    sources = {"logs", "tests"}
    b = ClaimBasis(root=room, scope=lambda: sorted(sources))
    b.record("nothing older than March is open", evidence=["proof.txt"], claim_id="ages")

    sources.discard("logs")

    status = b.recheck()[0]
    assert status.verdict == HOLDS
    assert status.narrowed == ("logs",)
    assert "logs" in status.why()


def test_a_scope_that_discovers_nothing_raises(room):
    b = ClaimBasis(root=room, scope=lambda: [])
    with pytest.raises(BasisError) as exc:
        b.current_scope()
    assert "trivially" in str(exc.value)


def test_a_claim_with_a_scope_is_unknown_when_the_scope_cannot_be_seen(room):
    """Judging a scoped claim from a basis with no scope function is a guess."""
    store = room / "claims.json"
    ClaimBasis(store, root=room, scope=lambda: ["logs"]).record(
        "measured", evidence=["proof.txt"], claim_id="m")

    blind = ClaimBasis(store, root=room)  # no scope function
    status = blind.recheck()[0]
    assert status.verdict == UNKNOWN
    assert "scope" in status.unjudged
    assert blind.run(echo=False) == 2


# ------------------------------------------------------- non-file evidence
def test_evidence_we_cannot_judge_is_unknown_not_a_pass(room):
    b = ClaimBasis(root=room)
    b.record("64 tests pass", evidence=[Evidence.value("suite", "64 passed")], claim_id="t")

    assert b.recheck()[0].verdict == UNKNOWN
    assert b.run(echo=False) == 2, "UNKNOWN must not exit 0"


def test_supplying_the_same_value_holds_and_a_different_one_reopens(room):
    b = ClaimBasis(root=room)
    b.record("64 tests pass", evidence=[Evidence.value("suite", "64 passed")], claim_id="t")

    assert b.recheck({"suite": "64 passed"})[0].verdict == HOLDS
    assert b.recheck({"suite": "63 passed"})[0].verdict == REOPENED


def test_value_evidence_stores_a_fingerprint_not_the_text(room):
    """The store gets committed. Evidence text can be a log line."""
    store = room / "claims.json"
    b = ClaimBasis(store, root=room)
    b.record("done", evidence=[Evidence.value("log", "user bob@example.com ok")],
             claim_id="d")

    assert "bob@example.com" not in store.read_text(encoding="utf-8")


# ------------------------------------------------------------------ history
def test_re_measuring_keeps_the_superseded_claim(basis, room):
    """Quietly overwriting would look identical to never having been wrong."""
    (room / "proof.txt").write_text("red\n", encoding="utf-8")

    again = basis.record("the suite passes", evidence=["proof.txt"], claim_id="suite")

    assert len(again.superseded) == 1
    assert again.superseded[0]["claim"] == "the suite passes"
    assert basis.recheck()[0].verdict == HOLDS


def test_retiring_stops_the_alarm_but_keeps_the_record(basis):
    basis.retire("suite", "tracked in ROADMAP.md")

    status = basis.recheck()[0]
    assert status.verdict == RETIRED
    assert "ROADMAP.md" in status.why()
    assert basis.run(echo=False) == 0, "a retired claim must not keep failing the run"
    assert len(basis) == 1, "retiring is not deleting"


def test_retiring_with_nowhere_for_the_work_to_go_is_refused(basis):
    with pytest.raises(BasisError) as exc:
        basis.retire("suite", "")
    assert "somewhere for the work to go" in str(exc.value)


def test_retiring_an_unknown_claim_raises(basis):
    with pytest.raises(BasisError):
        basis.retire("never-recorded", "somewhere")


# -------------------------------------------------------------- the store
def test_an_empty_store_exits_2_not_0(room):
    """Nothing being watched looks identical to nothing having expired."""
    assert ClaimBasis(room / "none.json", root=room).run(echo=False) == 2


def test_a_corrupt_store_raises_rather_than_reading_as_empty(room):
    broken = room / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(BasisError) as exc:
        ClaimBasis(broken, root=room).recheck()
    assert "every claim as holding" in str(exc.value)


def test_the_store_is_valid_json_and_survives_a_reopen(basis, room):
    written = json.loads((room / "claims.json").read_text(encoding="utf-8"))
    assert written["version"] == 1
    assert written["claims"]["suite"]["claim"] == "the suite passes"

    reloaded = ClaimBasis(room / "claims.json", root=room)
    assert reloaded.recheck()[0].verdict == HOLDS


def test_a_basis_with_no_store_keeps_claims_in_memory(room):
    b = ClaimBasis(root=room)
    b.record("done", evidence=["proof.txt"], claim_id="d")
    assert len(b) == 1
    assert not list(room.glob("*.json"))


def test_recheck_returns_every_claim_not_just_the_stale_ones(room):
    """"2 reopened" means nothing without "out of how many"."""
    (room / "b.txt").write_text("b", encoding="utf-8")
    b = ClaimBasis(root=room)
    b.record("one", evidence=["proof.txt"], claim_id="one")
    b.record("two", evidence=["b.txt"], claim_id="two")

    (room / "b.txt").write_text("changed", encoding="utf-8")

    assert len(b.recheck()) == 2
    assert len(b.reopened()) == 1


# --------------------------------------------------------------- integration
def test_as_check_reports_broke_to_a_harness_when_a_claim_reopens(basis, room):
    (room / "proof.txt").write_text("red\n", encoding="utf-8")

    h = Harness()
    h.check("claims", "Every closed claim still rests on unchanged evidence")(
        basis.as_check())

    assert h.run(echo=False) == 1


def test_as_check_reports_unknown_when_nothing_is_recorded(room):
    h = Harness()
    h.check("claims", "Every closed claim still rests on unchanged evidence")(
        ClaimBasis(room / "none.json", root=room).as_check())

    assert h.run(echo=False) == 2, "nothing watched is UNKNOWN, never a pass"


def test_as_check_passes_when_everything_holds(basis):
    h = Harness()
    h.check("claims", "Every closed claim still rests on unchanged evidence")(
        basis.as_check())

    assert h.run(echo=False) == 0


# --------------------------------------------------------------- small parts
def test_fingerprint_of_a_missing_path_is_the_absent_sentinel(room):
    assert fingerprint_path(room / "nope.txt") == ABSENT


def test_slug_is_stable_and_readable():
    assert slug("Auth refactor done!") == "auth-refactor-done"
    assert slug("   ") == "claim"


def test_claim_id_defaults_to_a_slug_of_the_claim(room):
    b = ClaimBasis(root=room)
    claim = b.record("Auth refactor done", evidence=["proof.txt"])
    assert claim.claim_id == "auth-refactor-done"


# ----------------------------------------------------------------- selftest
def test_selftest_passes():
    assert ClaimBasis.selftest(echo=False) is True


def test_selftest_runs_as_a_command_and_exits_0():
    r = subprocess.run([sys.executable, "-m", "agentattest.basis", "--selftest"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SELFTEST PASS" in r.stdout


# ---------------------------------------------------------------------- CLI
def cli(*args, cwd):
    return subprocess.run([sys.executable, "-m", "agentattest.basis", *args],
                          capture_output=True, text=True, timeout=120, cwd=str(cwd))


def test_cli_records_then_reports_holding_then_reopened(room):
    r = cli("--store", "claims.json", "--record", "the suite passes",
            "--evidence", "proof.txt", cwd=room)
    assert r.returncode == 0, r.stderr
    assert "recorded the-suite-passes" in r.stdout

    r = cli("--store", "claims.json", cwd=room)
    assert r.returncode == 0, r.stdout
    assert "HOLDS" in r.stdout

    (room / "proof.txt").write_text("red\n", encoding="utf-8")
    r = cli("--store", "claims.json", cwd=room)
    assert r.returncode == 1, r.stdout
    assert "REOPENED" in r.stdout
    assert "1 REOPENED" in r.stdout


def test_cli_refuses_evidence_that_is_not_there_with_exit_2(room):
    r = cli("--store", "claims.json", "--record", "built it",
            "--evidence", "nope.txt", cwd=room)
    assert r.returncode == 2
    assert "refused" in r.stderr


def test_cli_on_an_empty_store_exits_2(room):
    r = cli("--store", "nothing.json", cwd=room)
    assert r.returncode == 2
    assert "not the same as nothing having expired" in r.stdout
