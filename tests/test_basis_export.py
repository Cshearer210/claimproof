"""The durable export, and the contract a consumer is allowed to pin.

A claim's evidence proves a file had some content. It does not say WHICH VERSION OF WHICH
REPOSITORY that content belonged to, and without that a durable receipt cannot be replayed
by anyone who was not in the room. `Candidate` is that binding and these tests are the
contract around it.

The test that matters most is `test_the_frozen_shape_has_not_drifted`. A consumer that
pins this schema is pinning a promise, and a promise with no test is a hope.

# newstore: `src/claimproof/schemas/claimproof.basis.v0.json` is a JSON SCHEMA -- a published wire
# contract with no rows, no writer and nothing appending to it. It is not a data store.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from claimproof.basis import (
    HOLDS, REOPENED, SCHEMA_VERSION, UNKNOWN,
    BasisError, Candidate, ClaimBasis, Evidence, from_export, schema, schema_path,
)

# Read through the accessor, never by path: the suite also runs against the INSTALLED
# package, where the repo root does not exist. That run is what caught the schema
# sitting outside the wheel in the first place.


@pytest.fixture()
def room(tmp_path):
    (tmp_path / "proof.txt").write_text("green\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def bound(room):
    return ClaimBasis(room / "claims.json", root=room,
                      candidate=Candidate("owner/repo", "abc123", "git-commit"))


# --------------------------------------------------------------- the binding itself

def test_a_candidate_refuses_to_be_half_a_binding():
    """'Some version of this repo' cannot be replayed, so it is not a binding."""
    with pytest.raises(BasisError):
        Candidate("", "abc123")
    with pytest.raises(BasisError):
        Candidate("owner/repo", "   ")


def test_identity_is_opaque_and_is_not_required_to_be_a_git_sha():
    """A generated snapshot is as real a candidate as a commit."""
    c = Candidate("owner/repo", "snapshot-2026-10-10-build-41", "generated-snapshot")
    assert from_export({
        "schema_version": SCHEMA_VERSION,
        "claim": {"id": "x", "state": HOLDS},
        "evidence": [{"ref": "a", "digest": "d", "kind": "value"}],
        "candidate": c.as_dict(),
    })[0] == c


def test_discover_reads_git_and_labels_a_dirty_tree_as_a_different_candidate(tmp_path):
    """A dirty tree is NOT the commit. Reporting the bare sha would bind evidence to a
    tree that never existed."""
    if not _git_available():
        pytest.skip("git is not installed")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "first")

    clean = Candidate.discover(tmp_path)
    assert clean is not None and clean.identity_kind == "git-commit"
    assert "+dirty" not in clean.identity

    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    dirty = Candidate.discover(tmp_path)
    assert dirty.identity_kind == "git-commit-dirty"
    assert dirty.identity.startswith(clean.identity + "+dirty.")

    # and two DIFFERENT dirty states of one commit are two different candidates
    (tmp_path / "a.txt").write_text("three\n", encoding="utf-8")
    assert Candidate.discover(tmp_path).identity != dirty.identity


def test_discover_returns_none_rather_than_guessing(tmp_path):
    """A fabricated candidate is worse than an absent one: a reader cannot tell it from
    a real binding."""
    assert Candidate.discover(tmp_path / "not-a-repo") is None


# --------------------------------------------------------------------- the export

def test_an_unbound_export_is_refused_not_warned_about(room):
    """The whole gap being closed is evidence that cannot say where it came from."""
    basis = ClaimBasis(room / "c.json", root=room)
    basis.record("done", evidence=["proof.txt"])
    with pytest.raises(BasisError) as exc:
        basis.export("done")
    assert "candidate" in str(exc.value)


def test_exporting_a_claim_that_does_not_exist_is_refused(bound):
    with pytest.raises(BasisError):
        bound.export("never-recorded")


def test_the_state_is_re_measured_not_read_back(bound, room):
    """A stored verdict is a verdict about the past. A consumer is asking about now."""
    bound.record("done", evidence=["proof.txt"])
    assert bound.export("done")["claim"]["state"] == HOLDS
    (room / "proof.txt").write_text("red\n", encoding="utf-8")
    assert bound.export("done")["claim"]["state"] == REOPENED


def test_unknown_is_exported_as_unknown_and_never_as_holds(bound):
    """'I could not check' must never reach a reader as 'I checked and it holds'."""
    bound.record("done", evidence=[Evidence.value("pytest", "20 passed")])
    assert bound.export("done")["claim"]["state"] == UNKNOWN
    assert bound.export("done", values={"pytest": "20 passed"})["claim"]["state"] == HOLDS


def test_export_all_says_why_a_claim_could_not_be_bound(room):
    """A silently shorter list is the shrinking denominator: 3 of 11 exported looks
    exactly like everything exported."""
    basis = ClaimBasis(room / "c.json", root=room)
    basis.record("unbound", evidence=["proof.txt"])
    basis.candidate = Candidate("owner/repo", "abc123")
    basis.record("bound", evidence=["proof.txt"])

    out = {e["claim"]["id"]: e for e in basis.export_all()}
    assert len(out) == 2, "every claim appears, exportable or not"
    assert out["bound"]["claim"]["state"] == HOLDS
    assert out["unbound"]["claim"]["state"] == "NOT_EXPORTABLE"
    assert "candidate" in out["unbound"]["why"]


def test_a_payload_round_trips(bound):
    """A contract only one side can speak is one neither side can test."""
    bound.record("done", evidence=["proof.txt"])
    payload = bound.export("done")
    candidate, claim, state = from_export(json.loads(json.dumps(payload)))
    assert candidate == Candidate("owner/repo", "abc123", "git-commit")
    assert claim.claim_id == "done" and state == HOLDS
    assert [e.ref for e in claim.evidence] == ["proof.txt"]


def test_an_unknown_schema_version_is_refused_rather_than_guessed(bound):
    with pytest.raises(BasisError) as exc:
        from_export({"schema_version": "claimproof.basis/v99", "claim": {}, "evidence": [],
                     "candidate": {"repository": "o/r", "identity": "x"}})
    assert "v99" in str(exc.value)


# ------------------------------------------------- the contract a consumer may pin

def test_the_frozen_shape_has_not_drifted(bound):
    """THE CONTRACT TEST, and the reason the rest of this file exists.

    CounterProof froze a fixture of this store because there was no contract to pin
    (hippoley, CounterProof#64, 2026-10-08). A frozen fixture on the consumer side rots
    silently when the producer changes shape -- the consumer keeps passing against a
    payload nobody emits any more. This test is the producer holding the same contract,
    so the drift fails HERE, where it can be fixed, instead of there.

    Adding a field is allowed and must not break a reader: the keys below are the floor,
    not the ceiling. REMOVING or RENAMING one is a breaking change and bumps
    SCHEMA_VERSION.
    """
    bound.record("done", evidence=["proof.txt"])
    p = bound.export("done")

    assert p["schema_version"] == "claimproof.basis/v0"
    assert set(p) >= {"schema_version", "claim", "evidence", "candidate"}
    assert set(p["claim"]) >= {"id", "state"}
    assert set(p["evidence"][0]) >= {"ref", "digest", "kind"}
    assert set(p["candidate"]) >= {"repository", "identity"}
    assert p["claim"]["state"] in {"HOLDS", "REOPENED", "UNKNOWN", "RETIRED"}
    assert p["evidence"][0]["kind"] in {"file", "value"}
    # it must survive a real JSON round trip -- no sets, no tuples, no datetimes
    assert json.loads(json.dumps(p)) == p


def test_the_schema_ships_inside_the_package(bound):
    """A contract only readable on GitHub is one a consumer infers from a sample instead."""
    assert schema_path().is_file(), (
        "the wire contract must be in the installed package, not only in the repo")
    assert schema_path().parent.parent.name == "claimproof"


def test_the_shipped_schema_describes_what_is_actually_emitted(bound):
    """A schema file that drifts from the code is worse than none: a consumer validates
    against it and believes it checked something."""
    doc = schema()
    bound.record("done", evidence=["proof.txt"])
    p = bound.export("done")

    assert doc["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    for key in doc["required"]:
        assert key in p, f"the schema requires {key!r} and the export does not emit it"
    assert set(doc["properties"]["claim"]["required"]) <= set(p["claim"])
    assert set(doc["properties"]["candidate"]["required"]) <= set(p["candidate"])
    assert p["claim"]["state"] in doc["properties"]["claim"]["properties"]["state"]["enum"]
    for item in p["evidence"]:
        assert set(doc["properties"]["evidence"]["items"]["required"]) <= set(item)


def test_the_cli_emits_the_same_payload(room):
    """Proven at the entry point, not only through the API. A library that works and a
    command that does not is a library nobody can use."""
    store = room / "c.json"
    for args in (["--record", "done", "--evidence", "proof.txt"],
                 ["--export", "done"]):
        r = subprocess.run(
            [sys.executable, "-m", "claimproof.basis", "--store", str(store),
             "--root", str(room), "--candidate-repo", "owner/repo",
             "--candidate-id", "abc123"] + args,
            capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["candidate"] == {"repository": "owner/repo", "identity": "abc123",
                                    "identity_kind": "opaque"}
    assert payload["claim"]["state"] == HOLDS


def test_half_a_candidate_on_the_cli_is_refused(room):
    r = subprocess.run(
        [sys.executable, "-m", "claimproof.basis", "--store", str(room / "c.json"),
         "--root", str(room), "--candidate-repo", "owner/repo", "--list"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "binding" in r.stderr


# ------------------------------------------------------------------ backwards safety

def test_a_store_written_before_candidates_existed_still_reads(room):
    """This is additive. An old store must not become unreadable, or the feature costs
    every existing user their history."""
    old = {"version": 1, "claims": {"legacy": {
        "claim": "written before candidates existed",
        "recorded": "2026-01-01T00:00:00Z",
        "evidence": [{"ref": "proof.txt", "digest": "x", "kind": "file"}],
        "scope": [],
    }}}
    (room / "c.json").write_text(json.dumps(old), encoding="utf-8")
    basis = ClaimBasis(room / "c.json", root=room)
    claim = basis.claims()[0]
    assert claim.claim_id == "legacy" and claim.candidate is None
    assert basis.recheck()[0].verdict in {HOLDS, REOPENED, UNKNOWN}


def test_a_claim_keeps_the_candidate_it_was_recorded_on(room):
    """Per CLAIM, not per STORE: one store accumulates claims recorded at different
    commits, and a store-level candidate would relabel the old ones."""
    basis = ClaimBasis(room / "c.json", root=room,
                       candidate=Candidate("owner/repo", "first"))
    basis.record("one", evidence=["proof.txt"])
    basis.candidate = Candidate("owner/repo", "second")
    basis.record("two", evidence=["proof.txt"])
    assert basis.export("one")["candidate"]["identity"] == "first"
    assert basis.export("two")["candidate"]["identity"] == "second"


def _git_available():
    try:
        return subprocess.run(["git", "--version"], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git(where, *args):
    subprocess.run(("git", "-C", str(where)) + args, capture_output=True,
                   text=True, timeout=60, check=True)
