"""Declaring a corruption unkillable must be hard to do quietly.

A file that removes findings from your own score is the easiest way to
manufacture a good one, so these test the refusals more than the happy path.
"""
import json

import pytest

from deadcanary import equivalents
from deadcanary.equivalents import (EQUIVALENTS_NAME, InvalidDeclaration, load,
                                    partition, render_equivalents)

REPORT = {"corruptions": [
    {"name": "blank_required", "table": "raw", "column": "notes",
     "verdict": "survived", "caught_by": []},
    {"name": "drop_rows", "table": "raw", "column": "id",
     "verdict": "survived", "caught_by": []},
    {"name": "duplicate_key", "table": "raw", "column": "id",
     "verdict": "killed", "caught_by": ["unique_raw_id"]},
]}
REASON = ("notes is free text with no downstream consumer, so a null and an "
          "empty string are indistinguishable by design")


def _write(tmp_path, body):
    (tmp_path / EQUIVALENTS_NAME).write_text(json.dumps(body), encoding="utf-8")
    return tmp_path


def test_its_own_cases_hold():
    equivalents.selftest()


def test_no_file_means_no_declarations(tmp_path):
    assert load(tmp_path) == {}


def test_a_declaration_without_a_real_reason_is_refused(tmp_path):
    """Warned-about would not be enough: the reason IS the artefact."""
    _write(tmp_path, {"drop_rows on raw.id": {"why": "n/a"}})
    with pytest.raises(InvalidDeclaration) as caught:
        load(tmp_path)
    assert "no real reason" in str(caught.value)


def test_an_unreadable_file_never_reads_as_an_empty_one(tmp_path):
    (tmp_path / EQUIVALENTS_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(InvalidDeclaration):
        load(tmp_path)


def test_a_list_instead_of_an_object_is_refused(tmp_path):
    (tmp_path / EQUIVALENTS_NAME).write_text('["drop_rows on raw.id"]', encoding="utf-8")
    with pytest.raises(InvalidDeclaration):
        load(tmp_path)


def test_a_bare_string_is_accepted_as_the_reason(tmp_path):
    _write(tmp_path, {"blank_required on raw.notes": REASON})
    assert load(tmp_path)["blank_required on raw.notes"].why == REASON


def test_the_raw_count_is_always_printed_beside_the_adjusted_one(tmp_path):
    declared = load(_write(tmp_path, {"blank_required on raw.notes": {"why": REASON}}))
    text = render_equivalents(REPORT, declared)
    assert "2 corruption(s) nothing caught" in text, "the raw number must survive"
    assert "1 remain unexplained" in text


def test_only_the_declared_corruption_is_excluded(tmp_path):
    declared = load(_write(tmp_path, {"blank_required on raw.notes": {"why": REASON}}))
    escapes, excluded, stale = partition(REPORT, declared)
    assert escapes == ["drop_rows on raw.id"]
    assert len(excluded) == 1
    assert stale == []


def test_a_declaration_matching_nothing_is_reported_stale(tmp_path):
    declared = load(_write(tmp_path, {"blank_required on gone.column": {
        "why": "this column was removed from the warehouse months ago"}}))
    _, _, stale = partition(REPORT, declared)
    assert len(stale) == 1
    assert "STALE" in render_equivalents(REPORT, declared)


def test_a_caught_corruption_cannot_be_declared_away(tmp_path):
    """Excluding something a test already catches would be meaningless, and it
    must not silently remove a real catch from the matrix."""
    declared = load(_write(tmp_path, {"duplicate_key on raw.id": {
        "why": "this is caught, so declaring it equivalent should change nothing"}}))
    escapes, excluded, _ = partition(REPORT, declared)
    assert excluded == [], "only UNCAUGHT corruptions can be declared equivalent"
    assert set(escapes) == {"blank_required on raw.notes", "drop_rows on raw.id"}
