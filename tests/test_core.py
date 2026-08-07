"""The contract tests. Every one of these describes a way a gate can be untrustworthy."""
import pytest

from claimproof import Case, Finding, Gate, SelftestError


class WordGate(Gate):
    """Flags any line containing 'bad'. Minimal, correct, honest about itself."""

    def inspect(self, text):
        return [
            Finding(message="contains 'bad'", line=i + 1, excerpt=ln.strip()[:30])
            for i, ln in enumerate(text.splitlines())
            if "bad" in ln.lower()
        ]

    def selftest_cases(self):
        return [
            Case(text="this is bad", expect_flagged=True),
            Case(text="this is fine", expect_flagged=False),
        ]


def test_a_working_gate_verifies_and_reports_what_it_checked():
    checked = WordGate().verify()
    assert len(checked) == 2


def test_it_finds_the_thing_with_line_and_excerpt():
    findings = WordGate().check("all good\nthis is bad\nfine")
    assert len(findings) == 1
    assert findings[0].line == 2
    assert "bad" in findings[0].excerpt


def test_clean_text_produces_no_findings():
    assert WordGate().check("nothing wrong here") == []


# --------------------------------------------------------------------------
# The failure modes. Each of these is a gate you should not be allowed to trust.
# --------------------------------------------------------------------------

class NoCases(WordGate):
    def selftest_cases(self):
        return []


class OnlyGoodCases(WordGate):
    """The common real-world shape: someone wrote tests, but only happy ones."""

    def selftest_cases(self):
        return [Case(text="this is fine", expect_flagged=False)]


class AlwaysPasses(WordGate):
    """Looks like a gate. Never flags anything. This is the budget-hit-zero bug."""

    def inspect(self, text):
        return []


class Explodes(WordGate):
    def inspect(self, text):
        raise ValueError("boom")


def test_a_gate_with_no_selftest_cases_is_refused():
    with pytest.raises(SelftestError, match="no selftest cases"):
        NoCases().verify()


def test_a_gate_that_only_tests_the_happy_path_is_refused():
    with pytest.raises(SelftestError, match="made to fail on purpose"):
        OnlyGoodCases().verify()


def test_a_gate_that_silently_passes_everything_is_caught():
    """The exact production failure this library was built from."""
    with pytest.raises(SelftestError, match="expected to flag"):
        AlwaysPasses().verify()


def test_a_gate_that_raises_is_a_broken_gate_not_a_clean_result():
    with pytest.raises(SelftestError, match="raised ValueError"):
        Explodes().verify()


def test_check_refuses_to_return_a_clean_result_from_an_unverified_gate():
    """inspect() alone would return [] and look like a pass. check() must not."""
    assert AlwaysPasses().inspect("this is bad") == []      # the trap
    with pytest.raises(SelftestError):
        AlwaysPasses().check("this is bad")                 # the guard


def test_findings_are_readable_without_reading_the_source():
    f = Finding(message="contains 'bad'", line=3, excerpt="this is bad")
    s = str(f)
    assert "line 3" in s and "bad" in s


def test_gate_name_defaults_to_the_class_name():
    assert WordGate().name == "WordGate"
