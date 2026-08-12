"""UnbackedClaims: the gate that reads a reply before it is sent."""
import pytest

from claimproof import SelftestError
from claimproof.gates import UnbackedClaims


def test_its_own_selftest_cases_all_hold():
    """The gate's shipped fixtures must agree with its behaviour, or it is broken."""
    checked = UnbackedClaims().verify()
    assert len(checked) == 25


@pytest.mark.parametrize("text", [
    "It works.",
    "Everything is fixed now.",
    "Deployed.",
    "All tests pass.",
    "The bug is fixed and it works now.",
])
def test_bare_claims_are_flagged(text):
    assert UnbackedClaims().check(text), f"should have flagged: {text!r}"


@pytest.mark.parametrize("text", [
    "It works. exit=0",
    "Ran it:\n```\n12 passed\n```\nAll tests pass.",
    "Fixed the import in core.py:41 and 12 tests now pass.",
    "This should work, but I have not run it.",
    "I think that fixes it, though I did not check.",
    "",
])
def test_backed_or_hedged_text_is_left_alone(text):
    assert UnbackedClaims().check(text) == [], f"should not have flagged: {text!r}"


def test_the_finding_says_where_and_what():
    findings = UnbackedClaims().check("line one\nAll tests pass.\nline three")
    assert len(findings) == 1
    assert findings[0].line == 2
    assert "no nearby evidence" in findings[0].message
    assert "All tests pass" in findings[0].excerpt


def test_evidence_counts_from_a_neighbouring_line_not_just_the_same_line():
    text = "Ran the suite, 12 passed.\nAll tests pass."
    assert UnbackedClaims().check(text) == []


def test_go_test_ok_line_counts_as_evidence():
    text = "ok  pkg/thing  0.42s\nAll tests pass."
    assert UnbackedClaims().check(text) == []


def test_go_test_banner_without_nearby_claim_still_flags():
    text = "ok  pkg/thing  0.42s\nanother line\nAll tests pass."
    assert UnbackedClaims(window=1).check(text)


def test_a_zero_window_only_accepts_evidence_on_the_same_line():
    text = "Ran the suite, 12 passed.\nAll tests pass."
    assert UnbackedClaims(window=0).check(text)          # neighbour no longer counts
    assert UnbackedClaims(window=0).check("All tests pass. exit=0") == []


def test_a_negative_window_is_rejected_rather_than_silently_clamped():
    with pytest.raises(ValueError):
        UnbackedClaims(window=-1)


def test_multiple_unbacked_claims_are_all_reported():
    findings = UnbackedClaims().check("It works.\n\n\n\n\n\n\nDeployed.")
    assert len(findings) == 2


def test_lowercase_pass_in_the_claim_does_not_clear_the_claim():
    """Regression. The evidence pattern once matched PASS case-insensitively, so
    the word 'pass' inside 'All tests pass' cleared its own claim and the gate
    approved every claim containing it. Caught by the mandatory must-fail case."""
    assert UnbackedClaims().check("All tests pass.")
    assert UnbackedClaims().check("Tests passed.")
    assert UnbackedClaims().check("It works, everything passes.")


def test_shouted_tool_output_still_counts_as_evidence():
    """The other half: real output shouts these tokens, and that must still clear."""
    assert UnbackedClaims().check("All tests pass.\nPASSED") == []
    assert UnbackedClaims().check("Deployed.\nOK") == []
