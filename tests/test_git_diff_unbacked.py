"""A claim that names a file must be backed by a diff that touches that file.

The gate's own `selftest_cases()` proves it in both directions and `check()`
refuses to run until they pass. These tests cover what the cases cannot: that the
gate is REACHABLE from the package root, and that its message names both the file
claimed and the files actually touched -- a finding a reader cannot act on is a
finding that gets ignored.
"""
import claimproof
from claimproof.gates import GitDiffUnbacked

STAT = " src/claimproof/parser.py | 12 ++++++------\n"
OTHER = " src/claimproof/other.py  |  4 ++--\n"


def test_it_is_exported_from_the_package_root():
    assert claimproof.GitDiffUnbacked is GitDiffUnbacked


def test_its_own_cases_pass_in_both_directions():
    GitDiffUnbacked().check("")          # raises SelftestError if either half fails


def test_a_named_fix_with_the_wrong_diff_is_refused():
    found = GitDiffUnbacked().inspect("Fixed the parser bug in parser.py.\n" + OTHER)
    assert found, "a claim naming parser.py with a diff touching other.py must be caught"
    assert "parser.py" in found[0].message
    assert "other.py" in found[0].message, "the finding must name what DID change"


def test_a_named_fix_with_the_right_diff_is_allowed():
    assert not GitDiffUnbacked().inspect("Fixed the parser bug in parser.py.\n" + STAT)


def test_a_turn_with_no_diff_is_left_to_the_other_gate():
    assert not GitDiffUnbacked().inspect("Fixed the parser bug in parser.py.")
