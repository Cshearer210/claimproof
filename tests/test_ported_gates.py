"""The three gates built from real incidents where success and failure looked alike.

Each gate's own `selftest_cases()` carries its fixtures and `verify()` runs them.
These tests cover the half a gate cannot check about itself: that its fixtures
are load-bearing, that it is exported, and that the specific incident it was
built from is still caught.
"""
import pytest

from claimproof import gates
from claimproof.core import Finding, SelftestError
from claimproof.gates import ArtifactNameMismatch, MergeDroppedASide, UnreadSource

PORTED = [MergeDroppedASide, ArtifactNameMismatch, UnreadSource]


@pytest.mark.parametrize("cls", PORTED, ids=lambda c: c.name)
def test_each_gate_proves_itself_in_both_directions(cls):
    checked = cls().verify()
    cases = cls().selftest_cases()
    assert any(c.expect_flagged for c in cases), "no case this gate must catch"
    assert any(not c.expect_flagged for c in cases), "no case it must leave alone"
    assert len(checked) == len(cases)


@pytest.mark.parametrize("cls", PORTED, ids=lambda c: c.name)
def test_the_must_fire_cases_actually_depend_on_the_gate(cls):
    """Neuter it. If the cases still pass, they were never testing anything."""
    blind = cls()
    blind.inspect = lambda text: []
    with pytest.raises(SelftestError):
        blind.verify()


@pytest.mark.parametrize("cls", PORTED, ids=lambda c: c.name)
def test_the_guard_cases_actually_depend_on_the_gate(cls):
    """Jam it open. If the cases still pass, over-firing would go unnoticed."""
    noisy = cls()
    noisy.inspect = lambda text: [Finding("mutation")]
    with pytest.raises(SelftestError):
        noisy.verify()


@pytest.mark.parametrize("cls", PORTED, ids=lambda c: c.name)
def test_each_gate_is_exported(cls):
    import claimproof

    assert cls.__name__ in gates.__all__
    assert cls.__name__ in claimproof.__all__
    assert getattr(claimproof, cls.__name__) is cls


# ------------------------------------------------------- the real incidents
def test_a_two_sided_merge_resolved_by_taking_one_side_is_refused():
    """Two machines, different edits to one file, and one push wins in silence."""
    found = MergeDroppedASide().check(
        "Merged the laptop and server copies of recall.py.\n"
        "$ git merge -X ours laptop-branch\n")
    assert found, "a one-sided resolution under a two-sided merge claim got through"
    assert "one side whole" in found[0].message


def test_a_real_merge_is_left_alone_even_when_it_mentions_the_flag():
    assert not MergeDroppedASide().check(
        "Merged the laptop and server copies. I did NOT use -X ours.\n"
        "Merge made by the 'ort' strategy.\n")


def test_a_claim_naming_one_side_is_not_a_combine_claim():
    assert not MergeDroppedASide().check(
        "Merged the pull request.\n$ git merge --ff-only feature\n")


def test_a_filename_cited_one_suffix_away_from_the_one_written_is_refused():
    """A writer and a reader disagreeing by a host suffix.

    Days of "no saved verdict yet" and dozens of unread results, with nothing
    crashing and nothing alarming -- the reader simply opened a name that had
    never existed.
    """
    found = ArtifactNameMismatch().check(
        "The results are in regression-verdict.json.\n"
        "$ python report.py --out build/regression-verdict-linux.json\n")
    assert found
    assert "two spellings" in found[0].message


def test_an_unrelated_filename_is_not_a_near_miss():
    assert not ArtifactNameMismatch().check(
        "The results are in verdict.json.\n"
        "$ python report.py --out unrelated-inventory.csv\n")


def test_a_cited_file_with_no_write_receipt_is_left_to_unbacked_claims():
    """Two gates must never report one defect twice."""
    assert not ArtifactNameMismatch().check(
        "The results are in verdict.json. I have not run anything yet.\n")


def test_a_source_that_was_only_grepped_is_not_a_source_that_was_read():
    """Two keyword searches, zero files opened, reported as having read them."""
    found = UnreadSource().check(
        "I read through PATTERNS.md and there is nothing on caching.\n"
        "PATTERNS.md:41:  cache the embedding, not the answer\n")
    assert found
    assert "only receipt for it in this turn is a search" in found[0].message


def test_saying_you_searched_is_honest_and_is_never_flagged():
    assert not UnreadSource().check(
        "I searched PATTERNS.md for caching and found nothing.\n"
        "PATTERNS.md:41:  cache the embedding, not the answer\n")


def test_a_read_claim_with_no_search_receipt_is_left_to_unbacked_claims():
    assert not UnreadSource().check("I read through PATTERNS.md.\n")


def test_opening_the_file_clears_the_read_claim():
    assert not UnreadSource().check(
        "I read through PATTERNS.md.\n"
        "$ cat PATTERNS.md\n"
        "PATTERNS.md:41:  cache the embedding, not the answer\n")
