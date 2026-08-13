"""The join between the two tools, held down in both directions.

claimproof refuses a claim of success that carries no evidence a machine can
check. `deadcanary` produces exactly one kind of evidence: proof that a data test
suite can actually fail. This is where the two meet.

The claim being policed here is the one nobody questions: **"the data tests
pass."** Green is not evidence that a test works -- it is equally what a test
that cannot fail looks like, every morning, for two years.

Every case below is written the way claimproof requires its own gates to be
written: at least one the gate MUST flag, and at least one guard it must look at
and leave alone. The guards matter more. A gate that flags correct work does not
look broken, it looks like a discovery, and then it gets switched off.
"""
import json

import pytest

from deadcanary.gate import (GreenTestsUnproven, attest, recheck,
                             suite_fingerprint)

CLEAN_REPORT = {
    "project": "somewhere",
    "tests_total": 20, "tests_green": 20,
    "dead_canaries": [], "dead_canaries_provisional": [],
    "coverage_complete": True,
    "mutations_planned": 37, "mutations_applied": 37,
}

MANIFEST = {
    "nodes": {
        "test.p.not_null_orders_order_id": {
            "name": "not_null_orders_order_id", "resource_type": "test",
            "test_metadata": {"name": "not_null"}, "depends_on": {"nodes": ["model.p.orders"]},
        },
        "model.p.orders": {"name": "orders", "resource_type": "model"},
    },
    "sources": {"source.p.raw.raw_orders": {"name": "raw_orders", "meta": {}}},
    "metadata": {"generated_at": "2026-08-13T10:00:00Z", "invocation_id": "aaaa"},
}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "target").mkdir(parents=True)
    (root / "dbt_project.yml").write_text("name: p\n", encoding="utf-8")
    (root / "target" / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    return root


def _report(project, **overrides):
    body = dict(CLEAN_REPORT, **overrides)
    (project / "deadcanary-report.json").write_text(json.dumps(body), encoding="utf-8")
    return project / "deadcanary-report.json"


# --------------------------------------------------------------- the gate

def test_the_gate_proves_itself_in_both_directions():
    """claimproof refuses a gate that has only ever been shown to fire.

    This is not a formality. `Gate.verify()` raises unless the cases include
    something it must catch AND something it must leave alone, so a gate that
    cannot demonstrate both is refused before it is ever used.
    """
    assert GreenTestsUnproven().verify(), "the gate reported no checked cases"


def test_green_tests_with_nothing_proving_them_is_refused(project):
    findings = GreenTestsUnproven(project=project).inspect(
        "All 20 dbt tests pass. Data quality is covered.")
    assert findings, "an unproven green suite was allowed through"
    assert "never been proved" in str(findings[0]).lower() or "no deadcanary" in str(findings[0]).lower()


def test_a_suite_with_dead_canaries_is_refused_and_they_are_named(project):
    _report(project, dead_canaries=["unique_orders_order_id", "not_null_orders_order_id"])

    findings = GreenTestsUnproven(project=project).inspect("All 20 dbt tests pass.")

    assert findings, "a suite with two tests that cannot fail was allowed through"
    assert "unique_orders_order_id" in str(findings[0]), \
        "the reader is told there is a problem but not which test"


def test_a_partial_run_cannot_support_the_claim(project):
    """Partial coverage names no dead canaries. That is not the same as none.

    deadcanary already refuses to name dead canaries on a partial run. The
    failure this guards against is the report then being READ as a clean bill of
    health, because `dead_canaries` is an empty list either way.
    """
    _report(project, coverage_complete=False, dead_canaries=[],
            dead_canaries_provisional=["unique_orders_order_id"])

    findings = GreenTestsUnproven(project=project).inspect("dbt tests all green.")

    assert findings, "a partial measurement was accepted as proof"
    assert "partial" in str(findings[0]).lower() or "not every" in str(findings[0]).lower()


def test_a_clean_complete_run_lets_the_claim_through(project):
    """The guard that matters: when the work was actually done, say nothing."""
    _report(project)
    assert GreenTestsUnproven(project=project).inspect("All 20 dbt tests pass.") == []


def test_a_claim_about_something_else_is_not_this_gate_s_business(project):
    """No report exists here at all, and none of these may be flagged."""
    gate = GreenTestsUnproven(project=project)
    for text in [
        "All 316 unit tests pass.",
        "The build is green.",
        "dbt run failed on stg_orders.",
        "I need to find out whether the dbt tests can fail at all.",
    ]:
        assert gate.inspect(text) == [], f"flagged something unrelated: {text!r}"


def test_hedged_language_is_left_alone(project):
    """Honesty is not the thing to punish.

    claimproof leaves hedges alone on purpose: a gate that punishes admitted
    uncertainty teaches agents to be vague instead of accurate. Same rule here.
    """
    gate = GreenTestsUnproven(project=project)
    assert gate.inspect("The dbt tests should pass, but I have not checked.") == []
    assert gate.inspect("I think the data tests are fine.") == []


# ------------------------------------------------- the claim that expires

def test_a_proof_is_recorded_against_what_it_actually_proved(project, tmp_path):
    _report(project)
    store = tmp_path / "claims.json"
    basis = attest(project, store=store)

    assert len(basis) == 1
    assert recheck(project, store, echo=False) == 0, \
        "the claim did not hold the moment it was recorded"


def test_a_suite_value_nobody_supplies_is_CANNOT_TELL_not_fine(project, tmp_path):
    """Absent and fine must never look the same, and here they do not.

    The suite fingerprint is not a file, so claimproof cannot re-read it -- it
    has to be handed today's value. Left unsupplied it returns 2, cannot tell.
    That is the whole reason `recheck()` exists instead of leaving every caller
    to remember, because the one who forgets gets a clean-looking 0... which is
    exactly what would happen if this returned HOLDS.
    """
    _report(project)
    store = tmp_path / "claims.json"
    basis = attest(project, store=store)

    assert basis.run(echo=False) == 2, "an unjudgeable claim was reported as holding"
    assert recheck(project, store, echo=False) == 0


def test_re_running_dbt_does_not_reopen_the_claim(project, tmp_path):
    """The noise guard, and it is the whole reason this is not fingerprinting
    manifest.json directly.

    dbt stamps a fresh timestamp and invocation id into that file on every single
    run, so its hash changes constantly while nothing about the test suite has.
    A claim that reopens after every build is a checker crying wolf, and it gets
    switched off within a week -- claimproof's own docs say so, which makes doing
    it here inexcusable.
    """
    _report(project)
    store = tmp_path / "claims.json"
    attest(project, store=store)

    moved = dict(MANIFEST, metadata={"generated_at": "2026-08-13T18:00:00Z",
                                     "invocation_id": "bbbb"})
    (project / "target" / "manifest.json").write_text(json.dumps(moved), encoding="utf-8")

    assert recheck(project, store, echo=False) == 0,         "a rebuild that changed no test reopened the claim"


def test_adding_a_test_reopens_the_claim(project, tmp_path):
    """The case the whole loop exists for.

    deadcanary answers "can these tests fail?" for the suite as it stood. The
    moment somebody adds a test, that answer covers a suite that no longer
    exists -- and nothing anywhere would have said so.
    """
    _report(project)
    store = tmp_path / "claims.json"
    attest(project, store=store)

    grown = json.loads(json.dumps(MANIFEST))
    grown["nodes"]["test.p.unique_orders_order_id"] = {
        "name": "unique_orders_order_id", "resource_type": "test",
        "test_metadata": {"name": "unique"}, "depends_on": {"nodes": ["model.p.orders"]},
    }
    (project / "target" / "manifest.json").write_text(json.dumps(grown), encoding="utf-8")

    assert recheck(project, store, echo=False) == 1,         "a new, never-proved test did not reopen the claim"


def test_adding_a_source_reopens_the_claim(project, tmp_path):
    """A new source is new raw data nothing has ever tried to corrupt."""
    _report(project)
    store = tmp_path / "claims.json"
    attest(project, store=store)

    grown = json.loads(json.dumps(MANIFEST))
    grown["sources"]["source.p.raw.raw_items"] = {"name": "raw_items", "meta": {}}
    (project / "target" / "manifest.json").write_text(json.dumps(grown), encoding="utf-8")

    assert recheck(project, store, echo=False) == 1,         "a source nothing has corrupted did not reopen the claim"


def test_the_fingerprint_is_stable_across_key_order(project):
    """Two manifests describing the same suite must fingerprint the same.

    dbt does not promise dict ordering between versions, and a digest that moves
    when nothing did is the same cry-wolf failure as the timestamp one.
    """
    a = suite_fingerprint(MANIFEST)
    shuffled = {"sources": MANIFEST["sources"],
                "nodes": dict(reversed(list(MANIFEST["nodes"].items()))),
                "metadata": {"invocation_id": "zzzz"}}
    assert suite_fingerprint(shuffled) == a


def test_a_project_never_measured_cannot_be_attested(project, tmp_path):
    """Recording a claim with no report would create a claim nothing can re-verify."""
    with pytest.raises(FileNotFoundError):
        attest(project, store=tmp_path / "claims.json")
