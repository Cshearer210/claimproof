"""The live-state harness. The rule under test: UNKNOWN is never a pass."""
import pytest

from claimproof.harness import BROKE, OK, UNKNOWN, Harness


def build(ok=0, broke=0, unknown=0, raises=0):
    h = Harness()
    for i in range(ok):
        h.check(f"ok{i}", "passes")(lambda: (True, "fine"))
    for i in range(broke):
        h.check(f"broke{i}", "fails")(lambda: (False, "bad"))
    for i in range(unknown):
        h.check(f"unknown{i}", "cannot tell")(lambda: (None, "no data"))
    for i in range(raises):
        h.check(f"raises{i}", "explodes")(
            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    return h


def test_all_passing_exits_zero():
    assert build(ok=3).run(echo=False) == 0


def test_anything_broken_exits_one():
    assert build(ok=3, broke=1).run(echo=False) == 1


def test_unknown_alone_exits_two_and_is_not_a_pass():
    """The central rule. A check that could not tell must not read as healthy."""
    assert build(ok=3, unknown=1).run(echo=False) == 2


def test_broken_outranks_unknown():
    assert build(broke=1, unknown=1).run(echo=False) == 1


def test_a_check_that_raises_reports_unknown_not_ok():
    results = build(raises=1).evaluate()
    assert results[0].verdict == UNKNOWN
    assert "RuntimeError" in results[0].detail


def test_verdicts_are_distinguishable():
    verdicts = [r.verdict for r in build(ok=1, broke=1, unknown=1).evaluate()]
    assert verdicts == [OK, BROKE, UNKNOWN]
    assert len(set(verdicts)) == 3


def test_an_empty_harness_is_not_a_pass_by_accident():
    """Zero checks means nothing was verified. It still exits 0, but the count is
    visible so a caller can refuse it. Recorded here so the behaviour is deliberate."""
    h = Harness()
    assert len(h) == 0
    assert h.run(echo=False) == 0


def test_duplicate_check_ids_are_refused():
    h = Harness()
    h.check("dupe", "first")(lambda: (True, ""))
    with pytest.raises(ValueError, match="duplicate"):
        h.check("dupe", "second")(lambda: (True, ""))


def test_a_check_id_is_required():
    with pytest.raises(ValueError):
        Harness().check("", "no id")(lambda: (True, ""))


def test_ids_are_listable_so_a_registry_can_be_counted():
    h = build(ok=2, broke=1)
    assert h.ids == ["ok0", "ok1", "broke0"]
    assert len(h) == 3


def test_the_harness_can_prove_itself():
    """Without this, a bug turning every check into a pass would look like health."""
    assert Harness().selftest() is True


def test_the_output_line_names_the_thing_in_plain_words():
    line = build(broke=1).evaluate()[0].line()
    assert "fails" in line and "bad" in line
