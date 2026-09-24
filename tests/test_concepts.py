"""concepts: maps a function/label to the CONCEPT it is about (classify_function, build_label_map).

concepts.selftest() kills 16/18 of its own mutants (measured 2026-09-24) but no pytest test ran
it, so the suite covered this module 0%. Wire the selftest in, plus a direct behaviour assertion
on the public surface (add takes concept, name, where; concept must be a shared CONCEPT)."""
import json

from claimproof import concepts


def test_its_own_selftest_passes():
    assert not concepts.selftest()


def test_conceptmap_add_records_label_under_its_concept():
    cm = concepts.ConceptMap()
    cm.add("gate", "MyGuard", "x.py:1")
    data = json.loads(cm.to_json())
    assert "my guard" in data["labels"]["gate"]       # _norm splits camelCase to words
    assert any("MyGuard" in ex for ex in data["examples"]["gate"])
