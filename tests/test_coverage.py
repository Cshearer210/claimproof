"""A count that does not carry its denominator is not a result.

The test that matters most is `test_two_of_four_examined_and_nothing_broken_is_not_a_pass`.
Every other test here exists to stop that one from being weakened.
"""
import json

import pytest

from agentattest import Harness
from agentattest.coverage import Coverage, CoverageError, Diff

MEMBERS = ["a", "b", "c", "d"]


@pytest.fixture()
def cov():
    return Coverage("nodes", lambda: list(MEMBERS))


# ------------------------------------------------------------- the core case
def test_two_of_four_examined_and_nothing_broken_is_not_a_pass(cov):
    cov.examine("a", True, "fine")
    cov.examine("b", True, "fine")

    assert cov.broke == []
    assert cov.run(echo=False) == 2, "0 broken out of half the population is not a pass"


def test_the_report_states_the_fraction_rather_than_a_bare_count(cov):
    cov.examine("a", True, "fine")
    cov.examine("b", True, "fine")

    report = cov.report()
    assert "2 of 4 nodes examined" in report
    assert "UNACCOUNTED : 2" in report
    assert "clean bill of health" in report


def test_the_report_names_the_members_nobody_looked_at(cov):
    cov.examine("a", True)
    cov.skip("b", "not in this tier", measured=0)

    report = cov.report()
    assert "? c" in report and "? d" in report


def test_the_same_zero_broken_passes_once_everything_is_accounted_for(cov):
    for m in MEMBERS:
        cov.examine(m, True, "fine")

    assert cov.run(echo=False) == 0
    assert "4 of 4 nodes examined" in cov.report()


def test_a_broken_member_exits_1_ahead_of_any_unknown(cov):
    cov.examine("a", False, "down")
    cov.examine("b", None, "cannot tell")
    cov.skip("c", "out of tier", measured=0)

    assert cov.run(echo=False) == 1, "a real failure must outrank not knowing"


def test_an_examined_member_with_no_verdict_is_unknown(cov):
    for m in MEMBERS:
        cov.examine(m, None, "the probe timed out")

    assert cov.run(echo=False) == 2
    assert "COULD NOT TELL" in cov.report()


# ---------------------------------------------- no exclusion without a measure
def test_an_exclusion_with_no_measurement_is_unknown_not_a_pass():
    cov = Coverage("dirs", lambda: ["src", "cache"])
    cov.examine("src", True, "read")
    cov.skip("cache", "it's a cache")

    assert cov.run(echo=False) == 2
    assert "NOT MEASURED" in cov.report()
    assert "guess" in cov.report()


def test_the_same_exclusion_with_a_measurement_passes_and_prints_it():
    cov = Coverage("dirs", lambda: ["src", "cache"])
    cov.examine("src", True, "read")
    cov.skip("cache", "package downloads, re-fetchable", measured=606)

    assert cov.run(echo=False) == 0
    assert "606" in cov.report()


def test_measured_zero_is_a_measurement_and_omitting_it_is_not():
    """Absent-and-fine and present-and-fine must not look the same."""
    zero = Coverage("dirs", lambda: ["src", "empty"])
    zero.examine("src", True)
    zero.skip("empty", "nothing in it", measured=0)
    assert zero.run(echo=False) == 0

    absent = Coverage("dirs", lambda: ["src", "empty"])
    absent.examine("src", True)
    absent.skip("empty", "nothing in it")
    assert absent.run(echo=False) == 2


def test_an_exclusion_with_no_reason_is_refused(cov):
    with pytest.raises(CoverageError) as exc:
        cov.skip("a", "   ")
    assert "needs a reason" in str(exc.value)


# ---------------------------------------------------- the population itself
def test_a_typed_list_as_the_population_is_refused():
    with pytest.raises(CoverageError) as exc:
        Coverage("nodes", ["a", "b"])
    assert "CALLABLE" in str(exc.value)


def test_an_empty_population_raises_rather_than_reading_as_clean():
    with pytest.raises(CoverageError) as exc:
        Coverage("nodes", lambda: []).population()
    assert "0 of 0" in str(exc.value)


def test_examining_something_outside_the_population_is_refused(cov):
    with pytest.raises(CoverageError) as exc:
        cov.examine("stranger", True)
    assert "denominator never included" in str(exc.value)


def test_recording_the_same_member_twice_is_refused(cov):
    cov.examine("a", True)
    with pytest.raises(CoverageError):
        cov.examine("a", False)
    with pytest.raises(CoverageError):
        cov.skip("a", "changed my mind", measured=0)


