"""`--baseline` -- the CI ratchet, held down in both directions.

A real project's test suite grows over time. `--expect-dead N` demands an EXACT count,
so it breaks the moment anyone adds a test -- and a check that breaks on ordinary,
healthy work gets deleted, not fixed. The ratchet asks a narrower question: did
coverage get WORSE than it has ever been recorded? That is the one thing a CI gate
should actually block on.

Every case here is written the way this project holds its own gates to: at least one
the ratchet MUST catch, and at least one ordinary case it must leave alone. The second
kind matters more -- a check that fires on healthy growth is the exact failure mode
`--expect-dead` already has, and building a second copy of it would not be a fix.
"""
import json

from deadcanary.__main__ import ratchet


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_baseline_yet_is_recorded_and_passes(tmp_path):
    """A first run is not a regression. It is the thing everything else compares to."""
    path = tmp_path / "baseline.json"
    code, message = ratchet(3, path)

    assert code == 0
    assert path.is_file(), "nothing was recorded for the next run to compare against"
    assert _read(path) == {"dead_canaries": 3}
    assert "no baseline yet" in message.lower()


def test_at_or_under_the_baseline_passes_and_leaves_the_file_alone(tmp_path):
    """The guard: healthy, unchanged coverage must never fail the build."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dead_canaries": 5}), encoding="utf-8")

    code, message = ratchet(5, path)

    assert code == 0, "coverage that did not change was treated as a regression"
    assert _read(path) == {"dead_canaries": 5}, "the file moved on an unchanged run"
    assert "5" in message


def test_more_dead_canaries_than_recorded_fails(tmp_path):
    """The case the whole feature exists for: coverage genuinely got worse."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dead_canaries": 2}), encoding="utf-8")

    code, message = ratchet(6, path)

    assert code == 1
    assert _read(path) == {"dead_canaries": 2}, "a failing run rewrote the bar it failed"
    assert "worse" in message.lower()
    assert "6" in message and "2" in message


def test_fewer_dead_canaries_passes_without_update_baseline(tmp_path):
    """An improvement is not required to be captured. Only regressions must fail."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dead_canaries": 8}), encoding="utf-8")

    code, message = ratchet(3, path, update=False)

    assert code == 0
    assert _read(path) == {"dead_canaries": 8}, \
        "the file ratcheted down without being asked to -- --update-baseline is what for"


def test_fewer_dead_canaries_with_update_baseline_ratchets_down(tmp_path):
    """The one way the file is allowed to change: an explicit, genuine improvement."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dead_canaries": 8}), encoding="utf-8")

    code, message = ratchet(3, path, update=True)

    assert code == 0
    assert _read(path) == {"dead_canaries": 3}
    assert "ratcheted down" in message.lower()


def test_a_regression_never_ratchets_even_with_update_baseline(tmp_path):
    """update never means 'trust this run either way'. A regression still fails, always."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"dead_canaries": 2}), encoding="utf-8")

    code, message = ratchet(6, path, update=True)

    assert code == 1
    assert _read(path) == {"dead_canaries": 2}, \
        "--update-baseline let a WORSE run rewrite the bar -- it must only ever go down"


def test_an_unreadable_baseline_file_is_cannot_tell_not_a_pass(tmp_path):
    """Absent and fine must never look the same as broken and fine.

    A file that exists but cannot be parsed is not the same as no file at all -- treating
    it as 'no baseline yet' would silently overwrite whatever a human meant to put there.
    """
    path = tmp_path / "baseline.json"
    path.write_text("not json at all {{{", encoding="utf-8")

    code, message = ratchet(1, path)

    assert code == 2, "a broken baseline file was treated as a pass or a fresh start"
    assert path.read_text(encoding="utf-8") == "not json at all {{{", \
        "an unreadable file was overwritten instead of reported"


def test_a_baseline_file_missing_the_expected_key_is_cannot_tell(tmp_path):
    """Valid JSON, wrong shape -- still not something to guess at."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"something_else": 1}), encoding="utf-8")

    code, _ = ratchet(1, path)

    assert code == 2
