"""`claimproof audit`: the check on the checks.

The meta-test at the bottom is the one that earns its keep -- it runs the audit
over every gate this library ships, so a gate whose proof does not depend on the
gate can never be released, however good its docstring is.
"""
import pytest

from claimproof import audit
from claimproof.audit import (BROKEN, PROVEN, UNPROVEN, GateAudit, audit_gate,
                              discover_gates, report)
from claimproof.core import Case, Finding, Gate


class Fine(Gate):
    """A real gate: the guard case is a near miss of the bad one."""

    name = "fixture-fine"

    def inspect(self, text):
        return [Finding("no receipt")] if "done, no receipt" in text else []

    def selftest_cases(self):
        return [Case("the migration is done, no receipt at all", True),
                Case("the migration is done, receipt attached", False)]


class FarGuard(Gate):
    """Fires and stays quiet -- but on text it was never going to fire on."""

    name = "fixture-far-guard"

    def inspect(self, text):
        return [Finding("x")] if "done, no receipt" in text else []

    def selftest_cases(self):
        return [Case("the migration is done, no receipt at all", True),
                Case("z", False)]


class CannotFlagItsOwnCase(Gate):
    name = "fixture-broken"

    def inspect(self, text):
        return []

    def selftest_cases(self):
        return [Case("anything", True), Case("anything else", False)]


def test_a_genuinely_proven_gate_is_reported_proven():
    r = audit_gate(Fine)
    assert r.verdict == PROVEN
    assert r.must_fire == 1 and r.guards == 1


def test_a_guard_that_proves_nothing_is_reported_unproven():
    r = audit_gate(FarGuard)
    assert r.verdict == UNPROVEN
    assert "stay quiet on text it was never going to fire on" in r.detail


def test_a_gate_that_cannot_catch_its_own_case_is_broken_not_unproven():
    """BROKEN and UNPROVEN are different repairs, so they must not collapse."""
    assert audit_gate(CannotFlagItsOwnCase).verdict == BROKEN


def test_a_gate_that_explodes_is_a_verdict_not_a_crash():
    class Explodes(Gate):
        name = "fixture-explodes"

        def inspect(self, text):
            raise RuntimeError("boom")

        def selftest_cases(self):
            return [Case("a", True), Case("b", False)]

    assert audit_gate(Explodes).verdict == BROKEN


def test_an_audit_that_found_nothing_reports_unknown_and_never_clean():
    """Empty is not a finding. A tool that looked at nothing must not pass."""
    assert report("nowhere", [], [], quiet=True) == 2


def test_an_unproven_gate_makes_the_run_exit_one():
    rows = [GateAudit("a", PROVEN, "", 2, 1, 1), GateAudit("b", UNPROVEN, "", 2, 1, 1)]
    assert report("x", rows, [], quiet=True) == 1


def test_a_module_that_could_not_be_read_is_unknown_even_when_the_rest_pass():
    rows = [GateAudit("a", PROVEN, "", 2, 1, 1)]
    assert report("x", rows, ["broken_module: ImportError: no"], quiet=True) == 2


def test_the_guard_threshold_is_load_bearing():
    """Mutate the number. A threshold nobody has moved has never been tested."""
    keep = audit.GUARD_SIMILARITY_FLOOR
    try:
        audit.GUARD_SIMILARITY_FLOOR = 0.99
        assert audit_gate(Fine).verdict == UNPROVEN, "raising the floor changed nothing"
        audit.GUARD_SIMILARITY_FLOOR = 0.0
        assert audit_gate(FarGuard).verdict == PROVEN, "lowering the floor changed nothing"
    finally:
        audit.GUARD_SIMILARITY_FLOOR = keep


def test_main_reads_its_own_argv_not_the_process_argv():
    """A function that behaves differently depending on its caller is untestable."""
    assert audit.main(["--selftest"]) == 0


def test_the_modules_selftest_passes():
    assert audit.selftest() == 0


# --------------------------------------------------------------- the meta-test
def test_every_gate_this_library_ships_survives_its_own_audit():
    """The one that matters: no weak gate can be released.

    Discovery walks the module rather than reading a list of class names, so a
    gate added next week is audited without anyone remembering to add it here.
    """
    found, problems = discover_gates("claimproof.gates")
    assert not problems, f"could not read: {problems}"
    assert len(found) >= 8, f"discovery only found {len(found)} gates"

    rows = [audit_gate(g) for g in found]
    weak = [r for r in rows if r.verdict != PROVEN]
    assert not weak, "\n".join(f"{r.name}: {r.verdict} -- {r.detail}" for r in weak)


@pytest.mark.parametrize("target", ["claimproof.gates", "claimproof"])
def test_discovery_finds_gates_by_module_and_by_package(target):
    found, problems = discover_gates(target)
    assert found, f"no gates discovered under {target}"
    assert not problems, f"could not read: {problems}"


def test_discovery_reports_an_unimportable_target_rather_than_returning_clean():
    found, problems = discover_gates("claimproof.no_such_module_at_all")
    assert found == []
    assert problems, "an unimportable target returned no gates AND no problem"


# ------------------------- what the package-wide run exposed
def test_the_audit_does_not_report_its_own_fixtures():
    """An instrument whose own test data shows up in its results is lying.

    `audit.py` defines deliberately-weak fixture gates so it can prove itself.
    A package-wide run used to audit those and report the weak one as a finding.
    """
    found, _ = discover_gates("claimproof")
    names = {g.__name__ for g in found}
    assert "_FarGuard" not in names and "_Real" not in names, (
        f"the audit is counting its own fixtures: {sorted(names)}")


def test_a_gate_may_declare_its_own_exemption_and_the_reason_is_printed():
    """A declared exemption, never a list of names nobody maintains."""

    class OnPurpose(Gate):
        name = "fixture-on-purpose"
        audit_exempt = "a demonstration of a broken gate"

        def inspect(self, text):
            return []

        def selftest_cases(self):
            return [Case("a", True), Case("b", False)]

    r = audit_gate(OnPurpose)
    assert r.verdict == audit.EXEMPT
    assert "a demonstration of a broken gate" in r.detail


def test_an_exempt_gate_does_not_make_the_run_fail():
    rows = [GateAudit("a", PROVEN, ""), GateAudit("b", audit.EXEMPT, "declared")]
    assert report("x", rows, [], quiet=True) == 0


def test_an_undeclared_broken_gate_still_fails_even_next_to_an_exempt_one():
    """The exemption must not become a way to hide a real one."""
    rows = [GateAudit("a", audit.EXEMPT, "declared"), GateAudit("b", BROKEN, "real")]
    assert report("x", rows, [], quiet=True) == 1


def test_discovering_a_package_directory_loses_no_module():
    """Loading a package file-by-file breaks its relative imports.

    `crewai.py` dropped out of the population with "attempted relative import
    with no known parent package" -- honestly reported as a floor, and still a
    hole.
    """
    import pathlib as _pl

    pkg = _pl.Path(__file__).resolve().parents[1] / "src" / "claimproof"
    if not pkg.is_dir():
        pytest.skip("repo-layout test: src/claimproof is not on disk here")
    found, problems = discover_gates(str(pkg))
    assert not problems, f"a module dropped out of the population: {problems}"
    assert {g.__name__ for g in found} >= {"UnbackedClaims", "MergeDroppedASide"}
