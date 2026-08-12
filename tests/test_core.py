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


class OnlyBadCases(WordGate):
    """The mirror of OnlyGoodCases, and the one nobody thinks to check.

    Proven it can fire; never shown it can stay quiet. Half a proof reads
    exactly like a whole one.
    """

    def selftest_cases(self):
        return [Case(text="this is bad", expect_flagged=True)]


class ManyBadOneGuard(WordGate):
    """The boundary: four cases it must catch, exactly one it must leave alone.

    This is the guard case for the guard-case rule itself -- the requirement
    must not fire on a gate that satisfies it.
    """

    def selftest_cases(self):
        return [
            Case(text="this is bad", expect_flagged=True),
            Case(text="BAD", expect_flagged=True),
            Case(text="also bad here", expect_flagged=True),
            Case(text="quite bad", expect_flagged=True),
            Case(text="this is fine", expect_flagged=False),
        ]


class AlwaysPasses(WordGate):
    """Looks like a gate. Never flags anything. This is the budget-hit-zero bug."""

    def inspect(self, text):
        return []


class FlagsEverything(WordGate):
    """The over-firing gate: the expensive failure, because it does not look broken.

    A gate that flags correct work reads as a discovery. It generates work that
    was never there, and once someone notices, it gets switched off -- and after
    that it catches nothing at all.
    """

    def inspect(self, text):
        return [Finding(message="contains 'bad'", line=1)]


class Explodes(WordGate):
    def inspect(self, text):
        raise ValueError("boom")


def test_a_gate_with_no_selftest_cases_is_refused():
    with pytest.raises(SelftestError, match="no selftest cases"):
        NoCases().verify()


def test_a_gate_that_only_tests_the_happy_path_is_refused():
    with pytest.raises(SelftestError, match="made to fail on purpose"):
        OnlyGoodCases().verify()


def test_a_gate_with_no_guard_case_is_refused():
    """Proven to fire is half a proof. It must also be shown to stay quiet."""
    with pytest.raises(SelftestError, match="must be a GUARD"):
        OnlyBadCases().verify()


def test_one_guard_case_among_many_bad_ones_is_enough():
    """The guard-case rule must not fire on a gate that already satisfies it."""
    assert len(ManyBadOneGuard().verify()) == 5


def test_a_gate_that_flags_correct_work_is_caught_by_its_guard_case():
    """The other half of the budget-hit-zero bug, and the costlier half."""
    with pytest.raises(SelftestError, match="expected to pass"):
        FlagsEverything().verify()


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


# --------------------------------------------------------------------------
# The library holding itself to its own rule.
# --------------------------------------------------------------------------

def _shipped_gates():
    """Every Gate the package ships, DISCOVERED rather than typed.

    A typed list is the exact bug `TypedScope` exists to flag: it silently stops
    covering the gate somebody adds next month, and nothing says so.

    `__main__` is skipped because importing it runs the demo and calls
    `sys.exit()`, which would end the test run with no traceback.
    """
    import contextlib
    import importlib
    import inspect
    import io
    import pkgutil

    import claimproof

    gates = {}
    for mod in pkgutil.iter_modules(claimproof.__path__):
        if mod.name.startswith("__"):
            continue
        with contextlib.redirect_stdout(io.StringIO()):   # demo prints on import
            m = importlib.import_module(f"claimproof.{mod.name}")
        for obj in vars(m).values():
            if (inspect.isclass(obj) and issubclass(obj, Gate) and obj is not Gate
                    and not inspect.isabstract(obj)
                    and obj.__module__.startswith("claimproof.")):
                gates[f"{obj.__module__}.{obj.__qualname__}"] = obj
    return gates


#: Refused on purpose, each with the reason on the line. Anything else that
#: cannot satisfy the contract is a bug, not an entry here.
DELIBERATELY_UNVERIFIABLE = {
    "claimproof.demo.NeverFails",       # the demo's own bad example: flags nothing
}


def test_every_gate_the_library_ships_proves_itself_in_both_directions():
    """The rule applies to us first. A library that exempts itself teaches nothing."""
    gates = _shipped_gates()
    assert gates, "discovery found no gates at all -- that is a broken test, not a clean result"

    checked, needs_arguments = [], []
    for path, cls in sorted(gates.items()):
        if path in DELIBERATELY_UNVERIFIABLE:
            continue
        try:
            gate = cls()
        except TypeError:
            needs_arguments.append(path)     # built by its own module's tests, with a fixture
            continue
        cases = gate.selftest_cases()
        assert any(c.expect_flagged for c in cases), f"{path}: no case it is required to flag"
        assert any(not c.expect_flagged for c in cases), f"{path}: no guard case to leave alone"
        gate.verify()
        checked.append(path)

    # State the denominator rather than a bare pass, and make a new unbuildable
    # gate announce itself instead of quietly falling out of coverage.
    assert needs_arguments == ["claimproof.ledger.NothingLeft"], (
        f"the set of gates this test cannot construct changed: {needs_arguments}. "
        f"Give the new one a fixture here, or it is not covered by anything."
    )
    assert len(checked) >= 3, f"only verified {checked}"


def test_findings_are_readable_without_reading_the_source():
    f = Finding(message="contains 'bad'", line=3, excerpt="this is bad")
    s = str(f)
    assert "line 3" in s and "bad" in s


def test_gate_name_defaults_to_the_class_name():
    assert WordGate().name == "WordGate"
