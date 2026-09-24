"""finding: the shared contract + triangulation engine (identity / triangulate / trust / to_sarif).

finding.py is copied verbatim into all 4 portfolio repos as their one schema, yet its own logic
was barely asserted -- its selftest kills only 3/9 of its mutants (measured 2026-09-24). These
tests exercise the branches the mutants live in: the trust ladder, identity's method-independence,
the disagreement rule, and the SARIF level split."""
from claimproof.finding import (
    Finding, triangulate, method_disagreements, to_sarif, CONCEPTS,
)


def _f(method, loc="g.py:1", cls="no-clean-without-looking", concept="gate",
       both=False, conf=0.5):
    return Finding(concept, cls, loc, "signal", method=method,
                   both_directions_proven=both, confidence=conf)


def test_identity_ignores_method_but_not_location():
    a = _f("ast"); b = _f("mutation"); c = _f("ast", loc="g.py:99")
    assert a.identity() == b.identity()      # same what/where, different method -> same id
    assert a.identity() != c.identity()      # different location -> different id


def test_both_directions_defaults_false():
    # kills the mutant flipping the dataclass default (L50): a finding not proven both ways
    # must NOT read as proven.
    f = Finding("gate", "cls", "g.py:1", "signal", method="m")
    assert f.both_directions_proven is False


def test_to_json_keys_are_sorted_deterministically():
    # kills the sort_keys=True->False mutant (L69): output is key-sorted, so 'confidence'
    # (alphabetically before 'defect_class') precedes it in the string.
    s = _f("ast").to_json()
    assert s.index('"concept"') < s.index('"confidence"') < s.index('"defect_class"')


def test_identity_uses_id_key_when_present():
    a = _f("ast"); a.extra["id_key"] = "shared-content"
    b = _f("mutation", loc="other.py:5"); b.extra["id_key"] = "shared-content"
    # same defect_class + id_key collapses two different locations to one identity
    assert a.identity() == b.identity()


def test_trust_ladder_all_three_rungs():
    # >=2 methods AND both-directions -> corroborated
    corrob = triangulate([_f("ast", both=True), _f("mutation", both=True)])
    assert corrob[0].trust == "corroborated"
    assert corrob[0].corroboration == 2
    # >=2 methods, NO both-directions -> multi-method
    multi = triangulate([_f("ast"), _f("mutation")])
    assert multi[0].trust == "multi-method"
    # one method -> single-method
    single = triangulate([_f("ast")])
    assert single[0].trust == "single-method"


def test_triangulate_sorts_most_corroborated_first():
    lone = _f("ast", loc="lonely.py:1")
    pair_a = _f("ast", loc="shared.py:2"); pair_b = _f("mutation", loc="shared.py:2")
    out = triangulate([lone, pair_a, pair_b])
    assert out[0].corroboration == 2       # the 2-method defect leads
    assert out[0].location == "shared.py:2"


def test_disagreement_is_a_finding_only_when_a_different_method_clears_it():
    flag = Finding("test", "dead-canary", "t.py:1", "mutation survived", method="mutation")
    clear = Finding("test", "clean-verdict", "t.py:1", "asserts on return", method="ast")
    assert len(method_disagreements([flag, clear])) == 1
    # two flags, no clear -> agreement, not a disagreement
    assert method_disagreements([flag, _f("ast", loc="t.py:1", cls="dead-canary")]) == []
    # a method that clears its OWN flag does not count (clearers minus flaggers)
    same = Finding("test", "clean-verdict", "t.py:1", "x", method="mutation")
    assert method_disagreements([flag, same]) == []
    # ASYMMETRIC case that kills the flag/clear-swap mutant (L129): one loc flagged by A,
    # cleared by A AND B. Correct: clearers = {A,B}-{A} = {B} -> 1. Swapped roles -> 0.
    fA = Finding("test", "dead-canary", "z.py:1", "s", method="A")
    cA = Finding("test", "clean-verdict", "z.py:1", "s", method="A")
    cB = Finding("test", "clean-verdict", "z.py:1", "s", method="B")
    assert len(method_disagreements([fA, cA, cB])) == 1


def test_to_sarif_level_splits_on_trust():
    # distinct defect_class per finding so the level is attributable, killing the
    # trust==single-method -> != mutant (L151): the mapping direction must be exact.
    single = triangulate([_f("ast", cls="single-cls")])
    multi = triangulate([_f("ast", cls="multi-cls", both=True),
                         _f("mutation", cls="multi-cls", both=True)])
    sarif = to_sarif(single + multi, "claimproof")
    levels = {r["ruleId"]: r["level"] for r in sarif["runs"][0]["results"]}
    assert levels["single-cls"] == "warning"   # single-method is a lead
    assert levels["multi-cls"] == "error"      # corroborated is an error
    assert sarif["version"] == "2.1.0"


def test_concept_is_in_the_shared_contract():
    assert _f("ast").concept in CONCEPTS


def test_its_own_selftest_passes():
    from claimproof import finding
    assert not finding.selftest()
