"""Each test asked the question it exists to answer.

"This test never fired" invites the answer "nothing broke". "This test is blind
to the one thing it exists to detect" does not. These pin the second kind.

The parsing half runs against the manifest dbt really wrote for the packaged
demo -- a hand-written manifest fixture matches whatever the parser expects,
which makes it unable to fail.
"""
import json
from pathlib import Path

import pytest

from deadcanary import matrix, targeted
from deadcanary.mutations import Target
from deadcanary.targeted import aims_from_manifest, blind_to_own_purpose

DEMO = Path(targeted.__file__).parent / "_demo" / "target" / "manifest.json"
RAW = [Target("main", "raw_orders", "id", "INTEGER"),
       Target("main", "raw_orders", "status", "VARCHAR"),
       Target("main", "raw_orders", "amount", "INTEGER"),
       Target("main", "raw_orders", "customer_id", "INTEGER")]


@pytest.fixture()
def manifest():
    return json.loads(DEMO.read_text(encoding="utf-8"))


def test_its_own_cases_hold():
    targeted.selftest()
    matrix.selftest()


def test_each_test_type_gets_the_corruption_that_breaks_its_guarantee(manifest):
    by_type = {a.test_type: a for a in aims_from_manifest(manifest, RAW) if a.reachable}
    assert by_type["not_null"].mutation.name == "blank_required"
    assert by_type["accepted_values"].mutation.name == "unexpected_category"


def test_a_column_nothing_corruptible_carries_is_unreachable_not_absent(manifest):
    """The demo renames id -> order_id in its model, so the bridge cannot reach it.

    That is a real limit of matching on column NAME instead of doing lineage,
    and the honest response is to say the question could not be put -- never to
    quietly drop the test or, worse, report it as covered.
    """
    aims = aims_from_manifest(manifest, RAW)
    unreachable = [a for a in aims if not a.reachable]
    assert unreachable, "the renamed column should be unreachable"
    assert all("cannot be put to it" in a.note or "cannot be posed" in a.note
               or "no targeted corruption" in a.note for a in unreachable)


def test_an_unknown_test_type_is_reported_not_assumed_covered():
    odd = {"nodes": {"test.p.weird.1": {"resource_type": "test", "column_name": "amount",
                                        "test_metadata": {"name": "some_custom_test"}}}}
    aim = aims_from_manifest(odd, RAW)[0]
    assert not aim.reachable
    assert "no targeted corruption" in aim.note


def test_the_plan_is_the_same_every_run(manifest):
    """Two runs that cannot be compared are two runs nobody can act on."""
    a = [str(x) for x in aims_from_manifest(manifest, RAW)]
    b = [str(x) for x in aims_from_manifest(manifest, list(reversed(RAW)))]
    assert a == b


@pytest.mark.parametrize("verdict,caught,expected_blind", [
    ("killed", True, False),
    ("survived", False, True),
])
def test_blindness_is_decided_by_what_actually_happened(manifest, verdict, caught,
                                                        expected_blind):
    aim = next(a for a in aims_from_manifest(manifest, RAW)
               if a.reachable and a.test_type == "not_null")
    m = aim.mutation
    report = {"corruptions": [{"name": m.name, "table": m.target.table,
                               "column": m.target.column, "verdict": verdict,
                               "caught_by": [aim.test_id] if caught else []}]}
    assert bool(blind_to_own_purpose(report, [aim])) is expected_blind


def test_a_corruption_that_was_never_applied_is_no_verdict(manifest):
    aim = next(a for a in aims_from_manifest(manifest, RAW) if a.reachable)
    assert blind_to_own_purpose({"corruptions": []}, [aim]) == []
    noop = {"corruptions": [{"name": aim.mutation.name, "table": aim.mutation.target.table,
                             "column": aim.mutation.target.column, "verdict": "noop",
                             "caught_by": []}]}
    assert blind_to_own_purpose(noop, [aim]) == [], "a no-op was never a question"


def test_the_report_carries_the_column_type_so_nothing_has_to_guess():
    """Dropping the dtype silently disabled every type-dependent corruption --
    accepted_values simply could not be posed, and said so for the wrong reason."""
    from deadcanary.hunt import hunt  # noqa: F401  (import guards the shape below)
    import inspect
    src = inspect.getsource(__import__("deadcanary.hunt", fromlist=["hunt"]).hunt)
    assert '"dtype"' in src and '"schema"' in src


# ------------------------------- ONE DEFINITION, MANY READERS (2026-09-17)

REPORT_WITH_A_BROKEN_RUN = {"corruptions": [
    {"name": "a", "table": "raw", "column": "x", "verdict": "KILLED", "caught_by": ["t1"]},
    {"name": "b", "table": "raw", "column": "y", "verdict": "SURVIVED", "caught_by": []},
    {"name": "c", "table": "raw", "column": "z", "verdict": "BROKE-THE-RUN", "caught_by": []},
    {"name": "d", "table": "raw", "column": "w", "verdict": "NO-OP", "caught_by": []},
]}


def test_every_reader_uses_one_definition_of_applied():
    """Three modules used to answer "was this applied" privately, and two left
    BROKE out -- so a report's denominator could disagree with mutations_applied
    in the same run, silently."""
    from deadcanary.hunt import APPLIED, BROKE, KILLED, SURVIVED

    assert set(APPLIED) == {KILLED, SURVIVED, BROKE}
    km = matrix.kill_matrix(REPORT_WITH_A_BROKEN_RUN)
    assert km.measured == 3, "a no-op was never applied; a broken run was"


def test_a_broken_run_is_in_the_denominator_and_in_neither_pile():
    km = matrix.kill_matrix(REPORT_WITH_A_BROKEN_RUN)
    assert km.uncaught == ["b on raw.y"], "a broken run must not be invented as an escape"
    assert km.inconclusive == ["c on raw.z"]
    assert "BROKE THE RUN" in matrix.render_matrix(REPORT_WITH_A_BROKEN_RUN)


def test_a_broken_run_is_not_evidence_that_a_test_is_blind():
    from deadcanary.mutations import Target

    aim = targeted.Aim("test.x", "not_null", "z",
                       targeted.BY_TEST_TYPE["not_null"](Target("main", "raw", "z", "VARCHAR")))
    assert targeted.blind_to_own_purpose(REPORT_WITH_A_BROKEN_RUN, [aim]) == []
