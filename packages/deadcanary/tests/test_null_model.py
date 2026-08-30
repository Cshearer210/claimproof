"""`verify_kills()` -- proving a catch was not just a coin flip.

A test credited with catching a corruption is only evidence of anything if it does
not ALSO fail with no corruption applied at all. Mutation testing tools do not
normally check this, and it is exactly the kind of gap that makes a number "moved
the way you expected" the most dangerous kind of result -- it looks like a finding
and might just be a flaky test getting lucky.

`rebuild`/`get_status` are plain functions here, never a mock object, the same
reason the rest of this project avoids mocks for anything touching real
measurement: a fake that is programmed to agree with the code under test proves
nothing about whether the code is actually right.
"""
from deadcanary.hunt import verify_kills


def _fixed_status(sequence):
    """A real function returning a different, real dict each call -- not a mock."""
    calls = iter(sequence)
    def get_status():
        return next(calls)
    return get_status


def test_nothing_credited_means_no_rebuilds_and_nothing_flagged():
    """The guard: a run with no credited tests must not pay for a single clean rebuild."""
    rebuilds = []
    unreliable = verify_kills(set(), rebuild=lambda: rebuilds.append(1),
                              get_status=lambda: {"never": "called"})
    assert unreliable == set()
    assert rebuilds == [], "verify_kills rebuilt the warehouse with nothing to check"


def test_a_test_that_stays_green_on_every_clean_run_is_reliable():
    """The guard that matters most: an ordinary, working test must never be flagged."""
    status = _fixed_status([
        {"not_null_orders_id": "pass", "unique_orders_id": "pass"},
        {"not_null_orders_id": "pass", "unique_orders_id": "pass"},
    ])
    unreliable = verify_kills({"not_null_orders_id", "unique_orders_id"},
                              rebuild=lambda: None, get_status=status, repeats=2, echo=False)
    assert unreliable == set()


def test_a_test_that_fails_on_a_clean_run_is_flagged():
    """The case the whole function exists for: a credited test that is flaky."""
    status = _fixed_status([
        {"flaky_test": "fail", "solid_test": "pass"},
        {"flaky_test": "pass", "solid_test": "pass"},
    ])
    unreliable = verify_kills({"flaky_test", "solid_test"},
                              rebuild=lambda: None, get_status=status, repeats=2, echo=False)
    assert unreliable == {"flaky_test"}, \
        "a test that failed on even one clean run was not flagged"
    assert "solid_test" not in unreliable, \
        "a test that never failed on a clean run was flagged anyway"


def test_failing_once_across_the_repeats_is_enough_to_flag():
    """One clean-run failure is enough. This is a safety check, not a vote."""
    status = _fixed_status([
        {"t": "pass"},
        {"t": "pass"},
        {"t": "fail"},
    ])
    unreliable = verify_kills({"t"}, rebuild=lambda: None, get_status=status,
                              repeats=3, echo=False)
    assert unreliable == {"t"}


def test_a_failure_outside_the_credited_set_is_ignored():
    """This function answers one question about the CREDITED tests, and only that."""
    status = _fixed_status([{"credited": "pass", "somebody_else": "fail"}])
    unreliable = verify_kills({"credited"}, rebuild=lambda: None, get_status=status,
                              repeats=1, echo=False)
    assert unreliable == set(), \
        "a failure in a test nobody was crediting was treated as a problem anyway"


def test_rebuild_runs_exactly_once_per_repeat():
    """Cost is real -- exactly `repeats` clean rebuilds, no more, no fewer."""
    calls = []
    status = _fixed_status([{"t": "pass"}] * 4)
    verify_kills({"t"}, rebuild=lambda: calls.append(1), get_status=status,
                repeats=4, echo=False)
    assert len(calls) == 4
