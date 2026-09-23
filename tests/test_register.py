"""The register: a finding stays red until something proves it is gone.

The tests that matter most are the ABSENCE ones. Closing a finding because it
stopped appearing is right when the scope was examined and wrong when it was
not, and those two look identical from outside -- which is exactly the failure
this whole library exists for.
"""
import pytest

from claimproof.core import Finding, SelftestError
from claimproof.register import (ACCEPTED, FIXED, RED, Register, RegisterError,
                                 StillRed, selftest)


def f(message, excerpt=""):
    return Finding(message, excerpt=excerpt)


# ------------------------------------------------------------- recording
def test_the_same_defect_twice_is_one_row_with_a_rising_count():
    r = Register()
    r.record("g", [f("a claim with no receipt", "all tests pass")], scope="s")
    r.record("g", [f("a claim with no receipt", "all tests pass")], scope="s")
    assert len(r.problems) == 1
    assert r.problems[0].times_seen == 2


def test_a_defect_that_moved_down_a_line_is_not_a_new_defect():
    r = Register()
    r.record("g", [Finding("x", line=3, excerpt="e")], scope="s")
    r.record("g", [Finding("x", line=99, excerpt="e")], scope="s")
    assert len(r.problems) == 1


def test_a_denominator_that_moved_is_one_defect_not_two():
    """"3 of 41 checked" and "3 of 44 checked" are the same finding."""
    r = Register()
    r.record("g", [f("only 3 of 41 checked")], scope="s")
    r.record("g", [f("only 3 of 44 checked")], scope="s")
    assert len(r.problems) == 1


def test_recording_needs_a_gate_name():
    with pytest.raises(RegisterError):
        Register().record("", [f("x")], scope="s")


# --------------------------------------------------------------- absence
def test_reconcile_closes_what_the_examined_scope_no_longer_shows():
    r = Register()
    r.record("g", [f("one"), f("two")], scope="turn-1")
    closed, _ = r.reconcile("g", [f("two")], scope="turn-1")
    assert [c.message for c in closed] == ["one"]
    assert len(r.red()) == 1


def test_reconcile_never_closes_what_it_did_not_look_at():
    """The whole point. Absent-and-fixed must not look like never-examined."""
    r = Register()
    r.record("g", [f("in scope")], scope="turn-1")
    r.record("g", [f("other scope")], scope="turn-2")
    closed, not_examined = r.reconcile("g", [], scope="turn-1")
    assert [c.message for c in closed] == ["in scope"]
    assert [e.message for e in not_examined] == ["other scope"]
    assert len(r.red()) == 1


def test_reconcile_never_closes_another_gates_findings():
    r = Register()
    r.record("gate-a", [f("from a")], scope="s")
    r.record("gate-b", [f("from b")], scope="s")
    closed, _ = r.reconcile("gate-a", [], scope="s")
    assert [c.message for c in closed] == ["from a"]
    assert [p.message for p in r.red()] == ["from b"]


def test_reconcile_refuses_to_run_without_a_scope():
    with pytest.raises(RegisterError):
        Register().reconcile("g", [], scope="")


# --------------------------------------------------------------- closing
def test_a_closed_finding_that_comes_back_goes_red_again():
    r = Register()
    r.record("g", [f("regression")], scope="s")
    r.close(r.problems[0].id, "pytest: 12 passed, the receipt is attached")
    r.record("g", [f("regression")], scope="s")
    assert r.problems[0].state == RED
    assert not r.problems[0].evidence, "a reopened finding kept its closing evidence"


@pytest.mark.parametrize("bad", ["", "   ", "fixed", "done.", "works"])
def test_closing_refuses_a_bare_claim_as_evidence(bad):
    r = Register()
    r.record("g", [f("needs proof")], scope="s")
    with pytest.raises(RegisterError):
        r.close(r.problems[0].id, bad)


def test_closing_with_real_evidence_takes_it_off_the_board():
    r = Register()
    r.record("g", [f("needs proof")], scope="s")
    r.close(r.problems[0].id, "exit=0 and the output shows 0 findings")
    assert r.red() == []
    assert r.problems[0].state == FIXED


def test_accepting_a_problem_requires_a_reason():
    r = Register()
    r.record("g", [f("known and deliberate")], scope="s")
    with pytest.raises(RegisterError):
        r.accept(r.problems[0].id, "   ")
    r.accept(r.problems[0].id, "third-party code we do not control")
    assert r.problems[0].state == ACCEPTED
    assert r.red() == []


def test_closing_an_unknown_id_is_refused_rather_than_ignored():
    with pytest.raises(RegisterError):
        Register().close("nosuchid", "real evidence here, exit=0")


# --------------------------------------------------------------- reading
def test_an_item_reported_again_and_again_is_surfaced():
    r = Register()
    for _ in range(4):
        r.record("g", [f("never fixed")], scope="s")
    assert len(r.rediscovered()) == 1
    assert r.rediscovered(at_least=9) == []
    assert "never closed" in r.report()


def test_run_exits_one_while_anything_is_red_and_zero_when_nothing_is():
    r = Register()
    assert r.run(echo=False) == 0
    r.record("g", [f("something")], scope="s")
    assert r.run(echo=False) == 1


# --------------------------------------------------------------- the disk
def test_the_board_survives_being_reopened(tmp_path):
    """Surviving the session that forgot is the entire premise."""
    p = tmp_path / "problems.json"
    a = Register(p)
    a.record("g", [f("survives a restart")], scope="s")
    b = Register(p)
    assert len(b.red()) == 1
    assert b.red()[0].id == a.problems[0].id


def test_a_corrupt_board_is_refused_rather_than_silently_replaced(tmp_path):
    """Starting fresh over the only record of what is broken is the worst option."""
    p = tmp_path / "problems.json"
    p.write_text("{not json at all")
    with pytest.raises(RegisterError):
        Register(p)


# ---------------------------------------------------------------- the gate
def test_still_red_refuses_an_all_clear_while_something_is_red():
    r = Register()
    r.record("g", [f("a claim with no receipt")], scope="s")
    found = StillRed(r).check("All clear.")
    assert found
    assert "still red" in found[0].message


def test_still_red_leaves_a_true_all_clear_alone():
    assert not StillRed(Register()).check("All clear.")


@pytest.mark.parametrize("line", [
    "Not everything is clean yet.",
    "Once everything is clean I will ship.",
    "Fixed the first finding; the other is still open.",
])
def test_a_hedged_or_partial_claim_is_not_a_total_claim(line):
    r = Register()
    r.record("g", [f("something")], scope="s")
    assert not StillRed(r).check(line)


def test_the_gate_proves_itself_against_a_fixture_not_the_live_board():
    """An empty live register must never excuse a detector that cannot detect."""
    checked = StillRed(Register()).verify()
    assert checked, "verify() returned no checked cases"


def test_the_gate_cannot_pass_while_blind():
    """Mutate the CLASS, not the instance.

    `StillRed.verify()` builds its own probe against a fixture register, so
    patching one instance's `inspect` never reaches the code being proven --
    the first version of this test passed while proving nothing, which is the
    exact shape the whole library is about.
    """

    class Blind(StillRed):
        def inspect(self, text):
            return []

    with pytest.raises(SelftestError):
        Blind(Register()).verify()


def test_the_modules_selftest_passes():
    assert selftest() == 0