def test_the_denominator_is_fixed_for_the_run():
    """A population that grows mid-run must not make the report inconsistent."""
    moving = ["a", "b"]
    cov = Coverage("nodes", lambda: moving)
    for m in cov.population():
        cov.examine(m, True)

    moving.append("c")

    assert len(cov.population()) == 2
    assert cov.run(echo=False) == 0
    assert len(cov.population(refresh=True)) == 3
    assert cov.run(echo=False) == 2, "the new member is now unaccounted for"


def test_duplicates_in_discovery_are_collapsed_not_double_counted():
    cov = Coverage("nodes", lambda: ["a", "b", "a"])
    assert len(cov.population()) == 2


def test_reconciliation_is_asserted(cov):
    cov.examine("a", True)
    cov.skip("b", "out", measured=0)

    cov.reconcile()  # must not raise
    assert len(cov.examined) + len(cov.skipped) + len(cov.unaccounted) == len(cov.population())


# ------------------------------------------------------------------- diffing
def test_the_diff_reports_new_gone_and_grew():
    first = Coverage("nodes", lambda: ["a", "b"])
    first.examine("a", True, measured=10)
    first.examine("b", True, measured=10)
    snapshot = first.as_dict()

    later = Coverage("nodes", lambda: ["a", "c"])
    later.examine("a", True, measured=100)
    later.examine("c", True, measured=10)

    d = later.diff(snapshot)
    assert d.appeared == ("c",)
    assert d.vanished == ("b",)
    assert d.grew == ("a",)
    assert bool(d) is True


def test_an_unchanged_run_diffs_to_nothing():
    cov = Coverage("nodes", lambda: ["a", "b"])
    cov.examine("a", True, measured=10)
    cov.examine("b", True, measured=10)

    assert not cov.diff(cov.as_dict())


def test_grew_ignores_members_with_no_measurement_on_either_side():
    """Comparing against a missing number would invent a change."""
    first = Coverage("nodes", lambda: ["a"])
    first.examine("a", True)              # no measurement
    later = Coverage("nodes", lambda: ["a"])
    later.examine("a", True, measured=10_000)

    assert later.diff(first.as_dict()).grew == ()


def test_diffing_against_a_missing_baseline_raises(tmp_path, cov):
    cov.examine("a", True)
    for m in MEMBERS[1:]:
        cov.skip(m, "out", measured=0)

    with pytest.raises(CoverageError) as exc:
        cov.diff(tmp_path / "never-written.json")
    assert "not the same as nothing having changed" in str(exc.value)


def test_save_round_trips_through_a_real_file(tmp_path, cov):
    cov.examine("a", True, "fine", measured=3)
    for m in MEMBERS[1:]:
        cov.skip(m, "out of tier", measured=0)

    path = cov.save(tmp_path / "ledger" / "run.json")
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written["what"] == "nodes"
    assert written["discovered"] == MEMBERS
    assert not cov.diff(written)


# --------------------------------------------------------------- integration
def test_as_check_tells_a_harness_that_a_partial_scan_is_unknown(cov):
    cov.examine("a", True)
    cov.examine("b", True)

    h = Harness()
    h.check("nodes", "Every node is accounted for and healthy")(cov.as_check())

    assert h.run(echo=False) == 2


def test_as_check_says_zero_broken_means_nothing_when_most_went_unseen(cov):
    cov.examine("a", True)

    verdict, detail = cov.as_check()()
    assert verdict is None
    assert "0 broken means nothing" in detail


def test_as_check_passes_when_the_whole_population_is_accounted_for(cov):
    cov.examine("a", True)
    for m in MEMBERS[1:]:
        cov.skip(m, "out of tier", measured=0)

    h = Harness()
    h.check("nodes", "Every node is accounted for and healthy")(cov.as_check())

    assert h.run(echo=False) == 0


# ------------------------------------------------------------------ selftest
def test_selftest_passes():
    assert Coverage.selftest(echo=False) is True


def test_the_demo_command_exits_2_and_shows_both_readings():
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "agentattest.coverage"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2, r.stdout
    assert "2 nodes checked, 0 broken" in r.stdout
    assert "2 of 7 nodes examined" in r.stdout


def test_selftest_runs_as_a_command_and_exits_0():
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "agentattest.coverage", "--selftest"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SELFTEST PASS" in r.stdout
